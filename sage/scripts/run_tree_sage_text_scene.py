#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from tree_sage_text.orchestrator import run_text_scene_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run TreeSAGE text-to-scene MVP pipeline.")
    parser.add_argument("--prompt")
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--room-type", choices=("bedroom", "living_room", "study"))
    parser.add_argument("--style")
    parser.add_argument("--candidate-count", type=int, default=3)
    parser.add_argument("--asset-strategy", choices=("generate_from_scratch", "asset_library"), default="generate_from_scratch")
    parser.add_argument("--asset-pipeline", choices=("none", "auto", "source_images", "asset_library", "trellis2_prompt"), default="auto")
    parser.add_argument("--asset-source-image-dir", type=Path)
    parser.add_argument("--asset-source-image-required", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--asset-source-image-qa-strict", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--trellis-asset-library-dir", type=Path)
    parser.add_argument("--articulated-asset-library-dir", type=Path)
    parser.add_argument("--reuse-asset-alias-file", type=Path)
    parser.add_argument("--human-constraints-file", type=Path, action="append")
    parser.add_argument("--asset-style-consistency", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--asset-style-qa-strict", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--room-texture-search", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--layout-critic", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--assemble-scene", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--trellis-url", default="http://127.0.0.1:8082")
    parser.add_argument("--trellis-pipeline-type", default="512", choices=("512", "1024", "1024_cascade", "1536_cascade"))
    parser.add_argument("--trellis-preprocess-image", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--asset-timeout", type=float, default=900.0)
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--texture-size", type=int, default=2048)
    parser.add_argument("--decimation-target", type=int, default=500000)
    parser.add_argument("--force-assets", action="store_true")
    parser.add_argument("--blender-bin", default="/data/xy/tools/blender-4.3.2-linux-x64/blender")
    parser.add_argument("--seed", type=int, default=1700)
    return parser.parse_args()


def main() -> None:
    summary = run_text_scene_pipeline(parse_args())
    print(f"[tree-sage-text] wrote {summary['scene_plan']}")
    print(f"[tree-sage-text] preview {summary['layout_preview']}")


if __name__ == "__main__":
    main()
