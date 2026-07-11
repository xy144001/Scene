from __future__ import annotations

from typing import Any

from .room_priors import build_prior_objects, build_room


def _relation(rel_type: str, subject: str, obj: str, confidence: float, evidence: str) -> dict[str, Any]:
    return {
        "type": rel_type,
        "subject": subject,
        "object": obj,
        "confidence": confidence,
        "evidence": evidence,
    }


def build_text_scene_graph(brief: dict[str, Any], asset_strategy: str) -> dict[str, Any]:
    room_type = str(brief.get("room_type") or "bedroom")
    room = build_room(brief)
    objects = build_prior_objects(brief, asset_strategy)
    ids = {str(obj["id"]) for obj in objects}
    relations: list[dict[str, Any]] = []

    if "bed" in ids:
        relations.append(_relation("against_wall", "bed", "wall_north", 0.92, "Bedroom prior places the bed headboard against the back wall."))
    if {"left_nightstand", "bed"} <= ids:
        relations.append(_relation("left_of", "left_nightstand", "bed", 0.9, "Bedroom grammar places one nightstand on each side of the bed."))
        relations.append(_relation("near", "left_nightstand", "bed", 0.9, "Bedside companion."))
    if {"right_nightstand", "bed"} <= ids:
        relations.append(_relation("right_of", "right_nightstand", "bed", 0.9, "Bedroom grammar places one nightstand on each side of the bed."))
        relations.append(_relation("near", "right_nightstand", "bed", 0.9, "Bedside companion."))
    if {"left_table_lamp", "left_nightstand"} <= ids:
        relations.append(_relation("on", "left_table_lamp", "left_nightstand", 0.95, "Table lamps sit on bedside tables."))
    if {"right_table_lamp", "right_nightstand"} <= ids:
        relations.append(_relation("on", "right_table_lamp", "right_nightstand", 0.95, "Table lamps sit on bedside tables."))
    if "wardrobe" in ids:
        relations.append(_relation("against_wall", "wardrobe", "wall_east", 0.72, "Bedroom storage defaults to a side wall."))
    if "dresser" in ids:
        relations.append(_relation("against_wall", "dresser", "wall_west", 0.7, "Dresser defaults to a free side wall."))
    if {"rug", "bed"} <= ids:
        relations.append(_relation("under", "rug", "bed", 0.85, "Area rug is a visual underlay for the main bed."))
    if {"wall_art", "bed"} <= ids:
        relations.append(_relation("above", "wall_art", "bed", 0.8, "Wall art is centered above the main anchor."))
        relations.append(_relation("attached_to", "wall_art", "wall_north", 0.85, "Wall art is a wall fixture."))
    if "door" in ids:
        relations.append(_relation("attached_to", "door", "wall_east", 0.72, "Room door defaults to side wall near the front."))
    if "ceiling_light" in ids:
        relations.append(_relation("attached_to", "ceiling_light", "ceiling", 0.95, "Ceiling light is a ceiling fixture."))

    if {"desk", "office_chair"} <= ids:
        relations.append(_relation("tucked_under", "office_chair", "desk", 0.9, "Desk-chair cluster uses a shallow chair tuck."))
        relations.append(_relation("against_wall", "desk", "wall_west", 0.72, "Desk defaults to a side wall unless prompt overrides it."))

    if {"window", "left_curtain", "right_curtain"} <= ids:
        relations.append(_relation("attached_to", "window", "wall_west", 0.85, "Window defaults to a side wall."))
        relations.append(_relation("left_of", "left_curtain", "window", 0.96, "Curtain assembly order."))
        relations.append(_relation("right_of", "right_curtain", "window", 0.96, "Curtain assembly order."))
        relations.append(_relation("same_height", "left_curtain", "right_curtain", 0.96, "Curtain panels should be symmetric."))

    if room_type == "living_room":
        if "sofa" in ids:
            relations.append(_relation("against_wall", "sofa", "wall_south", 0.76, "Living room sofa defaults to the front wall facing TV."))
        if {"coffee_table", "sofa"} <= ids:
            relations.append(_relation("in_front_of", "coffee_table", "sofa", 0.9, "Coffee table sits in front of sofa."))
        if "tv_stand" in ids:
            relations.append(_relation("against_wall", "tv_stand", "wall_north", 0.84, "Media console faces sofa."))
        if "tv" in ids:
            relations.append(_relation("attached_to", "tv", "wall_north", 0.9, "TV is mounted above or behind media console."))
        if {"rug", "coffee_table"} <= ids:
            relations.append(_relation("under", "rug", "coffee_table", 0.85, "Living room rug anchors the seating group."))

    if room_type == "study":
        if "desk" in ids:
            relations.append(_relation("against_wall", "desk", "wall_north", 0.8, "Study desk defaults to main wall."))
        if "bookcase" in ids:
            relations.append(_relation("against_wall", "bookcase", "wall_east", 0.78, "Bookcase defaults to side wall."))

    return {
        "schema": "tree_sage_text_scene_graph_v1",
        "scene_id": f"text_scene_{room_type}",
        "room_type": room_type,
        "building_style": str(brief.get("style_text") or ""),
        "description": str(brief.get("prompt") or ""),
        "room": room,
        "objects": objects,
        "relations": relations,
    }
