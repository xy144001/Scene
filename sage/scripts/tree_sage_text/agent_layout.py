from __future__ import annotations

from copy import deepcopy
import os
import subprocess
from pathlib import Path
from typing import Any

from tree_sage_flow2.io import extract_json

from .io import write_json
from .layout import (
    _ensure_desk_chair_facing,
    _ensure_all_objects_have_pose,
    _ensure_plant_away_from_door,
    _objects_by_id,
    _place_against_wall,
    _place_ceiling,
    _place_pendant_pair,
    _place_wall_fixture,
    _support_children,
)


def _compact_object(obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": obj.get("id"),
        "category": obj.get("category"),
        "description": obj.get("description"),
        "dimensions": obj.get("dimensions"),
        "placement_type": obj.get("placement_type"),
        "support_hint": obj.get("support_id") or obj.get("agent_semantics", {}).get("support_hint"),
        "layout_role": obj.get("agent_semantics", {}).get("layout_role"),
        "semantic_class": obj.get("agent_semantics", {}).get("semantic_class"),
    }


def _compact_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "scene_id": candidate.get("scene_id"),
        "layout_variant": candidate.get("layout_variant"),
        "objects": [
            {
                "id": obj.get("id"),
                "x": obj.get("x"),
                "y": obj.get("y"),
                "z": obj.get("z"),
                "yaw": obj.get("yaw"),
                "wall_id": obj.get("wall_id"),
                "functional_cluster_id": obj.get("functional_cluster_id"),
            }
            for obj in candidate.get("objects", [])
            if isinstance(obj, dict)
        ],
    }


def _build_agent_prompt(request_path: Path) -> str:
    return f"""Read the JSON layout request at:
{request_path}

You are redesigning a text-to-3D interior scene layout. Return JSON only.
Use the exact schema requested in the file. Do not write prose outside JSON.
"""


def _run_codex_layout_agent(
    *,
    request_path: Path,
    response_path: Path,
    stdout_path: Path,
    stderr_path: Path,
    model: str,
    reasoning_effort: str,
    cwd: Path,
) -> dict[str, Any]:
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
        f'model_reasoning_effort="{reasoning_effort}"',
        "--ephemeral",
        "--cd",
        str(cwd),
        "--sandbox",
        "read-only",
        "--output-last-message",
        str(response_path),
        "--",
        _build_agent_prompt(request_path),
    ]
    proc = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=int(os.environ.get("SAGE_TEXT_LAYOUT_AGENT_TIMEOUT", "900")),
        check=False,
    )
    stdout_path.write_text(proc.stdout, encoding="utf-8")
    stderr_path.write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"text layout planner agent failed with code {proc.returncode}: {proc.stderr[-1200:]}")
    return extract_json(response_path.read_text(encoding="utf-8"))


