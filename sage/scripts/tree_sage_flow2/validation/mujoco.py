"""MuJoCo proxy validation for TreeSAGE Flow 2 layouts."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

from tree_sage_flow2.io import write_json


DEFAULT_MUJOCO_PY = os.environ.get("SAGE_FLOW2_MUJOCO_PY", "/home/xy/PAT3D/pat3d_stage3/pat3/bin/python")
FLOW2_MUJOCO_MAX_DISPLACEMENT = float(os.environ.get("SAGE_FLOW2_MUJOCO_MAX_DISPLACEMENT", "0.18"))
VIRTUAL_WALLS = {"wall_north", "wall_south", "wall_east", "wall_west"}


def _flow2_mujoco_point(x: float, y: float, z: float = 0.0) -> dict[str, float]:
    return {"x": round(float(x), 6), "y": round(float(y), 6), "z": round(float(z), 6)}


def _category_text(obj: dict[str, Any]) -> str:
    parts = [
        obj.get("id", ""),
        obj.get("category", ""),
        obj.get("description", ""),
        obj.get("asset_prompt", ""),
        obj.get("semantic_class", ""),
        obj.get("semantic_layout_role", ""),
    ]
    return " ".join(str(part) for part in parts if part is not None).lower()


def _has_text(obj: dict[str, Any], keywords: tuple[str, ...]) -> bool:
    text = _category_text(obj)
    return any(keyword in text for keyword in keywords)


def _has_word_text(obj: dict[str, Any], keywords: tuple[str, ...]) -> bool:
    text = _category_text(obj)
    for keyword in keywords:
        if " " in keyword:
            if keyword in text:
                return True
            continue
        if re.search(rf"\b{re.escape(keyword)}\b", text):
            return True
    return False


def _is_wall_attached_object(obj: dict[str, Any]) -> bool:
    placement = str(obj.get("placement_type") or "").strip().lower()
    support_id = str(obj.get("support_id") or "").strip().lower()
    if placement == "attached_to_wall" or support_id in VIRTUAL_WALLS:
        return True
    text = _category_text(obj)
    return any(keyword in text for keyword in ("window", "door", "wall art", "painting", "picture", "mirror", "clock", "poster"))


def _is_hanging_object(obj: dict[str, Any]) -> bool:
    if _is_wall_attached_object(obj):
        return False
    return _has_text(obj, ("hanging", "pendant", "ceiling light", "chandelier"))


def _is_bed_or_sofa_object(obj: dict[str, Any]) -> bool:
    category = str(obj.get("category") or "").lower()
    if any(keyword in category for keyword in ("blanket", "throw", "quilt", "bedspread", "pillow", "cushion")):
        return False
    if any(keyword in _category_text(obj) for keyword in ("bed throw", "throw blanket", "bed blanket", "bed pillow", "accent pillow")):
        return False
    semantic = str(obj.get("semantic_class") or "").strip().lower()
    if semantic in {"bed", "sofa", "couch"}:
        return True
    if category in {"bed", "queen bed", "king bed", "single bed", "twin bed", "sofa", "couch", "sectional"}:
        return True
    return _has_word_text(obj, ("bed", "sofa", "couch", "sectional"))


def _round_yaw_90(value: float) -> float:
    return float(round(float(value) / 90.0) * 90.0) % 360.0


def _footprint_yaw(obj: dict[str, Any]) -> float:
    value = float(obj.get("yaw", 0.0) or 0.0) + float(obj.get("footprint_yaw_offset_degrees", 0.0) or 0.0)
    return _round_yaw_90(value)


ObjectPredicate = Callable[[dict[str, Any]], bool]
ObjectTextPredicate = Callable[[dict[str, Any], tuple[str, ...]], bool]
ObjectYawFn = Callable[[dict[str, Any]], float]


def _flow2_plan_to_mujoco_room(
    plan: dict[str, Any],
    parent: dict[str, str],
    *,
    is_wall_attached_fn: ObjectPredicate | None = None,
    is_hanging_fn: ObjectPredicate | None = None,
    footprint_yaw_fn: ObjectYawFn | None = None,
) -> dict[str, Any]:
    room = plan["room"]
    room_id = "room_tree_sage_flow2"
    width = float(room["width"])
    length = float(room["length"])
    height = float(room.get("height", room.get("ceiling_height", 2.7)))
    walls = [
        {"id": f"wall_{room_id}_north", "start_point": _flow2_mujoco_point(0, length), "end_point": _flow2_mujoco_point(width, length), "height": height, "thickness": 0.1, "material": "flow2_wall"},
        {"id": f"wall_{room_id}_south", "start_point": _flow2_mujoco_point(0, 0), "end_point": _flow2_mujoco_point(width, 0), "height": height, "thickness": 0.1, "material": "flow2_wall"},
        {"id": f"wall_{room_id}_east", "start_point": _flow2_mujoco_point(width, 0), "end_point": _flow2_mujoco_point(width, length), "height": height, "thickness": 0.1, "material": "flow2_wall"},
        {"id": f"wall_{room_id}_west", "start_point": _flow2_mujoco_point(0, 0), "end_point": _flow2_mujoco_point(0, length), "height": height, "thickness": 0.1, "material": "flow2_wall"},
    ]
    objects: list[dict[str, Any]] = []
    for obj in plan.get("objects", []):
        if not isinstance(obj, dict) or not obj.get("id"):
            continue
        dims = obj.get("dimensions") if isinstance(obj.get("dimensions"), dict) else {}
        obj_width = max(float(dims.get("width", 0.05) or 0.05), 0.01)
        obj_length = max(float(dims.get("length", 0.05) or 0.05), 0.01)
        obj_height = max(float(dims.get("height", 0.05) or 0.05), 0.01)
        support_id = str(obj.get("support_id") or parent.get(str(obj.get("id")), "floor"))
        placement_type = str(obj.get("placement_type", "floor"))
        is_wall_attached = is_wall_attached_fn or _is_wall_attached_object
        is_hanging = is_hanging_fn or _is_hanging_object
        footprint_yaw = footprint_yaw_fn or _footprint_yaw
        if placement_type == "attached_to_wall" or is_wall_attached(obj) or is_hanging(obj):
            place_id = "wall"
        elif support_id and support_id not in {"", "None"} | VIRTUAL_WALLS:
            place_id = support_id
        else:
            place_id = "floor"
        volume = obj_width * obj_length * obj_height
        objects.append(
            {
                "id": str(obj["id"]),
                "room_id": room_id,
                "type": str(obj.get("category", "object")),
                "description": str(obj.get("description", obj.get("category", ""))),
                "position": _flow2_mujoco_point(float(obj.get("x", 0.0)), float(obj.get("y", 0.0)), float(obj.get("z", 0.0))),
                "rotation": {"x": 0.0, "y": 0.0, "z": round(float(footprint_yaw(obj)), 6)},
                "dimensions": {"width": obj_width, "length": obj_length, "height": obj_height},
                "place_id": place_id,
                "placement_constraints": [],
                "mass": max(float(obj.get("mass", volume * 80.0) or volume * 80.0), 0.05),
            }
        )
    return {
        "id": room_id,
        "room_type": str(plan.get("room_type", "tree_sage_flow2_room")),
        "position": _flow2_mujoco_point(0, 0, 0),
        "dimensions": {"width": width, "length": length, "height": height},
        "walls": walls,
        "doors": [],
        "windows": [],
        "objects": objects,
        "floor_material": "flow2_floor",
        "ceiling_height": height,
    }


def _flow2_soft_visual_mujoco_exempt_ids(
    plan: dict[str, Any],
    parent: dict[str, str],
    *,
    has_text_fn: ObjectTextPredicate | None = None,
    is_bed_or_sofa_fn: ObjectPredicate | None = None,
) -> set[str]:
    objects = {str(obj.get("id")): obj for obj in plan.get("objects", []) if isinstance(obj, dict) and obj.get("id")}
    exempt: set[str] = set()
    has_text = has_text_fn or _has_text
    is_bed_or_sofa = is_bed_or_sofa_fn or _is_bed_or_sofa_object
    for object_id, obj in objects.items():
        if not has_text(obj, ("pillow", "cushion", "blanket", "duvet", "comforter", "quilt")):
            continue
        support_id = str(obj.get("support_id") or parent.get(object_id) or "")
        support = objects.get(support_id)
        if support and is_bed_or_sofa(support):
            exempt.add(object_id)
    return exempt


def _parse_flow2_mujoco_stdout(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def run_flow2_mujoco_check(
    plan: dict[str, Any],
    output_dir: Path,
    parent: dict[str, str],
    python_bin: str = DEFAULT_MUJOCO_PY,
    max_displacement: float = FLOW2_MUJOCO_MAX_DISPLACEMENT,
    is_wall_attached_fn: ObjectPredicate | None = None,
    is_hanging_fn: ObjectPredicate | None = None,
    is_bed_or_sofa_fn: ObjectPredicate | None = None,
    has_text_fn: ObjectTextPredicate | None = None,
    footprint_yaw_fn: ObjectYawFn | None = None,
) -> dict[str, Any]:
    room = _flow2_plan_to_mujoco_room(
        plan,
        parent,
        is_wall_attached_fn=is_wall_attached_fn,
        is_hanging_fn=is_hanging_fn,
        footprint_yaw_fn=footprint_yaw_fn,
    )
    room_path = output_dir / "mujoco_room.json"
    write_json(room_path, room)
    code = f"""
