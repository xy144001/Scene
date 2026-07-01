# Bedroom 0610 113657 Example

这个示例对应我们调试最多的卧室 reference 图：

- `reference_0610_113657.png`: 原始 reference。
- `prompt.txt`: image-only 场景推断 prompt。
- `scene_graph_augmented_curtains_ceiling_raw_input.json`: 固定对象类别和对象 ID 的 scene graph 输入。
- `human_constraints_manual_bbox_v1.json`: 人工 bbox projection overlap 约束示例。
- `source_images_manifest.txt`: image2 生成的逐物体源图文件名清单。

要复现同一批资产，请把 image2 源图放在：

```bash
examples/bedroom_0610_113657/source_images/
```

在原机器上可以直接运行：

```bash
scripts/prepare_bedroom_source_images_from_local.sh
```

如果不放 source images，Flow2 仍可尝试通过 Trellis bridge 的 Flux fallback 生成资产，但结果不会和我们当前 image2 实验一致。

