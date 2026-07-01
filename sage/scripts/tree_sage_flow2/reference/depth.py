"""Reference-depth module boundary for TreeSAGE Flow 2.

Depth estimation currently still depends on several scene-graph and semantic
helpers that live in the main runner.  This wrapper makes reference analysis a
separate call site now, while allowing the internals to move here incrementally.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


ReferenceDepthBuilder = Callable[[Any, dict[str, Any], Path], dict[str, Any]]


def run_reference_depth_analysis(
    *,
    builder: ReferenceDepthBuilder,
    args: Any,
    scene_graph: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    return builder(args, scene_graph, output_dir)
