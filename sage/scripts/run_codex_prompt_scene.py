#!/usr/bin/env python3
"""Use local Codex once to plan a SAGE-style scene, then export it to GLB.

The script keeps the expensive/fragile official agent loop out of the critical
path while preserving the user-facing flow: prompt -> layout plan -> scene JSON
-> GLB export -> quick preview.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_SOURCE_SCENE = "/data/xy/SAGE_repro/SAGE-10k/scenes/20251215_175349_layout_d990801a"
DEFAULT_OUTPUT_DIR = "/data/xy/SAGE_repro/codex_prompt_scene"
DEFAULT_EXPORT_PY = "/data/xy/SAGE_repro/SAGE-10k/kits/export_glb.py"
DEFAULT_EXPORT_VENV = "/data/xy/SAGE_repro/venv/bin/python"
DEFAULT_MUJOCO_PY = "/home/xy/PAT3D/pat3d_stage3/pat3/bin/python"


PROMPT_PRESETS = {
    "codex_office": (
        "Generate a single compact AI research office / computer lab. It should contain two work areas, "
        "desks with matching chairs, shelves for books and components, a filing cabinet, a printer station, "
        "and a visible network router. Keep believable walking space and align furniture against walls."
    ),
    "official_room_living": (
        "A living room with a coffee table holding a small toy rubik cube, a student desk positioned away "
        "from the coffee table, and a round table with a coke can positioned away from both other tables"
    ),
    "official_room_bedroom": "A bedroom.",
    "official_room_kitchen": "A medium-sized kitchen.",
    "official_room_abandoned_restroom": "A medium-sized rusty, dusty, and abandoned restroom.",
    "official_room_starry_bedroom": "A medium-sized van gogh the starry night style bedroom.",
}


def point(x: float, y: float, z: float = 0.0) -> dict[str, float]:
    return {"x": round(float(x), 4), "y": round(float(y), 4), "z": round(float(z), 4)}


def dims(width: float, length: float, height: float) -> dict[str, float]:
    return {"width": float(width), "length": float(length), "height": float(height)}


def rot(z: float) -> dict[str, float]:
    return {"x": 0, "y": 0, "z": round(float(z), 2)}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def template_objects(template_layout: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for room in template_layout["rooms"]:
        for obj in room.get("objects", []):
            result.setdefault(obj["type"], deepcopy(obj))
    return result


def asset_catalog(templates: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    catalog = []
    for object_type, obj in sorted(templates.items()):
        catalog.append(
            {
                "type": object_type,
                "source_id": obj["source_id"],
                "dimensions": obj["dimensions"],
                "description": obj["description"],
            }
        )
    return catalog


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


def fallback_plan(prompt_text: str) -> dict[str, Any]:
    return {
        "scene_id": "layout_codex_prompt_office",
        "room_type": "compact AI research office",
        "building_style": "modern practical office",
        "description": prompt_text,
        "room": {"width": 6.2, "length": 4.8, "ceiling_height": 2.7},
        "objects": [
            {"type": "desk", "id": "desk_primary", "x": 1.15, "y": 1.25, "rotation_z": 270},
            {"type": "chair", "id": "chair_primary", "x": 2.15, "y": 1.25, "rotation_z": 90},
            {"type": "desk", "id": "desk_secondary", "x": 4.75, "y": 1.05, "rotation_z": 0},
            {"type": "chair", "id": "chair_secondary", "x": 4.75, "y": 1.95, "rotation_z": 180},
            {"type": "shelf", "id": "shelf_north_left", "x": 1.1, "y": 4.55, "rotation_z": 180},
            {"type": "shelf", "id": "shelf_north_right", "x": 2.35, "y": 4.55, "rotation_z": 180},
            {"type": "cabinet", "id": "cabinet_west", "x": 0.25, "y": 3.45, "rotation_z": 270},
            {"type": "printer", "id": "printer_station", "x": 5.35, "y": 4.42, "rotation_z": 180},
            {"type": "router", "id": "router_station", "x": 5.86, "y": 4.43, "rotation_z": 180},
        ],
    }


def build_codex_prompt(prompt_text: str, catalog: list[dict[str, Any]]) -> str:
    return f"""
You are replacing the VLM planner for one SAGE reproduction run.
Use the user scene prompt to create a compact, plausible single-room layout plan.

User scene prompt:
{prompt_text}

Available reusable 3D asset types, with dimensions:
{json.dumps(catalog, indent=2)}

Return only JSON matching this shape:
{{
  "scene_id": "layout_codex_prompt_<short_name>",
  "room_type": "...",
  "building_style": "...",
  "description": "...",
  "room": {{"width": 4.5-8.0, "length": 3.5-6.0, "ceiling_height": 2.7}},
  "objects": [
    {{"type": "one available type", "id": "short_unique_id", "x": number, "y": number, "rotation_z": 0|90|180|270}}
  ]
}}

