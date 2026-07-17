from __future__ import annotations

from copy import deepcopy
import math
from typing import Any


WALLS = {"wall_north", "wall_south", "wall_west", "wall_east"}


def _dims(obj: dict[str, Any]) -> tuple[float, float, float]:
    dims = obj.get("dimensions") if isinstance(obj.get("dimensions"), dict) else {}
    return float(dims.get("width", 1.0)), float(dims.get("length", 1.0)), float(dims.get("height", 1.0))


def _world_extents(obj: dict[str, Any]) -> tuple[float, float]:
    width, length, _ = _dims(obj)
    yaw = int(round(float(obj.get("yaw", 0.0) or 0.0))) % 180
    if yaw == 90:
        return length, width
    return width, length


def _set_pose(obj: dict[str, Any], x: float, y: float, z: float = 0.0, yaw: float = 0.0, wall_id: str | None = None) -> None:
    obj["x"] = round(float(x), 4)
    obj["y"] = round(float(y), 4)
    obj["z"] = round(float(z), 4)
    obj["yaw"] = round(float(yaw), 3)
    if wall_id:
        obj["wall_id"] = wall_id
        obj.setdefault("agent_semantics", {})["wall_relation"] = {
            "mode": "attached" if obj.get("placement_type") == "wall" else "against",
            "wall_id": wall_id,
            "confidence": 0.8,
            "source": "text_scene_layout_prior",
        }


def _place_against_wall(obj: dict[str, Any], room: dict[str, Any], wall_id: str, tangent: float, z: float = 0.0) -> None:
    width, length, _ = _dims(obj)
    room_w = float(room["width"])
    room_l = float(room["length"])
    if wall_id == "wall_north":
        _set_pose(obj, tangent, room_l - length / 2.0 - 0.05, z, 0.0, wall_id)
    elif wall_id == "wall_south":
        _set_pose(obj, tangent, length / 2.0 + 0.05, z, 180.0, wall_id)
    elif wall_id == "wall_west":
        _set_pose(obj, length / 2.0 + 0.05, tangent, z, 90.0, wall_id)
    elif wall_id == "wall_east":
        _set_pose(obj, room_w - length / 2.0 - 0.05, tangent, z, 270.0, wall_id)


def _place_wall_fixture(obj: dict[str, Any], room: dict[str, Any], wall_id: str, tangent: float, z: float) -> None:
    width, length, _ = _dims(obj)
    room_w = float(room["width"])
    room_l = float(room["length"])
    inset = max(length / 2.0, 0.035)
    if wall_id == "wall_north":
        _set_pose(obj, tangent, room_l - inset, z, 0.0, wall_id)
    elif wall_id == "wall_south":
        _set_pose(obj, tangent, inset, z, 180.0, wall_id)
    elif wall_id == "wall_west":
        _set_pose(obj, inset, tangent, z, 90.0, wall_id)
    elif wall_id == "wall_east":
        _set_pose(obj, room_w - inset, tangent, z, 270.0, wall_id)


def _objects_by_id(objects: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(obj.get("id")): obj for obj in objects}


def _support_children(objects: dict[str, dict[str, Any]]) -> None:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for obj in objects.values():
        support_id = obj.get("agent_semantics", {}).get("support_hint")
        if not support_id or support_id == "floor" or support_id not in objects:
            continue
        grouped.setdefault(str(support_id), []).append(obj)
    for support_id, children in grouped.items():
        support = objects[str(support_id)]
        sw, sl, sh = _dims(support)
        sx, sy = float(support.get("x", 0.0)), float(support.get("y", 0.0))
        if support_id == "desk":
            yaw = float(support.get("yaw", 0.0) or 0.0)
            radians = math.radians(yaw)
            cos_yaw = math.cos(radians)
            sin_yaw = math.sin(radians)
            desk_offsets = {
                "monitor": (0.0, sl * 0.22),
                "laptop": (-sw * 0.18, -sl * 0.1),
                "desk_lamp": (sw * 0.34, sl * 0.12),
                "desk_books": (-sw * 0.34, sl * 0.1),
            }
            for index, obj in enumerate(children):
                object_id = str(obj.get("id") or "")
                local_x, local_y = desk_offsets.get(object_id, (((index % 3) - 1) * sw * 0.22, 0.0))
                wx = sx + local_x * cos_yaw - local_y * sin_yaw
                wy = sy + local_x * sin_yaw + local_y * cos_yaw
                _set_pose(obj, wx, wy, float(support.get("z", 0.0)) + sh, yaw)
                obj["support_id"] = support_id
                obj["placement_type"] = "support"
                obj["support_surface_z"] = round(float(support.get("z", 0.0)) + sh, 4)
                obj["z"] = round(float(support.get("z", 0.0)) + sh, 4)
                obj["agent_semantics"]["support_hint"] = support_id
                obj["agent_semantics"]["support_height_source"] = "text_scene_support_surface"
            continue
        count = max(1, len(children))
        for index, obj in enumerate(children):
            _, _, height = _dims(obj)
            span = min(max(sw * 0.45, 0.18), max(sw - 0.18, 0.18))
            normalized = 0.0 if count == 1 else (index / (count - 1)) - 0.5
            offset_x = normalized * span
            if str(obj.get("id", "")).startswith("left_"):
                offset_x = -abs(offset_x or min(0.12, sw * 0.18))
            elif str(obj.get("id", "")).startswith("right_"):
                offset_x = abs(offset_x or min(0.12, sw * 0.18))
            _set_pose(obj, sx + offset_x, sy, float(support.get("z", 0.0)) + sh, 0.0)
            obj["support_id"] = support_id
            obj["placement_type"] = "support"
            obj["support_surface_z"] = round(float(support.get("z", 0.0)) + sh, 4)
            obj["z"] = round(float(support.get("z", 0.0)) + sh, 4)
            obj["agent_semantics"]["support_hint"] = support_id
            obj["agent_semantics"]["support_height_source"] = "text_scene_support_surface"


