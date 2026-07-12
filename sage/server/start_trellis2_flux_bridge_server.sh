#!/usr/bin/env bash

set -e

export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
PIPELINE_TYPE="${TRELLIS_PIPELINE_TYPE:-512}"

/home/xy/PAT3D/pat3d_stage2/pat2/bin/python "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/trellis2_flux_bridge_server.py" --pipeline-type "$PIPELINE_TYPE" "$@"