Rules:
- Use only available asset types. If the prompt asks for missing categories, approximate with the closest available office/lab asset.
- Place 8 to 14 total objects.
- Keep every object center inside the room footprint.
- Put shelves/cabinets/printers/routers near walls.
- Put chairs facing desks.
- Avoid overlaps by keeping at least 0.45m between object centers unless they are functionally paired.
- Do not include markdown, comments, or any text outside the JSON.
""".strip()


def run_codex(prompt: str, output_dir: Path, model: str | None = None) -> dict[str, Any]:
    prompt_path = output_dir / "codex_request.txt"
    response_path = output_dir / "codex_response.txt"
    prompt_path.write_text(prompt, encoding="utf-8")

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
        prompt,
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
    (output_dir / "codex_stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (output_dir / "codex_stderr.txt").write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"codex exec failed with code {proc.returncode}; see {output_dir / 'codex_stderr.txt'}")
    return extract_json(response_path.read_text(encoding="utf-8"))


def make_object(template: dict[str, Any], object_id: str, room_id: str, x: float, y: float, zrot: float) -> dict[str, Any]:
    obj = deepcopy(template)
    obj["id"] = object_id
    obj["room_id"] = room_id
    obj["position"] = point(x, y, 0.0)
    obj["rotation"] = rot(zrot)
    obj["place_id"] = "floor"
    obj["placement_constraints"] = []
    return obj


def clamp_plan(plan: dict[str, Any], templates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    room = plan.setdefault("room", {})
    room["width"] = min(max(float(room.get("width", 6.0)), 4.0), 8.0)
    room["length"] = min(max(float(room.get("length", 4.5)), 3.0), 6.0)
    room["ceiling_height"] = float(room.get("ceiling_height", 2.7))
    valid_objects = []
    seen = set()
    for idx, obj in enumerate(plan.get("objects", [])):
        object_type = obj.get("type")
        if object_type not in templates:
            continue
        width = templates[object_type]["dimensions"]["width"]
        length = templates[object_type]["dimensions"]["length"]
        x = min(max(float(obj.get("x", 1.0)), width / 2 + 0.05), room["width"] - width / 2 - 0.05)
        y = min(max(float(obj.get("y", 1.0)), length / 2 + 0.05), room["length"] - length / 2 - 0.05)
        raw_id = re.sub(r"[^a-zA-Z0-9_]+", "_", str(obj.get("id") or f"{object_type}_{idx}")).strip("_")
        object_id = f"codex_{raw_id or object_type}_{idx:02d}"
        if object_id in seen:
            object_id = f"{object_id}_{idx}"
        seen.add(object_id)
        valid_objects.append(
            {
                "type": object_type,
                "id": object_id,
                "x": x,
                "y": y,
                "rotation_z": float(obj.get("rotation_z", 0)),
            }
        )
    plan["objects"] = valid_objects[:14] or fallback_plan(plan.get("description", ""))["objects"]
    return plan


def build_layout(plan: dict[str, Any], templates: dict[str, dict[str, Any]], selected_prompt: str) -> dict[str, Any]:
    scene_id = re.sub(r"[^a-zA-Z0-9_]+", "_", str(plan.get("scene_id") or "layout_codex_prompt_scene")).strip("_")
    if not scene_id.startswith("layout_"):
        scene_id = f"layout_{scene_id}"
    room_id = "room_codex_prompt"
    room_width = float(plan["room"]["width"])
    room_length = float(plan["room"]["length"])
    ceiling = float(plan["room"].get("ceiling_height", 2.7))

    walls = [
        {"id": f"wall_{room_id}_north", "start_point": point(0, room_length), "end_point": point(room_width, room_length), "height": ceiling, "thickness": 0.1, "material": "room_6bca04af_wall"},
        {"id": f"wall_{room_id}_south", "start_point": point(0, 0), "end_point": point(room_width, 0), "height": ceiling, "thickness": 0.1, "material": "room_6bca04af_wall"},
        {"id": f"wall_{room_id}_east", "start_point": point(room_width, 0), "end_point": point(room_width, room_length), "height": ceiling, "thickness": 0.1, "material": "room_6bca04af_wall"},
        {"id": f"wall_{room_id}_west", "start_point": point(0, 0), "end_point": point(0, room_length), "height": ceiling, "thickness": 0.1, "material": "room_6bca04af_wall"},
    ]

    objects = [
        make_object(templates[item["type"]], item["id"], room_id, item["x"], item["y"], item["rotation_z"])
        for item in plan["objects"]
        if item["type"] in templates
    ]

    return {
        "id": scene_id,
        "rooms": [
            {
                "id": room_id,
                "room_type": str(plan.get("room_type") or "Codex planned room"),
                "position": point(0, 0),
                "dimensions": dims(room_width, room_length, ceiling),
                "walls": walls,
                "doors": [
                    {
                        "id": "door_codex_prompt_entry",
                        "wall_id": f"wall_{room_id}_east",
                        "position_on_wall": 0.55,
                        "width": 0.92,
                        "height": 2.05,
                        "door_type": "entry",
                        "opens_inward": True,
                        "opening": False,
                        "door_material": "Door_6",
                    }
                ],
                "objects": objects,
                "windows": [],
                "floor_material": "room_6bca04af_floor",
                "ceiling_height": ceiling,
            }
        ],
        "total_area": round(room_width * room_length, 2),
        "building_style": str(plan.get("building_style") or "practical generated scene"),
        "description": str(plan.get("description") or selected_prompt),
        "created_from_text": selected_prompt,
        "policy_analysis": {},
    }


def copy_assets(source_scene: Path, output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in ["objects", "materials"]:
        shutil.copytree(source_scene / name, output_dir / name)


def run_export(layout_path: Path, output_dir: Path) -> Path:
    export_dir = output_dir / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([DEFAULT_EXPORT_VENV, DEFAULT_EXPORT_PY, str(layout_path), str(export_dir)], check=True)
    return export_dir / layout_path.name.replace(".json", ".glb")


def run_preview(layout_path: Path, output_dir: Path) -> Path:
    preview = output_dir / "preview_topdown.png"
    subprocess.run([DEFAULT_EXPORT_VENV, "scripts/render_layout_topdown.py", str(layout_path), str(preview)], check=True)
    return preview


def run_mujoco_check(layout_path: Path) -> dict[str, Any]:
    code = f"""
