from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


ANCHOR_ORDER_BY_ROOM = {
    "bedroom": ["bed", "rug", "wardrobe", "dresser", "left_nightstand", "right_nightstand"],
    "living_room": ["sofa", "rug", "coffee_table", "tv_stand", "office_chair"],
    "study": ["desk", "office_chair", "bookcase", "rug"],
}

WOOD_CATEGORIES = {"bed", "nightstand", "wardrobe", "dresser", "desk", "coffee_table", "tv_stand", "bookcase", "side_table", "door"}
FABRIC_CATEGORIES = {"bed", "sofa", "office_chair", "chair", "curtain", "rug", "basket"}
NEUTRAL_CATEGORIES = {"curtain", "lamp", "table_lamp", "floor_lamp", "ceiling_light", "window", "door"}
ACCENT_SAFE_CATEGORIES = {"plant", "wall_art", "rug", "office_chair", "sofa"}


def _contains(text: str, needles: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(needle in lowered for needle in needles)


def _hex(rgb: list[int]) -> str:
    return "#" + "".join(f"{max(0, min(255, int(v))):02x}" for v in rgb[:3])


def _palette_from_prompt(prompt: str, style_tags: list[str]) -> dict[str, Any]:
    text = f"{prompt} {' '.join(style_tags)}".lower()
    if _contains(text, ("white oak", "light oak", "scandinavian", "nordic", "japandi", "light wood")):
        wood = {
            "name": "light white oak",
            "rgb": [184, 148, 94],
            "keywords": ["light oak", "white oak", "natural pale wood", "low-sheen wood"],
        }
    elif _contains(text, ("walnut", "dark wood", "dark walnut", "espresso")):
        wood = {
            "name": "dark walnut",
            "rgb": [86, 54, 32],
            "keywords": ["dark walnut", "dark brown wood", "low-sheen wood grain"],
        }
    elif _contains(text, ("honey", "warm wood", "american", "cozy")):
        wood = {
            "name": "warm honey oak",
            "rgb": [156, 100, 48],
            "keywords": ["warm honey oak", "medium warm wood", "low-sheen wood grain"],
        }
    else:
        wood = {
            "name": "natural medium oak",
            "rgb": [132, 91, 52],
            "keywords": ["natural medium oak", "warm brown wood", "low-sheen wood grain"],
        }

    neutrals = [
        {"name": "warm cream", "rgb": [232, 222, 204]},
        {"name": "soft beige", "rgb": [207, 191, 166]},
        {"name": "greige", "rgb": [178, 170, 154]},
    ]
    if _contains(text, ("gray", "grey", "industrial", "concrete")) and not _contains(text, ("beige", "cream", "warm neutral")):
        neutrals = [
            {"name": "warm gray", "rgb": [184, 184, 176]},
            {"name": "soft greige", "rgb": [190, 182, 166]},
            {"name": "off white", "rgb": [230, 228, 220]},
        ]

    accents: list[dict[str, Any]] = []
    if _contains(text, ("navy", "blue")):
        accents.append({"name": "navy blue accent", "rgb": [26, 58, 102], "use": "pillows, chair upholstery, small accents"})
    if _contains(text, ("sage", "green", "olive")):
        accents.append({"name": "muted green accent", "rgb": [105, 124, 92], "use": "plants, pillows, throws"})
    if _contains(text, ("black metal", "industrial", "black")):
        metal = {"name": "matte black metal", "rgb": [25, 24, 22], "keywords": ["matte black metal", "thin black hardware"]}
    elif _contains(text, ("brass", "gold")):
        metal = {"name": "aged brass", "rgb": [174, 130, 72], "keywords": ["aged brass", "warm muted brass"]}
    else:
        metal = {"name": "dark bronze or black hardware", "rgb": [45, 38, 32], "keywords": ["dark bronze", "black hardware"]}

    return {
        "base_neutrals": [{**item, "hex": _hex(item["rgb"])} for item in neutrals],
        "wood": {**wood, "hex": _hex(wood["rgb"])},
        "metal": {**metal, "hex": _hex(metal["rgb"])},
        "accents": [{**item, "hex": _hex(item["rgb"])} for item in accents],
        "avoid": [
            "unrelated saturated colors",
            "glossy plastic unless requested",
            "random red/orange wood when the scene uses neutral walnut or oak",
            "mixed visual eras across furniture",
            "strong studio shadows or colored lighting",
        ],
    }


def _material_language(palette: dict[str, Any], style_tags: list[str]) -> list[str]:
    wood = palette["wood"]
    metal = palette["metal"]
    fabric = "linen, cotton, boucle, or softly woven upholstery"
    if "industrial" in style_tags:
        fabric = "plain woven upholstery with restrained texture"
    if "traditional" in style_tags:
        fabric = "classic woven fabric with restrained pattern"
    return [
        f"{wood['name']} for main wood furniture",
        f"{metal['name']} for handles, legs, rods, and small metal details",
        fabric,
        "matte or low-sheen finishes",
        "warm neutral lighting and clean product-photo exposure",
    ]


def _object_ids(scene_graph: dict[str, Any]) -> list[str]:
    return [str(obj.get("id")) for obj in scene_graph.get("objects", []) if isinstance(obj, dict) and obj.get("id")]


def _anchor_ids(room_type: str, object_ids: list[str]) -> list[str]:
    ordered = [object_id for object_id in ANCHOR_ORDER_BY_ROOM.get(room_type, []) if object_id in object_ids]
    for object_id in object_ids:
        if len(ordered) >= 5:
            break
        if object_id not in ordered and any(token in object_id for token in ("sofa", "bed", "desk", "table", "stand", "rug")):
            ordered.append(object_id)
    return ordered[:5]


def build_asset_style_spec(brief: dict[str, Any], scene_graph: dict[str, Any]) -> dict[str, Any]:
    prompt = str(brief.get("prompt") or scene_graph.get("description") or "")
    style_tags = [str(tag) for tag in brief.get("style_tags") or []]
    room_type = str(brief.get("room_type") or scene_graph.get("room_type") or "bedroom")
    object_ids = _object_ids(scene_graph)
    palette = _palette_from_prompt(prompt, style_tags)
    materials = _material_language(palette, style_tags)
    anchors = _anchor_ids(room_type, object_ids)
    palette_text = "; ".join(
        [
            "base neutrals: " + ", ".join(item["name"] for item in palette["base_neutrals"]),
            "wood: " + palette["wood"]["name"],
            "metal: " + palette["metal"]["name"],
            "accents: " + (", ".join(item["name"] for item in palette["accents"]) if palette["accents"] else "only muted scene accents"),
        ]
    )
    return {
        "schema": "tree_sage_text_asset_style_spec_v1",
        "enabled": True,
        "source": "text_scene_asset_style_consistency",
        "room_type": room_type,
        "style_tags": style_tags,
        "style_text": str(brief.get("style_text") or ", ".join(style_tags)),
        "palette": palette,
        "material_language": materials,
        "anchor_object_ids": anchors,
        "image2_global_style_prompt": (
            "All asset source images must feel from the same interior collection. "
            f"Use {palette_text}. Materials: {', '.join(materials)}. "
            "Use a clean isolated product-photo view on a flat magenta or transparent-compatible background. "
            "Keep color temperature, contrast, and finish consistent across all generated assets."
        ),
        "image2_negative_style_prompt": (
            "Do not introduce unrelated saturated colors, mismatched wood species, glossy toy-like plastic, "
            "heavy colored lighting, cluttered room backgrounds, text labels, extra furniture, or display platforms."
        ),
        "qa_policy": {
            "default_strict": False,
            "warn_on_high_unrelated_saturation": True,
            "warn_on_wood_tone_mismatch": True,
            "warn_on_anchor_inconsistency": True,
        },
    }


def _category_rule(obj: dict[str, Any], style_spec: dict[str, Any]) -> dict[str, Any]:
    object_id = str(obj.get("id") or "")
    category = str(obj.get("category") or object_id)
    palette = style_spec["palette"]
    if category in WOOD_CATEGORIES or any(token in object_id for token in WOOD_CATEGORIES):
        material = f"use {palette['wood']['name']} or a closely compatible low-sheen wood tone"
    elif category in FABRIC_CATEGORIES or "curtain" in object_id:
        neutral_names = ", ".join(item["name"] for item in palette["base_neutrals"])
        accent_names = ", ".join(item["name"] for item in palette["accents"])
        material = f"use fabric in {neutral_names}" + (f" with restrained {accent_names}" if accent_names else "")
    elif "lamp" in category or "light" in category:
        material = f"use warm white shade/glass with {palette['metal']['name']} or muted ceramic details"
    elif category == "plant":
        material = "natural green foliage with a neutral ceramic, woven, or dark planter"
    elif category == "books":
        material = "muted decorative books in warm neutral, navy, sage, or dark walnut compatible covers"
    elif category in {"vase", "ceramic"}:
        material = "warm neutral ceramic with matte low-sheen finish"
    elif category == "basket":
        material = "natural woven fiber in warm beige or greige"
    elif category == "wall_art":
        material = "muted framed art that uses the scene palette; avoid loud unrelated poster colors"
    else:
        material = "use colors and finishes from the global scene palette"
    return {
        "object_id": object_id,
        "category": category,
        "material_rule": material,
        "avoid": style_spec["palette"]["avoid"],
    }


def apply_asset_style_to_scene_graph(scene_graph: dict[str, Any], style_spec: dict[str, Any]) -> dict[str, Any]:
    styled = deepcopy(scene_graph)
    styled["asset_style_spec"] = style_spec
    global_prompt = style_spec["image2_global_style_prompt"]
    negative_prompt = style_spec["image2_negative_style_prompt"]
    anchor_ids = set(style_spec.get("anchor_object_ids") or [])
    for obj in styled.get("objects", []):
        if not isinstance(obj, dict):
            continue
        rule = _category_rule(obj, style_spec)
        is_anchor = str(obj.get("id")) in anchor_ids
        obj["asset_style"] = {
            "is_anchor_asset": is_anchor,
            "rule": rule,
            "global_style_prompt": global_prompt,
            "negative_style_prompt": negative_prompt,
        }
        base_prompt = str(obj.get("asset_prompt") or obj.get("description") or obj.get("id"))
        style_suffix = (
            f" Scene style consistency: {rule['material_rule']}. "
            f"{global_prompt} Negative style constraints: {negative_prompt}"
        )
        if "Scene style consistency:" not in base_prompt:
            obj["asset_prompt"] = base_prompt.rstrip(" .") + "." + style_suffix
    return styled


def build_image2_generation_plan(scene_graph: dict[str, Any], style_spec: dict[str, Any]) -> dict[str, Any]:
    anchor_ids = [str(item) for item in style_spec.get("anchor_object_ids") or []]
    objects = [obj for obj in scene_graph.get("objects", []) if isinstance(obj, dict)]
    object_ids = [str(obj.get("id")) for obj in objects if obj.get("id")]
    batches = [
        {
            "batch": 1,
            "name": "style_anchor_assets",
            "object_ids": [object_id for object_id in anchor_ids if object_id in object_ids],
            "instruction": "Generate these first. QA them for material/color/style before generating remaining objects.",
            "style_reference_ids": [],
        },
        {
            "batch": 2,
            "name": "remaining_assets_with_anchor_references",
            "object_ids": [object_id for object_id in object_ids if object_id not in anchor_ids],
            "instruction": (
                "Generate these after anchor assets pass QA. Provide accepted anchor images or an anchor contact sheet "
                "as image2 style references, while still generating only the requested target object."
            ),
            "style_reference_ids": [object_id for object_id in anchor_ids if object_id in object_ids],
        },
    ]
    items = []
    for obj in objects:
        object_id = str(obj.get("id"))
        is_anchor = object_id in anchor_ids
        rule = obj.get("asset_style", {}).get("rule") if isinstance(obj.get("asset_style"), dict) else _category_rule(obj, style_spec)
        prompt = (
            f"Generate only the {object_id} as a single isolated front-view product photo for 3D asset creation. "
            f"{rule['material_rule']}. {style_spec['image2_global_style_prompt']} "
            f"Negative: {style_spec['image2_negative_style_prompt']}"
        )
        if not is_anchor:
            prompt += " Match the accepted anchor asset images for palette, material finish, lighting, and overall interior style; do not copy their shape."
        items.append(
            {
                "id": object_id,
                "category": obj.get("category"),
                "is_anchor_asset": is_anchor,
                "image2_prompt": prompt,
                "style_reference_ids": [] if is_anchor else [anchor_id for anchor_id in anchor_ids if anchor_id in object_ids],
                "output_filename": f"{object_id}.png",
                "qa_expectations": [
                    "target object only",
                    "front view or canonical product view",
                    "clean flat background",
                    "material and palette consistent with asset_style_spec",
                    "no extra display platform or unrelated room background",
                ],
            }
        )
    return {
        "schema": "tree_sage_text_image2_asset_generation_plan_v1",
        "source": "text_scene_asset_style_consistency",
        "asset_style_spec": "text_scene_asset_style_spec.json",
        "batches": batches,
        "objects": items,
    }


def _foreground_pixels(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        arr = np.asarray(rgb, dtype=np.int16)
    h, w = arr.shape[:2]
    border_width = max(2, min(24, h // 12, w // 12))
    border = np.concatenate(
        [
            arr[:border_width].reshape(-1, 3),
            arr[-border_width:].reshape(-1, 3),
            arr[:, :border_width].reshape(-1, 3),
            arr[:, -border_width:].reshape(-1, 3),
        ],
        axis=0,
    )
    bg = np.median(border, axis=0)
    dist = np.abs(arr - bg).mean(axis=2)
    subject = dist > 35.0
    fg = arr[subject].reshape(-1, 3)
    if len(fg) == 0:
        return arr.reshape(-1, 3)
    stride = max(1, len(fg) // 60000)
    return fg[::stride]


def analyze_source_image_style(path: Path, obj: dict[str, Any], style_spec: dict[str, Any] | None) -> dict[str, Any]:
    report: dict[str, Any] = {
        "enabled": bool(style_spec),
        "ok": True,
        "warnings": [],
    }
    if not style_spec:
        return report
    if not path.exists():
        report["ok"] = False
        report["warnings"].append("missing_source_image_for_style_qa")
        return report
    try:
        fg = _foreground_pixels(path).astype(np.float32)
    except Exception as exc:
        report["ok"] = False
        report["warnings"].append(f"style_image_read_failed:{type(exc).__name__}")
        return report
    if len(fg) == 0:
        report["ok"] = False
        report["warnings"].append("no_foreground_pixels_for_style_qa")
        return report
    rgb_median = np.median(fg, axis=0)
    rgb_mean = np.mean(fg, axis=0)
    maxc = np.max(fg, axis=1)
    minc = np.min(fg, axis=1)
    saturation = np.where(maxc > 0.0, (maxc - minc) / np.maximum(maxc, 1.0), 0.0)
    value = maxc / 255.0
    sat_p75 = float(np.percentile(saturation, 75))
    sat_mean = float(np.mean(saturation))
    val_mean = float(np.mean(value))
    category = str(obj.get("category") or obj.get("id") or "")
    object_id = str(obj.get("id") or "")
    report.update(
        {
            "median_rgb": [int(round(float(v))) for v in rgb_median],
            "mean_rgb": [int(round(float(v))) for v in rgb_mean],
            "mean_saturation": round(sat_mean, 4),
            "p75_saturation": round(sat_p75, 4),
            "mean_value": round(val_mean, 4),
        }
    )
    score = 1.0
    has_accent = bool(style_spec.get("palette", {}).get("accents"))
    if sat_p75 > 0.62 and category not in ACCENT_SAFE_CATEGORIES and object_id not in ACCENT_SAFE_CATEGORIES and not has_accent:
        report["warnings"].append("high_saturation_without_scene_accent")
        score -= 0.28
    if (category in WOOD_CATEGORIES or object_id in WOOD_CATEGORIES) and style_spec:
        wood_name = str(style_spec.get("palette", {}).get("wood", {}).get("name", "")).lower()
        red_bias = float(rgb_mean[0] - max(rgb_mean[1], rgb_mean[2]))
        if "dark" in wood_name and val_mean > 0.72:
            report["warnings"].append("wood_asset_too_light_for_dark_wood_scene")
            score -= 0.2
        if ("oak" in wood_name or "natural" in wood_name) and val_mean < 0.2:
            report["warnings"].append("wood_asset_too_dark_for_oak_or_natural_wood_scene")
            score -= 0.18
        if red_bias > 62 and "walnut" in wood_name:
            report["warnings"].append("wood_asset_too_red_or_orange_for_walnut_scene")
            score -= 0.18
    if (category in NEUTRAL_CATEGORIES or object_id in NEUTRAL_CATEGORIES) and sat_mean > 0.42:
        report["warnings"].append("neutral_category_has_unexpectedly_strong_color")
        score -= 0.18
    report["style_alignment_score"] = round(max(0.0, min(1.0, score)), 4)
    report["ok"] = score >= 0.55
    return report
