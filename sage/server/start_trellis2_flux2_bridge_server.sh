#!/usr/bin/env bash

set -e

export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"

/home/xy/PAT3D/pat3d_stage2/pat2/bin/python "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/trellis2_flux_bridge_server.py" \
  --flux-server-url "${FLUX2_SERVER_URL:-http://127.0.0.1:8084}" \
  --flux-profile flux2-klein \
  "$@"
