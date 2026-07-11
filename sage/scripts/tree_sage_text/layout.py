from __future__ import annotations

from copy import deepcopy
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
    for obj in objects.values():
        support_id = obj.get("agent_semantics", {}).get("support_hint")
        if not support_id or support_id == "floor" or support_id not in objects:
            continue
        support = objects[str(support_id)]
        sw, sl, sh = _dims(support)
        _, _, height = _dims(obj)
        sx, sy = float(support.get("x", 0.0)), float(support.get("y", 0.0))
        offset_x = min(0.12, max(0.0, sw * 0.18))
        if str(obj.get("id", "")).startswith("left_"):
            offset_x = -offset_x
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


def _has_pose(obj: dict[str, Any]) -> bool:
    return all(key in obj for key in ("x", "y", "z", "yaw"))


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
        _place_against_wall(objects["dresser"], room, "wall_west", room_l * 0.52)
    if "desk" in objects:
        _place_against_wall(objects["desk"], room, "wall_west", room_l * 0.28)
    if "office_chair" in objects and "desk" in objects:
        desk = objects["desk"]
        _set_pose(objects["office_chair"], float(desk["x"]) + 0.56, float(desk["y"]), 0.0, 90.0)
        objects["office_chair"]["functional_cluster_id"] = "desk_chair_cluster_01"
        desk["functional_cluster_id"] = "desk_chair_cluster_01"
    if "plant" in objects:
        _set_pose(objects["plant"], room_w - 0.42, 0.65, 0.0, 0.0)
    if "floor_lamp" in objects:
        _set_pose(objects["floor_lamp"], 0.55, 1.0, 0.0, 0.0)
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
            _set_pose(objects["office_chair"], float(desk["x"]), float(desk["y"]) - 0.58, 0.0, 0.0)
        objects["office_chair"]["functional_cluster_id"] = "desk_chair_cluster_01"
        desk["functional_cluster_id"] = "desk_chair_cluster_01"
    if "bookcase" in objects:
        _place_against_wall(objects["bookcase"], room, "wall_east", room_l * 0.58)
    if "rug" in objects:
        _set_pose(objects["rug"], room_w / 2.0, room_l / 2.0, 0.0, 0.0)
    if "wall_art" in objects:
        _place_wall_fixture(objects["wall_art"], room, "wall_north", room_w * 0.25, 1.35)
    if "plant" in objects:
        _set_pose(objects["plant"], 0.55, 0.65, 0.0, 0.0)
    _place_window_cluster(objects, room, "wall_west", room_l * 0.65)
    _place_door(objects, room, "wall_east")


def generate_layout_candidates(scene_graph: dict[str, Any], candidate_count: int = 3) -> list[dict[str, Any]]:
    room = deepcopy(scene_graph["room"])
    room_type = str(scene_graph.get("room_type") or "bedroom")
    variants_by_room = {
        "bedroom": ["north_center_bed", "north_center_compact", "east_wall_bed"],
        "living_room": ["sofa_south", "sofa_south_compact", "sofa_west"],
        "study": ["desk_north", "desk_west_window", "desk_north_compact"],
    }
    variants = variants_by_room.get(room_type, variants_by_room["bedroom"])[: max(1, candidate_count)]
    candidates: list[dict[str, Any]] = []
    for index, variant in enumerate(variants, start=1):
        objects = _objects_by_id(deepcopy(scene_graph["objects"]))
        if room_type == "living_room":
            _living_room_layout(objects, room, variant)
        elif room_type == "study":
            _study_layout(objects, room, variant)
        else:
            _bedroom_layout(objects, room, variant)
        _place_ceiling(objects, room)
        _support_children(objects)
        _ensure_all_objects_have_pose(objects, room, room_type)
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
