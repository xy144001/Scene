from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import trimesh


def _color(mesh: trimesh.Trimesh, rgba: tuple[int, int, int, int]) -> trimesh.Trimesh:
    mesh.visual = trimesh.visual.TextureVisuals(
        material=trimesh.visual.material.PBRMaterial(
            baseColorFactor=[float(channel) / 255.0 for channel in rgba],
            metallicFactor=0.0,
            roughnessFactor=0.72,
        )
    )
    mesh.visual.vertex_colors = rgba
    return mesh


def _add_box(
    scene: trimesh.Scene,
    name: str,
    extents: tuple[float, float, float],
    center: tuple[float, float, float],
    rgba: tuple[int, int, int, int],
) -> None:
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation(center)
    scene.add_geometry(_color(mesh, rgba), geom_name=name)


def _add_cylinder(
    scene: trimesh.Scene,
    name: str,
    radius: float,
    height: float,
    center: tuple[float, float, float],
    rgba: tuple[int, int, int, int],
    sections: int = 32,
) -> None:
    mesh = trimesh.creation.cylinder(radius=radius, height=height, sections=sections)
    mesh.apply_translation(center)
    scene.add_geometry(_color(mesh, rgba), geom_name=name)


def _add_sphere(
    scene: trimesh.Scene,
    name: str,
    scale: tuple[float, float, float],
    center: tuple[float, float, float],
    rgba: tuple[int, int, int, int],
) -> None:
    mesh = trimesh.creation.icosphere(subdivisions=2, radius=1.0)
    mesh.apply_scale(scale)
    mesh.apply_translation(center)
    scene.add_geometry(_color(mesh, rgba), geom_name=name)


def make_rug() -> trimesh.Scene:
    scene = trimesh.Scene()
    _add_box(scene, "base", (2.0, 1.25, 0.035), (0, 0, 0.0175), (80, 122, 100, 255))
    _add_box(scene, "border_n", (2.08, 0.06, 0.012), (0, 0.655, 0.047), (214, 184, 98, 255))
    _add_box(scene, "border_s", (2.08, 0.06, 0.012), (0, -0.655, 0.047), (214, 184, 98, 255))
    _add_box(scene, "border_w", (0.06, 1.25, 0.012), (-1.03, 0, 0.047), (214, 184, 98, 255))
    _add_box(scene, "border_e", (0.06, 1.25, 0.012), (1.03, 0, 0.047), (214, 184, 98, 255))
    for i, x in enumerate([-0.72, -0.36, 0.0, 0.36, 0.72]):
        _add_box(scene, f"gold_motif_{i}", (0.12, 0.95, 0.01), (x, 0, 0.055), (224, 204, 130, 255))
    for i, y in enumerate([-0.38, 0.0, 0.38]):
        _add_box(scene, f"blue_band_{i}", (1.65, 0.055, 0.01), (0, y, 0.06), (54, 93, 123, 255))
    return scene


def make_table() -> trimesh.Scene:
    scene = trimesh.Scene()
    _add_box(scene, "top", (1.35, 0.82, 0.10), (0, 0, 0.72), (35, 88, 135, 255))
    _add_box(scene, "gold_trim_front", (1.43, 0.045, 0.08), (0, -0.435, 0.72), (213, 172, 86, 255))
    _add_box(scene, "gold_trim_back", (1.43, 0.045, 0.08), (0, 0.435, 0.72), (213, 172, 86, 255))
    _add_box(scene, "gold_trim_left", (0.045, 0.86, 0.08), (-0.705, 0, 0.72), (213, 172, 86, 255))
    _add_box(scene, "gold_trim_right", (0.045, 0.86, 0.08), (0.705, 0, 0.72), (213, 172, 86, 255))
    for i, (x, y) in enumerate([(-0.55, -0.32), (0.55, -0.32), (-0.55, 0.32), (0.55, 0.32)]):
        _add_cylinder(scene, f"leg_{i}", 0.055, 0.70, (x, y, 0.35), (176, 127, 54, 255), sections=12)
    return scene


