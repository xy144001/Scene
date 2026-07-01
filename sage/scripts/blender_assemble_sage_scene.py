#!/usr/bin/env python3
"""Assemble a SAGE-style scene in Blender from a JSON plan and per-object GLBs."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


TARGET_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT"}


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser(description="Assemble a scene GLB with Blender.")
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--asset-dir", required=True, type=Path)
    parser.add_argument("--output-glb", required=True, type=Path)
    return parser.parse_args(argv)


def clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def make_material(
    name: str,
    color: tuple[float, float, float, float],
    spec: object | None = None,
) -> bpy.types.Material:
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
    if bsdf:
        if "Base Color" in bsdf.inputs:
            bsdf.inputs["Base Color"].default_value = color
        if "Alpha" in bsdf.inputs:
            bsdf.inputs["Alpha"].default_value = color[3]
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = 0.82
    texture_image = None
    if isinstance(spec, dict) and spec.get("texture_image"):
        candidate = Path(str(spec.get("texture_image")))
        if candidate.exists():
            texture_image = candidate
    if texture_image and mat.node_tree and bsdf:
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        tex = nodes.new(type="ShaderNodeTexImage")
        tex.name = "sampled_floor_image_texture" if name.startswith("floor") else "sampled_image_texture"
        tex.image = bpy.data.images.load(str(texture_image), check_existing=True)
        tex.extension = "REPEAT"
        links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def material_color_from_spec(spec: object, fallback: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    if not isinstance(spec, dict):
        return fallback
    raw_color = spec.get("base_color") or spec.get("color") or spec.get("diffuse_color")
    if not isinstance(raw_color, (list, tuple)) or len(raw_color) < 3:
        return fallback
    try:
        values = [float(value) for value in raw_color[:4]]
    except (TypeError, ValueError):
        return fallback
    if max(values[:3]) > 1.0:
        values[:3] = [value / 255.0 for value in values[:3]]
    alpha = float(spec.get("alpha", values[3] if len(values) > 3 else fallback[3]))
    rgba = values[:3] + [alpha]
    return tuple(max(0.0, min(1.0, value)) for value in rgba)  # type: ignore[return-value]


def material_by_name(
    name: str,
    color: tuple[float, float, float, float],
    spec: object | None = None,
) -> bpy.types.Material:
    existing = bpy.data.materials.get(name)
    if existing:
        return existing
    return make_material(name, color, spec)


def is_rug_plan(obj_plan: dict) -> bool:
    text = " ".join(
        str(obj_plan.get(key, ""))
        for key in ("id", "category", "semantic_class", "layout_role", "description", "asset_prompt")
    )
    normalized = text.lower().replace("_", " ")
    return any(keyword in normalized for keyword in ("rug", "carpet", "floor mat", "area rug"))


def apply_material_override(objects: list[bpy.types.Object], mat: bpy.types.Material) -> None:
    for obj in objects:
        data = getattr(obj, "data", None)
        if obj.type not in TARGET_TYPES or data is None or not hasattr(data, "materials"):
            continue
        data.materials.clear()
        data.materials.append(mat)


def add_box(name: str, center: tuple[float, float, float], extents: tuple[float, float, float], mat: bpy.types.Material) -> None:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=center)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = extents
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)


def add_rug_underlay(obj_plan: dict, mat: bpy.types.Material) -> None:
    dims = obj_plan.get("dimensions") if isinstance(obj_plan.get("dimensions"), dict) else {}
    width = float(dims.get("width", 1.0) or 1.0)
    length = float(dims.get("length", 1.0) or 1.0)
    height = min(max(float(dims.get("height", 0.018) or 0.018), 0.008), 0.024)
    x = float(obj_plan.get("x", 0.0) or 0.0)
    y = float(obj_plan.get("y", 0.0) or 0.0)
    z = float(obj_plan.get("z", 0.0) or 0.0) + height * 0.5 + 0.002
    yaw = math.radians(
        float(obj_plan.get("yaw", 0.0) or 0.0)
        + float(obj_plan.get("footprint_yaw_offset_degrees", 0.0) or 0.0)
    )
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x, y, z))
    obj = bpy.context.object
    obj.name = f"{obj_plan.get('id', 'rug')}_visual_underlay"
    obj.dimensions = (width, length, height)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.rotation_euler[2] = yaw
    obj.data.materials.append(mat)


def add_room(room: dict[str, object]) -> None:
    width = float(room["width"])
    length = float(room["length"])
    height = float(room["height"])
    material_plan = room.get("materials") if isinstance(room.get("materials"), dict) else {}
    walls_plan = material_plan.get("walls") if isinstance(material_plan, dict) and isinstance(material_plan.get("walls"), dict) else {}
    global_wall_plan = material_plan.get("global_wall") if isinstance(material_plan, dict) else None
    floor_plan = material_plan.get("floor") if isinstance(material_plan, dict) else None
    floor_mat = make_material(
        "floor_warm_gray",
        material_color_from_spec(floor_plan, (0.82, 0.80, 0.74, 1.0)),
        floor_plan,
    )
    default_wall_color = material_color_from_spec(global_wall_plan, (0.89, 0.885, 0.855, 1.0))
    wall_mats = {
        wall_id: make_material(
            f"{wall_id}_material",
            material_color_from_spec(walls_plan.get(wall_id), default_wall_color) if isinstance(walls_plan, dict) else default_wall_color,
            walls_plan.get(wall_id) if isinstance(walls_plan, dict) else global_wall_plan,
        )
        for wall_id in ("wall_north", "wall_south", "wall_west", "wall_east")
    }
    add_box("floor", (width / 2.0, length / 2.0, -0.025), (width, length, 0.05), floor_mat)
    add_box("wall_north", (width / 2.0, length + 0.04, height / 2.0), (width, 0.08, height), wall_mats["wall_north"])
    add_box("wall_south", (width / 2.0, -0.04, height / 2.0), (width, 0.08, height), wall_mats["wall_south"])
    add_box("wall_west", (-0.04, length / 2.0, height / 2.0), (0.08, length, height), wall_mats["wall_west"])
    add_box("wall_east", (width + 0.04, length / 2.0, height / 2.0), (0.08, length, height), wall_mats["wall_east"])


def imported_objects(before: set[bpy.types.Object]) -> list[bpy.types.Object]:
    return [obj for obj in bpy.context.scene.objects if obj not in before]


def mesh_bbox_world(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    corners: list[Vector] = []
    for obj in objects:
        if obj.type not in TARGET_TYPES:
            continue
        for corner in obj.bound_box:
            corners.append(obj.matrix_world @ Vector(corner))
    if not corners:
        raise RuntimeError("Imported asset has no renderable geometry.")
    min_v = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
    max_v = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
    return min_v, max_v


def axis_to_z_matrix(axis_to_z: int, axis_sign: float = 1.0) -> Matrix:
    sign = -1.0 if float(axis_sign) < 0.0 else 1.0
    if axis_to_z == 0:
        if sign < 0.0:
            return Matrix(((0.0, 0.0, 1.0, 0.0), (0.0, 1.0, 0.0, 0.0), (-1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
        return Matrix(((0.0, 0.0, -1.0, 0.0), (0.0, 1.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
    if axis_to_z == 1:
        if sign < 0.0:
            return Matrix(((1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, -1.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
        return Matrix(((1.0, 0.0, 0.0, 0.0), (0.0, 0.0, -1.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
    return Matrix.Identity(4)


def parent_roots(objects: list[bpy.types.Object], root: bpy.types.Object) -> None:
    imported_set = set(objects)
    root_candidates = [obj for obj in objects if obj.parent not in imported_set]
    for obj in root_candidates:
        world = obj.matrix_world.copy()
        obj.parent = root
        obj.matrix_world = world


def transform_imported_asset(objects: list[bpy.types.Object], obj_plan: dict) -> None:
    axis_matrix = axis_to_z_matrix(
        int(obj_plan.get("asset_axis_to_z", 2)),
        float(obj_plan.get("asset_axis_to_z_sign", 1.0) or 1.0),
    )
    if axis_matrix != Matrix.Identity(4):
        for obj in objects:
            if obj.type in TARGET_TYPES:
                obj.matrix_world = axis_matrix @ obj.matrix_world

    asset_local_offset = float(obj_plan.get("asset_local_yaw_offset_degrees", 0.0) or 0.0)
    if abs(asset_local_offset) > 1e-6:
        local_front_matrix = Matrix.Rotation(math.radians(asset_local_offset), 4, "Z")
        for obj in objects:
            if obj.type in TARGET_TYPES:
                obj.matrix_world = local_front_matrix @ obj.matrix_world

    renderables = [obj for obj in objects if obj.type in TARGET_TYPES]
    min_v, max_v = mesh_bbox_world(renderables)
    center = (min_v + max_v) * 0.5
    extents = max_v - min_v
    dims = obj_plan["dimensions"]
    target = Vector((float(dims["width"]), float(dims["length"]), float(dims["height"])))
    scale = Vector(
        (
            target.x / max(float(extents.x), 1e-6),
            target.y / max(float(extents.y), 1e-6),
            target.z / max(float(extents.z), 1e-6),
        )
    )

    root = bpy.data.objects.new(f"{obj_plan['id']}_root", None)
    bpy.context.scene.collection.objects.link(root)
    parent_roots(objects, root)

    yaw = math.radians(
        float(obj_plan.get("yaw", 0.0) or 0.0)
        + float(obj_plan.get("footprint_yaw_offset_degrees", 0.0) or 0.0)
    )
    final_matrix = (
        Matrix.Translation((float(obj_plan["x"]), float(obj_plan["y"]), float(obj_plan.get("z", 0.0))))
        @ Matrix.Rotation(yaw, 4, "Z")
        @ Matrix.Translation((0.0, 0.0, target.z / 2.0))
        @ Matrix.Diagonal((scale.x, scale.y, scale.z, 1.0))
        @ Matrix.Translation((-center.x, -center.y, -center.z))
    )
    root.matrix_world = final_matrix


def import_asset(asset_path: Path, obj_plan: dict) -> None:
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=str(asset_path))
    objects = imported_objects(before)
    for imported in objects:
        imported.name = f"{obj_plan['id']}_{imported.name}"
        if getattr(imported, "data", None):
            imported.data.name = f"{obj_plan['id']}_{imported.data.name}"
    transform_imported_asset(objects, obj_plan)
    if is_rug_plan(obj_plan):
        rug_mat = material_by_name("rug_visual_separate_from_floor", (0.86, 0.83, 0.74, 1.0))
        apply_material_override(objects, rug_mat)
        add_rug_underlay(obj_plan, rug_mat)


def main() -> None:
    args = parse_args()
    print(f"loading plan: {args.plan}", flush=True)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    clear_scene()
    print("adding room", flush=True)
    add_room(plan["room"])
    for obj in plan.get("objects", []):
        asset_path = args.asset_dir / f"{obj['id']}.glb"
        if not asset_path.exists():
            raise FileNotFoundError(f"Missing asset for {obj['id']}: {asset_path}")
        print(f"importing {obj['id']}: {asset_path}", flush=True)
        import_asset(asset_path, obj)
        print(f"imported {obj['id']}", flush=True)

    args.output_glb.parent.mkdir(parents=True, exist_ok=True)
    print(f"exporting scene: {args.output_glb}", flush=True)
    bpy.ops.export_scene.gltf(filepath=str(args.output_glb), export_format="GLB")
    print(json.dumps({"output_glb": str(args.output_glb)}, indent=2), flush=True)


if __name__ == "__main__":
    main()
