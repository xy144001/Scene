# TreeSAGE Flow 2 当前流程与问题总结

本文档总结截至当前版本的 TreeSAGE Flow 2 实现状态、主要模块、最近 Moroccan conference 场景实验结论，以及当前阻碍复杂多物体布局稳定通过的关键问题。

当前结论先放在前面：

1. Flow 2 已经从“整体一次性布局”升级为“支撑树 + 分支布局 + scene hypergraph + 全局验证”的流程。
2. 最近加入的全局 pair 约束是有效的，尤其在 `ratio=0.1`、`min_gap=0.015` 后，右后椅子与中间椅子的深度顺序已经能恢复。
3. v32 仍然没有整体通过，主要原因不是物体 scale 太大或房间太挤，而是 pair repair 和 collision repair 分阶段执行，会互相破坏。
4. 当前 pair 是中心点顺序约束，不是 footprint 完全分离约束；碰撞由另一个模块处理。这导致“pair 满足”和“几何不碰撞”之间没有联合求解。
5. 当前局部 `same_depth/same_column` 约束有过硬风险，尤其是不同类物体在 reference 图中因投影看起来对齐时，会被误当成硬世界坐标约束。

## 1. 当前目标

Flow 2 的目标是处理比原始 SAGE/Flow 1 更复杂的多物体场景。

输入：

- 完整 prompt。
- prompt 对应的 Flux/Flux2 reference 图。
- scene graph，来自官方示例、前置 agent，或已有实验版本。
- 可选资产目录，用于复用已生成合格资产。

输出：

- `scene_tree_sage_flow2.glb`：最终 3D 场景。
- `scene_plan.json`：最终物体位置、尺寸、朝向、支撑关系。
- `support_tree.json`：支撑树。
- `scene_hypergraph.json`：场景高阶约束。
- 多个验证和修复报告，例如 collision、MuJoCo、pose、reference alignment、global validator 等。

当前主要实验场景是 Moroccan conference room，30 个物体，复用 Trellis2 资产，重点调试多椅子、多 pouf、多墙面物体的布局。

## 2. Flow 1 与 Flow 2 的区别

Flow 1 更接近 flat object placement：

- 从 prompt/scene graph 得到物体列表。
- 直接对所有物体做整体布局。
- 生成资产后组装场景。
- 验证器发现错误后做局部修补。

Flow 1 的问题是复杂场景中缺少结构分解：

- 桌面物体、墙面物体、地面大物体容易混在一起处理。
- 多个相似物体很难和 reference 中的具体实例对应。
- 局部错误会影响全局，修复时容易把已经正确的区域调坏。
- 前后/左右排序、pose、scale、贴墙关系缺少统一约束层。

Flow 2 的核心变化：

- 用 support tree 表示真实支撑关系。
- 用 branch 作为执行单位，而不是单个物体。
- 用 scene hypergraph 表示局部组、全局 pair、墙面组、桌面组等高阶关系。
- 用分支级和全局级验证器反复修复。
- 引入 reference 图中的 bbox/order/pose 作为布局约束来源。

## 3. 当前整体流程

### 3.1 输入读取

流程读取：

- `prompt-file`
- `scene-graph-file`
- `reuse-asset-dir`
- 可选 `flux-image`

当前 v30-v32 全局 pair 实验中，为了隔离布局逻辑，运行时关闭了多个 agent：

- `--no-reference-grounding-agent`
- `--no-spatial-order-agent`
- `--no-pose-agent`
- `--no-render-pose-feedback-agent`
- `--no-semantic-agent`
- `--no-relation-agent`

因此 v30-v32 的 reference order 不是 agent 现场看图判断的，而是从 scene graph/scene plan 中已有的 `image_bbox` 字段推导出来的。

这点非常重要：如果 `image_bbox` 或实例对应关系错了，pair 的“正确答案”也会错。

### 3.2 房间尺寸与轴向 grounding

当前流程会处理房间尺寸和轴向：

- prompt/官方描述中 Moroccan conference 场景是 `5m x 7m`。
- 当前实际 room 设置为 `width=7.0, length=5.0`，这是为了让 reference 图横向长边对应世界 x 轴。
- `room_axis_grounding_report.json` 会记录是否发生了轴交换。

这个模块解决的是之前长宽反、房间变窄、物体挤在一起的问题。

当前仍需注意：

- 如果没有 reference 图，流程可能复用上一版 axis grounding。
- 这对复现实验可用，但最终流程应该尽量带 reference 图，让轴向 grounding 能独立判断。

### 3.3 Scene graph 到 support tree

scene graph 中的关系分两类：

