#!/usr/bin/env python3
"""Generate a small scene with local Codex planning and Trellis2-generated assets."""

from __future__ import annotations

import argparse
import http.client as http_client
import json
import math
import os
import re
import shutil
import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageFont


DEFAULT_BLENDER = "/data/xy/tools/blender-4.3.2-linux-x64/blender"


OFFICIAL_PROMPTS = {
    "office_task": (
        "In an office with a desk holding a coffee mug and document folder with an office chair in front, "
        "a bookshelf with a stapler against the wall, a filing cabinet with a tape dispenser positioned away "
        "from the desk and bookshelf, and a side table near the desk, the robot must pick up the coffee mug "
        "from the desk and place it on the side table."
    ),
    "living_room_task": (
        "In a living room with a coffee table holding a small toy rubik cube and a plate, a student desk "
        "positioned away from the coffee table, and a round table with a coke can positioned away from both "
        "other tables, the robot must pick up the toy rubik cube from the coffee table and place it on the plate."
    ),
    "craft_room": (
        "Craft supply hoarder's bungalow work room with yarn, beads, fabric bolts, paints, brushes, "
        "and scrapbooking materials."
    ),
}


FALLBACK_PLAN = {
    "scene_id": "layout_selfmade_trellis_office",
    "room_type": "compact office",
    "building_style": "clean pragmatic research office",
    "description": "A compact office generated with self-made Trellis2 assets.",
    "room": {"width": 5.8, "length": 4.2, "height": 2.7},
    "objects": [
        {
            "id": "desk_main",
            "category": "desk",
            "asset_prompt": "a simple modern wooden office desk, rectangular, four legs, isolated object, no room",
            "x": 1.15,
            "y": 1.15,
            "z": 0.0,
            "yaw": 270,
            "dimensions": {"width": 1.4, "length": 0.75, "height": 0.75},
        },
        {
            "id": "office_chair",
            "category": "chair",
            "asset_prompt": "a black ergonomic office chair with backrest and wheels, isolated object, no room",
            "x": 2.1,
            "y": 1.15,
            "z": 0.0,
            "yaw": 90,
            "dimensions": {"width": 0.65, "length": 0.65, "height": 1.05},
        },
        {
            "id": "bookshelf",
            "category": "bookshelf",
            "asset_prompt": "a tall wooden bookshelf with several shelves and books, isolated object, no room",
            "x": 0.55,
            "y": 3.35,
            "z": 0.0,
            "yaw": 270,
            "dimensions": {"width": 0.9, "length": 0.35, "height": 1.75},
        },
        {
            "id": "filing_cabinet",
            "category": "cabinet",
            "asset_prompt": "a gray metal filing cabinet with drawers, office furniture, isolated object, no room",
            "x": 4.95,
            "y": 1.0,
            "z": 0.0,
            "yaw": 90,
            "dimensions": {"width": 0.65, "length": 0.45, "height": 1.1},
        },
        {
            "id": "side_table",
            "category": "side table",
            "asset_prompt": "a small square side table, light wood, simple furniture, isolated object, no room",
            "x": 3.85,
            "y": 2.8,
            "z": 0.0,
            "yaw": 0,
            "dimensions": {"width": 0.65, "length": 0.65, "height": 0.55},
        },
        {
            "id": "coffee_mug",
            "category": "coffee mug",
            "asset_prompt": "a red ceramic coffee mug with handle, isolated object, plain background",
            "x": 1.15,
            "y": 1.15,
            "z": 0.78,
            "yaw": 25,
            "dimensions": {"width": 0.18, "length": 0.14, "height": 0.16},
        },
    ],
}


def _is_loopback_url(url: str) -> bool:
    host = urlparse(url).hostname
    return host in {"127.0.0.1", "localhost", "::1"}


@contextmanager
def _open_url_no_proxy_for_loopback(req_or_url: Any, timeout: float):
    url = req_or_url.full_url if hasattr(req_or_url, "full_url") else str(req_or_url)
    if _is_loopback_url(url):
        opener = urlrequest.build_opener(urlrequest.ProxyHandler({}))
        with opener.open(req_or_url, timeout=timeout) as resp:
            yield resp
        return
    with urlrequest.urlopen(req_or_url, timeout=timeout) as resp:
        yield resp


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def make_codex_prompt(scene_prompt: str) -> str:
    return f"""
You are the local Codex replacement for the SAGE scene planner.
Create one compact single-room scene plan from this prompt:

{scene_prompt}

Return only JSON:
{{
  "scene_id": "layout_selfmade_trellis_<short_name>",
  "room_type": "...",
  "building_style": "...",
  "description": "...",
  "room": {{"width": 4.5-7.0, "length": 3.5-5.5, "height": 2.7}},
  "objects": [
    {{
      "id": "short_unique_id",
      "category": "semantic category",
      "asset_prompt": "single isolated object prompt suitable for text-to-image-to-3D",
      "x": number,
      "y": number,
      "z": number,
      "yaw": 0|90|180|270,
      "dimensions": {{"width": meters, "length": meters, "height": meters}}
    }}
  ]
}}

Rules:
- 5 to 9 objects only, because each object will be generated by Trellis2.
- Coordinate system: x/y are object centers in meters from the room's southwest floor corner.
- x must be in [0, room.width], y must be in [0, room.length]. Never use negative coordinates.
- z is the object's bottom height in meters. Floor objects use z=0; tabletop objects use the support height.
- Include task-relevant objects if mentioned.
- Use simple isolated-object asset prompts, not full-room prompts.
- Put large furniture on z=0. Put tabletop objects at the support surface height.
- Keep object centers inside room bounds.
- Avoid markdown and any text outside JSON.
""".strip()


