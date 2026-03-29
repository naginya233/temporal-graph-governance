# 缓行评分演示文档 / Slowdown Scoring Demo

## 1. 用途 / Purpose

本文件用于快速解释系统如何把 following 结构信号转换为 score，并进一步映射到 high/medium/low。

This document is for presentation and defense scenarios, explaining how following-graph signals are converted into a score and then mapped to high/medium/low.

---

## 2. 评分公式 / Scoring Formula

实现位置：traffic_agent_system/agents/cognitive_agents.py::_score_slowdown

总分由 6 项相加：

1. max_chain 贡献：min(max_chain // 2, 4)
2. convoy_count 贡献：min(convoy_count, 3) * 2
3. merge_cnt 贡献：2 / 1 / 0（merge_cnt >= 2 / ==1 / ==0）
4. cycle_detected：若 True 则 +2
5. max_chain >= 6：额外 +1
6. queue_density >= 1.0：额外 +1

等级映射：

- high: score >= 8
- medium: score >= 4 and < 8
- low: score < 4

### 2.1 缓行类型 vs 缓行等级（异同） / Slowdown Class vs Level

相同点 / Similarity:

- 二者都用于描述当前帧的缓行状态，且都由 following 结构信号驱动。

不同点 / Difference:

1. 缓行等级 (level) 回答“严重程度有多高”

- 取值：high / medium / low。
- 来源：score 阈值映射（score >= 8 为 high，>=4 为 medium，否则 low）。
- 侧重：连续刻度的强弱分层，适合排序与优先级调度。

2. 缓行类型 (class) 回答“属于哪种性质”

- 取值：
	- normal_controlled_queue（正常受控排队）
	- sustained_slowdown（持续缓行）
	- anomalous_slowdown（异常缓行）
- 来源：规则判定（是否有环、是否满足持续结构模式、是否极端异常结构）。
- 侧重：机理解释和治理策略选择（是常规排队、持续拥堵，还是异常互锁）。

组合解读 / Joint Interpretation:

- level 决定“先看谁”（优先级）。
- class 决定“怎么治”（治理动作类型）。

例如：

- medium + sustained_slowdown：中等风险但已持续，应优化配时与疏散。
- high + normal_controlled_queue：强队列但可能仍受控，不应直接判异常。
- medium + anomalous_slowdown：分数未必最高，但结构异常（如环）需要优先排查。

### 2.2 缓行类型分类规则（实现口径） / Class Rules (Implementation)

实现位置：traffic_agent_system/agents/cognitive_agents.py::_classify_slowdown

判定按以下顺序执行（前面的条件命中后直接返回）：

1. anomalous_slowdown（异常缓行）

- 条件 A：cycle_detected = True（following 图存在环）
- 条件 B：极端结构异常同时满足：
	- score >= 10
	- max_chain >= 9
	- convoy_count >= 3
	- merge_cnt >= 3
	- queue_density >= 1.2

2. sustained_slowdown（持续缓行）

- 条件组 A（任一满足即可）：
	- max_chain >= 4
	- convoy_count >= 2
	- merge_cnt >= 2 且 queue_density >= 0.85
	- max_chain >= 3 且 queue_density >= 0.9
- 条件组 B（补充判定）：
	- score >= 6 且 merge_cnt >= 1 且 queue_density >= 0.95

3. normal_controlled_queue（正常受控排队）

- 当以上异常和持续条件均不满足时，判为正常受控排队。

解释建议：

- class 是结构类型判定，不完全等同于分数高低。
- 例如存在环时，即使 score 不是最高，也会优先归入 anomalous_slowdown。
- 因此在汇报中应同时给出 level（强度）和 class（性质）。

---

## 3. 字段解释 / Field Meaning

- max_chain: 最长跟驰链长度（边数）
- convoy_count: 检测到的车队链数量
- merge_cnt: 汇聚节点数（通常 following 图入度 >= 2）
- cycle_detected: following 图中是否存在有向环
- queue_density: following_edges / following_nodes

### 3.1 为什么跟驰边数和跟驰节点数不同？ / Why edge_count +1 != node_count?

实现使用的是有向图，不是一一配对表：

- 节点（node）表示对象实体（车或交通参与者）。
- 边（edge）表示一条有方向的跟驰关系（A -> B，表示 A 跟驰 B）。

因此它们不是 1:1 对应，常见情况如下：

1. 链式队列（A->B->C->D）
	4 个节点，3 条边，edge_count < node_count。

2. 汇聚结构（A->C, B->C）
	3 个节点，2 条边；一个节点可以有多条入边。

3. 复杂分叉/互联结构
	单节点可参与多条入边和出边，edge_count 可以接近甚至超过 node_count。

所以 queue_density = edge_count / node_count 表示“关系密度”，不是“车辆物理密度”。

- 值偏低：关系稀疏，通常更接近自由流或弱队列。
- 值接近或超过 1.0：关系紧密，常对应明显跟驰拥挤或结构复杂化。

---

## 4. 10 个典型场景对照表 / 10 Typical Scenarios

| # | 场景简述 | max_chain | convoy_count | merge_cnt | cycle_detected | queue_density | 公式分解 | 总分 | 等级 |
|---|---|---:|---:|---:|---|---:|---|---:|---|
| 1 | 自由流阶段：车辆之间只有零散跟驰关系，未形成连续队列，也没有汇聚冲突。 | 1 | 0 | 0 | False | 0.30 | 0 + 0 + 0 + 0 + 0 + 0 | 0 | low |
| 2 | 短暂排队：路口前出现一小段单链跟驰（如红灯初期），但影响范围很小。 | 2 | 1 | 0 | False | 0.70 | 1 + 2 + 0 + 0 + 0 + 0 | 3 | low |
| 3 | 轻微汇入干扰：单车队存在且出现 1 个汇聚节点，说明局部并入导致通行效率下降。 | 3 | 1 | 1 | False | 0.95 | 1 + 2 + 1 + 0 + 0 + 0 | 4 | medium |
| 4 | 中等缓行：队列链条延长，同时关系密度超过 1.0，说明跟驰关系已经明显拥挤。 | 4 | 1 | 1 | False | 1.10 | 2 + 2 + 1 + 0 + 0 + 1 | 6 | medium |
| 5 | 长链单源缓行：存在较长队列但主要是单一车队传播，未出现明显多点扩散。 | 6 | 1 | 0 | False | 0.80 | 3 + 2 + 0 + 0 + 1 + 0 | 6 | medium |
| 6 | 多团簇拥堵起势：至少两条车队并行发展，并伴随轻度汇聚，整体进入高风险阈值。 | 5 | 2 | 1 | False | 1.00 | 2 + 4 + 1 + 0 + 0 + 1 | 8 | high |
| 7 | 结构性拥堵：长链 + 多车队 + 多汇聚同时出现，表现为路口上游持续回压。 | 8 | 3 | 2 | False | 1.10 | 4 + 6 + 2 + 0 + 1 + 1 | 14 | high |
| 8 | 互锁倾向：检测到 following 环，虽然最长链不高，但结构异常导致风险抬升。 | -1 | 1 | 2 | True | 1.00 | 0 + 2 + 2 + 2 + 0 + 1 | 7 | medium |
| 9 | 极端复杂拥塞：长链、多车队、多汇聚与环并存，属于异常缓行高置信候选。 | 9 | 3 | 3 | True | 1.30 | 4 + 6 + 2 + 2 + 1 + 1 | 16 | high |
| 10 | 单链主导但未扩散：虽然有较长链条，但缺少多车队/汇聚支撑，整体仅中风险。 | 7 | 0 | 0 | False | 0.40 | 3 + 0 + 0 + 0 + 1 + 0 | 4 | medium |

注：当 cycle_detected=True 时，图分析中 max_chain 常被置为 -1，此时链长分记为 0（实现中使用 max(max_chain, 0)）。

---

## 5. 核心思路 / Core Idea

1. 系统不是看单一阈值，而是把链长、车队数量、汇聚结构、循环异常和密度综合成一个结构化分数。
2. 分数阈值简单清晰：>=8 是 high，4~7 是 medium，<4 是 low。
3. 通过 10 个典型场景表，可以说明为什么某些样本虽然“有链”但仍只是 medium，或为什么“多车队 + 汇聚 + 高密度”会直接进入 high。

---

## 6. 实现对照 / Code Mapping

- 评分函数：traffic_agent_system/agents/cognitive_agents.py::_score_slowdown
- 等级映射：traffic_agent_system/agents/cognitive_agents.py::_level_from_score
- 跟驰结构诊断：traffic_agent_system/governance/graph_analyzer.py::diagnose_following_anomaly