def _dims(obj: dict[str, Any]) -> tuple[float, float, float]:
    dims = obj.get("dimensions") if isinstance(obj.get("dimensions"), dict) else {}
    return float(dims.get("width", 1.0)), float(dims.get("length", 1.0)), float(dims.get("height", 1.0))


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _apply_agent_pose(obj: dict[str, Any], pose: dict[str, Any], room: dict[str, Any]) -> None:
    width, length, height = _dims(obj)
    room_w = float(room["width"])
    room_l = float(room["length"])
    room_h = float(room["height"])
    placement = str(obj.get("placement_type") or "floor")
    wall_id = str(pose.get("wall_id") or obj.get("wall_id") or "")
    z = _clamp(float(pose.get("z", obj.get("z", 0.0)) or 0.0), 0.0, max(0.0, room_h - height))
    yaw = float(pose.get("yaw", obj.get("yaw", 0.0)) or 0.0)

    if placement == "wall" and wall_id in {"wall_north", "wall_south", "wall_west", "wall_east"}:
        tangent = float(pose.get("x", 0.0)) if wall_id in {"wall_north", "wall_south"} else float(pose.get("y", 0.0))
        tangent_max = room_w if wall_id in {"wall_north", "wall_south"} else room_l
        _place_wall_fixture(obj, room, wall_id, _clamp(tangent, width / 2.0, tangent_max - width / 2.0), z)
        return

    if placement == "ceiling":
        obj["x"] = round(_clamp(float(pose.get("x", room_w / 2.0) or room_w / 2.0), width / 2.0, room_w - width / 2.0), 4)
        obj["y"] = round(_clamp(float(pose.get("y", room_l / 2.0) or room_l / 2.0), length / 2.0, room_l - length / 2.0), 4)
        obj["z"] = round(_clamp(z, 0.0, room_h - height), 4)
        obj["yaw"] = round(yaw, 3)
        return

    if wall_id in {"wall_north", "wall_south", "wall_west", "wall_east"} and placement in {"floor", "floor_layer"}:
        tangent = float(pose.get("x", 0.0)) if wall_id in {"wall_north", "wall_south"} else float(pose.get("y", 0.0))
        tangent_max = room_w if wall_id in {"wall_north", "wall_south"} else room_l
        _place_against_wall(obj, room, wall_id, _clamp(tangent, width / 2.0, tangent_max - width / 2.0), z)
        obj.setdefault("agent_semantics", {})["agent_requested_yaw"] = round(yaw, 3)
        obj["agent_semantics"]["wall_pose_yaw_source"] = "text_scene_wall_against_layout_rule"
        return

    obj["x"] = round(_clamp(float(pose.get("x", obj.get("x", room_w / 2.0)) or room_w / 2.0), width / 2.0, room_w - width / 2.0), 4)
    obj["y"] = round(_clamp(float(pose.get("y", obj.get("y", room_l / 2.0)) or room_l / 2.0), length / 2.0, room_l - length / 2.0), 4)
    obj["z"] = round(z, 4)
    obj["yaw"] = round(yaw, 3)


def _merge_agent_candidate(
    scene_graph: dict[str, Any],
    agent_candidate: dict[str, Any],
    *,
    index: int,
) -> dict[str, Any]:
    room = deepcopy(scene_graph["room"])
    room_type = str(scene_graph.get("room_type") or "bedroom")
    objects = _objects_by_id(deepcopy(scene_graph["objects"]))
    for pose in agent_candidate.get("objects", []):
        if not isinstance(pose, dict):
            continue
        object_id = str(pose.get("id") or "")
        obj = objects.get(object_id)
        if not obj:
            continue
        _apply_agent_pose(obj, pose, room)
        if pose.get("functional_cluster_id"):
            obj["functional_cluster_id"] = str(pose["functional_cluster_id"])
        obj.setdefault("agent_semantics", {})["pose_source"] = "text_layout_planner_agent"
        if pose.get("rationale"):
            obj["agent_semantics"]["pose_rationale"] = str(pose.get("rationale"))

    _place_ceiling(objects, room)
    _place_pendant_pair(objects, room)
    _support_children(objects)
    _ensure_all_objects_have_pose(objects, room, room_type)
    _ensure_plant_away_from_door(objects, room)
    _ensure_desk_chair_facing(objects)
    return {
        "scene_id": f"{scene_graph.get('scene_id', 'text_scene')}_agent_{index}",
        "room_type": room_type,
        "building_style": scene_graph.get("building_style", ""),
        "description": scene_graph.get("description", ""),
        "room": room,
        "objects": list(objects.values()),
        "relations": deepcopy(scene_graph.get("relations", [])),
        "layout_variant": str(agent_candidate.get("layout_variant") or f"agent_{index}"),
        "layout_candidate_index": index,
        "layout_planner_agent": {
            "model": agent_candidate.get("model"),
            "rationale": agent_candidate.get("rationale"),
            "strategy": agent_candidate.get("strategy"),
        },
    }


