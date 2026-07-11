#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import time
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


WEBUI_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEBUI_DIR / "static"
WORKSPACE_ROOT = WEBUI_DIR.parents[1]
FLOW_SCRIPT = Path(os.environ.get("SAGE_FLOW_SCRIPT", str(WORKSPACE_ROOT / "sage" / "scripts" / "run_tree_sage_scene.py"))).expanduser()
TEXT_FLOW_SCRIPT = Path(os.environ.get("SAGE_TEXT_FLOW_SCRIPT", str(WORKSPACE_ROOT / "sage" / "scripts" / "run_tree_sage_text_scene.py"))).expanduser()
FLOW_PYTHON = Path(os.environ.get("SAGE_FLOW_PYTHON", "/data/xy/SAGE_repro/venv/bin/python")).expanduser()
DEFAULT_WEBUI_DATA_ROOT = Path(os.environ.get("SAGE_WEBUI_DATA_ROOT", "/data/xy/SAGE_runs/webui")).resolve()
JOBS_DIR = Path(os.environ.get("SAGE_WEBUI_JOBS_DIR", str(DEFAULT_WEBUI_DATA_ROOT / "jobs"))).resolve()
DEFAULT_OUTPUT_ROOT = Path(os.environ.get("SAGE_WEBUI_OUTPUT_ROOT", str(DEFAULT_WEBUI_DATA_ROOT / "runs"))).resolve()
DEFAULT_ASSET_SOURCE_ROOT = Path(os.environ.get("SAGE_WEBUI_ASSET_SOURCE_ROOT", str(DEFAULT_WEBUI_DATA_ROOT / "source_images"))).resolve()

RUNNING_PROCS: dict[str, subprocess.Popen[bytes]] = {}


def utc_stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sanitize_label(value: Any, fallback: str = "scene") -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    text = text.strip("._-")
    return text[:80] or fallback