- 支撑关系：`on`、`inside`、`attached_to`、`against_wall` 等，用于构建 support tree。
- 空间关系：`left_of`、`right_of`、`in_front_of`、`behind`、`near`、`facing` 等，进入 cross constraints 或 hypergraph。

support tree 包含虚拟节点：

- `floor`
- `wall_north`
- `wall_south`
- `wall_west`
- `wall_east`

这样可以统一处理：

- 地面物体。
- 靠墙但落地的物体。
- 只贴墙的物体。
- 桌面/柜面小物体。

### 3.4 分支规划与执行

planner 根据支撑树和场景关系选择分支顺序：

1. 优先处理墙面吸附物体。
2. 再处理靠墙的大型地面物体。
3. 再处理核心地面分支，例如会议桌、椅子组。
4. 最后处理依附在父物体上的小物体。

原则：

- 桌面物体应该和桌子在一个分支内一起处理。
- 墙面物体单独作为墙面分支处理。
- 已经验证通过的分支应尽量冻结。

当前还没有完全实现强冻结机制，后续全局修复仍可能移动已布局物体。

### 3.5 资产复用与质量检查

当前流程会读取或复用 Trellis2 资产，并生成：

- `asset_registry.json`
- `asset_component_policy_report.json`
- `component_policy_regeneration_report.json`

已知资产问题：

- 有些物体会被拆成大量 components，例如部分椅子、pouf、bookshelf。
- 墙面平面资产，例如门、窗、画、钟，容易生成成厚物体或多碎片。
- 部分资产存在白底/残片问题。
- 当前 v32 复用资产后，物理碰撞已能通过，但资产视觉质量仍不是最终状态。

资产问题会影响最终观感和局部碰撞，但 v32 的主要失败不是资产 scale 或物理碰撞。

### 3.6 Pose 与墙面修正

当前已有或尝试过的 pose 相关模块包括：

- pose expectation。
- pose review。
- group pose repair。
- wall asset axis repair。
- render pose feedback，当前 v30-v32 实验关闭。

已知问题：

- 椅子前后左右朝向仍不稳定。
- 门/窗的 wall pose 和 axis 仍容易错。
- 墙面平面物体需要 `axis/pose` 自动修正。
- pose 的最终正确性最好通过和 reference 同视角渲染对比来审查。

当前 v32 主要调的是位置 pair，不是 pose。

## 4. Scene Hypergraph 当前内容

scene hypergraph 是 Flow 2 当前最重要的约束层。

当前 Moroccan conference v32 中有 7 个 factor：

- `reference_axis_pair_constraints` x 2
- `facing_group` x 2
- `radial_group` x 1
- `same_wall_ordered_group` x 1
- `tabletop_cluster` x 1

### 4.1 Local reference axis pair

局部 pair 用于局部 cluster，例如右侧 pouf/椅子区域。

它会包含：

- strict pair：`left_of`、`in_front_of`
- same-axis pair：`same_column`、`same_depth`

问题：

- `same_column/same_depth` 来自 2D bbox 视觉对齐。
- 这种对齐可能是透视投影造成的，不一定代表世界坐标中必须同列/同深度。
- 对不同类物体，例如 pouf 和椅子，作为硬约束风险较高。

### 4.2 Global reference axis pair

最近新增的全局 pair factor：

```text
factor_id = global_reference_axis_pairs_floor
type = reference_axis_pair_constraints
scope = global_floor_reference
```

它选择 floor/root 物体，排除：

- 墙面吸附物体。
- 桌面小物体。
- support parent 下的子物体。
- floor covering。
- hanging object。

它只生成 strict pair：

- `left_of`
- `in_front_of`

全局 pair 不生成 `same_depth/same_column`，这是为了避免全局范围的视觉投影对齐变成硬世界约束。

当前默认阈值：

```text
REFERENCE_SAME_AXIS_CENTER_RATIO = 0.1
GLOBAL_REFERENCE_PAIR_MIN_IMAGE_GAP = 0.015
SPATIAL_ORDER_MIN_AXIS_GAP = 0.035
```

约束生成逻辑：

```text
same_axis_threshold = min(REFERENCE_SAME_AXIS_MAX_IMAGE_GAP,
                          REFERENCE_SAME_AXIS_CENTER_RATIO * min(bbox_size_a, bbox_size_b))

strong_enough = ref_gap >= max(GLOBAL_REFERENCE_PAIR_MIN_IMAGE_GAP,
                               same_axis_threshold * 1.2)
```

注意：

- `ref_gap` 是 reference 图 bbox 中心差。
- bbox 坐标是归一化图像坐标。
- y 方向中，image y 越大表示越靠前，image y 越小表示越靠后。

