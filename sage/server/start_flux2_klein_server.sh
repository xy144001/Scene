#!/usr/bin/env bash

set -e

export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export HF_HOME="${HF_HOME:-/data/xy/hf}"
export HF_HUB_CACHE="${HF_HUB_CACHE:-/data/xy/hf/hub}"
export HF_XET_CACHE="${HF_XET_CACHE:-/data/xy/hf/xet}"

/home/xy/PAT3D/pat3d_stage1/pat/bin/python "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/flux2_klein_server.py" "$@"