def _place_ceiling(objects: dict[str, dict[str, Any]], room: dict[str, Any]) -> None:
    light = objects.get("ceiling_light")
    if not light:
        return
    _, _, h = _dims(light)
    _set_pose(light, float(room["width"]) / 2.0, float(room["length"]) / 2.0, float(room["height"]) - h - 0.02, 0.0)
    light["placement_type"] = "ceiling"


def _place_pendant_pair(objects: dict[str, dict[str, Any]], room: dict[str, Any]) -> None:
    island = objects.get("kitchen_island")
    if not island:
        return
    ix = float(island.get("x", float(room["width"]) / 2.0))
    iy = float(island.get("y", float(room["length"]) / 2.0))
    _, _, room_h = float(room["width"]), float(room["length"]), float(room["height"])
    for light_id, dx in (("left_pendant_light", -0.42), ("right_pendant_light", 0.42)):
        light = objects.get(light_id)
        if not light:
            continue
        _, _, h = _dims(light)
        _set_pose(light, ix + dx, iy, room_h - h - 0.02, 0.0)
        light["placement_type"] = "ceiling"
        light["functional_cluster_id"] = "kitchen_island_lighting_cluster_01"


def _has_pose(obj: dict[str, Any]) -> bool:
    return all(key in obj for key in ("x", "y", "z", "yaw"))


def _round_yaw_90(yaw: float) -> float:
    return float((round(float(yaw) / 90.0) * 90) % 360)


def _yaw_towards(src: dict[str, Any], dst: dict[str, Any]) -> float:
    dx = float(dst.get("x", 0.0)) - float(src.get("x", 0.0))
    dy = float(dst.get("y", 0.0)) - float(src.get("y", 0.0))
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return _round_yaw_90(float(src.get("yaw", 0.0) or 0.0))
    return _round_yaw_90(math.degrees(math.atan2(dy, dx)))


def _visual_front_yaw_correction(obj: dict[str, Any]) -> float:
    semantics = obj.get("agent_semantics") if isinstance(obj.get("agent_semantics"), dict) else {}
    return float(
        obj.get(
            "visual_front_yaw_correction_degrees",
            semantics.get("visual_front_yaw_correction_degrees", 0.0),
        )
        or 0.0
    )


def _desk_open_vector(desk: dict[str, Any]) -> tuple[float, float] | None:
    wall_id = str(
        desk.get("wall_id")
        or desk.get("agent_semantics", {}).get("wall_relation", {}).get("wall_id")
        or ""
    )
    if wall_id == "wall_north":
        return 0.0, -1.0
    if wall_id == "wall_south":
        return 0.0, 1.0
    if wall_id == "wall_west":
        return 1.0, 0.0
    if wall_id == "wall_east":
        return -1.0, 0.0
    return None


def _axis_extent(obj: dict[str, Any], axis: tuple[float, float]) -> float:
    width, length = _world_extents(obj)
    return width if abs(axis[0]) >= abs(axis[1]) else length