def run_codex(scene_prompt: str, output_dir: Path, model: str | None) -> dict[str, Any]:
    request_text = make_codex_prompt(scene_prompt)
    request_path = output_dir / "codex_scene_request.txt"
    response_path = output_dir / "codex_scene_response.txt"
    request_path.write_text(request_text, encoding="utf-8")
    cmd = [
        "codex",
        "exec",
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
        request_text,
    ]
    if model:
        cmd[2:2] = ["--model", model]
    proc = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=int(os.environ.get("SAGE_CODEX_TIMEOUT", "600")),
        check=False,
    )
    (output_dir / "codex_scene_stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (output_dir / "codex_scene_stderr.txt").write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"codex exec failed with code {proc.returncode}")
    return extract_json(response_path.read_text(encoding="utf-8"))


def clean_plan(plan: dict[str, Any], max_objects: int = 7) -> dict[str, Any]:
    room = plan.setdefault("room", {})
    room["width"] = min(max(float(room.get("width", 5.8)), 4.5), 7.0)
    room["length"] = min(max(float(room.get("length", 4.2)), 3.5), 5.5)
    room["height"] = float(room.get("height", 2.7))
    raw_objects = list(plan.get("objects", []))
    raw_xs = [float(obj.get("x", 0.0)) for obj in raw_objects if isinstance(obj, dict)]
    raw_ys = [float(obj.get("y", 0.0)) for obj in raw_objects if isinstance(obj, dict)]
    center_origin = bool(raw_xs and raw_ys and (min(raw_xs) < 0.0 or min(raw_ys) < 0.0))
    x_offset = room["width"] / 2.0 if center_origin else 0.0
    y_offset = room["length"] / 2.0 if center_origin else 0.0
    objects = []
    seen = set()
    for i, obj in enumerate(raw_objects):
        object_id = re.sub(r"[^a-zA-Z0-9_]+", "_", str(obj.get("id") or f"object_{i}")).strip("_") or f"object_{i}"
        if object_id in seen:
            object_id = f"{object_id}_{i}"
        seen.add(object_id)
        dims = obj.get("dimensions") or {}
        width = min(max(float(dims.get("width", 0.6)), 0.08), 2.0)
        length = min(max(float(dims.get("length", 0.6)), 0.08), 2.0)
        category_hint = f"{obj.get('category', '')} {obj.get('id', '')}".lower()
        min_height = 0.01 if any(k in category_hint for k in ["folder", "paper", "document"]) else 0.08
        height = min(max(float(dims.get("height", 0.6)), min_height), 2.2)
        raw_x = float(obj.get("x", 1.0)) + x_offset
        raw_y = float(obj.get("y", 1.0)) + y_offset
        x = min(max(raw_x, width / 2 + 0.05), room["width"] - width / 2 - 0.05)
        y = min(max(raw_y, length / 2 + 0.05), room["length"] - length / 2 - 0.05)
        objects.append(
            {
                "id": object_id,
                "category": str(obj.get("category") or object_id),
                "asset_prompt": str(obj.get("asset_prompt") or f"a {object_id}, isolated object, no room"),
                "x": x,
                "y": y,
                "z": max(float(obj.get("z", 0.0)), 0.0),
                "yaw": float(obj.get("yaw", 0.0)),
                "dimensions": {"width": width, "length": length, "height": height},
            }
        )
    plan["objects"] = objects[:max(1, int(max_objects))] or FALLBACK_PLAN["objects"]
    plan["_coordinate_frame"] = "center_origin_translated_to_corner_origin" if center_origin else "corner_origin"
    plan["scene_id"] = re.sub(r"[^a-zA-Z0-9_]+", "_", str(plan.get("scene_id") or FALLBACK_PLAN["scene_id"])).strip("_")
    if not plan["scene_id"].startswith("layout_"):
        plan["scene_id"] = f"layout_{plan['scene_id']}"
    plan.setdefault("room_type", "self-made Trellis2 room")
    plan.setdefault("building_style", "self-made generated scene")
    plan.setdefault("description", "A scene generated with local Codex planning and Trellis2 assets.")
    return plan


def _category_text(obj: dict[str, Any]) -> str:
    return f"{obj.get('id', '')} {obj.get('category', '')} {obj.get('asset_prompt', '')}".lower()


def _has_any(obj: dict[str, Any], keywords: list[str]) -> bool:
    text = _category_text(obj)
    return any(keyword in text for keyword in keywords)


def _is_protected_wall_flat_asset(obj: dict[str, Any]) -> bool:
    text = _category_text(obj)
    placement = str(obj.get("placement_type") or "").strip().lower()
    support_id = str(obj.get("support_id") or "").strip().lower()
    wall_related = (
        placement == "attached_to_wall"
        or support_id.startswith("wall_")
        or any(keyword in text for keyword in ("wall-mounted", "wall mounted", "attached to wall"))
    )
    if not wall_related:
        return False
    if "window" in text:
        return False
    return any(
        keyword in text
        for keyword in (
            "door",
            "curtain",
            "drape",
            "wall art",
            "framed art",
            "painting",
            "picture",
            "poster",
            "print",
            "mirror",
        )
    )


def _find_first(plan: dict[str, Any], keywords: list[str]) -> dict[str, Any] | None:
    for obj in plan.get("objects", []):
        if _has_any(obj, keywords):
            return obj
    return None


def _round_yaw_90(yaw: float) -> float:
    return float((round(float(yaw) / 90.0) * 90) % 360)


def _yaw_towards(src: dict[str, Any], dst: dict[str, Any]) -> float:
    dx = float(dst["x"]) - float(src["x"])
    dy = float(dst["y"]) - float(src["y"])
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return _round_yaw_90(float(src.get("yaw", 0.0)))
    return _round_yaw_90(math.degrees(math.atan2(dy, dx)))


def _rotated_footprint(obj: dict[str, Any]) -> tuple[float, float]:
    dims = obj["dimensions"]
    width = float(dims["width"])
    length = float(dims["length"])
    effective_yaw = (
        float(obj.get("yaw", 0.0) or 0.0)
        + float(obj.get("footprint_yaw_offset_degrees", 0.0) or 0.0)
    )
    yaw = int(_round_yaw_90(effective_yaw)) % 180
    return (length, width) if yaw == 90 else (width, length)


def _clamp(value: float, lo: float, hi: float) -> float:
    if hi < lo:
        return (lo + hi) / 2.0
    return min(max(value, lo), hi)


def _clamp_object_to_room(obj: dict[str, Any], room: dict[str, float]) -> None:
    width, length = _rotated_footprint(obj)
    margin = 0.08
    obj["x"] = _clamp(float(obj["x"]), width / 2.0 + margin, float(room["width"]) - width / 2.0 - margin)
    obj["y"] = _clamp(float(obj["y"]), length / 2.0 + margin, float(room["length"]) - length / 2.0 - margin)


def _place_on_support(
    obj: dict[str, Any],
    support: dict[str, Any],
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    height_offset: float = 0.012,
) -> None:
    support_dims = support["dimensions"]
    obj_dims = obj["dimensions"]
    sx = float(support["x"]) + offset_x
    sy = float(support["y"]) + offset_y
    max_dx = max(0.0, float(support_dims["width"]) / 2.0 - float(obj_dims["width"]) / 2.0 - 0.06)
    max_dy = max(0.0, float(support_dims["length"]) / 2.0 - float(obj_dims["length"]) / 2.0 - 0.06)
    obj["x"] = float(support["x"]) + _clamp(sx - float(support["x"]), -max_dx, max_dx)
    obj["y"] = float(support["y"]) + _clamp(sy - float(support["y"]), -max_dy, max_dy)
    obj["z"] = float(support.get("z", 0.0)) + float(support_dims["height"]) + height_offset
    obj["support_id"] = support["id"]
    obj["placement_type"] = "on_top"


def _normalize_object_dimensions(plan: dict[str, Any]) -> None:
    for obj in plan.get("objects", []):
        dims = obj["dimensions"]
        text = _category_text(obj)
        if "document" in text or "folder" in text:
            dims["width"] = _clamp(float(dims["width"]), 0.24, 0.36)
            dims["length"] = _clamp(float(dims["length"]), 0.18, 0.28)
            dims["height"] = _clamp(float(dims["height"]), 0.018, 0.035)
        elif "mug" in text or "cup" in text:
            dims["width"] = _clamp(float(dims["width"]), 0.10, 0.16)
            dims["length"] = _clamp(float(dims["length"]), 0.08, 0.15)
            dims["height"] = _clamp(float(dims["height"]), 0.09, 0.14)
        elif "chair" in text:
            dims["width"] = _clamp(float(dims["width"]), 0.55, 0.75)
            dims["length"] = _clamp(float(dims["length"]), 0.55, 0.75)
            dims["height"] = _clamp(float(dims["height"]), 0.85, 1.15)
        elif "bookshelf" in text or "book shelf" in text:
            dims["width"] = _clamp(float(dims["width"]), 0.75, 1.10)
            dims["length"] = _clamp(float(dims["length"]), 0.28, 0.45)
            dims["height"] = _clamp(float(dims["height"]), 1.55, 2.05)
        elif "filing" in text or "cabinet" in text:
            dims["width"] = _clamp(float(dims["width"]), 0.45, 0.75)
            dims["length"] = _clamp(float(dims["length"]), 0.40, 0.75)
            dims["height"] = _clamp(float(dims["height"]), 0.85, 1.25)


def _repair_office_layout(plan: dict[str, Any]) -> list[str]:
    room = plan["room"]
    issues: list[str] = []
    desk = _find_first(plan, ["desk"])
    chair = _find_first(plan, ["chair"])
    side_table = _find_first(plan, ["side_table", "side table"])
    bookshelf = _find_first(plan, ["bookshelf", "book shelf"])
    filing = _find_first(plan, ["filing", "cabinet"])
    mug = _find_first(plan, ["mug", "coffee cup"])
    folder = _find_first(plan, ["folder", "document"])

    if desk:
        desk["x"] = _clamp(float(room["width"]) * 0.27, float(desk["dimensions"]["width"]) / 2.0 + 0.18, float(room["width"]) - float(desk["dimensions"]["width"]) / 2.0 - 0.18)
        desk["y"] = _clamp(float(room["length"]) - float(desk["dimensions"]["length"]) / 2.0 - 0.45, float(desk["dimensions"]["length"]) / 2.0 + 0.18, float(room["length"]) - float(desk["dimensions"]["length"]) / 2.0 - 0.18)
        desk["z"] = 0.0
        desk["yaw"] = 270.0
        desk["placement_type"] = "floor"
        issues.append("anchored desk near the wall as the primary support surface")

    if chair and desk:
        chair["x"] = float(desk["x"])
        chair["y"] = float(desk["y"]) - float(desk["dimensions"]["length"]) / 2.0 - float(chair["dimensions"]["length"]) / 2.0 - 0.28
        chair["z"] = 0.0
        chair["yaw"] = _yaw_towards(chair, desk)
        chair["placement_type"] = "floor"
        issues.append("moved office chair in front of the desk and oriented it toward the desk")

    if side_table and desk:
        side_table["x"] = float(desk["x"]) + float(desk["dimensions"]["width"]) / 2.0 + float(side_table["dimensions"]["width"]) / 2.0 + 0.38
        side_table["y"] = float(desk["y"])
        side_table["z"] = 0.0
        side_table["yaw"] = 0.0
        side_table["placement_type"] = "floor"
        issues.append("placed side table close to the desk for the mug transfer task")

    if bookshelf:
        bookshelf["x"] = float(room["width"]) - float(bookshelf["dimensions"]["width"]) / 2.0 - 0.35
        bookshelf["y"] = float(room["length"]) - float(bookshelf["dimensions"]["length"]) / 2.0 - 0.12
        bookshelf["z"] = 0.0
        bookshelf["yaw"] = 270.0
        bookshelf["placement_type"] = "floor"
        issues.append("moved bookshelf against the north wall")

    if filing:
        filing["x"] = float(room["width"]) - float(filing["dimensions"]["width"]) / 2.0 - 0.25
        filing["y"] = float(filing["dimensions"]["length"]) / 2.0 + 0.35
        filing["z"] = 0.0
        filing["yaw"] = 180.0
        filing["placement_type"] = "floor"
        issues.append("kept filing cabinet away from desk and bookshelf")

    if mug and desk:
        _place_on_support(mug, desk, offset_x=-0.36, offset_y=-0.02, height_offset=0.012)
        mug["yaw"] = 90.0
        issues.append("snapped coffee mug onto the desk top")

    if folder and desk:
        _place_on_support(folder, desk, offset_x=0.30, offset_y=0.05, height_offset=0.008)
        folder["yaw"] = 0.0
        issues.append("snapped document folder onto the desk top and reduced its thickness")

    for obj in plan.get("objects", []):
        _clamp_object_to_room(obj, room)

    return issues


def _topdown_overlap(a: dict[str, Any], b: dict[str, Any], padding: float = 0.06) -> tuple[float, float]:
    aw, al = _rotated_footprint(a)
    bw, bl = _rotated_footprint(b)
    dx = (aw + bw) / 2.0 + padding - abs(float(a["x"]) - float(b["x"]))
    dy = (al + bl) / 2.0 + padding - abs(float(a["y"]) - float(b["y"]))
    return dx, dy


def _repair_floor_collisions(plan: dict[str, Any]) -> list[str]:
    room = plan["room"]
    floor_objects = [
        obj
        for obj in plan.get("objects", [])
        if str(obj.get("placement_type", "floor")) == "floor" and float(obj.get("z", 0.0)) <= 0.05
    ]
    fixes: list[str] = []
    for _ in range(12):
        moved = False
        for index, a in enumerate(floor_objects):
            for b in floor_objects[index + 1 :]:
                dx, dy = _topdown_overlap(a, b)
                if dx <= 0.0 or dy <= 0.0:
                    continue
                if dx < dy:
                    direction = 1.0 if float(b["x"]) >= float(a["x"]) else -1.0
                    b["x"] = float(b["x"]) + direction * (dx + 0.04)
                else:
                    direction = 1.0 if float(b["y"]) >= float(a["y"]) else -1.0
                    b["y"] = float(b["y"]) + direction * (dy + 0.04)
                _clamp_object_to_room(b, room)
                fixes.append(f"resolved top-down overlap between {a['id']} and {b['id']}")
                moved = True
        if not moved:
            break
    return fixes


def apply_asset_pose_defaults(plan: dict[str, Any]) -> list[str]:
    fixes: list[str] = []
    for obj in plan.get("objects", []):
        obj.setdefault("asset_axis_to_z", 2)
        obj.setdefault("asset_local_yaw_offset_degrees", 0.0)
        obj.setdefault("front_yaw_offset_degrees", 0.0)
        obj.setdefault("footprint_yaw_offset_degrees", 0.0)
        if "bookshelf" not in _category_text(obj) and "book shelf" not in _category_text(obj):
            continue
        try:
            current_axis = int(obj.get("asset_axis_to_z", 2))
        except (TypeError, ValueError):
            current_axis = 2
        if current_axis != 2:
            fixes.append(f"{obj['id']}: locked bookshelf asset_axis_to_z=2")
        obj["asset_axis_to_z"] = 2
        obj["front_yaw_offset_degrees"] = 0.0
        if int(_round_yaw_90(float(obj.get("yaw", 0.0)))) == 270:
            obj["yaw"] = 180.0
            fixes.append(f"{obj['id']}: rotated bookshelf face toward room")
    return fixes


def audit_and_repair_plan(plan: dict[str, Any], scene_prompt: str) -> dict[str, Any]:
    original = json.loads(json.dumps(plan))
    _normalize_object_dimensions(plan)
    fixes = []
    if "office" in scene_prompt.lower() or any(_has_any(obj, ["desk", "chair", "bookshelf"]) for obj in plan.get("objects", [])):
        fixes.extend(_repair_office_layout(plan))
    else:
        for obj in plan.get("objects", []):
            obj["yaw"] = _round_yaw_90(float(obj.get("yaw", 0.0)))
            _clamp_object_to_room(obj, plan["room"])
    fixes.extend(apply_asset_pose_defaults(plan))
    for obj in plan.get("objects", []):
        _clamp_object_to_room(obj, plan["room"])
    fixes.extend(_repair_floor_collisions(plan))
    plan["_layout_audit"] = {
        "enabled": True,
        "fixes": fixes,
        "input_object_count": len(original.get("objects", [])),
        "output_object_count": len(plan.get("objects", [])),
    }
    return plan


def post_json(url: str, payload: dict[str, Any], timeout: float = 30.0) -> tuple[int, dict[str, Any]]:
    req = urlrequest.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with _open_url_no_proxy_for_loopback(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def get_job(url: str, timeout: float = 30.0) -> tuple[int, bytes, str]:
    try:
        with _open_url_no_proxy_for_loopback(url, timeout=timeout) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type", "")
    except HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Content-Type", "")


RETRYABLE_JOB_POLL_ERRORS = (
    TimeoutError,
    socket.timeout,
    ConnectionResetError,
    ConnectionAbortedError,
    BrokenPipeError,
    http_client.RemoteDisconnected,
    URLError,
)


def generate_asset(
    trellis_url: str,
    obj: dict[str, Any],
    asset_dir: Path,
    seed: int,
    timeout: float,
    steps: int,
    texture_size: int,
    decimation_target: int,
    pipeline_type: str,
    preprocess_image: bool,
    force: bool = False,
) -> Path:
    asset_dir.mkdir(parents=True, exist_ok=True)
    out_path = asset_dir / f"{obj['id']}.glb"
    meta_path = asset_dir / f"{obj['id']}.json"
    if out_path.exists() and not force:
        return out_path
    request_payload = {
        "input_text": obj["asset_prompt"],
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
            status, payload = post_json(
                trellis_url.rstrip("/") + "/generate",
                request_payload,
                timeout=30.0,
            )
            break
        except RETRYABLE_JOB_POLL_ERRORS as exc:
            if time.time() >= deadline:
                raise RuntimeError(
                    f"Trellis2 server did not accept job for {obj['id']} before timeout: {exc}"
                ) from exc
            print(
                f"[trellis2] waiting for server to accept {obj['id']} after connection error: {exc}",
                flush=True,
            )
            time.sleep(5.0)
    if status != 202:
        raise RuntimeError(f"Trellis2 server returned {status}: {payload}")
    job_id = payload["job_id"]
    while time.time() < deadline:
        try:
            status, body, content_type = get_job(trellis_url.rstrip("/") + f"/job/{job_id}", timeout=60.0)
        except RETRYABLE_JOB_POLL_ERRORS:
            time.sleep(2.0)
            continue
        if status == 200:
            out_path.write_bytes(body)
            bridge_metadata = None
            try:
                metadata_status, metadata_body, _ = get_job(
                    trellis_url.rstrip("/") + f"/job/{job_id}/metadata",
                    timeout=60.0,
                )
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
                    "job_id": job_id,
                    "object": obj,
                    "asset_path": str(out_path),
                    "content_type": content_type,
                    "bridge_metadata": bridge_metadata,
                },
            )
            return out_path
        if status == 500:
            bridge_metadata = None
            try:
                metadata_status, metadata_body, _ = get_job(
                    trellis_url.rstrip("/") + f"/job/{job_id}/metadata",
                    timeout=60.0,
                )
            except RETRYABLE_JOB_POLL_ERRORS:
                metadata_status, metadata_body = 0, b""
            if metadata_status == 200:
                try:
                    bridge_metadata = json.loads(metadata_body.decode("utf-8"))
                except Exception as exc:
                    bridge_metadata = {"metadata_parse_error": str(exc)}
            else:
                bridge_metadata = {"metadata_status": metadata_status, "metadata_body": metadata_body[:500].decode("utf-8", errors="replace")}
            write_json(
                meta_path,
                {
                    "job_id": job_id,
                    "object": obj,
                    "asset_path": str(out_path),
                    "status": "failed",
                    "server_error": body.decode("utf-8", errors="replace"),
                    "bridge_metadata": bridge_metadata,
                },
            )
            raise RuntimeError(body.decode("utf-8", errors="replace"))
        if status in {404, 410}:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            print(
                f"[trellis2] job {job_id} for {obj['id']} disappeared with status {status}; "
                "resubmitting on the available server",
                flush=True,
            )
            time.sleep(5.0)
            return generate_asset(
                trellis_url,
                obj,
                asset_dir,
                seed=seed,
                timeout=remaining,
                steps=steps,
                texture_size=texture_size,
                decimation_target=decimation_target,
                pipeline_type=pipeline_type,
                preprocess_image=preprocess_image,
                force=force,
            )
        if status != 202:
            raise RuntimeError(f"Trellis2 job {job_id} returned {status}: {body[:200]!r}")
        time.sleep(3.0)
    try:
        metadata_status, metadata_body, _ = get_job(
            trellis_url.rstrip("/") + f"/job/{job_id}/metadata",
            timeout=60.0,
        )
    except RETRYABLE_JOB_POLL_ERRORS:
        metadata_status, metadata_body = 0, b""
    bridge_metadata = None
    if metadata_status == 200:
        try:
            bridge_metadata = json.loads(metadata_body.decode("utf-8"))
        except Exception as exc:
            bridge_metadata = {"metadata_parse_error": str(exc)}
    write_json(
        meta_path,
        {
            "job_id": job_id,
            "object": obj,
            "asset_path": str(out_path),
            "status": "timeout",
            "bridge_metadata": bridge_metadata,
        },
    )
    raise TimeoutError(f"Trellis2 job timed out for {obj['id']}")


def _safe_mesh_split(mesh: trimesh.Trimesh) -> list[trimesh.Trimesh]:
    try:
        parts = list(mesh.split(only_watertight=False))
        return parts or [mesh]
    except Exception:
        return [mesh]


def _face_connected_components(mesh: trimesh.Trimesh) -> list[list[int]]:
    face_count = len(mesh.faces)
    if face_count == 0:
        return []
    parent = list(range(face_count))
    rank = [0] * face_count

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a: int, b: int) -> None:
        root_a = find(a)
        root_b = find(b)
        if root_a == root_b:
            return
        if rank[root_a] < rank[root_b]:
            root_a, root_b = root_b, root_a
        parent[root_b] = root_a
        if rank[root_a] == rank[root_b]:
            rank[root_a] += 1

    try:
        for a, b in mesh.face_adjacency:
            union(int(a), int(b))
    except Exception:
        return [list(range(face_count))]

    groups: dict[int, list[int]] = {}
    for index in range(face_count):
        groups.setdefault(find(index), []).append(index)
    return list(groups.values())


