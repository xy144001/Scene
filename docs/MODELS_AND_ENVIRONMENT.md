# Models And Environment

## Required Runtime

- Linux + NVIDIA GPU. TRELLIS.2 资产生成建议 24GB 以上显存；512 pipeline 更省显存。
- Python 3.10 for Flow2 orchestration.
- Blender 4.3.2 or newer compatible build. 当前默认路径是 `/data/xy/tools/blender-4.3.2-linux-x64/blender`。
- Codex CLI with image input support. Flow2 agents call `codex exec` for JSON VLM decisions.
- CUDA/PyTorch versions must match the machine driver.

## Required Models

Set these paths in `.env` copied from `env/paths.example.env`.

1. TRELLIS.2 repo and weights
   - `SAGE_TRELLIS_REPO`: local TRELLIS.2 source repo.
   - `SAGE_TRELLIS_MODEL`: local `trellis2_primary` model directory.
   - For `--pipeline-type 512`, the bridge loads:
     - `sparse_structure_flow_model`
     - `sparse_structure_decoder`
     - `shape_slat_decoder`
     - `tex_slat_decoder`
     - `shape_slat_flow_model_512`
     - `tex_slat_flow_model_512`

2. RMBG-2.0 background removal
   - `SAGE_RMBG_MODEL`: local RMBG-2.0 model directory.
   - `SAGE_RMBG_MODULE_ROOT`: Hugging Face module cache that contains the RMBG custom module.

3. Reference depth model
   - `SAGE_REFERENCE_DEPTH_MODEL`: local relative depth model directory, currently `/data/xy/pat3d_stage1_data/models/depth__large_relative`.
   - This is optional for smoke tests if running with `--no-reference-depth`, but should be enabled for normal reproduction.

4. Optional Flux models
   - `SAGE_FLUX2_MODEL`: local `FLUX.2-klein-9B`; useful when generating fallback source images.
   - `SAGE_FLUX1_MODEL`: local Flux.1 schnell model; legacy fallback only.
   - Current best reproduction uses image2 source images, so Flux is not needed if `--asset-source-image-dir` is complete.

## Python Environments

Use separate environments if possible:

```bash
conda env create -f env/conda_orchestrator.yml
conda activate tree-sage-flow2
```

For TRELLIS.2, start from the official TRELLIS.2 environment and then compare against:

```bash
pip install -r env/trellis2_bridge_requirements.txt
```

For the orchestrator venv:

```bash
pip install -r env/orchestrator_requirements.txt
```

## Important TRELLIS.2 Export Setting

Use no-WebP GLB export by default. We observed color shifts on some assets when using compressed WebP textures inside GLB. The bridge now defaults to:

```bash
--no-glb-webp
```

The current compact reproduction setting is:

```bash
--pipeline-type 512 --trellis-preprocess-image --texture-size 512 --decimation-target 500000 --no-glb-webp
```

