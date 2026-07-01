#!/usr/bin/env python3
"""Run a local Codex-as-VLM visual correction loop over a SAGE-style scene."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from run_selfmade_trellis_scene import (
    OFFICIAL_PROMPTS,
    apply_asset_pose_defaults,
    assemble_scene_blender,
    audit_and_repair_plan,
    clean_plan,
    extract_json,
    generate_asset,
    repair_assets_for_scene,
    render_preview,
    selected_scene_prompt,
    write_json,
    _category_text,
    _clamp,
    _clamp_object_to_room,
    _find_first,
    _normalize_object_dimensions,
    _repair_floor_collisions,
    _round_yaw_90,
)


DEFAULT_BLENDER = os.environ.get("SAGE_BLENDER_BIN", "/data/xy/tools/blender-4.3.2-linux-x64/blender")


def _copy_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(plan))


def _object_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(obj.get("id")): obj for obj in plan.get("objects", [])}


def _asset_exists(asset_dir: Path, obj: dict[str, Any]) -> bool:
    return (asset_dir / f"{obj['id']}.glb").exists()


def _clean_assets_if_requested(args: argparse.Namespace, plan: dict[str, Any], source_dir: Path, output_asset_dir: Path) -> Path:
    if not args.clean_assets:
        return source_dir
    cleaned_dir = output_asset_dir.parent / f"{output_asset_dir.name}_cleaned"
    reports = repair_assets_for_scene(
        plan,
        source_dir,
        cleaned_dir,
        trellis_url=args.trellis_url,
        seed=args.seed,
        timeout=args.asset_timeout,
        steps=args.steps,
        texture_size=args.texture_size,
        decimation_target=args.decimation_target,
        force_clean=args.force_clean_assets,
        regenerate_integrated=args.regenerate_integrated_artifacts,
    )
    write_json(output_asset_dir.parent / "asset_cleanup_report.json", reports)
    return cleaned_dir


def prepare_assets(args: argparse.Namespace, plan: dict[str, Any], output_asset_dir: Path) -> Path:
    if args.reuse_asset_dir:
        source_dir = Path(args.reuse_asset_dir)
        missing = [obj["id"] for obj in plan["objects"] if not _asset_exists(source_dir, obj)]
        if missing:
            raise FileNotFoundError(f"Missing reused assets for: {', '.join(missing)}")
        if args.copy_reused_assets:
            output_asset_dir.mkdir(parents=True, exist_ok=True)
            for obj in plan["objects"]:
                for suffix in (".glb", ".json"):
                    src = source_dir / f"{obj['id']}{suffix}"
                    if src.exists():
                        shutil.copy2(src, output_asset_dir / src.name)
            return _clean_assets_if_requested(args, plan, output_asset_dir, output_asset_dir)
        return _clean_assets_if_requested(args, plan, source_dir, output_asset_dir)

    output_asset_dir.mkdir(parents=True, exist_ok=True)
    for index, obj in enumerate(plan["objects"]):
        asset_path = generate_asset(
            args.trellis_url,
            obj,
            output_asset_dir,
            seed=args.seed + index,
            timeout=args.asset_timeout,
            steps=args.steps,
            texture_size=args.texture_size,
            decimation_target=args.decimation_target,
            force=args.force_assets,
        )
        print(f"generated {obj['id']}: {asset_path}", flush=True)
    return _clean_assets_if_requested(args, plan, output_asset_dir, output_asset_dir)


def make_contact_sheet(image_paths: list[Path], output_path: Path, title: str, thumb: int = 360) -> Path:
    if not image_paths:
        raise ValueError("No images for contact sheet.")
    font = ImageFont.load_default()
    label_h = 34
    cols = 2 if len(image_paths) <= 4 else 3
    rows = math.ceil(len(image_paths) / cols)
    canvas = Image.new("RGB", (cols * thumb, rows * (thumb + label_h) + 44), (245, 241, 231))
    draw = ImageDraw.Draw(canvas)
    draw.text((14, 12), title, fill=(20, 20, 20), font=font)
    for idx, path in enumerate(image_paths):
        row = idx // cols
        col = idx % cols
        x = col * thumb
        y = 44 + row * (thumb + label_h)
        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((thumb - 18, thumb - 18), Image.Resampling.LANCZOS)
            ox = x + (thumb - img.width) // 2
            oy = y + (thumb - img.height) // 2
            canvas.paste(img, (ox, oy))
        label = path.stem
        draw.rectangle([x, y + thumb, x + thumb, y + thumb + label_h], fill=(232, 226, 214))
        draw.text((x + 10, y + thumb + 10), label, fill=(25, 25, 25), font=font)
        draw.rectangle([x, y, x + thumb - 1, y + thumb + label_h - 1], outline=(170, 160, 145))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    return output_path


def run_blender_diagnostics(
    blender_bin: str,
    scene_glb: Path,
    plan_path: Path,
    asset_dir: Path,
    output_dir: Path,
    resolution: int,
    force: bool = False,
    skip_assets: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "render_manifest.json"
    if manifest_path.exists() and not force:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        paths = [Path(path) for path in manifest.get("scene_views", []) + manifest.get("asset_views", [])]
        if paths and all(path.exists() for path in paths):
            return manifest

    script = Path(__file__).with_name("blender_render_sage_diagnostics.py")
    cmd = [
        blender_bin,
        "--background",
        "--python",
        str(script),
        "--",
        "--scene-glb",
        str(scene_glb),
        "--plan",
        str(plan_path),
        "--asset-dir",
        str(asset_dir),
        "--output-dir",
        str(output_dir),
        "--resolution",
        str(resolution),
    ]
    if skip_assets:
        cmd.append("--skip-assets")
    proc = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=int(os.environ.get("SAGE_BLENDER_TIMEOUT", "900")),
        check=False,
    )
    (output_dir / "blender_stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (output_dir / "blender_stderr.txt").write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"Blender diagnostics failed with code {proc.returncode}: {proc.stderr[-1000:]}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def critic_prompt(plan: dict[str, Any], scene_prompt: str, allow_new_objects: bool, pose_audit: str) -> str:
    new_object_rule = (
        "You may add a missing prompt-required object by using a new id in layout_corrections; "
        "when you do, include category and asset_prompt."
        if allow_new_objects
        else "Do not invent new object ids; only correct ids already present in the plan."
    )
    if pose_audit == "all":
        pose_rule = (
            "Pose audit is mandatory: include a layout_correction for every existing object id, even if the value is unchanged. "
            "For every non-symmetric object, also include an asset_correction locking asset_axis_to_z and front_yaw_offset_degrees."
        )
    elif pose_audit == "key":
        pose_rule = (
            "Pose audit is mandatory for key furniture and task objects: include layout_corrections for desk, chair, side table, "
            "bookshelf, filing cabinet, mug, and any tabletop props."
        )
    else:
        pose_rule = "Use layout_corrections only for clear pose, placement, or scale errors."
    return f"""
