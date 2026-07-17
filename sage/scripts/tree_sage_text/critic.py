from __future__ import annotations

import math
from typing import Any

from .layout import aabb_overlap, object_bbox_xy


IGNORE_COLLISION_CATEGORIES = {"rug", "wall_art", "window", "curtain", "door", "tv", "ceiling_light"}
ALLOW_OVERLAP_PAIRS = {
    frozenset(("rug", "bed")),
    frozenset(("rug", "sofa")),
    frozenset(("rug", "coffee_table")),
    frozenset(("desk", "chair")),
}


def _object_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(obj.get("id")): obj for obj in plan.get("objects", []) if isinstance(obj, dict)}


def _category(obj: dict[str, Any]) -> str:
    return str(obj.get("category") or obj.get("id") or "")


def _is_floor_physical(obj: dict[str, Any]) -> bool:
    if _category(obj) in IGNORE_COLLISION_CATEGORIES:
        return False
    if str(obj.get("placement_type")) in {"wall", "ceiling", "support", "floor_layer"}:
        return False
    return True


def _is_wall_fixture(obj: dict[str, Any]) -> bool:
    return str(obj.get("placement_type")) == "wall" and bool(obj.get("wall_id"))


def _wall_fixture_intervals(obj: dict[str, Any]) -> tuple[str, tuple[float, float], tuple[float, float]]:
    dims = obj.get("dimensions") if isinstance(obj.get("dimensions"), dict) else {}
    width = float(dims.get("width", 1.0))
    height = float(dims.get("height", 1.0))
    wall_id = str(obj.get("wall_id"))
    tangent = float(obj.get("x", 0.0)) if wall_id in {"wall_north", "wall_south"} else float(obj.get("y", 0.0))
    z = float(obj.get("z", 0.0))
    return wall_id, (tangent - width / 2.0, tangent + width / 2.0), (z, z + height)


def _wall_overlap_issue(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any] | None:
    wall_a, tangent_a, z_a = _wall_fixture_intervals(a)
    wall_b, tangent_b, z_b = _wall_fixture_intervals(b)
    if wall_a != wall_b:
        return None
    tangent_overlap = min(tangent_a[1], tangent_b[1]) - max(tangent_a[0], tangent_b[0])
    z_overlap = min(z_a[1], z_b[1]) - max(z_a[0], z_b[0])
    if tangent_overlap <= 0.04 or z_overlap <= 0.04:
        return None
    return {
        "a": a.get("id"),
        "b": b.get("id"),
        "wall_id": wall_a,
        "tangent_overlap": round(tangent_overlap, 4),
        "z_overlap": round(z_overlap, 4),
    }


def _plant_door_issue(objects: dict[str, dict[str, Any]]) -> str | None:
    plant = objects.get("plant")
    door = objects.get("door")
    if not (plant and door):
        return None
    dx = float(plant.get("x", 0.0)) - float(door.get("x", 0.0))
    dy = float(plant.get("y", 0.0)) - float(door.get("y", 0.0))
    distance = (dx * dx + dy * dy) ** 0.5
    if distance < 1.0:
        return f"plant is too close to the door ({distance:.2f}m center distance)"
    return None


def _round_yaw_90(yaw: float) -> float:
    return float((round(float(yaw) / 90.0) * 90) % 360)


def _angle_diff(a: float, b: float) -> float:
    return abs((float(a) - float(b) + 180.0) % 360.0 - 180.0)


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


def _bbox_axis_extent(obj: dict[str, Any], axis: tuple[float, float]) -> float:
    x0, y0, x1, y1 = object_bbox_xy(obj)
    return (x1 - x0) if abs(axis[0]) >= abs(axis[1]) else (y1 - y0)


def desk_chair_facing_issue(objects: dict[str, dict[str, Any]], max_degrees: float = 45.0) -> str | None:
    desk = objects.get("desk")
    chair = objects.get("office_chair")
    if not (desk and chair):
        return None
    dx = float(desk.get("x", 0.0)) - float(chair.get("x", 0.0))
    dy = float(desk.get("y", 0.0)) - float(chair.get("y", 0.0))
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return "desk-chair cluster has overlapping centers, cannot determine chair facing"
    target_yaw = _round_yaw_90(math.degrees(math.atan2(dy, dx)))
    chair_raw_yaw = _round_yaw_90(float(chair.get("yaw", 0.0) or 0.0))
    chair_visual_yaw = _round_yaw_90(chair_raw_yaw + _visual_front_yaw_correction(chair))
    diff = _angle_diff(chair_visual_yaw, target_yaw)
    if diff > max_degrees:
        return (
            "office_chair front does not face desk "
            f"(chair_raw_yaw={chair_raw_yaw:g}, chair_visual_yaw={chair_visual_yaw:g}, "
            f"target_yaw={target_yaw:g}, diff={diff:.1f})"
        )
    return None