import json
from isaacsim.isaac_mcp.server import create_single_room_layout_scene_from_room, simulate_the_scene
create_result = create_single_room_layout_scene_from_room({str(output_dir)!r}, {str(room_path)!r})
simulate_result = simulate_the_scene()
print(json.dumps({{"create": create_result, "simulate": simulate_result}}, default=str))
"""
    env = os.environ.copy()
    env["SAGE_SIM_BACKEND"] = "mujoco"
    default_server_path = Path(__file__).resolve().parents[3] / "server"
    server_pythonpath = os.environ.get("SAGE_SERVER_PYTHONPATH", str(default_server_path))
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        server_pythonpath
        if not existing_pythonpath
        else os.pathsep.join([server_pythonpath, existing_pythonpath])
    )
    try:
        proc = subprocess.run(
            [python_bin, "-c", code],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=float(os.environ.get("SAGE_FLOW2_MUJOCO_TIMEOUT", "180")),
        )
    except Exception as exc:
        return {
            "schema": "tree_sage_flow2_mujoco_check_v1",
            "enabled": True,
            "proxy_model": "axis_aligned_box_room",
            "python": python_bin,
            "room_path": str(room_path),
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    parsed = _parse_flow2_mujoco_stdout(proc.stdout) or {}
    simulate = parsed.get("simulate") if isinstance(parsed.get("simulate"), dict) else {}
    mujoco_reports = simulate.get("mujoco_reports", []) if isinstance(simulate, dict) else []
    exempt_ids = _flow2_soft_visual_mujoco_exempt_ids(
        plan,
        parent,
        has_text_fn=has_text_fn,
        is_bed_or_sofa_fn=is_bed_or_sofa_fn,
    )
    max_disp_raw = 0.0
    max_disp_filtered = 0.0
    if isinstance(mujoco_reports, list):
        for item in mujoco_reports:
            if not isinstance(item, dict):
                continue
            max_disp_raw = max(max_disp_raw, float(item.get("max_displacement", 0.0) or 0.0))
            top_displacements = item.get("top_displacements") if isinstance(item.get("top_displacements"), list) else []
            for entry in top_displacements:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("body") or "") in exempt_ids:
                    continue
                max_disp_filtered = max(max_disp_filtered, float(entry.get("displacement", 0.0) or 0.0))
    unstable_objects_raw = simulate.get("unstable_objects", []) if isinstance(simulate, dict) else []
    unstable_objects = [str(object_id) for object_id in unstable_objects_raw if str(object_id) not in exempt_ids]
    simulate_ok = str(simulate.get("status", "")).lower() == "success" if isinstance(simulate, dict) else False
    displacement_warning = max_disp_filtered > float(max_displacement)
    ok = proc.returncode == 0 and simulate_ok and not unstable_objects
    return {
        "schema": "tree_sage_flow2_mujoco_check_v1",
        "enabled": True,
        "proxy_model": "axis_aligned_box_room",
        "python": python_bin,
        "room_path": str(room_path),
        "returncode": int(proc.returncode),
        "max_displacement": round(float(max_disp_filtered), 6),
        "raw_max_displacement": round(float(max_disp_raw), 6),
        "max_displacement_threshold": float(max_displacement),
        "displacement_warning": bool(displacement_warning),
        "unstable_objects": unstable_objects,
        "raw_unstable_objects": unstable_objects_raw,
        "soft_visual_exemptions": sorted(exempt_ids),
        "create": parsed.get("create"),
        "simulate": simulate,
        "stdout_tail": proc.stdout.splitlines()[-20:],
        "stderr_tail": proc.stderr.splitlines()[-20:],
        "ok": bool(ok),
    }
