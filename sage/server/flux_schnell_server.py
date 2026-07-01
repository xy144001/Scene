#!/usr/bin/env python3
"""Small async Flux.1-schnell HTTP server compatible with SAGE's FluxClient."""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class JobStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}

    def create(self) -> str:
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = {"status": "processing", "created_at": time.time()}
        return job_id

    def update(self, job_id: str, **payload: Any) -> None:
        with self._lock:
            self._jobs[job_id].update(payload)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None


class FluxRuntime:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self._lock = threading.Lock()
        self._pipe = None
        self._torch = None

    def _pipeline(self):
        if self._pipe is not None:
            return self._pipe, self._torch
        with self._lock:
            if self._pipe is not None:
                return self._pipe, self._torch
            import torch
            from diffusers import FluxPipeline

            dtype = getattr(torch, self.args.dtype)
            print(f"[flux] loading pipeline from {self.args.model_path}", flush=True)
            pipe = FluxPipeline.from_pretrained(
                self.args.model_path,
                torch_dtype=dtype,
                local_files_only=True,
            )
            if self.args.cpu_offload and hasattr(pipe, "enable_model_cpu_offload"):
                pipe.enable_model_cpu_offload()
            else:
                pipe = pipe.to(self.args.device)
            pipe.set_progress_bar_config(disable=True)
            self._pipe = pipe
            self._torch = torch
            print(f"[flux] ready on {self.args.device}", flush=True)
        return self._pipe, self._torch

    def generate(self, payload: dict[str, Any], job_id: str) -> Path:
        prompt = str(payload.get("prompt") or payload.get("input_text") or "").strip()
        if not prompt:
            raise ValueError("Missing prompt")
        width = int(payload.get("width", self.args.width))
        height = int(payload.get("height", self.args.height))
        steps = int(payload.get("steps", payload.get("num_inference_steps", self.args.steps)))
        seed = payload.get("seed")
        guidance_scale = float(payload.get("guidance_scale", self.args.guidance_scale))

        pipe, torch = self._pipeline()
        generator = None
        if seed is not None:
            generator = torch.Generator(device=self.args.device).manual_seed(int(seed))

        image = pipe(
            prompt=prompt,
            width=width,
            height=height,
            num_inference_steps=steps,
            guidance_scale=guidance_scale,
            max_sequence_length=int(payload.get("max_sequence_length", self.args.max_sequence_length)),
            generator=generator,
        ).images[0]

        output_dir = Path(self.args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        image_path = output_dir / f"{job_id}.png"
        image.save(image_path)
        (output_dir / f"{job_id}.json").write_text(
            json.dumps(
                {
                    "job_id": job_id,
                    "prompt": prompt,
                    "seed": seed,
                    "width": width,
                    "height": height,
                    "steps": steps,
                    "guidance_scale": guidance_scale,
                    "image_path": str(image_path),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return image_path


def json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload).encode("utf-8")


def build_handler(jobs: JobStore, runtime: FluxRuntime):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SAGEFluxSchnell/0.1"

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path, content_type: str) -> None:
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path in {"/", "/health"}:
                self._send_json(
                    200,
                    {
                        "status": "healthy",
                        "service": "flux-schnell",
                        "gpu_available": True,
                        "model_path": runtime.args.model_path,
                    },
                )
                return
            if parsed.path == "/api/v1/models":
                self._send_json(200, {"data": [{"id": "FLUX.1-schnell", "path": runtime.args.model_path}]})
                return
            if parsed.path.startswith("/job/"):
                job_id = parsed.path.rsplit("/", 1)[-1]
                job = jobs.get(job_id)
                if job is None:
                    self._send_json(404, {"error": "job not found"})
                    return
                if job.get("status") == "done":
                    self._send_file(Path(str(job["image_path"])), "image/png")
                    return
                if job.get("status") == "failed":
                    self._send_json(
                        500,
                        {
                            "error": job.get("error", "unknown error"),
                            "error_log": job.get("error_log"),
                        },
                    )
                    return
                self._send_json(202, {"status": job.get("status", "processing")})
                return
            self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/generate":
                self._send_json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                job_id = jobs.create()

                def worker() -> None:
                    try:
                        image_path = runtime.generate(payload, job_id)
                        jobs.update(job_id, status="done", image_path=str(image_path), completed_at=time.time())
                    except Exception as exc:  # pragma: no cover - runtime failures are reported over HTTP
                        trace = traceback.format_exc()
                        error_log = Path(runtime.args.output_dir) / f"{job_id}.error.txt"
                        error_log.parent.mkdir(parents=True, exist_ok=True)
                        error_log.write_text(trace, encoding="utf-8")
                        jobs.update(
                            job_id,
                            status="failed",
                            error=str(exc),
                            error_log=str(error_log),
                            completed_at=time.time(),
                        )
                        print(f"[flux] job {job_id} failed:\n{trace}", flush=True)

                threading.Thread(target=worker, daemon=True).start()
                self._send_json(202, {"job_id": job_id, "status": "processing", "message": "Processing started"})
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"[flux] {self.address_string()} {fmt % args}", flush=True)

    return Handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve local Flux.1-schnell behind SAGE's async image API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8083)
    parser.add_argument("--model-path", default="/data/xy/pat3d_stage1_data/models/text_to_image__primary")
    parser.add_argument("--output-dir", default="/data/xy/SAGE_repro/flux_images")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--dtype", default="bfloat16", choices=["float16", "bfloat16", "float32"])
    parser.add_argument("--cpu-offload", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--width", type=int, default=768)
    parser.add_argument("--height", type=int, default=768)
    parser.add_argument("--steps", type=int, default=4)
    parser.add_argument("--guidance-scale", type=float, default=0.0)
    parser.add_argument("--max-sequence-length", type=int, default=256)
    return parser.parse_args()


def main() -> None:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    args = parse_args()
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    jobs = JobStore()
    runtime = FluxRuntime(args)
    httpd = ThreadingHTTPServer((args.host, args.port), build_handler(jobs, runtime))
    print(f"[flux] serving on http://{args.host}:{args.port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