def make_lounge_chair() -> trimesh.Scene:
    scene = trimesh.Scene()
    green = (25, 120, 82, 255)
    dark = (54, 48, 42, 255)
    _add_box(scene, "seat", (0.78, 0.70, 0.18), (0, 0, 0.38), green)
    _add_box(scene, "back", (0.78, 0.12, 0.58), (0, 0.34, 0.68), green)
    _add_box(scene, "left_arm", (0.12, 0.68, 0.35), (-0.45, 0.02, 0.52), green)
    _add_box(scene, "right_arm", (0.12, 0.68, 0.35), (0.45, 0.02, 0.52), green)
    _add_box(scene, "front_rail", (0.86, 0.06, 0.08), (0, -0.36, 0.30), dark)
    for i, (x, y) in enumerate([(-0.32, -0.24), (0.32, -0.24), (-0.32, 0.24), (0.32, 0.24)]):
        _add_cylinder(scene, f"leg_{i}", 0.035, 0.34, (x, y, 0.17), dark, sections=10)
    return scene


def make_cream_chair() -> trimesh.Scene:
    scene = make_lounge_chair()
    for geom in scene.geometry.values():
        if hasattr(geom.visual, "vertex_colors"):
            colors = geom.visual.vertex_colors
            green_mask = colors[:, 1] > colors[:, 0]
            colors[green_mask] = (228, 214, 180, 255)
    return scene


def make_ottoman() -> trimesh.Scene:
    scene = trimesh.Scene()
    _add_box(scene, "tufted_body", (0.78, 0.78, 0.34), (0, 0, 0.18), (30, 132, 91, 255))
    for i, x in enumerate([-0.24, 0.0, 0.24]):
        _add_box(scene, f"tuft_x_{i}", (0.018, 0.72, 0.018), (x, 0, 0.36), (18, 95, 65, 255))
    for i, y in enumerate([-0.24, 0.0, 0.24]):
        _add_box(scene, f"tuft_y_{i}", (0.72, 0.018, 0.018), (0, y, 0.365), (18, 95, 65, 255))
    return scene


def make_pouf() -> trimesh.Scene:
    scene = trimesh.Scene()
    _add_cylinder(scene, "body", 0.40, 0.34, (0, 0, 0.17), (37, 91, 160, 255), sections=48)
    _add_cylinder(scene, "top_stitch", 0.34, 0.035, (0, 0, 0.355), (65, 122, 190, 255), sections=48)
    for i, angle in enumerate(np.linspace(0, 2 * np.pi, 8, endpoint=False)):
        _add_box(
            scene,
            f"stitch_{i}",
            (0.035, 0.40, 0.025),
            (0.18 * np.cos(angle), 0.18 * np.sin(angle), 0.38),
            (211, 174, 88, 255),
        )
    return scene


def make_door() -> trimesh.Scene:
    scene = trimesh.Scene()
    wood = (129, 78, 44, 255)
    gold = (203, 163, 82, 255)
    _add_box(scene, "door_panel", (0.86, 0.055, 1.62), (0, 0, 0.81), wood)
    _add_box(scene, "frame_left", (0.075, 0.075, 1.72), (-0.49, 0, 0.86), gold)
    _add_box(scene, "frame_right", (0.075, 0.075, 1.72), (0.49, 0, 0.86), gold)
    _add_box(scene, "frame_top", (1.05, 0.075, 0.075), (0, 0, 1.68), gold)
    _add_box(scene, "inner_inlay", (0.42, 0.065, 0.80), (0, -0.01, 0.74), (87, 49, 30, 255))
    _add_box(scene, "knob", (0.055, 0.075, 0.055), (0.32, -0.045, 0.82), gold)
    return scene


