from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from .layout import object_bbox_xy


COLORS = {
    "bed": "#7b5a42",
    "nightstand": "#9a6a3f",
    "wardrobe": "#8a5b32",
    "dresser": "#a06a3c",
    "desk": "#7b6248",
    "chair": "#2d3238",
    "sofa": "#6a756b",
    "coffee_table": "#9a6a3f",
    "tv_stand": "#7b6248",
    "tv": "#202428",
    "bookcase": "#745331",
    "rug": "#d8d0bf",
    "window": "#b7d5e9",
    "curtain": "#c8c0ae",
    "door": "#f0eee8",
    "wall_art": "#d6c3a4",
    "plant": "#4f7f49",
    "table_lamp": "#e4d7b7",
    "floor_lamp": "#d6c3a4",
    "ceiling_light": "#f0dfb8",
}


def _svg_rect(x: float, y: float, w: float, h: float, fill: str, stroke: str = "#1f2933", opacity: float = 1.0) -> str:
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="1.2" opacity="{opacity:.3f}" />'
    )


def write_topdown_svg(plan: dict[str, Any], path: Path) -> None:
    room = plan["room"]
    room_w = float(room["width"])
    room_l = float(room["length"])
    scale = 140.0
    pad = 42.0
    canvas_w = room_w * scale + pad * 2.0
    canvas_h = room_l * scale + pad * 2.0
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w:.0f}" height="{canvas_h:.0f}" viewBox="0 0 {canvas_w:.0f} {canvas_h:.0f}">',
        '<rect width="100%" height="100%" fill="#f6f5ef"/>',
        _svg_rect(pad, pad, room_w * scale, room_l * scale, "#ffffff", "#303a33"),
        f'<text x="{pad:.1f}" y="24" font-family="Arial" font-size="16" fill="#1e2521">{escape(str(plan.get("scene_id", "text scene")))}</text>',
    ]
    for wall, label_x, label_y in (
        ("N", pad + room_w * scale / 2, pad - 10),
        ("S", pad + room_w * scale / 2, pad + room_l * scale + 24),
        ("W", pad - 24, pad + room_l * scale / 2),
        ("E", pad + room_w * scale + 16, pad + room_l * scale / 2),
    ):
        parts.append(f'<text x="{label_x:.1f}" y="{label_y:.1f}" font-family="Arial" font-size="12" fill="#647067">{wall}</text>')

    for obj in plan.get("objects", []):
        if not isinstance(obj, dict):
            continue
        category = str(obj.get("category") or "")
        fill = COLORS.get(category, "#b8b0a3")
        x0, y0, x1, y1 = object_bbox_xy(obj)
        sx = pad + x0 * scale
        sy = pad + (room_l - y1) * scale
        sw = max(2.0, (x1 - x0) * scale)
        sh = max(2.0, (y1 - y0) * scale)
        opacity = 0.65 if category in {"rug", "wall_art", "window", "curtain", "door", "tv", "ceiling_light"} else 0.92
        parts.append(_svg_rect(sx, sy, sw, sh, fill, "#26302b", opacity))
        label = escape(str(obj.get("id") or category))
        parts.append(
            f'<text x="{sx + 3:.1f}" y="{sy + min(14.0, sh - 3.0):.1f}" '
            f'font-family="Arial" font-size="10" fill="#121714">{label}</text>'
        )
    parts.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
