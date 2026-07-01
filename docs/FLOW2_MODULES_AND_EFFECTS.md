# TreeSAGE Flow2 模块化流程说明

本文档按模块梳理当前 TreeSAGE Flow2 的完整流程。重点不是记录一次实验命令，而是说明每个模块输入什么、怎么起效、输出什么、常见失败信号是什么。师弟接手时应先读本文，再看 `TREE_SAGE_FLOW2_PIPELINE.md` 的长版设计背景。

## 0. 总体目标

Flow2 的目标是从一张室内 reference image 复原一个可渲染的 3D 静态场景。当前最稳定的路径是：

1. 用 reference image 作为视觉主证据。
2. 用 image2 为每个物体生成单独的正面源图。
3. 用 TRELLIS.2 把逐物体源图转成 GLB 资产。
4. 用 Flow2 的 support tree、reference grounding、粗细空间排序、窗口窗帘簇 solver、碰撞修复和最终渲染反馈来布局。

核心入口：

- `sage/scripts/run_tree_sage_scene.py`
- `sage/server/trellis2_flux_bridge_server.py`
- `examples/bedroom_0610_113657/`

当前推荐资产生成参数：

```bash
--trellis-pipeline-type 512 --trellis-preprocess-image --texture-size 512 --decimation-target 500000
```

TRELLIS.2 bridge 默认使用 no-WebP GLB 导出，避免部分资产颜色偏移。

## 1. 输入层

### 1.1 Reference Image

输入：

- `--flux-image`
- `--pose-reference-image`

作用：

- 作为全流程的视觉真值来源。
- agent 从图里判断房间类型、物体数量、物体 bbox、墙面归属、前后左右上下关系、物体朝向和相对尺度。
- 渲染反馈模块会把最终 render 和 reference 拼图对比。

输出：

- `reference_instance_map.json`
- `reference_alignment_report.json`
- `reference_vs_render_*.png`

失败信号：

- reference 图和 prompt 不一致。
- 图里有大面积遮挡或透视极端，导致左右/深度判断不稳定。
- 后续 `reference_grounding_mapped_count` 明显低于实际物体数。

### 1.2 Prompt

输入：

- `--prompt-file`
- 或 image-only 默认 prompt。

作用：

- 给 agent 一个任务边界：只复原静态室内场景，软装细节尽量并入床/沙发等主资产，不作为独立刚体。
- 对 image-only 场景，prompt 不负责决定物体清单，reference image 才是主证据。

输出：

- `selected_prompt.txt`

失败信号：

- prompt 说的是另一类房间，会误导 agent。
- prompt 把枕头、被子、毯子拆成独立物体，会增加布局和物理验证难度。

### 1.3 Scene Graph

输入：

- `--scene-graph-file` 可选。

作用：

- 固定物体 ID、类别、初始尺寸、支撑关系和部分 reference metadata。
- 对复现实验，传入固定 scene graph 可以减少 agent 每次重新识别物体带来的随机差异。
- 对新图，可以不传，让 semantic/reference agent 生成或补全。

输出：

- `initial_scene_graph_raw.json`
- `initial_scene_graph_sanitized_input.json`
- `scene_graph.json`

失败信号：

- object ID 和 source image 文件名不匹配。
- scene graph 携带旧输出目录里的绝对路径，但目标机器没有这些文件。
- 支撑关系把墙上物体错误挂到 floor，或把桌面物体错误挂到房间。

### 1.4 Image2 Source Images

输入：

- `--asset-source-image-dir`
- `--asset-source-image-required`

作用：

- 对每个物体提供一张孤立正面源图，作为 TRELLIS.2 image-to-3D 输入。
- 这是当前替代 Flux 逐物体生成的主要路径，目的是让资产颜色、纹理和 reference 更接近。

输出：

- `asset_source_report.json`
- `assets_trellis2/*.glb`
- `assets_trellis2_cleaned/*.glb`

失败信号：

