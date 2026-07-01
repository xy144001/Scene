# TreeSAGE Flow2 整体流程说明

这份文档用于向导师说明：我们的系统不是把一张图直接丢给一个模型得到 3D 场景，而是一个多阶段、可检查、可回退、可插入人工约束的 scene reconstruction pipeline。每个模块都会把自己的判断写成结构化中间结果，后续模块继续读取这些结果并修正场景。

核心目标是：从一张 reference image 生成一个房间 3D 场景，使物体类别、数量、纹理、朝向、尺度、支撑关系、墙面关系、前后左右上下关系尽量和 reference 一致。

当前主入口：

- `sage/scripts/run_tree_sage_scene.py`
- `sage/server/trellis2_flux_bridge_server.py`

当前推荐资产生成路径：

- image2 生成逐物体正面源图。
- TRELLIS.2 `pipeline_type=512` 将源图生成 GLB。
- GLB 导出默认不使用 WebP 纹理压缩，避免颜色偏移。

## 1. 一句话总流程

Flow2 的主流程可以概括成：

```text
reference image + prompt + optional scene graph + optional human constraints
  -> 清洗/补全 scene graph
  -> 绑定 reference 中的实例 bbox 和视觉证据
  -> 构建 support tree 和 branch execution plan
  -> 生成或复用每个物体的 TRELLIS.2 资产
  -> 根据 reference 估计 pose / scale / wall attachment
  -> Stage 1 粗布局
  -> Stage 2 紧凑化、支撑和碰撞修复
  -> Stage 3 细致空间排序和必要的 scale 修正
  -> 窗户窗帘等特殊结构 solver
  -> Blender 组装、渲染反馈、物理/全局验证
  -> final scene GLB + reports
```

其中最重要的思想是：前面的模块不直接追求最终完美布局，而是先产出“足够合理的中间场景”；后面的模块在这个中间场景上逐步加入更细的约束。

## 2. 运行时的核心数据结构如何演化

整个流程里主要有四类结构不断被补充：

1. `scene_graph`
   - 描述房间、物体、类别、初始尺寸、支撑关系、reference bbox、语义标签。
   - 它回答“场景里有什么”和“它们大概是什么关系”。

2. `support_tree`
   - 从 scene graph 转换出来的树状支撑结构。
   - 它回答“谁支撑谁”“哪些物体应该一起处理”。

3. `scene_plan`
   - 最终布局计划。
   - 每个物体会有 `x/y/z/yaw/dimensions/support_id/placement_type` 等可执行信息。
   - 它回答“每个物体在 3D 房间里具体放在哪里”。

4. `asset_registry`
   - 记录每个物体对应的 GLB、asset source、bbox、清理结果、质量检查结果。
   - 它回答“每个物体用哪个 3D 资产渲染”。

模块之间不是松散并列关系，而是按以下方式传递信息：

```text
scene_graph
  -> support_tree / scene_hypergraph
  -> branch_execution_plan
  -> scene_plan
  -> asset_registry + cleaned assets
  -> Blender final scene
```

reference 相关信息会贯穿全程：

```text
reference image
  -> reference_instance_map / depth / spatial orders
  -> scale prior / pose prior / fine spatial constraints
  -> render feedback
```

人工约束不是单独摆放物体，而是进入同一套约束表示：

```text
human constraints
  -> bbox projection overlap / edge alignment / ordering constraints
  -> fine spatial order repair
  -> scene_plan updates
```

## 3. Phase 0：准备输入

### 3.1 输入内容

一次完整运行通常包含：

- reference image：房间最终视觉目标。
- prompt：告诉 agent 任务边界，尤其是“只重建静态室内场景，软装尽量合入主物体”。
- scene graph：可选；复现实验时建议固定，减少 agent 重新识别带来的随机性。
- human constraints：可选；用于补充 agent 不稳定的精细关系。
- image2 source images：每个物体一张孤立正面图，用于 TRELLIS.2 生成资产。

卧室例子中，输入位于：