def _ensure_desk_chair_facing(objects: dict[str, dict[str, Any]]) -> None:
    desk = objects.get("desk")
    chair = objects.get("office_chair")
    if not desk or not chair or not _has_pose(desk) or not _has_pose(chair):
        return

    open_vector = _desk_open_vector(desk)
    if open_vector is not None:
        ox, oy = open_vector
        # First set the chair yaw from the side it should occupy, then use the
        # rotated footprint to keep only a shallow tuck under the desk.
        target_visual_yaw = _round_yaw_90(math.degrees(math.atan2(-oy, -ox)))
        chair["yaw"] = _round_yaw_90(target_visual_yaw - _visual_front_yaw_correction(chair))
        chair_extent = _axis_extent(chair, open_vector)
        desk_x0, desk_y0, desk_x1, desk_y1 = object_bbox_xy(desk)
        shallow_overlap = min(0.1, max(0.045, chair_extent * 0.16))
        if abs(ox) >= abs(oy):
            desk_edge = desk_x1 if ox > 0 else desk_x0
            x = desk_edge + ox * (chair_extent / 2.0 - shallow_overlap)
            y = float(desk.get("y", chair.get("y", 0.0)))
        else:
            desk_edge = desk_y1 if oy > 0 else desk_y0
            x = float(desk.get("x", chair.get("x", 0.0)))
            y = desk_edge + oy * (chair_extent / 2.0 - shallow_overlap)
        _set_pose(chair, x, y, float(chair.get("z", 0.0) or 0.0), float(chair["yaw"]))
    else:
        target_visual_yaw = _yaw_towards(chair, desk)
        chair["yaw"] = _round_yaw_90(target_visual_yaw - _visual_front_yaw_correction(chair))

    chair["yaw"] = _round_yaw_90(target_visual_yaw - _visual_front_yaw_correction(chair))
    chair["functional_cluster_id"] = "desk_chair_cluster_01"
    desk["functional_cluster_id"] = "desk_chair_cluster_01"
    chair.setdefault("agent_semantics", {})["chair_facing_target"] = {
        "target_id": "desk",
        "target_visual_yaw": target_visual_yaw,
        "source": "text_scene_desk_chair_facing_rule",
    }
    chair["agent_semantics"]["desk_chair_cluster_solver"] = {
        "source": "text_scene_desk_chair_cluster_solver",
        "mode": "open_side_shallow_tuck" if open_vector is not None else "face_center_only",
        "desk_open_vector": list(open_vector) if open_vector is not None else None,
    }


def _place_door(objects: dict[str, dict[str, Any]], room: dict[str, Any], wall_id: str = "wall_east") -> None:
    door = objects.get("door")
    if not door:
        return
    tangent = 0.85 if wall_id in {"wall_east", "wall_west"} else float(room["width"]) - 0.75
    _place_wall_fixture(door, room, wall_id, tangent, 0.0)


def _place_window_cluster(objects: dict[str, dict[str, Any]], room: dict[str, Any], wall_id: str = "wall_west", tangent: float | None = None) -> None:
    window = objects.get("window")
    if not window:
        return
    tangent = float(tangent if tangent is not None else float(room["length"]) * 0.64)
    _place_wall_fixture(window, room, wall_id, tangent, 0.88)
    ww, _, wh = _dims(window)
    left = objects.get("left_curtain")
    right = objects.get("right_curtain")
    if left and right:
        cw, _, ch = _dims(left)
        gap = 0.035
        if wall_id in {"wall_west", "wall_east"}:
            _place_wall_fixture(left, room, wall_id, tangent - ww / 2.0 - cw / 2.0 - gap, max(0.25, float(window["z"]) + wh - ch))
            _place_wall_fixture(right, room, wall_id, tangent + ww / 2.0 + cw / 2.0 + gap, max(0.25, float(window["z"]) + wh - ch))
        else:
            _place_wall_fixture(left, room, wall_id, tangent - ww / 2.0 - cw / 2.0 - gap, max(0.25, float(window["z"]) + wh - ch))
            _place_wall_fixture(right, room, wall_id, tangent + ww / 2.0 + cw / 2.0 + gap, max(0.25, float(window["z"]) + wh - ch))
        for curtain in (left, right):
            curtain["functional_cluster_id"] = "window_curtain_cluster_01"
        window["functional_cluster_id"] = "window_curtain_cluster_01"


