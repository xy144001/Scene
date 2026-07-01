# SAGE 复现状态

## 当前结论

- 论文：`SAGE.pdf`，标题为 `SAGE: Scalable Agentic 3D Scene Generation for Embodied AI`。
- 官方代码：`/home/xy/SAGE/sage`，Git commit `fe3966013a495dc1642710de93a83ddf66e534a0`。
- 大文件和复现输出统一放在 `/data/xy/SAGE_repro`。
- 已完成最小复现：官方 SAGE-10k 场景导出 GLB、Flux 文生图、Flux + Trellis2 图生 3D 桥接。
- 已新增 `SAGE_SIM_BACKEND=mujoco` 本地后端，用于在没有 Isaac Sim 时跑通物理检查流程。

## 已生成文件

- 官方 SAGE-10k 样例场景 GLB：`/data/xy/SAGE_repro/exports/glb/layout_d990801a.glb`
- Flux smoke test 图片：`/data/xy/SAGE_repro/flux_images_test_fast/fe9887ed38db4606a89b672408ed3626.png`
- Trellis2 smoke test GLB：`/data/xy/SAGE_repro/trellis2_bridge_test/03836bbbeca049be94d9b090b2596d7d.glb`
- Trellis2 smoke test 元数据：`/data/xy/SAGE_repro/trellis2_bridge_test/03836bbbeca049be94d9b090b2596d7d.json`

## 本地服务

在 `/home/xy/SAGE/sage` 下启动 Flux：

```bash
./server/start_flux_schnell_server.sh --port 8083 --output-dir /data/xy/SAGE_repro/flux_images --width 768 --height 768 --steps 4
```

显存充足时可加 `--no-cpu-offload` 提速。

启动 Trellis2 桥接服务：

```bash
./server/start_trellis2_flux_bridge_server.sh --port 8082 --flux-server-url http://127.0.0.1:8083 --output-dir /data/xy/SAGE_repro/trellis2_bridge --pipeline-type 512
```

该桥接服务兼容 SAGE 原来的 TRELLIS 异步接口：`POST /generate` 返回 `job_id`，`GET /job/<job_id>` 返回 GLB。

## 修改点

- `server/constants.py` 支持用环境变量覆盖结果和数据根目录。
- `client/scripts/_env.sh` 统一设置 `/data/xy/SAGE_repro` 相关路径。
- 4 个 client 启动脚本改为不依赖硬编码 `cd SAGE`。
- `client/isaac_sim_conda.sh` 改为可配置 `CONDA_ENV_NAME`、`ISAACSIM_PATH`、`ISAACLAB_PATH`。
- 新增 `server/flux_schnell_server.py` 和启动脚本，用本地 Flux.1-schnell 提供 SAGE 需要的文生图接口。
- 新增 `server/trellis2_flux_bridge_server.py` 和启动脚本，用 Flux 生成参考图，再调用本地 Trellis2 生成 GLB。
- Trellis2 桥接层会把 RGB 参考图预处理成 RGBA，避免 Trellis2 在无 alpha 输入上触发 rembg 的 meta tensor 报错。
- 新增 `server/isaacsim/isaac_mcp/local_mujoco_backend.py`，在 `SAGE_SIM_BACKEND=mujoco` 时绕过 Isaac Sim socket，保留 `create_*`、`simulate_the_scene` 等原函数调用形状。

## 仍未完整复现的部分

- 官方完整 pipeline 还需要 Isaac Sim 4.2；当前机器未发现可用 Isaac Sim 安装。
- 官方 server 的 LLM/VLM 需要真实 API 或本地 OpenAI-compatible endpoint；`server/key.json` 已放占位配置，实际 key 和 endpoint 还需要填。
- SAGE-10k 完整数据集约 870GB，当前只下载了官方 kit 和一个公开样例场景用于最小复现。
- 当前 `/data/xy/SAGE_repro/venv` 是导出用最小环境，还没有 `mcp` 和 `mujoco`；完整 client 流程需要补轻量依赖环境。
