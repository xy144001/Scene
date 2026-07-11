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


def normalized_rgba(raw: object, fallback: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        return fallback
    try:
        values = [float(value) for value in raw[:4]]
    except (TypeError, ValueError):
        return fallback
    if max(values[:3]) > 1.0:
        values[:3] = [value / 255.0 for value in values[:3]]
    alpha = values[3] if len(values) > 3 else fallback[3]
    rgba = values[:3] + [alpha]
    return tuple(max(0.0, min(1.0, value)) for value in rgba)  # type: ignore[return-value]


def shifted_color(color: tuple[float, float, float, float], factor: float) -> tuple[float, float, float, float]:
    rgb = [max(0.0, min(1.0, channel * factor)) for channel in color[:3]]
    return (rgb[0], rgb[1], rgb[2], color[3])


def make_color_ramp(
    nodes: bpy.types.Nodes,
    color_a: tuple[float, float, float, float],
    color_b: tuple[float, float, float, float],
    position_a: float = 0.2,
    position_b: float = 1.0,
) -> bpy.types.Node:
    ramp = nodes.new(type="ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = position_a
    ramp.color_ramp.elements[0].color = color_a
    ramp.color_ramp.elements[1].position = position_b
    ramp.color_ramp.elements[1].color = color_b
    return ramp


def apply_bump_from_fac(
    nodes: bpy.types.Nodes,
    links: bpy.types.NodeLinks,
    fac_output: bpy.types.NodeSocket,
    bsdf: bpy.types.Node,
    strength: float,
    distance: float,
) -> None:
    if "Normal" not in bsdf.inputs or strength <= 0.0:
        return
    bump = nodes.new(type="ShaderNodeBump")
    if "Strength" in bump.inputs:
        bump.inputs["Strength"].default_value = strength
    if "Distance" in bump.inputs:
        bump.inputs["Distance"].default_value = distance
    links.new(fac_output, bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def apply_procedural_texture(
    mat: bpy.types.Material,
    bsdf: bpy.types.Node,
    base_color: tuple[float, float, float, float],
    spec: dict[str, object],
) -> None:
    if not mat.node_tree:
        return
    texture_type = str(spec.get("texture_type") or "")
    if not texture_type.startswith("procedural_"):
        return
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    secondary = normalized_rgba(spec.get("secondary_color"), shifted_color(base_color, 1.08))
    grain = normalized_rgba(spec.get("grain_color"), shifted_color(base_color, 0.72))
    if texture_type in {"procedural_painted_plaster", "procedural_limewash", "procedural_matte_paint"}:
        noise = nodes.new(type="ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = float(spec.get("noise_scale", 42.0) or 42.0)
        noise.inputs["Detail"].default_value = float(spec.get("noise_detail", 8.0) or 8.0)
        noise.inputs["Roughness"].default_value = 0.56
        ramp = make_color_ramp(nodes, shifted_color(base_color, 0.94), secondary, 0.12, 1.0)
        links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
        if "Base Color" in bsdf.inputs:
            links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
        apply_bump_from_fac(
            nodes,
            links,
            noise.outputs["Fac"],
            bsdf,
            float(spec.get("bump_strength", 0.014) or 0.014),
            0.06,
        )
    elif texture_type == "procedural_wood_plank":
        wave = nodes.new(type="ShaderNodeTexWave")
        try:
            wave.wave_type = "RINGS"
        except Exception:
            pass
        wave.inputs["Scale"].default_value = float(spec.get("wave_scale", 18.0) or 18.0)
        wave.inputs["Distortion"].default_value = float(spec.get("wave_distortion", 8.0) or 8.0)
        ramp = make_color_ramp(nodes, grain, secondary, 0.18, 1.0)
        links.new(wave.outputs["Color"], ramp.inputs["Fac"])
        if "Base Color" in bsdf.inputs:
            links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
        apply_bump_from_fac(
            nodes,
            links,
            wave.outputs["Color"],
            bsdf,
            float(spec.get("bump_strength", 0.03) or 0.03),
            0.045,
        )
    elif texture_type == "procedural_low_pile_carpet":
        noise = nodes.new(type="ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = float(spec.get("noise_scale", 72.0) or 72.0)
        noise.inputs["Detail"].default_value = float(spec.get("noise_detail", 12.0) or 12.0)
        noise.inputs["Roughness"].default_value = 0.7
        ramp = make_color_ramp(nodes, shifted_color(base_color, 0.88), secondary, 0.25, 1.0)
        links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
        if "Base Color" in bsdf.inputs:
            links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
        apply_bump_from_fac(
            nodes,
            links,
            noise.outputs["Fac"],
            bsdf,
            float(spec.get("bump_strength", 0.018) or 0.018),
            0.035,
        )


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
            roughness = 0.82
            if isinstance(spec, dict):
                try:
                    roughness = float(spec.get("roughness", roughness) or roughness)
                except (TypeError, ValueError):
                    pass
            bsdf.inputs["Roughness"].default_value = max(0.0, min(1.0, roughness))
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
    elif isinstance(spec, dict) and mat.node_tree and bsdf:
        apply_procedural_texture(mat, bsdf, color, spec)
    return mat


def material_color_from_spec(spec: object, fallback: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    if not isinstance(spec, dict):
        return fallback
    raw_color = spec.get("base_color") or spec.get("color") or spec.get("diffuse_color")
    color = normalized_rgba(raw_color, fallback)
    try:
        alpha = float(spec.get("alpha", color[3]) or color[3])
    except (TypeError, ValueError):
        alpha = color[3]
    return (color[0], color[1], color[2], max(0.0, min(1.0, alpha)))


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
