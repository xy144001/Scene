from __future__ import annotations

from typing import Any


def synthesize_constraints(scene_graph: dict[str, Any], human_constraints: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    constraints: list[dict[str, Any]] = []
    for rel in scene_graph.get("relations", []):
        if not isinstance(rel, dict):
            continue
        rel_type = str(rel.get("type") or "")
        priority = "soft"
        if rel_type in {"on", "attached_to", "against_wall", "tucked_under"}:
            priority = "hard"
        elif rel_type in {"left_of", "right_of", "above", "under", "same_height", "in_front_of"}:
            priority = "strong"
        constraints.append(
            {
                "source": "text_scene_relation",
                "priority": priority,
                "type": rel_type,
                "subject": rel.get("subject"),
                "object": rel.get("object"),
                "confidence": rel.get("confidence", 0.7),
                "evidence": rel.get("evidence", ""),
            }
        )

    object_ids = {str(obj.get("id")) for obj in scene_graph.get("objects", []) if isinstance(obj, dict)}
    if {"left_nightstand", "bed", "right_nightstand"} <= object_ids:
        constraints.append(
            {
                "source": "room_prior",
                "priority": "strong",
                "type": "symmetric_about",
                "subjects": ["left_nightstand", "right_nightstand"],
                "anchor": "bed",
                "evidence": "Bedroom grammar expects bedside tables to be balanced around the bed.",
            }
        )
    if {"left_curtain", "window", "right_curtain"} <= object_ids:
        constraints.append(
            {
                "source": "functional_cluster",
                "priority": "hard",
                "type": "window_curtain_assembly",
                "members": ["left_curtain", "window", "right_curtain"],
                "evidence": "Window-curtain cluster has fixed tangent order and paired-panel symmetry.",
            }
        )
    if {"desk", "office_chair"} <= object_ids:
        constraints.append(
            {
                "source": "functional_cluster",
                "priority": "hard",
                "type": "desk_chair_tuck",
                "members": ["desk", "office_chair"],
                "evidence": "Chair should be shallowly tucked under the desk, not separated as ordinary furniture.",
            }
        )

    for item in human_constraints or []:
        if isinstance(item, dict):
            merged = dict(item)
            merged.setdefault("source", "human_constraint")
            merged.setdefault("priority", "hard")
            constraints.append(merged)

    return {
        "schema": "tree_sage_text_constraints_v1",
        "constraints": constraints,
        "constraint_count": len(constraints),
    }
