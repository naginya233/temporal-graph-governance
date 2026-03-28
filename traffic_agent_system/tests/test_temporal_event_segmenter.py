import unittest

from governance.temporal_event_segmenter import TemporalEventSegmenter


class TestTemporalEventSegmenter(unittest.TestCase):
    @staticmethod
    def _make_record(frame_id, level, score, convoy=0, merge=0, max_chain=0, density=0.0):
        return {
            "frame_id": frame_id,
            "event_analysis": {
                "risk": {
                    "level": level,
                    "score": score,
                    "yielding_cnt": 0,
                    "chain_cnt": 0,
                    "deadlock_cnt": 0,
                    "bottleneck_cnt": 0,
                    "convoy_cnt": convoy,
                    "merge_cnt": merge,
                    "queue_density": density,
                    "cycle_detected": False,
                    "max_chain": max_chain,
                }
            },
        }

    def test_contiguous_active_frames_form_one_segment(self):
        records = [
            self._make_record("000001", "low", 1),
            self._make_record("000002", "medium", 4, convoy=1, max_chain=4),
            self._make_record("000003", "high", 10, convoy=2, merge=1, max_chain=7),
            self._make_record("000004", "low", 1),
        ]

        segmenter = TemporalEventSegmenter(min_active_level="medium")
        segments = segmenter.segment(records)

        self.assertEqual(len(segments), 1)
        segment = segments[0]
        self.assertEqual(segment["start_frame"], "000002")
        self.assertEqual(segment["end_frame"], "000003")
        self.assertEqual(segment["peak_frame"], "000003")
        self.assertEqual(segment["peak_score"], 10)
        self.assertIn("long_convoy", segment["dominant_causes"])
        self.assertIn("multi_convoy", segment["dominant_causes"])

    def test_low_frame_splits_two_segments(self):
        records = [
            self._make_record("000010", "medium", 5, convoy=1, max_chain=4),
            self._make_record("000011", "low", 0),
            self._make_record("000012", "high", 9, convoy=2, merge=1, max_chain=6),
        ]

        segmenter = TemporalEventSegmenter(min_active_level="medium")
        segments = segmenter.segment(records)

        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0]["start_frame"], "000010")
        self.assertEqual(segments[1]["start_frame"], "000012")

    def test_calibrated_risk_fallback_supported(self):
        records = [
            {
                "frame_id": "000020",
                "event_analysis": {
                    "calibrated_risk": {
                        "level": "high",
                        "score": 9,
                            "yielding_cnt": 0,
                        "chain_cnt": 0,
                        "deadlock_cnt": 0,
                        "bottleneck_cnt": 0,
                            "convoy_cnt": 1,
                            "merge_cnt": 0,
                            "queue_density": 0.8,
                        "cycle_detected": False,
                            "max_chain": 4,
                    }
                },
            }
        ]

        segmenter = TemporalEventSegmenter(min_active_level="medium")
        segments = segmenter.segment(records)

        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["start_frame"], "000020")


if __name__ == "__main__":
    unittest.main()