def desk_chair_tuck_issue(objects: dict[str, dict[str, Any]]) -> str | None:
    desk = objects.get("desk")
    chair = objects.get("office_chair")
    if not (desk and chair):
        return None
    open_vector = _desk_open_vector(desk)
    if open_vector is None:
        overlap, area = aabb_overlap(desk, chair)
        if not overlap or area < 0.02:
            return "desk-chair cluster is not shallowly tucked"
        return None

    ox, oy = open_vector
    dx = float(chair.get("x", 0.0)) - float(desk.get("x", 0.0))
    dy = float(chair.get("y", 0.0)) - float(desk.get("y", 0.0))
    open_offset = dx * ox + dy * oy
    if open_offset <= 0.0:
        return "office_chair is on the wall side of the desk instead of the open room side"
    desk_half = _bbox_axis_extent(desk, open_vector) / 2.0
    chair_half = _bbox_axis_extent(chair, open_vector) / 2.0
    tuck_depth = desk_half + chair_half - open_offset
    if tuck_depth < 0.02:
        return f"office_chair is separated from desk instead of shallowly tucked (tuck_depth={tuck_depth:.2f}m)"
    if tuck_depth > 0.18:
        return f"office_chair is tucked too deeply into the desk (tuck_depth={tuck_depth:.2f}m)"
    return None


def _room_bounds_issue(plan: dict[str, Any], obj: dict[str, Any]) -> str | None:
    if str(obj.get("placement_type")) in {"wall", "ceiling"}:
        return None
    room = plan["room"]
    width = float(room["width"])
    length = float(room["length"])
    x0, y0, x1, y1 = object_bbox_xy(obj)
    if x0 < -0.03 or y0 < -0.03 or x1 > width + 0.03 or y1 > length + 0.03:
        return f"{obj.get('id')} extends outside room bounds"
    return None


def _support_issue(objects: dict[str, dict[str, Any]], obj: dict[str, Any]) -> str | None:
    support_id = obj.get("support_id") or obj.get("agent_semantics", {}).get("support_hint")
    if not support_id or support_id == "floor":
        return None
    support = objects.get(str(support_id))
    if not support:
        return f"{obj.get('id')} references missing support {support_id}"
    sx0, sy0, sx1, sy1 = object_bbox_xy(support)
    ox0, oy0, ox1, oy1 = object_bbox_xy(obj)
    if ox0 < sx0 - 0.08 or ox1 > sx1 + 0.08 or oy0 < sy0 - 0.08 or oy1 > sy1 + 0.08:
        return f"{obj.get('id')} is not on top of {support_id}"
    expected_z = float(support.get("z", 0.0)) + float(support.get("dimensions", {}).get("height", 0.0))
    if abs(float(obj.get("z", 0.0)) - expected_z) > 0.06:
        return f"{obj.get('id')} has wrong support height on {support_id}"
    return None


def _symmetry_score(objects: dict[str, dict[str, Any]]) -> tuple[float, list[str]]:
    issues: list[str] = []
    bed = objects.get("bed")
    left = objects.get("left_nightstand")
    right = objects.get("right_nightstand")
    if not (bed and left and right):
        return 0.0, issues
    bx = float(bed.get("x", 0.0))
    left_dist = abs(float(left.get("x", 0.0)) - bx)
    right_dist = abs(float(right.get("x", 0.0)) - bx)
    residual = abs(left_dist - right_dist)
    if residual > 0.12:
        issues.append("bedside nightstands are not symmetric around bed")
    return max(0.0, 1.0 - residual / 0.5), issues


def _functional_score(objects: dict[str, dict[str, Any]]) -> tuple[float, list[str]]:
    issues: list[str] = []
    score = 1.0
    if {"desk", "office_chair"} <= set(objects):
        desk = objects["desk"]
        chair = objects["office_chair"]
        overlap, area = aabb_overlap(desk, chair)
        if not overlap or area < 0.03:
            score -= 0.18
            issues.append("desk-chair cluster is not shallowly tucked")
    if {"left_curtain", "window", "right_curtain"} <= set(objects):
        left = objects["left_curtain"]
        window = objects["window"]
        right = objects["right_curtain"]
        if not (float(left.get("y", 0.0)) < float(window.get("y", 0.0)) < float(right.get("y", 0.0))):
            score -= 0.18
            issues.append("window-curtain tangent order is not left curtain / window / right curtain")
        top_left = float(left.get("z", 0.0)) + float(left.get("dimensions", {}).get("height", 0.0))
        top_right = float(right.get("z", 0.0)) + float(right.get("dimensions", {}).get("height", 0.0))
        if abs(top_left - top_right) > 0.08:
            score -= 0.12
            issues.append("curtain panel top edges are not symmetric")
    return max(0.0, score), issues