- `examples/bedroom_0610_113657/reference_0610_113657.png`
- `examples/bedroom_0610_113657/prompt.txt`
- `examples/bedroom_0610_113657/scene_graph_augmented_curtains_ceiling_raw_input.json`
- `examples/bedroom_0610_113657/human_constraints_manual_bbox_v1.json`
- `examples/bedroom_0610_113657/source_images/`

### 3.2 为什么要分成这些输入

reference image 负责视觉事实；prompt 负责任务边界；scene graph 负责对象 ID 和复现实验稳定性；source images 负责资产纹理；human constraints 负责弥补当前自动视觉判断不稳定的细节。

如果只用一张图直接让模型生成，错误无法定位。现在每类输入都有对应报告，出问题时可以知道是识别错、资产错、尺度错、排序错，还是最终渲染错。

## 4. Phase 1：建立干净的 scene graph

### 4.1 运行顺序

主流程开始后先写入 `selected_prompt.txt`，然后进入 scene graph 阶段：

1. 如果传了 `--scene-graph-file`，读取该文件。
2. 如果没有传，则由 agent 根据 prompt 和 reference image 生成初始 scene graph。
3. 对 scene graph 做输入保护和清洗。
4. 删除不该作为输入的旧 run metadata。
5. 修正软装、床品、窗台、窗框等容易被错误拆分的物体。

### 4.2 这个阶段怎么起作用

这个阶段不是布局，而是把“有什么物体”定下来。

例如卧室里，床的枕头、被子、绿色毯子不应该作为独立刚体分别摆放，而应该作为床资产的一部分。这个规则在 scene graph 清洗阶段生效，否则后续 support tree 会出现许多没有真实支撑意义的小物体，TRELLIS.2 也会为它们单独生成资产，最终场景会拥挤且不稳定。

### 4.3 输出

关键报告：

- `initial_scene_graph_raw.json`
- `initial_scene_graph_sanitized_input.json`
- `scene_graph_input_guard_report.json`
- `scene_graph_input_sanitize_report.json`
- `soft_layout_detail_policy_report.json`
- `scene_graph.json`

### 4.4 对后续的影响

后续所有模块都依赖 `scene_graph.objects` 中的 object ID。如果这里的 ID、类别、支撑关系错了，后面即使用很强的布局 solver 也只能修局部问题。

典型影响：

- object ID 决定 source image 文件名匹配。
- category 决定 asset prompt、scale prior、component policy。
- support relation 决定 support tree。
- wall relation 决定墙面吸附和 yaw。

## 5. Phase 2：房间尺度、坐标系和材质 grounding

### 5.1 运行顺序

scene graph 清洗完成后，流程会先处理房间本身：

1. 确定 room width / length / height。
2. 判断 reference 图像横轴应该对应世界坐标的哪条轴。
3. 根据 reference 采样墙面和地面基础颜色。

### 5.2 为什么这个阶段必须在布局前

如果房间长宽比或轴向错了，后面所有 bbox 到世界坐标的映射都会错。比如 reference 中横向展开的是房间宽边，但程序把它映射到短边，床、柜子、窗户都会被压缩或放错墙。

因此这个阶段先固定世界坐标系，后续所有 `x/y`、wall id、front/back 判断都基于这里的决定。

### 5.3 输出

关键报告：

- `room_size_grounding_report.json`
- `room_axis_grounding_report.json`
- `wall_material_plan_report.json`
- `floor_material_sampled_texture.png`

### 5.4 对后续的影响

这个阶段会影响：

- 墙面物体贴哪面墙。
- reference bbox 横向/纵向如何映射到世界坐标。
- Stage 1 粗布局的初始坐标。
- Stage 3 细致排序里 `x/y/z` 轴分别代表什么。

## 6. Phase 3：Reference grounding，把图中实例绑定到场景物体

### 6.1 运行顺序

房间坐标定好后，系统开始读 reference image：

1. 为每个 scene graph object 找 reference 中的可见实例。
2. 记录 bbox、label、描述、置信度、是否和同类物体混淆。
3. 可选运行 reference depth，为 bbox 增加前后深度证据。
4. 生成 reference view condition，用来判断这张图适合从哪些轴解释前后左右。

