# 行人过街规则与定义说明

## 1. 目标

在不改变车辆缓行主链路的前提下，基于同一套 scene graph 数据补充行人过街统计，用于回答：

1. 当前时段是否存在明显行人过街活动。
2. 当前时段是否达到繁忙或饱和过街状态。

## 2. 数据来源

- 数据输入：每帧 scene graph 的 object_map_triples。
- 主体对象：subject_type 包含 PEDESTRIAN / PERSON / WALKER。

## 3. 过街识别规则

### 3.1 标准过街关系

若 relation 含有 cross（如 crossing、crosses），或属于 walking_across、walk_across、on_crosswalk、in_crosswalk、entering_crosswalk、leaving_crosswalk、traversing_crosswalk，则认为是过街关系候选。

### 3.2 放宽规则（用于提高召回）

若 relation 为 in / on / inside / overlap / intersect，且 object_type 为 CROSSWALK，则同样记为过街活动。

### 3.3 目标约束

- 对标准过街关系，object_type 应属于 CROSSWALK / LANE / JUNCTION / ROAD。
- 对放宽规则，object_type 需包含 CROSSWALK。

## 4. 核心定义

### 4.1 过街活跃个体

第 t 帧过街行人集合记为 A_t。

### 4.2 新增过街事件

为避免同一行人跨帧重复计数：

E_t = A_t - A_(t-1)

其中 |E_t| 为第 t 帧新增过街事件数。

### 4.3 滑动窗口

窗口长度 W（帧）可配置，默认 60，范围 5-5000。

第 t 帧统计窗口为 [t-W+1, t]。

## 5. 统计指标定义

- window_frames：当前统计窗口长度 W。
- crossing_event_count：窗口内新增过街事件总数，sum(|E_i|)。
- crossing_edge_count：窗口内过街关系边总数。
- unique_active_pedestrian_count：窗口内出现过过街活跃状态的唯一个体数，|union(A_i)|。
- unique_event_pedestrian_count：窗口内触发过新增事件的唯一个体数。
- active_crossing_count：当前帧活跃过街个体数，|A_t|。
- active_entities：当前帧活跃过街行人 ID 列表。
- new_crossing_entities：当前帧新增过街行人 ID 列表，即 E_t。
- active_targets：当前帧涉及的过街目标（斑马线/车道/路口等）。

## 6. 滑动窗口计算逻辑

对按时间排序后的记录逐帧处理：

1. 提取当前帧 snapshot（active_entities、targets、edge_count）。
2. 计算 new_event_entities = active_entities - prev_active。
3. 将当前帧写入队列并累加窗口计数。
4. 当队列长度超过 W 时，弹出最老帧并抵消其贡献。
5. 生成当前帧 pedestrian_crossing_summary。

说明：这是固定长度的滚动窗口，不是全局累计。

## 7. 饱和判定规则

阈值：

- busy_threshold（默认 8）
- saturated_threshold（默认 14）

约束：saturated_threshold >= busy_threshold + 1。

判定：

1. crossing_event_count >= saturated_threshold，saturation_level = saturated。
2. crossing_event_count >= busy_threshold 且 < saturated_threshold，saturation_level = busy。
3. crossing_event_count < busy_threshold，saturation_level = normal。

## 8. 阈值自定义与生效方式

前端行人面板支持实时调整：

- 滑动窗口帧数
- 繁忙阈值 busy_threshold
- 饱和阈值 saturated_threshold

后端接口：/api/governance/pedestrian_window

- 入参：window_frames、busy_threshold、saturated_threshold。
- 行为：更新配置后重建治理索引，按时间顺序重算行人统计。
- 返回：更新后的窗口与阈值，便于前端回填显示。

## 9. 输出协议

治理任务 task 中新增 pedestrian_crossing_summary：

- window_frames: int
- crossing_event_count: int
- crossing_edge_count: int
- unique_active_pedestrian_count: int
- unique_event_pedestrian_count: int
- active_crossing_count: int
- active_entities: string[]
- active_targets: string[]
- new_crossing_entities: string[]
- saturation_level: normal | busy | saturated
- thresholds:
  - busy: int
  - saturated: int
- insight: string

## 10. 兼容性与注意事项

- 不改变既有治理主流程接口，只做字段扩展和新增行人接口。
- 旧前端不读取 pedestrian_crossing_summary 时行为不受影响。
- 若历史缓存索引缺少行人摘要，系统会自动补算并落盘。
