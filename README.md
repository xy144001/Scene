# TreeSAGE Scene Generation Package

这是当前 TreeSAGE 图生场景与文生场景实验流程的 GitHub 版本。仓库只包含代码、配置、说明文档和小体积示例输入，不包含模型权重、Trellis2 生成资产、GLB 场景结果和 `/data/xy` 运行产物。

## Current Pipeline

系统现在有两条主链路。

### Image-To-Scene

图生场景主入口是 `sage/scripts/run_tree_sage_scene.py`。核心顺序是：

1. 输入 reference image、prompt、可选 scene graph、可选人工约束。
2. 构建或修正 scene graph、support tree、物体类别、pose/scale 初值。
3. 使用 image2 生成逐物体 source image，流程只消费这些 source images，不再自动回退 Flux。
4. 进入 Trellis2 前做 source image QA，确认图片是目标物体、颜色接近 reference、背景干净。
5. 用 Trellis2 `pipeline_type=512 + preprocess_image + no-WebP GLB export` 生成资产。
6. 一阶段做粗布局和高度/scale 修正，二阶段做紧凑与碰撞修复，三阶段做细致 bbox/空间关系调整。
7. 特殊团簇 solver 处理窗户-窗帘等固定结构。
8. critic 默认开启，最终对 reference 与 render 进行评价，并只接受通用且验证有效的流程修正。
9. Blender 组装最终 GLB 和诊断渲染。

### Text-To-Scene

文生场景主入口是 `sage/scripts/run_tree_sage_text_scene.py`。当前是 MVP，但已经接入完整可运行链路：

1. 输入文本 prompt 和可选 `--room-type`。
2. 生成 text brief、room grammar、scene graph、关系约束和多候选布局。
3. 默认开启 text layout critic，选择最合理候选。
4. 默认开启 `--room-texture-search`，为墙面和地板选择温和、常见的室内纹理。
5. 纹理模块会生成实际 PNG 贴图到 `room_textures/`，并写入 `scene_plan.room.materials`。
6. 资产有两种来源：
   - `generate_from_scratch`: 提供 image2 单物体图目录，然后由 Trellis2 生成 GLB。
   - `asset_library`: 直接复用已有 Trellis2 rigid asset 库。
7. Blender 组装最终 `scene_text_sage.glb`。

文生场景不会使用 Flux fallback。缺少 image2 source image 目录或缺少必需物体图片时会失败或阻塞。

## Repository Layout

- `sage/scripts/run_tree_sage_scene.py`: 图生场景 Flow2 主入口。
- `sage/scripts/run_tree_sage_text_scene.py`: 文生场景主入口。
- `sage/scripts/tree_sage_flow2/`: 图生场景的模块化 agent、reference、validation 边界模块。
- `sage/scripts/tree_sage_text/`: 文生场景 brief、scene graph、layout、critic、asset、texture search 模块。
- `sage/scripts/blender_assemble_sage_scene.py`: Blender 场景组装脚本，支持房间墙面/地板 image texture。
- `sage/server/trellis2_flux_bridge_server.py`: 本地 Trellis2 HTTP bridge。名字保留历史兼容，当前流程使用 image2 source images。
- `sage/webui/`: 本地网页控制面板。
- `examples/bedroom_0610_113657/`: 卧室 reference 的可复现实验输入。
- `scripts/`: portable 启动/复现脚本。
- `env/`: 环境和路径模板。
- `docs/`: 详细流程文档、调试记录和环境说明。

建议先读：

- `docs/FLOW2_MODULES_AND_EFFECTS.md`
- `docs/MODELS_AND_ENVIRONMENT.md`
- `sage/webui/README.md`

## Environment

1. 准备 Python orchestration 环境。

```bash
conda env create -f env/conda_orchestrator.yml
conda activate tree-sage-flow2
```

或使用已有 venv：

```bash
pip install -r env/orchestrator_requirements.txt
```

2. 准备本机路径配置。

```bash
cp env/paths.example.env .env
source .env
```

需要按机器实际路径配置：

- Python/venv 路径
- Blender 路径
- Trellis2 repo、模型和环境
- 默认输出目录，建议放在 `/data/xy/SAGE_runs/...`

3. 安装/准备 Trellis2。

Trellis2 模型权重不放进 GitHub。详细说明见 `docs/MODELS_AND_ENVIRONMENT.md`。我们当前默认使用：

- `pipeline_type=512`
- `preprocess_image=True`
- `texture_size=2048`
- `decimation_target=500000`
- no-WebP GLB export

## Start Services

启动 Trellis2 bridge：

```bash
source .env
scripts/start_trellis2_bridge_512_no_webp.sh
```