def _strip_broad_thin_components(mesh: trimesh.Trimesh, scene_bounds: np.ndarray) -> tuple[trimesh.Trimesh, list[dict[str, Any]]]:
    scene_extents = np.maximum(scene_bounds[1] - scene_bounds[0], 1e-6)
    max_scene_extent = float(scene_extents.max())
    removed: list[dict[str, Any]] = []
    remove_faces: list[int] = []
    for faces in _face_connected_components(mesh):
        if len(faces) < max(64, int(0.015 * max(len(mesh.faces), 1))):
            continue
        try:
            part = mesh.submesh([faces], append=True, repair=False)
        except Exception:
            continue
        bounds = np.asarray(part.bounds, dtype=float)
        extents = np.maximum(bounds[1] - bounds[0], 0.0)
        sorted_extents = np.sort(extents)
        broad_sheet = (
            sorted_extents[2] >= 0.62 * max_scene_extent
            and sorted_extents[1] >= 0.50 * max_scene_extent
            and sorted_extents[0] <= 0.045 * max_scene_extent
        )
        large_enough = len(faces) >= int(0.035 * max(len(mesh.faces), 1)) or float(part.area) >= 0.10 * float(mesh.area)
        if broad_sheet and large_enough:
            remove_faces.extend(faces)
            removed.append(
                {
                    "removed_faces": len(faces),
                    "bounds": bounds.round(6).tolist(),
                    "extents": extents.round(6).tolist(),
                    "area": float(part.area),
                }
            )

    if not remove_faces:
        return mesh, removed
    keep = np.ones(len(mesh.faces), dtype=bool)
    keep[np.asarray(remove_faces, dtype=int)] = False
    cleaned = mesh.copy()
    cleaned.update_faces(keep)
    cleaned.remove_unreferenced_vertices()
    return cleaned, removed


