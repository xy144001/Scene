# TreeSAGE Local Web UI

本目录提供一个本地网页控制面板，用于把图生场景和文生场景流程包装成可视化入口。

## 启动

```bash
/data/xy/SAGE_repro/venv/bin/python /home/xy/SAGE/sage/webui/server.py --host 127.0.0.1 --port 8787
```

打开：

```text
http://127.0.0.1:8787/
```

## 当前接入

- 图生场景：接入 `run_tree_sage_scene.py`，可创建任务，也可勾选“立即运行”启动后台进程。
- 文生场景：UI/API 已接入 `scripts/run_tree_sage_text_scene.py`。当前链路会生成文本 brief、scene graph、约束、多候选布局、text critic、资产计划、资产生成/复用、Blender 组装和最终 GLB。
- 文生房间纹理：默认开启 `--room-texture-search`，根据房间类型、style 和 prompt 选择温和的墙面/地板纹理规格，写入 `text_scene_texture_search.json` 和 `scene_plan.room.materials`；Blender 会用 procedural painted plaster/limewash/wood plank/carpet 材质节点渲染墙壁和地板。
- 资产从 0 生成：通过 `--asset-source-image-dir` 接入 image2 物体图目录，先做 source image QA，再使用 Trellis2 `512 + preprocess_image + 1024 texture + 120000 decimation` 默认参数生成 GLB。
- 资产库复用：通过 `--reuse-asset-dir`、`--reuse-asset-alias-file`、`--partial-reuse-assets`、`--copy-reused-assets` 接入现有 Trellis2 rigid asset 目录。
- critic：默认开启，默认 3 轮。
- 文生从 0 生成资产时不会自动回退到 Flux；缺少 image2 source image 目录或 required object 图片时任务会阻塞/失败。

## 预留接口

- 铰接物体资产库：UI/API 已有 `articulatedAssetLibraryDir` 字段，当前主流程尚未消费。
- 整体窗帘-窗户团簇资产：UI/API 已有开关，当前图生稳定流程仍使用确定性窗帘簇 solver。
- image2 单物体图生成目前由 Codex 对话侧或外部工具完成；WebUI 后台任务只消费生成好的 `source_images/` 文件。

## API

- `GET /api/config`
- `POST /api/jobs/preview`
- `POST /api/jobs`
- `GET /api/jobs`
- `GET /api/jobs/{id}`
- `POST /api/jobs/{id}/cancel`

默认数据根目录是 `/data/xy/SAGE_runs/webui/`：

- 任务记录和日志写入 `/data/xy/SAGE_runs/webui/jobs/`
- 场景输出写入 `/data/xy/SAGE_runs/webui/runs/`
- image2 单物体图默认提示根目录是 `/data/xy/SAGE_runs/webui/source_images/`

这些路径可以分别用 `SAGE_WEBUI_DATA_ROOT`、`SAGE_WEBUI_JOBS_DIR`、`SAGE_WEBUI_OUTPUT_ROOT`、`SAGE_WEBUI_ASSET_SOURCE_ROOT` 覆盖。