## 5. Pair 语义

当前 pair 是中心点排序约束，不是完整几何分离约束。

### 5.1 前后关系

`subject in_front_of target` 的验证是：

```text
target.y - subject.y >= required_gap
```

其中 `required_gap` 至少为：

```text
SPATIAL_ORDER_MIN_AXIS_GAP = 0.035m
```

这表示：

- 只要求 subject 的中心点在 target 中心点前方。
- 不要求 subject 的后边界完全在 target 的前边界前。

### 5.2 左右关系

`subject left_of target` 的验证是：

```text
target.x - subject.x >= required_gap
```

同样是中心点关系，不是 footprint 完全在左侧。

### 5.3 Pair 与碰撞的关系

pair 只负责排序，碰撞由以下模块处理：

- aggregate collision report。
- repair report。
- MuJoCo check。

因此当前存在一个结构性问题：

```text
pair repair 让中心顺序正确
collision repair 又为了清碰撞移动物体
移动后 pair 又坏掉
```

这正是 v32 没过的核心原因之一。

## 6. v30-v32 实验结论

### 6.1 v30：全局 pair 初版

输出目录：

```text
/data/xy/SAGE_repro/sage10k_official_compare/flow2_official_moroccan_conference_global_pairs_v30
```

参数：

```text
REFERENCE_SAME_AXIS_CENTER_RATIO = 0.35
GLOBAL_REFERENCE_PAIR_MIN_IMAGE_GAP = 0.045
```

结果：

- 全局 pair：295 条。
- 前后 pair：145 条。
- 左右 pair：150 条。
- hypergraph validation：通过。
- collision：通过。
- MuJoCo：通过。

问题：

- reference 中右后两把椅子应该比中间两把更深。
- v30 中这类浅深度差没有进入硬 pair。
- 原因是阈值太保守，gap `0.0355-0.0490` 被认为不够强。

结论：

- v30 是通过版，但对细微 depth ordering 不够敏感。

### 6.2 v31：ratio 改为 0.1

输出目录：

```text
/data/xy/SAGE_repro/sage10k_official_compare/flow2_official_moroccan_conference_global_pairs_ratio01_v31
```

参数：

```text
REFERENCE_SAME_AXIS_CENTER_RATIO = 0.1
GLOBAL_REFERENCE_PAIR_MIN_IMAGE_GAP = 0.045
```

结果：

- 全局 pair：301 条。
- 前后 pair：151 条。
- 左右 pair：150 条。
- hypergraph validation：失败。
- global pair 剩余 8 个违例。
- collision/MuJoCo 最终可过。

问题：

- ratio 降低后，一些浅 depth pair 被纳入。
- 但 `GLOBAL_REFERENCE_PAIR_MIN_IMAGE_GAP=0.045` 仍是主要下限。
- 右后椅子的深度顺序仍没有完全恢复。

结论：

- 单独降低 ratio 不够，固定 min gap 仍然太保守。

### 6.3 v32：ratio 0.1 + min gap 0.015

输出目录：

```text
/data/xy/SAGE_repro/sage10k_official_compare/flow2_official_moroccan_conference_global_pairs_ratio01_mingap015_v32
```

参数：

```text
REFERENCE_SAME_AXIS_CENTER_RATIO = 0.1
GLOBAL_REFERENCE_PAIR_MIN_IMAGE_GAP = 0.015
```

结果：

- 全局 pair：326 条。
- 前后 pair：162 条。
- 左右 pair：164 条。
- 右后椅子深度顺序恢复：

```text
scene deepest/back first:
sofa_seat_08, sofa_seat_09, sofa_seat_02, sofa_seat_03

reference deepest/back first:
sofa_seat_08, sofa_seat_09, sofa_seat_02, sofa_seat_03
```

仍未通过：

- `scene_hypergraph_validation_ok=false`
- `final_layout_polish_ok=false`
- `global_validator_ok=false`
- global pair 剩余 9 个违例。
- local `reference_axis_pairs_blue_pouf_01_blue_pouf_02` 剩余 5 个违例。
- collision 通过。
- MuJoCo 通过。

核心残留问题：

- `blue_pouf_01` 被 collision repair 推到太靠前的位置。
- 按 global pair，它应该在：

```text
required blue_pouf_01 y: 1.8275 到 3.06
current blue_pouf_01 y: 0.45125
```

这个区间本身可行，因此不是没空间。

结论：

- `min_gap=0.015` 对恢复椅子深度有效。
- 但全局 pair 变密后，当前分阶段 repair 不能稳定同时满足 pair 和 collision。