def _component_rows(mesh: trimesh.Trimesh) -> list[dict[str, Any]]:
    if len(mesh.faces) == 0:
        return []
    face_vertices = mesh.vertices[mesh.faces]
    face_areas = mesh.area_faces
    rows: list[dict[str, Any]] = []
    for index, faces in enumerate(_face_connected_components(mesh)):
        if not faces:
            continue
        faces_array = np.asarray(faces, dtype=int)
        verts = face_vertices[faces_array].reshape(-1, 3)
        bounds = np.stack([verts.min(axis=0), verts.max(axis=0)])
        rows.append(
            {
                "index": index,
                "faces": faces_array,
                "face_count": int(len(faces_array)),
                "area": float(face_areas[faces_array].sum()),
                "bounds": bounds,
                "extents": bounds[1] - bounds[0],
            }
        )
    return rows


def _strip_bbox_outlier_components(
    mesh: trimesh.Trimesh,
    significant_area: float = 0.01,
    bbox_padding: float = 0.02,
) -> tuple[trimesh.Trimesh, dict[str, Any]]:
    rows = _component_rows(mesh)
    raw_bounds = np.asarray(mesh.bounds, dtype=float)
    report: dict[str, Any] = {
        "raw_bounds": np.round(raw_bounds, 6).tolist(),
        "raw_extents": np.round(raw_bounds[1] - raw_bounds[0], 6).tolist(),
        "significant_area": float(significant_area),
        "bbox_padding": float(bbox_padding),
        "removed_components": [],
        "removed_component_count": 0,
        "removed_face_count": 0,
    }
    significant_bounds = [row["bounds"] for row in rows if float(row["area"]) >= significant_area]
    if significant_bounds:
        stacked = np.stack(significant_bounds, axis=0)
        robust_bounds = np.stack([stacked[:, 0, :].min(axis=0), stacked[:, 1, :].max(axis=0)])
    else:
        robust_bounds = raw_bounds
    report["robust_bounds"] = np.round(robust_bounds, 6).tolist()
    report["robust_extents"] = np.round(robust_bounds[1] - robust_bounds[0], 6).tolist()

    min_allowed = robust_bounds[0] - float(bbox_padding)
    max_allowed = robust_bounds[1] + float(bbox_padding)
    removed_faces: list[np.ndarray] = []
    for row in rows:
        if float(row["area"]) >= significant_area:
            continue
        bounds = row["bounds"]
        outside = bool(np.any(bounds[0] < min_allowed) or np.any(bounds[1] > max_allowed))
        if not outside:
            continue
        removed_faces.append(row["faces"])
        report["removed_components"].append(
            {
                "index": int(row["index"]),
                "face_count": int(row["face_count"]),
                "area": round(float(row["area"]), 8),
                "bounds": np.round(row["bounds"], 6).tolist(),
                "extents": np.round(row["extents"], 6).tolist(),
            }
        )

    if removed_faces:
        keep = np.ones(len(mesh.faces), dtype=bool)
        keep[np.concatenate(removed_faces)] = False
        cleaned = mesh.copy()
        cleaned.update_faces(keep)
        cleaned.remove_unreferenced_vertices()
    else:
        cleaned = mesh

    clean_bounds = np.asarray(cleaned.bounds, dtype=float)
    report["clean_bounds"] = np.round(clean_bounds, 6).tolist()
    report["clean_extents"] = np.round(clean_bounds[1] - clean_bounds[0], 6).tolist()
    report["removed_component_count"] = len(report["removed_components"])
    report["removed_face_count"] = int(sum(len(faces) for faces in removed_faces))
    return cleaned, report