def make_white_double_closet_door() -> trimesh.Scene:
    scene = trimesh.Scene()
    white = (238, 234, 224, 255)
    shadow = (196, 190, 178, 255)
    dark = (36, 31, 28, 255)
    _add_box(scene, "left_panel", (0.52, 0.035, 1.82), (-0.27, 0, 0.91), white)
    _add_box(scene, "right_panel", (0.52, 0.035, 1.82), (0.27, 0, 0.91), white)
    _add_box(scene, "center_gap", (0.018, 0.041, 1.78), (0, -0.004, 0.91), shadow)
    for side, cx in (("left", -0.27), ("right", 0.27)):
        _add_box(scene, f"{side}_inset_top", (0.34, 0.043, 0.46), (cx, -0.006, 1.32), (226, 222, 214, 255))
        _add_box(scene, f"{side}_inset_bottom", (0.34, 0.043, 0.62), (cx, -0.006, 0.56), (226, 222, 214, 255))
        _add_box(scene, f"{side}_rail_top", (0.44, 0.048, 0.035), (cx, -0.01, 1.58), shadow)
        _add_box(scene, f"{side}_rail_mid", (0.44, 0.048, 0.035), (cx, -0.01, 1.03), shadow)
        _add_box(scene, f"{side}_rail_bottom", (0.44, 0.048, 0.035), (cx, -0.01, 0.22), shadow)
    _add_cylinder(scene, "left_knob", 0.035, 0.035, (-0.055, -0.035, 0.86), dark, sections=16)
    _add_cylinder(scene, "right_knob", 0.035, 0.035, (0.055, -0.035, 0.86), dark, sections=16)
    return scene


def make_window() -> trimesh.Scene:
    scene = trimesh.Scene()
    frame = (42, 45, 44, 255)
    trim = (225, 218, 202, 255)
    _add_box(scene, "left_frame", (0.055, 0.065, 1.25), (-0.34, 0, 0.625), frame)
    _add_box(scene, "right_frame", (0.055, 0.065, 1.25), (0.34, 0, 0.625), frame)
    _add_box(scene, "top_frame", (0.73, 0.065, 0.055), (0, 0, 1.235), frame)
    _add_box(scene, "bottom_frame", (0.73, 0.065, 0.055), (0, 0, 0.055), frame)
    for i, x in enumerate([-0.115, 0.115]):
        _add_box(scene, f"vertical_mullion_{i}", (0.032, 0.07, 1.16), (x, -0.006, 0.61), frame)
    for i, z in enumerate([0.34, 0.62, 0.90]):
        _add_box(scene, f"horizontal_mullion_{i}", (0.62, 0.07, 0.032), (0, -0.006, z), frame)
    _add_box(scene, "thin_sill", (0.78, 0.085, 0.045), (0, -0.012, 0.0225), trim)
    return scene


def make_lantern() -> trimesh.Scene:
    scene = trimesh.Scene()
    _add_cylinder(scene, "body", 0.28, 0.62, (0, 0, 0.47), (222, 207, 165, 255), sections=8)
    _add_cylinder(scene, "glass", 0.22, 0.52, (0, 0, 0.47), (245, 226, 170, 120), sections=16)
    _add_cylinder(scene, "top", 0.20, 0.12, (0, 0, 0.84), (158, 126, 72, 255), sections=12)
    _add_cylinder(scene, "bottom", 0.20, 0.08, (0, 0, 0.12), (158, 126, 72, 255), sections=12)
    _add_box(scene, "hanger", (0.06, 0.06, 0.30), (0, 0, 1.02), (158, 126, 72, 255))
    return scene


