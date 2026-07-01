# TreeSAGE Flow 2 整体流程文档

本文档总结当前我们实现和验证过的 TreeSAGE Flow 2 场景生成流程，方便与其他人讨论系统设计、模块边界、当前能力和待改进点。

## 1. 背景与目标

原始流程可以理解为 Flow 1：从 prompt 解析出一批物体，然后直接做整体布局、生成资产、组装场景。这种方式在物体数量少、关系简单时可用，但在复杂场景中容易出现几个问题：

1. 多物体之间缺少显式父子/支撑结构，桌面物体、墙面物体、地面物体容易混在同一层处理。
2. 多个相似物体难以和 reference 图中的具体实例对应，例如一圈椅子、多个窗户、多个装饰画。
3. 位置、朝向、尺寸比例的错误很难局部修复，经常一个错误会影响全场景。
4. 资产生成质量不稳定，尤其是墙面平面物体容易被 Trellis2 生成成碎片状 GLB。

Flow 2 的目标是：以 prompt 和对应的 Flux reference 图为输入，构建支撑树和分支执行计划，每次只处理一个结构分支，逐步布局、验证、修复、冻结已经通过的分支，最后做全局验证和场景组装。

核心思想：

- 用 `support tree` 表示真实支撑关系，而不是只依赖 flat scene graph。
- 用 reference 图做实例级 grounding，明确每个场景物体对应图中哪个物体。
- 先处理墙面/贴墙/大物体，再处理自由地面物体，再处理桌面小物体。
- 分支内部局部验证，分支之间全局验证。
- 对每个资产单独做质量、component policy、pose、scale、bbox 和碰撞检查。

## 2. 输入与输出

### 2.1 输入

当前 Flow 2 的标准输入包括：

1. `prompt`
   - 完整场景描述。
   - 最好使用完整 prompt，而不是简略版，否则 reference 图包含的信息和 planner 看到的信息会不一致。

2. `flux_image`
   - 由完整 prompt 生成的 reference 图。
   - 这是后续 grounding、空间排序、pose 审查、比例验证的重要依据。

3. 可选 `scene_graph`
   - 如果已有官方或前置模块生成的 scene graph，可以直接传入。
   - 如果没有，则由 planner 从 prompt 解析生成。

4. 可选 `room_layout`
   - 如果有官方 layout 或前置模块输出的房间结构文件，优先读取其中的 `rooms[0].dimensions`。
   - 如果没有结构文件，则从 prompt 中解析显式尺寸，例如 `5m x 7m`。
   - 这一步用于避免 scene graph agent 把房间长宽比压错，导致 reference bbox 到世界坐标的映射整体变形。
   - 还会根据 reference 图横纵比例判断世界坐标轴是否需要交换，避免把 reference 中的横向长边压到短边上。

5. 资产目录
   - 可以完全新生成。
   - 也可以复用上一版合格资产，只对不合格资产重新生成或 fallback。

### 2.2 输出

一次完整运行会输出：

1. `scene_tree_sage_flow2.glb`
   - 最终组装的 3D 场景。

2. `scene_plan.json`
   - 最终布局后的场景计划，包括每个物体的位置、尺寸、朝向、支撑关系。

3. `support_tree.json`
   - 从 scene graph 转换出的支撑树。

4. `branch_execution_plan.json`
   - 分支处理顺序和每个分支的执行信息。

5. `reference_instance_map.json`
   - 每个场景物体和 reference 图中实例的对应关系。

6. 关键验证报告：
   - `asset_registry.json`
   - `asset_component_policy_report.json`
   - `component_policy_regeneration_report.json`
   - `room_size_grounding_report.json`
   - `room_axis_grounding_report.json`
   - `spatial_order_report.json`
   - `spatial_order_repair_report.json`
   - `pose_review_report.json`
   - `wall_asset_axis_repair_report.json`
   - `aggregate_collision_report.json`
   - `mujoco_check.json`
   - `global_validator_report.json`

