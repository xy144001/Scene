#!/usr/bin/env python3
"""Generate one SAGE asset through an external Articraft checkout.

This wrapper intentionally keeps Articraft outside the main TreeSAGE process. It
executes the external generator in a per-object work directory, then tries to
materialize a single GLB that the SAGE assembler can consume.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np
import trimesh


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def object_prompt(obj: dict[str, Any]) -> str:
    category = str(obj.get("category") or obj.get("id") or "object")
    description = str(obj.get("description") or "").strip()
    asset_prompt = str(obj.get("asset_prompt") or "").strip()
    dims = obj.get("dimensions") if isinstance(obj.get("dimensions"), dict) else {}
    width = float(dims.get("width", 1.0) or 1.0)
    length = float(dims.get("length", 1.0) or 1.0)
    height = float(dims.get("height", 1.0) or 1.0)
    support = str(obj.get("placement_type") or "floor")
    prompt = (
        f"Create a realistic {category} as a clean structured 3D asset. "
        f"Target proportions are width {width:.2f}m, depth {length:.2f}m, height {height:.2f}m. "
        "Use a strict raw local coordinate frame: Z is vertical/up, X is visual width, Y is depth, "
        "and +Y is the semantic front side when the object has a front. "
        "Keep a stable upright coordinate frame, a clear semantic front when the object has one, "
        "no room, no floor, no wall, no duplicate objects, and no floating disconnected fragments. "
    )
    if "table" in category.lower() or "desk" in category.lower():
        prompt += (
            "The tabletop must be a broad horizontal slab near the top, parallel to the XY plane, "
            "with legs or supports below it; do not create a vertical tabletop panel. "
        )
    if support == "attached_to_wall" or "wall" in support:
        prompt += "This is a wall-mounted object: make it visually flat with a very thin Y depth axis and a broad XZ face. "
    if asset_prompt:
        prompt += f"Asset-specific requirements: {asset_prompt}. "
    if description:
        prompt += f"Scene-specific visual description: {description}"
    return prompt.strip()


def run_command(cmd: list[str], cwd: Path, timeout: float, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def uv_command() -> list[str]:
    uv_path = shutil.which("uv")
    if uv_path:
        return [uv_path]
    return [sys.executable, "-m", "uv"]


def default_articraft_python() -> Path | None:
    candidate = Path("/data/xy/tools/blender-4.3.2-linux-x64/4.3/python/bin/python3.11")
    return candidate if candidate.exists() else None


def find_candidate_assets(work_dir: Path) -> list[Path]:
    suffixes = {".glb", ".gltf", ".obj", ".stl", ".ply"}
    ignored_parts = {"node_modules", ".git", ".venv", "__pycache__"}
    candidates: list[Path] = []
    for path in work_dir.rglob("*"):
        if any(part in ignored_parts for part in path.parts):
            continue
        if path.is_file() and path.suffix.lower() in suffixes:
            candidates.append(path)
    return sorted(candidates, key=lambda p: (p.stat().st_size if p.exists() else 0), reverse=True)


def snapshot_record_dirs(repo: Path) -> dict[str, float]:
    records_root = repo / "data" / "records"
    if not records_root.exists():
        return {}
    snapshot: dict[str, float] = {}
    for path in records_root.iterdir():
        if path.is_dir():
            snapshot[path.name] = path.stat().st_mtime
    return snapshot


def parse_record_dir(text: str, repo: Path) -> Path | None:
    patterns = [
        r"record_dir=([^\s]+)",
        r"record_id=([A-Za-z0-9_.:-]+)",
        r"generated\s+record_id=([A-Za-z0-9_.:-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        value = match.group(1).strip()
        path = Path(value)
        if path.exists() and path.is_dir():
            return path.resolve()
        candidate = repo / "data" / "records" / value
        if candidate.exists() and candidate.is_dir():
            return candidate.resolve()
    return None


def detect_new_record_dir(repo: Path, before: dict[str, float], stdout: str, stderr: str) -> Path | None:
    parsed = parse_record_dir(stdout + "\n" + stderr, repo)
    if parsed is not None:
        return parsed
    records_root = repo / "data" / "records"
    if not records_root.exists():
        return None
    candidates: list[Path] = []
    for path in records_root.iterdir():
        if not path.is_dir():
            continue
        previous_mtime = before.get(path.name)
        if previous_mtime is None or path.stat().st_mtime > previous_mtime:
            candidates.append(path)
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime).resolve()


def artifact_search_roots(repo: Path, record_dir: Path | None, work_dir: Path) -> list[Path]:
    roots = [work_dir]
    if record_dir is not None:
        record_id = record_dir.name
        roots.extend(
            [
                repo / "data" / "cache" / "record_materialization" / record_id / "assets" / "glb",
                repo / "data" / "cache" / "record_materialization" / record_id / "assets" / "meshes",
                repo / "data" / "cache" / "record_materialization" / record_id / "assets",
                repo / "data" / "cache" / "record_materialization" / record_id,
                record_dir / "assets" / "glb",
                record_dir / "assets" / "meshes",
                record_dir / "assets",
                record_dir,
            ]
        )
    seen: set[Path] = set()
    unique: list[Path] = []
    for root in roots:
        resolved = root.resolve()
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def find_candidate_assets_in_roots(roots: list[Path]) -> list[Path]:
    candidates: list[Path] = []
    for root in roots:
        if root.is_file():
            if root.suffix.lower() in {".glb", ".gltf", ".obj", ".stl", ".ply"}:
                candidates.append(root)
            continue
        candidates.extend(find_candidate_assets(root))
    dedup: dict[Path, Path] = {path.resolve(): path for path in candidates}
    return sorted(dedup.values(), key=lambda p: (p.stat().st_size if p.exists() else 0), reverse=True)


def materialize_glb(candidate: Path, output_path: Path) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if candidate.suffix.lower() == ".glb":
        shutil.copy2(candidate, output_path)
        return {"source_asset": str(candidate), "conversion": "copied_glb"}
    loaded = trimesh.load(candidate, force="scene")
    if not isinstance(loaded, trimesh.Scene):
        loaded = trimesh.Scene(loaded)
    loaded.export(output_path)
    return {"source_asset": str(candidate), "conversion": f"{candidate.suffix.lower()}_to_glb"}


def _parse_floats(text: str | None, expected: int, default: list[float]) -> list[float]:
    if not text:
        return list(default)
    values = [float(part) for part in text.split()]
    return values if len(values) == expected else list(default)


def _origin_transform(origin: ET.Element | None) -> np.ndarray:
    xyz = _parse_floats(origin.get("xyz") if origin is not None else None, 3, [0.0, 0.0, 0.0])
    rpy = _parse_floats(origin.get("rpy") if origin is not None else None, 3, [0.0, 0.0, 0.0])
    transform = trimesh.transformations.euler_matrix(rpy[0], rpy[1], rpy[2], axes="sxyz")
    transform[:3, 3] = xyz
    return transform


def _visual_rgba(visual: ET.Element) -> tuple[list[int], list[float]]:
    color = visual.find("./material/color")
    rgba = _parse_floats(color.get("rgba") if color is not None else None, 4, [0.72, 0.72, 0.72, 1.0])
    rgba_int = [max(0, min(255, int(round(value * 255.0)))) for value in rgba]
    return rgba_int, [float(value) for value in rgba]


def _mesh_from_urdf_geometry(geometry: ET.Element, urdf_path: Path) -> trimesh.Trimesh | None:
    box = geometry.find("box")
    if box is not None:
        return trimesh.creation.box(extents=_parse_floats(box.get("size"), 3, [1.0, 1.0, 1.0]))
    cylinder = geometry.find("cylinder")
    if cylinder is not None:
        return trimesh.creation.cylinder(
            radius=float(cylinder.get("radius") or 0.5),
            height=float(cylinder.get("length") or 1.0),
            sections=32,
        )
    sphere = geometry.find("sphere")
    if sphere is not None:
        return trimesh.creation.icosphere(radius=float(sphere.get("radius") or 0.5), subdivisions=3)
    mesh_node = geometry.find("mesh")
    if mesh_node is not None and mesh_node.get("filename"):
        mesh_path = Path(str(mesh_node.get("filename")))
        if not mesh_path.is_absolute():
            mesh_path = (urdf_path.parent / mesh_path).resolve()
        loaded = trimesh.load(mesh_path, force="mesh")
        if isinstance(loaded, trimesh.Trimesh):
            loaded.apply_scale(_parse_floats(mesh_node.get("scale"), 3, [1.0, 1.0, 1.0]))
            return loaded
    return None


def materialize_urdf_visuals_to_glb(urdf_path: Path, output_path: Path) -> dict[str, Any]:
    root = ET.fromstring(urdf_path.read_text(encoding="utf-8"))
    scene = trimesh.Scene()
    visual_count = 0
    for link in root.findall("link"):
        for visual in link.findall("visual"):
            geometry = visual.find("geometry")
            if geometry is None:
                continue
            mesh = _mesh_from_urdf_geometry(geometry, urdf_path)
            if mesh is None:
                continue
            rgba_int, rgba_float = _visual_rgba(visual)
            mesh.visual = trimesh.visual.TextureVisuals(
                material=trimesh.visual.material.PBRMaterial(
                    baseColorFactor=rgba_float,
                    roughnessFactor=0.55,
                    metallicFactor=0.0,
                )
            )
            name = visual.get("name") or f"{link.get('name', 'link')}_visual_{visual_count}"
            scene.add_geometry(mesh, node_name=name, geom_name=name, transform=_origin_transform(visual.find("origin")))
            visual_count += 1
    if visual_count <= 0:
        raise FileNotFoundError(f"No supported visual geometry in URDF: {urdf_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    scene.export(output_path)
    return {
        "source_asset": str(urdf_path),
        "conversion": "urdf_visual_primitives_to_glb",
        "visual_count": visual_count,
    }


def candidate_urdf_paths(repo: Path, record_dir: Path | None) -> list[Path]:
    if record_dir is None:
        return []
    record_id = record_dir.name
    candidates = [
        repo / "data" / "cache" / "record_materialization" / record_id / "model.urdf",
        record_dir / "model.urdf",
    ]
    return [path.resolve() for path in candidates if path.exists()]


def run_articraft_generate(args: argparse.Namespace, obj: dict[str, Any], work_dir: Path) -> dict[str, Any]:
    repo = args.articraft_repo
    prompt = args.prompt_override or object_prompt(obj)
    reference_image = args.reference_image
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "sage_object.json").write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    (work_dir / "prompt.txt").write_text(prompt + "\n", encoding="utf-8")

    before_records = snapshot_record_dirs(repo)
    if args.articraft_command:
        command = [part.format(prompt=prompt, work_dir=str(work_dir)) for part in args.articraft_command]
    else:
        python_args: list[str] = []
        articraft_python = args.articraft_python or default_articraft_python()
        if articraft_python is not None:
            python_args = ["--python", str(articraft_python), "--no-python-downloads"]
        command = [
            *uv_command(),
            "run",
            *python_args,
            "articraft",
            "generate",
            "--provider",
            str(args.articraft_provider),
            "--model",
            str(args.articraft_model),
        ]
        if reference_image is not None:
            command.extend(["--image", str(reference_image)])
            shutil.copy2(reference_image, work_dir / f"reference_image{reference_image.suffix.lower()}")
            (work_dir / "reference_image_path.txt").write_text(str(reference_image) + "\n", encoding="utf-8")
        command.extend(["--max-cost-usd", str(args.max_cost_usd), prompt])
    env = os.environ.copy()
    env.setdefault("ARTICRAFT_WORKDIR", str(work_dir))
    env.setdefault("ARTICRAFT_CODEX_MODEL", str(args.articraft_model))
    env.setdefault("UV_DEFAULT_INDEX", "https://pypi.tuna.tsinghua.edu.cn/simple")
    proc = run_command(command, repo, args.timeout, env=env)
    (work_dir / "articraft_stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (work_dir / "articraft_stderr.txt").write_text(proc.stderr, encoding="utf-8")
    record_dir = detect_new_record_dir(repo, before_records, proc.stdout, proc.stderr)
    return {
        "command": command,
        "returncode": int(proc.returncode),
        "stdout_tail": proc.stdout.splitlines()[-40:],
        "stderr_tail": proc.stderr.splitlines()[-40:],
        "prompt": prompt,
        "reference_image": str(reference_image) if reference_image is not None else None,
        "record_dir": str(record_dir) if record_dir is not None else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run external Articraft generation for one SAGE object.")
    parser.add_argument("--object-json", required=True, type=Path)
    parser.add_argument("--output-glb", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--articraft-repo", type=Path, default=Path("external/articraft"))
    parser.add_argument("--articraft-python", type=Path)
    parser.add_argument("--articraft-provider", default="codex-cli")
    parser.add_argument("--articraft-model", default="gpt-5.4")
    parser.add_argument("--articraft-command", nargs="+")
    parser.add_argument("--prompt-override")
    parser.add_argument("--reference-image", type=Path)
    parser.add_argument("--max-cost-usd", type=float, default=0.75)
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args()

    obj = read_json(args.object_json)
    report: dict[str, Any] = {
        "schema": "tree_sage_articraft_asset_worker_v1",
        "object_id": obj.get("id"),
        "articraft_repo": str(args.articraft_repo),
        "work_dir": str(args.work_dir),
        "output_glb": str(args.output_glb),
        "ok": False,
    }
    try:
        if not args.articraft_repo.exists():
            raise FileNotFoundError(f"Articraft repo not found: {args.articraft_repo}")
        run_report = run_articraft_generate(args, obj, args.work_dir)
        report["run"] = run_report
        if int(run_report.get("returncode", 1)) != 0:
            raise RuntimeError(f"Articraft command failed with code {run_report.get('returncode')}")
        record_dir = Path(str(run_report["record_dir"])) if run_report.get("record_dir") else None
        search_roots = artifact_search_roots(args.articraft_repo, record_dir, args.work_dir)
        report["artifact_search_roots"] = [str(path) for path in search_roots]
        candidates = find_candidate_assets_in_roots(search_roots)
        report["candidate_assets"] = [str(path) for path in candidates[:20]]
        packaged_candidates = [path for path in candidates if path.suffix.lower() in {".glb", ".gltf"}]
        if packaged_candidates:
            conversion = materialize_glb(packaged_candidates[0], args.output_glb)
        else:
            urdf_paths = candidate_urdf_paths(args.articraft_repo, record_dir)
            report["candidate_urdfs"] = [str(path) for path in urdf_paths]
            if urdf_paths:
                conversion = materialize_urdf_visuals_to_glb(urdf_paths[0], args.output_glb)
            elif candidates:
                conversion = materialize_glb(candidates[0], args.output_glb)
            else:
                raise FileNotFoundError("Articraft run produced no mesh/GLB/URDF candidate")
        report.update(conversion)
        report["ok"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    write_json(args.report, report)
    print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)
    sys.exit(0 if report.get("ok") else 2)


if __name__ == "__main__":
    main()
