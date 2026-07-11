from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from run_selfmade_trellis_scene import (
    RETRYABLE_JOB_POLL_ERRORS,
    assemble_scene_blender,
    generate_asset,
    get_job,
    post_json,
    _open_url_no_proxy_for_loopback,
)

from .io import write_json


def _trellis_healthy(trellis_url: str, timeout: float = 3.0) -> bool:
    try:
        with _open_url_no_proxy_for_loopback(trellis_url.rstrip("/") + "/health", timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def _load_aliases(alias_file: Path | None) -> dict[str, str]:
    if not alias_file:
        return {}
    raw = json.loads(alias_file.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        if isinstance(raw.get("aliases"), dict):
            return {str(key): str(value) for key, value in raw["aliases"].items()}
        return {str(key): str(value) for key, value in raw.items() if isinstance(value, str)}
    return {}


def _resolve_library_asset(
    object_id: str,
    library_dir: Path,
    aliases: dict[str, str],
) -> Path | None:
    alias = aliases.get(object_id, object_id)
    candidates = [
        Path(alias),
        library_dir / f"{alias}.glb",
        library_dir / alias,
        library_dir / object_id / f"{object_id}.glb",
        library_dir / object_id / "asset.glb",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def write_asset_plan(plan: dict[str, Any], output_dir: Path, requested_pipeline: str, resolved_pipeline: str) -> dict[str, Any]:
    items = []
    for obj in plan.get("objects", []):
        if not isinstance(obj, dict):
            continue
        items.append(
            {
                "id": obj.get("id"),
                "category": obj.get("category"),
                "asset_prompt": obj.get("asset_prompt"),
                "requested_pipeline": requested_pipeline,
                "resolved_pipeline": resolved_pipeline,
                "placement_type": obj.get("placement_type"),
            }
        )
    report = {
        "schema": "tree_sage_text_asset_plan_v1",
        "requested_pipeline": requested_pipeline,
        "resolved_pipeline": resolved_pipeline,
        "object_count": len(items),
        "objects": items,
    }
    write_json(output_dir / "text_scene_asset_plan.json", report)
    return report


SOURCE_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


def _asset_source_image_path(source_dir: Path, obj: dict[str, Any]) -> Path | None:
    object_id = str(obj.get("id") or "").strip()
    if not object_id:
        return None
    for suffix in SOURCE_IMAGE_EXTENSIONS:
        candidate = source_dir / f"{object_id}{suffix}"
        if candidate.exists():
            return candidate
    return source_dir / f"{object_id}.png"


def analyze_asset_source_image(path: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "ok": False,
        "warnings": [],
    }
    if not path.exists():
        report["warnings"].append("missing_source_image")
        return report
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        arr = np.asarray(rgb, dtype=np.int16)
    h, w = arr.shape[:2]
    report["size"] = [int(w), int(h)]
    border_width = max(2, min(24, h // 12, w // 12))
    border = np.concatenate(
        [
            arr[:border_width].reshape(-1, 3),
            arr[-border_width:].reshape(-1, 3),
            arr[:, :border_width].reshape(-1, 3),
            arr[:, -border_width:].reshape(-1, 3),
        ],
        axis=0,
    )
    bg = np.median(border, axis=0)
    dist = np.abs(arr - bg).mean(axis=2)
    border_dist = np.abs(border - bg).mean(axis=1)
    subject = dist > 35.0
    ys, xs = np.where(subject)
    report["background_rgb_median"] = [int(round(float(v))) for v in bg]
    report["border_background_ratio_d25"] = round(float((border_dist < 25.0).mean()), 6)
    report["subject_ratio"] = round(float(subject.mean()), 6)
    if len(xs):
        bbox = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
        report["subject_bbox_xyxy"] = bbox
        report["subject_padding_ltrb"] = [bbox[0], bbox[1], w - 1 - bbox[2], h - 1 - bbox[3]]
    else:
        report["subject_bbox_xyxy"] = None
        report["subject_padding_ltrb"] = [0, 0, 0, 0]
        report["warnings"].append("no_foreground_detected_against_border_background")
    if w < 512 or h < 512:
        report["warnings"].append("source_image_resolution_below_512")
    if float(report["border_background_ratio_d25"]) < 0.72:
        report["warnings"].append("border_background_not_flat_or_object_touches_edges")
    subject_ratio = float(report["subject_ratio"])
    if subject_ratio < 0.025:
        report["warnings"].append("foreground_subject_too_small_or_missing")
    if subject_ratio > 0.88:
        report["warnings"].append("foreground_subject_too_large_or_background_not_separable")
    padding = report.get("subject_padding_ltrb") if isinstance(report.get("subject_padding_ltrb"), list) else []
    if padding and min(int(v) for v in padding) < 6:
        report["warnings"].append("foreground_touches_image_edge_or_has_too_little_padding")
    blocking = {
        "missing_source_image",
        "no_foreground_detected_against_border_background",
        "foreground_subject_too_small_or_missing",
        "foreground_subject_too_large_or_background_not_separable",
    }
    report["ok"] = not any(warning in blocking for warning in report["warnings"])
    return report


def write_asset_source_image_qa_report(
    plan: dict[str, Any],
    output_dir: Path,
    source_dir: Path | None,
    *,
    required: bool,
    qa_strict: bool,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": "tree_sage_text_asset_source_image_qa_v1",
        "enabled": bool(source_dir),
        "source_dir": str(source_dir) if source_dir else None,
        "required": required,
        "qa_strict": qa_strict,
        "objects": [],
        "missing": [],
        "failed": [],
        "ok": True,
    }
    if not source_dir:
        report["ok"] = not required
        if required:
            report["reason"] = "missing_asset_source_image_dir"
        write_json(output_dir / "text_scene_asset_source_image_qa_report.json", report)
        return report
    for obj in plan.get("objects", []):
        if not isinstance(obj, dict) or not obj.get("id"):
            continue
        path = _asset_source_image_path(source_dir, obj)
        qa = analyze_asset_source_image(path) if path else {"exists": False, "ok": False, "warnings": ["missing_source_image"]}
        item = {
            "id": str(obj.get("id")),
            "category": obj.get("category"),
            "source_image": str(path) if path else None,
            "qa": qa,
        }
        report["objects"].append(item)
        if not qa.get("exists"):
            report["missing"].append(str(obj.get("id")))
        elif not qa.get("ok"):
            report["failed"].append({"id": str(obj.get("id")), "warnings": qa.get("warnings", [])})
    required_missing = bool(report["missing"]) and required
    strict_failed = bool(report["failed"]) and qa_strict
    report["ok"] = not required_missing and not strict_failed
    if required_missing:
        report["reason"] = "missing_required_asset_source_images"
    elif strict_failed:
        report["reason"] = "asset_source_image_qa_failed"
    write_json(output_dir / "text_scene_asset_source_image_qa_report.json", report)
    return report


def generate_asset_from_source_image(
    trellis_url: str,
    obj: dict[str, Any],
    source_image: Path,
    asset_dir: Path,
    *,
    seed: int,
    timeout: float,
    steps: int,
    texture_size: int,
    decimation_target: int,
    pipeline_type: str,
    preprocess_image: bool,
    force: bool,
    qa_strict: bool,
) -> Path:
    asset_dir.mkdir(parents=True, exist_ok=True)
    object_id = str(obj["id"])
    out_path = asset_dir / f"{object_id}.glb"
    meta_path = asset_dir / f"{object_id}.json"
    if out_path.exists() and meta_path.exists() and not force:
        return out_path
    qa = analyze_asset_source_image(source_image)
    if qa_strict and not qa.get("ok"):
        write_json(
            meta_path,
            {
                "source": "tree_sage_text_trellis2_from_image2_source_image",
                "status": "pre_trellis_image_qa_failed",
                "object": obj,
                "asset_path": str(out_path),
                "asset_source_image": str(source_image),
                "pre_trellis_image_qa": qa,
            },
        )
        raise ValueError(f"pre-Trellis source-image QA failed for {object_id}: {qa.get('warnings')}")
    request_payload = {
        "input_text": obj["asset_prompt"],
        "reference_image_path": str(source_image.resolve()),
        "seed": seed,
        "pipeline_type": pipeline_type,
        "preprocess_image": preprocess_image,
        "sparse_steps": steps,
        "shape_steps": steps,
        "tex_steps": steps,
        "texture_size": texture_size,
        "decimation_target": decimation_target,
        "simplify_limit": 1048576,
    }
    deadline = time.time() + timeout
    while True:
        try:
            status, payload = post_json(trellis_url.rstrip("/") + "/generate", request_payload, timeout=30.0)
            break
        except RETRYABLE_JOB_POLL_ERRORS as exc:
            if time.time() >= deadline:
                raise RuntimeError(f"Trellis2 did not accept image-source job for {object_id}: {exc}") from exc
            time.sleep(5.0)
    if status != 202:
        raise RuntimeError(f"Trellis2 server returned {status} for image-source asset {object_id}: {payload}")
    job_id = str(payload["job_id"])
    bridge_metadata = None
    while time.time() < deadline:
        try:
            status, body, content_type = get_job(trellis_url.rstrip("/") + f"/job/{job_id}", timeout=60.0)
        except RETRYABLE_JOB_POLL_ERRORS:
            time.sleep(2.0)
            continue
        if status == 200:
            out_path.write_bytes(body)
            try:
                metadata_status, metadata_body, _ = get_job(trellis_url.rstrip("/") + f"/job/{job_id}/metadata", timeout=60.0)
            except RETRYABLE_JOB_POLL_ERRORS:
                metadata_status, metadata_body = 0, b""
            if metadata_status == 200:
                try:
                    bridge_metadata = json.loads(metadata_body.decode("utf-8"))
                except Exception as exc:
                    bridge_metadata = {"metadata_parse_error": str(exc)}
            write_json(
                meta_path,
                {
                    "source": "tree_sage_text_trellis2_from_image2_source_image",
                    "job_id": job_id,
                    "object": obj,
                    "asset_path": str(out_path),
                    "content_type": content_type,
                    "asset_source_image": str(source_image),
                    "pre_trellis_image_qa": qa,
                    "trellis_request_payload": request_payload,
                    "bridge_metadata": bridge_metadata,
                },
            )
            return out_path
        if status == 500:
            write_json(
                meta_path,
                {
                    "source": "tree_sage_text_trellis2_from_image2_source_image",
                    "status": "failed",
                    "job_id": job_id,
                    "object": obj,
                    "asset_path": str(out_path),
                    "asset_source_image": str(source_image),
                    "pre_trellis_image_qa": qa,
                    "server_error": body.decode("utf-8", errors="replace"),
                    "bridge_metadata": bridge_metadata,
                },
            )
            raise RuntimeError(body.decode("utf-8", errors="replace"))
        if status in {404, 410}:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            time.sleep(5.0)
            return generate_asset_from_source_image(
                trellis_url,
                obj,
                source_image,
                asset_dir,
                seed=seed,
                timeout=remaining,
                steps=steps,
                texture_size=texture_size,
                decimation_target=decimation_target,
                pipeline_type=pipeline_type,
                preprocess_image=preprocess_image,
                force=force,
                qa_strict=qa_strict,
            )
        if status != 202:
            raise RuntimeError(f"Trellis2 image-source job {job_id} for {object_id} returned {status}: {body[:200]!r}")
        time.sleep(3.0)
    write_json(
        meta_path,
        {
            "source": "tree_sage_text_trellis2_from_image2_source_image",
            "status": "timeout",
            "job_id": job_id,
            "object": obj,
            "asset_path": str(out_path),
            "asset_source_image": str(source_image),
            "pre_trellis_image_qa": qa,
            "bridge_metadata": bridge_metadata,
        },
    )
    raise TimeoutError(f"Trellis2 image-source job timed out for {object_id}")


def copy_library_assets(
    plan: dict[str, Any],
    library_dir: Path,
    alias_file: Path | None,
    asset_dir: Path,
) -> dict[str, Any]:
    asset_dir.mkdir(parents=True, exist_ok=True)
    aliases = _load_aliases(alias_file)
    copied: list[dict[str, Any]] = []
    missing: list[str] = []
    for obj in plan.get("objects", []):
        object_id = str(obj.get("id"))
        source = _resolve_library_asset(object_id, library_dir, aliases)
        if source:
            dst = asset_dir / f"{object_id}.glb"
            shutil.copy2(source, dst)
            meta_src = source.with_suffix(".json")
            if meta_src.exists():
                shutil.copy2(meta_src, asset_dir / f"{object_id}.json")
            else:
                write_json(
                    asset_dir / f"{object_id}.json",
                    {
                        "source": "tree_sage_text_asset_library",
                        "library_source": str(source),
                        "object": obj,
                        "asset_path": str(dst),
                    },
                )
            copied.append({"id": object_id, "source": str(source), "asset": str(dst)})
        else:
            missing.append(object_id)
    report = {
        "schema": "tree_sage_text_asset_library_copy_v1",
        "library_dir": str(library_dir),
        "asset_dir": str(asset_dir),
        "copied_count": len(copied),
        "missing_count": len(missing),
        "copied": copied,
        "missing": missing,
        "ok": not missing,
    }
    write_json(asset_dir.parent / "asset_library_copy_report.json", report)
    return report


def generate_trellis_prompt_assets(
    plan: dict[str, Any],
    asset_dir: Path,
    *,
    trellis_url: str,
    seed: int,
    timeout: float,
    steps: int,
    texture_size: int,
    decimation_target: int,
    pipeline_type: str,
    preprocess_image: bool,
    force: bool,
) -> dict[str, Any]:
    generated = []
    failures = []
    asset_dir.mkdir(parents=True, exist_ok=True)
    for index, obj in enumerate(plan.get("objects", [])):
        try:
            asset_path = generate_asset(
                trellis_url,
                obj,
                asset_dir,
                seed=seed + index,
                timeout=timeout,
                steps=steps,
                texture_size=texture_size,
                decimation_target=decimation_target,
                pipeline_type=pipeline_type,
                preprocess_image=preprocess_image,
                force=force,
            )
            generated.append({"id": obj.get("id"), "asset": str(asset_path)})
        except Exception as exc:
            failures.append({"id": obj.get("id"), "error": f"{type(exc).__name__}: {exc}"})
    report = {
        "schema": "tree_sage_text_trellis_prompt_assets_v1",
        "asset_dir": str(asset_dir),
        "trellis_url": trellis_url,
        "generated_count": len(generated),
        "failure_count": len(failures),
        "generated": generated,
        "failures": failures,
        "ok": not failures,
    }
    write_json(asset_dir.parent / "trellis_prompt_asset_report.json", report)
    return report


def generate_trellis_source_image_assets(
    plan: dict[str, Any],
    source_dir: Path,
    asset_dir: Path,
    *,
    trellis_url: str,
    seed: int,
    timeout: float,
    steps: int,
    texture_size: int,
    decimation_target: int,
    pipeline_type: str,
    preprocess_image: bool,
    force: bool,
    qa_strict: bool,
) -> dict[str, Any]:
    generated = []
    failures = []
    asset_dir.mkdir(parents=True, exist_ok=True)
    for index, obj in enumerate(plan.get("objects", [])):
        if not isinstance(obj, dict) or not obj.get("id"):
            continue
        try:
            source_image = _asset_source_image_path(source_dir, obj)
            if not source_image or not source_image.exists():
                raise FileNotFoundError(f"missing image2 source image: {source_image}")
            asset_path = generate_asset_from_source_image(
                trellis_url,
                obj,
                source_image,
                asset_dir,
                seed=seed + index,
                timeout=timeout,
                steps=steps,
                texture_size=texture_size,
                decimation_target=decimation_target,
                pipeline_type=pipeline_type,
                preprocess_image=preprocess_image,
                force=force,
                qa_strict=qa_strict,
            )
            generated.append({"id": obj.get("id"), "source_image": str(source_image), "asset": str(asset_path)})
        except Exception as exc:
            failures.append({"id": obj.get("id"), "error": f"{type(exc).__name__}: {exc}"})
    report = {
        "schema": "tree_sage_text_trellis_source_image_assets_v1",
        "asset_dir": str(asset_dir),
        "source_dir": str(source_dir),
        "trellis_url": trellis_url,
        "generated_count": len(generated),
        "failure_count": len(failures),
        "generated": generated,
        "failures": failures,
        "ok": not failures,
    }
    write_json(asset_dir.parent / "trellis_source_image_asset_report.json", report)
    return report


def ensure_assets_and_scene(plan: dict[str, Any], plan_path: Path, output_dir: Path, args: Any) -> dict[str, Any]:
    requested = str(args.asset_pipeline)
    resolved = requested
    report: dict[str, Any] = {
        "schema": "tree_sage_text_asset_pipeline_v1",
        "requested_pipeline": requested,
        "asset_strategy": str(args.asset_strategy),
        "asset_dir": None,
        "scene_glb": None,
        "steps": [],
        "ok": True,
    }
    if requested == "none":
        write_asset_plan(plan, output_dir, requested, "none")
        write_json(output_dir / "text_scene_asset_pipeline_report.json", report)
        return report

    asset_dir = output_dir / "assets_text_scene"
    if requested == "auto":
        if str(args.asset_strategy) == "asset_library" and args.trellis_asset_library_dir:
            resolved = "asset_library"
        else:
            resolved = "source_images"

    write_asset_plan(plan, output_dir, requested, resolved)
    report["resolved_pipeline"] = resolved

    if resolved == "asset_library":
        if not args.trellis_asset_library_dir:
            raise ValueError("--trellis-asset-library-dir is required for asset_library pipeline")
        library_report = copy_library_assets(plan, Path(args.trellis_asset_library_dir), args.reuse_asset_alias_file, asset_dir)
        report["steps"].append({"type": "asset_library", "report": str(output_dir / "asset_library_copy_report.json")})
        if library_report.get("missing"):
            report["ok"] = False
            report["asset_dir"] = str(asset_dir)
            write_json(output_dir / "text_scene_asset_pipeline_report.json", report)
            raise RuntimeError(
                "Asset library is missing required objects: " + ", ".join(str(item) for item in library_report["missing"])
            )
    elif resolved == "source_images":
        source_dir = Path(args.asset_source_image_dir) if args.asset_source_image_dir else None
        qa_report = write_asset_source_image_qa_report(
            plan,
            output_dir,
            source_dir,
            required=True,
            qa_strict=bool(args.asset_source_image_qa_strict),
        )
        report["steps"].append({"type": "image2_source_image_qa", "report": str(output_dir / "text_scene_asset_source_image_qa_report.json")})
        if not qa_report.get("ok"):
            report["ok"] = False
            report["asset_dir"] = str(asset_dir)
            report["error"] = (
                "image2 source images are required before Trellis2 asset generation. "
                f"QA reason: {qa_report.get('reason') or 'unknown'}"
            )
            write_json(output_dir / "text_scene_asset_pipeline_report.json", report)
            if qa_report.get("missing"):
                raise FileNotFoundError("missing required image2 source images: " + ", ".join(qa_report["missing"]))
            if qa_report.get("failed"):
                raise ValueError(
                    "image2 source image QA failed for: "
                    + ", ".join(str(item.get("id")) for item in qa_report["failed"])
                )
            raise RuntimeError(str(report["error"]))
        if not _trellis_healthy(str(args.trellis_url)):
            report["ok"] = False
            report["asset_dir"] = str(asset_dir)
            report["error"] = (
                f"Trellis2 service is not healthy at {args.trellis_url}. "
                "Start the Trellis2 bridge or use asset_library mode with a complete asset directory."
            )
            write_json(output_dir / "text_scene_asset_pipeline_report.json", report)
            raise RuntimeError(str(report["error"]))
        trellis_report = generate_trellis_source_image_assets(
            plan,
            source_dir,
            asset_dir,
            trellis_url=str(args.trellis_url),
            seed=int(args.seed),
            timeout=float(args.asset_timeout),
            steps=int(args.steps),
            texture_size=int(args.texture_size),
            decimation_target=int(args.decimation_target),
            pipeline_type=str(args.trellis_pipeline_type),
            preprocess_image=bool(args.trellis_preprocess_image),
            force=bool(args.force_assets),
            qa_strict=bool(args.asset_source_image_qa_strict),
        )
        report["steps"].append({"type": "trellis2_from_image2_source_images", "report": str(output_dir / "trellis_source_image_asset_report.json")})
        if trellis_report.get("failures"):
            report["ok"] = False
            report["asset_dir"] = str(asset_dir)
            write_json(output_dir / "text_scene_asset_pipeline_report.json", report)
            raise RuntimeError(
                "Trellis2 failed for required objects: "
                + ", ".join(str(item.get("id")) for item in trellis_report["failures"])
            )
    elif resolved == "trellis2_prompt":
        report["ok"] = False
        report["asset_dir"] = str(asset_dir)
        report["error"] = "trellis2_prompt is disabled for text-to-scene; provide image2 source images or use asset_library."
        write_json(output_dir / "text_scene_asset_pipeline_report.json", report)
        raise RuntimeError(str(report["error"]))
    else:
        raise ValueError(f"Unknown text-scene asset pipeline: {resolved}")

    report["asset_dir"] = str(asset_dir)
    if bool(args.assemble_scene):
        scene_glb = output_dir / "scene_text_sage.glb"
        assemble_scene_blender(str(args.blender_bin), plan_path, asset_dir, scene_glb)
        report["scene_glb"] = str(scene_glb)
        report["steps"].append({"type": "assemble_scene_blender", "scene_glb": str(scene_glb)})
    write_json(output_dir / "text_scene_asset_pipeline_report.json", report)
    return report