7. 辅助图片：
   - `preview_topdown.png`
   - `reference_instance_overlay.png`
   - `reference_instance_crops/`

## 3. 总体架构

Flow 2 可以分成三层：

### 3.1 Planner 层

Planner 接收 prompt、reference 图和 scene graph，负责：

1. 解析物体列表、类别、尺寸、支撑关系。
2. 构建 support tree。
3. 判断哪些物体是：
   - 地面根分支。
   - 桌面/柜面等子分支。
   - 只贴墙、不落地的墙面分支。
   - 靠墙但落地的大物体分支。
4. 结合 reference 图，决定分支处理顺序。
5. 给每个分支生成候选布局和约束。

排序策略大致是：

1. 最先处理只吸附在墙上的物体，例如画、窗户、钟、墙面装饰。
2. 然后处理靠墙的大型地面分支，例如书架、柜子。
3. 再处理房间中心的大型地面分支，例如会议桌、沙发组。
4. 最后处理依附在父物体上的小物体，例如桌上的书、杯子。

### 3.2 Executor 层

Executor 每次只处理 planner 选中的一个分支。它负责：

1. 在当前冻结场景中摆放该分支。
2. 对分支内部物体做局部布局。
3. 检查分支与墙壁、地面、父物体的关系是否正确。
4. 检查分支内部物体的大小比例、前后左右顺序、pose 和碰撞。
5. 如果错误可修复，就局部调整；如果不可修复，就把错误返回 planner 或资产模块。

重要原则：

- 已通过验证的旧分支会被冻结。
- 当前分支不能破坏已经冻结的分支。
- 桌面物体应该跟桌子属于同一个分支，一轮内一起处理。
- 墙上物体单独作为墙面分支处理，不应该混入地面分支。

### 3.3 Global Validator 层

全局验证器在每个分支通过局部验证后运行，负责：

1. 检查所有分支之间是否存在碰撞。
2. 检查分支之间的左右/前后关系是否符合 reference 图。
3. 检查分支之间的大小比例是否合理。
4. 检查整体 reference alignment。
5. 调用 MuJoCo 做物理稳定性检查。

如果全局验证失败，会回退到 Executor，并给出错误信息，例如：

- 哪两个分支碰撞。
- 哪组物体左右顺序错误。
- 哪个物体贴错墙。
- 哪个物体尺寸比例明显异常。
- 哪个物体在 MuJoCo 中不稳定。

## 4. 详细执行流程

### 4.1 读取 prompt 和 reference 图

流程从完整 prompt 和 Flux reference 图开始。reference 图必须尽量由同一份完整 prompt 生成，否则 planner 和视觉 grounding 会看到不同信息，容易导致关系判断错误。

当前使用方式：

- prompt 来自 `selected_prompt.txt`。
- reference 图来自官方或 Flux 输出，例如 `preview_0.png`。
- scene graph 可以从旧版本复用，也可以重新生成。

### 4.2 构建或读取 scene graph

scene graph 描述物体、类别、尺寸、关系。这里需要区分两类边：

1. 支撑边：
   - `mug on table`
   - `painting attached_to wall`
   - `books on table`
   - 这些边会进入 support tree。

2. 非支撑约束边：
   - `left_of`
   - `right_of`
   - `in_front_of`
   - `near`
   - `against wall`
   - 这些边不会变成父子关系，而是进入 cross constraints 或验证规则。

### 4.3 房间尺寸与轴向 grounding

scene graph 进入 planner 前会先做房间尺寸判断，保证后续所有 bbox 映射、墙面位置、碰撞检查和相机对齐使用同一套 room scale。

优先级：

1. 如果传入官方 layout 或结构化 layout 文件，使用 `rooms[0].dimensions`。
2. 否则从完整 prompt、scene graph description、`created_from_text` 中解析显式尺寸，例如 `5m x 7m`。
3. 如果没有任何显式尺寸，才保留 scene graph agent 输出的 room 尺寸。