## 7. 当前失败原因分析

### 7.1 不是主要 scale 问题

v32 最终：

```text
aggregate_collision_ok = true
aggregate_conflict_count = 0
mujoco_ok = true
```

所以当前失败不是“物体太大导致物理摆不下”。

当然，scale 仍可能影响 repair 难度，因为 footprint 越大，pair 中心排序越容易和碰撞修复冲突。但它不是 v32 的主因。

### 7.2 Pair 与 collision 分开修

当前流程大致是：

1. hypergraph repair 修 pair。
2. collision repair 清碰撞。
3. final polish 重复上述过程。

问题是 collision repair 不一定保护 high-priority pair。

v32 中明确出现：

```text
blue_pouf_01 away from sofa_seat_10 by [0.89, -0.35, 0.0]
```

这个动作清掉了碰撞，但把 `blue_pouf_01` 推到了过前位置，导致全局 pair 失败。

### 7.3 Center pair 不等于 footprint clearance

pair 要求中心排序：

```text
target.y - subject.y >= 0.035
```

但真实物体 footprint 可能是：

```text
blue_pouf_01: 0.75 x 0.7425
sofa_seat_10: 0.8 x 0.8
```

中心差 `0.035m` 对这种物体几乎没有几何意义，两个物体仍然可能重叠。

然后 collision repair 必须做大位移，大位移又破坏 pair。

### 7.4 Local same-axis 约束过硬

v32 的局部 factor：

```text
reference_axis_pairs_blue_pouf_01_blue_pouf_02
```

包含：

- `blue_pouf_01 same_column sofa_seat_08`
- `blue_pouf_01 same_depth sofa_seat_10`
- `blue_pouf_02 same_column sofa_seat_09`
- `sofa_seat_09 same_column sofa_seat_10`

这些来自 reference bbox 中很小的中心差。

问题：

- 这种对齐可能只是透视投影。
- 不同类物体之间的 same-depth/same-column 不应该默认 hard。
- same-axis 更适合作为 soft preference 或局部视觉提示。

### 7.5 Agent 未参与当前 v30-v32 的 reference 判断

当前 v30-v32 实验关闭了 reference grounding 和 spatial order agent。

因此：

- 没有 agent 直接看 reference 图判断深度排序。
- 没有显式人工级实例匹配审查。
- pair 正确性依赖 scene graph 中已有 `image_bbox`。

这对 isolating layout bug 有帮助，但不是最终完整 Flow 2。

最终流程应重新启用：

- reference grounding agent。
- spatial order agent。
- render pose feedback agent。
- pose review agent。

并且要把 agent 判断和 bbox 规则结果交叉验证。

## 8. 当前模块清单与状态

| 模块 | 当前状态 | 主要问题 |
|---|---|---|
| prompt/scene graph 读取 | 可用 | 简略 prompt 会导致 reference 与 planner 信息不一致 |
| room size grounding | 可用 | 无 reference 时可能复用旧轴向 |
| support tree | 可用 | 冻结语义还不够强 |
| branch execution | 可用 | 后续全局修复仍可能破坏已处理分支 |
| asset registry | 可用 | 部分资产 component 过碎 |
| component policy | 可用 | 是否单 component 仍需 agent 辅助泛化 |
| wall asset axis repair | 可用 | 门/窗/画等仍需更强平面资产处理 |
| pose review | 部分可用 | 当前 v30-v32 实验关闭；椅子朝向仍不稳 |
| reference grounding | 可用但本轮关闭 | 最终必须启用 |
| spatial order agent | 可用但本轮关闭 | 当前 pair 主要来自 bbox |
| scene hypergraph | 可用 | 局部 same-axis 硬约束风险高 |
| global pair | 新增可用 | 阈值有效，但 repair 解不稳 |
| collision repair | 可用 | 会破坏 pair |
| MuJoCo check | 可用 | 当前只验证稳定性，不负责布局优化 |
| final polish | 可用但不稳 | pair/collision 分阶段循环不收敛 |

## 9. 当前最重要的问题

### 问题 1：pair/collision 缺少联合求解

这是当前最高优先级问题。

现象：

- pair 修好了。
- collision repair 把物体推开。
- pair 又坏了。
- final polish 多轮后 score 不下降。

建议：

- pair repair 的候选移动要同时计算 collision score。
- collision repair 的候选移动要同时计算 hypergraph pair score。
- 最终选择 joint score 最优移动，而不是先修一个再修另一个。

### 问题 2：strict pair 的 required gap 太弱

当前 strict pair 只要求中心差 `0.035m`。

