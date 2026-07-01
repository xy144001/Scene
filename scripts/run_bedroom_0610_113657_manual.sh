#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${SAGE_ORCH_PYTHON:-python}"
EXAMPLE="${ROOT}/examples/bedroom_0610_113657"
SOURCE_IMAGES="${SAGE_BEDROOM_SOURCE_IMAGES:-${EXAMPLE}/source_images}"
OUTPUT_DIR="${SAGE_OUTPUT_DIR:-/data/xy/SAGE_runs/tree_sage_flow2/bedroom_0610_113657_manual}"

if [ ! -d "${SOURCE_IMAGES}" ]; then
  echo "Missing source images: ${SOURCE_IMAGES}" >&2
  echo "Run scripts/prepare_bedroom_source_images_from_local.sh or place image2 source images there." >&2
  exit 2
fi

"${PYTHON}" "${ROOT}/sage/scripts/run_tree_sage_scene.py" \
  --prompt-file "${EXAMPLE}/prompt.txt" \
  --flux-image "${EXAMPLE}/reference_0610_113657.png" \
  --pose-reference-image "${EXAMPLE}/reference_0610_113657.png" \
  --scene-graph-file "${EXAMPLE}/scene_graph_augmented_curtains_ceiling_raw_input.json" \
  --human-constraints-file "${EXAMPLE}/human_constraints_manual_bbox_v1.json" \
  --output-dir "${OUTPUT_DIR}" \
  --trellis-url "${SAGE_TRELLIS_URL:-http://127.0.0.1:8082}" \
  --trellis-pipeline-type 512 \
  --trellis-preprocess-image \
  --asset-source-image-dir "${SOURCE_IMAGES}" \
  --asset-source-image-required \
  --texture-size 512 \
  --decimation-target 500000 \
  --steps 12 \
  --seed 1700 \
  --blender-bin "${SAGE_BLENDER_BIN:-/data/xy/tools/blender-4.3.2-linux-x64/blender}" \
  --model "${SAGE_CODEX_MODEL:-gpt-5}" \
  "$@"