- source image 不是目标物体，例如床头柜生成成抽屉柜或方向错。
- source image 颜色已经偏离 reference，TRELLIS.2 后面很难修回来。
- 背景不干净或物体被裁切，导致 TRELLIS.2 生成碎片。

## 2. 可选人工约束层

输入：

- `--human-constraints-file`

当前支持示例：

- `bbox_projection_overlaps`

作用：

- 把人工观察到的关键关系转成标准约束，进入 Flow2 的细致空间修复。
- 主要弥补 agent 难以稳定判断的关系，例如 side-wall 深度投影相交、床和门外边缘近似对齐、画和柜子在侧墙方向投影应相交。

输出：

- 约束被合并进 fine spatial order / bbox projection overlap 相关报告。

失败信号：

- 人工约束 ID 写错，不匹配 scene graph object ID。
- 约束本身和资产尺度无解，solver 会移动或拉伸到异常形态。
- 约束只修父物体，没有同步处理其上小物体，视觉上会出现桌面物体漂移。

原则：

- 无人工约束版用于检验自动化能力。
- 人工约束版用于复现高质量目标结果和沉淀规则。
- 人工约束应尽量写成通用约束类型，而不是在代码里写死某张图的对象。

## 3. 场景图清洗与语义规范化

模块：

- scene graph input guard
- scene graph sanitize
- soft layout detail policy
- integrated bedding/window sill policy

作用：

- 删除旧 run 输出里不该作为输入的中间 metadata。
- 把软装细节合并到主资产，例如枕头、被子、毯子合入床。
- 修正窗台、床品、墙面细节这类容易被错误拆出来的对象。

输出：

- `scene_graph_input_guard_report.json`
- `scene_graph_input_sanitize_report.json`
- `soft_layout_detail_policy_report.json`
- `integrated_bed_bedding_dedupe_report.json`

失败信号：

- 物体数量膨胀，床品/窗台/窗框被拆成许多独立刚体。
- 支撑树里出现没有物理意义的 soft objects。
- 资产生成阶段为软装单独生成 GLB，布局变得拥挤或碰撞。

## 4. 房间 grounding 与坐标系模块

模块：

- room size grounding
- room axis grounding
- wall material plan

作用：

- 确定房间宽、长、高。
- 判断 reference 图横向长边应映射到世界 `x/width` 还是 `y/length`。
- 从 reference 采样墙面和地板基础颜色，避免房间材质完全不匹配。

输出：

- `room_size_grounding_report.json`
- `room_axis_grounding_report.json`
- `wall_material_plan_report.json`
- `floor_material_sampled_texture.png`

失败信号：

- room 长宽反了，床、柜子、窗户投影整体扭曲。
- 所有物体被挤到短边方向。
- 墙面颜色明显不贴近 reference。

## 5. Reference Grounding 模块

作用：

- 为每个 scene graph object 绑定 reference 中的实例 bbox。
- 为后续空间排序、尺度先验、pose 判断、渲染反馈提供视觉依据。

输入：

- reference image
- scene graph object list
- 可选 cached reference metadata

输出：

- `reference_instance_map.json`
- `reference_alignment_report.json`
- `reference_view_condition_report.json`

怎么起效：

- agent 给每个物体分配 reference label 和 bbox。
- 对重复物体，例如左右床头柜，会保留 ambiguity 信息，避免错误合并。
- bbox 参与后续投影、排序和尺度估计。

失败信号：

- 左右同类物体互换，例如左右床头柜反了。
- 墙上画、窗户、门没有 bbox，后续墙面定位会漂。
- bbox 太松，导致尺度和投影关系错误。

## 6. Reference Depth 模块

作用：

- 用单目深度模型为 reference bbox 提供前后深度辅助。
- 对 image 纵深明显的场景，可辅助判断哪个物体更靠前/靠后。

输入：

- reference image
- depth model

输出：

- `reference_depth/depth_map.npy`
- `reference_depth/depth_map.png`
- `reference_depth_report.json`

怎么起效：

- 对每个 bbox 采样深度统计。
- 对大物体可按 slice 采样前端/后端深度。
- 空间排序 agent 和 repair 模块会引用这些前后证据。

