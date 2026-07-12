from __future__ import annotations

from pathlib import Path
from typing import Any

from .asset_style import apply_asset_style_to_scene_graph, build_asset_style_spec, build_image2_generation_plan
from .assets import ensure_assets_and_scene
from .brief import build_text_scene_brief
from .constraints import synthesize_constraints
from .critic import select_best_candidate
from .io import read_optional_json, write_json
from .layout import generate_layout_candidates
from .preview import write_topdown_svg
from .scene_graph import build_text_scene_graph
from .texture_search import build_room_texture_search_plan, materialize_room_texture_images


def _load_human_constraints(paths: list[Path] | None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in paths or []:
        raw = read_optional_json(path)
        if isinstance(raw, list):
            items.extend(item for item in raw if isinstance(item, dict))
        elif isinstance(raw, dict):
            if isinstance(raw.get("constraints"), list):
                items.extend(item for item in raw["constraints"] if isinstance(item, dict))
            else:
                items.append(raw)
    return items


def run_text_scene_pipeline(args: Any) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    prompt = str(args.prompt or "")
    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError("text-to-scene requires --prompt or --prompt-file")

    (output_dir / "selected_prompt.txt").write_text(prompt + "\n", encoding="utf-8")

    brief = build_text_scene_brief(
        prompt,
        room_type_override=args.room_type,
        style_override=args.style,
    )
    write_json(output_dir / "text_scene_brief.json", brief)

    asset_style_spec = None
    image2_generation_plan = None
    texture_report = None
    scene_graph = build_text_scene_graph(brief, asset_strategy=str(args.asset_strategy))
    if bool(getattr(args, "asset_style_consistency", True)):
        asset_style_spec = build_asset_style_spec(brief, scene_graph)
        scene_graph = apply_asset_style_to_scene_graph(scene_graph, asset_style_spec)
        image2_generation_plan = build_image2_generation_plan(scene_graph, asset_style_spec)
        write_json(output_dir / "text_scene_asset_style_spec.json", asset_style_spec)
        write_json(output_dir / "text_scene_image2_generation_plan.json", image2_generation_plan)
    if bool(getattr(args, "room_texture_search", True)):
        texture_report = build_room_texture_search_plan(brief, prompt)
        texture_report = materialize_room_texture_images(texture_report, output_dir / "room_textures")
        scene_graph["room"]["materials"] = texture_report["materials"]
        write_json(output_dir / "text_scene_texture_search.json", texture_report)
    if args.trellis_asset_library_dir:
        scene_graph["asset_libraries"] = {
            "trellis_rigid_assets": str(args.trellis_asset_library_dir),
            "reuse_asset_alias_file": str(args.reuse_asset_alias_file) if args.reuse_asset_alias_file else None,
        }
    if args.articulated_asset_library_dir:
        scene_graph.setdefault("asset_libraries", {})["articulated_assets"] = str(args.articulated_asset_library_dir)
    write_json(output_dir / "text_scene_scene_graph.json", scene_graph)

    human_constraints = _load_human_constraints(args.human_constraints_file)
    constraints = synthesize_constraints(scene_graph, human_constraints)
    write_json(output_dir / "text_scene_constraints.json", constraints)

    candidates = generate_layout_candidates(scene_graph, candidate_count=int(args.candidate_count))
    write_json(output_dir / "text_scene_layout_candidates.json", {"schema": "tree_sage_text_layout_candidates_v1", "candidates": candidates})

    if args.layout_critic:
        critic = select_best_candidate(candidates, constraints)
        selected_index = int(critic["selected_index"])
    else:
        critic = {
            "schema": "tree_sage_text_scene_critic_v1",
            "selected_index": 0,
            "selected_candidate_id": candidates[0]["scene_id"] if candidates else None,
            "scores": [],
            "accepted": True,
            "disabled": True,
        }
        selected_index = 0
    write_json(output_dir / "text_scene_critic.json", critic)

    selected_plan = candidates[selected_index]
    selected_plan["constraints"] = constraints["constraints"]
    selected_plan["text_scene_reports"] = {
        "brief": str(output_dir / "text_scene_brief.json"),
        "scene_graph": str(output_dir / "text_scene_scene_graph.json"),
        "constraints": str(output_dir / "text_scene_constraints.json"),
        "layout_candidates": str(output_dir / "text_scene_layout_candidates.json"),
        "critic": str(output_dir / "text_scene_critic.json"),
    }
    if texture_report is not None:
        selected_plan["text_scene_reports"]["texture_search"] = str(output_dir / "text_scene_texture_search.json")
    if asset_style_spec is not None:
        selected_plan["asset_style_spec"] = asset_style_spec
        selected_plan["image2_generation_plan"] = image2_generation_plan
        selected_plan["text_scene_reports"]["asset_style_spec"] = str(output_dir / "text_scene_asset_style_spec.json")
        selected_plan["text_scene_reports"]["image2_generation_plan"] = str(output_dir / "text_scene_image2_generation_plan.json")
    scene_plan_path = output_dir / "scene_plan.json"
    selected_plan["asset_pipeline_status"] = {
        "strategy": str(args.asset_strategy),
        "requested_pipeline": str(args.asset_pipeline),
        "implemented": str(args.asset_pipeline) != "none",
        "status": "pending",
    }
    write_json(scene_plan_path, selected_plan)
    write_topdown_svg(selected_plan, output_dir / "layout_preview.svg")
    asset_pipeline_report = ensure_assets_and_scene(selected_plan, scene_plan_path, output_dir, args)
    selected_plan["asset_pipeline_status"] = {
        "strategy": str(args.asset_strategy),
        "requested_pipeline": str(args.asset_pipeline),
        "resolved_pipeline": asset_pipeline_report.get("resolved_pipeline"),
        "implemented": str(args.asset_pipeline) != "none",
        "ok": asset_pipeline_report.get("ok"),
        "asset_dir": asset_pipeline_report.get("asset_dir"),
        "scene_glb": asset_pipeline_report.get("scene_glb"),
        "report": str(output_dir / "text_scene_asset_pipeline_report.json"),
    }
    write_json(scene_plan_path, selected_plan)

    summary = {
        "schema": "tree_sage_text_scene_summary_v1",
        "output_dir": str(output_dir),
        "prompt": prompt,
        "room_type": brief["room_type"],
        "style_tags": brief["style_tags"],
        "object_count": len(selected_plan.get("objects", [])),
        "candidate_count": len(candidates),
        "selected_candidate_id": selected_plan.get("scene_id"),
        "critic_accepted": critic.get("accepted"),
        "critic_score": (
            critic.get("scores", [{}])[selected_index].get("score")
            if critic.get("scores") and selected_index < len(critic["scores"])
            else None
        ),
        "scene_plan": str(output_dir / "scene_plan.json"),
        "layout_preview": str(output_dir / "layout_preview.svg"),
        "asset_pipeline_status": selected_plan["asset_pipeline_status"],
        "asset_pipeline_report": str(output_dir / "text_scene_asset_pipeline_report.json"),
        "scene_glb": asset_pipeline_report.get("scene_glb"),
    }
    if texture_report is not None:
        summary["texture_search"] = str(output_dir / "text_scene_texture_search.json")
    if asset_style_spec is not None:
        summary["asset_style_spec"] = str(output_dir / "text_scene_asset_style_spec.json")
        summary["image2_generation_plan"] = str(output_dir / "text_scene_image2_generation_plan.json")
    write_json(output_dir / "summary.json", summary)
    return summary