from isaacsim.isaac_mcp.server import create_single_room_layout_scene_from_room, simulate_the_scene
import json, tempfile, os
layout = json.load(open({str(layout_path)!r}))
room = layout['rooms'][0]
fd, room_path = tempfile.mkstemp(suffix='.json')
os.close(fd)
json.dump(room, open(room_path, 'w'))
print(create_single_room_layout_scene_from_room({str(layout_path.parent)!r}, room_path))
print(simulate_the_scene())
os.remove(room_path)
"""
    env = os.environ.copy()
    env["SAGE_SIM_BACKEND"] = "mujoco"
    env["PYTHONPATH"] = "/home/xy/SAGE/sage/server"
    proc = subprocess.run([DEFAULT_MUJOCO_PY, "-c", code], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def selected_prompt(args: argparse.Namespace) -> str:
    if args.prompt:
        return args.prompt
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8").strip()
    return PROMPT_PRESETS[args.prompt_preset]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one local-Codex SAGE-style prompt scene.")
    parser.add_argument("--prompt-preset", default="codex_office", choices=sorted(PROMPT_PRESETS))
    parser.add_argument("--prompt-file")
    parser.add_argument("--prompt")
    parser.add_argument("--model", default=None)
    parser.add_argument("--source-scene", default=DEFAULT_SOURCE_SCENE)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--fallback-if-codex-fails", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    source_scene = Path(args.source_scene)
    output_dir = Path(args.output_dir)
    copy_assets(source_scene, output_dir)

    template_layout = load_json(source_scene / "layout_d990801a.json")
    templates = template_objects(template_layout)
    prompt_text = selected_prompt(args)
    (output_dir / "selected_prompt.txt").write_text(prompt_text + "\n", encoding="utf-8")
    codex_prompt = build_codex_prompt(prompt_text, asset_catalog(templates))

    try:
        plan = run_codex(codex_prompt, output_dir, model=args.model)
        plan["_planner"] = "codex_exec"
    except Exception as exc:
        (output_dir / "codex_error.txt").write_text(str(exc), encoding="utf-8")
        if not args.fallback_if_codex_fails:
            raise
        plan = fallback_plan(prompt_text)
        plan["_planner"] = "fallback_after_codex_error"

    plan = clamp_plan(plan, templates)
    write_json(output_dir / "codex_plan.json", plan)
    layout = build_layout(plan, templates, prompt_text)
    layout_path = output_dir / f"{layout['id']}.json"
    write_json(layout_path, layout)

    glb_path = run_export(layout_path, output_dir)
    preview_path = run_preview(layout_path, output_dir)
    mujoco_report = run_mujoco_check(layout_path)
    write_json(output_dir / "mujoco_check.json", mujoco_report)

    summary = {
        "planner": plan.get("_planner"),
        "prompt_path": str(output_dir / "selected_prompt.txt"),
        "plan_path": str(output_dir / "codex_plan.json"),
        "layout_path": str(layout_path),
        "glb_path": str(glb_path),
        "preview_path": str(preview_path),
        "mujoco_check_path": str(output_dir / "mujoco_check.json"),
    }
    write_json(output_dir / "run_summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