def _bedroom_layout(objects: dict[str, dict[str, Any]], room: dict[str, Any], variant: str) -> None:
    room_w = float(room["width"])
    room_l = float(room["length"])
    bed = objects.get("bed")
    if bed:
        if variant == "east_wall_bed":
            _place_against_wall(bed, room, "wall_east", room_l * 0.58)
        else:
            _place_against_wall(bed, room, "wall_north", room_w / 2.0)
    if bed and "left_nightstand" in objects and "right_nightstand" in objects:
        bw, bl, _ = _dims(bed)
        nsw, nsl, _ = _dims(objects["left_nightstand"])
        gap = 0.16
        if variant == "east_wall_bed":
            bx, by = float(bed["x"]), float(bed["y"])
            _set_pose(objects["left_nightstand"], bx, by + bl / 2.0 + gap + nsw / 2.0, 0.0, 90.0)
            _set_pose(objects["right_nightstand"], bx, by - bl / 2.0 - gap - nsw / 2.0, 0.0, 90.0)
        else:
            bx = float(bed["x"])
            y = room_l - nsl / 2.0 - 0.11
            _set_pose(objects["left_nightstand"], bx - bw / 2.0 - gap - nsw / 2.0, y, 0.0, 0.0)
            _set_pose(objects["right_nightstand"], bx + bw / 2.0 + gap + nsw / 2.0, y, 0.0, 0.0)
    if bed and "bed_bench" in objects:
        bw, bl, _ = _dims(bed)
        bench_w, bench_l, _ = _dims(objects["bed_bench"])
        if variant == "east_wall_bed":
            _set_pose(objects["bed_bench"], max(0.75, float(bed["x"]) - bl / 2.0 - bench_l / 2.0 - 0.14), float(bed["y"]), 0.0, 90.0)
        else:
            _set_pose(objects["bed_bench"], float(bed["x"]), max(0.65, float(bed["y"]) - bl / 2.0 - bench_l / 2.0 - 0.14), 0.0, 0.0)
        objects["bed_bench"]["functional_cluster_id"] = "bed_sleeping_cluster_01"
        bed["functional_cluster_id"] = "bed_sleeping_cluster_01"
    if "rug" in objects:
        if bed:
            _set_pose(objects["rug"], float(bed["x"]), max(1.55, float(bed["y"]) - 0.45), 0.0, 0.0)
        else:
            _set_pose(objects["rug"], room_w / 2.0, room_l / 2.0, 0.0, 0.0)
    if "wall_art" in objects:
        anchor_x = float(bed["x"]) if bed else room_w / 2.0
        if variant == "east_wall_bed":
            _place_wall_fixture(objects["wall_art"], room, "wall_east", float(bed["y"]) if bed else room_l / 2.0, 1.35)
        else:
            _place_wall_fixture(objects["wall_art"], room, "wall_north", anchor_x, 1.35)
    if "wardrobe" in objects:
        _place_against_wall(objects["wardrobe"], room, "wall_east", room_l * 0.72 if variant != "east_wall_bed" else room_l * 0.25)
    if "dresser" in objects:
        _place_against_wall(objects["dresser"], room, "wall_west", room_l * 0.25)
    if "dresser_mirror" in objects:
        dresser_y = float(objects["dresser"]["y"]) if "dresser" in objects and "y" in objects["dresser"] else room_l * 0.25
        _place_wall_fixture(objects["dresser_mirror"], room, "wall_west", dresser_y, 1.12)
    if "desk" in objects:
        _place_against_wall(objects["desk"], room, "wall_west", room_l * 0.28)
    if "office_chair" in objects and "desk" in objects:
        desk = objects["desk"]
        _set_pose(objects["office_chair"], float(desk["x"]) + 0.56, float(desk["y"]), 0.0, 90.0)
        objects["office_chair"]["functional_cluster_id"] = "desk_chair_cluster_01"
        desk["functional_cluster_id"] = "desk_chair_cluster_01"
    if "plant" in objects:
        _set_pose(objects["plant"], room_w - 0.55, room_l * 0.42, 0.0, 0.0)
    if "accent_chair" in objects:
        _set_pose(objects["accent_chair"], 0.95, 0.9, 0.0, 45.0)
        objects["accent_chair"]["functional_cluster_id"] = "bedroom_reading_corner_01"
    if "bedroom_side_table" in objects:
        _set_pose(objects["bedroom_side_table"], 1.62, 0.92, 0.0, 0.0)
        objects["bedroom_side_table"]["functional_cluster_id"] = "bedroom_reading_corner_01"
    if "floor_lamp" in objects:
        _set_pose(objects["floor_lamp"], 0.78, 0.45, 0.0, 0.0)
    _place_window_cluster(objects, room, "wall_west", room_l * 0.66)
    _place_door(objects, room, "wall_east")