def run_text_layout_planner_agent(
    *,
    scene_graph: dict[str, Any],
    constraints: dict[str, Any],
    rule_candidates: list[dict[str, Any]],
    output_dir: Path,
    model: str,
    candidate_count: int,
    reasoning_effort: str = "medium",
    cwd: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    request_path = output_dir / "text_scene_layout_agent_request.json"
    response_path = output_dir / "text_scene_layout_agent_response.md"
    stdout_path = output_dir / "text_scene_layout_agent_stdout.txt"
    stderr_path = output_dir / "text_scene_layout_agent_stderr.txt"
    room = scene_graph.get("room") if isinstance(scene_graph.get("room"), dict) else {}
    request = {
        "schema": "tree_sage_text_layout_planner_agent_request_v1",
        "instructions": [
            "Design a better interior layout than the rule baseline, using the exact room coordinate system.",
            "Coordinate system: x is west-to-east/left-to-right, y is south-to-north/front-to-back, z is upward.",
            "Walls: wall_west is x=0, wall_east is x=room.width, wall_south is y=0, wall_north is y=room.length.",
            "For wall fixtures, provide wall_id, bottom z, and tangent coordinate via x for north/south or y for west/east.",
            "For floor furniture against a wall, provide wall_id plus its tangent coordinate; the pipeline will choose the wall-safe asset yaw and footprint placement.",
            "Keep support children on their support object; the pipeline will re-set their final tabletop z.",
            "Plants must stay at least 1.0m away from doors.",
            "For every desk/work-table plus office-chair workstation, put the chair on the open room side of the desk, shallowly tucked, with the chair backrest on the side away from the desktop. The pipeline will enforce the asset-specific chair yaw.",
            "Wall fixtures on the same wall must not overlap.",
            "Return exactly requested_candidate_count diverse candidates unless the room is impossible.",
            "Return only JSON with schema tree_sage_text_layout_planner_agent_v1.",
        ],
        "output_schema": {
            "schema": "tree_sage_text_layout_planner_agent_v1",
            "model": model,
            "candidates": [
                {
                    "layout_variant": "short_name",
                    "strategy": "one sentence",
                    "rationale": "brief rationale",
                    "objects": [
                        {
                            "id": "object id",
                            "x": "number",
                            "y": "number",
                            "z": "number",
                            "yaw": "number degrees",
                            "wall_id": "optional wall_north/wall_south/wall_west/wall_east",
                            "functional_cluster_id": "optional cluster name",
                            "rationale": "optional short reason",
                        }
                    ],
                }
            ],
        },
        "room": {
            "width": room.get("width"),
            "length": room.get("length"),
            "height": room.get("height"),
            "room_type": scene_graph.get("room_type"),
        },
        "prompt": scene_graph.get("description"),
        "objects": [_compact_object(obj) for obj in scene_graph.get("objects", []) if isinstance(obj, dict)],
        "constraints": constraints.get("constraints", []),
        "rule_baseline_candidates": [_compact_candidate(candidate) for candidate in rule_candidates[:3]],
        "requested_candidate_count": max(1, int(candidate_count)),
    }
    write_json(request_path, request)
    report: dict[str, Any] = {
        "schema": "tree_sage_text_layout_planner_agent_report_v1",
        "enabled": True,
        "model": model,
        "request": str(request_path),
        "response": str(response_path),
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
        "ok": False,
        "candidate_count": 0,
    }
    try:
        raw = _run_codex_layout_agent(
            request_path=request_path,
            response_path=response_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            model=model,
            reasoning_effort=reasoning_effort,
            cwd=cwd or Path.cwd(),
        )
        raw_candidates = raw.get("candidates") if isinstance(raw, dict) else None
        if not isinstance(raw_candidates, list) or not raw_candidates:
            raise ValueError("layout planner agent returned no candidates")
        candidates = [
            _merge_agent_candidate(scene_graph, candidate, index=index)
            for index, candidate in enumerate(raw_candidates[: max(1, int(candidate_count))], start=1)
            if isinstance(candidate, dict)
        ]
        if not candidates:
            raise ValueError("layout planner agent candidates were invalid after merge")
        report["ok"] = True
        report["candidate_count"] = len(candidates)
        report["raw_response_schema"] = raw.get("schema") if isinstance(raw, dict) else None
        report["raw_candidate_count"] = len(raw_candidates)
        write_json(output_dir / "text_scene_layout_agent_report.json", report)
        return candidates, report
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        write_json(output_dir / "text_scene_layout_agent_report.json", report)
        return [], report