def _is_ground_artifact(bounds: np.ndarray, scene_bounds: np.ndarray) -> bool:
    scene_extents = np.maximum(scene_bounds[1] - scene_bounds[0], 1e-6)
    extents = np.maximum(bounds[1] - bounds[0], 0.0)
    near_bottom = bounds[0, 2] <= scene_bounds[0, 2] + max(0.04 * scene_extents[2], 0.025)
    very_thin = extents[2] <= max(0.04 * scene_extents[2], 0.035)
    footprint_ratio = (extents[0] * extents[1]) / max(scene_extents[0] * scene_extents[1], 1e-6)
    broad = footprint_ratio >= 0.34 or (extents[0] >= 0.78 * scene_extents[0] and extents[1] >= 0.78 * scene_extents[1])
    return bool(near_bottom and very_thin and broad)


def _detect_low_horizontal_sheet_faces(mesh: trimesh.Trimesh, scene_bounds: np.ndarray) -> dict[str, Any] | None:
    if len(mesh.faces) == 0:
        return None
    scene_extents = np.maximum(scene_bounds[1] - scene_bounds[0], 1e-6)
    z_limit = scene_bounds[0, 2] + max(0.035 * scene_extents[2], 0.025)
    try:
        normals = mesh.face_normals
        centers = mesh.triangles_center
        tri = mesh.triangles
        xy_area = np.abs(
            (tri[:, 1, 0] - tri[:, 0, 0]) * (tri[:, 2, 1] - tri[:, 0, 1])
            - (tri[:, 1, 1] - tri[:, 0, 1]) * (tri[:, 2, 0] - tri[:, 0, 0])
        ) * 0.5
        low = centers[:, 2] <= z_limit
        horizontal = np.abs(normals[:, 2]) >= 0.86
        candidates = low & horizontal
        if not np.any(candidates):
            return None
        projected_area = float(xy_area[candidates].sum())
        scene_xy_area = float(scene_extents[0] * scene_extents[1])
        face_area_ratio = float(mesh.area_faces[candidates].sum()) / max(float(mesh.area), 1e-6)
        if projected_area < 0.22 * scene_xy_area or face_area_ratio < 0.18:
            return None
        return {
            "candidate_faces": int(np.count_nonzero(candidates)),
            "projected_area": projected_area,
            "scene_xy_area": scene_xy_area,
            "face_area_ratio": face_area_ratio,
            "z_limit": float(z_limit),
        }
    except Exception:
        return None


def _artifact_cleanup_policy(obj: dict[str, Any]) -> dict[str, Any]:
    text = _category_text(obj)
    is_bookshelf = "bookshelf" in text or "book shelf" in text
    is_foliage = any(keyword in text for keyword in ("plant", "potted", "foliage", "trailing"))
    if _is_protected_wall_flat_asset(obj):
        return {
            "broad_thin_component_cleanup": False,
            "bbox_fragment_cleanup": False,
            "ground_component_cleanup": False,
            "integrated_low_sheet_regeneration": False,
            "reason": "protected_wall_flat_asset_planes",
        }
    if is_foliage:
        return {
            "broad_thin_component_cleanup": False,
            "bbox_fragment_cleanup": False,
            "ground_component_cleanup": False,
            "integrated_low_sheet_regeneration": False,
            "reason": "protected_foliage_complex_components",
        }
    planar_keywords = [
        "desk",
        "table",
        "counter",
        "cabinet",
        "drawer",
        "folder",
        "document",
        "paper",
        "plate",
        "tray",
    ]
    has_legitimate_large_planes = any(keyword in text for keyword in planar_keywords)
    return {
        "broad_thin_component_cleanup": bool(is_bookshelf or not has_legitimate_large_planes),
        "bbox_fragment_cleanup": bool(is_bookshelf),
        "ground_component_cleanup": bool(is_bookshelf or not has_legitimate_large_planes),
        "integrated_low_sheet_regeneration": bool(is_bookshelf or not has_legitimate_large_planes),
        "reason": "bookshelf_background_plane_allowed"
        if is_bookshelf
        else "protected_legitimate_planar_surfaces"
        if has_legitimate_large_planes
        else "default_non_planar_asset_cleanup",
    }


