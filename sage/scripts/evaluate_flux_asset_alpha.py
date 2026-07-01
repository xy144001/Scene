#!/usr/bin/env python3
"""Run current Trellis2 bridge alpha-prep logic on FLUX.1/FLUX.2 asset images."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw


ROOT = Path("/data/xy/SAGE_repro/flux1_flux2_asset_alpha_compare")
RAW_SUMMARY = ROOT / "raw_summary.json"
ALPHA_DIR = ROOT / "alpha_bridge"


def checkerboard(size: tuple[int, int]) -> Image.Image:
    w, h = size
    tile = 24
    canvas = Image.new("RGB", size, (230, 230, 230))
    draw = ImageDraw.Draw(canvas)
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            if ((x // tile) + (y // tile)) % 2 == 0:
                draw.rectangle([x, y, x + tile - 1, y + tile - 1], fill=(180, 180, 180))
    return canvas


def alpha_composite_preview(path: Path, size: int = 256) -> Image.Image:
    rgba = Image.open(path).convert("RGBA")
    bg = checkerboard(rgba.size).convert("RGBA")
    composited = Image.alpha_composite(bg, rgba).convert("RGB")
    composited.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (size, size), (235, 235, 235))
    canvas.paste(composited, ((size - composited.width) // 2, (size - composited.height) // 2))
    return canvas


def thumb_rgb(path: Path, size: int = 256) -> Image.Image:
    image = Image.open(path).convert("RGB")
    image.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (size, size), (235, 235, 235))
    canvas.paste(image, ((size - image.width) // 2, (size - image.height) // 2))
    return canvas


def thumb_mask(path: Path, size: int = 256) -> Image.Image:
    image = Image.open(path).convert("L")
    image.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("L", (size, size), 0)
    canvas.paste(image, ((size - image.width) // 2, (size - image.height) // 2))
    return canvas.convert("RGB")


def bottom_white_foreground_ratio(rgba_path: Path) -> float:
    rgba = np.array(Image.open(rgba_path).convert("RGBA"), dtype=np.uint8)
    rgb = rgba[:, :, :3].astype(np.float32)
    alpha = rgba[:, :, 3] > 24
    h = rgba.shape[0]
    bottom = np.zeros_like(alpha)
    bottom[int(h * 0.62) :, :] = True
    try:
        import cv2

        hsv = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2HSV)
        white_like = (hsv[:, :, 1] <= 45) & (hsv[:, :, 2] >= 210)
    except Exception:
        maxc = rgb.max(axis=2)
        minc = rgb.min(axis=2)
        white_like = (maxc >= 210) & ((maxc - minc) <= 45)
    denom = np.count_nonzero(alpha & bottom)
    if denom == 0:
        return 0.0
    return float(np.count_nonzero(alpha & bottom & white_like)) / float(denom)


def load_bridge_runtime():
    spec = importlib.util.spec_from_file_location("trellis2_bridge", "server/trellis2_flux_bridge_server.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    args = SimpleNamespace(
        output_dir=str(ALPHA_DIR),
        alpha_mode="rembg",
        alpha_fallback_threshold=True,
        alpha_threshold=48.0,
        bg_saturation_threshold=28.0,
        bg_value_threshold=222.0,
        alpha_min_component_ratio=0.00025,
        alpha_morph_kernel=5,
        alpha_dilate=1,
        alpha_bbox_threshold=24,
        alpha_content_scale=0.86,
        alpha_quality_check=True,
        alpha_require_quality=False,
        alpha_min_foreground_ratio=0.012,
        alpha_max_foreground_ratio=0.68,
        alpha_max_border_foreground_ratio=0.015,
        rmbg_model="/data/xy/pat3d_stage2_data/models/rmbg_2_0",
        rmbg_module_root="/data/xy/pat3d_stage2_data/cache/hf_home/modules",
        rmbg_offload_cpu=True,
        device="cuda",
    )
    return module.Trellis2BridgeRuntime(args)


def save_alpha_contact(records: list[dict[str, object]], output_path: Path) -> None:
    cases = []
    for record in records:
        case = str(record["case"])
        if case not in cases:
            cases.append(case)
    by_key = {(str(record["model"]), str(record["case"])): record for record in records}
    tile = 220
    label_h = 34
    columns = [
        ("flux1-schnell", "raw"),
        ("flux1-schnell", "cutout"),
        ("flux1-schnell", "mask"),
        ("flux2-klein", "raw"),
        ("flux2-klein", "cutout"),
        ("flux2-klein", "mask"),
    ]
    sheet = Image.new("RGB", (tile * len(columns), (tile + label_h) * len(cases)), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    for row, case in enumerate(cases):
        for col, (model, view) in enumerate(columns):
            record = by_key[(model, case)]
            if view == "raw":
                image = thumb_rgb(Path(str(record["raw_path"])), tile)
            elif view == "cutout":
                image = alpha_composite_preview(Path(str(record["prepared_image_path"])), tile)
            else:
                image = thumb_mask(Path(str(record["mask_path"])), tile)
            x = col * tile
            y = row * (tile + label_h)
            draw.rectangle([x, y, x + tile, y + label_h], fill=(30, 30, 30))
            draw.text((x + 8, y + 10), f"{model} / {case} / {view}", fill=(255, 255, 255))
            sheet.paste(image, (x, y + label_h))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)


def main() -> None:
    summary = json.loads(RAW_SUMMARY.read_text(encoding="utf-8"))
    ALPHA_DIR.mkdir(parents=True, exist_ok=True)
    runtime = load_bridge_runtime()
    records: list[dict[str, object]] = []
    for raw_record in summary["records"]:
        model = str(raw_record["model"])
        case = str(raw_record["case"])
        raw_path = Path(str(raw_record["path"]))
        job_id = f"{model.replace('-', '_')}_{case}"
        prepared = runtime._prepare_reference_rgba(raw_path, job_id, SimpleNamespace())
        metadata_path = ALPHA_DIR / "reference_rgba" / f"{job_id}.alpha.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        mask_path = Path(str(metadata["mask_path"]))
        records.append(
            {
                "model": model,
                "case": case,
                "raw_path": str(raw_path),
                "prepared_image_path": str(prepared),
                "mask_path": str(mask_path),
                "alpha_method": metadata.get("method"),
                "alpha_quality": metadata.get("alpha_quality"),
                "bottom_white_foreground_ratio": round(bottom_white_foreground_ratio(prepared), 6),
                "generation_seconds": raw_record.get("seconds"),
            }
        )
    contact = ROOT / "alpha_contact_sheet.png"
    save_alpha_contact(records, contact)
    aggregate: dict[str, dict[str, object]] = {}
    for model in sorted({str(record["model"]) for record in records}):
        model_records = [record for record in records if record["model"] == model]
        aggregate[model] = {
            "cases": len(model_records),
            "alpha_ok": sum(1 for r in model_records if r.get("alpha_quality", {}).get("ok")),
            "mean_bottom_white_foreground_ratio": round(
                float(np.mean([float(r["bottom_white_foreground_ratio"]) for r in model_records])),
                6,
            ),
            "mean_generation_seconds": round(
                float(np.mean([float(r["generation_seconds"]) for r in model_records])),
                3,
            ),
            "methods": sorted({str(r["alpha_method"]) for r in model_records}),
        }
    result = {
        "output_dir": str(ROOT),
        "alpha_contact_sheet": str(contact),
        "records": records,
        "aggregate": aggregate,
    }
    (ROOT / "alpha_summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