You are the visual audit module in a SAGE-style scene-generation pipeline.
You receive rendered images of the current 3D scene and per-object GLB previews.

Scene prompt:
{scene_prompt}

Current JSON plan:
{json.dumps(plan, indent=2)}

Coordinate rules:
- Room origin is the southwest floor corner; x east/right, y north/back, z up.
- Object x/y/z are bottom-center positions in meters.
- yaw degrees are about +z; 0 means facing +x/east, 90 means +y/north, 180 means -x/west, 270 means -y/south.
- asset_axis_to_z means which raw GLB bounding-box axis should be treated as vertical before scaling: 0=x, 1=y, 2=z.
- front_yaw_offset_degrees rotates the imported asset around z before placement. Use only 0, 90, 180, or 270.

Task:
Audit whether objects are upright, plausible in size, correctly placed, and task-relevant.
Correct only clear visual/layout errors. Preserve the office task: mug starts on desk, side table is near desk, chair faces desk, bookshelf and filing cabinet are against walls.

Return only JSON with this exact shape:
{{
  "summary": "short diagnosis",
  "asset_corrections": [
    {{
      "id": "object id",
      "asset_axis_to_z": 0,
      "front_yaw_offset_degrees": 0,
      "quality": "ok|bad",
      "reason": "short reason"
    }}
  ],
  "layout_corrections": [
    {{
      "id": "object id",
      "x": 1.0,
      "y": 1.0,
      "z": 0.0,
      "yaw": 0,
      "dimensions": {{"width": 0.5, "length": 0.5, "height": 0.5}},
      "category": "optional category for new objects only",
      "asset_prompt": "optional isolated-object text-to-3D prompt for new objects only",
      "support_id": "optional support object id or null",
      "placement_type": "floor|on_top",
      "reason": "short reason"
    }}
  ]
}}