def make_floor_lamp() -> trimesh.Scene:
    scene = trimesh.Scene()
    _add_cylinder(scene, "base", 0.22, 0.06, (0, 0, 0.03), (150, 111, 58, 255), sections=32)
    _add_cylinder(scene, "pole", 0.035, 1.18, (0, 0, 0.65), (160, 120, 62, 255), sections=16)
    _add_cylinder(scene, "shade", 0.24, 0.36, (0, 0, 1.35), (226, 202, 143, 255), sections=24)
    _add_cylinder(scene, "cap", 0.08, 0.05, (0, 0, 1.56), (150, 111, 58, 255), sections=16)
    return scene


def make_potted_plant() -> trimesh.Scene:
    scene = trimesh.Scene()
    _add_cylinder(scene, "pot", 0.24, 0.34, (0, 0, 0.17), (113, 113, 108, 255), sections=24)
    _add_cylinder(scene, "soil", 0.21, 0.03, (0, 0, 0.355), (68, 54, 42, 255), sections=24)
    for i, angle in enumerate(np.linspace(0, 2 * np.pi, 7, endpoint=False)):
        x = 0.17 * np.cos(angle)
        y = 0.17 * np.sin(angle)
        _add_cylinder(scene, f"stem_{i}", 0.015, 0.38, (x * 0.35, y * 0.35, 0.56), (52, 95, 58, 255), sections=8)
        _add_sphere(scene, f"leaf_{i}", (0.16, 0.07, 0.035), (x, y, 0.78), (44, 126, 70, 255))
    return scene


def make_round_tabletop_plant() -> trimesh.Scene:
    scene = trimesh.Scene()
    _add_cylinder(scene, "white_ceramic_pot", 0.18, 0.24, (0, 0, 0.12), (228, 231, 222, 255), sections=32)
    _add_cylinder(scene, "soil", 0.155, 0.025, (0, 0, 0.252), (72, 55, 40, 255), sections=32)
    _add_cylinder(scene, "central_stem", 0.025, 0.28, (0, 0, 0.39), (49, 96, 54, 255), sections=12)
    _add_sphere(scene, "round_foliage_core", (0.22, 0.22, 0.20), (0, 0, 0.60), (38, 125, 68, 255))
    for i, angle in enumerate(np.linspace(0, 2 * np.pi, 6, endpoint=False)):
        x = 0.12 * np.cos(angle)
        y = 0.12 * np.sin(angle)
        _add_sphere(scene, f"upright_leaf_cluster_{i}", (0.11, 0.09, 0.08), (x, y, 0.63), (53, 148, 78, 255))
    return scene


def make_bookshelf() -> trimesh.Scene:
    scene = trimesh.Scene()
    wood = (182, 142, 92, 255)
    dark = (115, 82, 52, 255)
    _add_box(scene, "left_side", (0.08, 0.32, 1.65), (-0.46, 0, 0.825), wood)
    _add_box(scene, "right_side", (0.08, 0.32, 1.65), (0.46, 0, 0.825), wood)
    _add_box(scene, "back", (1.0, 0.04, 1.65), (0, 0.18, 0.825), (154, 116, 74, 255))
    for i, z in enumerate([0.08, 0.48, 0.88, 1.28, 1.62]):
        _add_box(scene, f"shelf_{i}", (1.0, 0.34, 0.06), (0, 0, z), wood)
    for i, x in enumerate([-0.17, 0.17]):
        _add_box(scene, f"divider_{i}", (0.055, 0.31, 1.48), (x, 0, 0.84), wood)
    for i, (x, z) in enumerate([(-0.30, 0.28), (0.0, 0.68), (0.28, 1.08), (-0.05, 1.45)]):
        _add_box(scene, f"book_stack_{i}", (0.20, 0.20, 0.18), (x, -0.03, z), dark)
    return scene


