import math
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx

from core.constants import ALLOWED_RELATIONS


MOTORIZED_TYPE_TOKENS: Tuple[str, ...] = (
    "CAR",
    "VAN",
    "BUS",
    "TRUCK",
    "MOTORCYCLE",
    "SUV",
    "TAXI",
    "PICKUP",
    "MINIBUS",
    "TRACTOR",
    "TRAILER",
    "FREIGHT",
)

NON_MOTORIZED_TYPE_TOKENS: Tuple[str, ...] = (
    "BICYCLE",
    "CYCLIST",
    "E_BIKE",
    "EBIKE",
    "TRICYCLE",
    "PEDESTRIAN",
    "PERSON",
    "RIDER",
)

class TrafficGraphAnalyzer:
    """
    Traffic Scene Graph Analyzer for relation-driven governance.
    Implements advanced graph-theoretic algorithms to detect traffic anomalies based on the Section 6 of the research report.
    """
    def __init__(
        self,
        graph_data: Dict[str, Any],
        spatial_context: Optional[Dict[str, Any]] = None,
        following_filter: Optional[Dict[str, Any]] = None,
    ):
        self.raw_data = graph_data
        self.G = self._build_multigraph(graph_data)
        self.relation_index = self._build_relation_index()
        self.spatial_context = spatial_context or {}

        config = following_filter or {}
        self.following_filter_config = {
            "enabled": bool(config.get("enabled", True)),
            "min_longitudinal_gap": float(config.get("min_longitudinal_gap", 1.5)),
            "max_longitudinal_gap": float(config.get("max_longitudinal_gap", 35.0)),
            "max_lateral_offset": float(config.get("max_lateral_offset", 3.2)),
            "min_heading_cos": float(config.get("min_heading_cos", 0.35)),
            "require_same_lane": bool(config.get("require_same_lane", True)),
        }

    @staticmethod
    def _normalize_object_type(raw_value: Any) -> str:
        text = str(raw_value or "").strip().upper()
        return text if text else "UNKNOWN"

    @classmethod
    def _is_non_motorized(cls, object_type: str) -> bool:
        normalized = cls._normalize_object_type(object_type)
        return any(token in normalized for token in NON_MOTORIZED_TYPE_TOKENS)

    @classmethod
    def _is_motorized(cls, object_type: str) -> bool:
        normalized = cls._normalize_object_type(object_type)
        if cls._is_non_motorized(normalized):
            return False
        return any(token in normalized for token in MOTORIZED_TYPE_TOKENS)

    def _resolve_node_type(self, node_id: str, node_geo: Optional[Dict[str, Any]] = None) -> str:
        graph_type = self._normalize_object_type((self.G.nodes.get(node_id) or {}).get("type", "UNKNOWN"))
        if graph_type != "UNKNOWN":
            return graph_type
        if isinstance(node_geo, dict):
            geo_type = self._normalize_object_type(node_geo.get("object_type", "UNKNOWN"))
            if geo_type != "UNKNOWN":
                return geo_type
        return graph_type

    def _adaptive_thresholds_for_edge(self, src_type: str, dst_type: str) -> Tuple[str, Dict[str, float]]:
        thresholds = {
            "min_longitudinal_gap": float(self.following_filter_config["min_longitudinal_gap"]),
            "max_longitudinal_gap": float(self.following_filter_config["max_longitudinal_gap"]),
            "max_lateral_offset": float(self.following_filter_config["max_lateral_offset"]),
            "min_heading_cos": float(self.following_filter_config["min_heading_cos"]),
        }

        src_motor = self._is_motorized(src_type)
        dst_motor = self._is_motorized(dst_type)
        src_non_motor = self._is_non_motorized(src_type)
        dst_non_motor = self._is_non_motorized(dst_type)

        if src_motor and dst_motor:
            profile = "motorized_pair"
            thresholds["min_longitudinal_gap"] = max(0.2, thresholds["min_longitudinal_gap"] * 0.75)
            thresholds["max_longitudinal_gap"] = thresholds["max_longitudinal_gap"] * 1.25
            thresholds["max_lateral_offset"] = thresholds["max_lateral_offset"] * 1.35
            thresholds["min_heading_cos"] = max(-1.0, thresholds["min_heading_cos"] - 0.15)
        elif src_non_motor and dst_non_motor:
            profile = "non_motorized_pair"
            thresholds["min_longitudinal_gap"] = thresholds["min_longitudinal_gap"] * 1.2
            thresholds["max_longitudinal_gap"] = thresholds["max_longitudinal_gap"] * 0.7
            thresholds["max_lateral_offset"] = thresholds["max_lateral_offset"] * 0.75
            thresholds["min_heading_cos"] = min(0.95, thresholds["min_heading_cos"] + 0.2)
        else:
            profile = "mixed_or_unknown_pair"

        return profile, thresholds

    def _can_relax_lane_mismatch(
        self,
        src_lane: str,
        dst_lane: str,
        src_type: str,
        dst_type: str,
        longitudinal_gap: float,
        lateral_gap: float,
        heading_cos: float,
        thresholds: Dict[str, float],
    ) -> bool:
        if not (self._is_motorized(src_type) and self._is_motorized(dst_type)):
            return False

        base_consistent_motion = (
            longitudinal_gap >= (thresholds["min_longitudinal_gap"] * 0.7)
            and longitudinal_gap <= (thresholds["max_longitudinal_gap"] * 1.25)
            and lateral_gap <= (thresholds["max_lateral_offset"] * 1.1)
            and heading_cos >= (thresholds["min_heading_cos"] - 0.05)
        )
        if not base_consistent_motion:
            return False

        lane_geometry = self.spatial_context.get("lane_geometry")
        if not isinstance(lane_geometry, dict):
            return True

        src_lane_geo = lane_geometry.get(src_lane)
        dst_lane_geo = lane_geometry.get(dst_lane)
        if not isinstance(src_lane_geo, dict) or not isinstance(dst_lane_geo, dict):
            return True

        src_cx = float(src_lane_geo.get("center_x", 0.0))
        src_cy = float(src_lane_geo.get("center_y", 0.0))
        dst_cx = float(dst_lane_geo.get("center_x", 0.0))
        dst_cy = float(dst_lane_geo.get("center_y", 0.0))
        center_distance = math.sqrt(((src_cx - dst_cx) * (src_cx - dst_cx)) + ((src_cy - dst_cy) * (src_cy - dst_cy)))

        src_ax = float(src_lane_geo.get("axis_x", 1.0))
        src_ay = float(src_lane_geo.get("axis_y", 0.0))
        dst_ax = float(dst_lane_geo.get("axis_x", 1.0))
        dst_ay = float(dst_lane_geo.get("axis_y", 0.0))
        lane_direction_cos = abs((src_ax * dst_ax) + (src_ay * dst_ay))

        return (
            center_distance <= 9.0
            and lane_direction_cos >= 0.55
        )

    @staticmethod
    def _entity_lanes_from_graph(graph_data: Dict[str, Any]) -> Dict[str, str]:
        lane_by_entity: Dict[str, str] = {}
        for triple in graph_data.get("object_map_triples", []):
            if not isinstance(triple, dict):
                continue
            relation = str(triple.get("relation", "")).lower()
            object_type = str(triple.get("object_type", "")).upper()
            if relation != "in" or not object_type.startswith("LANE"):
                continue

            subject = str(triple.get("subject", "")).strip()
            lane_id = str(triple.get("object", "")).strip()
            if subject and lane_id and subject not in lane_by_entity:
                lane_by_entity[subject] = lane_id
        return lane_by_entity

    def _combined_lane_index(self) -> Dict[str, str]:
        lane_by_entity = self._entity_lanes_from_graph(self.raw_data)
        external_lane_index = self.spatial_context.get("lane_by_entity")
        if isinstance(external_lane_index, dict):
            for entity_id, lane_id in external_lane_index.items():
                entity = str(entity_id).strip()
                lane = str(lane_id).strip()
                if entity and lane:
                    lane_by_entity[entity] = lane
        return lane_by_entity

    def _filter_following_edges(self, following_edges: List[Tuple[str, str]]) -> Tuple[List[Tuple[str, str]], Dict[str, Any]]:
        if not self.following_filter_config["enabled"]:
            return following_edges, {
                "enabled": False,
                "applied": False,
                "raw_edge_count": len(following_edges),
                "kept_edge_count": len(following_edges),
                "removed_edge_count": 0,
                "removal_rate": 0.0,
                "reasons": {},
                "removed_edges": [],
                "spatial_context_available": False,
            }

        entity_geometry = self.spatial_context.get("entity_geometry")
        if not isinstance(entity_geometry, dict) or not entity_geometry:
            return following_edges, {
                "enabled": True,
                "applied": False,
                "raw_edge_count": len(following_edges),
                "kept_edge_count": len(following_edges),
                "removed_edge_count": 0,
                "removal_rate": 0.0,
                "reasons": {},
                "removed_edges": [],
                "spatial_context_available": False,
            }

        lane_index = self._combined_lane_index()
        kept_edges: List[Tuple[str, str]] = []
        removed_edges: List[Dict[str, Any]] = []
        reason_counter: Dict[str, int] = {}
        profile_counter: Dict[str, int] = {}
        missing_geometry_edges = 0
        lane_mismatch_relaxed_kept = 0

        def _count_reason(name: str) -> None:
            reason_counter[name] = reason_counter.get(name, 0) + 1

        for subject, obj in sorted(following_edges, key=lambda edge: (str(edge[0]), str(edge[1]))):
            src = str(subject)
            dst = str(obj)
            src_geo = entity_geometry.get(src)
            dst_geo = entity_geometry.get(dst)

            src_type = self._resolve_node_type(src, src_geo if isinstance(src_geo, dict) else None)
            dst_type = self._resolve_node_type(dst, dst_geo if isinstance(dst_geo, dict) else None)
            profile, thresholds = self._adaptive_thresholds_for_edge(src_type, dst_type)
            profile_counter[profile] = profile_counter.get(profile, 0) + 1

            if not isinstance(src_geo, dict) or not isinstance(dst_geo, dict):
                kept_edges.append((src, dst))
                missing_geometry_edges += 1
                continue

            dx = float(dst_geo.get("x", 0.0)) - float(src_geo.get("x", 0.0))
            dy = float(dst_geo.get("y", 0.0)) - float(src_geo.get("y", 0.0))

            dst_hx = float(dst_geo.get("heading_x", 1.0))
            dst_hy = float(dst_geo.get("heading_y", 0.0))
            heading_norm = math.sqrt((dst_hx * dst_hx) + (dst_hy * dst_hy))
            if heading_norm <= 1e-8:
                dst_hx, dst_hy = 1.0, 0.0
            else:
                dst_hx /= heading_norm
                dst_hy /= heading_norm

            longitudinal_gap = (dx * dst_hx) + (dy * dst_hy)
            lateral_gap = abs((dx * (-dst_hy)) + (dy * dst_hx))

            src_hx = float(src_geo.get("heading_x", 1.0))
            src_hy = float(src_geo.get("heading_y", 0.0))
            src_norm = math.sqrt((src_hx * src_hx) + (src_hy * src_hy))
            if src_norm <= 1e-8:
                src_hx, src_hy = 1.0, 0.0
            else:
                src_hx /= src_norm
                src_hy /= src_norm

            heading_cos = (src_hx * dst_hx) + (src_hy * dst_hy)

            if self.following_filter_config["require_same_lane"]:
                src_lane = lane_index.get(src)
                dst_lane = lane_index.get(dst)
                if src_lane and dst_lane and src_lane != dst_lane:
                    if profile == "motorized_pair":
                        lane_mismatch_relaxed_kept += 1
                    elif self._can_relax_lane_mismatch(
                        src_lane=src_lane,
                        dst_lane=dst_lane,
                        src_type=src_type,
                        dst_type=dst_type,
                        longitudinal_gap=longitudinal_gap,
                        lateral_gap=lateral_gap,
                        heading_cos=heading_cos,
                        thresholds=thresholds,
                    ):
                        lane_mismatch_relaxed_kept += 1
                    else:
                        _count_reason("lane_mismatch")
                        removed_edges.append(
                            {
                                "subject": src,
                                "object": dst,
                                "reason": "lane_mismatch",
                                "subject_lane": src_lane,
                                "object_lane": dst_lane,
                                "subject_type": src_type,
                                "object_type": dst_type,
                                "edge_profile": profile,
                            }
                        )
                        continue

            reason = ""
            if longitudinal_gap < thresholds["min_longitudinal_gap"]:
                reason = "not_ahead"
            elif longitudinal_gap > thresholds["max_longitudinal_gap"]:
                reason = "too_far_longitudinal"
            elif lateral_gap > thresholds["max_lateral_offset"]:
                reason = "too_far_lateral"
            elif heading_cos < thresholds["min_heading_cos"]:
                reason = "heading_mismatch"

            if reason:
                _count_reason(reason)
                removed_edges.append(
                    {
                        "subject": src,
                        "object": dst,
                        "reason": reason,
                        "longitudinal_gap": round(longitudinal_gap, 6),
                        "lateral_gap": round(lateral_gap, 6),
                        "heading_cos": round(heading_cos, 6),
                        "subject_type": src_type,
                        "object_type": dst_type,
                        "edge_profile": profile,
                    }
                )
                continue

            kept_edges.append((src, dst))

        removed_edge_count = len(removed_edges)
        raw_edge_count = len(following_edges)
        kept_edge_count = len(kept_edges)
        removal_rate = float(removed_edge_count / raw_edge_count) if raw_edge_count else 0.0

        return kept_edges, {
            "enabled": True,
            "applied": True,
            "raw_edge_count": raw_edge_count,
            "kept_edge_count": kept_edge_count,
            "removed_edge_count": removed_edge_count,
            "removal_rate": round(removal_rate, 6),
            "reasons": dict(sorted(reason_counter.items(), key=lambda item: item[0])),
            "removed_edges": removed_edges[:30],
            "bypassed_missing_geometry_edges": missing_geometry_edges,
            "lane_mismatch_relaxed_kept": lane_mismatch_relaxed_kept,
            "edge_profile_counts": dict(sorted(profile_counter.items(), key=lambda item: item[0])),
            "spatial_context_available": True,
            "spatial_source": str(self.spatial_context.get("source", "none")),
            "calibrated_to_world": bool(self.spatial_context.get("calibrated_to_world", False)),
            "thresholds": dict(self.following_filter_config),
        }

    def _build_multigraph(self, graph_data: Dict[str, Any]) -> nx.MultiDiGraph:
        """
        Build a NetworkX MultiDiGraph from traffic scene graph triples to support multiple relations between same entities.
        """
        G = nx.MultiDiGraph()

        triples = graph_data.get("object_object_triples", [])
        for triple in triples:
            u = triple.get("subject")
            v = triple.get("object")
            rel = triple.get("relation")
            if not u or not v or not rel:
                continue
            if rel not in ALLOWED_RELATIONS:
                continue

            if not G.has_node(u):
                G.add_node(u, type=triple.get("subject_type", "UNKNOWN"))
            if not G.has_node(v):
                G.add_node(v, type=triple.get("object_type", "UNKNOWN"))

            G.add_edge(u, v, relation=rel)

        return G

    def _build_relation_index(self) -> Dict[str, Set[Tuple[str, str]]]:
        index: Dict[str, Set[Tuple[str, str]]] = {}
        for u, v, data in self.G.edges(data=True):
            relation = data.get("relation")
            if not relation:
                continue
            index.setdefault(relation, set()).add((u, v))
        return index

    def identify_yielding_disorder(self) -> List[Tuple[str, str]]:
        """
        治理一：让行规则失效与通行权失衡识别 (Yielding Disorder & RoW Imbalance)
        Identifies missing 'yielding_to' edges where 'conflict_with' exists.
        """
        disorders: List[Tuple[str, str]] = []
        conflict_edges = self.relation_index.get("conflict_with", set())
        yielding_edges = self.relation_index.get("yielding_to", set())

        for u, v in sorted(conflict_edges):
            has_yield = (u, v) in yielding_edges or (v, u) in yielding_edges
            if not has_yield:
                disorders.append((u, v))
        return disorders
        
    def trace_conflict_propagation(self) -> List[List[str]]:
        """
        治理二：关系链演化与冲突传播 (Conflict Propagation Chain)
        Traces chains such as A (conflict_with) B (following) C indicating secondary congestion.
        """
        propagation_chains: List[List[str]] = []
        chain_set: Set[Tuple[str, str, str]] = set()

        conflict_edges = self.relation_index.get("conflict_with", set())
        following_edges = self.relation_index.get("following", set())

        following_from: Dict[str, List[str]] = {}
        following_to: Dict[str, List[str]] = {}
        for src, dst in following_edges:
            following_from.setdefault(src, []).append(dst)
            following_to.setdefault(dst, []).append(src)

        for u, v in conflict_edges:
            for w in following_from.get(v, []):
                chain_set.add((u, v, w))
            for x in following_to.get(u, []):
                chain_set.add((x, u, v))

        for chain in sorted(chain_set):
            propagation_chains.append([chain[0], chain[1], chain[2]])

        return propagation_chains

    def diagnose_following_anomaly(self) -> Dict[str, Any]:
        """
        治理三：跟驰结构缓行治理 (Following Queue Profiling)
        Analyzes following structure for slow-moving convoy indicators.
        """
        following_edges = list(self.relation_index.get("following", set()))
        filtered_following_edges, filter_meta = self._filter_following_edges(following_edges)

        FG = nx.DiGraph()
        FG.add_edges_from(filtered_following_edges)

        merge_nodes: List[str] = []
        convoy_chains: List[List[str]] = []
        max_chain_length = 0
        cycle_detected = False
        node_count = FG.number_of_nodes()
        edge_count = FG.number_of_edges()
        queue_density = round((edge_count / max(1, node_count)), 4) if node_count else 0.0

        if len(FG.nodes) > 0:
            if nx.is_directed_acyclic_graph(FG):
                for comp_nodes in nx.weakly_connected_components(FG):
                    sub = nx.DiGraph(FG.subgraph(comp_nodes))
                    longest_path = [str(node) for node in nx.dag_longest_path(sub)]
                    if len(longest_path) >= 2:
                        chain_length = len(longest_path) - 1
                        max_chain_length = max(max_chain_length, chain_length)
                        if chain_length >= 2:
                            convoy_chains.append(longest_path)
            else:
                cycle_detected = True
                max_chain_length = -1

            for node in FG.nodes():
                if FG.in_degree(node) >= 2:
                    merge_nodes.append(node)

        convoy_chains = sorted(convoy_chains, key=len, reverse=True)
        convoy_count = len(convoy_chains)
        following_nodes = sorted(str(node) for node in FG.nodes())
        following_edges_detail = [
            {"subject": str(u), "object": str(v)}
            for u, v in sorted(FG.edges(), key=lambda item: (str(item[0]), str(item[1])))
        ]

        following_node_geometry: Dict[str, Dict[str, float]] = {}
        entity_geometry = self.spatial_context.get("entity_geometry")
        if isinstance(entity_geometry, dict):
            for node in following_nodes:
                geo = entity_geometry.get(node)
                if not isinstance(geo, dict):
                    continue
                following_node_geometry[node] = {
                    "x": float(geo.get("x", 0.0)),
                    "y": float(geo.get("y", 0.0)),
                    "heading_x": float(geo.get("heading_x", 0.0)),
                    "heading_y": float(geo.get("heading_y", 0.0)),
                    "object_type": self._resolve_node_type(node, geo),
                }

        following_lane_by_node: Dict[str, str] = {}
        lane_by_entity = self.spatial_context.get("lane_by_entity")
        if isinstance(lane_by_entity, dict):
            for node in following_nodes:
                lane_id = lane_by_entity.get(node)
                if lane_id is not None:
                    following_lane_by_node[node] = str(lane_id)

        following_lane_geometry: Dict[str, Dict[str, float]] = {}
        lane_geometry = self.spatial_context.get("lane_geometry")
        if isinstance(lane_geometry, dict):
            used_lanes = set(following_lane_by_node.values())
            for lane_id in used_lanes:
                lane_geo = lane_geometry.get(lane_id)
                if not isinstance(lane_geo, dict):
                    continue
                following_lane_geometry[lane_id] = {
                    "axis_x": float(lane_geo.get("axis_x", 1.0)),
                    "axis_y": float(lane_geo.get("axis_y", 0.0)),
                    "center_x": float(lane_geo.get("center_x", 0.0)),
                    "center_y": float(lane_geo.get("center_y", 0.0)),
                }

        queue_index = 0.0
        queue_index += min(max(max_chain_length, 0) / 6.0, 1.0) * 4.0
        queue_index += min(convoy_count / 3.0, 1.0) * 3.0
        queue_index += min(len(merge_nodes) / 2.0, 1.0) * 2.0
        queue_index += 1.0 if cycle_detected else 0.0
        queue_index += 1.0 if queue_density >= 1.0 else 0.0
        queue_index = round(min(queue_index, 10.0), 3)

        return {
            "max_following_chain": max_chain_length,
            "cycle_detected": cycle_detected,
            "node_count": node_count,
            "edge_count": edge_count,
            "raw_following_edge_count": int(filter_meta.get("raw_edge_count", edge_count)),
            "filtered_following_edge_count": int(filter_meta.get("kept_edge_count", edge_count)),
            "removed_following_edge_count": int(filter_meta.get("removed_edge_count", 0)),
            "queue_density": queue_density,
            "convoy_count": convoy_count,
            "convoy_chains": convoy_chains[:5],
            "following_nodes": following_nodes,
            "following_edges": following_edges_detail,
            "following_node_geometry": following_node_geometry,
            "following_lane_by_node": following_lane_by_node,
            "following_lane_geometry": following_lane_geometry,
            "following_filter": filter_meta,
            "merge_nodes": sorted(merge_nodes),
            "structural_bottlenecks": sorted(merge_nodes),
            "queue_index": queue_index,
        }

    def detect_multi_agent_deadlocks(self) -> List[List[str]]:
        """
        治理四：多边结构挖掘：多主体博弈僵局识别 (Multi-Agent Game Deadlocks)
        Identifies cycles of 'conflict_with' where no resolution (yield) exists.
        """
        conflict_edges = list(self.relation_index.get("conflict_with", set()))
        yielding_edges = self.relation_index.get("yielding_to", set())

        conflict_graph = nx.DiGraph(conflict_edges)
        deadlocks: List[List[str]] = []

        for cycle in nx.simple_cycles(conflict_graph):
            if len(cycle) < 2:
                continue

            unresolved = True
            for i in range(len(cycle)):
                cur_node = cycle[i]
                nxt_node = cycle[(i + 1) % len(cycle)]
                if (cur_node, nxt_node) in yielding_edges or (nxt_node, cur_node) in yielding_edges:
                    unresolved = False
                    break

            if unresolved:
                deadlocks.append(cycle)

        return deadlocks