输出：

- `room_size_grounding_report.json`
- `scene_graph["_room_size_grounding"]`
- `scene_plan["_flow2"]["room_size_grounding"]`

这个模块会记录修正前后尺寸、候选来源、采用来源和 warning。例如当前 Moroccan conference 场景中，旧 scene graph 给出 `5m x 6m`，但官方 layout 和 prompt 都是 `5m x 7m`，因此会把 `length` 从 `6.0` 修正到 `7.0`。

尺寸修正后还会做轴向 grounding：

1. 如果 reference 图是横向构图，但 grounded room 的长轴在 `length`，则可以把世界布局轴交换为 `width=7, length=5`。
2. 如果 reference 图和房间轴向已经一致，则保持原轴向。
3. 该步骤不改变房间面积，只决定 `image horizontal` 应该映射到世界 `x/width` 的哪条物理长边。

输出：

- `room_axis_grounding_report.json`
- `scene_graph["_room_axis_grounding"]`
- `scene_plan["_flow2"]["room_axis_grounding"]`

这个模块解决的是“数值尺寸正确但 reference 映射方向错”的问题。例如 prompt/官方尺寸是 `5m x 7m`，但 reference 图横向展开的是 7m 长边时，如果仍然把图像横轴映射到 `width=5`，家具会被挤在短边上，看起来像长宽反了。

### 4.4 构建 support tree

support tree 是 Flow 2 的核心结构。根节点通常包括：

- `floor`
- `wall_north`
- `wall_south`
- `wall_west`
- `wall_east`

典型结构：

```text
floor
  central_conference_table
    table_books
    table_mug
  bookshelf_right
  sofa_seat_01
  sofa_seat_02
wall_north
  arched_window_left
  arched_window_right
  wall_clock_back
wall_west
  wall_art_left
wall_east
  wall_art_right
```

这样可以保证：

- 桌面物体不会被当成地面物体。
- 墙面物体不会被错误悬空在房间中。
- 每个分支有明确父节点和局部坐标约束。

### 4.5 Reference instance grounding

这是为了解决“多个相似物体无法对应”的问题。

Agent 或 grounding 模块会参考 reference 图，给每个物体建立实例对应：

- `sofa_seat_01` 对应图中左前椅子。
- `sofa_seat_02` 对应图中右前椅子。
- `arched_window_left` 对应后墙左窗。
- `arched_window_right` 对应后墙右窗。

输出：

- `reference_instance_map.json`
- `reference_instance_overlay.png`
- `reference_instance_crops/`

这个映射后续会被空间排序、pose 审查、比例验证复用。没有这一步时，左右/前后排序很容易失效，因为系统不知道“当前这个椅子”对应 reference 图里的哪把椅子。

### 4.6 分支排序与执行计划

Planner 根据 support tree 和 reference 图生成分支顺序。

优先级：

1. 只贴墙、不落地的墙面物体。
2. 靠墙的大型落地物体。
3. 房间中心的大型物体。
4. 小型地面物体。
5. 桌面/柜面子物体。

每个分支会记录：

- parent support id。
- 是否靠墙。
- 靠近哪面墙。
- 是否必须贴墙。
- 是否有子物体。
- 分支内部物体比例。
- 与其他分支的 cross constraints。

### 4.7 分支候选布局

Executor 会为当前分支生成多个候选布局，并根据以下评分选择：

1. 与父节点关系是否正确。
2. 与 reference 图中的位置是否相似。
3. 左右/前后关系是否合理。
4. 是否贴墙或贴父物体。
5. 是否和已冻结分支碰撞。
6. 是否符合尺寸比例。

如果候选布局失败，会尝试局部移动、旋转或调整尺寸。

### 4.8 空间排序检查与修复

空间排序分两类：

1. 左右关系排序。
2. 前后关系排序。

流程：