def score_candidate(plan: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    objects = _object_map(plan)
    issues: list[str] = []
    penalties = 0.0

    for obj in objects.values():
        bounds_issue = _room_bounds_issue(plan, obj)
        if bounds_issue:
            issues.append(bounds_issue)
            penalties += 0.08
        support_issue = _support_issue(objects, obj)
        if support_issue:
            issues.append(support_issue)
            penalties += 0.1

    physical = [obj for obj in objects.values() if _is_floor_physical(obj)]
    collision_pairs: list[dict[str, Any]] = []
    for i, a in enumerate(physical):
        for b in physical[i + 1 :]:
            pair = frozenset((_category(a), _category(b)))
            overlap, area = aabb_overlap(a, b)
            if not overlap:
                continue
            if area < 0.002:
                continue
            if pair in ALLOW_OVERLAP_PAIRS and area < 0.18:
                continue
            collision_pairs.append({"a": a.get("id"), "b": b.get("id"), "area": round(area, 4)})
            penalties += min(0.18, 0.04 + area * 0.08)
    if collision_pairs:
        issues.append(f"{len(collision_pairs)} physical collision pairs")

    wall_fixtures = [obj for obj in objects.values() if _is_wall_fixture(obj)]
    wall_collision_pairs: list[dict[str, Any]] = []
    for i, a in enumerate(wall_fixtures):
        for b in wall_fixtures[i + 1 :]:
            issue = _wall_overlap_issue(a, b)
            if not issue:
                continue
            wall_collision_pairs.append(issue)
            penalties += 0.08
    if wall_collision_pairs:
        issues.append(f"{len(wall_collision_pairs)} wall fixture overlap pairs")

    plant_issue = _plant_door_issue(objects)
    if plant_issue:
        issues.append(plant_issue)
        penalties += 0.1
    desk_chair_issue = desk_chair_facing_issue(objects)
    if desk_chair_issue:
        issues.append(desk_chair_issue)
        penalties += 0.18
    desk_chair_tuck = desk_chair_tuck_issue(objects)
    if desk_chair_tuck:
        issues.append(desk_chair_tuck)
        penalties += 0.16

    symmetry, symmetry_issues = _symmetry_score(objects)
    issues.extend(symmetry_issues)
    penalties += (1.0 - symmetry) * 0.08 if symmetry_issues else 0.0

    functional, functional_issues = _functional_score(objects)
    issues.extend(functional_issues)
    penalties += (1.0 - functional) * 0.18

    hard_constraints = [
        item
        for item in constraints.get("constraints", [])
        if isinstance(item, dict) and item.get("priority") == "hard"
    ]
    hard_bonus = min(0.12, len(hard_constraints) * 0.01)
    density = len(objects) / max(1.0, float(plan["room"]["width"]) * float(plan["room"]["length"]))
    density_penalty = 0.0
    if density < 0.32:
        density_penalty = 0.04
        issues.append("scene may be sparse")
    elif density > 0.85:
        density_penalty = 0.06
        issues.append("scene may be overcrowded")

    score = max(0.0, min(1.0, 0.82 + hard_bonus - penalties - density_penalty))
    return {
        "candidate_id": plan.get("scene_id"),
        "layout_variant": plan.get("layout_variant"),
        "score": round(score, 4),
        "ok": (
            score >= 0.68
            and not collision_pairs
            and not wall_collision_pairs
            and not plant_issue
            and not desk_chair_issue
            and not desk_chair_tuck
        ),
        "issues": issues,
        "collision_pairs": collision_pairs,
        "wall_collision_pairs": wall_collision_pairs,
        "metrics": {
            "object_count": len(objects),
            "hard_constraint_count": len(hard_constraints),
            "density": round(density, 4),
            "symmetry_score": round(symmetry, 4) if "bed" in objects else None,
            "functional_score": round(functional, 4),
        },
    }


def select_best_candidate(candidates: list[dict[str, Any]], constraints: dict[str, Any]) -> dict[str, Any]:
    scored = [score_candidate(plan, constraints) for plan in candidates]
    best_index = max(range(len(scored)), key=lambda idx: scored[idx]["score"]) if scored else 0
    return {
        "schema": "tree_sage_text_scene_critic_v1",
        "selected_index": best_index,
        "selected_candidate_id": scored[best_index]["candidate_id"] if scored else None,
        "scores": scored,
        "accepted": bool(scored and scored[best_index]["ok"]),
    }
