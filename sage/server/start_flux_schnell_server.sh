#!/usr/bin/env bash

set -e

export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"

/home/xy/PAT3D/pat3d_stage1/pat/bin/python "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/flux_schnell_server.py" "$@"
