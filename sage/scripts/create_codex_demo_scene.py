#!/usr/bin/env python3
"""Create a small Codex-planned demo scene using already-downloaded SAGE assets."""

from __future__ import annotations

import argparse
import json
import shutil
from copy import deepcopy
from pathlib import Path


def point(x: float, y: float, z: float = 0.0) -> dict[str, float]:
    return {"x": x, "y": y, "z": z}


def dims(width: float, length: float, height: float) -> dict[str, float]:
    return {"width": width, "length": length, "height": height}


def rot(z: float) -> dict[str, float]:
    return {"x": 0, "y": 0, "z": z}


def find_object(layout: dict, object_type: str) -> dict:
    for room in layout["rooms"]:
        for obj in room.get("objects", []):
            if obj.get("type") == object_type:
                return deepcopy(obj)
    raise KeyError(f"Missing object type in template scene: {object_type}")


def make_object(template: dict, object_id: str, x: float, y: float, zrot: float, place_id: str = "floor") -> dict:
    obj = deepcopy(template)
    obj["id"] = object_id
    obj["room_id"] = "room_codex_office"
    obj["position"] = point(x, y, 0.0)
    obj["rotation"] = rot(zrot)
    obj["place_id"] = place_id
    obj["placement_constraints"] = []
    return obj


def build_layout(template_layout: dict) -> dict:
    desk = find_object(template_layout, "desk")
    chair = find_object(template_layout, "chair")
    shelf = find_object(template_layout, "shelf")
    cabinet = find_object(template_layout, "cabinet")
    printer = find_object(template_layout, "printer")
    router = find_object(template_layout, "router")

    room_id = "room_codex_office"
    walls = [
        {
            "id": "wall_room_codex_office_north",
            "start_point": point(0.0, 4.5),
            "end_point": point(6.0, 4.5),
            "height": 2.7,
            "thickness": 0.1,
            "material": "room_6bca04af_wall",
        },
        {
            "id": "wall_room_codex_office_south",
            "start_point": point(0.0, 0.0),
            "end_point": point(6.0, 0.0),
            "height": 2.7,
            "thickness": 0.1,
            "material": "room_6bca04af_wall",
        },
        {
            "id": "wall_room_codex_office_east",
            "start_point": point(6.0, 0.0),
            "end_point": point(6.0, 4.5),
            "height": 2.7,
            "thickness": 0.1,
            "material": "room_6bca04af_wall",
        },
        {
            "id": "wall_room_codex_office_west",
            "start_point": point(0.0, 0.0),
            "end_point": point(0.0, 4.5),
            "height": 2.7,
            "thickness": 0.1,
            "material": "room_6bca04af_wall",
        },
    ]

    objects = [
        make_object(desk, "codex_desk_main", 1.15, 1.25, 270),
        make_object(chair, "codex_chair_main", 2.15, 1.25, 90),
        make_object(desk, "codex_desk_side", 4.55, 1.00, 0),
        make_object(chair, "codex_chair_side", 4.55, 1.85, 180),
        make_object(shelf, "codex_shelf_north_left", 1.05, 4.27, 180),
        make_object(shelf, "codex_shelf_north_right", 2.25, 4.27, 180),
        make_object(cabinet, "codex_cabinet_west", 0.25, 3.35, 270),
        make_object(printer, "codex_printer_corner", 5.25, 4.18, 180),
        make_object(router, "codex_router_corner", 5.75, 4.20, 180),
    ]

    return {
        "id": "layout_codex_demo_office",
        "rooms": [
            {
                "id": room_id,
                "room_type": "compact AI research office",
                "position": point(0.0, 0.0),
                "dimensions": dims(6.0, 4.5, 2.7),
                "walls": walls,
                "doors": [
                    {
                        "id": "door_codex_office_entry",
                        "wall_id": "wall_room_codex_office_east",
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
                "ceiling_height": 2.7,
            }
        ],
        "total_area": 27.0,
        "building_style": "modern practical office",
        "description": "A compact Codex-planned office scene with two work desks, chairs, storage, network equipment, and shelves.",
        "created_from_text": "Create a compact AI research office suitable for previewing the SAGE scene pipeline.",
        "policy_analysis": {},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-scene", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    source = Path(args.source_scene)
    output = Path(args.output_dir)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    for name in ["objects", "materials"]:
        shutil.copytree(source / name, output / name)

    template_layout = json.loads((source / "layout_d990801a.json").read_text(encoding="utf-8"))
    layout = build_layout(template_layout)
    (output / "layout_codex_demo_office.json").write_text(json.dumps(layout, indent=2), encoding="utf-8")
    print(output / "layout_codex_demo_office.json")


if __name__ == "__main__":
    main()