def _living_room_layout(objects: dict[str, dict[str, Any]], room: dict[str, Any], variant: str) -> None:
    room_w = float(room["width"])
    room_l = float(room["length"])
    if "sofa" in objects:
        if variant == "sofa_west":
            _place_against_wall(objects["sofa"], room, "wall_west", room_l / 2.0)
        else:
            _place_against_wall(objects["sofa"], room, "wall_south", room_w / 2.0)
    if "coffee_table" in objects:
        if "sofa" in objects and variant == "sofa_west":
            _set_pose(objects["coffee_table"], 1.75, room_l / 2.0, 0.0, 90.0)
        else:
            _set_pose(objects["coffee_table"], room_w / 2.0, 2.05, 0.0, 0.0)
    if "rug" in objects:
        table = objects.get("coffee_table")
        _set_pose(objects["rug"], float(table.get("x", room_w / 2.0)) if table else room_w / 2.0, float(table.get("y", room_l / 2.0)) if table else room_l / 2.0, 0.0, 0.0)
    if "tv_stand" in objects:
        _place_against_wall(objects["tv_stand"], room, "wall_north", room_w / 2.0)
    if "left_bookcase" in objects:
        _place_against_wall(objects["left_bookcase"], room, "wall_north", max(0.7, room_w / 2.0 - 1.35))
    if "right_bookcase" in objects:
        _place_against_wall(objects["right_bookcase"], room, "wall_north", min(room_w - 0.7, room_w / 2.0 + 1.35))
    if "tv" in objects:
        _place_wall_fixture(objects["tv"], room, "wall_north", room_w / 2.0, 1.25)
    if "bookcase" in objects:
        _place_against_wall(objects["bookcase"], room, "wall_east", room_l * 0.65)
    if "wall_art" in objects:
        _place_wall_fixture(objects["wall_art"], room, "wall_west", room_l * 0.65, 1.35)
    if "floor_lamp" in objects:
        _set_pose(objects["floor_lamp"], 0.7, 1.1, 0.0, 0.0)
    if "plant" in objects:
        _set_pose(objects["plant"], room_w - 0.55, 0.75, 0.0, 0.0)
    if "left_side_table" in objects and "sofa" in objects:
        sofa = objects["sofa"]
        sw, sl, _ = _dims(sofa)
        stw, stl, _ = _dims(objects["left_side_table"])
        _set_pose(objects["left_side_table"], float(sofa["x"]) - sw / 2.0 - stw / 2.0 - 0.12, float(sofa["y"]) + 0.05, 0.0, 180.0)
    if "right_side_table" in objects and "sofa" in objects:
        sofa = objects["sofa"]
        sw, sl, _ = _dims(sofa)
        stw, stl, _ = _dims(objects["right_side_table"])
        _set_pose(objects["right_side_table"], float(sofa["x"]) + sw / 2.0 + stw / 2.0 + 0.12, float(sofa["y"]) + 0.05, 0.0, 180.0)
    if "accent_chair" in objects:
        table = objects.get("coffee_table")
        if table:
            _set_pose(objects["accent_chair"], min(room_w - 0.85, float(table["x"]) + 1.45), float(table["y"]) + 0.25, 0.0, 270.0)
            objects["accent_chair"]["functional_cluster_id"] = "living_room_seating_cluster_01"
            table["functional_cluster_id"] = "living_room_seating_cluster_01"
    if "woven_basket" in objects and "sofa" in objects:
        sofa = objects["sofa"]
        _, sofa_l, _ = _dims(sofa)
        basket_w, basket_l, _ = _dims(objects["woven_basket"])
        _set_pose(
            objects["woven_basket"],
            max(0.45, float(sofa["x"]) - 1.2),
            min(room_l - 0.65, float(sofa["y"]) + sofa_l / 2.0 + basket_l / 2.0 + 0.12),
            0.0,
            0.0,
        )
    _place_window_cluster(objects, room, "wall_west", room_l * 0.63)
    _place_door(objects, room, "wall_east")


def _ensure_living_room_explicit_object_poses(objects: dict[str, dict[str, Any]], room: dict[str, Any]) -> None:
    room_w = float(room["width"])
    room_l = float(room["length"])
    table = objects.get("coffee_table")
    sofa = objects.get("sofa")
    if "office_chair" in objects and not _has_pose(objects["office_chair"]):
        anchor_x = float(table.get("x", room_w / 2.0)) if table else room_w / 2.0
        anchor_y = float(table.get("y", room_l / 2.0)) if table else room_l / 2.0
        _set_pose(objects["office_chair"], max(0.75, anchor_x - 1.25), anchor_y, 0.0, 90.0)
        objects["office_chair"]["functional_cluster_id"] = "living_room_seating_cluster_01"
        if table:
            table["functional_cluster_id"] = "living_room_seating_cluster_01"
    lamp_targets = {
        "left_table_lamp": -1.45,
        "right_table_lamp": 1.45,
    }
    for lamp_id, dx in lamp_targets.items():
        lamp = objects.get(lamp_id)
        if not lamp or _has_pose(lamp):
            continue
        if sofa:
            _set_pose(lamp, float(sofa["x"]) + dx, float(sofa["y"]) + 0.18, 0.0, 0.0)
        else:
            _set_pose(lamp, room_w / 2.0 + dx, 0.85, 0.0, 0.0)
        lamp["placement_type"] = "floor"
        lamp.setdefault("agent_semantics", {})["support_fallback"] = "no_matching_side_table_in_text_scene_layout"


