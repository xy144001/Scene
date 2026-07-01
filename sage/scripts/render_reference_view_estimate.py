#!/usr/bin/env python3
"""Render an estimated reference-camera view for a TreeSAGE GLB."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser(description="Render an estimated Flux/reference camera view for a TreeSAGE scene GLB.")
    parser.add_argument("--scene-glb", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resolution-x", type=int, default=1600)
    parser.add_argument("--resolution-y", type=int, default=900)
    parser.add_argument("--camera", choices=("front_high", "front_left_high", "front_right_high"), default="front_high")
    return parser.parse_args(argv)


def clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def look_at(obj: bpy.types.Object, target: tuple[float, float, float]) -> None:
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def setup_world() -> None:
    scene = bpy.context.scene
    scene.world = scene.world or bpy.data.worlds.new("World")
    scene.world.color = (0.02, 0.02, 0.02)
    bpy.ops.object.light_add(type="AREA", location=(3.5, 2.5, 5.5))
    light = bpy.context.object
    light.name = "ReferenceEstimateKeyLight"
    light.data.energy = 700
    light.data.size = 6.0


def setup_render(output: Path, resolution_x: int, resolution_y: int) -> None:
    scene = bpy.context.scene
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except TypeError:
        scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = int(resolution_x)
    scene.render.resolution_y = int(resolution_y)
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(output)
    if hasattr(scene, "eevee") and hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = 32


def hide_front_wall(plan: dict) -> None:
    room = plan.get("room") if isinstance(plan.get("room"), dict) else {}
    width = float(room.get("width", 7.0) or 7.0)
    height = float(room.get("height", 2.7) or 2.7)
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
        min_v = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
        max_v = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
        extent = max_v - min_v
        center = (min_v + max_v) * 0.5
        is_front_wall = (
            extent.x >= width * 0.75
            and extent.z >= height * 0.65
            and extent.y <= 0.18
            and center.y <= 0.12
        )
        if is_front_wall:
            obj.hide_render = True
            obj.hide_viewport = True


def add_camera(plan: dict, mode: str) -> bpy.types.Object:
    room = plan.get("room") if isinstance(plan.get("room"), dict) else {}
    width = float(room.get("width", 7.0) or 7.0)
    length = float(room.get("length", 5.0) or 5.0)
    height = float(room.get("height", 2.7) or 2.7)
    target = (width * 0.50, length * 0.52, height * 0.32)

    if mode == "front_left_high":
        location = (width * 0.30, -length * 1.04, height * 2.05)
    elif mode == "front_right_high":
        location = (width * 0.70, -length * 1.04, height * 2.05)
    else:
        location = (width * 0.50, -length * 1.08, height * 2.05)

    cam_data = bpy.data.cameras.new("EstimatedReferenceCamera")
    cam = bpy.data.objects.new("EstimatedReferenceCamera", cam_data)
    bpy.context.collection.objects.link(cam)
    cam.location = location
    look_at(cam, target)
    cam.data.type = "PERSP"
    cam.data.lens = 32
    cam.data.sensor_width = 32
    bpy.context.scene.camera = cam
    return cam


def main() -> None:
    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    clear_scene()
    bpy.ops.import_scene.gltf(filepath=str(args.scene_glb))
    hide_front_wall(plan)
    setup_world()
    cam = add_camera(plan, args.camera)
    setup_render(args.output, args.resolution_x, args.resolution_y)
    bpy.ops.render.render(write_still=True)
    meta = {
        "scene_glb": str(args.scene_glb),
        "plan": str(args.plan),
        "output": str(args.output),
        "camera": args.camera,
        "camera_location": [round(float(v), 6) for v in cam.location],
        "camera_rotation_euler": [round(float(v), 6) for v in cam.rotation_euler],
        "lens": float(cam.data.lens),
    }
    args.output.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