### 6.2 这个阶段怎么起作用

它把“图里的床”绑定到 `queen_bed`，把“左边的床头柜”绑定到 `left_nightstand`。后续所有排序和尺度判断都依赖这个绑定。

对于重复物体，比如左右两个床头柜，grounding 会保留 ambiguity 信息，避免系统把两个同类物体合并成一个，或者左右互换。

### 6.3 输出

关键报告：

- `reference_instance_map.json`
- `reference_alignment_report.json`
- `reference_view_condition_report.json`
- `reference_depth_report.json`

### 6.4 对后续的影响

这个阶段的 bbox 会直接用于：

- 粗略左右/前后排序。
- 物体相对尺度估计。
- 细致 bbox 投影关系。
- 渲染结果和 reference 的最终对比。

如果这里 bbox 绑定错了，后面会出现系统看似执行了排序，但排序目标本身就是错的。

## 7. Phase 4：构建 support tree 和执行分支

### 7.1 运行顺序

reference grounding 后，系统从 scene graph 构建结构化执行计划：

1. 抽取支撑边，例如 `lamp on nightstand`、`painting attached_to wall`。
2. 构建 `support_tree`。
3. 构建 `scene_hypergraph`，记录组合关系和跨物体约束。
4. 生成 `branch_execution_plan`，决定先处理哪些分支。

### 7.2 这个阶段怎么起作用

它把 flat object list 变成可局部处理的结构。

执行顺序一般是：

1. 墙面分支，例如画、窗户、门、窗帘。
2. 靠墙大型家具，例如床、衣柜、dresser。
3. 中心或自由地面家具，例如地毯、桌子。
4. 支撑在父物体上的小物体，例如台灯、植物、书、闹钟。

这样做的原因是：墙和大型家具决定房间骨架；小物体必须跟随父物体。如果先摆小物体，再移动父物体，小物体会漂移。

### 7.3 输出

关键报告：

- `support_tree.json`
- `scene_hypergraph.json`
- `scene_hypergraph_validation_report.json`
- `branch_execution_plan.json`
- `branch_summaries.json`

### 7.4 对后续的影响

support tree 会决定：

- 哪些物体一起进入分支布局。
- 父物体移动时，子物体是否需要同步更新。
- 支撑面检测和 tabletop packing 如何执行。
- MuJoCo 验证时 place_id 如何设置。

## 8. Phase 5：资产生成和资产质量检查

### 8.1 运行顺序

在对象列表和 ID 稳定后，系统为每个物体准备 3D 资产：

1. 根据 object ID 从 `--asset-source-image-dir` 找 image2 source image。
2. 如果 source image 缺失，按配置决定报错或 fallback。
3. 把 source image 发给 TRELLIS.2 bridge。
4. TRELLIS.2 生成 GLB。
5. 清理地面碎片、bbox 外碎片和明显噪声。
6. 建立 `asset_registry`。
7. 根据 component policy 检查资产是否是合理整体。

### 8.2 这个阶段怎么起作用

资产生成只负责物体外观和几何，不负责最终摆放。它输出的资产 bbox 和 metadata 会被后续 scale、pose 和布局模块使用。

我们之前遇到的颜色问题就在这个阶段定位：

- source image 颜色正常。
- TRELLIS.2 生成后某些 GLB 颜色偏绿或偏红。
- 检查发现和 GLB 内 WebP texture export 有关。
- 修正为 no-WebP export 后颜色恢复。

因此目前 TRELLIS.2 bridge 默认：

```text
glb_webp = false
```

并推荐：

```bash
--pipeline-type 512 --trellis-preprocess-image --texture-size 512 --decimation-target 500000
```

### 8.3 输出

关键报告和目录：

- `asset_source_report.json`
- `assets_trellis2/`
- `assets_trellis2_cleaned/`
- `asset_registry.json`
- `asset_cleanup_report.json`
- `asset_component_policy_report.json`
- `component_policy_regeneration_report.json`

### 8.4 对后续的影响

资产 bbox 会影响：

