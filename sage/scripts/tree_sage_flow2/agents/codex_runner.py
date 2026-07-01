"""Shared Codex CLI runner for Flow 2 JSON agents."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from tree_sage_flow2.io import extract_json


def run_codex_json_agent(
    *,
    agent_name: str,
    prompt: str,
    image_path: Path,
    output_dir: Path,
    request_path: Path,
    response_path: Path,
    stdout_path: Path,
    stderr_path: Path,
    model: str | None = None,
    prompt_arg: str | None = None,
    cwd: Path | None = None,
    reasoning_effort: str = "low",
) -> dict[str, Any]:
    """Run one short-lived Codex JSON agent and return parsed JSON.

    The subprocess is intentionally ephemeral and read-only. It is not a
    persistent chat window; the caller owns all state through request/response
    files in the output directory.
    """

    output_dir.mkdir(parents=True, exist_ok=True)
    request_path.write_text(prompt, encoding="utf-8")
    cmd = [
        "codex",
        "exec",
        "--ignore-user-config",
        "--ignore-rules",
        "--disable",
        "plugins",
        "--disable",
        "plugin_sharing",
        "--disable",
        "plugin_hooks",
        "-c",
        f'model_reasoning_effort="{reasoning_effort}"',
        "--ephemeral",
        "--cd",
        str(cwd or Path.cwd()),
        "--sandbox",
        "read-only",
        "--output-last-message",
        str(response_path),
        "--image",
        str(image_path),
        "--",
        prompt_arg if prompt_arg is not None else prompt,
    ]
    if model:
        cmd[2:2] = ["--model", model]
    proc = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=int(os.environ.get("SAGE_CODEX_TIMEOUT", "900")),
        check=False,
    )
    stdout_path.write_text(proc.stdout, encoding="utf-8")
    stderr_path.write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"codex {agent_name} failed with code {proc.returncode}: {proc.stderr[-1000:]}")
    return extract_json(response_path.read_text(encoding="utf-8"))

