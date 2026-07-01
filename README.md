# TreeSAGE Flow2 Reproduction Package

这是当前 TreeSAGE Flow2 实验流程的可上传 GitHub 版本。它包含代码、配置模板、示例约束和说明，不包含模型权重和大体积运行产物。

## What This Runs

Flow2 的主线是：

1. 输入 reference image、prompt、可选 scene graph、可选人工约束。
2. 用 Codex/VLM agents 建立或修正 scene graph、support tree、空间关系和细致 bbox 约束。
3. 为每个物体读取 image2 source image，调用 TRELLIS.2 生成 GLB。
4. 用一阶段粗布局、二阶段紧凑/碰撞修复、三阶段细致空间排序修复布局。
5. 用 Blender 组装和渲染最终场景。

当前默认资产生成策略：`TRELLIS.2 pipeline_type=512 + preprocess image + texture_size=512 + no-WebP GLB export`。no-WebP 是我们修复颜色偏移后的默认导出流程。

## Repository Layout

- `sage/scripts/run_tree_sage_scene.py`: Flow2 主入口。
- `sage/scripts/tree_sage_flow2/`: agents、IO、reference depth、MuJoCo validation 边界模块。
- `sage/server/trellis2_flux_bridge_server.py`: 本地 TRELLIS.2 HTTP bridge。
- `examples/bedroom_0610_113657/`: 当前卧室 reference 的可复现实验输入。
- `scripts/`: portable 启动/复现脚本。
- `env/`: 依赖和路径模板。
- `docs/`: 更长的设计文档和调试记录。

建议新同学先读 `docs/FLOW2_MODULES_AND_EFFECTS.md`。这份文档按模块解释每一步怎么起效、输出什么报告、失败时该查哪里。

## Setup

1. 准备代码目录。

```bash
cd tree_sage_flow2_repro
cp env/paths.example.env .env
```

2. 修改 `.env` 里的模型、Python 和 Blender 路径，然后加载：

```bash
source .env
```

3. 安装 orchestration 环境：

```bash
conda env create -f env/conda_orchestrator.yml
conda activate tree-sage-flow2
```

或使用已有 venv 后：

```bash
pip install -r env/orchestrator_requirements.txt
```

4. 准备 TRELLIS.2 环境和模型。细节见 `docs/MODELS_AND_ENVIRONMENT.md`。

## Start TRELLIS.2 Bridge

```bash
source .env
scripts/start_trellis2_bridge_512_no_webp.sh
```

服务默认监听 `http://127.0.0.1:8082`。保持这个终端运行。

## Prepare Bedroom Source Images

在原机器上可以直接复制我们 image2 生成的逐物体源图：

```bash
scripts/prepare_bedroom_source_images_from_local.sh
```

在新机器上，把 `examples/bedroom_0610_113657/source_images_manifest.txt` 里的文件放到：

```bash
examples/bedroom_0610_113657/source_images/
```

这些图片由 image2 按“reference + 单个物体文本，正面孤立照片”生成。进入 TRELLIS.2 前需要人工或脚本检查图片是否确实是目标物体、颜色是否接近 reference、背景是否干净。

## Run Reproduction

无人工约束版：

```bash
source .env
scripts/run_bedroom_0610_113657_no_manual.sh
```

带人工约束版：

```bash
source .env
scripts/run_bedroom_0610_113657_manual.sh
```

只检查 planning 是否能跑通，不生成资产：

```bash
source .env
scripts/run_bedroom_0610_113657_plan_only_smoke.sh
```

主要输出在 `SAGE_OUTPUT_DIR`，默认是 `/data/xy/SAGE_runs/tree_sage_flow2/...`。重点看：

- `scene_tree_sage_flow2.glb`
- `scene_plan.json`
- `reference_vs_render_est_front_high_fine_spatial_order.png`
- `preview_topdown.png`
- `fine_spatial_order_report.json`
- `asset_registry.json`
- `run_summary.json`

## Notes For New References

- 如果是新 reference，先生成逐物体 image2 source images，再放到一个新的 `source_images/` 目录。
- 运行前先检查 source images；床、柜子、窗帘这种纹理/颜色容易影响 Trellis2 结果。
- 窗户窗帘簇按固定顺序处理：左窗帘、窗户、右窗帘；solver 会按 reference 判断 tight/medium/loose 紧密程度。
- 人工约束文件是可选模块，格式见 `examples/bedroom_0610_113657/human_constraints_manual_bbox_v1.json`。
- 如果只想看布局流程，可以先用 `--plan-only` 或 `--reuse-asset-dir`，避免每次重跑 TRELLIS.2。