def make_cabinet() -> trimesh.Scene:
    scene = trimesh.Scene()
    _add_box(scene, "body", (1.05, 0.42, 0.52), (0, 0, 0.28), (166, 119, 70, 255))
    _add_box(scene, "top", (1.10, 0.46, 0.055), (0, 0, 0.57), (194, 148, 92, 255))
    for x in [-0.27, 0.27]:
        _add_box(scene, f"drawer_{x}", (0.43, 0.035, 0.18), (x, -0.225, 0.36), (141, 96, 55, 255))
        _add_box(scene, f"handle_{x}", (0.16, 0.025, 0.025), (x, -0.25, 0.38), (55, 48, 42, 255))
    return scene


def make_coat_stand() -> trimesh.Scene:
    scene = trimesh.Scene()
    metal = (52, 45, 41, 255)
    _add_cylinder(scene, "base", 0.26, 0.05, (0, 0, 0.025), metal, sections=24)
    _add_cylinder(scene, "pole", 0.035, 1.45, (0, 0, 0.75), metal, sections=16)
    for i, angle in enumerate(np.linspace(0, 2 * np.pi, 4, endpoint=False)):
        x = 0.17 * np.cos(angle)
        y = 0.17 * np.sin(angle)
        _add_box(scene, f"hook_{i}", (0.32 if abs(x) > abs(y) else 0.045, 0.32 if abs(y) > abs(x) else 0.045, 0.045), (x, y, 1.38), metal)
    return scene


def make_wall_clock() -> trimesh.Scene:
    scene = trimesh.Scene()
    _add_cylinder(scene, "frame", 0.32, 0.055, (0, 0, 0.03), (171, 126, 58, 255), sections=48)
    _add_cylinder(scene, "face", 0.27, 0.065, (0, 0, 0.065), (232, 220, 184, 255), sections=48)
    _add_box(scene, "hour_hand", (0.035, 0.16, 0.012), (0, 0.05, 0.105), (42, 39, 35, 255))
    _add_box(scene, "minute_hand", (0.20, 0.025, 0.012), (0.07, 0, 0.11), (42, 39, 35, 255))
    return scene


def make_wall_art() -> trimesh.Scene:
    scene = trimesh.Scene()
    _add_box(scene, "panel", (0.82, 0.05, 0.56), (0, 0, 0.28), (35, 90, 116, 255))
    _add_box(scene, "frame_top", (0.90, 0.065, 0.045), (0, 0, 0.56), (203, 166, 84, 255))
    _add_box(scene, "frame_bottom", (0.90, 0.065, 0.045), (0, 0, 0.02), (203, 166, 84, 255))
    _add_box(scene, "frame_left", (0.045, 0.065, 0.56), (-0.43, 0, 0.28), (203, 166, 84, 255))
    _add_box(scene, "frame_right", (0.045, 0.065, 0.56), (0.43, 0, 0.28), (203, 166, 84, 255))
    for i, x in enumerate([-0.24, 0.0, 0.24]):
        _add_box(scene, f"tile_{i}", (0.13, 0.07, 0.13), (x, -0.04, 0.28), (93, 153, 126, 255))
    return scene


def make_tabletop_photo_frame() -> trimesh.Scene:
    scene = trimesh.Scene()
    wood = (92, 62, 42, 255)
    mat = (236, 228, 210, 255)
    photo = (84, 118, 142, 255)
    _add_box(scene, "photo_panel", (0.34, 0.025, 0.24), (0, -0.006, 0.18), photo)
    _add_box(scene, "mat_panel", (0.42, 0.018, 0.30), (0, -0.014, 0.18), mat)
    _add_box(scene, "frame_top", (0.47, 0.04, 0.035), (0, -0.03, 0.345), wood)
    _add_box(scene, "frame_bottom", (0.47, 0.04, 0.035), (0, -0.03, 0.015), wood)
    _add_box(scene, "frame_left", (0.035, 0.04, 0.32), (-0.235, -0.03, 0.18), wood)
    _add_box(scene, "frame_right", (0.035, 0.04, 0.32), (0.235, -0.03, 0.18), wood)
    _add_box(scene, "rear_stand", (0.055, 0.20, 0.26), (0, 0.085, 0.13), wood)
    return scene


