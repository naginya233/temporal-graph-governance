import base64
import os
import requests
import math
from typing import Any, Dict, List, Optional
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

VLM_TRIGGER_MODES = {
    "off",
    "critical",
    "uncertainty",
    "sample",
    "critical_sample",
    "hybrid",
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
        spatial_context: Optional[Dict[str, Any]] = None,
        following_filter: Optional[Dict[str, Any]] = None,
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
        llm_api_url: str = "http://8.138.133.71:8080/v1/chat/completions",
        model_name: str = "qwen2-vl",
        request_timeout: int = 12,
        llm_api_key: str = "",
        enable_vlm: bool = True,
        llm_trigger_mode: str = "critical_sample",
        llm_max_calls: int = 1200,
        llm_max_ratio: float = 0.08,
        llm_sample_every_n: int = 60,
        ollama_url: str = "",
    ):
        self.name = "EventAgent"
        self.use_llm = use_llm
        # backward compatibility: if old arg ollama_url is explicitly set, prefer it.
        self.llm_api_url = (ollama_url or llm_api_url).strip()
        self.model_name = model_name
        self.request_timeout = max(1, int(request_timeout))
        self.llm_api_key = llm_api_key
        self.enable_vlm = enable_vlm
        normalized_mode = str(llm_trigger_mode or "critical").strip().lower()
        self.llm_trigger_mode = normalized_mode if normalized_mode in VLM_TRIGGER_MODES else "critical"
        self.llm_max_calls = max(0, int(llm_max_calls))
        self.llm_max_ratio = max(0.0, min(float(llm_max_ratio), 1.0))
        self.llm_sample_every_n = max(0, int(llm_sample_every_n))

        self._expected_frames = 0
        self._processed_frames = 0
        self._llm_calls_made = 0
        self._llm_budget_total = -1
        self.reset_run_budget(expected_frames=0)

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

            source_weights: Dict[str, float] = {
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
            source_weights_map = obj.get("source_weights")
            if not isinstance(source_weights_map, dict):
                continue
            for entity_id, weight in source_weights_map.items():
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
    def _is_critical_slowdown(slowdown: Dict[str, Any]) -> bool:
        return slowdown["level"] in {"medium", "high"} or bool(slowdown.get("is_abnormal", False))

    @staticmethod
    def _is_uncertain_slowdown(slowdown: Dict[str, Any]) -> bool:
        score = int(slowdown.get("score", 0) or 0)
        merge_cnt = int(slowdown.get("merge_cnt", 0) or 0)
        max_chain = int(slowdown.get("max_chain", 0) or 0)
        queue_density = float(slowdown.get("queue_density", 0.0) or 0.0)

        near_level_boundaries = score in {3, 4, 7, 8}
        ambiguous_density = 0.82 <= queue_density <= 1.05
        ambiguous_structure = (merge_cnt == 1 and ambiguous_density) or (max_chain in {3, 4} and ambiguous_density)
        return near_level_boundaries or ambiguous_structure

    def _is_sampled_frame(self) -> bool:
        if self.llm_sample_every_n <= 0:
            return False
        if self._processed_frames <= 0:
            return False
        return self._processed_frames % self.llm_sample_every_n == 0

    def _should_call_llm(self, slowdown: Dict[str, Any]) -> tuple[bool, str]:
        critical = self._is_critical_slowdown(slowdown)
        uncertain = self._is_uncertain_slowdown(slowdown)
        sampled = self._is_sampled_frame()

        mode = self.llm_trigger_mode
        if mode == "off":
            return False, "mode_off"
        if mode == "critical":
            return critical, "critical" if critical else "not_critical"
        if mode == "uncertainty":
            return uncertain, "uncertainty" if uncertain else "not_uncertain"
        if mode == "sample":
            return sampled, "sample" if sampled else "not_sampled"
        if mode == "critical_sample":
            if critical:
                return True, "critical"
            if sampled:
                return True, "sample"
            return False, "not_critical_or_sampled"
        if mode == "hybrid":
            if critical:
                return True, "critical"
            if uncertain:
                return True, "uncertainty"
            if sampled:
                return True, "sample"
            return False, "not_hybrid_triggered"
        return critical, "critical" if critical else "not_critical"

    def reset_run_budget(self, expected_frames: int = 0) -> None:
        self._expected_frames = max(0, int(expected_frames))
        self._processed_frames = 0
        self._llm_calls_made = 0

        limits: List[int] = []
        if self.llm_max_calls > 0:
            limits.append(self.llm_max_calls)

        if self.llm_max_ratio > 0.0 and self._expected_frames > 0:
            ratio_limit = int(math.ceil(self._expected_frames * self.llm_max_ratio))
            ratio_limit = max(1, ratio_limit)
            # 小规模 run 至少保留少量 VLM 预算，避免样本过少无法触发。
            if self._expected_frames <= 200:
                ratio_limit = max(3, ratio_limit)
            limits.append(ratio_limit)

        self._llm_budget_total = min(limits) if limits else -1

    def _budget_remaining(self) -> Optional[int]:
        if self._llm_budget_total < 0:
            return None
        return max(0, self._llm_budget_total - self._llm_calls_made)

    def _consume_llm_budget(self) -> tuple[bool, str]:
        if self._llm_budget_total < 0:
            return True, "unlimited"
        if self._llm_calls_made < self._llm_budget_total:
            self._llm_calls_made += 1
            return True, "consumed"
        return False, "budget_exhausted"

    @staticmethod
    def _guess_image_mime_type(image_path: str) -> str:
        ext = os.path.splitext(str(image_path or ""))[1].lower()
        if ext in {".jpg", ".jpeg"}:
            return "image/jpeg"
        if ext == ".png":
            return "image/png"
        if ext == ".webp":
            return "image/webp"
        if ext == ".gif":
            return "image/gif"
        return "application/octet-stream"

    def _build_image_data_url(self, image_path: str) -> str:
        if not image_path:
            return ""
        if not os.path.isfile(image_path):
            return ""
        try:
            with open(image_path, "rb") as image_file:
                encoded = base64.b64encode(image_file.read()).decode("utf-8")
            mime_type = self._guess_image_mime_type(image_path)
            return f"data:{mime_type};base64,{encoded}"
        except OSError:
            return ""

    @staticmethod
    def _extract_chat_content(message_content: Any) -> str:
        if isinstance(message_content, str):
            return message_content.strip()
        if isinstance(message_content, list):
            chunks: List[str] = []
            for chunk in message_content:
                if not isinstance(chunk, dict):
                    continue
                if chunk.get("type") == "text":
                    text = str(chunk.get("text", "")).strip()
                    if text:
                        chunks.append(text)
            return "\n".join(chunks).strip()
        return ""

    def _call_chat_completions(
        self,
        system_prompt: str,
        user_prompt: str,
        raw_image_path: Optional[str] = None,
    ) -> str:
        user_text = f"当前路口状态:\n{user_prompt}\n\n请给出治理建议："
        user_content: Any = user_text

        if self.enable_vlm and raw_image_path:
            image_data_url = self._build_image_data_url(raw_image_path)
            if image_data_url:
                user_content = [
                    {"type": "text", "text": user_text},
                    {
                        "type": "image_url",
                        "image_url": {"url": image_data_url},
                    },
                ]

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
        }
        headers = {"Content-Type": "application/json"}
        if self.llm_api_key:
            headers["Authorization"] = f"Bearer {self.llm_api_key}"

        try:
            response = requests.post(
                self.llm_api_url,
                headers=headers,
                json=payload,
                timeout=self.request_timeout,
            )
            if response.status_code != 200:
                response_preview = response.text[:500]
                return f"[LLM 异常] 状态码: {response.status_code}, body: {response_preview}"

            try:
                result = response.json()
            except ValueError:
                return f"[LLM 异常] 响应不是合法 JSON: {response.text[:500]}"

            choices = result.get("choices", [])
            if isinstance(choices, list) and choices:
                first_choice = choices[0] if isinstance(choices[0], dict) else {}
                message = first_choice.get("message", {}) if isinstance(first_choice, dict) else {}
                content = self._extract_chat_content(message.get("content", ""))
                if content:
                    return content

            # fallback:兼容某些本地服务保留的 response 字段
            fallback_content = str(result.get("response", "")).strip()
            if fallback_content:
                return fallback_content
            return "[LLM 异常] 返回结构缺少可解析内容(choices/message/content)"
        except requests.exceptions.RequestException as exc:
            return f"[LLM 服务未响应] {exc}"

    def reason(self, scene_insights: Dict[str, Any], raw_image_path: Optional[str] = None) -> str:
        analysis = self.analyze(scene_insights, raw_image_path=raw_image_path)
        return analysis["report"]

    def analyze(self, scene_insights: Dict[str, Any], raw_image_path: Optional[str] = None) -> Dict[str, Any]:
        self._processed_frames += 1

        slowdown = self._score_slowdown(scene_insights)
        prompt = self._generate_prompt(scene_insights, slowdown)

        if slowdown.get("class") == "anomalous_slowdown":
            fast_decision = "【快速决策】检测到异常缓行，建议优先排查瓶颈车道与信号放行冲突。"
        elif slowdown.get("class") == "sustained_slowdown":
            fast_decision = "【快速决策】检测到持续缓行，建议优化配时并提升排队消散效率。"
        else:
            fast_decision = "【快速决策】当前为正常受控排队，维持常规监测。"
        
        llm_insight = ""
        llm_meta: Dict[str, Any] = {
            "enabled": bool(self.use_llm),
            "trigger_mode": self.llm_trigger_mode,
            "triggered": False,
            "trigger_reason": "",
            "skipped_reason": "",
            "request_timeout_sec": self.request_timeout,
            "processed_frames": self._processed_frames,
            "expected_frames": self._expected_frames,
            "calls_made": self._llm_calls_made,
            "budget_total": (self._llm_budget_total if self._llm_budget_total >= 0 else None),
            "budget_remaining": self._budget_remaining(),
        }

        if self.use_llm:
            should_call, trigger_reason = self._should_call_llm(slowdown)
            llm_meta["trigger_reason"] = trigger_reason

            if should_call:
                allowed, budget_state = self._consume_llm_budget()
                if allowed:
                    sys_prompt = (
                        "你是交通缓行分析助手。"
                        "请基于 following 结构给出缓行原因判断和两条可执行建议，"
                        "并明确是否需要信号配时优化。"
                        "回答控制在3句话内。"
                    )
                    llm_reply = self._call_chat_completions(
                        system_prompt=sys_prompt,
                        user_prompt=prompt,
                        raw_image_path=raw_image_path,
                    )
                    llm_insight = f"\n【大模型(标准ChatCompletions接口)深度语义推理】\n{llm_reply}"
                    llm_meta["triggered"] = True
                else:
                    llm_meta["skipped_reason"] = budget_state
            else:
                llm_meta["skipped_reason"] = "trigger_not_matched"
        else:
            llm_meta["skipped_reason"] = "llm_disabled"

        llm_meta["calls_made"] = self._llm_calls_made
        llm_meta["budget_remaining"] = self._budget_remaining()

        report = prompt + fast_decision + llm_insight
        return {
            "slowdown": slowdown,
            "risk": dict(slowdown),
            "fast_decision": fast_decision,
            "llm_insight": llm_insight,
            "llm_meta": llm_meta,
            "report": report,
        }
