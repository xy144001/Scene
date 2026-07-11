from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
import random
from typing import Any


TEXTURE_SEARCH_REFERENCES = [
    {
        "title": "Neutral living room guidance",
        "url": "https://www.thespruce.com/neutral-living-room-ideas-8663497",
        "takeaway": "Neutral living rooms commonly use cream, beige, greige, taupe, natural wood, and layered subtle texture.",
    },
    {
        "title": "Interior paint finish guidance",
        "url": "https://www.architecturaldigest.com/story/interior-paint-buying-guide",
        "takeaway": "Eggshell or matte-like interior wall finishes are common for lived-in areas because they hide imperfections while staying practical.",
    },
    {
        "title": "Textured wall finish guidance",
        "url": "https://www.bhg.com/eco-friendly-wall-finishes-8584394",
        "takeaway": "Limewash, chalk finish, Venetian plaster, and clay/plaster-like finishes add depth without strong visual clutter.",
    },
    {
        "title": "Living room flooring guidance",
        "url": "https://www.thespruce.com/flooring-choices-creating-more-work-11937760",
        "takeaway": "Low-sheen natural or mid-tone wood is more forgiving than high-gloss or very dark flooring in main living spaces.",
    },
    {
        "title": "Wood floor design guidance",
        "url": "https://www.bhg.com/home-improvement/flooring/types/decorating-with-wood-floors/",
        "takeaway": "Wood floors add warmth and work as a neutral base when balanced with rugs and softer textures.",
    },
]


WALL_PRESETS: dict[str, dict[str, Any]] = {
    "warm_greige_plaster": {
        "texture_type": "procedural_painted_plaster",
        "texture_label": "warm greige painted plaster",
        "base_color": [0.82, 0.79, 0.72],
        "secondary_color": [0.9, 0.875, 0.82],
        "roughness": 0.9,
        "noise_scale": 42.0,
        "noise_detail": 8.0,
        "bump_strength": 0.018,
        "visual_intensity": "subtle",
    },
    "soft_warm_white_limewash": {
        "texture_type": "procedural_limewash",
        "texture_label": "soft warm white limewash",
        "base_color": [0.88, 0.86, 0.81],
        "secondary_color": [0.96, 0.945, 0.91],
        "roughness": 0.92,
        "noise_scale": 28.0,
        "noise_detail": 10.0,
        "bump_strength": 0.014,
        "visual_intensity": "subtle",
    },
    "quiet_taupe_matte_paint": {
        "texture_type": "procedural_matte_paint",
        "texture_label": "quiet taupe matte paint",
        "base_color": [0.72, 0.68, 0.62],
        "secondary_color": [0.82, 0.79, 0.73],
        "roughness": 0.88,
        "noise_scale": 55.0,
        "noise_detail": 6.0,
        "bump_strength": 0.008,
        "visual_intensity": "very_subtle",
    },
    "soft_gray_plaster": {
        "texture_type": "procedural_painted_plaster",
        "texture_label": "soft warm gray plaster",
        "base_color": [0.72, 0.72, 0.69],
        "secondary_color": [0.83, 0.825, 0.79],
        "roughness": 0.9,
        "noise_scale": 38.0,
        "noise_detail": 8.0,
        "bump_strength": 0.014,
        "visual_intensity": "subtle",
    },
}


FLOOR_PRESETS: dict[str, dict[str, Any]] = {
    "natural_oak_low_sheen": {
        "texture_type": "procedural_wood_plank",
        "texture_label": "natural oak low-sheen planks",
        "base_color": [0.58, 0.42, 0.27],
        "secondary_color": [0.72, 0.56, 0.36],
        "grain_color": [0.38, 0.25, 0.14],
        "roughness": 0.72,
        "wave_scale": 18.0,
        "wave_distortion": 8.0,
        "bump_strength": 0.032,
        "visual_intensity": "moderate",
    },
    "light_white_oak_low_sheen": {
        "texture_type": "procedural_wood_plank",
        "texture_label": "light white oak low-sheen planks",
        "base_color": [0.68, 0.56, 0.39],
        "secondary_color": [0.82, 0.72, 0.52],
        "grain_color": [0.48, 0.35, 0.2],
        "roughness": 0.76,
        "wave_scale": 16.0,
        "wave_distortion": 7.0,
        "bump_strength": 0.026,
        "visual_intensity": "moderate",
    },
    "honey_oak_low_sheen": {
        "texture_type": "procedural_wood_plank",
        "texture_label": "honey oak low-sheen planks",
        "base_color": [0.62, 0.43, 0.23],
        "secondary_color": [0.78, 0.58, 0.32],
        "grain_color": [0.42, 0.27, 0.12],
        "roughness": 0.74,
        "wave_scale": 17.0,
        "wave_distortion": 9.0,
        "bump_strength": 0.03,
        "visual_intensity": "moderate",
    },
    "soft_wool_carpet": {
        "texture_type": "procedural_low_pile_carpet",
        "texture_label": "soft warm neutral low-pile carpet",
        "base_color": [0.64, 0.58, 0.48],
        "secondary_color": [0.78, 0.72, 0.62],
        "roughness": 0.96,
        "noise_scale": 72.0,
        "noise_detail": 12.0,
        "bump_strength": 0.018,
        "visual_intensity": "subtle",
    },
}


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(needle in lowered for needle in needles)