失败信号：

- 单目深度把墙面平面和前景家具混淆。
- 对白色门、窗帘、床品这类低纹理对象，深度值可能不可靠。
- 深度模块可作为证据，但不应单独决定所有前后排序。

## 7. Support Tree 与 Hypergraph 模块

作用：

- 把 flat scene graph 转成支撑树。
- 区分 floor branch、wall branch、tabletop branch、functional cluster。
- 决定布局处理顺序和冻结策略。

输出：

- `support_tree.json`
- `scene_hypergraph.json`
- `scene_hypergraph_validation_report.json`
- `branch_execution_plan.json`

怎么起效：

- 墙上物体优先作为 wall branch。
- 靠墙大型家具作为 floor branch anchor。
- 桌面小物体跟随父物体处理，避免父物体移动后子物体不同步。
- functional cluster 用于约束床-床头柜、窗户-窗帘、地毯-床等组合关系。

失败信号：

- 柜子移动了，上面的植物/书没有跟着微调。
- 墙上画被当作 floor object。
- 桌面物体漂浮或嵌入父物体。

## 8. 资产生成模块

模块：

- source image selection
- TRELLIS.2 bridge
- GLB export
- asset cleanup
- component policy check

作用：

- 把逐物体 image2 source image 转成 GLB。
- 修剪地面碎片和明显 bbox 外碎片。
- 检查资产是否符合组件策略，例如床应是一个 coherent assembly，柜子不应碎成很多无关组件。

关键脚本：

- `sage/server/trellis2_flux_bridge_server.py`
- `sage/scripts/clean_asset_bbox_fragments.py`

当前关键设置：

- `pipeline_type=512`
- `texture_size=512`
- `decimation_target=500000`
- `glb_webp=false`

为什么 no-WebP 起效：

- 之前部分 GLB 内 WebP texture 会出现颜色偏移，例如棕黄变棕红、灰色偏绿。
- no-WebP 后 GLB 体积变大一些，但颜色更接近 source image。
- 当前默认以颜色正确为优先。

输出：

- `asset_registry.json`
- `asset_cleanup_report.json`
- `asset_component_policy_report.json`
- `component_policy_regeneration_report.json`

失败信号：

- 资产颜色和 source image 不一致。
- GLB 文件异常大，通常是 texture size 或压缩方式变化。
- 资产朝向不对，例如床头柜不是正面朝外。
- 窗帘、窗户这种薄片物体被生成成厚块或碎片。

## 9. Pose 与 Canonical Front 模块

作用：

- 判断资产的正面、背面、长轴方向。
- 修正床、柜子、门、床头柜等物体的 yaw，使它们面向正确方向。

输出：

- `pose_expectation_report.json`
- `reference_instance_pose_grounding_report.json`
- `asset_canonical_front_report.json`
- `back_to_wall_asset_local_yaw_repair_report.json`
- `bedside_front_pose_report.json`

怎么起效：

- 对靠墙家具，背面贴墙，正面朝房间。
- 对床，床头靠后墙，床身向房间前方延伸。
- 对门，门板贴墙且面板朝房间内。

失败信号：

- 床头柜抽屉朝墙。
- 门平面方向错或嵌墙。
- 资产自身 canonical front 错，后续 yaw 修复只能部分补救。

## 10. 尺度先验模块

模块：

- reference scale prior
- object scale prior
- asset metadata scale prior
- scale prior supported children
- fine spatial order scale refiner

作用：

- 根据 reference bbox、类别常识和资产 metadata 调整物体尺寸。
- 支持在第三阶段发现“位置关系无解”时回头修 scale。

输出：

- `reference_scale_prior_report.json`
- `object_scale_prior_report.json`
- `supported_child_scale_refresh_report.json`
- `scale_prior_supported_child_restore_report.json`

怎么起效：

