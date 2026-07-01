#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${1:-/data/xy/SAGE_runs/image2_replacement_20260624/source_images}"
DST="${SAGE_BEDROOM_SOURCE_IMAGES:-${ROOT}/examples/bedroom_0610_113657/source_images}"

mkdir -p "${DST}"
rsync -a "${SRC}/" "${DST}/"
echo "Copied source images to ${DST}"

