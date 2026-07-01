#!/usr/bin/env python3
"""Daemonize a resumable FLUX.2-klein-9B Hugging Face download under /data/xy."""

from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path


REPO_ID = "black-forest-labs/FLUX.2-klein-9B"
MODEL_DIR = Path("/data/xy/models/FLUX.2-klein-9B")
LOG_PATH = MODEL_DIR / "download.log"
PID_PATH = MODEL_DIR / "download.pid"
ALLOW_PATTERNS = [
    "model_index.json",
    "scheduler/*",
    "tokenizer/*",
    "text_encoder/*",
    "transformer/*",
    "vae/*",
    "README.md",
    "LICENSE.md",
    ".gitattributes",
]


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _existing_pid() -> int | None:
    if not PID_PATH.exists():
        return None
    try:
        pid = int(PID_PATH.read_text(encoding="utf-8").strip())
    except Exception:
        return None
    return pid if _pid_is_running(pid) else None


def _download() -> None:
    os.environ.setdefault("HF_HOME", "/data/xy/hf")
    os.environ.setdefault("HF_HUB_CACHE", "/data/xy/hf/hub")
    os.environ.setdefault("HF_XET_CACHE", "/data/xy/hf/xet")
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")

    from huggingface_hub import snapshot_download

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[{time.strftime('%F %T')}] starting download: {REPO_ID}", flush=True)
    path = snapshot_download(
        repo_id=REPO_ID,
        local_dir=str(MODEL_DIR),
        token=True,
        max_workers=6,
        allow_patterns=ALLOW_PATTERNS,
    )
    print(f"[{time.strftime('%F %T')}] downloaded_to {path}", flush=True)


def _daemonize() -> int:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    pid = os.fork()
    if pid > 0:
        return pid
    os.setsid()
    pid = os.fork()
    if pid > 0:
        os._exit(0)

    with LOG_PATH.open("a", encoding="utf-8") as log:
        os.dup2(log.fileno(), sys.stdout.fileno())
        os.dup2(log.fileno(), sys.stderr.fileno())
        sys.stdin.close()
        PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
        try:
            _download()
        except Exception:
            traceback.print_exc()
            raise
        finally:
            try:
                PID_PATH.unlink()
            except FileNotFoundError:
                pass
    os._exit(0)


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "start"
    if command == "status":
        pid = _existing_pid()
        print(f"running={bool(pid)} pid={pid or ''} log={LOG_PATH}")
        return
    if command != "start":
        raise SystemExit(f"unknown command: {command}")

    pid = _existing_pid()
    if pid:
        print(f"already_running pid={pid} log={LOG_PATH}")
        return
    parent_pid = _daemonize()
    print(f"started pid={parent_pid} log={LOG_PATH} model_dir={MODEL_DIR}")


if __name__ == "__main__":
    main()
