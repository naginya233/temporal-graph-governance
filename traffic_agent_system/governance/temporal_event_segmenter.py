from collections import Counter
from typing import Any, Dict, List


RISK_PRIORITY = {
    "low": 0,
    "medium": 1,
    "high": 2,
}


class TemporalEventSegmenter:
    """Convert frame-level risks into contiguous event segments."""

    def __init__(self, min_active_level: str = "medium"):
        self.min_active_level = min_active_level

    def _is_active(self, risk_level: str) -> bool:
        current = RISK_PRIORITY.get(risk_level, 0)
        threshold = RISK_PRIORITY.get(self.min_active_level, 1)
        return current >= threshold

    @staticmethod
    def _extract_risk(record: Dict[str, Any]) -> Dict[str, Any]:
        event_analysis = record.get("event_analysis") or {}
        if isinstance(event_analysis.get("risk"), dict):
            return event_analysis["risk"]
        if isinstance(event_analysis.get("calibrated_risk"), dict):
            return event_analysis["calibrated_risk"]
        return {}

    @staticmethod
    def _extract_causes(record: Dict[str, Any]) -> List[str]:
        risk = TemporalEventSegmenter._extract_risk(record)

        causes: List[str] = []
        if int(risk.get("yielding_cnt", 0)) > 0:
            causes.append("yielding_disorder")
        if int(risk.get("chain_cnt", 0)) > 0:
            causes.append("conflict_chain")
        if int(risk.get("deadlock_cnt", 0)) > 0:
            causes.append("deadlock")
        if bool(risk.get("cycle_detected", False)):
            causes.append("following_cycle")
        if int(risk.get("bottleneck_cnt", 0)) > 0 or int(risk.get("max_chain", 0)) >= 4:
            causes.append("following_bottleneck")

        if not causes and int(risk.get("score", 0)) > 0:
            causes.append("other_risk")
        return causes

    def _start_segment(self, record: Dict[str, Any], score: int, level: str) -> Dict[str, Any]:
        frame_id = record.get("frame_id")
        return {
            "start_frame": frame_id,
            "end_frame": frame_id,
            "frame_ids": [frame_id],
            "scores": [score],
            "peak_score": score,
            "peak_level": level,
            "peak_frame": frame_id,
            "cause_counter": Counter(self._extract_causes(record)),
        }

    def _append_segment_frame(
        self,
        segment: Dict[str, Any],
        record: Dict[str, Any],
        score: int,
        level: str,
    ) -> None:
        frame_id = record.get("frame_id")
        segment["end_frame"] = frame_id
        segment["frame_ids"].append(frame_id)
        segment["scores"].append(score)
        segment["cause_counter"].update(self._extract_causes(record))

        current_peak_score = int(segment["peak_score"])
        current_peak_level = str(segment["peak_level"])
        if score > current_peak_score or (
            score == current_peak_score and RISK_PRIORITY.get(level, 0) > RISK_PRIORITY.get(current_peak_level, 0)
        ):
            segment["peak_score"] = score
            segment["peak_level"] = level
            segment["peak_frame"] = frame_id

    @staticmethod
    def _finalize_segment(segment: Dict[str, Any], segment_id: int) -> Dict[str, Any]:
        scores: List[int] = segment["scores"]
        dominant_causes = [name for name, _ in segment["cause_counter"].most_common(3)]

        return {
            "segment_id": segment_id,
            "start_frame": segment["start_frame"],
            "end_frame": segment["end_frame"],
            "frame_count": len(segment["frame_ids"]),
            "peak_frame": segment["peak_frame"],
            "peak_score": int(segment["peak_score"]),
            "peak_level": segment["peak_level"],
            "mean_score": round(sum(scores) / max(1, len(scores)), 3),
            "dominant_causes": dominant_causes,
            "frames": segment["frame_ids"],
        }

    def segment(self, frame_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        segments: List[Dict[str, Any]] = []
        current_segment: Dict[str, Any] = {}

        for record in frame_records:
            risk = self._extract_risk(record)
            risk_level = str(risk.get("level", "low")).lower()
            score = int(risk.get("score", 0))

            if self._is_active(risk_level):
                if not current_segment:
                    current_segment = self._start_segment(record, score, risk_level)
                else:
                    self._append_segment_frame(current_segment, record, score, risk_level)
            elif current_segment:
                segments.append(self._finalize_segment(current_segment, len(segments) + 1))
                current_segment = {}

        if current_segment:
            segments.append(self._finalize_segment(current_segment, len(segments) + 1))

        return segments