def _copy_spec(spec: dict[str, Any], *, role: str, source: str) -> dict[str, Any]:
    result = deepcopy(spec)
    result["role"] = role
    result["source"] = source
    result["alpha"] = 1.0
    return result


def _select_wall_preset(room_type: str, style_tags: list[str], prompt: str) -> str:
    style_text = " ".join(style_tags).lower()
    combined = f"{style_text} {prompt}".lower()
    if _contains_any(prompt.lower(), ("beige wall", "beige walls", "cream wall", "cream walls", "warm neutral", "greige")):
        return "warm_greige_plaster"
    if _contains_any(combined, ("industrial", "concrete", "gray", "grey")):
        return "soft_gray_plaster"
    if _contains_any(combined, ("taupe", "moody", "traditional")):
        return "quiet_taupe_matte_paint"
    if room_type == "bedroom" or _contains_any(combined, ("minimal", "japandi", "white", "cream")):
        return "soft_warm_white_limewash"
    return "warm_greige_plaster"


def _select_floor_preset(room_type: str, style_tags: list[str], prompt: str) -> str:
    style_text = " ".join(style_tags).lower()
    combined = f"{style_text} {prompt}".lower()
    if _contains_any(combined, ("carpet", "soft underfoot", "wall-to-wall")) and room_type == "bedroom":
        return "soft_wool_carpet"
    if _contains_any(combined, ("light wood", "white oak", "japandi", "minimal", "scandinavian")):
        return "light_white_oak_low_sheen"
    if _contains_any(combined, ("warm", "cozy", "honey", "american")):
        return "honey_oak_low_sheen"
    return "natural_oak_low_sheen"


def build_room_texture_search_plan(brief: dict[str, Any], prompt: str) -> dict[str, Any]:
    room_type = str(brief.get("room_type") or "bedroom")
    style_tags = [str(tag) for tag in brief.get("style_tags") or []]
    style_text = str(brief.get("style_text") or " ".join(style_tags))
    wall_key = _select_wall_preset(room_type, style_tags, prompt)
    floor_key = _select_floor_preset(room_type, style_tags, prompt)
    wall = _copy_spec(WALL_PRESETS[wall_key], role="wall", source="text_scene_texture_search")
    floor = _copy_spec(FLOOR_PRESETS[floor_key], role="floor", source="text_scene_texture_search")
    ceiling = {
        "texture_type": "procedural_matte_paint",
        "texture_label": "plain warm white ceiling paint",
        "base_color": [0.9, 0.89, 0.85],
        "secondary_color": [0.96, 0.955, 0.93],
        "roughness": 0.9,
        "noise_scale": 60.0,
        "noise_detail": 4.0,
        "bump_strength": 0.004,
        "visual_intensity": "very_subtle",
        "role": "ceiling",
        "source": "text_scene_texture_search",
        "alpha": 1.0,
    }
    materials = {
        "schema": "tree_sage_text_material_plan_v2",
        "source": "text_scene_texture_search",
        "global_wall": wall,
        "walls": {wall_id: deepcopy(wall) for wall_id in ("wall_north", "wall_south", "wall_west", "wall_east")},
        "ceiling": ceiling,
        "floor": floor,
    }
    search_queries = [
        f"{room_type.replace('_', ' ')} warm neutral wall texture painted plaster limewash",
        f"{room_type.replace('_', ' ')} low sheen natural wood floor warm neutral",
        f"{style_text} interior common wall floor texture",
    ]
    return {
        "schema": "tree_sage_text_room_texture_search_v1",
        "enabled": True,
        "room_type": room_type,
        "style_tags": style_tags,
        "search_queries": search_queries,
        "reference_notes": TEXTURE_SEARCH_REFERENCES,
        "selection": {
            "wall_preset": wall_key,
            "floor_preset": floor_key,
            "wall": wall,
            "floor": floor,
            "ceiling": ceiling,
        },
        "materials": materials,
    }


