#!/usr/bin/env python3
"""Render a simple top-down preview for a SAGE layout JSON."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


COLORS = {
    "desk": (153, 102, 61),
    "chair": (75, 120, 190),
    "shelf": (92, 140, 92),
    "cabinet": (150, 125, 85),
    "printer": (115, 115, 125),
    "router": (170, 95, 95),
}


def draw_rotated_rect(draw: ImageDraw.ImageDraw, cx: float, cy: float, w: float, h: float, angle_deg: float, fill, outline) -> None:
    angle = math.radians(angle_deg)
    corners = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    points = []
    for x, y in corners:
        rx = x * math.cos(angle) - y * math.sin(angle)
        ry = x * math.sin(angle) + y * math.cos(angle)
        points.append((cx + rx, cy + ry))
    draw.polygon(points, fill=fill, outline=outline)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("layout_json")
    parser.add_argument("output_png")
    parser.add_argument("--size", type=int, default=1400)
    args = parser.parse_args()

    layout = json.loads(Path(args.layout_json).read_text(encoding="utf-8"))
    room = layout["rooms"][0]
    margin = 90
    width_m = float(room["dimensions"]["width"])
    length_m = float(room["dimensions"]["length"])
    scale = min((args.size - 2 * margin) / width_m, (args.size - 2 * margin) / length_m)
    canvas_w = int(width_m * scale + 2 * margin)
    canvas_h = int(length_m * scale + 2 * margin)

    image = Image.new("RGB", (canvas_w, canvas_h), (241, 236, 225))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    def to_px(x: float, y: float) -> tuple[float, float]:
        return margin + x * scale, canvas_h - margin - y * scale

    x0, y0 = to_px(0, 0)
    x1, y1 = to_px(width_m, length_m)
    draw.rectangle([x0, y1, x1, y0], fill=(230, 222, 205), outline=(44, 44, 44), width=6)

    for door in room.get("doors", []):
        wall_id = door.get("wall_id", "")
        pos = float(door.get("position_on_wall", 0.5))
        door_w = float(door.get("width", 0.9)) * scale
        if "east" in wall_id:
            dx, dy = to_px(width_m, pos * length_m)
            draw.line([(dx, dy - door_w / 2), (dx, dy + door_w / 2)], fill=(225, 80, 55), width=10)
        elif "west" in wall_id:
            dx, dy = to_px(0, pos * length_m)
            draw.line([(dx, dy - door_w / 2), (dx, dy + door_w / 2)], fill=(225, 80, 55), width=10)
        elif "north" in wall_id:
            dx, dy = to_px(pos * width_m, length_m)
            draw.line([(dx - door_w / 2, dy), (dx + door_w / 2, dy)], fill=(225, 80, 55), width=10)
        else:
            dx, dy = to_px(pos * width_m, 0)
            draw.line([(dx - door_w / 2, dy), (dx + door_w / 2, dy)], fill=(225, 80, 55), width=10)

    for obj in room.get("objects", []):
        cx, cy = to_px(float(obj["position"]["x"]), float(obj["position"]["y"]))
        w = float(obj["dimensions"]["width"]) * scale
        h = float(obj["dimensions"]["length"]) * scale
        angle = -float(obj.get("rotation", {}).get("z", 0))
        color = COLORS.get(obj.get("type"), (130, 130, 130))
        draw_rotated_rect(draw, cx, cy, w, h, angle, color, (30, 30, 30))
        draw.text((cx + 4, cy + 4), obj.get("type", "obj"), fill=(20, 20, 20), font=font)

    title = f"{layout['id']} - {room['room_type']}"
    draw.text((margin, 25), title, fill=(20, 20, 20), font=font)
    Path(args.output_png).parent.mkdir(parents=True, exist_ok=True)
    image.save(args.output_png)
    print(args.output_png)


if __name__ == "__main__":
    main()