def _ensure_all_objects_have_pose(objects: dict[str, dict[str, Any]], room: dict[str, Any], room_type: str) -> None:
    if room_type == "living_room":
        _ensure_living_room_explicit_object_poses(objects, room)
    room_w = float(room["width"])
    room_l = float(room["length"])
    floor_slots = [
        (0.7, 0.7, 0.0),
        (room_w - 0.7, 0.7, 0.0),
        (0.7, room_l - 0.7, 180.0),
        (room_w - 0.7, room_l - 0.7, 180.0),
        (room_w / 2.0, room_l / 2.0, 0.0),
    ]
    wall_slots = [
        ("wall_north", room_w * 0.25, 1.35),
        ("wall_north", room_w * 0.75, 1.35),
        ("wall_west", room_l * 0.35, 1.35),
        ("wall_east", room_l * 0.65, 1.35),
    ]
    floor_index = 0
    wall_index = 0
    for obj in objects.values():
        if _has_pose(obj):
            continue
        placement = str(obj.get("placement_type") or "floor")
        if placement == "ceiling":
            _, _, h = _dims(obj)
            _set_pose(obj, room_w / 2.0, room_l / 2.0, float(room["height"]) - h - 0.02, 0.0)
        elif placement == "wall":
            wall_id, tangent, z = wall_slots[wall_index % len(wall_slots)]
            wall_index += 1
            _place_wall_fixture(obj, room, wall_id, tangent, z)
        else:
            x, y, yaw = floor_slots[floor_index % len(floor_slots)]
            floor_index += 1
            _set_pose(obj, x, y, 0.0, yaw)
            if placement == "support":
                obj["placement_type"] = "floor"
                obj.setdefault("agent_semantics", {})["support_fallback"] = "missing_support_object_in_text_scene_layout"
        obj.setdefault("agent_semantics", {})["pose_fallback_source"] = "text_scene_layout_pose_completeness_guard"


def _floor_collision_area_at(
    obj: dict[str, Any],
    objects: dict[str, dict[str, Any]],
    *,
    x: float,
    y: float,
) -> float:
    original_x = obj.get("x")
    original_y = obj.get("y")
    obj["x"] = x
    obj["y"] = y
    try:
        total = 0.0
        for other in objects.values():
            if other is obj:
                continue
            if str(other.get("placement_type")) in {"wall", "ceiling", "support", "floor_layer"}:
                continue
            if not _has_pose(other):
                continue
            overlap, area = aabb_overlap(obj, other)
            if overlap:
                total += area
        return total
    finally:
        if original_x is None:
            obj.pop("x", None)
        else:
            obj["x"] = original_x
        if original_y is None:
            obj.pop("y", None)
        else:
            obj["y"] = original_y


def _ensure_plant_away_from_door(objects: dict[str, dict[str, Any]], room: dict[str, Any], min_distance: float = 1.05) -> None:
    plant = objects.get("plant")
    door = objects.get("door")
    if not plant or not door or not _has_pose(plant) or not _has_pose(door):
        return
    px = float(plant.get("x", 0.0))
    py = float(plant.get("y", 0.0))
    dx = px - float(door.get("x", 0.0))
    dy = py - float(door.get("y", 0.0))
    if (dx * dx + dy * dy) ** 0.5 >= min_distance:
        return

    room_w = float(room["width"])
    room_l = float(room["length"])
    candidates = [
        (0.55, room_l * 0.52, 0.0),
        (room_w - 0.55, room_l * 0.52, 0.0),
        (0.55, room_l - 0.7, 180.0),
        (room_w - 0.55, room_l - 0.7, 180.0),
        (0.55, 0.75, 0.0),
        (room_w - 0.55, 0.75, 0.0),
    ]
    best: tuple[float, float, float, float] | None = None
    for x, y, yaw in candidates:
        ddx = x - float(door.get("x", 0.0))
        ddy = y - float(door.get("y", 0.0))
        distance = (ddx * ddx + ddy * ddy) ** 0.5
        if distance < min_distance:
            continue
        collision_area = _floor_collision_area_at(plant, objects, x=x, y=y)
        rank = collision_area - distance * 0.001
        if best is None or rank < best[0]:
            best = (rank, x, y, yaw)
    if best is None:
        return
    _, x, y, yaw = best
    _set_pose(plant, x, y, float(plant.get("z", 0.0) or 0.0), yaw)
    plant.setdefault("agent_semantics", {})["plant_door_clearance_source"] = "text_scene_layout_postprocess"