Rules:
- Include a correction only when it should change or explicitly lock an important value.
- {new_object_rule}
- {pose_rule}
- For cups/mugs, prefer asset_axis_to_z=2 unless the preview clearly shows z is not vertical.
- For side tables/desks/bookshelves/chairs, choose the axis that makes legs/shelves/backrest vertical.
- If an object appears rotated sideways, upside down, mirrored to face a wall, floating, intersecting, or visually inconsistent with its support relation, correct x/y/z/yaw/dimensions and/or front_yaw_offset_degrees.
- Keep mug dimensions around 0.10-0.16m wide and 0.09-0.14m tall.
- Keep side table around 0.45-0.75m wide/long and 0.45-0.65m tall.
- Do not request regeneration unless the asset is unusable; if unusable set quality="bad".
""".strip()


def run_codex_visual_critic(
    plan: dict[str, Any],
    scene_prompt: str,
    image_paths: list[Path],
    output_dir: Path,
    model: str | None,
    allow_new_objects: bool,
    pose_audit: str,
) -> dict[str, Any]:
    prompt = critic_prompt(plan, scene_prompt, allow_new_objects, pose_audit)
    request_path = output_dir / "codex_visual_critic_request.txt"
    response_path = output_dir / "codex_visual_critic_response.txt"
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
        'model_reasoning_effort="low"',
        "--ephemeral",
        "--cd",
        str(Path.cwd()),
        "--sandbox",
        "read-only",
        "--output-last-message",
        str(response_path),
    ]
    if model:
        cmd[2:2] = ["--model", model]
    for image_path in image_paths:
        cmd.extend(["--image", str(image_path)])
    cmd.extend(["--", prompt])
    proc = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=int(os.environ.get("SAGE_CODEX_TIMEOUT", "900")),
        check=False,
    )
    (output_dir / "codex_visual_critic_stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (output_dir / "codex_visual_critic_stderr.txt").write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"codex visual critic failed with code {proc.returncode}: {proc.stderr[-1000:]}")
    return extract_json(response_path.read_text(encoding="utf-8"))


def _bounded_dimensions(obj: dict[str, Any], dims: dict[str, Any]) -> dict[str, float]:
    current = obj["dimensions"]
    proposed = {
        "width": _clamp(float(dims.get("width", current["width"])), 0.04, 2.4),
        "length": _clamp(float(dims.get("length", current["length"])), 0.04, 2.4),
        "height": _clamp(float(dims.get("height", current["height"])), 0.01, 2.4),
    }
    test_obj = _copy_plan(obj)
    test_obj["dimensions"] = proposed
    _normalize_object_dimensions({"objects": [test_obj]})
    return test_obj["dimensions"]


def _normalize_offset(value: Any) -> float:
    try:
        return float((round(float(value) / 90.0) * 90) % 360)
    except (TypeError, ValueError):
        return 0.0


def snap_supported_objects(plan: dict[str, Any]) -> None:
    objects = _object_map(plan)
    for obj in plan.get("objects", []):
        support_id = obj.get("support_id")
        if not support_id:
            continue
        support = objects.get(str(support_id))
        if not support:
            continue
        obj["placement_type"] = "on_top"
        support_dims = support["dimensions"]
        obj_dims = obj["dimensions"]
        max_dx = max(0.0, float(support_dims["width"]) / 2.0 - float(obj_dims["width"]) / 2.0 - 0.055)
        max_dy = max(0.0, float(support_dims["length"]) / 2.0 - float(obj_dims["length"]) / 2.0 - 0.055)
        obj["x"] = float(support["x"]) + _clamp(float(obj.get("x", support["x"])) - float(support["x"]), -max_dx, max_dx)
        obj["y"] = float(support["y"]) + _clamp(float(obj.get("y", support["y"])) - float(support["y"]), -max_dy, max_dy)
        if "bookshelf" in _category_text(support) or "book shelf" in _category_text(support):
            low = float(support.get("z", 0.0)) + 0.18
            high = float(support.get("z", 0.0)) + float(support_dims["height"]) - float(obj_dims["height"]) - 0.05
            obj["z"] = _clamp(float(obj.get("z", low)), low, max(low, high))
        else:
            obj["z"] = float(support.get("z", 0.0)) + float(support_dims["height"]) + 0.012


def _clean_new_object_id(raw_id: Any, existing: dict[str, dict[str, Any]]) -> str:
    base = re.sub(r"[^a-zA-Z0-9_]+", "_", str(raw_id or "new_object")).strip("_").lower() or "new_object"
    object_id = base
    index = 1
    while object_id in existing:
        index += 1
        object_id = f"{base}_{index}"
    return object_id


def _new_object_from_correction(correction: dict[str, Any], existing: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if not isinstance(correction.get("dimensions"), dict):
        return None
    object_id = _clean_new_object_id(correction.get("id"), existing)
    category = str(correction.get("category") or object_id.replace("_", " "))
    dims = {
        "width": _clamp(float(correction["dimensions"].get("width", 0.2)), 0.04, 1.0),
        "length": _clamp(float(correction["dimensions"].get("length", 0.1)), 0.04, 1.0),
        "height": _clamp(float(correction["dimensions"].get("height", 0.08)), 0.01, 1.0),
    }
    asset_prompt = str(correction.get("asset_prompt") or f"single {category}, isolated object, no room, no base, transparent background")
    return {
        "id": object_id,
        "category": category,
        "asset_prompt": asset_prompt,
        "x": float(correction.get("x", 1.0)),
        "y": float(correction.get("y", 1.0)),
        "z": max(float(correction.get("z", 0.0)), 0.0),
        "yaw": _round_yaw_90(float(correction.get("yaw", 0.0))),
        "dimensions": dims,
        "support_id": str(correction["support_id"]) if correction.get("support_id") else None,
        "placement_type": correction.get("placement_type") if correction.get("placement_type") in {"floor", "on_top"} else "floor",
    }


def apply_visual_critic(plan: dict[str, Any], critic: dict[str, Any], scene_prompt: str, allow_new_objects: bool) -> dict[str, Any]:
    updated = _copy_plan(plan)
    objects = _object_map(updated)
    applied: list[str] = []

    for correction in critic.get("asset_corrections", []) or []:
        obj = objects.get(str(correction.get("id")))
        if not obj:
            continue
        if "asset_axis_to_z" in correction:
            try:
                axis = int(correction["asset_axis_to_z"])
                if axis in (0, 1, 2):
                    obj["asset_axis_to_z"] = axis
                    applied.append(f"{obj['id']}: asset_axis_to_z={axis}")
            except (TypeError, ValueError):
                pass
        if "front_yaw_offset_degrees" in correction:
            offset = _normalize_offset(correction["front_yaw_offset_degrees"])
            obj["front_yaw_offset_degrees"] = offset
            applied.append(f"{obj['id']}: front_yaw_offset_degrees={offset:g}")
        if correction.get("quality") == "bad":
            obj["visual_quality"] = "bad"
            applied.append(f"{obj['id']}: marked bad asset")

    for correction in critic.get("layout_corrections", []) or []:
        obj = objects.get(str(correction.get("id")))
        if not obj:
            if allow_new_objects:
                new_obj = _new_object_from_correction(correction, objects)
                if new_obj:
                    updated.setdefault("objects", []).append(new_obj)
                    objects[new_obj["id"]] = new_obj
                    applied.append(f"{new_obj['id']}: added new object")
            continue
        for key in ("x", "y", "z"):
            if key in correction and correction[key] is not None:
                obj[key] = float(correction[key])
        if "yaw" in correction and correction["yaw"] is not None:
            obj["yaw"] = _round_yaw_90(float(correction["yaw"]))
        if isinstance(correction.get("dimensions"), dict):
            obj["dimensions"] = _bounded_dimensions(obj, correction["dimensions"])
        if "support_id" in correction:
            support_id = correction.get("support_id")
            obj["support_id"] = str(support_id) if support_id else None
        if "placement_type" in correction and correction["placement_type"] in {"floor", "on_top"}:
            obj["placement_type"] = correction["placement_type"]
        applied.append(f"{obj['id']}: layout correction")

    _normalize_object_dimensions(updated)
    snap_supported_objects(updated)

    # Keep the task's support relation stable if the critic omits it.
    desk = _find_first(updated, ["desk"])
    mug = _find_first(updated, ["mug", "coffee cup"])
    folder = _find_first(updated, ["folder", "document"])
    if desk and mug and not mug.get("support_id"):
        mug["support_id"] = desk["id"]
    if desk and folder and not folder.get("support_id"):
        folder["support_id"] = desk["id"]
    snap_supported_objects(updated)

    for obj in updated.get("objects", []):
        if str(obj.get("placement_type", "floor")) == "floor":
            obj["z"] = 0.0
        obj["yaw"] = _round_yaw_90(float(obj.get("yaw", 0.0)))
        _clamp_object_to_room(obj, updated["room"])
    applied.extend(apply_asset_pose_defaults(updated))
    applied.extend(_repair_floor_collisions(updated))
    updated["_visual_critic"] = {
        "enabled": True,
        "summary": critic.get("summary", ""),
        "applied": applied,
        "raw": critic,
    }
    return updated


def load_or_create_plan(args: argparse.Namespace, output_dir: Path) -> tuple[dict[str, Any], str]:
    scene_prompt = selected_scene_prompt(args)
    (output_dir / "selected_prompt.txt").write_text(scene_prompt + "\n", encoding="utf-8")
    if args.plan_file:
        plan = extract_json(Path(args.plan_file).read_text(encoding="utf-8"))
        plan["_planner"] = plan.get("_planner", "codex_exec_plan_file")
    else:
        raise ValueError("This closed-loop runner currently requires --plan-file so it can focus on visual audit.")
    plan = clean_plan(plan, max_objects=args.max_objects)
    if args.layout_audit:
        plan = audit_and_repair_plan(plan, scene_prompt)
    else:
        apply_asset_pose_defaults(plan)
    return plan, scene_prompt


def run_iteration(
    args: argparse.Namespace,
    plan: dict[str, Any],
    scene_prompt: str,
    asset_dir: Path,
    output_dir: Path,
    iteration: int,
) -> dict[str, Any]:
    iter_dir = output_dir / f"iteration_{iteration:02d}"
    iter_dir.mkdir(parents=True, exist_ok=True)
    plan_path = iter_dir / "scene_plan.json"
    write_json(plan_path, plan)

    scene_glb = iter_dir / "scene_selfmade_trellis.glb"
    assemble_scene_blender(args.blender_bin, plan_path, asset_dir, scene_glb)
    render_preview(plan, iter_dir / "preview_topdown.png")

    render_dir = iter_dir / "visual_diagnostics"
    manifest = run_blender_diagnostics(
        args.blender_bin,
        scene_glb,
        plan_path,
        asset_dir,
        render_dir,
        args.render_resolution,
        force=args.force_render,
        skip_assets=args.skip_asset_renders,
    )
    scene_sheet = make_contact_sheet([Path(p) for p in manifest.get("scene_views", [])], render_dir / "scene_contact_sheet.png", "Scene diagnostics")
    image_paths = [scene_sheet]
    asset_views = [Path(p) for p in manifest.get("asset_views", [])]
    if asset_views:
        image_paths.append(make_contact_sheet(asset_views, render_dir / "asset_contact_sheet.png", "Asset diagnostics"))
    critic = run_codex_visual_critic(
        plan,
        scene_prompt,
        image_paths,
        iter_dir,
        args.model,
        args.allow_new_objects,
        args.pose_audit,
    )
    write_json(iter_dir / "codex_visual_critic.json", critic)
    return apply_visual_critic(plan, critic, scene_prompt, args.allow_new_objects)


def ensure_assets_for_plan(args: argparse.Namespace, plan: dict[str, Any], asset_dir: Path) -> None:
    missing = [obj for obj in plan.get("objects", []) if not _asset_exists(asset_dir, obj)]
    if not missing:
        return
    if args.reuse_asset_dir and not args.copy_reused_assets and not args.clean_assets:
        raise FileNotFoundError(
            "Visual critic added objects but --reuse-asset-dir points at an immutable source. "
            "Rerun with --copy-reused-assets so new Trellis2 assets are generated in the output dir."
        )
    generation_dir = asset_dir if not args.clean_assets else asset_dir.parent / "_visual_critic_new_raw_assets"
    for index, obj in enumerate(missing):
        asset_path = generate_asset(
            args.trellis_url,
            obj,
            generation_dir,
            seed=args.seed + 1000 + index,
            timeout=args.asset_timeout,
            steps=args.steps,
            texture_size=args.texture_size,
            decimation_target=args.decimation_target,
            force=args.force_assets,
        )
        print(f"generated missing visual-critic asset {obj['id']}: {asset_path}", flush=True)
    if args.clean_assets:
        reports = repair_assets_for_scene(
            {"objects": missing},
            generation_dir,
            asset_dir,
            trellis_url=args.trellis_url,
            seed=args.seed + 1000,
            timeout=args.asset_timeout,
            steps=args.steps,
            texture_size=args.texture_size,
            decimation_target=args.decimation_target,
            force_clean=True,
            regenerate_integrated=args.regenerate_integrated_artifacts,
        )
        write_json(asset_dir.parent / "asset_cleanup_report_new_objects.json", reports)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a Codex visual closed loop over an existing SAGE-style scene plan.")
    parser.add_argument("--prompt-preset", default="office_task", choices=sorted(OFFICIAL_PROMPTS))
    parser.add_argument("--prompt")
    parser.add_argument("--prompt-file")
    parser.add_argument("--plan-file", required=True)
    parser.add_argument("--model")
    parser.add_argument("--output-dir", default="/data/xy/SAGE_repro/selfmade_trellis_scene_codexloop")
    parser.add_argument("--reuse-asset-dir")
    parser.add_argument("--copy-reused-assets", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--trellis-url", default="http://127.0.0.1:8082")
    parser.add_argument("--seed", type=int, default=700)
    parser.add_argument("--asset-timeout", type=float, default=900.0)
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--texture-size", type=int, default=512)
    parser.add_argument("--decimation-target", type=int, default=50000)
    parser.add_argument("--force-assets", action="store_true")
    parser.add_argument("--clean-assets", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--force-clean-assets", action="store_true")
    parser.add_argument("--regenerate-integrated-artifacts", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--max-objects", type=int, default=7)
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--allow-new-objects", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--pose-audit", choices=("normal", "key", "all"), default="normal")
    parser.add_argument("--layout-audit", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--blender-bin", default=DEFAULT_BLENDER)
    parser.add_argument("--render-resolution", type=int, default=820)
    parser.add_argument("--force-render", action="store_true")
    parser.add_argument("--skip-asset-renders", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not Path(args.blender_bin).exists():
        raise FileNotFoundError(f"Blender binary not found: {args.blender_bin}")

    plan, scene_prompt = load_or_create_plan(args, output_dir)
    write_json(output_dir / "scene_plan_initial.json", plan)
    asset_dir = prepare_assets(args, plan, output_dir / "assets_trellis2")

    current = plan
    for iteration in range(max(0, int(args.iterations))):
        current = run_iteration(args, current, scene_prompt, asset_dir, output_dir, iteration)
        write_json(output_dir / f"scene_plan_after_iteration_{iteration:02d}.json", current)
        ensure_assets_for_plan(args, current, asset_dir)

    final_plan = output_dir / "scene_plan_final.json"
    write_json(final_plan, current)
    final_glb = output_dir / "scene_selfmade_trellis_codexloop.glb"
    assemble_scene_blender(args.blender_bin, final_plan, asset_dir, final_glb)
    render_preview(current, output_dir / "preview_topdown_final.png")
    summary = {
        "prompt": str(output_dir / "selected_prompt.txt"),
        "initial_plan": str(output_dir / "scene_plan_initial.json"),
        "final_plan": str(final_plan),
        "assets_dir": str(asset_dir),
        "final_scene_glb": str(final_glb),
        "final_preview": str(output_dir / "preview_topdown_final.png"),
        "iterations": int(args.iterations),
    }
    write_json(output_dir / "run_summary.json", summary)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr, flush=True)
        raise
