#!/usr/bin/env python3
"""Generate a local DepthAnything reference depth map for TreeSAGE."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image
from transformers import pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a reference depth map with a local depth-estimation model.")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default="/data/xy/pat3d_stage1_data/models/depth__large_relative")
    parser.add_argument("--device", default="auto")
    return parser.parse_args()


def resolve_device(raw: str) -> int:
    raw = str(raw or "auto").strip().lower()
    if raw == "auto":
        return 0 if torch.cuda.is_available() else -1
    if raw.startswith("cuda:") and torch.cuda.is_available():
        return int(raw.split(":", 1)[1])
    if raw == "cuda" and torch.cuda.is_available():
        return 0
    try:
        return int(raw)
    except ValueError:
        return -1


def estimate_depth(depth_pipe: Any, image: Image.Image) -> np.ndarray:
    result = depth_pipe(image)
    if "predicted_depth" in result:
        value = result["predicted_depth"]
        if isinstance(value, torch.Tensor):
            arr = value.squeeze().detach().cpu().numpy()
        else:
            arr = np.asarray(value)
    else:
        arr = np.asarray(result["depth"])
    return np.asarray(arr, dtype=np.float32)


def normalize_depth_for_png(depth_map: np.ndarray) -> np.ndarray:
    values = np.asarray(depth_map, dtype=np.float32)
    finite = np.isfinite(values)
    if not finite.any():
        return np.zeros(values.shape, dtype=np.uint8)
    lo = float(np.percentile(values[finite], 1.0))
    hi = float(np.percentile(values[finite], 99.0))
    if hi <= lo + 1e-6:
        return np.zeros(values.shape, dtype=np.uint8)
    normalized = np.clip((values - lo) / (hi - lo), 0.0, 1.0)
    return (normalized * 255.0).astype(np.uint8)


def depth_metadata(depth_pipe: Any, requested_model: str) -> dict[str, Any]:
    model_cfg = getattr(getattr(depth_pipe, "model", None), "config", None)
    depth_estimation_type = str(
        getattr(model_cfg, "depth_estimation_type", None)
        or ("metric" if "metric" in requested_model.lower() else "relative")
    ).strip().lower()
    value_convention = "metric_depth" if depth_estimation_type == "metric" else "inverse_relative"
    max_depth = getattr(model_cfg, "max_depth", None)
    model_name = str(
        getattr(model_cfg, "_name_or_path", None)
        or getattr(model_cfg, "name_or_path", None)
        or requested_model
    )
    return {
        "requested_model": requested_model,
        "resolved_model": model_name,
        "depth_estimation_type": depth_estimation_type,
        "depth_value_convention": value_convention,
        "max_depth": float(max_depth) if max_depth is not None else None,
    }


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    image = Image.open(args.image).convert("RGB")
    depth_pipe = pipeline(task="depth-estimation", model=str(args.model), device=resolve_device(args.device))
    depth_map = estimate_depth(depth_pipe, image)
    meta = depth_metadata(depth_pipe, str(args.model))
    meta.update(
        {
            "schema": "tree_sage_reference_depth_model_report_v1",
            "image": str(args.image),
            "image_size": [int(image.size[0]), int(image.size[1])],
            "depth_map_npy": str(args.output_dir / "depth_map.npy"),
            "depth_map_png": str(args.output_dir / "depth_map.png"),
            "raw_stats": {
                "min": round(float(np.nanmin(depth_map)), 6),
                "max": round(float(np.nanmax(depth_map)), 6),
                "median": round(float(np.nanmedian(depth_map)), 6),
            },
        }
    )
    np.save(args.output_dir / "depth_map.npy", depth_map.astype(np.float32))
    Image.fromarray(normalize_depth_for_png(depth_map)).save(args.output_dir / "depth_map.png")
    (args.output_dir / "depth_model_report.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2), flush=True)


if __name__ == "__main__":
    main()
