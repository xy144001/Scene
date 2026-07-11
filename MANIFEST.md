# Upload Manifest

建议上传到 GitHub 的内容：

- `sage/scripts/`: TreeSAGE Flow2 图生主流程、文生主流程、Blender 组装/渲染脚本、fallback 资产脚本。
- `sage/scripts/tree_sage_text/`: 文生场景 brief、scene graph、layout、critic、asset pipeline 和 room texture search 模块。
- `sage/webui/`: 本地网页控制面板，默认输出写入 `/data/xy/SAGE_runs/webui/`。
- `sage/server/trellis2_flux_bridge_server.py`: TRELLIS.2 HTTP bridge，当前默认 no-WebP GLB 导出。
- `sage/server/flux2_klein_server.py`, `sage/server/flux_schnell_server.py`: 历史可选本地 Flux 服务；当前主流程不再自动回退 Flux。
- `sage/config/`: 当前复用别名、经验日志等轻量配置。
- `sage/skills/tree-sage-layout-debugging/`: 当前调试 skill 文档。
- `examples/bedroom_0610_113657/`: 参考图、固定 scene graph、人工约束示例、source image 清单。
- `env/`: 环境依赖和路径模板。
- `scripts/`: portable 启动和复现脚本。
- `docs/`: 流程说明、状态记录、回归记录。

不要上传：

- 模型权重目录，例如 `models/`, `/data/xy/pat3d_stage*_data/models/`。
- 运行输出，例如 `outputs/`, `runs/`, `/data/xy/SAGE_runs/...`。
- WebUI 本地任务和日志，例如 `sage/webui/runs/`, `sage/webui/jobs/`。
- GLB 资产、Blender 文件、大图临时渲染，除非明确要做 release artifact。
- 本地 API key 或 `key.json`。
- `__pycache__`, `.git`, `.venv`。
