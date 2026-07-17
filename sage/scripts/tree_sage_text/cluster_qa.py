from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from tree_sage_flow2.io import extract_json

from .critic import desk_chair_facing_issue, desk_chair_tuck_issue
from .io import write_json


def _object_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(obj.get("id")): obj for obj in plan.get("objects", []) if isinstance(obj, dict)}


def _run_visual_agent(
    *,
    image_path: Path,
    output_dir: Path,
    model: str,
    timeout: float,
) -> dict[str, Any]:
    response_path = output_dir / "desk_chair_visual_qa_response.md"
    stdout_path = output_dir / "desk_chair_visual_qa_stdout.txt"
    stderr_path = output_dir / "desk_chair_visual_qa_stderr.txt"
    prompt = """Inspect the attached desk-chair cluster render.

Decide whether the office chair is facing the desk/work surface correctly.
The correct relation is: a person sitting in the chair would face the desktop, and the chair backrest is on the side away from the desk.
Fail if the backrest is between the seat and the desktop, or if the chair appears to show its back toward the desk.

Return JSON only:
{
  "schema": "tree_sage_text_desk_chair_visual_qa_v1",
  "ok": true|false,
  "confidence": 0.0-1.0,
  "issue": "short issue or null",
  "evidence": "short visual evidence"
}
"""
    cmd = [
        "codex",
        "exec",
        "--model",
        model,
        "--ignore-user-config",
        "--ignore-rules",
        "--disable",
        "plugins",
        "--disable",
        "plugin_sharing",
        "--disable",
        "plugin_hooks",
        "-c",
        'model_reasoning_effort="low"',
        "--ephemeral",
        "--cd",
        str(Path.cwd()),
        "--sandbox",
        "read-only",
        "--output-last-message",
        str(response_path),
        "--image",
        str(image_path),
        "--",
        prompt,
    ]
    proc = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=float(timeout),
        check=False,
    )
    stdout_path.write_text(proc.stdout, encoding="utf-8")
    stderr_path.write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        return {
            "schema": "tree_sage_text_desk_chair_visual_qa_v1",
            "ok": False,
            "reason": "visual_qa_agent_failed",
            "returncode": proc.returncode,
            "stderr": proc.stderr[-1200:],
        }
    try:
        data = extract_json(response_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "schema": "tree_sage_text_desk_chair_visual_qa_v1",
            "ok": False,
            "reason": "visual_qa_agent_json_parse_failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
    if not isinstance(data, dict):
        return {
            "schema": "tree_sage_text_desk_chair_visual_qa_v1",
            "ok": False,
            "reason": "visual_qa_agent_non_object_response",
        }
    data.setdefault("schema", "tree_sage_text_desk_chair_visual_qa_v1")
    return data


def run_desk_chair_orientation_qa(
    plan: dict[str, Any],
    *,
    scene_plan_path: Path,
    scene_glb: Path | None,
    output_dir: Path,
    blender_bin: str,
    render_enabled: bool,
    visual_agent_enabled: bool = True,
    visual_agent_model: str = "gpt-5.6-sol",
    timeout: float = 300.0,
) -> dict[str, Any]:
    objects = _object_map(plan)
    report: dict[str, Any] = {
        "schema": "tree_sage_text_desk_chair_orientation_qa_v1",
        "enabled": True,
        "render_enabled": bool(render_enabled),
        "visual_agent_enabled": bool(visual_agent_enabled),
        "visual_agent_model": visual_agent_model,
        "scene_glb": str(scene_glb) if scene_glb else None,
        "scene_plan": str(scene_plan_path),
        "render": None,
        "ok": True,
        "checks": [],
    }
    if not {"desk", "office_chair"} <= set(objects):
        report["reason"] = "no_desk_chair_cluster"
        write_json(output_dir / "text_scene_desk_chair_orientation_qa.json", report)
        return report

    facing_issue = desk_chair_facing_issue(objects)
    tuck_issue = desk_chair_tuck_issue(objects)
    check = {
        "type": "chair_front_faces_desk",
        "subject": "office_chair",
        "object": "desk",
        "ok": facing_issue is None,
        "issue": facing_issue,
        "chair_yaw": objects["office_chair"].get("yaw"),
        "chair_visual_front_yaw_correction_degrees": objects["office_chair"]
        .get("agent_semantics", {})
        .get("visual_front_yaw_correction_degrees"),
        "desk_xy": [objects["desk"].get("x"), objects["desk"].get("y")],
        "chair_xy": [objects["office_chair"].get("x"), objects["office_chair"].get("y")],
    }
    report["checks"].append(check)
    if facing_issue:
        report["ok"] = False
        report["reason"] = "chair_front_not_facing_desk"
    tuck_check = {
        "type": "desk_chair_open_side_shallow_tuck",
        "members": ["desk", "office_chair"],
        "ok": tuck_issue is None,
        "issue": tuck_issue,
    }
    report["checks"].append(tuck_check)
    if tuck_issue:
        report["ok"] = False
        report["reason"] = "desk_chair_tuck_invalid"

    if render_enabled and scene_glb:
        output = output_dir / "desk_chair_cluster_render.png"
        script = Path(__file__).resolve().parents[1] / "blender_render_text_scene_cluster.py"
        cmd = [
            str(blender_bin),
            "--background",
            "--python",
            str(script),
            "--",
            "--scene-glb",
            str(scene_glb),
            "--plan",
            str(scene_plan_path),
            "--output",
            str(output),
            "--cluster",
            "desk_chair",
        ]
        proc = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=float(timeout),
            check=False,
        )
        report["render"] = str(output)
        report["render_stdout"] = str(output_dir / "desk_chair_cluster_render_stdout.txt")
        report["render_stderr"] = str(output_dir / "desk_chair_cluster_render_stderr.txt")
        Path(report["render_stdout"]).write_text(proc.stdout, encoding="utf-8")
        Path(report["render_stderr"]).write_text(proc.stderr, encoding="utf-8")
        if proc.returncode != 0 or not output.exists():
            report["ok"] = False
            report["reason"] = "desk_chair_cluster_render_failed"
            report["render_returncode"] = proc.returncode
        elif visual_agent_enabled:
            visual = _run_visual_agent(
                image_path=output,
                output_dir=output_dir,
                model=visual_agent_model,
                timeout=timeout,
            )
            report["visual_qa"] = visual
            if not visual.get("ok", False):
                report["ok"] = False
                report["reason"] = "desk_chair_visual_qa_failed"

    write_json(output_dir / "text_scene_desk_chair_orientation_qa.json", report)
    return report
