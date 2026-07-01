#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${SAGE_TRELLIS_PYTHON:-python}"

: "${SAGE_TRELLIS_REPO:?Set SAGE_TRELLIS_REPO to the local TRELLIS.2 repo}"
: "${SAGE_TRELLIS_MODEL:?Set SAGE_TRELLIS_MODEL to the trellis2_primary model directory}"
: "${SAGE_RMBG_MODEL:?Set SAGE_RMBG_MODEL to the local RMBG-2.0 model directory}"

export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export HF_HOME="${HF_HOME:-/data/xy/hf}"
export HF_HUB_CACHE="${HF_HUB_CACHE:-${HF_HOME}/hub}"
export HF_XET_CACHE="${HF_XET_CACHE:-${HF_HOME}/xet}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"

"${PYTHON}" "${ROOT}/sage/server/trellis2_flux_bridge_server.py" \
  --host "${SAGE_TRELLIS_HOST:-127.0.0.1}" \
  --port "${SAGE_TRELLIS_PORT:-8082}" \
  --trellis-repo "${SAGE_TRELLIS_REPO}" \
  --trellis-model "${SAGE_TRELLIS_MODEL}" \
  --output-dir "${SAGE_TRELLIS_OUTPUT_DIR:-/data/xy/SAGE_repro/trellis2_bridge}" \
  --rmbg-model "${SAGE_RMBG_MODEL}" \
  --rmbg-module-root "${SAGE_RMBG_MODULE_ROOT:-/data/xy/pat3d_stage2_data/cache/hf_home/modules}" \
  --pipeline-type 512 \
  --trellis-preprocess-image \
  --texture-size 512 \
  --decimation-target 500000 \
  --no-glb-webp \
  "$@"