1. 根据 reference instance map，把图中同一组物体按从左到右排序。
2. 把当前 3D 布局投影到同一视角，得到当前排序。
3. 对比 reference 排序和当前排序。
4. 如果不一致，执行局部位置修复。

这个模块必须依赖实例对应关系，否则多个椅子会无法判断哪一把应该去哪。

### 4.9 Pose 审查与修复

位置大致正确后，pose agent 会逐个物体审查朝向。

当前重点：

- 椅子前后方向是否正确。
- 桌子的长轴/短轴是否反了。
- 窗户、画、钟是否贴合墙面。
- 墙面物体的厚度轴是否朝墙。
- 小物体在桌面上的朝向是否自然。

Pose 审查原则：

1. 先确定位置和 support relation。
2. 再检查 pose。
3. Pose 正确后再做 scale。
4. 最后做碰撞和物理验证。

输出：

- `pose_expectation_report.json`
- `pose_review_report.json`
- `wall_asset_axis_repair_report.json`

### 4.10 支撑面 registry 与支撑面应用

系统会为可承载物体的对象建立支撑面信息，例如：

- table top。
- cabinet top。
- floor。
- wall plane。

然后把子物体吸附到正确支撑面上。

典型规则：

- `table_books` 和 `table_mug` 必须在 `central_conference_table` 的 top surface。
- `wall_art_left` 必须 attached to 对应墙面。
- `wall_clock_back` 必须 attached to 后墙。

输出：

- `support_surface_registry.json`
- `support_surface_application_report.json`

### 4.11 资产生成、复用和清理

资产模块负责给每个物体提供 GLB。

有三种模式：

1. 全部新生成：
   - 对每个物体调用 Trellis2/Flux bridge 生成资产。

2. 部分复用：
   - 合格资产从上一版复用。
   - 缺失或不合格资产重新生成。

3. Procedural fallback：
   - 对 Trellis2 特别容易失败的类别，使用本地几何 fallback。
   - 当前最适合用于墙面平面资产：画、门、窗、钟、面板。

资产清理会处理：

- bbox 外的残片。
- 白底/底座/平台。
- 地面残片。
- disconnected fragments。
- 资产坐标轴归一化。

输出：

- `assets_trellis2/`
- `assets_trellis2_cleaned/`
- `asset_cleanup_report.json`

### 4.12 Asset registry 与 component policy

Asset registry 会扫描每个资产的几何结构，并判断质量。

每个资产会记录：

- 组件数量。
- 最大主组件比例。
- bbox。
- 原始轴和目标轴。
- thin axis。
- scale。
- component policy。
- warnings。
- quality。

Component policy 用于判断一个物体是否应该是单体、主物体带细节、带底座多细节，还是应该拆分成多个物体。

重要 policy：

1. `single_integrated_panel`
   - 适用于画、窗、门、镜子、标牌。
   - 要求一个连续背板或连续主体。
   - 如果生成成很多碎片，应重生或 fallback。

2. `single_main_body_with_parts`
   - 适用于椅子、桌子、柜子等。
   - 允许有细节组件，但必须有清晰主身体。

3. `many_details_on_base`
   - 适用于书架、植物、复杂装饰。
   - 允许很多细节，但必须有 base/frame/主支撑。

4. `set_should_be_split`
   - 如果一个资产实际包含多个逻辑物体，应拆成多个 scene objects。

当前我们认为“是否应该单 component”最好让 agent 结合 reference 和类别判断，而不是固定规则写死。规则脚本只负责几何测量和硬约束验证。

### 4.13 不合格资产重生

如果 asset registry 发现 component policy 失败，会进入重生流程。

标准重生路径：

1. 根据失败原因微调 asset prompt。
2. 调用 Flux/Trellis2 重新生成。
3. 清理重生资产。
4. 重新扫描 asset registry。
5. 如果仍失败，继续下一 pass 或保留原资产并报告。

当前实践：