- 物体真实宽长高。
- 贴墙时哪个面是背面。
- 支撑面高度。
- 碰撞检测。
- Stage 3 发现关系无解时是否需要改 scale。

如果资产本身颜色、朝向或几何错了，layout 模块不应该硬修。正确定位方式是回到 source image 或 TRELLIS.2 参数。

## 9. Phase 6：Pose 和 scale 先验

### 9.1 运行顺序

资产准备好后，系统开始决定物体在世界中的朝向和尺寸：

1. 根据 category 和 reference 判断 expected pose。
2. 判断资产 canonical front。
3. 对靠墙物体设置背面贴墙、正面朝房间。
4. 根据 reference bbox、类别常识和资产 metadata 估计 scale。
5. 对父子关系中的子物体刷新相对位置和高度。

### 9.2 这个阶段怎么起作用

它解决的是“物体该多大、面向哪”的问题。

例如：

- 床的床头应该贴后墙，床身向房间前方延伸。
- 床头柜抽屉面应该朝外，而不是朝墙。
- 门应该是贴墙平面，门板正面朝房间。
- 台灯高度应该和床头区域关系合理。

### 9.3 输出

关键报告：

- `pose_expectation_report.json`
- `reference_instance_pose_grounding_report.json`
- `asset_canonical_front_report.json`
- `back_to_wall_asset_local_yaw_repair_report.json`
- `reference_scale_prior_report.json`
- `object_scale_prior_report.json`
- `supported_child_scale_refresh_report.json`

### 9.4 对后续的影响

这个阶段给 Stage 1 提供初始尺寸和朝向。如果床的前后长度太短，后面即使移动床中心，也很难满足“床外边缘和门外边缘接近”这类边缘关系。因此 Stage 3 还允许在必要时回头触发 scale refiner。

## 10. Phase 7：Stage 1 粗布局

### 10.1 运行顺序

Stage 1 是第一次真正把物体放进 3D 房间：

1. 根据 support tree 的 branch 顺序处理物体。
2. 根据 wall relation 把墙面物体吸附到墙上。
3. 根据 reference bbox center 做粗略左右/前后排序。
4. 根据 reference depth 和 view condition 辅助判断深度。
5. 根据高度排序修正大型墙面/高物体的高度范围。
6. 产出一个大致合理但还不精细的 `scene_plan`。

### 10.2 这个阶段怎么起作用

Stage 1 的任务不是最终对齐，而是把场景从“物体列表”变成“基本像 reference 的粗布局”。

它会尽量保证：

- 床在后墙中间。
- 左右床头柜在床两边。
- 衣柜靠右墙。
- 窗户窗帘在左墙。
- 画在床上方或左墙相应位置。
- 门在右侧墙面附近。

### 10.3 输出

关键报告：

- `branch_candidates.json`
- `incremental_branch_report.json`
- `spatial_order_report.json`
- `scene_plan.json`

### 10.4 为什么不能只靠 Stage 1

早期问题是 Stage 1 主要基于中心点排序。中心点正确不代表物体的前端、后端、外边缘正确。

例如：

- 左墙画和左侧 dresser 的中心深度可能不同，但它们在 reference 中沿墙面深度投影应该相交。
- 床中心位置正确，但床前后长度太短，导致床外边缘无法和门外边缘接近。
- 窗帘左右中心看似合理，但整体簇太散，影响左墙其它物体的深度关系。

因此 Stage 1 只提供可修的初始场景，不能作为最终结果。

## 11. Phase 8：Stage 2 紧凑化、支撑和碰撞修复

### 11.1 运行顺序

Stage 2 在 Stage 1 的基础上处理局部物理和紧凑性：

1. 建立每个父物体的 support surface。
2. 把桌面小物体投放到父物体表面。
3. 对同一父物体上的多个小物体做 packing。
4. 修复物体间明显碰撞。
5. 修复地毯 underlay、靠墙家具和墙体间距。
6. 做全局 aggregate collision 检查。

### 11.2 这个阶段怎么起作用