def clean_asset_ground_artifacts(source_path: Path, output_path: Path, obj: dict[str, Any], force: bool = False) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not force:
        return {"object_id": obj["id"], "source": str(source_path), "output": str(output_path), "skipped": True}
    report: dict[str, Any] = {
        "object_id": obj["id"],
        "source": str(source_path),
        "output": str(output_path),
        "removed_components": 0,
        "removed_faces": 0,
        "changed": False,
        "requires_regeneration": False,
    }
    try:
        loaded = trimesh.load(source_path, force="scene")
        if not isinstance(loaded, trimesh.Scene):
            loaded = trimesh.Scene(loaded)
        scene_bounds = np.array(loaded.bounds, dtype=float)
        cleanup_policy = _artifact_cleanup_policy(obj)
        report["cleanup_policy"] = cleanup_policy
        cleaned_scene = trimesh.Scene()
        kept_count = 0

        for node in loaded.graph.nodes_geometry:
            node_transform, geom_name = loaded.graph[node]
            geom = loaded.geometry[geom_name].copy()
            geom.apply_transform(node_transform)
            removed_components = []
            if cleanup_policy["broad_thin_component_cleanup"]:
                geom, removed_components = _strip_broad_thin_components(geom, scene_bounds)
            if removed_components:
                report.setdefault("removed_broad_thin_components", []).extend(
                    [{"geometry": geom_name, **item} for item in removed_components]
                )
                report["removed_components"] += len(removed_components)
                report["removed_faces"] += int(sum(int(item.get("removed_faces", 0)) for item in removed_components))
                report["changed"] = True
            if cleanup_policy.get("bbox_fragment_cleanup"):
                geom, bbox_report = _strip_bbox_outlier_components(geom)
                if bbox_report["removed_component_count"]:
                    report.setdefault("removed_bbox_outlier_components", []).append({"geometry": geom_name, **bbox_report})
                    report["removed_components"] += int(bbox_report["removed_component_count"])
                    report["removed_faces"] += int(bbox_report["removed_face_count"])
                    report["changed"] = True
            for part_index, part in enumerate(_safe_mesh_split(geom)):
                if len(part.vertices) == 0 or len(part.faces) == 0:
                    continue
                part_bounds = np.array(part.bounds, dtype=float)
                if cleanup_policy["ground_component_cleanup"] and _is_ground_artifact(part_bounds, scene_bounds):
                    report["removed_components"] += 1
                    report["removed_faces"] += int(len(part.faces))
                    report["changed"] = True
                    continue
                integrated_sheet = (
                    _detect_low_horizontal_sheet_faces(part, scene_bounds)
                    if cleanup_policy["integrated_low_sheet_regeneration"]
                    else None
                )
                if integrated_sheet:
                    report["requires_regeneration"] = True
                    report.setdefault("integrated_broad_thin_faces", []).append(
                        {"geometry": geom_name, "part_index": part_index, **integrated_sheet}
                    )
                cleaned_scene.add_geometry(part, geom_name=f"{obj['id']}_{geom_name}_{part_index}")
                kept_count += 1

        if kept_count == 0:
            shutil.copy2(source_path, output_path)
            report["changed"] = False
            report["warning"] = "cleanup produced no kept geometry; copied source"
            return report
        if report["changed"]:
            report["artifact_action"] = "bbox_fragment_component_cleanup"
            cleaned_scene.export(output_path)
        else:
            report["artifact_action"] = "regenerate_required" if report.get("requires_regeneration") else "none"
            shutil.copy2(source_path, output_path)
        return report
    except Exception as exc:
        shutil.copy2(source_path, output_path)
        report["changed"] = False
        report["error"] = str(exc)
        return report


def clean_assets_for_scene(
    plan: dict[str, Any],
    source_dir: Path,
    output_dir: Path,
    force: bool = False,
) -> list[dict[str, Any]]:
    reports = []
    def preview_layer(obj: dict[str, Any]) -> int:
        text = _category_text(obj)
        if any(keyword in text for keyword in ("rug", "carpet", "floor covering")):
            return 0
        if str(obj.get("placement_type")) == "attached_to_wall":
            return 2
        if any(keyword in text for keyword in ("hanging", "pendant", "chandelier")):
            return 3
        return 1

    for obj in sorted(plan["objects"], key=preview_layer):
        src = source_dir / f"{obj['id']}.glb"
        dst = output_dir / f"{obj['id']}.glb"
        reports.append(clean_asset_ground_artifacts(src, dst, obj, force=force))
        meta_src = source_dir / f"{obj['id']}.json"
        if meta_src.exists():
            shutil.copy2(meta_src, output_dir / meta_src.name)
    return reports


def _regeneration_retry_object(obj: dict[str, Any]) -> dict[str, Any]:
    retry = json.loads(json.dumps(obj))
    prompt = str(retry.get("asset_prompt") or retry.get("category") or retry.get("id"))
    retry["asset_prompt"] = (
        f"{prompt}, isolated product cutout, object only, floating slightly above ground with visible underside, "
        "no floor, no ground plane, no wall, no room, no platform, no base slab, no pedestal, no plinth, "
        "no display stand, no contact shadow"
    )
    retry["_regeneration_reason"] = "integrated_broad_thin_artifact"
    return retry


def repair_assets_for_scene(
    plan: dict[str, Any],
    source_dir: Path,
    output_dir: Path,
    trellis_url: str,
    seed: int,
    timeout: float,
    steps: int,
    texture_size: int,
    decimation_target: int,
    pipeline_type: str,
    preprocess_image: bool,
    force_clean: bool = False,
    regenerate_integrated: bool = True,
) -> list[dict[str, Any]]:
    reports = []
    regenerated_raw_dir = output_dir / "_regenerated_raw"
    for index, obj in enumerate(plan["objects"]):
        src = source_dir / f"{obj['id']}.glb"
        dst = output_dir / f"{obj['id']}.glb"
        report = clean_asset_ground_artifacts(src, dst, obj, force=force_clean)
        if report.get("requires_regeneration") and regenerate_integrated:
            retry_obj = _regeneration_retry_object(obj)
            regenerated_src = generate_asset(
                trellis_url,
                retry_obj,
                regenerated_raw_dir,
                seed=seed + 5000 + index,
                timeout=timeout,
                steps=steps,
                texture_size=texture_size,
                decimation_target=decimation_target,
                pipeline_type=pipeline_type,
                preprocess_image=preprocess_image,
                force=True,
            )
            retry_report = clean_asset_ground_artifacts(regenerated_src, dst, obj, force=True)
            report["regeneration"] = {
                "enabled": True,
                "retry_asset_prompt": retry_obj["asset_prompt"],
                "raw_regenerated_asset": str(regenerated_src),
                "cleanup_report": retry_report,
            }
            report["artifact_action"] = (
                "regenerated_then_component_cleanup"
                if retry_report.get("changed")
                else "regenerated_still_requires_review"
                if retry_report.get("requires_regeneration")
                else "regenerated"
            )
        meta_src = source_dir / f"{obj['id']}.json"
        if meta_src.exists():
            shutil.copy2(meta_src, output_dir / meta_src.name)
        reports.append(report)
    return reports


