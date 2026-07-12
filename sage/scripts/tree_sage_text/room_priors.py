from __future__ import annotations

from copy import deepcopy
from typing import Any


BASE_ROOM = {
    "bedroom": {"width": 5.2, "length": 4.2, "height": 2.7},
    "living_room": {"width": 6.0, "length": 4.8, "height": 2.8},
    "study": {"width": 4.2, "length": 3.6, "height": 2.7},
}

MATERIALS = {
    "modern": {
        "wall": [0.86, 0.85, 0.81],
        "floor": [0.45, 0.34, 0.22],
    },
    "warm": {
        "wall": [0.84, 0.78, 0.68],
        "floor": [0.46, 0.32, 0.19],
    },
    "minimal": {
        "wall": [0.9, 0.9, 0.87],
        "floor": [0.62, 0.55, 0.45],
    },
    "industrial": {
        "wall": [0.52, 0.52, 0.5],
        "floor": [0.3, 0.28, 0.25],
    },
}


def dims(width: float, length: float, height: float) -> dict[str, float]:
    return {"width": width, "length": length, "height": height}


OBJECT_LIBRARY: dict[str, dict[str, Any]] = {
    "bed": {
        "category": "bed",
        "dimensions": dims(1.75, 2.15, 0.9),
        "placement_type": "floor",
        "semantic_class": "floor_furniture",
        "layout_role": "main_anchor",
        "description": "bed with integrated bedding and pillows",
    },
    "left_nightstand": {
        "category": "nightstand",
        "dimensions": dims(0.55, 0.45, 0.55),
        "placement_type": "floor",
        "semantic_class": "floor_furniture",
        "layout_role": "bedside_companion",
        "description": "left bedside nightstand",
    },
    "right_nightstand": {
        "category": "nightstand",
        "dimensions": dims(0.55, 0.45, 0.55),
        "placement_type": "floor",
        "semantic_class": "floor_furniture",
        "layout_role": "bedside_companion",
        "description": "right bedside nightstand",
    },
    "left_table_lamp": {
        "category": "table_lamp",
        "dimensions": dims(0.28, 0.28, 0.48),
        "placement_type": "support",
        "semantic_class": "tabletop_child",
        "layout_role": "task_lighting",
        "support_id": "left_nightstand",
        "description": "small table lamp on left nightstand",
    },
    "right_table_lamp": {
        "category": "table_lamp",
        "dimensions": dims(0.28, 0.28, 0.48),
        "placement_type": "support",
        "semantic_class": "tabletop_child",
        "layout_role": "task_lighting",
        "support_id": "right_nightstand",
        "description": "small table lamp on right nightstand",
    },
    "wardrobe": {
        "category": "wardrobe",
        "dimensions": dims(0.95, 0.62, 2.25),
        "placement_type": "floor",
        "semantic_class": "floor_furniture",
        "layout_role": "wall_storage",
        "description": "tall wardrobe against a side wall",
    },
    "dresser": {
        "category": "dresser",
        "dimensions": dims(1.25, 0.48, 0.85),
        "placement_type": "floor",
        "semantic_class": "floor_furniture",
        "layout_role": "wall_storage",
        "description": "low dresser with drawers against a wall",
    },
    "desk": {
        "category": "desk",
        "dimensions": dims(1.25, 0.65, 0.75),
        "placement_type": "floor",
        "semantic_class": "floor_furniture",
        "layout_role": "work_surface",
        "description": "writing desk or work table",
    },
    "office_chair": {
        "category": "chair",
        "dimensions": dims(0.58, 0.58, 0.9),
        "placement_type": "floor",
        "semantic_class": "floor_furniture",
        "layout_role": "workstation_chair",
        "description": "chair tucked partly under the desk",
    },
    "sofa": {
        "category": "sofa",
        "dimensions": dims(2.2, 0.95, 0.85),
        "placement_type": "floor",
        "semantic_class": "floor_furniture",
        "layout_role": "main_anchor",
        "description": "three seat sofa",
    },
    "coffee_table": {
        "category": "coffee_table",
        "dimensions": dims(1.1, 0.65, 0.42),
        "placement_type": "floor",
        "semantic_class": "floor_furniture",
        "layout_role": "center_table",
        "description": "coffee table in front of sofa",
    },
    "tv_stand": {
        "category": "tv_stand",
        "dimensions": dims(1.45, 0.42, 0.5),
        "placement_type": "floor",
        "semantic_class": "floor_furniture",
        "layout_role": "media_storage",
        "description": "low media console against wall",
    },
    "tv": {
        "category": "tv",
        "dimensions": dims(1.1, 0.06, 0.65),
        "placement_type": "wall",
        "semantic_class": "wall_fixture",
        "layout_role": "media_display",
        "description": "flat wall mounted television",
    },
    "bookcase": {
        "category": "bookcase",
        "dimensions": dims(0.95, 0.35, 1.9),
        "placement_type": "floor",
        "semantic_class": "floor_furniture",
        "layout_role": "wall_storage",
        "description": "bookcase against a wall",
    },
    "left_bookcase": {
        "category": "bookcase",
        "dimensions": dims(0.72, 0.34, 1.9),
        "placement_type": "floor",
        "semantic_class": "floor_furniture",
        "layout_role": "media_wall_storage",
        "description": "left slim bookcase with books and ceramics",
    },
    "right_bookcase": {
        "category": "bookcase",
        "dimensions": dims(0.72, 0.34, 1.9),
        "placement_type": "floor",
        "semantic_class": "floor_furniture",
        "layout_role": "media_wall_storage",
        "description": "right slim bookcase with books and ceramics",
    },
    "accent_chair": {
        "category": "chair",
        "dimensions": dims(0.72, 0.74, 0.86),
        "placement_type": "floor",
        "semantic_class": "floor_furniture",
        "layout_role": "secondary_seating",
        "description": "upholstered living room accent chair",
    },
    "left_side_table": {
        "category": "side_table",
        "dimensions": dims(0.44, 0.44, 0.48),
        "placement_type": "floor",
        "semantic_class": "floor_furniture",
        "layout_role": "sofa_side_table",
        "description": "left small side table beside sofa",
    },
    "right_side_table": {
        "category": "side_table",
        "dimensions": dims(0.44, 0.44, 0.48),
        "placement_type": "floor",
        "semantic_class": "floor_furniture",
        "layout_role": "sofa_side_table",
        "description": "right small side table beside sofa",
    },
    "woven_basket": {
        "category": "basket",
        "dimensions": dims(0.42, 0.42, 0.4),
        "placement_type": "floor",
        "semantic_class": "floor_decor",
        "layout_role": "soft_storage_decor",
        "description": "woven storage basket",
    },
    "stacked_books": {
        "category": "books",
        "dimensions": dims(0.34, 0.24, 0.12),
        "placement_type": "support",
        "semantic_class": "tabletop_child",
        "layout_role": "tabletop_decor",
        "support_id": "coffee_table",
        "description": "small stack of decorative books",
    },
    "ceramic_vase": {
        "category": "vase",
        "dimensions": dims(0.22, 0.22, 0.34),
        "placement_type": "support",
        "semantic_class": "tabletop_child",
        "layout_role": "tabletop_decor",
        "support_id": "coffee_table",
        "description": "neutral ceramic vase",
    },
    "rug": {
        "category": "rug",
        "dimensions": dims(2.7, 2.4, 0.025),
        "placement_type": "floor_layer",
        "semantic_class": "floor_covering",
        "layout_role": "visual_underlay",
        "description": "thin area rug",
    },
    "window": {
        "category": "window",
        "dimensions": dims(1.2, 0.06, 1.15),
        "placement_type": "wall",
        "semantic_class": "wall_fixture",
        "layout_role": "window",
        "description": "thin wall mounted residential window",
    },
    "left_curtain": {
        "category": "curtain",
        "dimensions": dims(0.42, 0.05, 1.75),
        "placement_type": "wall",
        "semantic_class": "wall_fixture",
        "layout_role": "left_window_curtain",
        "description": "left curtain panel beside window",
    },
    "right_curtain": {
        "category": "curtain",
        "dimensions": dims(0.42, 0.05, 1.75),
        "placement_type": "wall",
        "semantic_class": "wall_fixture",
        "layout_role": "right_window_curtain",
        "description": "right curtain panel beside window",
    },
    "door": {
        "category": "door",
        "dimensions": dims(0.9, 0.07, 2.05),
        "placement_type": "wall",
        "semantic_class": "wall_fixture",
        "layout_role": "room_door",
        "description": "floor grounded interior room door",
    },
    "wall_art": {
        "category": "wall_art",
        "dimensions": dims(0.95, 0.05, 0.55),
        "placement_type": "wall",
        "semantic_class": "wall_fixture",
        "layout_role": "wall_decor",
        "description": "framed wall art",
    },
    "plant": {
        "category": "plant",
        "dimensions": dims(0.45, 0.45, 0.9),
        "placement_type": "floor",
        "semantic_class": "floor_decor",
        "layout_role": "decor",
        "description": "potted indoor plant",
    },
    "floor_lamp": {
        "category": "floor_lamp",
        "dimensions": dims(0.35, 0.35, 1.55),
        "placement_type": "floor",
        "semantic_class": "floor_decor",
        "layout_role": "lighting",
        "description": "standing floor lamp",
    },
    "ceiling_light": {
        "category": "ceiling_light",
        "dimensions": dims(0.55, 0.55, 0.18),
        "placement_type": "ceiling",
        "semantic_class": "ceiling_fixture",
        "layout_role": "ceiling_light",
        "description": "ceiling mounted room light",
    },
}

