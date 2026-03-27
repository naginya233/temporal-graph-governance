from typing import Any, Dict, Tuple

from core.constants import ALLOWED_RELATIONS, VEHICLE_TYPES

class DynamicTopologyPruner:
    """
    边缘计算轻量化视语义剪枝模块 (Edge-Computing Lightweight Topology Pruner)
    对标报告第5章及第7.3节：交通知识引导的结构化剪枝掩码
    通过预先干预物理不可能产生的拓扑边，使得在后续图神经网络(GNN)或关系推演中的无效计算量大幅减少。
    """
    def __init__(self):
        self.pruned_edges_count = 0
        self.total_edges_count = 0
        self.pruned_by_reason: Dict[str, int] = {}

    def _mark_pruned(self, reason: str) -> None:
        self.pruned_edges_count += 1
        self.pruned_by_reason[reason] = self.pruned_by_reason.get(reason, 0) + 1

    @staticmethod
    def _is_vehicle(entity_type: str) -> bool:
        return entity_type in VEHICLE_TYPES

    def apply_knowledge_mask(self, graph_data: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        使用路网先验信息构建注意力掩码（Attention Mask）。
        在这里，我们转换为直接剪除图结构中的无效边，以模拟计算量的下降（降低推理延迟）。
        """
        if "object_object_triples" not in graph_data:
            return graph_data, {
                "total_edges": 0,
                "kept_edges": 0,
                "pruned_edges": 0,
                "compression_ratio": 0.0,
                "pruned_by_reason": {},
            }

        original_triples = graph_data["object_object_triples"]
        self.total_edges_count += len(original_triples)

        optimized_triples = []
        frame_pruned_count = 0
        frame_pruned_by_reason: Dict[str, int] = {}

        for triple in original_triples:
            u = triple.get("subject")
            v = triple.get("object")
            rel = triple.get("relation")
            subject_type = triple.get("subject_type", "UNKNOWN")
            object_type = triple.get("object_type", "UNKNOWN")

            reason = None
            if not u or not v or not rel:
                reason = "malformed_edge"
            elif rel not in ALLOWED_RELATIONS:
                reason = "unknown_relation"
            elif u == v:
                reason = "self_loop"
            elif rel == "following" and (
                not self._is_vehicle(subject_type) or not self._is_vehicle(object_type)
            ):
                reason = "invalid_following_type"

            if reason is not None:
                frame_pruned_count += 1
                frame_pruned_by_reason[reason] = frame_pruned_by_reason.get(reason, 0) + 1
                self._mark_pruned(reason)
                continue

            optimized_triples.append(triple)

        optimized_graph = graph_data.copy()
        optimized_graph["object_object_triples"] = optimized_triples

        total_edges = len(original_triples)
        kept_edges = len(optimized_triples)
        frame_ratio = (frame_pruned_count / total_edges) if total_edges else 0.0

        frame_stats = {
            "total_edges": total_edges,
            "kept_edges": kept_edges,
            "pruned_edges": frame_pruned_count,
            "compression_ratio": frame_ratio,
            "pruned_by_reason": frame_pruned_by_reason,
        }
        return optimized_graph, frame_stats

    def get_compression_ratio(self) -> float:
        """计算边缘轻量化率（节省的GNN算力比例）"""
        if self.total_edges_count == 0:
            return 0.0
        return self.pruned_edges_count / self.total_edges_count

    def get_global_stats(self) -> Dict[str, Any]:
        return {
            "total_edges": self.total_edges_count,
            "pruned_edges": self.pruned_edges_count,
            "compression_ratio": self.get_compression_ratio(),
            "pruned_by_reason": dict(self.pruned_by_reason),
        }
