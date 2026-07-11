from __future__ import annotations

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
            if pair in ALLOW_OVERLAP_PAIRS and area < 0.18:
                continue
            collision_pairs.append({"a": a.get("id"), "b": b.get("id"), "area": round(area, 4)})
            penalties += min(0.18, 0.04 + area * 0.08)
    if collision_pairs:
        issues.append(f"{len(collision_pairs)} physical collision pairs")

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
        "ok": score >= 0.68 and not collision_pairs,
        "issues": issues,
        "collision_pairs": collision_pairs,
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