Stage 2 让场景变成“物理上和支撑关系上基本成立”。这是 Stage 3 能工作的前提。

如果没有 Stage 2，Stage 3 会在一个很松散或碰撞很多的场景上处理精细排序，容易出现两个问题：

- 为了满足细致关系，移动步长过大。
- 细致约束和碰撞/支撑冲突，导致 solver 无解。

### 11.3 输出

关键报告：

- `support_surface_registry.json`
- `support_surface_application_report.json`
- `parent_packing_report.json`
- `tabletop_sibling_scale_packing_report.json`
- `aggregate_collision_report.json`
- `repair_report.json`

### 11.4 对后续的影响

Stage 2 会把父子关系稳定下来。后续如果 Stage 3 移动父物体，子物体也必须随父物体更新。我们之前看到“左侧柜子被修了深度，但上面的植物/书还很靠里”，本质就是父子同步和 supported-child refresh 没处理好。

## 12. Phase 9：Stage 3 细致空间排序

### 12.1 运行顺序

Stage 3 是 Flow2 相比早期版本最重要的升级。它在 Stage 1/2 产出的粗布局上继续修：

1. 读取 reference grounding 的 bbox。
2. 读取 Stage 1 的粗略排序。
3. 读取 human constraints 和 agent 识别的细致关系。
4. 对每个物体在某个轴上的 bbox 前端/后端/投影进行比较。
5. 如果 scene 中对应关系不满足，先尝试移动。
6. 如果移动无解或需要过大移动，再尝试有限 scale 修正。
7. 修完后重新检查碰撞、支撑和约束是否仍成立。

### 12.2 这个阶段怎么起作用

早期只看物体中心，例如 `A.center_y < B.center_y`。但真实 reference 中很多关系是边缘或投影关系：

- `A` 的后端可能在 `B` 后端之前。
- `A` 的前端可能和 `B` 的前端接近。
- 两个物体在某个轴上的投影应该相交。
- 墙上物体的上沿应该比另一个物体上沿高。

所以 Stage 3 不再只问“谁中心更靠前”，而是问：

```text
物体 A 在该轴上的 min/max 和物体 B 的 min/max / projection overlap 是否符合 reference？
```

### 12.3 人工约束如何进入 Stage 3

人工约束不会直接写死坐标，而是写成标准关系。例如：

```json
{
  "left_unit_id": "left_dresser",
  "right_unit_id": "left_wall_botanical_art",
  "axis": "y",
  "wall_id": "wall_west",
  "target_scene_overlap": 0.03
}
```

这表示：左侧 dresser 和左墙 botanical art 在 side-wall 深度方向的 bbox 投影应有重叠。solver 会根据当前 scene bbox 判断是否满足，不满足则移动或必要时修 scale。

### 12.4 输出

关键报告：

- `fine_spatial_order_report.json`
- `spatial_order_repair_report.json`
- `spatial_relation_repair_report.json`
- `floor_storage_front_repair_report.json`
- `final_layout_polish_report.json`

### 12.5 对最终效果的影响

Stage 3 负责解决这些“粗布局看起来差不多，但对照 reference 仍不对”的问题：

- 左墙画和左侧 dresser 的深度投影不该隔很远。
- 门外边缘和床外边缘在深度轴上应接近。
- 床顶和台灯高度应接近。
- 右侧柜子的上沿应高于门上沿，且接近窗帘簇上沿。

如果 Stage 3 报告里约束没被识别或没被应用，最终图就会看起来“布局大体对，但细节关系不对”。

## 13. Phase 10：特殊结构 solver

### 13.1 为什么需要特殊 solver

有些物体不是普通独立物体，而是强结构组合。最典型的是窗户窗帘簇：

```text
左窗帘 + 窗户 + 右窗帘 + 窗帘杆
```

如果把它们当普通墙面物体分别排序，常见失败是：

- 左右窗帘不对称。
- 窗户不在中间。
- 窗帘过度散开。
- 窗帘簇变宽后挤压左墙其它物体，导致 dresser 或 wall art 深度关系异常。

### 13.2 窗户窗帘簇 solver 如何起作用