- 先给每个物体一个合理世界尺寸。
- 如果 bbox 投影关系要求床前后更长、柜子深度更长/更短，scale refiner 可以调整尺寸，而不只是移动中心。
- 父物体 scale 改变后，子物体需要刷新位置和高度。

失败信号：

- 床在深度方向太短，导致床外边缘无法和门或柜子外边缘接近。
- 左侧靠墙柜子被拉得过长，因为窗户窗帘簇不够紧凑。
- 父物体尺寸变了，桌面物体看起来偏里或偏外。

## 11. 布局 Stage 1：粗布局与粗排序

作用：

- 根据支撑树、墙面关系、reference bbox 中心和粗略空间顺序，生成一个可用初始布局。
- 主要处理每个物体在哪面墙、左右大致顺序、前后大致区域、高度大致范围。

输出：

- `branch_candidates.json`
- `incremental_branch_report.json`
- `spatial_order_report.json`

怎么起效：

- 墙面物体贴对应墙。
- 大型 floor furniture 先靠墙或居中放置。
- 粗略空间排序使用 bbox 中心、reference depth 和关系 agent 输出。
- 高度排序用于修正物体 scale 高度，例如窗帘簇和门应属于高物体。

失败信号：

- 左右墙归属错误。
- 画和柜子在侧墙方向完全错开。
- 门、窗帘、柜子高度明显不对。

## 12. 布局 Stage 2：紧凑化、支撑和碰撞修复

作用：

- 在 Stage 1 基础上修复局部碰撞、桌面支撑、父子关系和场景密度。
- 如果场景不做 Stage 2，第三阶段细致排序可能不紧凑，很多关系会无解。

输出：

- `parent_packing_report.json`
- `aggregate_collision_report.json`
- `repair_report.json`
- `support_surface_registry.json`
- `support_surface_application_report.json`
- `tabletop_sibling_scale_packing_report.json`

怎么起效：

- 把桌面小物体投放到父物体可支撑表面。
- 对同一父物体上的多个小物体进行 sibling packing。
- 修复明显碰撞和越界。
- 对地毯等 floor covering 建 underlay 支撑关系。

失败信号：

- 桌面物体悬空、嵌入或互相重叠。
- 全局移动父物体后子物体没跟上。
- 场景太散，第三阶段再修时移动距离过大。

## 13. 布局 Stage 3：细致空间排序

作用：

- 在已有合理布局上，用更细粒度关系修正前后、左右、上下。
- 重点从“中心点排序”升级到“bbox 端点/投影关系”。

关键子模块：

- fine spatial order refiner
- fine spatial order detailed agent
- bbox projection overlap solver
- fine spatial order scale refiner
- floor storage front repair
- final layout polish

输出：

- `fine_spatial_order_report.json`
- `spatial_order_repair_report.json`
- `spatial_relation_repair_report.json`
- `floor_storage_front_repair_report.json`
- `final_layout_polish_report.json`

怎么起效：

- 对每个物体在某个轴上不只看中心，还看 bbox 的前端和后端。
- agent 可判断细致关系，但当前更稳定的是 bbox projection overlap 约束。
- 若两个 reference bbox 在某轴投影应相交，solver 会移动/必要时轻微改 scale，使 scene bbox 也相交。
- 上下方向排序用于维持墙上物体绝对位置，例如窗帘上沿、门上沿、画的位置。

失败信号：

- 左墙画和左靠墙柜子深度投影仍分离。
- 门外边缘和床外边缘应接近但没有接近。
- 床顶和台灯高度关系明显不对。
- solver 把某个物体拉伸到不合理尺寸，说明约束和当前资产尺度冲突。

## 14. 窗户窗帘簇 Solver

作用：

- 专门处理窗户、左右窗帘、窗帘杆这一类强结构组合。
- 这是因为单独把窗帘当普通墙面物体排序，经常会变成左右散开、窗口不居中、簇不紧凑。

当前规则：

- 固定顺序：左窗帘、窗户、右窗帘。
- 左右窗帘对称。
- 窗户在中间。
- 根据 reference 判断 tight / medium / loose 三档紧密程度。
- 对当前卧室 reference，属于 tight。