- Trellis2 对墙面平面物体容易生成碎片。
- 对 `wall_art` 这类 flat panel，procedural fallback 往往比继续随机重生更稳。
- 最新 v13 复用了 v11 合格资产，并用 fallback 替换了墙面不合格资产。

### 4.14 聚合碰撞检测

布局完成后会做 aggregate collision check。

检查内容：

- 同一父节点下的 sibling branches 是否碰撞。
- 桌面子物体之间是否碰撞。
- 地面分支之间是否碰撞。
- 墙面分支之间是否重叠。
- 墙面物体是否穿墙或离墙。

如果发现碰撞：

1. 尝试局部移动当前分支。
2. 尝试调整 yaw。
3. 尝试缩小局部尺度。
4. 如果无法修复，返回 planner/executor。

输出：

- `aggregate_collision_report.json`

### 4.15 MuJoCo 物理检查

当前已接入本地 MuJoCo 兼容检查。

作用：

- 发现物体是否明显不稳定。
- 发现支撑关系是否不合理。
- 估计物体在物理模拟后的位移。

当前判断方式：

- 如果 MuJoCo 返回 success，并且没有 unstable objects，则 `mujoco_ok=true`。
- `max_displacement` 超过阈值会记录 warning，但不直接判死刑。

原因：

- 当前 MuJoCo 使用的是简化 proxy box，不是完整 mesh 物理。
- 一些贴墙物体、大型靠墙物体会产生较大 displacement，但不一定代表最终 GLB 视觉失败。

输出：

- `mujoco_check.json`

### 4.16 Global validator

最终全局验证会汇总：

- aggregate collision。
- reference alignment。
- pose review。
- spatial order。
- spatial relation repair。
- incremental branch execution。
- MuJoCo simulation。

只有这些检查整体通过，才认为场景可用于人工检查或对比。

输出：

- `global_validator_report.json`

### 4.17 Blender 组装

最后用 Blender 把：

- floor。
- walls。
- cleaned assets。
- final scene plan。

组装成最终 GLB。

输出：

- `scene_tree_sage_flow2.glb`

## 5. 当前 v13 结果记录

最新一次完整结果：

```text
/data/xy/SAGE_repro/sage10k_official_compare/flow2_official_moroccan_conference_policy_grounding_v13/scene_tree_sage_flow2.glb
```

这版处理方式：

- 复用 v11 的合格 cleaned assets。
- 对不合格墙面资产使用 procedural fallback：
  - `arched_door_main`
  - `arched_window_left`
  - `arched_window_right`
  - `wall_art_left`
  - `wall_art_right`

验证结果：

- `global_validator_ok=true`
- `aggregate_collision_ok=true`
- `aggregate_conflict_count=0`
- `mujoco_ok=true`
- `component_policy_failed_count=0`
- `component_policy_remaining_failed_ids=[]`

仍需注意：

- MuJoCo 有 displacement warning，最大位移约 `1.7656`，但没有 unstable objects。
- 门和窗仍有 thin-footprint / wall-axis 警告，说明 procedural fallback 可用但还不是最终理想资产方案。
- 当前 reference grounding 虽能覆盖 30 个物体，但 usable count 仍偏低，复杂场景下还需要更强的实例识别。

## 6. Agent 与规则脚本的分工

适合交给 agent 的部分：

1. 从 prompt 和 reference 图判断物体类别、功能和语义。
2. 判断一个物体应该是单体、组合体、还是需要拆分。
3. 判断多个相似物体和 reference 图实例的对应关系。
4. 判断左右/前后排序。
5. 判断 pose 是否符合 reference。
6. 判断分支之间的大小比例是否合理。
7. 给出失败原因和修复建议。

适合规则脚本的部分：

1. bbox、尺寸、坐标、朝向的数值计算。
2. support tree 的确定性遍历。
3. 碰撞检测。
4. MuJoCo 调用。
5. GLB 清理、导出、组装。
6. 报告落盘。

当前系统的设计原则是：agent 做语义判断和视觉判断，脚本做几何执行和可复现验证。