DEFAULT_OBJECTS = {
    "bedroom": [
        "bed",
        "left_nightstand",
        "right_nightstand",
        "left_table_lamp",
        "right_table_lamp",
        "wardrobe",
        "rug",
        "wall_art",
        "ceiling_light",
        "door",
    ],
    "living_room": [
        "sofa",
        "coffee_table",
        "tv_stand",
        "tv",
        "rug",
        "floor_lamp",
        "plant",
        "wall_art",
        "ceiling_light",
        "door",
    ],
    "study": [
        "desk",
        "office_chair",
        "bookcase",
        "rug",
        "plant",
        "wall_art",
        "ceiling_light",
        "door",
    ],
}

EXPLICIT_EXPANSION = {
    "nightstand": ["left_nightstand", "right_nightstand"],
    "table_lamp": ["left_table_lamp", "right_table_lamp"],
    "curtains": ["left_curtain", "right_curtain"],
    "window": ["window"],
    "desk": ["desk", "office_chair"],
    "chair": ["office_chair"],
    "accent_chair": ["accent_chair"],
    "bookcase": ["bookcase"],
    "side_table": ["left_side_table", "right_side_table"],
    "basket": ["woven_basket"],
    "books": ["stacked_books"],
    "ceramics": ["ceramic_vase"],
    "tv": ["tv", "tv_stand"],
}