def _study_layout(objects: dict[str, dict[str, Any]], room: dict[str, Any], variant: str) -> None:
    room_w = float(room["width"])
    room_l = float(room["length"])
    if "desk" in objects:
        wall = "wall_north" if variant != "desk_west_window" else "wall_west"
        tangent = room_w / 2.0 if wall == "wall_north" else room_l * 0.58
        _place_against_wall(objects["desk"], room, wall, tangent)
    if "office_chair" in objects and "desk" in objects:
        desk = objects["desk"]
        if str(desk.get("wall_id")) == "wall_west":
            _set_pose(objects["office_chair"], float(desk["x"]) + 0.55, float(desk["y"]), 0.0, 90.0)
        else:
            _set_pose(objects["office_chair"], float(desk["x"]), float(desk["y"]) - 0.5, 0.0, 0.0)
        objects["office_chair"]["functional_cluster_id"] = "desk_chair_cluster_01"
        desk["functional_cluster_id"] = "desk_chair_cluster_01"
    if "bookcase" in objects:
        _place_against_wall(objects["bookcase"], room, "wall_east", room_l * 0.72)
    if "storage_cabinet" in objects:
        _place_against_wall(objects["storage_cabinet"], room, "wall_east", room_l * 0.36)
    if "reading_chair" in objects:
        _set_pose(objects["reading_chair"], 0.95, 1.05, 0.0, 55.0)
        objects["reading_chair"]["functional_cluster_id"] = "study_reading_corner_01"
    if "study_side_table" in objects:
        _set_pose(objects["study_side_table"], 1.67, 1.0, 0.0, 0.0)
        objects["study_side_table"]["functional_cluster_id"] = "study_reading_corner_01"
    if "floor_lamp" in objects:
        _set_pose(objects["floor_lamp"], 0.35, 1.45, 0.0, 0.0)
        objects["floor_lamp"]["functional_cluster_id"] = "study_reading_corner_01"
    if "rug" in objects:
        _set_pose(objects["rug"], room_w / 2.0, room_l * 0.46, 0.0, 0.0)
    if "wall_art" in objects:
        _place_wall_fixture(objects["wall_art"], room, "wall_north", room_w * 0.28, 1.38)
    if "pinboard" in objects:
        _place_wall_fixture(objects["pinboard"], room, "wall_north", room_w * 0.72, 1.35)
    if "plant" in objects:
        _set_pose(objects["plant"], room_w - 0.55, 0.65, 0.0, 0.0)
    _place_window_cluster(objects, room, "wall_west", room_l * 0.62)
    if "door" in objects:
        _place_wall_fixture(objects["door"], room, "wall_east", 0.65, 0.0)