输出：

- 窗帘/窗户相关修复进入 fine spatial order 和 cluster 报告。

怎么起效：

- 把窗帘簇当整体判断墙面位置。
- 先保证局部结构正确，再参与与左侧柜子、左墙画的深度投影关系。
- 窗帘簇紧凑后，左墙画可以往内挤，左侧柜子不需要被拉得过长。

失败信号：

- 左右窗帘不对称。
- 窗户不在中间。
- 窗帘散开导致左墙画、左 dresser 深度关系变坏。

## 15. 渲染反馈与最终验证

模块：

- Blender assembly
- topdown preview
- final render pose feedback
- global validator
- MuJoCo check

作用：

- 用 Blender 组装场景 GLB。
- 渲染 topdown 和 reference 对比图。
- 检查碰撞、稳定性、墙面关系、整体视觉对齐。

输出：

- `scene_tree_sage_flow2.glb`
- `preview_topdown.png`
- `render_est_front_high_fine_spatial_order.png`
- `reference_vs_render_est_front_high_fine_spatial_order.png`
- `global_validator_report.json`
- `mujoco_check.json`
- `run_summary.json`

怎么起效：

- Blender assembly 把房间、墙、地板、每个 GLB 资产按 `scene_plan.json` 组装。
- 渲染反馈 agent 检查朝向、大小和明显错位。
- MuJoCo proxy 检查物理稳定性，但墙面薄片和软装类对象会有豁免逻辑。

失败信号：

- topdown 看起来关系对，但前视 render 视觉错，通常是高度、朝向或资产 canonical front 问题。
- MuJoCo 失败但视觉正确，可能是薄片墙面物体或软装物体不适合刚体检查。
- render 和 reference 大布局一致但纹理错，通常应回 source image / TRELLIS.2 查，不应在 layout 里修。

## 16. 当前复现建议

复现 `examples/bedroom_0610_113657` 时推荐顺序：

1. 配好 `.env`。
2. 启动 TRELLIS.2 bridge：

```bash
scripts/start_trellis2_bridge_512_no_webp.sh
```

3. 准备 image2 source images：

```bash
scripts/prepare_bedroom_source_images_from_local.sh
```

4. 先跑 smoke test：

```bash
scripts/run_bedroom_0610_113657_plan_only_smoke.sh
```

5. 跑无人工约束版，看自动化能力：

```bash
scripts/run_bedroom_0610_113657_no_manual.sh
```

6. 跑人工约束版，复现当前较好结果：

```bash
scripts/run_bedroom_0610_113657_manual.sh
```

判断是否复现成功，优先看：

- `reference_vs_render_est_front_high_fine_spatial_order.png`
- `fine_spatial_order_report.json`
- `asset_registry.json`
- `run_summary.json`

## 17. 修改流程时的定位方法

如果资产颜色错：

- 先看 source image。
- 再看 TRELLIS.2 GLB export 是否 no-WebP。
- 不要先改 layout。

如果物体朝向错：

- 查 source image 正面是否正确。
- 查 `asset_canonical_front_report.json`。
- 查 `pose_*` 和 `back_to_wall_asset_local_yaw_repair_report.json`。

如果大布局散：

- 查 Stage 1 的 `spatial_order_report.json`。
- 查 Stage 2 的 `parent_packing_report.json` 和 `aggregate_collision_report.json`。
- 不要只在 Stage 3 用大步长硬拉。

如果细致关系错：

- 查 `fine_spatial_order_report.json`。
- 查 bbox projection overlap 约束是否被识别和应用。
- 若移动无解，再查 scale refiner 是否允许修尺寸。

如果窗户窗帘簇错：

- 优先查专门的 window curtain cluster solver。
- 不要把窗帘作为普通独立墙面物体分别排序。

如果人工约束版和无人工版差异很大：

- 说明自动 agent 没能稳定判断这类关系。
- 应考虑把人工约束总结成通用规则或可交互输入，而不是写死到某个 scene。

