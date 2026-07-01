#!/usr/bin/env python3
"""Generate a larger FLUX.1/FLUX.2 asset-image set for alpha-removal comparison."""

from __future__ import annotations

import gc
import json
import os
import time
from pathlib import Path

import torch
from PIL import Image, ImageDraw


FLUX1_MODEL = "/data/xy/pat3d_stage1_data/models/text_to_image__primary"
FLUX2_MODEL = "/data/xy/models/FLUX.2-klein-9B"
OUTPUT_DIR = Path("/data/xy/SAGE_repro/flux1_flux2_asset_alpha_compare")

CASES = [
    ("bookshelf", "a tall wooden bookshelf with several shelves and books"),
    ("filing_cabinet", "a gray metal filing cabinet with drawers"),
    ("office_chair", "a black ergonomic office chair with backrest and wheels"),
    ("coffee_mug", "a red ceramic coffee mug with handle"),
    ("document_folder", "a closed blue document folder with a few papers"),
    ("side_table", "a small square wooden side table"),
]


def asset_prompt(raw: str) -> str:
    return (
        "studio product image of exactly one object, object only, clean 3/4 view, "
        f"{raw}, full object visible, centered, realistic material details, "
        "flat solid saturated cyan background, strong color separation from the object, no white background, "
        "no extra props, no duplicate objects, no room, no walls, no floor, no ground plane, "
        "no pedestal, no display stand, no plinth, no base plate, no white platform, "
        "no table, no contact shadow, no reflection"
    )


def save_contact_sheet(records: list[dict[str, object]], output_path: Path) -> None:
    by_key = {(str(record["model"]), str(record["case"])): record for record in records}
    tile = 256
    label_h = 34
    cols = ["flux1-schnell", "flux2-klein"]
    sheet = Image.new("RGB", (tile * len(cols), (tile + label_h) * len(CASES)), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    for row, (case, _) in enumerate(CASES):
        for col, model in enumerate(cols):
            record = by_key[(model, case)]
            image = Image.open(str(record["path"])).convert("RGB")
            image.thumbnail((tile, tile), Image.Resampling.LANCZOS)
            x = col * tile
            y = row * (tile + label_h)
            draw.rectangle([x, y, x + tile, y + label_h], fill=(30, 30, 30))
            draw.text((x + 8, y + 10), f"{model} / {case}", fill=(255, 255, 255))
            canvas = Image.new("RGB", (tile, tile), (235, 235, 235))
            canvas.paste(image, ((tile - image.width) // 2, (tile - image.height) // 2))
            sheet.paste(canvas, (x, y + label_h))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)


def generate_flux1(records: list[dict[str, object]]) -> None:
    from diffusers import FluxPipeline

    pipe = FluxPipeline.from_pretrained(FLUX1_MODEL, torch_dtype=torch.bfloat16, local_files_only=True)
    pipe.enable_model_cpu_offload()
    pipe.set_progress_bar_config(disable=True)
    for idx, (case, raw) in enumerate(CASES):
        prompt = asset_prompt(raw)
        seed = 20260600 + idx
        start = time.time()
        image = pipe(
            prompt=prompt,
            width=768,
            height=768,
            num_inference_steps=4,
            guidance_scale=0.0,
            max_sequence_length=256,
            generator=torch.Generator(device="cuda").manual_seed(seed),
        ).images[0]
        path = OUTPUT_DIR / "raw" / f"flux1_schnell_{case}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        records.append(
            {
                "model": "flux1-schnell",
                "case": case,
                "raw_object": raw,
                "prompt": prompt,
                "path": str(path),
                "seed": seed,
                "seconds": round(time.time() - start, 3),
                "steps": 4,
                "guidance_scale": 0.0,
            }
        )
    del pipe
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def generate_flux2(records: list[dict[str, object]]) -> None:
    from diffusers import Flux2KleinPipeline

    pipe = Flux2KleinPipeline.from_pretrained(FLUX2_MODEL, torch_dtype=torch.bfloat16, local_files_only=True)
    pipe.enable_model_cpu_offload()
    pipe.set_progress_bar_config(disable=True)
    for idx, (case, raw) in enumerate(CASES):
        prompt = asset_prompt(raw)
        seed = 20260600 + idx
        start = time.time()
        image = pipe(
            prompt=prompt,
            width=768,
            height=768,
            num_inference_steps=4,
            guidance_scale=1.0,
            max_sequence_length=512,
            generator=torch.Generator(device="cuda").manual_seed(seed),
        ).images[0]
        path = OUTPUT_DIR / "raw" / f"flux2_klein_{case}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        records.append(
            {
                "model": "flux2-klein",
                "case": case,
                "raw_object": raw,
                "prompt": prompt,
                "path": str(path),
                "seed": seed,
                "seconds": round(time.time() - start, 3),
                "steps": 4,
                "guidance_scale": 1.0,
                "max_sequence_length": 512,
            }
        )
    del pipe
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def main() -> None:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    generate_flux1(records)
    generate_flux2(records)
    contact_sheet = OUTPUT_DIR / "raw_contact_sheet.png"
    save_contact_sheet(records, contact_sheet)
    summary = {
        "output_dir": str(OUTPUT_DIR),
        "raw_contact_sheet": str(contact_sheet),
        "cases": [{"case": case, "raw_object": raw} for case, raw in CASES],
        "records": records,
    }
    (OUTPUT_DIR / "raw_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
