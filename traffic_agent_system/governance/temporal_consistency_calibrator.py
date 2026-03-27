from typing import Any, Dict, List, Set, Tuple

RISK_RELATIONS = {
    "conflict_with",
    "yielding_to",
    "crossing",
}


def _risk_level_from_score(score: float) -> str:
    if score >= 8:
        return "high"
    if score >= 4:
        return "medium"
    return "low"


class TemporalConsistencyCalibrator:
    """Temporal consistency calibrator for frame-level risk outputs.

    The module adjusts risk by combining:
    1) persistence boost for stable risky relation edges,
    2) transient penalty for one-frame noisy edges,
    3) exponential moving average smoothing across frames.
    """

    def __init__(
        self,
        alpha: float = 0.7,
        persistence_window: int = 2,
        persistent_boost: float = 0.6,
        transient_penalty: float = 0.5,
        idle_decay: float = 0.35,
    ):
        self.alpha = max(0.0, min(1.0, float(alpha)))
        self.persistence_window = max(1, int(persistence_window))
        self.persistent_boost = max(0.0, float(persistent_boost))
        self.transient_penalty = max(0.0, float(transient_penalty))
        self.idle_decay = max(0.0, min(1.0, float(idle_decay)))

        self.prev_risky_edges: Set[Tuple[str, str, str]] = set()
        self.edge_streak: Dict[Tuple[str, str, str], int] = {}
        self.ema_score: float = 0.0
        self.frame_count: int = 0

        self.total_persistent_edges: int = 0
        self.total_transient_edges: int = 0
        self.total_jaccard: float = 0.0
        self.changed_level_frames: int = 0

    @staticmethod
    def _extract_risky_edges(scene_graph_dict: Dict[str, Any]) -> Set[Tuple[str, str, str]]:
        edges: Set[Tuple[str, str, str]] = set()
        triples = scene_graph_dict.get("object_object_triples", [])
        for triple in triples:
            relation = triple.get("relation")
            if relation not in RISK_RELATIONS:
                continue

            subject = str(triple.get("subject", ""))
            obj = str(triple.get("object", ""))
            if not subject or not obj:
                continue

            edges.add((subject, relation, obj))
        return edges

    @staticmethod
    def _jaccard(a: Set[Tuple[str, str, str]], b: Set[Tuple[str, str, str]]) -> float:
        union = a | b
        if not union:
            return 1.0
        return len(a & b) / len(union)

    def _update_streak(self, current_edges: Set[Tuple[str, str, str]]) -> None:
        new_streak: Dict[Tuple[str, str, str], int] = {}
        for edge in current_edges:
            new_streak[edge] = self.edge_streak.get(edge, 0) + 1
        self.edge_streak = new_streak

    def calibrate(
        self,
        frame_id: str,
        scene_graph_dict: Dict[str, Any],
        event_analysis: Dict[str, Any],
    ) -> Dict[str, Any]:
        raw_risk = dict(event_analysis.get("risk", {}))
        raw_score = float(raw_risk.get("score", 0))

        current_edges = self._extract_risky_edges(scene_graph_dict)
        self._update_streak(current_edges)

        persistent_edges = {e for e, streak in self.edge_streak.items() if streak >= self.persistence_window}
        transient_edges = {e for e in current_edges if e not in self.prev_risky_edges and self.edge_streak.get(e, 0) <= 1}

        jaccard = self._jaccard(current_edges, self.prev_risky_edges)
        temporal_adjust = (len(persistent_edges) * self.persistent_boost) - (len(transient_edges) * self.transient_penalty)

        if raw_score > 0:
            adjusted_score = max(0.0, raw_score + temporal_adjust)
            smoothed_score = (self.alpha * adjusted_score) + ((1.0 - self.alpha) * self.ema_score)
        else:
            smoothed_score = self.ema_score * self.idle_decay

        calibrated_score = int(round(smoothed_score))
        calibrated_level = _risk_level_from_score(calibrated_score)

        raw_level = str(raw_risk.get("level", _risk_level_from_score(raw_score))).lower()
        if calibrated_level != raw_level:
            self.changed_level_frames += 1

        calibrated_risk = dict(raw_risk)
        calibrated_risk.update(
            {
                "score": calibrated_score,
                "level": calibrated_level,
                "raw_score": raw_score,
                "raw_level": raw_level,
                "temporal_jaccard": round(jaccard, 6),
                "persistent_edge_count": len(persistent_edges),
                "transient_edge_count": len(transient_edges),
                "temporal_adjustment": round(temporal_adjust, 6),
                "ema_score": round(smoothed_score, 6),
                "calibration_enabled": True,
            }
        )

        self.prev_risky_edges = current_edges
        self.ema_score = smoothed_score
        self.frame_count += 1
        self.total_persistent_edges += len(persistent_edges)
        self.total_transient_edges += len(transient_edges)
        self.total_jaccard += jaccard

        return {
            "frame_id": frame_id,
            "raw_risk": raw_risk,
            "calibrated_risk": calibrated_risk,
            "temporal_features": {
                "risky_edge_count": len(current_edges),
                "persistent_edge_count": len(persistent_edges),
                "transient_edge_count": len(transient_edges),
                "jaccard_with_previous": round(jaccard, 6),
            },
        }

    def summary(self) -> Dict[str, Any]:
        avg_jaccard = self.total_jaccard / self.frame_count if self.frame_count else 0.0
        return {
            "enabled": True,
            "frames": self.frame_count,
            "avg_jaccard": round(avg_jaccard, 6),
            "total_persistent_edges": self.total_persistent_edges,
            "total_transient_edges": self.total_transient_edges,
            "changed_level_frames": self.changed_level_frames,
            "alpha": self.alpha,
            "persistence_window": self.persistence_window,
            "persistent_boost": self.persistent_boost,
            "transient_penalty": self.transient_penalty,
            "idle_decay": self.idle_decay,
        }
