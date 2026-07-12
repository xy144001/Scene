# TreeSAGE Flow2 0610_211046 Regression Fix - 2026-07-05

本文记录这次 `ChatGPT Image 2026年6月10日 21_10_46.png` 卧室场景越改越差的具体原因、修复点和验证结果。

## 结论

这次主要不是 agent 重新识别错了一个物体，而是三个后处理模块的规则有问题：

1. 床的贴墙资产 yaw 修复器过度相信几何 headboard 探针，导致床被翻到反向。
2. 墙面双开门已经触发了资产 QA warning，但 parametric fallback 规则反而跳过了它，导致继续使用错误 Trellis 门。
3. 窗帘簇 solver 把“窗帘贴近窗户”错误实现成“把窗帘本体压窄”，导致两侧 panel 过窄、视觉上不像参考图。

修复后输出目录：

- `/data/xy/SAGE_runs/image2_replacement_20260705/flow2_img0610_211046_fixed_pose_door_curtain_v2`
- 最终对比图：`reference_vs_render_est_front_high_final_accepted.png`
- 场景 GLB：`scene_tree_sage_flow2.glb`

## 原因 1：床为什么会反过来

坏版中 `back_to_wall_asset_local_yaw_repair_report.json` 把床的 `asset_local_yaw_offset_degrees` 从 `0` 改成了 `180`。触发原因是：

- headboard 几何探针给出 `candidate_asset_local_yaw_offset_degrees=180`。
- 但同一个探针也给出 `candidate_preserves_width_tangent_axis=false`。
- 旧逻辑只看 `headboard_confidence >= 0.28`，即使这个候选会破坏墙面切向宽轴，也强行接受。
- 更麻烦的是，这个修复发生在 canonical front 可用之前；第一次修补时 `canonical_front_probe=null`，所以后面的 canonical 判断来不及阻止错误。

修复位置：

- `sage/scripts/run_tree_sage_scene.py:12613`
- `sage/scripts/run_tree_sage_scene.py:12665`
- `sage/scripts/run_tree_sage_scene.py:12688`

新的规则：

- 如果已经有高置信 canonical front，非切向 headboard 几何候选不能覆盖它。
- 对 bed 来说，如果 headboard 几何候选不保持墙面切向宽轴，就保持当前 `asset_local_yaw_offset_degrees`，不做硬修复。
- 报告里明确写 `kept_current_yaw_rejected_non_tangent_headboard_candidate`，避免以后误读成已经成功对齐。

验证结果：

```text
bed yaw=270.0
bed asset_local_yaw_offset_degrees=0.0
back_to_wall_asset_local_yaw_repair_fix_count=0
```

## 原因 2：门为什么一直不对

`closet_double_door` 的 Trellis 资产触发了：

```text
wall-attached asset requires extreme axis compression
```

说明它不是一个适合贴墙的薄门板资产。项目里其实已有本地 parametric 白色双开门 factory，但旧 fallback 逻辑遇到“只有墙面薄轴/极端压缩 warning”时选择跳过，理由是保留 Trellis 可能更贴近 reference。这个判断在本场景是错的。

修复位置：

- `sage/scripts/run_tree_sage_scene.py:36194`

新的规则：

- 简单墙面门/closet door 只要触发薄轴或极端压缩 QA warning，就允许 flat parametric fallback。

验证结果：

```text
parametric_fallback_count=1
asset_non_trellis_ids=["closet_double_door"]
closet_double_door quality=ok
```

## 原因 3：窗帘簇为什么不紧凑/不对称

旧 tight 窗帘簇参数：

```text
SAGE_WINDOW_CURTAIN_CLUSTER_TIGHT_PANEL_MAX_RATIO=0.32
SAGE_WINDOW_CURTAIN_CLUSTER_TIGHT_PANEL_MAX_SPAN=0.36
SAGE_WINDOW_CURTAIN_CLUSTER_TIGHT_PANEL_MIN_SPAN=0.30
```

这等于把“tight”理解成“窗帘本体很窄”。但参考图里的 tight 是窗帘和窗户之间 gap 小，窗帘 panel 自身仍然很宽。

修复位置：

- `sage/scripts/run_tree_sage_scene.py:172`

新的默认值：

```text
SAGE_WINDOW_CURTAIN_CLUSTER_TIGHT_PANEL_MAX_RATIO=0.64
SAGE_WINDOW_CURTAIN_CLUSTER_TIGHT_PANEL_MAX_SPAN=0.72
SAGE_WINDOW_CURTAIN_CLUSTER_TIGHT_PANEL_MIN_SPAN=0.46
```

验证结果：

```text
window y=2.3776 width=1.12
left_curtain_panel y=1.4242 width=0.7168
right_curtain_panel y=3.3310 width=0.7168
curtain_rod y=2.3626 width=2.7236
fine_spatial_order_final_window_curtain_fix_count=1
```

