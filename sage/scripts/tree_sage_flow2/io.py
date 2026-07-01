"""Shared JSON IO helpers for TreeSAGE Flow 2.

These wrappers keep Flow 2 imports stable while the large runner is split into
smaller modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from run_selfmade_trellis_scene import extract_json as _extract_json
from run_selfmade_trellis_scene import write_json as _write_json


def extract_json(text: str) -> Any:
    return _extract_json(text)


def write_json(path: Path, data: Any) -> None:
    _write_json(path, data)