当前 solver 的规则：

1. 固定顺序：左窗帘、窗户、右窗帘。
2. 强制左右窗帘对称。
3. 窗户位于中间。
4. 根据 reference 判断 tight / medium / loose 三档紧密程度。
5. 把窗户窗帘作为一个 functional cluster 参与和其它物体的关系判断。

对于当前卧室 reference，判断为 tight，所以窗帘应贴近窗户，整体簇不应过宽。

### 13.3 它在整体流程里的位置

这个 solver 不是替代 Stage 3，而是嵌入 Stage 3 和 final polish 中：

```text
Stage 1 先放出粗位置
  -> Stage 2 保证不碰撞和支撑正确
  -> Stage 3 处理普通细致关系
  -> 窗户窗帘 solver 强制修复局部组合结构
  -> 再回到全局检查，确保修窗帘没有破坏其它约束
```

### 13.4 对最终效果的影响

窗帘簇紧凑后，左墙画可以向 reference 中更靠内的位置放，左侧 dresser 也不需要被错误拉长来满足投影关系。因此它会间接影响整个左墙布局。

## 14. Phase 11：Blender 组装、渲染反馈和全局验证

### 14.1 运行顺序

布局和资产都准备好后，系统进入最终验证：

1. Blender 根据 `scene_plan.json` 和 `assets_trellis2_cleaned/` 组装场景。
2. 导出 `scene_tree_sage_flow2.glb`。
3. 渲染 topdown 和 front-high 视角。
4. 将 render 与 reference 拼接对比。
5. final render feedback agent 检查明显错位、朝向和尺度问题。
6. global validator 检查碰撞、墙面关系、整体 reference alignment。
7. 可选 MuJoCo proxy 检查物理稳定性。

### 14.2 输出

最终关键产物：

- `scene_tree_sage_flow2.glb`
- `scene_plan.json`
- `preview_topdown.png`
- `render_est_front_high_fine_spatial_order.png`
- `reference_vs_render_est_front_high_fine_spatial_order.png`
- `global_validator_report.json`
- `mujoco_check.json`
- `run_summary.json`

### 14.3 这个阶段怎么起作用

前面的报告多是结构化数值判断，但最终用户看到的是 render。渲染反馈用于发现“结构化检查没报错但视觉上明显不对”的问题，例如：

- 柜子朝向反了。
- 床头柜正面没朝外。
- 墙上画高度看起来不对。
- 窗帘簇不符合 reference 的视觉紧密程度。

这个阶段不会凭空重建场景，它会把问题反馈到 pose、scale、fine order 或特殊 solver 中。

## 15. 以卧室例子说明整个流程如何串起来

以 `ChatGPT Image 2026年6月10日 11_36_57.png` 这张卧室图为例，系统实际在做：

1. 输入 reference，确认它是卧室，而不是 office preset。
2. 固定 scene graph，包含床、左右床头柜、台灯、衣柜、门、左窗、窗帘、dresser、墙画、地毯等。
3. 清洗掉不应独立出现的软装，把枕头、被子、绿色毯子并入床资产。
4. 绑定每个物体的 reference bbox，例如 `queen_bed` 对应中央床，`left_dresser` 对应左墙柜子。
5. 构建 support tree：台灯在床头柜上，植物/书在柜子上，画/门/窗户/窗帘挂墙。
6. 用 image2 source images 生成每个物体 GLB。
7. 用 no-WebP TRELLIS.2 导出保证颜色尽量不漂。
8. Stage 1 先把床放到后墙，衣柜放右边，窗户窗帘放左墙。
9. Stage 2 把台灯、植物、书等放回对应支撑面，并修碰撞。
10. Stage 3 检查更细关系，例如左墙画和 dresser 的 side-wall 深度投影、门外边缘和床外边缘、床顶和台灯高度。
11. 窗户窗帘 solver 把左窗帘、窗户、右窗帘修成 tight symmetric cluster。
12. Blender 渲染最终图，与 reference 拼接检查。

这也是为什么我们现在区分“无人工约束版”和“人工约束版”：

