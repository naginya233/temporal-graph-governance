import unittest

from governance.temporal_consistency_calibrator import TemporalConsistencyCalibrator


class TestTemporalConsistencyCalibrator(unittest.TestCase):
    @staticmethod
    def _scene_with_edge(subject: str, relation: str, obj: str):
        return {
            "object_object_triples": [
                {
                    "subject": subject,
                    "relation": relation,
                    "object": obj,
                }
            ]
        }

    @staticmethod
    def _event_with_score(score: int, level: str):
        return {
            "risk": {
                "score": score,
                "level": level,
                "yielding_cnt": 0,
                "chain_cnt": 0,
                "deadlock_cnt": 0,
                "bottleneck_cnt": 0,
                "max_chain": 0,
                "cycle_detected": False,
            }
        }

    def test_persistent_edge_boosts_later_frame(self):
        calibrator = TemporalConsistencyCalibrator(
            alpha=1.0,
            persistence_window=2,
            persistent_boost=1.0,
            transient_penalty=1.0,
        )

        frame_1 = calibrator.calibrate(
            frame_id="000001",
            scene_graph_dict=self._scene_with_edge("A", "conflict_with", "B"),
            event_analysis=self._event_with_score(8, "high"),
        )
        frame_2 = calibrator.calibrate(
            frame_id="000002",
            scene_graph_dict=self._scene_with_edge("A", "conflict_with", "B"),
            event_analysis=self._event_with_score(8, "high"),
        )

        self.assertEqual(frame_1["calibrated_risk"]["score"], 7)
        self.assertEqual(frame_2["calibrated_risk"]["score"], 9)
        self.assertEqual(frame_2["calibrated_risk"]["level"], "high")

    def test_idle_decay_quickly_drops_after_risk_disappears(self):
        calibrator = TemporalConsistencyCalibrator(
            alpha=1.0,
            persistence_window=2,
            persistent_boost=1.0,
            transient_penalty=1.0,
            idle_decay=0.35,
        )

        calibrator.calibrate(
            frame_id="000010",
            scene_graph_dict=self._scene_with_edge("A", "conflict_with", "B"),
            event_analysis=self._event_with_score(10, "high"),
        )
        frame_2 = calibrator.calibrate(
            frame_id="000011",
            scene_graph_dict={"object_object_triples": []},
            event_analysis=self._event_with_score(0, "low"),
        )

        self.assertEqual(frame_2["calibrated_risk"]["score"], 3)
        self.assertEqual(frame_2["calibrated_risk"]["level"], "low")

        summary = calibrator.summary()
        self.assertEqual(summary["frames"], 2)
        self.assertGreaterEqual(summary["total_transient_edges"], 1)


if __name__ == "__main__":
    unittest.main()