def _rgb255(color: object, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    if not isinstance(color, (list, tuple)) or len(color) < 3:
        return fallback
    try:
        values = [float(value) for value in color[:3]]
    except (TypeError, ValueError):
        return fallback
    if max(values) <= 1.0:
        values = [value * 255.0 for value in values]
    return tuple(max(0, min(255, int(round(value)))) for value in values)  # type: ignore[return-value]


def _mix_rgb(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return (
        int(round(a[0] * (1.0 - t) + b[0] * t)),
        int(round(a[1] * (1.0 - t) + b[1] * t)),
        int(round(a[2] * (1.0 - t) + b[2] * t)),
    )


def _write_wall_texture(spec: dict[str, Any], path: Path, seed: int) -> None:
    from PIL import Image, ImageFilter

    size = 768
    rng = random.Random(seed)
    base = _rgb255(spec.get("base_color"), (214, 205, 188))
    secondary = _rgb255(spec.get("secondary_color"), (232, 225, 210))
    noise = Image.effect_noise((size, size), 28.0).convert("L").filter(ImageFilter.GaussianBlur(radius=1.6))
    px = noise.load()
    image = Image.new("RGB", (size, size), base)
    out = image.load()
    for y in range(size):
        wash = 0.045 * math.sin((y / size) * 8.0 + rng.random() * 0.02)
        for x in range(size):
            value = px[x, y] / 255.0
            t = max(0.0, min(1.0, 0.34 + (value - 0.5) * 0.38 + wash))
            out[x, y] = _mix_rgb(base, secondary, t)
    image.save(path)


def _write_wood_texture(spec: dict[str, Any], path: Path, seed: int) -> None:
    from PIL import Image, ImageDraw, ImageFilter

    width = 1024
    height = 1024
    rng = random.Random(seed)
    base = _rgb255(spec.get("base_color"), (158, 110, 59))
    secondary = _rgb255(spec.get("secondary_color"), (198, 148, 82))
    grain = _rgb255(spec.get("grain_color"), (92, 58, 29))
    image = Image.new("RGB", (width, height), base)
    draw = ImageDraw.Draw(image)
    plank_h = 82
    y = 0
    while y < height:
        h = plank_h + rng.randint(-12, 14)
        row_color = _mix_rgb(base, secondary, rng.uniform(0.22, 0.5))
        draw.rectangle((0, y, width, min(height, y + h)), fill=row_color)
        draw.line((0, y, width, y), fill=_mix_rgb(row_color, grain, 0.18), width=2)
        for _ in range(20):
            yy = rng.randint(y, min(height - 1, y + h))
            x0 = rng.randint(0, width - 120)
            x1 = min(width, x0 + rng.randint(120, 520))
            line_color = _mix_rgb(row_color, grain, rng.uniform(0.08, 0.22))
            draw.line((x0, yy, x1, yy + rng.randint(-3, 3)), fill=line_color, width=1)
        y += h
    image = image.filter(ImageFilter.GaussianBlur(radius=0.25))
    image.save(path)


def _write_carpet_texture(spec: dict[str, Any], path: Path, seed: int) -> None:
    from PIL import Image, ImageFilter

    size = 768
    base = _rgb255(spec.get("base_color"), (164, 148, 122))
    secondary = _rgb255(spec.get("secondary_color"), (198, 184, 158))
    noise = Image.effect_noise((size, size), 54.0).convert("L").filter(ImageFilter.GaussianBlur(radius=0.45))
    px = noise.load()
    image = Image.new("RGB", (size, size), base)
    out = image.load()
    for y in range(size):
        for x in range(size):
            value = px[x, y] / 255.0
            t = max(0.0, min(1.0, 0.42 + (value - 0.5) * 0.52))
            out[x, y] = _mix_rgb(base, secondary, t)
    image.save(path)


def materialize_room_texture_images(texture_report: dict[str, Any], texture_dir: Path) -> dict[str, Any]:
    texture_dir.mkdir(parents=True, exist_ok=True)
    selection = texture_report.get("selection") if isinstance(texture_report.get("selection"), dict) else {}
    wall = selection.get("wall") if isinstance(selection.get("wall"), dict) else None
    floor = selection.get("floor") if isinstance(selection.get("floor"), dict) else None
    written: dict[str, str] = {}
    try:
        if wall:
            wall_path = texture_dir / "wall_texture.png"
            _write_wall_texture(wall, wall_path, 3101)
            wall["texture_image"] = str(wall_path)
            texture_report["materials"]["global_wall"]["texture_image"] = str(wall_path)
            for wall_spec in texture_report["materials"]["walls"].values():
                wall_spec["texture_image"] = str(wall_path)
            written["wall"] = str(wall_path)
        if floor:
            floor_path = texture_dir / "floor_texture.png"
            texture_type = str(floor.get("texture_type") or "")
            if texture_type == "procedural_low_pile_carpet":
                _write_carpet_texture(floor, floor_path, 4403)
            else:
                _write_wood_texture(floor, floor_path, 4403)
            floor["texture_image"] = str(floor_path)
            texture_report["materials"]["floor"]["texture_image"] = str(floor_path)
            written["floor"] = str(floor_path)
        texture_report["materialized_textures"] = written
    except Exception as exc:
        texture_report["materialized_textures"] = written
        texture_report["texture_generation_warning"] = f"{type(exc).__name__}: {exc}"
    return texture_report