def _asset_axis_rotation(axis_to_z: int, axis_sign: float = 1.0) -> np.ndarray:
    sign = -1.0 if float(axis_sign) < 0.0 else 1.0
    if axis_to_z == 0:
        # Rotate x-up assets into z-up: new_x=-old_z, new_y=old_y, new_z=old_x.
        matrix = np.eye(4)
        if sign < 0.0:
            matrix[:3, :3] = np.array([[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]])
        else:
            matrix[:3, :3] = np.array([[0.0, 0.0, -1.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0]])
        return matrix
    if axis_to_z == 1:
        # Rotate y-up assets into z-up: new_x=old_x, new_y=-old_z, new_z=old_y.
        matrix = np.eye(4)
        if sign < 0.0:
            matrix[:3, :3] = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]])
        else:
            matrix[:3, :3] = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])
        return matrix
    return np.eye(4)


def _desired_vertical_axis(obj: dict[str, Any], extents: np.ndarray) -> int:
    if "asset_axis_to_z" in obj:
        try:
            axis = int(obj["asset_axis_to_z"])
            if axis in (0, 1, 2):
                return axis
        except (TypeError, ValueError):
            pass
    # Trellis2 exports in this local pipeline are already z-up. The old
    # bbox heuristic often confused tabletops, shelves, and chair backs with
    # the vertical axis, rotating otherwise valid assets onto their sides.
    return 2


def _normalize_asset_axes(geom: trimesh.Trimesh, obj: dict[str, Any]) -> trimesh.Trimesh:
    bounds = np.array(geom.bounds, dtype=float)
    extents = np.maximum(bounds[1] - bounds[0], 1e-6)
    axis_to_z = _desired_vertical_axis(obj, extents)
    if axis_to_z == 2:
        return geom
    normalized = geom.copy()
    normalized.apply_transform(_asset_axis_rotation(axis_to_z, float(obj.get("asset_axis_to_z_sign", 1.0) or 1.0)))
    return normalized


def _load_oriented_asset_geometries(asset_path: Path, obj: dict[str, Any]) -> list[tuple[str, trimesh.Trimesh]]:
    loaded = trimesh.load(asset_path, force="scene")
    if not isinstance(loaded, trimesh.Scene):
        loaded = trimesh.Scene(loaded)
    oriented: list[tuple[str, trimesh.Trimesh]] = []
    for node in loaded.graph.nodes_geometry:
        node_transform, geom_name = loaded.graph[node]
        geom = loaded.geometry[geom_name].copy()
        geom.apply_transform(node_transform)
        geom = _normalize_asset_axes(geom, obj)
        asset_local_offset = float(obj.get("asset_local_yaw_offset_degrees", 0.0) or 0.0)
        if abs(asset_local_offset) > 1e-6:
            geom.apply_transform(trimesh.transformations.rotation_matrix(math.radians(asset_local_offset), [0, 0, 1]))
        oriented.append((geom_name, geom))
    return oriented


def _geometry_list_bounds(geometries: list[tuple[str, trimesh.Trimesh]]) -> np.ndarray:
    bounds = [np.array(geom.bounds, dtype=float) for _, geom in geometries if len(geom.vertices) > 0]
    if not bounds:
        return np.array([[0.0, 0.0, 0.0], [1e-6, 1e-6, 1e-6]], dtype=float)
    stacked = np.stack(bounds, axis=0)
    return np.array([stacked[:, 0, :].min(axis=0), stacked[:, 1, :].max(axis=0)], dtype=float)


def transform_for_bounds(bounds: np.ndarray, dims: dict[str, float], x: float, y: float, z: float, yaw: float) -> np.ndarray:
    source_center = (bounds[0] + bounds[1]) / 2.0
    source_extents = np.maximum(bounds[1] - bounds[0], 1e-6)
    target = np.array([dims["width"], dims["length"], dims["height"]], dtype=float)
    scale = target / source_extents
    to_origin = np.eye(4)
    to_origin[:3, 3] = -source_center
    to_bottom = np.eye(4)
    to_bottom[2, 3] = target[2] / 2.0
    scale_mat = np.diag([scale[0], scale[1], scale[2], 1.0])
    yaw_mat = trimesh.transformations.rotation_matrix(math.radians(yaw), [0, 0, 1])
    place = np.eye(4)
    place[:3, 3] = [x, y, z]
    return place @ yaw_mat @ to_bottom @ scale_mat @ to_origin


def add_asset_scene(main: trimesh.Scene, asset_path: Path, obj: dict[str, Any]) -> None:
    geometries = _load_oriented_asset_geometries(asset_path, obj)
    bounds = _geometry_list_bounds(geometries)
    effective_yaw = (
        float(obj.get("yaw", 0.0) or 0.0)
        + float(obj.get("footprint_yaw_offset_degrees", 0.0) or 0.0)
    )
    transform = transform_for_bounds(bounds, obj["dimensions"], obj["x"], obj["y"], obj["z"], effective_yaw)
    for geom_name, geom in geometries:
        geom = geom.copy()
        geom.apply_transform(transform)
        main.add_geometry(geom, geom_name=f"{obj['id']}_{geom_name}")


def add_box(scene: trimesh.Scene, name: str, extents: tuple[float, float, float], transform: np.ndarray, color: tuple[int, int, int, int]) -> None:
    mesh = trimesh.creation.box(extents=extents, transform=transform)
    mesh.visual.face_colors = color
    scene.add_geometry(mesh, geom_name=name)


def assemble_scene(plan: dict[str, Any], asset_dir: Path, output_glb: Path) -> None:
    room = plan["room"]
    width = room["width"]
    length = room["length"]
    height = room["height"]
    scene = trimesh.Scene()
    floor_t = trimesh.transformations.translation_matrix([width / 2.0, length / 2.0, -0.025])
    add_box(scene, "floor", (width, length, 0.05), floor_t, (210, 204, 190, 255))
    add_box(scene, "wall_north", (width, 0.08, height), trimesh.transformations.translation_matrix([width / 2.0, length + 0.04, height / 2.0]), (228, 226, 218, 180))
    add_box(scene, "wall_south", (width, 0.08, height), trimesh.transformations.translation_matrix([width / 2.0, -0.04, height / 2.0]), (228, 226, 218, 180))
    add_box(scene, "wall_west", (0.08, length, height), trimesh.transformations.translation_matrix([-0.04, length / 2.0, height / 2.0]), (228, 226, 218, 180))
    add_box(scene, "wall_east", (0.08, length, height), trimesh.transformations.translation_matrix([width + 0.04, length / 2.0, height / 2.0]), (228, 226, 218, 180))
    for obj in plan["objects"]:
        add_asset_scene(scene, asset_dir / f"{obj['id']}.glb", obj)
    output_glb.parent.mkdir(parents=True, exist_ok=True)
    scene.export(output_glb)