def json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def read_json_file(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(json_bytes(payload))
    tmp.replace(path)


def job_file(job_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", job_id):
        raise ValueError("invalid job id")
    return JOBS_DIR / f"{job_id}.json"


def command_preview(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def bool_payload(payload: dict[str, Any], key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def int_payload(payload: dict[str, Any], key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(payload.get(key, default))
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def float_payload(payload: dict[str, Any], key: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(payload.get(key, default))
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def build_flow_plan(payload: dict[str, Any], job_id: str | None = None) -> dict[str, Any]:
    mode = str(payload.get("mode") or "image_to_scene")
    asset_strategy = str(payload.get("assetStrategy") or "generate_from_scratch")
    scene_name = sanitize_label(payload.get("sceneName"), fallback=mode)
    output_root = Path(str(payload.get("outputRoot") or DEFAULT_OUTPUT_ROOT)).expanduser()
    output_dir = output_root / f"{scene_name}_{job_id}" if job_id else output_root / f"{scene_name}_<job_id>"
    warnings: list[str] = []
    reserved: list[str] = []

    if mode == "text_to_scene":
        text_prompt = str(payload.get("textPrompt") or payload.get("prompt") or "").strip()
        if not text_prompt:
            warnings.append("缺少 textPrompt；运行文生场景前必须填写文本 prompt。")
        command = [
            str(FLOW_PYTHON),
            str(TEXT_FLOW_SCRIPT),
            "--prompt",
            text_prompt or "<text-prompt>",
            "--output-dir",
            str(output_dir),
            "--asset-strategy",
            asset_strategy,
            "--asset-pipeline",
            "asset_library" if asset_strategy == "asset_library" else "source_images",
            "--candidate-count",
            str(int_payload(payload, "candidateCount", 3, 1, 8)),
            "--room-texture-search",
            "--trellis-pipeline-type",
            str(payload.get("trellisPipelineType") or "512"),
            "--texture-size",
            str(int_payload(payload, "textureSize", 1024, 256, 4096)),
            "--decimation-target",
            str(int_payload(payload, "decimationTarget", 120000, 10000, 1000000)),
            "--assemble-scene",
        ]
        if bool_payload(payload, "trellisPreprocessImage", True):
            command.append("--trellis-preprocess-image")
        else:
            command.append("--no-trellis-preprocess-image")
        raw_room_type = str(payload.get("roomType") or "").strip()
        room_aliases = {
            "bedroom": "bedroom",
            "bed room": "bedroom",
            "卧室": "bedroom",
            "主卧": "bedroom",
            "living_room": "living_room",
            "living room": "living_room",
            "客厅": "living_room",
            "起居室": "living_room",
            "study": "study",
            "office": "study",
            "书房": "study",
            "办公室": "study",
        }
        room_type = room_aliases.get(raw_room_type.lower(), raw_room_type.lower().replace(" ", "_"))
        if room_type:
            if room_type in {"bedroom", "living_room", "study"}:
                command.extend(["--room-type", room_type])
            else:
                warnings.append(f"未知房间类型 {raw_room_type!r}，将由文生 brief 自动判断。")
        style = str(payload.get("styleConstraints") or "").strip()
        if style:
            command.extend(["--style", style])
        human_constraints = str(payload.get("humanConstraintsFile") or "").strip()
        if human_constraints:
            command.extend(["--human-constraints-file", human_constraints])
        if bool_payload(payload, "useCritic", True):
            command.append("--layout-critic")
        else:
            command.append("--no-layout-critic")
        if asset_strategy == "asset_library":
            trellis_library = str(payload.get("trellisAssetLibraryDir") or "").strip()
            alias_file = str(payload.get("reuseAssetAliasFile") or "").strip()
            articulated_library = str(payload.get("articulatedAssetLibraryDir") or "").strip()
            if trellis_library:
                command.extend(["--trellis-asset-library-dir", trellis_library])
            else:
                warnings.append("选择了资产库模式，但未填写 Trellis2 rigid asset library 路径。")
            if alias_file:
                command.extend(["--reuse-asset-alias-file", alias_file])
            if articulated_library:
                command.extend(["--articulated-asset-library-dir", articulated_library])
                reserved.append("articulated_asset_library")
        else:
            source_image_dir = str(payload.get("assetSourceImageDir") or "").strip()
            if source_image_dir:
                command.extend(["--asset-source-image-dir", source_image_dir])
                command.append("--asset-source-image-required")
                command.append("--asset-source-image-qa-strict")
            else:
                command.extend(["--asset-source-image-dir", "<asset-source-image-dir>"])
                warnings.append("文生场景从 0 生成资产需要先提供 image2 单物体图目录；不会自动回退到 Flux。")
            reserved.append("image2_source_image_generation")
        return {
            "mode": mode,
            "implemented": True,
            "assetStrategy": asset_strategy,
            "command": command,
            "outputDir": str(output_dir),
            "warnings": warnings,
            "reservedInterfaces": reserved,
        }

    reference_image = str(payload.get("referenceImage") or "").strip()
    if not reference_image:
        warnings.append("缺少 referenceImage；运行图生场景前必须填写参考图路径。")

    command = [
        str(FLOW_PYTHON),
        str(FLOW_SCRIPT),
        "--flux-image",
        reference_image or "<reference-image>",
        "--output-dir",
        str(output_dir),
        "--no-layout-template-context",
        "--trellis-pipeline-type",
        str(payload.get("trellisPipelineType") or "512"),
        "--texture-size",
        str(int_payload(payload, "textureSize", 1024, 256, 4096)),
        "--decimation-target",
        str(int_payload(payload, "decimationTarget", 120000, 10000, 1000000)),
    ]

    prompt = str(payload.get("prompt") or "").strip()
    if prompt:
        command.extend(["--prompt", prompt])

    if bool_payload(payload, "trellisPreprocessImage", True):
        command.append("--trellis-preprocess-image")
    else:
        command.append("--no-trellis-preprocess-image")

    if bool_payload(payload, "useCritic", True):
        command.append("--final-visual-critic-agent")
        command.extend(["--final-visual-critic-max-iterations", str(int_payload(payload, "criticIterations", 3, 0, 8))])
        command.extend(["--final-visual-critic-accept-score", str(float_payload(payload, "criticAcceptScore", 0.72, 0.0, 1.0))])
    else:
        command.append("--no-final-visual-critic-agent")

    asset_source_dir = str(payload.get("assetSourceImageDir") or "").strip()
    if asset_source_dir:
        command.extend(["--asset-source-image-dir", asset_source_dir])
    elif asset_strategy == "generate_from_scratch":
        warnings.append("未填写 image2 物体图目录；如果流程没有提前生成 source_images，Trellis2 资产生成会缺少输入。")

    human_constraints = str(payload.get("humanConstraintsFile") or "").strip()
    if human_constraints:
        command.extend(["--human-constraints-file", human_constraints])

    if asset_strategy == "asset_library":
        trellis_library = str(payload.get("trellisAssetLibraryDir") or "").strip()
        alias_file = str(payload.get("reuseAssetAliasFile") or "").strip()
        if trellis_library:
            command.extend(["--reuse-asset-dir", trellis_library])
            command.append("--partial-reuse-assets")
            if bool_payload(payload, "copyReusedAssets", True):
                command.append("--copy-reused-assets")
        else:
            warnings.append("选择了资产库模式，但未填写 Trellis2 rigid asset library 路径。")
        if alias_file:
            command.extend(["--reuse-asset-alias-file", alias_file])
        articulated_library = str(payload.get("articulatedAssetLibraryDir") or "").strip()
        if articulated_library:
            reserved.append("articulated_asset_library")
            warnings.append("铰接物体资产库字段已写入任务，但当前主流程还未接入该数据库。")

    if bool_payload(payload, "planOnly", False):
        command.append("--plan-only")

    if bool_payload(payload, "wholeWindowCurtainCluster", False):
        reserved.append("whole_window_curtain_cluster_asset")
        warnings.append("整体窗帘-窗户团簇资产接口已预留；当前稳定流程仍使用确定性窗帘簇 solver。")

    return {
        "mode": mode,
        "implemented": True,
        "assetStrategy": asset_strategy,
        "command": command,
            "outputDir": str(output_dir),
            "warnings": warnings,
            "reservedInterfaces": reserved,
    }


def refresh_job(job: dict[str, Any]) -> dict[str, Any]:
    job_id = str(job.get("id") or "")
    proc = RUNNING_PROCS.get(job_id)
    if proc is not None:
        code = proc.poll()
        if code is None:
            job["status"] = "running"
        else:
            job["status"] = "succeeded" if code == 0 else "failed"
            job["returnCode"] = code
            job["finishedAt"] = job.get("finishedAt") or utc_stamp()
            RUNNING_PROCS.pop(job_id, None)
            write_json_file(job_file(job_id), job)
    elif job.get("status") == "running" and job.get("pid"):
        try:
            os.kill(int(job["pid"]), 0)
            job["status"] = "running_external"
        except OSError:
            job["status"] = "unknown_after_server_restart"
            job["finishedAt"] = job.get("finishedAt") or utc_stamp()
            write_json_file(job_file(job_id), job)
    return job


def start_job(job: dict[str, Any]) -> dict[str, Any]:
    command = job.get("plan", {}).get("command")
    if not isinstance(command, list) or not command:
        job["status"] = "blocked"
        job.setdefault("warnings", []).append("No runnable command is available for this job.")
        return job
    if "<reference-image>" in command:
        job["status"] = "blocked"
        job.setdefault("warnings", []).append("Reference image path is missing.")
        return job
    if "<text-prompt>" in command:
        job["status"] = "blocked"
        job.setdefault("warnings", []).append("Text prompt is missing.")
        return job
    if "<asset-source-image-dir>" in command:
        job["status"] = "blocked"
        job.setdefault("warnings", []).append("image2 source image directory is missing.")
        return job

    log_dir = JOBS_DIR / str(job["id"])
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / "stdout.log"
    stderr_path = log_dir / "stderr.log"
    stdout = stdout_path.open("ab")
    stderr = stderr_path.open("ab")
    proc = subprocess.Popen(
        [str(part) for part in command],
        cwd=str(WORKSPACE_ROOT),
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
    )
    RUNNING_PROCS[str(job["id"])] = proc
    job["status"] = "running"
    job["pid"] = proc.pid
    job["logs"] = {"stdout": str(stdout_path), "stderr": str(stderr_path)}
    job["startedAt"] = utc_stamp()
    return job


def config_payload() -> dict[str, Any]:
    return {
        "app": "TreeSAGE Local Control",
        "modes": [
            {"id": "image_to_scene", "label": "图生场景", "enabled": True},
            {"id": "text_to_scene", "label": "文生场景", "enabled": True, "status": "mvp"},
        ],
        "assetStrategies": [
            {"id": "generate_from_scratch", "label": "从 0 生成资产", "enabled": True},
            {"id": "asset_library", "label": "调用资产库", "enabled": True},
        ],
        "defaults": {
            "flowPython": str(FLOW_PYTHON),
            "flowScript": str(FLOW_SCRIPT),
            "textFlowScript": str(TEXT_FLOW_SCRIPT),
            "outputRoot": str(DEFAULT_OUTPUT_ROOT),
            "assetSourceRoot": str(DEFAULT_ASSET_SOURCE_ROOT),
            "trellisPipelineType": "512",
            "trellisPreprocessImage": True,
            "roomTextureSearch": True,
            "textureSize": 1024,
            "decimationTarget": 120000,
            "criticIterations": 3,
            "candidateCount": 3,
            "criticAcceptScore": 0.72,
        },
        "databaseHooks": {
            "trellisRigidAssets": {"connected": False, "field": "trellisAssetLibraryDir"},
            "articulatedAssets": {"connected": False, "field": "articulatedAssetLibraryDir"},
        },
        "api": [
            "GET /api/config",
            "POST /api/jobs/preview",
            "POST /api/jobs",
            "GET /api/jobs",
            "GET /api/jobs/{id}",
            "POST /api/jobs/{id}/cancel",
        ],
    }


class SageWebHandler(SimpleHTTPRequestHandler):
    server_version = "TreeSAGEWebUI/0.1"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def send_json(self, payload: Any, status: int = 200) -> None:
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/config":
                self.send_json(config_payload())
                return
            if path == "/api/jobs":
                JOBS_DIR.mkdir(parents=True, exist_ok=True)
                jobs = []
                for item in sorted(JOBS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                    job = refresh_job(read_json_file(item, {}))
                    if isinstance(job, dict):
                        jobs.append(job)
                self.send_json({"jobs": jobs[:80]})
                return
            if path.startswith("/api/jobs/"):
                job_id = path.rsplit("/", 1)[-1]
                job = read_json_file(job_file(job_id), None)
                if not isinstance(job, dict):
                    self.send_json({"error": "job not found"}, HTTPStatus.NOT_FOUND)
                    return
                self.send_json(refresh_job(job))
                return
            if path == "/":
                self.path = "/index.html"
            super().do_GET()
        except Exception as exc:
            self.send_json({"error": f"{type(exc).__name__}: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/jobs/preview":
                payload = self.read_json()
                self.send_json({"plan": build_flow_plan(payload)})
                return
            if path == "/api/jobs":
                payload = self.read_json()
                job_id = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
                plan = build_flow_plan(payload, job_id=job_id)
                job = {
                    "id": job_id,
                    "status": "created" if plan.get("implemented") else "reserved",
                    "createdAt": utc_stamp(),
                    "payload": payload,
                    "plan": plan,
                    "warnings": plan.get("warnings", []),
                }
                if bool_payload(payload, "runNow", False) and plan.get("implemented"):
                    job = start_job(job)
                write_json_file(job_file(job_id), job)
                self.send_json(job, HTTPStatus.CREATED)
                return
            if path.startswith("/api/jobs/") and path.endswith("/cancel"):
                job_id = path.split("/")[-2]
                job = read_json_file(job_file(job_id), None)
                if not isinstance(job, dict):
                    self.send_json({"error": "job not found"}, HTTPStatus.NOT_FOUND)
                    return
                proc = RUNNING_PROCS.get(job_id)
                if proc is not None and proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGTERM)
                    job["status"] = "cancelled"
                    job["finishedAt"] = utc_stamp()
                    RUNNING_PROCS.pop(job_id, None)
                else:
                    job["status"] = "cancel_requested"
                write_json_file(job_file(job_id), job)
                self.send_json(job)
                return
            self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_json({"error": f"{type(exc).__name__}: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)


def main() -> None:
    parser = argparse.ArgumentParser(description="TreeSAGE local web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), SageWebHandler)
    print(f"TreeSAGE Web UI: http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
