#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${SAGE_ORCH_PYTHON:-python}"
EXAMPLE="${ROOT}/examples/bedroom_0610_113657"
OUTPUT_DIR="${SAGE_OUTPUT_DIR:-/data/xy/SAGE_runs/tree_sage_flow2/bedroom_0610_113657_plan_only_smoke}"

"${PYTHON}" "${ROOT}/sage/scripts/run_tree_sage_scene.py" \
  --prompt-file "${EXAMPLE}/prompt.txt" \
  --flux-image "${EXAMPLE}/reference_0610_113657.png" \
  --pose-reference-image "${EXAMPLE}/reference_0610_113657.png" \
  --scene-graph-file "${EXAMPLE}/scene_graph_augmented_curtains_ceiling_raw_input.json" \
  --output-dir "${OUTPUT_DIR}" \
  --model "${SAGE_CODEX_MODEL:-gpt-5}" \
  --no-reference-depth \
  --no-mujoco-check \
  --skip-asset-renders \
  --plan-only \
  "$@"