## 7. 当前主要问题

### 7.1 Reference 对齐仍不够强

虽然我们已经加入 reference grounding、spatial order、pose review，但复杂场景中仍可能出现：

- 物体贴错墙。
- 多个相似椅子对应错。
- 尺寸比例和 reference 不一致。
- 只看 prompt 判断时漏掉 reference 中的视觉细节。

后续应增强：

- 更强的 instance grounding。
- 对每个分支单独裁剪 reference 并验证比例。
- 全局分支比例 agent。

### 7.2 Trellis2 墙面资产容易碎

画、门、窗这类平面物体，Trellis2 常生成多个碎片组件，而不是一个连续面板。

当前解决方式：

- component policy 识别失败。
- 重生时加强 prompt。
- 如果仍失败，用 procedural fallback。

后续更好的方案：

- 单独做 flat wall asset generator。
- 直接从 reference crop 生成一张贴图，贴到薄板 mesh 上。
- 对画/窗/门/标牌类资产，不再默认走通用 Trellis2。

### 7.3 Pose 仍需更强的视觉闭环

当前 pose agent 会根据规则和 reference 修正很多朝向，但最理想流程应该是：

1. 当前 scene 按 reference 相机视角渲染。
2. Agent 对比 reference 和 render。
3. 逐个物体输出 pose 修改建议。
4. 脚本应用修改。
5. 重新渲染并循环直到通过。

这会比只看 top-down 或几何规则更可靠。

### 7.4 MuJoCo 目前是 proxy 检查

目前 MuJoCo 用 axis-aligned box proxy，不是完整 mesh collision。

优点：

- 快。
- 可自动集成到流程。
- 可以发现明显不稳定。

缺点：

- 对贴墙物体、复杂形状、大型空心资产不够精确。
- displacement warning 不一定等价于视觉失败。

后续可以接入更完整的物理仿真，但成本更高。

## 8. 建议后续模块

### 8.1 Render-based pose correction agent

输入：

- reference 图。
- 当前 scene 同视角渲染图。
- reference instance map。

输出：

- 每个物体是否需要旋转。
- 应该旋转多少度。
- 是否需要翻转 front/back。
- 是否需要换 wall attachment axis。

### 8.2 Branch-level visual validator

每个分支完成后，单独验证：

- 分支在 reference 中的位置。
- 分支内部比例。
- 分支内部左右/前后关系。
- 分支与墙/父物体关系。

### 8.3 Global branch ratio agent

全局验证时，专门判断：

- 分支之间大小比例。
- 中央大物体是否过大/过小。
- 靠墙家具是否和墙面尺度一致。
- 小物体是否被放大。

### 8.4 Flat wall asset generator

对以下类别走专用生成：

- wall art。
- poster。
- painting。
- mirror。
- window。
- door panel。
- sign。

推荐实现：

- 从 reference crop 或 prompt 生成 2D 图。
- 贴到薄板 mesh 上。
- 自动加 frame/backing。
- 导出单体 GLB。

### 8.5 Stronger asset white-background removal

当前白底问题来自图像生成和 3D 重建两侧：

- Flux/Trellis 输入图可能带白背景、平台或阴影。
- RMBG/threshold cutout 可能没完全去掉。
- Trellis2 可能把背景当成实体重建。

后续可以：

- 使用更强的透明背景/抠图模型。
- 对 flat panel 类不走通用重建。
- 对生成图做 alpha quality 自动重试。
- 对 GLB 进行更强 bbox fragment 清理。

## 9. 一句话版本

TreeSAGE Flow 2 是一个 support-tree guided、reference-grounded、branch-wise incremental 的 3D 场景生成流程：先用 prompt 和 reference 图构建支撑树和实例对应，再按墙面/靠墙/地面/桌面分支逐步布局，每个分支局部验证并冻结，最后通过资产质量、空间关系、pose、碰撞和 MuJoCo 全局验证后，用 Blender 组装成最终 GLB。