这说明 solver 已经恢复为“窗帘 + 窗户 + 窗帘”的对称结构，且 panel 宽度接近旧版较合理结果。

## 验证方式

代码检查：

```text
/data/xy/SAGE_repro/venv/bin/python -m py_compile sage/scripts/run_tree_sage_scene.py
```

完整复跑：

```text
/data/xy/SAGE_runs/image2_replacement_20260705/flow2_img0610_211046_fixed_pose_door_curtain_v2
```

关键结果：

```text
back_to_wall_asset_local_yaw_repair_fix_count=0
parametric_fallback_count=1
asset_non_trellis_ids=["closet_double_door"]
aggregate_collision_ok=true
mujoco_ok=true
global_validator_ok=false
```

## 仍未完全解决的问题

1. `global_validator_ok=false` 仍存在，主要残留是侧墙窗户/窗帘的 2D left-right 关系在 oblique 视角下不可靠。
2. `fine_spatial_order_accepted=false`，因为 fine order 候选被物理/碰撞回退拒绝；最终图采用 accepted fallback。
3. 窗帘簇在数值和拓扑上已经对称，但渲染视觉仍不够理想。原因更像是 Trellis 单片窗帘资产和侧墙相机角度导致一侧读得不明显，而不是 solver 顺序又错了。
4. 这次没有加入人工约束，运行摘要里 `human_constraints_enabled=false`。

## 后续建议

如果要继续提升窗帘簇，下一步不应该再只调中心排序，而应考虑：

- 给 curtain panel 使用成对共享或镜像的资产，而不是两个独立 Trellis panel。
- 对窗帘 panel 做 procedural/parametric fallback，保证左右宽度、厚度、褶皱方向一致。
- 对 side-wall window-curtain cluster 的最终渲染做专门视觉 acceptance，而不是只看 top-down 数值对称。

## 2026-07-06 复查：门和窗帘仍然不合格的真正原因

用户指出 `flow2_img0610_211046_fixed_pose_door_curtain_v2` 里门仍然像薄片，窗帘左右视觉不对称。复查后结论是：上面的 v2 只能说明“数值关系”比坏版恢复了，但不能说明最终视觉已经正确。

### 门

门的贴墙轴本身没有明显放错：

```text
closet_double_door support_id=wall_west
dimensions width=0.896 length=0.08 height=2.106
yaw=0 footprint_yaw_offset_degrees=90
effective_footprint width=0.08 length=0.896 long_axis_world=y
local_footprint_long_axis=x
local_thin_axis=y
```

也就是说，局部 X 被当作门宽，局部 Y 被当作薄轴，最终长边沿左墙切向 `y`，薄轴沿墙法线，这是合理的。

真正的问题是门被替换成了当前的 flat parametric fallback。这个 fallback 几何非常薄、颜色几乎纯白，并且贴在左墙后，在估计相机的斜视角下只读到一条白色侧边/薄片，缺少真实门的面板厚度、门框、铰链、把手对比和墙面前偏移。因此它通过了 pose/yaw 审查，但视觉上仍然不像 reference 里的门。

现有 render pose feedback 只检查“朝向是否指向室内”，没有检查“门面是否可读”。报告里 `closet_double_door` 被判定为 `current_pose_issue=none`，这是验证缺口。

### 窗帘

窗帘 solver 的平面布局是对称的：

```text
window y=2.37764 width=1.12
left_curtain_panel y=1.42424 width=0.7168
right_curtain_panel y=3.33104 width=0.7168
left_gap=0.035 right_gap=0.035
tightness=tight
```

但最终渲染不对称，因为左右两个 Trellis 窗帘资产的局部轴不一致：

```text
left_curtain_panel raw extents  x=0.328 y=0.666 z=0.066
left local_footprint_long_axis=y
left local_thin_axis=z
left target_scale=[2.184, 0.0526, 29.131]

right_curtain_panel raw extents x=1.000 y=0.713 z=0.178
right local_footprint_long_axis=x
right local_thin_axis=z
right target_scale=[0.717, 0.0491, 11.730]
```

Blender 组装脚本当前逻辑是：

1. 先应用 `asset_axis_to_z` 和 `asset_local_yaw_offset_degrees`。
2. 读取变换后的 raw bbox。
3. 直接把 local X/Y/Z 分别缩放到 plan 的 `width/length/height`。
4. 最后只用 `yaw + footprint_yaw_offset_degrees` 放到世界。

因此 solver 里的同一个 `width=0.7168` 并不保证两个 mesh 在视觉上有同样的 curtain tangent span。左窗帘 raw 长轴在 local Y，却被压到 scene `length=0.035`；右窗帘 raw 长轴在 local X，才被映射到 scene `width=0.7168`。两侧虽然中心和 bbox 数值对称，褶皱方向和可见面积已经不对称。