这对排序够用，但对几何不碰撞不够。

建议：

- pair 验证仍可用中心顺序。
- pair repair 应该计算 footprint-aware clearance。
- 对大物体，移动目标应考虑半宽/半深和安全 margin。

例如：

```text
subject in_front_of target
repair target should prefer:
subject_back_edge + margin <= target_front_edge
```

而不是只满足：

```text
subject_center + 0.035 <= target_center
```

### 问题 3：same-depth/same-column 应改为 soft 或 class-aware

当前全局 pair 已经不生成 same-axis，这是正确方向。

但局部 cluster 仍会生成 same-axis 硬约束。

建议：

- same-axis 只对同类重复物体 hard，例如多把椅子、多幅墙画。
- 对不同类物体，例如 pouf 和 chair，默认 soft。
- 对墙面同组或同一 support surface，可保留更强 same-axis。

### 问题 4：reference grounding 与实例对应需要重新启用

多椅子场景最容易出错的是实例对应。

最终流程不能只依赖 scene graph 中已有 `image_bbox`。

建议：

- 启用 reference grounding agent。
- 让 agent 明确输出每个物体对应 reference 中哪个实例。
- 对重复物体输出 instance map 和可视化 overlay。
- pair 生成前检查 object-id 与 reference bbox 是否可信。

### 问题 5：pose 仍是独立风险

当前全局 pair 主要修位置，不修朝向。

已知问题：

- 椅子朝向可能仍反。
- 门/窗贴墙 axis 可能仍错。
- 书架/柜子靠墙方向需要单独验证。

建议：

- 在位置基本正确后，加入 render pose feedback。
- 用 reference 同视角渲染图对比 pose。
- 每个 pose-sensitive 物体逐个审查 yaw/front axis。

## 10. 短期建议路线

建议不要继续单纯调低 ratio/min gap。v32 已经说明：

- 降低阈值可以恢复细微椅子深度。
- 但约束变密后，repair 不会自动变好。

优先级建议：

1. 实现 joint pair-collision repair。
   - 每个移动候选同时评分 pair violation 和 collision violation。
   - collision repair 不允许无代价破坏 high-priority pair。

2. 降级局部 same-axis。
   - `same_depth/same_column` 默认 soft。
   - 同类重复物体或同墙面组才 hard。

3. 增加 footprint-aware repair target。
   - strict pair 的修复目标不要只用中心点 `0.035m`。
   - 大物体要用 footprint 边界和 clearance。

4. 加入冲突诊断报告。
   - 对每个失败 object 输出 feasible interval。
   - 输出是谁把它推出可行区间。
   - 输出 pair repair 与 collision repair 的来回破坏链。

5. 重新启用 reference grounding/spatial order agent 做完整流程测试。
   - bbox 规则给初始 pair。
   - agent 负责确认多实例对应和歧义 pair。

## 11. 当前可引用结果文件

v30 通过版：

```text
/data/xy/SAGE_repro/sage10k_official_compare/flow2_official_moroccan_conference_global_pairs_v30
```

v31 ratio=0.1：

```text
/data/xy/SAGE_repro/sage10k_official_compare/flow2_official_moroccan_conference_global_pairs_ratio01_v31
```

v32 ratio=0.1 + min_gap=0.015：

```text
/data/xy/SAGE_repro/sage10k_official_compare/flow2_official_moroccan_conference_global_pairs_ratio01_mingap015_v32
```

v32 对比图：

```text
/data/xy/SAGE_repro/sage10k_official_compare/flow2_official_moroccan_conference_global_pairs_ratio01_mingap015_v32/reference_vs_render_est_front_high_v32.png
```

v32 GLB：

```text
/data/xy/SAGE_repro/sage10k_official_compare/flow2_official_moroccan_conference_global_pairs_ratio01_mingap015_v32/scene_tree_sage_flow2.glb
```

## 12. 总结

目前 Flow 2 的结构方向是对的：

- support tree 能分解复杂场景。
- scene hypergraph 能表达局部组和全局 pair。
- 全局 pair 能明显改善多椅子深度排序。
- MuJoCo 和 aggregate collision 能过滤物理问题。

但当前系统还不是稳定的复杂场景布局器。

主要短板不在单个阈值，也不主要在 scale，而在：

```text
reference pair 目标
+ footprint-aware collision
+ repair search
没有形成同一个联合优化问题。
```

下一步如果要提升通过率，应优先把 pair repair 和 collision repair 合并成 joint repair，再处理局部 same-axis 软硬分级。这样比继续调 ratio/min gap 更可能让复杂场景稳定通过。
