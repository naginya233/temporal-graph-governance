import requests
import math
from typing import Any, Dict, List
from governance.graph_analyzer import TrafficGraphAnalyzer


SLOWDOWN_CLASS_LABELS = {
    "normal_controlled_queue": "正常受控排队",
    "sustained_slowdown": "持续缓行",
    "anomalous_slowdown": "异常缓行",
}

SOURCE_ROLE_WEIGHT = {
    "merge_bottleneck": 2.0,
    "cycle_lock": 1.6,
    "queue_head": 1.2,
}

class SceneAgent:
    """
    Scene Agent (场景理解智能体)
    Focuses on macro-level relations and aggregates subgraphs to recognize global patterns.
    """
    def __init__(self):
        self.name = "SceneAgent"

    def process(
        self,
        frame_id: str,
        scene_graph_dict: Dict[str, Any],
        spatial_context: Dict[str, Any] = None,
        following_filter: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        Takes raw scene graph output and performs structure analysis.
        """
        analyzer = TrafficGraphAnalyzer(
            scene_graph_dict,
            spatial_context=spatial_context,
            following_filter=following_filter,
        )

        # 缓行分析主线：仅基于 following 结构诊断车队状态
        following_diagnostics = analyzer.diagnose_following_anomaly()
        convoys = following_diagnostics.get("convoy_chains", [])

        return {
            "frame_id": frame_id,
            "yielding_disorders": [],
            "conflict_propagation_chains": [],
            "following_health": following_diagnostics,
            "following_convoys": convoys,
            "following_merge_nodes": following_diagnostics.get("merge_nodes", []),
            "game_deadlocks": [],
        }

class EventAgent:
    """
    Event Agent (事件推理智能体)
    Uses LLM / Rule-based prompting over the macro structures detected by SceneAgent to issue governance insights.
    """
    def __init__(
        self,
        use_llm: bool = True,
        ollama_url: str = "http://localhost:11434/api/generate",
        model_name: str = "qwen3-vl:4b",
        request_timeout: int = 20,
    ):
        self.name = "EventAgent"
        self.use_llm = use_llm
        self.ollama_url = ollama_url
        self.model_name = model_name
        self.request_timeout = request_timeout

    @staticmethod
    def _unique_ordered(items: List[str]) -> List[str]:
        return list(dict.fromkeys(str(item) for item in items if str(item).strip()))

    @staticmethod
    def _object_type_for_entity(entity_id: str, following_node_geometry: Dict[str, Dict[str, Any]]) -> str:
        geo = following_node_geometry.get(entity_id)
        if not isinstance(geo, dict):
            return "UNKNOWN"
        text = str(geo.get("object_type", "UNKNOWN") or "UNKNOWN").strip().upper()
        return text if text else "UNKNOWN"

    @staticmethod
    def _vehicle_source_weight(object_type: str) -> float:
        normalized = str(object_type or "").upper()
        if any(token in normalized for token in ("TRUCK", "FREIGHT", "CARGO")):
            return 2.4
        if any(token in normalized for token in ("BUS", "VAN", "PICKUP", "SUV")):
            return 1.35
        if any(token in normalized for token in ("CAR", "TAXI", "MOTORCYCLE")):
            return 1.0
        if any(token in normalized for token in ("BICYCLE", "CYCLIST", "TRICYCLE", "PEDESTRIAN", "PERSON")):
            return 0.65
        return 1.0

    def _source_weight(
        self,
        entity_id: str,
        source_type: str,
        following_node_geometry: Dict[str, Dict[str, Any]],
        upstream_by_node: Dict[str, List[str]],
    ) -> float:
        object_type = self._object_type_for_entity(entity_id, following_node_geometry)
        role_weight = SOURCE_ROLE_WEIGHT.get(source_type, 1.0)
        vehicle_weight = self._vehicle_source_weight(object_type)
        upstream_bonus = 1.0 + min(len(upstream_by_node.get(entity_id, [])), 5) * 0.08
        return round(role_weight * vehicle_weight * upstream_bonus, 4)

    def _build_slowdown_objects(self, scene_insights: Dict[str, Any]) -> Dict[str, Any]:
        following = scene_insights.get("following_health", {}) or {}
        convoy_chains = following.get("convoy_chains", []) or []
        merge_nodes = set(str(node) for node in following.get("merge_nodes", []) or [])
        following_nodes = self._unique_ordered([str(node) for node in (following.get("following_nodes", []) or [])])
        following_edges = following.get("following_edges", []) or []
        following_node_geometry = following.get("following_node_geometry", {}) or {}
        following_lane_by_node = following.get("following_lane_by_node", {}) or {}
        following_lane_geometry = following.get("following_lane_geometry", {}) or {}
        cycle_detected = bool(following.get("cycle_detected", False))

        upstream_by_node: Dict[str, List[str]] = {}
        for edge in following_edges:
            if not isinstance(edge, dict):
                continue
            src = str(edge.get("subject", "")).strip()
            dst = str(edge.get("object", "")).strip()
            if not src or not dst:
                continue
            upstream_by_node.setdefault(dst, []).append(src)

        slowdown_objects: List[Dict[str, Any]] = []
        all_individuals: List[str] = []
        queue_head_sources: List[str] = []

        def _spatial_order(members: List[str]) -> List[str]:
            if not members:
                return []

            lane_members: Dict[str, List[str]] = {}
            for node in members:
                lane_id = str(following_lane_by_node.get(node, "")).strip()
                if lane_id:
                    lane_members.setdefault(lane_id, []).append(node)

            if lane_members:
                dominant_lane = max(lane_members.items(), key=lambda item: len(item[1]))[0]
                lane_geo = following_lane_geometry.get(dominant_lane)
                if isinstance(lane_geo, dict):
                    axis_x = float(lane_geo.get("axis_x", 1.0))
                    axis_y = float(lane_geo.get("axis_y", 0.0))
                    center_x = float(lane_geo.get("center_x", 0.0))
                    center_y = float(lane_geo.get("center_y", 0.0))

                    lane_projections = []
                    for node in members:
                        geo = following_node_geometry.get(node)
                        if not isinstance(geo, dict):
                            lane_projections = []
                            break
                        x = float(geo.get("x", 0.0))
                        y = float(geo.get("y", 0.0))
                        lane_projections.append((node, ((x - center_x) * axis_x) + ((y - center_y) * axis_y)))

                    if lane_projections:
                        lane_projections.sort(key=lambda item: item[1])
                        return [node for node, _ in lane_projections]

            available = []
            for node in members:
                geo = following_node_geometry.get(node)
                if isinstance(geo, dict):
                    available.append((node, geo))

            if len(available) < 2:
                return list(members)

            avg_hx = 0.0
            avg_hy = 0.0
            for _, geo in available:
                avg_hx += float(geo.get("heading_x", 0.0))
                avg_hy += float(geo.get("heading_y", 0.0))

            norm = math.sqrt((avg_hx * avg_hx) + (avg_hy * avg_hy))
            if norm <= 1e-8:
                return list(members)

            axis_x = avg_hx / norm
            axis_y = avg_hy / norm

            projections = []
            for node in members:
                geo = following_node_geometry.get(node)
                if not isinstance(geo, dict):
                    return list(members)
                x = float(geo.get("x", 0.0))
                y = float(geo.get("y", 0.0))
                projections.append((node, (x * axis_x) + (y * axis_y)))

            projections.sort(key=lambda item: item[1])
            return [node for node, _ in projections]

        for idx, chain in enumerate(convoy_chains):
            members = self._unique_ordered([str(node) for node in chain])
            if not members:
                continue

            ordered_members = _spatial_order(members)

            queue_tail = ordered_members[0]
            queue_head = ordered_members[-1]
            chain_merge_sources = [node for node in ordered_members if node in merge_nodes]

            if chain_merge_sources:
                source_entities = self._unique_ordered(chain_merge_sources)
                source_type = "merge_bottleneck"
            elif cycle_detected:
                source_entities = [queue_head]
                source_type = "cycle_lock"
            else:
                source_entities = [queue_head]
                source_type = "queue_head"

            source_weights = {
                src: self._source_weight(
                    entity_id=src,
                    source_type=source_type,
                    following_node_geometry=following_node_geometry,
                    upstream_by_node=upstream_by_node,
                )
                for src in source_entities
            }
            source_entities = sorted(source_entities, key=lambda src: (-source_weights.get(src, 0.0), src))

            slowdown_objects.append(
                {
                    "flow_id": f"flow_{idx + 1}",
                    "flow_kind": "convoy_chain",
                    "chain": ordered_members,
                    "individual_entities": ordered_members,
                    "entity_count": len(ordered_members),
                    "queue_tail": queue_tail,
                    "queue_head": queue_head,
                    "source_entities": source_entities,
                    "source_primary": source_entities[0] if source_entities else "",
                    "source_primary_object_type": (
                        self._object_type_for_entity(source_entities[0], following_node_geometry)
                        if source_entities
                        else "UNKNOWN"
                    ),
                    "source_weights": {
                        src: source_weights.get(src, 0.0)
                        for src in source_entities
                    },
                    "source_type": source_type,
                    "upstream_to_source": {
                        src: self._unique_ordered(upstream_by_node.get(src, []))
                        for src in source_entities
                    },
                }
            )

            all_individuals.extend(ordered_members)
            queue_head_sources.append(queue_head)

        if not slowdown_objects and following_nodes:
            ordered_nodes = _spatial_order(following_nodes)
            component_sources = self._unique_ordered(list(merge_nodes)) or ([ordered_nodes[-1]] if ordered_nodes else [])
            fallback_type = "merge_bottleneck" if merge_nodes else ("cycle_lock" if cycle_detected else "queue_head")
            fallback_head = ordered_nodes[-1] if ordered_nodes else ""
            component_source_weights = {
                src: self._source_weight(
                    entity_id=src,
                    source_type=fallback_type,
                    following_node_geometry=following_node_geometry,
                    upstream_by_node=upstream_by_node,
                )
                for src in component_sources
            }
            component_sources = sorted(
                component_sources,
                key=lambda src: (-component_source_weights.get(src, 0.0), src),
            )
            slowdown_objects.append(
                {
                    "flow_id": "flow_1",
                    "flow_kind": "following_component",
                    "chain": [],
                    "individual_entities": ordered_nodes,
                    "entity_count": len(ordered_nodes),
                    "queue_tail": ordered_nodes[0] if ordered_nodes else "",
                    "queue_head": fallback_head,
                    "source_entities": component_sources,
                    "source_primary": component_sources[0] if component_sources else "",
                    "source_primary_object_type": (
                        self._object_type_for_entity(component_sources[0], following_node_geometry)
                        if component_sources
                        else "UNKNOWN"
                    ),
                    "source_weights": {
                        src: component_source_weights.get(src, 0.0)
                        for src in component_sources
                    },
                    "source_type": fallback_type,
                    "upstream_to_source": {
                        src: self._unique_ordered(upstream_by_node.get(src, []))
                        for src in component_sources
                    },
                }
            )
            all_individuals.extend(ordered_nodes)
            if fallback_head:
                queue_head_sources.append(fallback_head)

        merge_sources = self._unique_ordered(list(merge_nodes))
        cycle_sources = following_nodes if cycle_detected else []
        head_sources = self._unique_ordered(queue_head_sources)

        source_weight_by_entity: Dict[str, float] = {}
        for obj in slowdown_objects:
            if not isinstance(obj, dict):
                continue
            source_weights = obj.get("source_weights")
            if not isinstance(source_weights, dict):
                continue
            for entity_id, weight in source_weights.items():
                source_entity = str(entity_id)
                source_weight_by_entity[source_entity] = source_weight_by_entity.get(source_entity, 0.0) + float(weight)

        if not source_weight_by_entity:
            fallback_sources = self._unique_ordered(merge_sources + cycle_sources + head_sources)
            source_weight_by_entity = {
                entity_id: self._source_weight(
                    entity_id=entity_id,
                    source_type="queue_head",
                    following_node_geometry=following_node_geometry,
                    upstream_by_node=upstream_by_node,
                )
                for entity_id in fallback_sources
            }

        source_entities = sorted(source_weight_by_entity.keys(), key=lambda src: (-source_weight_by_entity[src], src))
        individual_entities = self._unique_ordered(all_individuals or following_nodes)

        source_weighted_ranking = [
            {
                "entity": source,
                "weight": round(source_weight_by_entity.get(source, 0.0), 4),
                "object_type": self._object_type_for_entity(source, following_node_geometry),
            }
            for source in source_entities
        ]

        return {
            "slowdown_objects": slowdown_objects,
            "individual_entities": individual_entities,
            "source_entities": source_entities,
            "source_summary": {
                "merge_bottleneck_sources": merge_sources,
                "cycle_lock_sources": cycle_sources,
                "queue_head_sources": head_sources,
                "source_count": len(source_entities),
                "source_weighted_ranking": source_weighted_ranking,
            },
        }

    @staticmethod
    def _level_from_score(score: int) -> str:
        if score >= 8:
            return "high"
        if score >= 4:
            return "medium"
        return "low"

    @staticmethod
    def _classify_slowdown(
        max_chain: int,
        convoy_count: int,
        merge_cnt: int,
        queue_density: float,
        cycle_detected: bool,
        score: int,
    ) -> str:
        # 分类目标：识别所有缓行，再区分正常受控/持续缓行/异常缓行。
        if cycle_detected:
            return "anomalous_slowdown"

        # 对信号受控排队做保守处理：仅在“极端且高分”的结构下判定异常。
        severe_structural_anomaly = (
            score >= 10
            and max_chain >= 9
            and convoy_count >= 3
            and merge_cnt >= 3
            and queue_density >= 1.2
        )
        if severe_structural_anomaly:
            return "anomalous_slowdown"

        sustained_structural_pattern = (
            max_chain >= 4
            or convoy_count >= 2
            or (merge_cnt >= 2 and queue_density >= 0.85)
            or (max_chain >= 3 and queue_density >= 0.9)
        )
        if sustained_structural_pattern:
            return "sustained_slowdown"

        sustained_by_score_and_structure = (
            score >= 6
            and merge_cnt >= 1
            and queue_density >= 0.95
        )
        if sustained_by_score_and_structure:
            return "sustained_slowdown"
        return "normal_controlled_queue"

    def _slowdown_causes(
        self,
        max_chain: int,
        convoy_count: int,
        merge_cnt: int,
        queue_density: float,
        cycle_detected: bool,
    ) -> List[str]:
        causes = []
        if max_chain >= 6:
            causes.append("long_convoy")
        if convoy_count >= 2:
            causes.append("multi_convoy")
        elif convoy_count >= 1:
            causes.append("single_convoy")
        if merge_cnt > 0:
            causes.append("merge_bottleneck")
        if queue_density >= 1.0:
            causes.append("dense_following")
        if cycle_detected:
            causes.append("following_cycle")
        if not causes:
            causes.append("controlled_queue")
        return causes

    def _score_slowdown(self, scene_insights: Dict[str, Any]) -> Dict[str, Any]:
        following = scene_insights.get("following_health", {})
        convoy_count = int(following.get("convoy_count", 0) or 0)
        merge_cnt = len(following.get("merge_nodes", []))
        cycle_detected = bool(following.get("cycle_detected", False))
        max_chain = int(following.get("max_following_chain", 0))
        queue_density = float(following.get("queue_density", 0.0) or 0.0)
        following_filter = following.get("following_filter", {}) or {}

        score = 0
        score += min(max(max_chain, 0) // 2, 4)
        score += min(convoy_count, 3) * 2
        score += 2 if merge_cnt >= 2 else (1 if merge_cnt == 1 else 0)
        score += 2 if cycle_detected else 0
        score += 1 if max_chain >= 6 else 0
        score += 1 if queue_density >= 1.0 else 0

        level = self._level_from_score(score)
        slowdown_class = self._classify_slowdown(
            max_chain=max_chain,
            convoy_count=convoy_count,
            merge_cnt=merge_cnt,
            queue_density=queue_density,
            cycle_detected=cycle_detected,
            score=score,
        )
        causes = self._slowdown_causes(
            max_chain=max_chain,
            convoy_count=convoy_count,
            merge_cnt=merge_cnt,
            queue_density=queue_density,
            cycle_detected=cycle_detected,
        )
        is_slowdown = slowdown_class in {"sustained_slowdown", "anomalous_slowdown"}
        slowdown_object_payload = self._build_slowdown_objects(scene_insights)
        metrics = {
            "following_edge_count": int(following.get("edge_count", 0) or 0),
            "following_edge_count_raw": int(
                following.get("raw_following_edge_count", following.get("edge_count", 0)) or 0
            ),
            "following_edge_count_filtered": int(
                following.get("filtered_following_edge_count", following.get("edge_count", 0)) or 0
            ),
            "following_edge_count_removed": int(following.get("removed_following_edge_count", 0) or 0),
            "following_filter_enabled": bool(following_filter.get("enabled", False)),
            "following_filter_applied": bool(following_filter.get("applied", False)),
            "following_filter_reasons": following_filter.get("reasons", {}),
            "spatial_context_available": bool(following_filter.get("spatial_context_available", False)),
            "spatial_source": str(following_filter.get("spatial_source", "none")),
            "calibrated_to_world": bool(following_filter.get("calibrated_to_world", False)),
        }

        return {
            "score": score,
            "level": level,
            "class": slowdown_class,
            "class_label": SLOWDOWN_CLASS_LABELS.get(slowdown_class, slowdown_class),
            "is_slowdown": is_slowdown,
            "is_abnormal": slowdown_class == "anomalous_slowdown",
            "yielding_cnt": 0,
            "chain_cnt": 0,
            "deadlock_cnt": 0,
            "bottleneck_cnt": merge_cnt,
            "convoy_cnt": convoy_count,
            "merge_cnt": merge_cnt,
            "queue_density": queue_density,
            "cycle_detected": cycle_detected,
            "max_chain": max_chain,
            "causes": causes,
            "dominant_cause": causes[0] if causes else "controlled_queue",
            "analysis_focus": "following_queue",
            "metrics": metrics,
            "individual_entities": slowdown_object_payload["individual_entities"],
            "source_entities": slowdown_object_payload["source_entities"],
            "source_summary": slowdown_object_payload["source_summary"],
            "slowdown_objects": slowdown_object_payload["slowdown_objects"],
            "slowdown_object_count": len(slowdown_object_payload["slowdown_objects"]),
        }

    def _score_risk(self, scene_insights: Dict[str, Any]) -> Dict[str, Any]:
        # 兼容旧接口：risk 与 slowdown 共享同一评分结果。
        return self._score_slowdown(scene_insights)
        
    def _generate_prompt(self, scene_insights: Dict[str, Any], slowdown: Dict[str, Any]) -> str:
        prompt = f"### 交叉口缓行车队分析 (Frame {scene_insights['frame_id']}) ###\n"
        prompt += (
            f"- 缓行等级: {slowdown['level']} (score={slowdown['score']})\n"
            f"- 缓行类型: {slowdown.get('class_label', 'unknown')} ({slowdown.get('class', 'unknown')})\n"
        )

        fh = scene_insights.get("following_health", {})
        convoy_chains = fh.get("convoy_chains", [])
        merge_nodes = fh.get("merge_nodes", [])

        prompt += (
            f"- [跟驰概况] following_nodes={fh.get('node_count', 0)}, "
            f"following_edges={fh.get('edge_count', 0)}, density={fh.get('queue_density', 0.0)}\n"
        )

        filter_meta = fh.get("following_filter", {}) or {}
        if filter_meta.get("applied", False):
            prompt += (
                f"- [空间一致性过滤] raw_edges={filter_meta.get('raw_edge_count', 0)}, "
                f"kept_edges={filter_meta.get('kept_edge_count', 0)}, "
                f"removed={filter_meta.get('removed_edge_count', 0)}, "
                f"reasons={filter_meta.get('reasons', {})}\n"
            )

        if fh.get("max_following_chain", 0) >= 3:
            prompt += f"- [缓行征兆] 发现最长跟驰链长度={fh['max_following_chain']}\n"

        if convoy_chains:
            sample = " -> ".join(convoy_chains[0])
            prompt += f"- [车队样例] 典型缓行车队链: {sample}\n"

        if merge_nodes:
            prompt += f"- [汇聚瓶颈] following 汇聚节点: {merge_nodes}\n"

        if fh.get("cycle_detected", False):
            prompt += "- [结构异常] following 图存在环，可能出现局部停滞或互锁\n"

        if fh.get("max_following_chain", 0) < 3 and not merge_nodes and not fh.get("cycle_detected", False):
            prompt += "- [平稳] 暂未发现明显缓行车队结构\n"
            
        return prompt

    @staticmethod
    def _should_call_llm(slowdown: Dict[str, Any]) -> bool:
        return slowdown["level"] in {"medium", "high"} or bool(slowdown.get("is_abnormal", False))

    def _call_ollama(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model_name,
            "prompt": f"{system_prompt}\n\n当前路口状态:\n{user_prompt}\n\n请给出治理建议：",
            "stream": False,
            "options": {
                "temperature": 0.2,
            },
        }
        try:
            response = requests.post(self.ollama_url, json=payload, timeout=self.request_timeout)
            if response.status_code == 200:
                result = response.json()
                return result.get("response", "").strip()
            return f"[LLM 异常] 状态码: {response.status_code}"
        except requests.exceptions.RequestException as exc:
            return f"[LLM 服务未响应] {exc}"

    def reason(self, scene_insights: Dict[str, Any]) -> str:
        analysis = self.analyze(scene_insights)
        return analysis["report"]

    def analyze(self, scene_insights: Dict[str, Any]) -> Dict[str, Any]:
        slowdown = self._score_slowdown(scene_insights)
        prompt = self._generate_prompt(scene_insights, slowdown)

        if slowdown.get("class") == "anomalous_slowdown":
            fast_decision = "【快速决策】检测到异常缓行，建议优先排查瓶颈车道与信号放行冲突。"
        elif slowdown.get("class") == "sustained_slowdown":
            fast_decision = "【快速决策】检测到持续缓行，建议优化配时并提升排队消散效率。"
        else:
            fast_decision = "【快速决策】当前为正常受控排队，维持常规监测。"
        
        llm_insight = ""
        if self.use_llm and self._should_call_llm(slowdown):
            sys_prompt = (
                "你是交通缓行分析助手。"
                "请基于 following 结构给出缓行原因判断和两条可执行建议，"
                "并明确是否需要信号配时优化。"
                "回答控制在3句话内。"
            )
            llm_reply = self._call_ollama(sys_prompt, prompt)
            llm_insight = f"\n【大模型(Qwen3-VL)深度语义推理】\n{llm_reply}"

        report = prompt + fast_decision + llm_insight
        return {
            "slowdown": slowdown,
            "risk": dict(slowdown),
            "fast_decision": fast_decision,
            "llm_insight": llm_insight,
            "report": report,
        }