def material_plan(style_tags: list[str]) -> dict[str, Any]:
    seed = next((tag for tag in style_tags if tag in MATERIALS), "modern")
    colors = MATERIALS[seed]
    wall_spec = {
        "texture_type": "solid_color",
        "base_color": colors["wall"],
        "roughness": 0.82,
        "alpha": 1.0,
    }
    return {
        "schema": "tree_sage_text_material_plan_v1",
        "source": "text_scene_room_prior",
        "global_wall": wall_spec,
        "walls": {wall: deepcopy(wall_spec) for wall in ("wall_north", "wall_south", "wall_west", "wall_east")},
        "ceiling": deepcopy(wall_spec),
        "floor": {
            "texture_type": "solid_color",
            "base_color": colors["floor"],
            "roughness": 0.82,
            "alpha": 1.0,
        },
    }


def object_ids_for_brief(brief: dict[str, Any]) -> list[str]:
    room_type = str(brief.get("room_type") or "bedroom")
    object_ids = list(DEFAULT_OBJECTS.get(room_type, DEFAULT_OBJECTS["bedroom"]))
    explicit = brief.get("explicit_object_types")
    if isinstance(explicit, list):
        for object_type in explicit:
            if room_type == "living_room" and str(object_type) == "bookcase":
                expansions = ["left_bookcase", "right_bookcase"]
            elif room_type == "living_room" and str(object_type) == "chair":
                expansions = ["accent_chair"]
            else:
                expansions = EXPLICIT_EXPANSION.get(str(object_type), [str(object_type)])
            for object_id in expansions:
                if object_id in OBJECT_LIBRARY and object_id not in object_ids:
                    object_ids.append(object_id)
    if "window" in object_ids and "left_curtain" not in object_ids and "curtains" in (brief.get("explicit_object_types") or []):
        object_ids.extend(["left_curtain", "right_curtain"])
    return object_ids


def make_object(object_id: str, style_tags: list[str], asset_strategy: str) -> dict[str, Any]:
    spec = deepcopy(OBJECT_LIBRARY[object_id])
    category = spec["category"]
    style_text = ", ".join(style_tags)
    prompt = f"{style_text} {spec['description']}, clean single 3D asset, front view, neutral background"
    return {
        "id": object_id,
        "category": category,
        "description": spec["description"],
        "asset_prompt": prompt,
        "dimensions": spec["dimensions"],
        "placement_type": spec["placement_type"],
        "asset_axis_to_z": 2,
        "front_yaw_offset_degrees": 0.0,
        "footprint_yaw_offset_degrees": 0.0,
        "asset_local_yaw_offset_degrees": 0.0,
        "agent_semantics": {
            "semantic_class": spec["semantic_class"],
            "layout_role": spec["layout_role"],
            "support_hint": spec.get("support_id", "floor"),
            "text_scene_prior": True,
        },
        "asset_generation": {
            "route": asset_strategy,
            "status": "planned",
        },
    }


def build_room(brief: dict[str, Any]) -> dict[str, Any]:
    room_type = str(brief.get("room_type") or "bedroom")
    room = deepcopy(BASE_ROOM.get(room_type, BASE_ROOM["bedroom"]))
    room["materials"] = material_plan(list(brief.get("style_tags") or []))
    return room


def build_prior_objects(brief: dict[str, Any], asset_strategy: str) -> list[dict[str, Any]]:
    style_tags = list(brief.get("style_tags") or [])
    return [make_object(object_id, style_tags, asset_strategy) for object_id in object_ids_for_brief(brief)]