def make_books() -> trimesh.Scene:
    scene = trimesh.Scene()
    for i, (z, rgba) in enumerate([(0.025, (41, 83, 142, 255)), (0.08, (50, 105, 166, 255)), (0.135, (219, 198, 132, 255))]):
        _add_box(scene, f"book_{i}", (0.36, 0.26, 0.045), (0.02 * i, 0, z), rgba)
    return scene


def make_mug() -> trimesh.Scene:
    scene = trimesh.Scene()
    _add_cylinder(scene, "cup", 0.13, 0.22, (0, 0, 0.11), (24, 126, 94, 255), sections=32)
    _add_cylinder(scene, "rim", 0.14, 0.025, (0, 0, 0.23), (35, 155, 117, 255), sections=32)
    _add_box(scene, "handle_upper", (0.08, 0.035, 0.035), (0.15, 0, 0.16), (24, 126, 94, 255))
    _add_box(scene, "handle_lower", (0.08, 0.035, 0.035), (0.15, 0, 0.08), (24, 126, 94, 255))
    _add_box(scene, "handle_side", (0.035, 0.035, 0.11), (0.19, 0, 0.12), (24, 126, 94, 255))
    return scene


FACTORIES = {
    "central_conference_table": make_table,
    "sofa_seat_01": make_lounge_chair,
    "sofa_seat_02": make_lounge_chair,
    "sofa_seat_03": make_lounge_chair,
    "sofa_seat_04": make_lounge_chair,
    "sofa_seat_05": make_ottoman,
    "sofa_seat_06": make_cream_chair,
    "sofa_seat_07": make_lounge_chair,
    "sofa_seat_08": make_lounge_chair,
    "sofa_seat_09": make_lounge_chair,
    "sofa_seat_10": make_lounge_chair,
    "blue_pouf_01": make_pouf,
    "blue_pouf_02": make_pouf,
    "arched_door_main": make_door,
    "arched_window_left": make_window,
    "arched_window_right": make_window,
    "left_window": make_window,
    "right_window": make_window,
    "bedroom_window": make_window,
    "window": make_window,
    "patterned_rug": make_rug,
    "hanging_lantern_left": make_lantern,
    "hanging_lantern_right": make_lantern,
    "floor_lamp_back": make_floor_lamp,
    "plant_left_back": make_potted_plant,
    "plant_right_back": make_potted_plant,
    "right_chest_plant": make_round_tabletop_plant,
    "bookshelf_right": make_bookshelf,
    "side_cabinet_right": make_cabinet,
    "coat_stand_back": make_coat_stand,
    "wall_clock_back": make_wall_clock,
    "wall_art_left": make_wall_art,
    "wall_art_right": make_wall_art,
    "table_books": make_books,
    "table_mug": make_mug,
    "closet_double_door": make_white_double_closet_door,
    "right_nightstand_plant": make_tabletop_photo_frame,
    "right_nightstand_photo": make_tabletop_photo_frame,
    "framed_photo": make_tabletop_photo_frame,
    "photo_frame": make_tabletop_photo_frame,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-dir", required=True, type=Path)
    parser.add_argument("--only-missing", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    args.asset_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for object_id, factory in FACTORIES.items():
        path = args.asset_dir / f"{object_id}.glb"
        if args.only_missing and path.exists():
            continue
        scene = factory()
        scene.export(path)
        (args.asset_dir / f"{object_id}.json").write_text(
            json.dumps(
                {
                    "object_id": object_id,
                    "asset_path": str(path),
                    "content_type": "model/gltf-binary",
                    "source": "procedural_tree_sage_fallback",
                },
                indent=2,
            )
        )
        written.append(object_id)
    print(json.dumps({"asset_dir": str(args.asset_dir), "written": written, "count": len(written)}, indent=2))


if __name__ == "__main__":
    main()