def _kitchen_layout(objects: dict[str, dict[str, Any]], room: dict[str, Any], variant: str) -> None:
    room_w = float(room["width"])
    room_l = float(room["length"])
    compact = variant.endswith("_compact")
    east_fridge = variant != "galley_west_window"

    if "base_cabinets" in objects:
        _place_against_wall(objects["base_cabinets"], room, "wall_north", room_w * 0.34)
    if "stove_range" in objects:
        _place_against_wall(objects["stove_range"], room, "wall_north", room_w * 0.68)
    if "range_hood" in objects:
        _place_wall_fixture(objects["range_hood"], room, "wall_north", room_w * 0.68, 1.55)
    if "left_upper_cabinets" in objects:
        _place_wall_fixture(objects["left_upper_cabinets"], room, "wall_north", max(0.7, room_w * 0.24), 1.38)
    if "right_upper_cabinets" in objects:
        _place_wall_fixture(objects["right_upper_cabinets"], room, "wall_north", min(room_w - 0.7, room_w * 0.84), 1.38)
    if "refrigerator" in objects:
        if east_fridge:
            _place_against_wall(objects["refrigerator"], room, "wall_east", room_l * 0.72)
        else:
            _place_against_wall(objects["refrigerator"], room, "wall_west", room_l * 0.72)
    if "kitchen_island" in objects:
        island_y = room_l * (0.46 if compact else 0.43)
        _set_pose(objects["kitchen_island"], room_w * 0.5, island_y, 0.0, 0.0)
    if "left_bar_stool" in objects and "kitchen_island" in objects:
        island = objects["kitchen_island"]
        iw, il, _ = _dims(island)
        stool_w, stool_l, _ = _dims(objects["left_bar_stool"])
        stool_y = max(0.55, float(island["y"]) - il / 2.0 - stool_l / 2.0 - 0.18)
        _set_pose(objects["left_bar_stool"], float(island["x"]) - iw * 0.28, stool_y, 0.0, 0.0)
        objects["left_bar_stool"]["functional_cluster_id"] = "kitchen_island_seating_cluster_01"
    if "right_bar_stool" in objects and "kitchen_island" in objects:
        island = objects["kitchen_island"]
        iw, il, _ = _dims(island)
        stool_w, stool_l, _ = _dims(objects["right_bar_stool"])
        stool_y = max(0.55, float(island["y"]) - il / 2.0 - stool_l / 2.0 - 0.18)
        _set_pose(objects["right_bar_stool"], float(island["x"]) + iw * 0.28, stool_y, 0.0, 0.0)
        objects["right_bar_stool"]["functional_cluster_id"] = "kitchen_island_seating_cluster_01"
    if "runner_rug" in objects:
        y = room_l * (0.28 if compact else 0.25)
        _set_pose(objects["runner_rug"], room_w * 0.5, y, 0.0, 0.0)
    if "open_shelf" in objects:
        shelf_wall = "wall_west" if east_fridge else "wall_east"
        _place_wall_fixture(objects["open_shelf"], room, shelf_wall, room_l * 0.45, 1.45)
    if "window" in objects:
        _place_wall_fixture(objects["window"], room, "wall_west", room_l * 0.58, 0.95)
    if "plant" in objects:
        _set_pose(objects["plant"], room_w - 0.45, 0.55, 0.0, 0.0)
    _place_pendant_pair(objects, room)


def generate_layout_candidates(scene_graph: dict[str, Any], candidate_count: int = 3) -> list[dict[str, Any]]:
    room = deepcopy(scene_graph["room"])
    room_type = str(scene_graph.get("room_type") or "bedroom")
    variants_by_room = {
        "bedroom": ["north_center_bed", "north_center_compact", "east_wall_bed"],
        "living_room": ["sofa_south", "sofa_south_compact", "sofa_west"],
        "study": ["desk_north", "desk_west_window", "desk_north_compact"],
        "kitchen": ["workwall_island", "workwall_island_compact", "galley_west_window"],
    }
    variants = variants_by_room.get(room_type, variants_by_room["bedroom"])[: max(1, candidate_count)]
    candidates: list[dict[str, Any]] = []
    for index, variant in enumerate(variants, start=1):
        objects = _objects_by_id(deepcopy(scene_graph["objects"]))
        if room_type == "living_room":
            _living_room_layout(objects, room, variant)
        elif room_type == "study":
            _study_layout(objects, room, variant)
        elif room_type == "kitchen":
            _kitchen_layout(objects, room, variant)
        else:
            _bedroom_layout(objects, room, variant)
        _place_ceiling(objects, room)
        _place_pendant_pair(objects, room)
        _support_children(objects)
        _ensure_all_objects_have_pose(objects, room, room_type)
        _ensure_plant_away_from_door(objects, room)
        _ensure_desk_chair_facing(objects)
        plan = {
            "scene_id": f"{scene_graph.get('scene_id', 'text_scene')}_{variant}",
            "room_type": room_type,
            "building_style": scene_graph.get("building_style", ""),
            "description": scene_graph.get("description", ""),
            "room": deepcopy(room),
            "objects": list(objects.values()),
            "relations": deepcopy(scene_graph.get("relations", [])),
            "layout_variant": variant,
            "layout_candidate_index": index,
        }
        candidates.append(plan)
    return candidates


def object_bbox_xy(obj: dict[str, Any]) -> tuple[float, float, float, float]:
    width, length = _world_extents(obj)
    x = float(obj.get("x", 0.0) or 0.0)
    y = float(obj.get("y", 0.0) or 0.0)
    return x - width / 2.0, y - length / 2.0, x + width / 2.0, y + length / 2.0


def aabb_overlap(a: dict[str, Any], b: dict[str, Any], margin: float = 0.0) -> tuple[bool, float]:
    ax0, ay0, ax1, ay1 = object_bbox_xy(a)
    bx0, by0, bx1, by1 = object_bbox_xy(b)
    dx = min(ax1, bx1) - max(ax0, bx0) + margin
    dy = min(ay1, by1) - max(ay0, by0) + margin
    if dx <= 0.0 or dy <= 0.0:
        return False, 0.0
    return True, dx * dy