- 无人工约束版用来验证 agent 和自动规则能做到哪里。
- 人工约束版把我们明确观察到、但 agent 暂时不稳定的关系写成标准约束，用来达到更接近 reference 的结果。

## 16. 每个阶段失败时应该怎么定位

### 16.1 物体数量或类别错

先查：

- `scene_graph.json`
- `semantic_agent_report.json`
- `scene_graph_input_sanitize_report.json`

不要先查 layout。物体清单错了，布局阶段无法真正修复。

### 16.2 物体纹理或颜色错

先查：

- `asset_source_report.json`
- source image 本身
- TRELLIS.2 metadata 中的 `glb_webp`
- `asset_registry.json`

颜色错通常是 source image 或 TRELLIS.2 导出问题，不是 layout 问题。

### 16.3 物体朝向错

先查：

- `asset_canonical_front_report.json`
- `pose_expectation_report.json`
- `back_to_wall_asset_local_yaw_repair_report.json`
- final render feedback report

如果 source image 正面本身就错，pose solver 很难完全救回来。

### 16.4 大布局错

先查：

- `room_axis_grounding_report.json`
- `spatial_order_report.json`
- `branch_execution_plan.json`
- `incremental_branch_report.json`

大布局错通常发生在坐标系、墙归属、粗排序或 branch 顺序。

### 16.5 细致关系错

先查：

- `fine_spatial_order_report.json`
- `spatial_relation_repair_report.json`
- human constraints 是否加载
- bbox projection overlap 是否被应用

如果 report 里没有相应约束，说明系统没有识别这条细致关系。如果识别了但没修好，通常是 scale 无解或碰撞/支撑限制阻止移动。

### 16.6 父物体动了，子物体没跟上

先查：

- `support_tree.json`
- `support_surface_application_report.json`
- `supported_child_scale_refresh_report.json`
- `tabletop_sibling_scale_packing_report.json`

这类问题说明父子同步或支撑面刷新还不完整。

### 16.7 窗帘窗户簇错

先查：

- window curtain cluster solver 相关报告。
- `fine_spatial_order_report.json`
- final render 对比图。

不要把窗帘当普通物体分别移动，应该优先让专门 solver 修局部结构。

## 17. 当前流程的关键创新点

相对于“一步到位生成场景”的方法，当前 Flow2 的关键点是：

1. 把 reference image 的证据结构化，生成 bbox、depth、pose、scale、spatial constraints。
2. 用 support tree 组织场景，让父子物体和墙面物体分支处理。
3. 用多阶段布局，从粗到细逐步收紧约束。
4. Stage 3 不再只看中心点，而是看 bbox 端点和投影关系。
5. 人工约束可以作为标准模块输入，而不是写死在代码里。
6. 对窗户窗帘等强结构组合使用专门 solver。
7. 资产生成和布局解耦，纹理问题回到 image2/TRELLIS.2，空间问题回到 layout solver。
8. 每个阶段都有报告，便于定位失败原因并沉淀经验。

## 18. 导师展示时建议强调的主线

可以按下面这条线讲：

1. 我们先把一张 reference 图转成结构化 scene graph 和 reference grounding。
2. 再把 flat object list 变成 support tree，让物体按支撑关系分支处理。
3. 资产不是直接从 prompt 生成，而是 image2 先生成逐物体参考图，再给 TRELLIS.2 生成 GLB，这样纹理更可控。
4. 布局不是一步完成，而是三阶段：
   - Stage 1 做粗布局。
   - Stage 2 做支撑、紧凑和碰撞。
   - Stage 3 做 bbox 端点、投影、边缘对齐等细致关系。
5. 对 agent 不稳定的细致关系，我们支持人工约束输入，并将其转成标准 solver 约束。
6. 对窗帘窗户这种组合结构，我们使用专门 solver，而不是普通物体排序。
7. 最后用 Blender 渲染和全局验证检查结果，所有中间过程都有 report 可追踪。

这条主线能说明：我们的系统是一个可解释、可调试、可复现的闭环流程，而不是单次模型调用。

