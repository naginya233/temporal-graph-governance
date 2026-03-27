import unittest

from governance.temporal_event_segmenter import TemporalEventSegmenter


class TestTemporalEventSegmenter(unittest.TestCase):
    @staticmethod
    def _make_record(frame_id, level, score, yielding=0, chain=0, deadlock=0):
        return {
            "frame_id": frame_id,
            "event_analysis": {
                "risk": {
                    "level": level,
                    "score": score,
                    "yielding_cnt": yielding,
                    "chain_cnt": chain,
                    "deadlock_cnt": deadlock,
                    "bottleneck_cnt": 0,
                    "cycle_detected": False,
                    "max_chain": 0,
                }
            },
        }

    def test_contiguous_active_frames_form_one_segment(self):
        records = [
            self._make_record("000001", "low", 1),
            self._make_record("000002", "medium", 4, yielding=1),
            self._make_record("000003", "high", 10, deadlock=1),
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
        self.assertIn("yielding_disorder", segment["dominant_causes"])
        self.assertIn("deadlock", segment["dominant_causes"])

    def test_low_frame_splits_two_segments(self):
        records = [
            self._make_record("000010", "medium", 5, yielding=1),
            self._make_record("000011", "low", 0),
            self._make_record("000012", "high", 9, chain=1),
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
                        "yielding_cnt": 1,
                        "chain_cnt": 0,
                        "deadlock_cnt": 0,
                        "bottleneck_cnt": 0,
                        "cycle_detected": False,
                        "max_chain": 0,
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