def assemble_scene_blender(blender_bin: str, plan_path: Path, asset_dir: Path, output_glb: Path) -> None:
    if not Path(blender_bin).exists():
        raise FileNotFoundError(f"Blender binary not found: {blender_bin}")
    script = Path(__file__).with_name("blender_assemble_sage_scene.py")
    output_glb.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        blender_bin,
        "--background",
        "--python",
        str(script),
        "--",
        "--plan",
        str(plan_path),
        "--asset-dir",
        str(asset_dir),
        "--output-glb",
        str(output_glb),
    ]
    proc = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=int(os.environ.get("SAGE_BLENDER_TIMEOUT", "900")),
        check=False,
    )
    (output_glb.parent / "blender_assemble_stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (output_glb.parent / "blender_assemble_stderr.txt").write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"Blender assembly failed with code {proc.returncode}: {proc.stderr[-1000:]}")
    if not output_glb.exists() or output_glb.stat().st_size <= 0:
        raise RuntimeError(
            "Blender assembly did not produce the expected GLB "
            f"{output_glb}: {proc.stderr[-1000:]}"
        )


def render_preview(plan: dict[str, Any], output_png: Path) -> None:
    room = plan["room"]
    margin = 80
    size = 1200
    scale = min((size - margin * 2) / room["width"], (size - margin * 2) / room["length"])
    canvas = Image.new("RGB", (size, int(room["length"] * scale + margin * 2)), (241, 236, 225))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()

    def px(x: float, y: float) -> tuple[float, float]:
        return margin + x * scale, canvas.height - margin - y * scale

    x0, y0 = px(0, 0)
    x1, y1 = px(room["width"], room["length"])
    draw.rectangle([x0, y1, x1, y0], outline=(40, 40, 40), width=5, fill=(226, 219, 204))
    for obj in plan["objects"]:
        cx, cy = px(obj["x"], obj["y"])
        effective_yaw_degrees = (
            float(obj.get("yaw", 0.0) or 0.0)
            + float(obj.get("footprint_yaw_offset_degrees", 0.0) or 0.0)
        )
        if int(_round_yaw_90(effective_yaw_degrees)) % 180 == 90:
            w = obj["dimensions"]["length"] * scale
            h = obj["dimensions"]["width"] * scale
        else:
            w = obj["dimensions"]["width"] * scale
            h = obj["dimensions"]["length"] * scale
        draw.rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], fill=(120, 155, 185), outline=(20, 20, 20))
        yaw = math.radians(effective_yaw_degrees)
        arrow_len = max(18.0, min(w, h) * 0.45)
        draw.line([cx, cy, cx + math.cos(yaw) * arrow_len, cy - math.sin(yaw) * arrow_len], fill=(220, 170, 40), width=3)
        draw.text((cx + 4, cy + 4), obj["category"], fill=(20, 20, 20), font=font)
    draw.text((margin, 25), f"{plan['scene_id']} - {plan['room_type']}", fill=(20, 20, 20), font=font)
    output_png.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_png)


def selected_scene_prompt(args: argparse.Namespace) -> str:
    if args.prompt:
        return args.prompt
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8").strip()
    return OFFICIAL_PROMPTS[args.prompt_preset]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a self-made scene using local Codex, Flux, and Trellis2.")
    parser.add_argument("--prompt-preset", default="office_task", choices=sorted(OFFICIAL_PROMPTS))
    parser.add_argument("--prompt")
    parser.add_argument("--prompt-file")
    parser.add_argument("--plan-file")
    parser.add_argument("--model")
    parser.add_argument("--output-dir", default="/data/xy/SAGE_repro/selfmade_trellis_scene")
    parser.add_argument("--trellis-url", default="http://127.0.0.1:8082")
    parser.add_argument("--trellis-pipeline-type", default="1024_cascade", choices=["512", "1024", "1024_cascade", "1536_cascade"])
    parser.add_argument("--trellis-preprocess-image", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--seed", type=int, default=700)
    parser.add_argument("--asset-timeout", type=float, default=900.0)
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--texture-size", type=int, default=2048)
    parser.add_argument("--decimation-target", type=int, default=500000)
    parser.add_argument("--max-objects", type=int, default=7)
    parser.add_argument("--layout-audit", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--clean-assets", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--force-clean-assets", action="store_true")
    parser.add_argument("--regenerate-integrated-artifacts", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--assembly-backend", choices=("blender", "trimesh"), default="blender")
    parser.add_argument("--blender-bin", default=DEFAULT_BLENDER)
    parser.add_argument("--force-assets", action="store_true")
    parser.add_argument("--use-fallback-plan", action=argparse.BooleanOptionalAction, default=False)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    scene_prompt = selected_scene_prompt(args)
    (output_dir / "selected_prompt.txt").write_text(scene_prompt + "\n", encoding="utf-8")

    if args.plan_file:
        plan = extract_json(Path(args.plan_file).read_text(encoding="utf-8"))
        plan["_planner"] = plan.get("_planner", "codex_exec_plan_file")
    elif args.use_fallback_plan:
        plan = dict(FALLBACK_PLAN)
        plan["_planner"] = "fallback"
    else:
        try:
            plan = run_codex(scene_prompt, output_dir, args.model)
            plan["_planner"] = "codex_exec"
        except Exception as exc:
            (output_dir / "codex_error.txt").write_text(str(exc), encoding="utf-8")
            plan = dict(FALLBACK_PLAN)
            plan["_planner"] = "fallback_after_codex_error"

    plan = clean_plan(plan, max_objects=args.max_objects)
    write_json(output_dir / "scene_plan_before_audit.json", plan)
    if args.layout_audit:
        plan = audit_and_repair_plan(plan, scene_prompt)
    write_json(output_dir / "scene_plan.json", plan)

    asset_dir = output_dir / "assets_trellis2"
    for index, obj in enumerate(plan["objects"]):
        asset_path = generate_asset(
            args.trellis_url,
            obj,
            asset_dir,
            seed=args.seed + index,
            timeout=args.asset_timeout,
            steps=args.steps,
            texture_size=args.texture_size,
            decimation_target=args.decimation_target,
            pipeline_type=args.trellis_pipeline_type,
            preprocess_image=args.trellis_preprocess_image,
            force=args.force_assets,
        )
        print(f"generated {obj['id']}: {asset_path}", flush=True)

    assembly_asset_dir = asset_dir
    if args.clean_assets:
        cleaned_asset_dir = output_dir / "assets_trellis2_cleaned"
        cleanup_report = repair_assets_for_scene(
            plan,
            asset_dir,
            cleaned_asset_dir,
            trellis_url=args.trellis_url,
            seed=args.seed,
            timeout=args.asset_timeout,
            steps=args.steps,
            texture_size=args.texture_size,
            decimation_target=args.decimation_target,
            pipeline_type=args.trellis_pipeline_type,
            preprocess_image=args.trellis_preprocess_image,
            force_clean=args.force_clean_assets,
            regenerate_integrated=args.regenerate_integrated_artifacts,
        )
        write_json(output_dir / "asset_cleanup_report.json", cleanup_report)
        assembly_asset_dir = cleaned_asset_dir

    scene_glb = output_dir / "scene_selfmade_trellis.glb"
    if args.assembly_backend == "blender":
        assemble_scene_blender(args.blender_bin, output_dir / "scene_plan.json", assembly_asset_dir, scene_glb)
    else:
        assemble_scene(plan, assembly_asset_dir, scene_glb)
    preview = output_dir / "preview_topdown.png"
    render_preview(plan, preview)
    summary = {
        "prompt": str(output_dir / "selected_prompt.txt"),
        "plan": str(output_dir / "scene_plan.json"),
        "raw_assets_dir": str(asset_dir),
        "assets_dir": str(assembly_asset_dir),
        "scene_glb": str(scene_glb),
        "preview": str(preview),
    }
    write_json(output_dir / "run_summary.json", summary)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
