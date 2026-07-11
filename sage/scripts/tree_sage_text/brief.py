from __future__ import annotations

import re
from typing import Any


ROOM_KEYWORDS = {
    "bedroom": ("bedroom", "bed room", "卧室", "主卧", "次卧", "床"),
    "living_room": ("living room", "livingroom", "lounge", "客厅", "起居室", "沙发", "电视"),
    "study": ("study", "office", "home office", "书房", "办公室", "办公", "书桌"),
}

STYLE_KEYWORDS = {
    "modern": ("modern", "现代"),
    "warm": ("warm", "cozy", "温馨", "暖色", "暖"),
    "wood": ("wood", "wooden", "walnut", "oak", "木", "原木", "胡桃木"),
    "minimal": ("minimal", "minimalist", "极简", "简约"),
    "scandinavian": ("scandinavian", "nordic", "北欧"),
    "japanese": ("japanese", "wabi", "日式", "侘寂"),
    "traditional": ("traditional", "classic", "复古", "传统", "美式"),
    "industrial": ("industrial", "metal", "工业"),
}

OBJECT_KEYWORDS = {
    "bed": ("bed", "queen bed", "king bed", "床", "双人床", "大床"),
    "nightstand": ("nightstand", "bedside table", "床头柜"),
    "wardrobe": ("wardrobe", "closet", "衣柜", "柜子"),
    "dresser": ("dresser", "chest of drawers", "斗柜", "五斗柜", "梳妆柜"),
    "desk": ("desk", "work table", "书桌", "桌子", "办公桌"),
    "chair": ("chair", "office chair", "椅子", "办公椅"),
    "sofa": ("sofa", "couch", "沙发"),
    "coffee_table": ("coffee table", "茶几"),
    "tv": ("tv", "television", "电视"),
    "tv_stand": ("tv stand", "media console", "电视柜"),
    "bookcase": ("bookcase", "bookshelf", "书架", "书柜"),
    "rug": ("rug", "carpet", "地毯"),
    "window": ("window", "窗户", "窗"),
    "curtains": ("curtain", "drape", "窗帘"),
    "door": ("door", "门"),
    "wall_art": ("wall art", "painting", "picture", "poster", "挂画", "画", "装饰画"),
    "plant": ("plant", "绿植", "植物", "盆栽"),
    "table_lamp": ("table lamp", "lamp on", "台灯"),
    "floor_lamp": ("floor lamp", "落地灯"),
    "ceiling_light": ("ceiling light", "ceiling lamp", "吊灯", "吸顶灯", "顶灯"),
}


def _contains(text: str, keywords: tuple[str, ...]) -> bool:
    normalized = text.lower()
    return any(keyword.lower() in normalized for keyword in keywords)


def _room_type_from_text(text: str, override: str | None = None) -> tuple[str, list[str]]:
    if override:
        return override, ["room_type_override"]
    scores: dict[str, int] = {}
    evidence: list[str] = []
    for room_type, keywords in ROOM_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword.lower() in text.lower())
        if score:
            scores[room_type] = score
            evidence.append(f"{room_type}:{score}")
    if not scores:
        return "bedroom", ["default_bedroom"]
    return max(scores, key=scores.get), evidence


def _style_tags(text: str, explicit_style: str | None = None) -> list[str]:
    tags: list[str] = []
    source = f"{text} {explicit_style or ''}"
    for tag, keywords in STYLE_KEYWORDS.items():
        if _contains(source, keywords):
            tags.append(tag)
    if not tags:
        tags.extend(["modern", "warm", "wood"])
    return tags


def _objects_from_text(text: str) -> list[str]:
    objects = []
    for object_type, keywords in OBJECT_KEYWORDS.items():
        if _contains(text, keywords):
            objects.append(object_type)
    return objects


def _layout_preferences(text: str) -> list[str]:
    preferences: list[str] = []
    lowered = text.lower()
    if any(token in lowered for token in ("center", "centered", "居中", "中间")):
        preferences.append("prefer_centered_main_anchor")
    if any(token in lowered for token in ("symmetric", "symmetry", "对称")):
        preferences.append("prefer_symmetry")
    if any(token in lowered for token in ("靠墙", "against wall", "back wall", "贴墙")):
        preferences.append("prefer_wall_backed_anchors")
    if any(token in lowered for token in ("near window", "窗边", "靠窗")):
        preferences.append("prefer_work_or_seating_near_window")
    if any(token in lowered for token in ("spacious", "walkable", "宽敞", "留出通道")):
        preferences.append("prefer_clear_walkways")
    return preferences


def build_text_scene_brief(
    prompt: str,
    *,
    room_type_override: str | None = None,
    style_override: str | None = None,
) -> dict[str, Any]:
    clean_prompt = re.sub(r"\s+", " ", prompt or "").strip()
    room_type, room_evidence = _room_type_from_text(clean_prompt, room_type_override)
    explicit_objects = _objects_from_text(clean_prompt)
    style_tags = _style_tags(clean_prompt, style_override)
    preferences = _layout_preferences(clean_prompt)
    return {
        "schema": "tree_sage_text_scene_brief_v1",
        "prompt": clean_prompt,
        "room_type": room_type,
        "room_type_evidence": room_evidence,
        "style_tags": style_tags,
        "style_text": style_override or ", ".join(style_tags),
        "explicit_object_types": explicit_objects,
        "layout_preferences": preferences,
        "quality_targets": [
            "prompt_consistency",
            "functional_room_layout",
            "collision_free_major_furniture",
            "support_validity",
            "readable_visual_composition",
        ],
    }