`wall_asset_axis_repair_report.json` 里 `fix_count=0`，说明这一步没有发现或修正 curtain panel 的局部轴错配。`fine_spatial_order_report.json` 也只验证了左右 gap/center/span，因此漏过了最终 mesh 视觉不对称。

### 修复方向

门：

- 当前门不是简单的“贴墙轴错了”，而是 fallback 视觉模型太弱。
- 需要改 parametric door fallback：增加可见面板 relief、门框、把手/铰链对比，并把可见正面轻微偏到墙内侧，避免斜视角只看到边。
- 还需要新增 door visual readability QA，不能只看 effective yaw。

窗帘：

- 不能只靠中心/gap solver 判断成功。
- 最稳的是给窗帘簇使用同一个 procedural/mirrored curtain panel asset，保证左右 local X=墙切向宽度、local Y=厚度、local Z=高度。
- 如果继续用 Trellis panel，则必须在 asset registry 后新增 curtain semantic-axis normalization：对每个 panel 判断 raw 长轴/薄轴/竖轴并设置 `asset_local_yaw_offset_degrees` 或直接重导出规范化 mesh。
- final acceptance 需要增加 mesh-level symmetry check：左右 panel 在世界切向可见宽度、世界高度、墙面法线厚度、顶部/底部 z 都应在容差内，而不是只看 plan 里的 `dimensions`。

## 2026-07-06 进一步修正：门诊断与窗帘 fallback

### 门诊断

为验证门是否是“方向错 + 强行压扁”导致，而不是单纯 fallback 白板问题，渲染了同一个 `closet_double_door` 在相同 scene plan transform 下的两类资产：

- Trellis 原始备份：`/home/xy/SAGE/diagnostics/door_axis_probe_20260706/trellis_original_yaws/closet_double_door/`
- 当前场景嵌入资产：`/home/xy/SAGE/diagnostics/door_axis_probe_20260706/embedded_current_yaws/closet_double_door/`
- 对比图：`/home/xy/SAGE/diagnostics/door_axis_probe_20260706/door_yaw_comparison_sheet.png`

结论：

- 用户怀疑是合理的。Trellis 原始门在 yaw 0/180 下几乎只读到边，yaw 90/270 才能看到门面。
- Trellis 原始门即使在能看到门面的 yaw 下，上下也有横杆/零件异常，不是一个干净的门板资产。
- 当前 parametric fallback 比 Trellis 规整，但最终视角仍会读到边和杆状细节；这说明门的问题包含两个部分：原始 Trellis 资产方向/几何不稳定，以及门的 pose/readability QA 只检查 effective yaw，没有检查“当前相机下门面是否可读”。

后续门修复不能只说“白板太弱”，还要加一个 door visual readability check：在估计相机或局部门视角下，门的可见面板面积必须足够大，否则尝试 yaw/footprint/front offset 组合或改用更可读的 procedural door。

### 窗帘修正

先加入了 `curtain_asset_axis_normalization_report`：

- 模块位置：`sage/scripts/run_tree_sage_scene.py`
- 报告输出：`curtain_asset_axis_normalization_report.json`
- 目标：对 curtain panel 自动选择 `asset_axis_to_z` 和 `asset_local_yaw_offset_degrees`，使 raw mesh 在 Blender 缩放前满足：
  - local X = 窗帘横向宽度
  - local Y = 墙面法线薄厚
  - local Z = 垂直高度

在 v2 旧资产上离线验证得到：

```text
left_curtain_panel:  axis_to_z 2 -> 1, local_yaw 0
right_curtain_panel: axis_to_z 2 -> 0, local_yaw 90
```

但进一步渲染发现：仅靠轴规范化还不够。Trellis 生成的 curtain mesh 本身不是稳定的“单片连续窗帘面”，右侧会出现条状碎片，仍然不能保证左右视觉一致。

因此又加入了通用 procedural curtain panel fallback：

- source：`tree_sage_generic_curtain_panel_parametric_v1`
- 默认开启开关：`SAGE_PARAMETRIC_CURTAIN_PANEL_FALLBACK=1`
- 写入逻辑：`write_parametric_asset` 支持 generic curtain panel，自动清除 Trellis 轴元数据，设置 `asset_axis_to_z=2`、`asset_local_yaw_offset_degrees=0`
- fallback 逻辑：paired wall curtain panel 默认使用 procedural/mirrored panel fallback，保证左右复用同一几何语义

诊断验证路径：

- 只做轴修复渲染：`/home/xy/SAGE/diagnostics/curtain_axis_probe_20260706/render_curtain_axis_fixed_front_high.png`
- procedural 窗帘渲染：`/home/xy/SAGE/diagnostics/curtain_parametric_probe_20260706/render_parametric_curtains_front_high.png`

结论：窗帘应以 procedural/mirrored panel 作为默认稳定 fallback；单纯依赖 Trellis panel + axis repair 仍不够稳。