服务默认监听：

```text
http://127.0.0.1:8082
```

启动本地 WebUI：

```bash
/data/xy/SAGE_repro/venv/bin/python /home/xy/SAGE/sage/webui/server.py --host 127.0.0.1 --port 8787
```

打开：

```text
http://127.0.0.1:8787/
```

WebUI 默认数据根目录：

```text
/data/xy/SAGE_runs/webui/
```

其中：

- `runs/`: 场景输出
- `jobs/`: job 记录和日志
- `source_images/`: image2 单物体图默认根目录

可以用环境变量覆盖：

- `SAGE_WEBUI_DATA_ROOT`
- `SAGE_WEBUI_OUTPUT_ROOT`
- `SAGE_WEBUI_JOBS_DIR`
- `SAGE_WEBUI_ASSET_SOURCE_ROOT`

## Image2 Source Images

当前流程要求先为每个物体准备 image2 source image。推荐方式：

1. 输入 reference 和目标物体文本。
2. 生成单个物体的正面、孤立、干净背景图。
3. 文件名与 object id 对齐，例如 `bed.png`、`window.png`、`left_curtain.png`。
4. 进入 Trellis2 前先 QA：物体类别正确、主要颜色正确、没有多余场景背景。

文生场景从 0 生成资产时，WebUI/API 需要填写 source image 目录；后台只消费这些图片，不负责自动调用 Flux。

## Run Image-To-Scene Example

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

只检查 planning，不生成资产：

```bash
source .env
scripts/run_bedroom_0610_113657_plan_only_smoke.sh
```

重点输出：

- `scene_tree_sage_flow2.glb`
- `scene_plan.json`
- `reference_vs_render_est_front_high_fine_spatial_order.png`
- `preview_topdown.png`
- `fine_spatial_order_report.json`
- `asset_registry.json`
- `run_summary.json`

## Run Text-To-Scene

使用资产库复用：

```bash
/data/xy/SAGE_repro/venv/bin/python sage/scripts/run_tree_sage_text_scene.py \
  --prompt-file prompt.txt \
  --output-dir /data/xy/SAGE_runs/webui/runs/my_text_scene \
  --room-type living_room \
  --asset-strategy asset_library \
  --asset-pipeline asset_library \
  --trellis-asset-library-dir /path/to/assets_text_scene \
  --candidate-count 3 \
  --layout-critic \
  --room-texture-search \
  --assemble-scene
```

从 image2 source images 生成资产：

```bash
/data/xy/SAGE_repro/venv/bin/python sage/scripts/run_tree_sage_text_scene.py \
  --prompt-file prompt.txt \
  --output-dir /data/xy/SAGE_runs/webui/runs/my_text_scene \
  --room-type living_room \
  --asset-strategy generate_from_scratch \
  --asset-pipeline source_images \
  --asset-source-image-dir /data/xy/SAGE_runs/webui/source_images/my_scene/source_images \
  --asset-source-image-required \
  --asset-source-image-qa-strict \
  --candidate-count 3 \
  --layout-critic \
  --room-texture-search \
  --assemble-scene
```

文生重点输出：

- `scene_text_sage.glb`
- `scene_plan.json`
- `layout_preview.svg`
- `text_scene_brief.json`
- `text_scene_scene_graph.json`
- `text_scene_constraints.json`
- `text_scene_critic.json`
- `text_scene_texture_search.json`
- `room_textures/wall_texture.png`
- `room_textures/floor_texture.png`
- `text_scene_asset_pipeline_report.json`
- `summary.json`

## Room Texture Search

文生场景默认开启纹理搜索模块。它根据 `room_type`、style tags 和 prompt 选择温和的墙面/地板方案：

- 墙面优先选择 warm greige painted plaster、soft warm white limewash、quiet taupe matte paint 等低对比纹理。
- 地板优先选择 low-sheen natural oak、white oak、honey oak 或卧室低绒 carpet。
- 显式 prompt 信息优先级高于泛化 style，例如 prompt 写了 `beige walls` 会优先选 warm greige，而不是被 `industrial` tag 拉到灰墙。
- 模块会生成 PNG 贴图，避免 Blender procedural 节点导出 GLB 后丢失。

参考信息记录在 `text_scene_texture_search.json`，便于后续审查。

## GitHub Size Rules

不要提交：

- `/data/xy` 下的运行结果
- Trellis2 模型权重
- 生成出来的 `.glb`
- `runs/`、`jobs/`、`room_textures/` 大批量实验产物
- `__pycache__/`

需要共享结果时，优先共享路径、summary、诊断图或小规模示例输入。
