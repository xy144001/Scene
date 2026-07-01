#!/usr/bin/env python3
"""Generate a small local FLUX.1 vs FLUX.2 comparison set for SAGE references."""

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
OUTPUT_DIR = Path("/data/xy/SAGE_repro/flux1_flux2_compare_smoke")

SCENE_PROMPT = (
    "A realistic compact office interior, wide angle view, all objects visible. "
    "There is a desk holding a coffee mug and document folder with an office chair in front. "
    "A tall bookshelf is against the back wall with a stapler on or near it. "
    "A filing cabinet with a tape dispenser is positioned away from the desk and bookshelf. "
    "A side table is near the desk. Clear spatial relationships, no extra objects."
)

OBJECT_PROMPT = (
    "studio product image of exactly one object, object only, clean 3/4 view, "
    "a tall wooden bookshelf with several shelves and books, "
    "full object visible, centered, realistic material details, "
    "flat solid saturated cyan background, strong color separation from the object, no white background, "
    "no extra props, no duplicate objects, no room, no walls, no floor, no ground plane, "
    "no pedestal, no display stand, no plinth, no base plate, no white platform, "
    "no table, no contact shadow, no reflection"
)


def _save_contact_sheet(records: list[dict[str, object]], output_path: Path) -> None:
    images = [Image.open(str(record["path"])).convert("RGB") for record in records]
    tile_w, tile_h = images[0].size
    label_h = 42
    sheet = Image.new("RGB", (tile_w * 2, (tile_h + label_h) * 2), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    for idx, (record, image) in enumerate(zip(records, images)):
        col = idx % 2
        row = idx // 2
        x = col * tile_w
        y = row * (tile_h + label_h)
        label = f"{record['model']} / {record['case']}"
        draw.rectangle([x, y, x + tile_w, y + label_h], fill=(30, 30, 30))
        draw.text((x + 12, y + 12), label, fill=(255, 255, 255))
        sheet.paste(image, (x, y + label_h))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)


def _generate_flux1(records: list[dict[str, object]]) -> None:
    from diffusers import FluxPipeline

    pipe = FluxPipeline.from_pretrained(FLUX1_MODEL, torch_dtype=torch.bfloat16, local_files_only=True)
    pipe.enable_model_cpu_offload()
    pipe.set_progress_bar_config(disable=True)
    for case, prompt, seed in [
        ("scene", SCENE_PROMPT, 20260530),
        ("object", OBJECT_PROMPT, 20260531),
    ]:
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
        path = OUTPUT_DIR / f"flux1_schnell_{case}.png"
        image.save(path)
        records.append(
            {
                "model": "flux1-schnell",
                "case": case,
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


def _generate_flux2(records: list[dict[str, object]]) -> None:
    from diffusers import Flux2KleinPipeline

    pipe = Flux2KleinPipeline.from_pretrained(FLUX2_MODEL, torch_dtype=torch.bfloat16, local_files_only=True)
    pipe.enable_model_cpu_offload()
    pipe.set_progress_bar_config(disable=True)
    for case, prompt, seed in [
        ("scene", SCENE_PROMPT, 20260530),
        ("object", OBJECT_PROMPT, 20260531),
    ]:
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
        path = OUTPUT_DIR / f"flux2_klein_{case}.png"
        image.save(path)
        records.append(
            {
                "model": "flux2-klein",
                "case": case,
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
    _generate_flux1(records)
    _generate_flux2(records)
    contact_sheet = OUTPUT_DIR / "contact_sheet.png"
    _save_contact_sheet(records, contact_sheet)
    summary = {
        "output_dir": str(OUTPUT_DIR),
        "contact_sheet": str(contact_sheet),
        "scene_prompt": SCENE_PROMPT,
        "object_prompt": OBJECT_PROMPT,
        "records": records,
    }
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
