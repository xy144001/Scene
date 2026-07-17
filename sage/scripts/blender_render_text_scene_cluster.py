#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector


TARGET_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT"}


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser(description="Render a local text-scene object cluster.")
    parser.add_argument("--scene-glb", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cluster", choices=("desk_chair",), default="desk_chair")
    parser.add_argument("--resolution-x", type=int, default=1200)
    parser.add_argument("--resolution-y", type=int, default=900)
    return parser.parse_args(argv)


def clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def look_at(obj: bpy.types.Object, target: Vector) -> None:
    direction = target - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def setup_world() -> None:
    world = bpy.data.worlds.new("ClusterWorld")
    world.use_nodes = True
    bpy.context.scene.world = world
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.94, 0.935, 0.92, 1.0)
    bg.inputs[1].default_value = 0.8


def add_area_light(name: str, location: tuple[float, float, float], energy: float, size: float) -> None:
    data = bpy.data.lights.new(name=name, type="AREA")
    data.energy = energy
    data.size = size
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    look_at(obj, Vector((0.0, 0.0, 0.8)))


def setup_lighting() -> None:
    add_area_light("ClusterKey", (3.0, -3.0, 4.0), 3200.0, 4.0)
    add_area_light("ClusterFill", (-3.0, 2.0, 3.0), 1200.0, 5.0)


def is_cluster_object(obj: bpy.types.Object, keywords: tuple[str, ...]) -> bool:
    text = f"{obj.name} {obj.data.name if getattr(obj, 'data', None) else ''}".lower()
    return any(keyword in text for keyword in keywords)


def visible_renderable_objects() -> list[bpy.types.Object]:
    return [obj for obj in bpy.context.scene.objects if obj.type in TARGET_TYPES and not obj.hide_render]


def mesh_bbox_world(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    corners: list[Vector] = []
    for obj in objects:
        for corner in obj.bound_box:
            corners.append(obj.matrix_world @ Vector(corner))
    if not corners:
        raise RuntimeError("No visible cluster geometry found.")
    return (
        Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners))),
        Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners))),
    )


def object_from_plan(plan: dict, object_id: str) -> dict | None:
    for obj in plan.get("objects", []):
        if isinstance(obj, dict) and str(obj.get("id")) == object_id:
            return obj
    return None


def setup_camera(plan: dict, output: Path, resolution_x: int, resolution_y: int) -> bpy.types.Object:
    objects = visible_renderable_objects()
    min_v, max_v = mesh_bbox_world(objects)
    center = (min_v + max_v) * 0.5
    extent = max_v - min_v
    scale = max(float(extent.x), float(extent.y), float(extent.z), 1.0)

    desk = object_from_plan(plan, "desk")
    chair = object_from_plan(plan, "office_chair")
    if desk and chair:
        dx = float(desk.get("x", 0.0)) - float(chair.get("x", 0.0))
        dy = float(desk.get("y", 0.0)) - float(chair.get("y", 0.0))
        direction = Vector((dx, dy, 0.0))
        if direction.length < 1e-5:
            direction = Vector((0.0, 1.0, 0.0))
        direction.normalize()
        side = Vector((-direction.y, direction.x, 0.0))
        # Render from the side of the desk-chair axis. A behind-the-chair view
        # makes correct chairs look like their backrest blocks the desktop.
        location = center + side * scale * 2.15 - direction * scale * 0.2 + Vector((0.0, 0.0, scale * 0.9))
    else:
        location = center + Vector((scale * 1.4, -scale * 1.8, scale * 1.1))

    cam_data = bpy.data.cameras.new("ClusterCamera")
    cam = bpy.data.objects.new("ClusterCamera", cam_data)
    bpy.context.collection.objects.link(cam)
    cam.location = location
    look_at(cam, center + Vector((0.0, 0.0, float(extent.z) * 0.08)))
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = max(float(extent.x), float(extent.y), 1.0) * 1.45
    bpy.context.scene.camera = cam

    scene = bpy.context.scene
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except Exception:
        scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = int(resolution_x)
    scene.render.resolution_y = int(resolution_y)
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(output)
    if hasattr(scene, "eevee") and hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = 32
    return cam


def main() -> None:
    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    clear_scene()
    bpy.ops.import_scene.gltf(filepath=str(args.scene_glb))
    keywords = ("desk", "office_chair")
    for obj in bpy.context.scene.objects:
        if obj.type not in TARGET_TYPES:
            continue
        keep = is_cluster_object(obj, keywords)
        obj.hide_render = not keep
        obj.hide_viewport = not keep
    setup_world()
    setup_lighting()
    cam = setup_camera(plan, args.output, args.resolution_x, args.resolution_y)
    bpy.ops.render.render(write_still=True)
    meta = {
        "scene_glb": str(args.scene_glb),
        "plan": str(args.plan),
        "output": str(args.output),
        "cluster": args.cluster,
        "camera_location": [round(float(v), 6) for v in cam.location],
        "camera_rotation_euler": [round(float(v), 6) for v in cam.rotation_euler],
    }
    args.output.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
