#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${SAGE_FLUX2_PYTHON:-${SAGE_TRELLIS_PYTHON:-python}}"

: "${SAGE_FLUX2_MODEL:?Set SAGE_FLUX2_MODEL to the local FLUX.2-klein-9B model directory}"

export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export HF_HOME="${HF_HOME:-/data/xy/hf}"
export HF_HUB_CACHE="${HF_HUB_CACHE:-${HF_HOME}/hub}"
export HF_XET_CACHE="${HF_XET_CACHE:-${HF_HOME}/xet}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"

"${PYTHON}" "${ROOT}/sage/server/flux2_klein_server.py" \
  --host "${SAGE_FLUX2_HOST:-127.0.0.1}" \
  --port "${SAGE_FLUX2_PORT:-8084}" \
  --model-path "${SAGE_FLUX2_MODEL}" \
  --output-dir "${SAGE_FLUX2_OUTPUT_DIR:-/data/xy/SAGE_repro/flux2_klein_images}" \
  "$@"
