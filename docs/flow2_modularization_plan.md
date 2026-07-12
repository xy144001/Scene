# TreeSAGE Flow 2 Modularization Plan

Current state:

- The Flow 2 orchestration lives mostly in `scripts/run_tree_sage_scene.py`.
- That file mixes CLI parsing, Codex agent calls, reference/depth analysis, scene graph normalization, layout repair, asset QA, Blender rendering, MuJoCo validation, and report writing.
- Codex agents are not persistent UI chat windows. They are short-lived `codex exec --ephemeral` subprocesses launched by the main Python script. Blender, DepthAnything, Trellis2 bridge, and MuJoCo are also subprocess/tool calls, not agent windows.

This plan keeps the existing behavior stable while moving code behind explicit module interfaces.

## Current Split Status

Implemented module boundaries:

- `scripts/tree_sage_flow2/io.py`
  - Shared JSON extraction/writing wrappers.
- `scripts/tree_sage_flow2/agents/codex_runner.py`
  - Shared ephemeral `codex exec` JSON-agent runner.
- `scripts/tree_sage_flow2/assets/source_report.py`
  - Asset provenance/source report now runs through the `assets/` package.
- `scripts/tree_sage_flow2/reference/depth.py`
  - Reference-depth analysis now has a separate module boundary. The heavy depth helper internals still live in `run_tree_sage_scene.py` and are passed through a builder callback, because they currently share many semantic predicates with layout logic.
- `scripts/tree_sage_flow2/validation/mujoco.py`
  - MuJoCo proxy validation now runs through the `validation/` package.

`scripts/run_tree_sage_scene.py` remains the orchestration entrypoint. The next useful split is to move the reference-depth helper dependencies into `reference/depth.py`, then move reference alignment/global validator into `validation/`.

## Target Package Layout

Create a package:

```text
scripts/tree_sage_flow2/
  __init__.py
  cli.py
  context.py
  orchestrator.py
  io.py
  config.py

  agents/
    __init__.py
    codex_runner.py
    scene_graph_agent.py
    semantics_agent.py
    relation_agent.py
    grounding_agent.py
    spatial_order_agent.py
    pose_agent.py
    asset_policy_agent.py
    render_pose_feedback_agent.py

  scene_graph/
    __init__.py
    normalize.py
    support_tree.py
    room_grounding.py
    reference_consistency.py

  reference/
    __init__.py
    depth.py
    view_condition.py
    grounding.py
    scale_prior.py
    spatial_order.py

  layout/
    __init__.py
    plan_builder.py
    support_surfaces.py
    branch_executor.py
    collision.py
    repair.py
    tabletop.py
    pose_review.py
    bedding_dedupe.py

  hypergraph/
    __init__.py
    build.py
    validate.py
    repair.py

  assets/
    __init__.py
    registry.py
    prepare.py
    component_policy.py
    axis_repair.py
    parametric_fallback.py
    source_report.py

  render/
    __init__.py
    preview.py
    blender.py
    turntables.py
    pose_feedback_sheets.py

  validation/
    __init__.py
    reference_alignment.py
    global_validator.py
    mujoco.py

  reports/
    __init__.py
    summary.py
    writers.py
```

`scripts/run_tree_sage_scene.py` should eventually become a thin compatibility entrypoint:

```python
from tree_sage_flow2.cli import parse_args
from tree_sage_flow2.orchestrator import run_flow2

def main() -> None:
    run_flow2(parse_args())

if __name__ == "__main__":
    main()
```

## Stable Interfaces

Use a small shared context object so modules do not pass dozens of positional arguments.

```python
@dataclass
class Flow2Inputs:
    scene_prompt: str
    flux_image: Path | None
    scene_graph_file: Path | None
    room_layout_file: Path | None
    output_dir: Path

@dataclass
class Flow2State:
    args: argparse.Namespace
    output_dir: Path
    scene_prompt: str
    scene_graph: dict[str, Any]
    support_tree: dict[str, Any]
    cross_constraints: list[dict[str, Any]]
    parent: dict[str, str]
    relation_to_parent: dict[str, str]
    plan: dict[str, Any]
    reports: dict[str, dict[str, Any]]
```

Each module should expose one or two public functions:

```python
def run_reference_analysis(state: Flow2State) -> Flow2State: ...
def run_layout_initialization(state: Flow2State) -> Flow2State: ...
def run_asset_pipeline(state: Flow2State) -> Flow2State: ...
def run_validation(state: Flow2State) -> Flow2State: ...
```

Rules:

- Public functions mutate `state.plan`, `state.scene_graph`, and `state.reports` deliberately.
- Private helpers stay inside their module.
- Every module writes no files directly unless it is in `reports/`, `render/`, `assets/prepare.py`, or a subprocess/tool wrapper.
- Agent modules return raw JSON plus a merge report. They should not directly mutate layout except through explicit merge functions.

## Module Call Chain

The orchestrator should read like this:

```python
state = load_or_create_scene_graph(args)
state = run_reference_analysis(state)
state = build_support_and_initial_plan(state)
state = apply_scale_and_reference_layout(state)
state = run_pose_and_hypergraph_passes(state)
state = run_plan_level_collision_repairs(state)

if not args.plan_only:
    state = run_asset_pipeline(state)
    state = run_render_pose_feedback(state)
    state = assemble_and_render_final_scene(state)

state = run_validation(state)
write_all_reports(state)
```

## Migration Order

Do not move everything at once. Use this order to avoid breaking known-good outputs:

1. `reports/` and `io/`
   - Move `write_json`, summary construction, report path creation, and preview/report output.
   - Lowest behavioral risk.

2. `agents/`
   - Move `run_codex_reference_json_agent`, `run_codex_scene_graph`, prompt builders, and merge functions.
   - Keep subprocess command exactly identical.
   - Regression check: request/response filenames must remain the same.

3. `validation/`
   - Move MuJoCo wrapper, global validator, reference alignment.
   - Regression check: `mujoco_check.json`, `global_validator_report.json`.

4. `assets/`
   - Move asset registry, component policy regeneration, wall axis repair, parametric fallback.
   - Regression check: `asset_registry.json`, `parametric_fallback_report.json`, GLB path.

5. `reference/`
   - Move depth, view condition, grounding, spatial order, scale prior.
   - Regression check: `reference_depth_report.json`, `object_scale_prior_report.json`.

6. `layout/`
   - Move plan builder, support surfaces, branch executor, collision repair, tabletop packing, bedding dedupe.
   - This is the highest-risk group because these functions share many helper predicates.

7. `hypergraph/`
   - Move build, validate, and repair once layout helpers are stable.

8. `orchestrator.py`
   - Only after modules above pass the same scene regression.

## Regression Gate

After each migration step, run the same known scene and compare:

```text
/data/xy/SAGE_runs/tree_sage_bedroom_frontview/flow_refiner_test_v68_soft_visual_mujoco_filter
```

Required invariants:

- `scene_tree_sage_flow2.glb` is generated.
- `aggregate_collision_ok == true`
- `aggregate_conflict_count == 0`
- `mujoco_ok == true`
- `integrated_bed_bedding_dedupe_removed_count == 1`
- `parametric_fallback_count == 1`
- `final_render_pose_feedback_rollback_count == 0`
- `asset_non_trellis_ids == ["closet_double_door"]`

Allowable differences:

- Codex agent wording in raw response files.
- Render image pixel-level differences from Blender nondeterminism.
- Soft scene hypergraph warnings, as long as hard warnings remain empty.

## What Not To Do

- Do not split by copying large unrelated blocks without tests.
- Do not change filenames of reports during migration.
- Do not convert agent subprocess calls into persistent chat sessions.
- Do not let modules import each other cyclically through `run_tree_sage_scene.py`.
- Do not move asset generation and layout repair in the same commit/step.

## First Practical Refactor

Recommended first code step:

1. Create `scripts/tree_sage_flow2/io.py` with `write_json`, `extract_json`, path helpers.
2. Create `scripts/tree_sage_flow2/agents/codex_runner.py` with the common `codex exec --ephemeral` runner.
3. Replace only the duplicated subprocess blocks in `run_codex_scene_graph`, `run_codex_object_semantics`, and `run_codex_reference_json_agent`.
4. Run `py_compile`.
5. Run one scene in a new output directory and compare reports against v68.
