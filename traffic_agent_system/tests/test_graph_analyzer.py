import unittest

from governance.graph_analyzer import TrafficGraphAnalyzer


class TestTrafficGraphAnalyzer(unittest.TestCase):
    def test_following_convoy_detected(self):
        graph_data = {
            "object_object_triples": [
                {
                    "subject": "A",
                    "subject_type": "CAR",
                    "relation": "following",
                    "object": "B",
                    "object_type": "CAR",
                },
                {
                    "subject": "B",
                    "subject_type": "CAR",
                    "relation": "following",
                    "object": "C",
                    "object_type": "CAR",
                }
            ]
        }
        analyzer = TrafficGraphAnalyzer(graph_data)
        following = analyzer.diagnose_following_anomaly()
        self.assertEqual(following["max_following_chain"], 2)
        self.assertGreaterEqual(following["convoy_count"], 1)

    def test_merge_node_detected(self):
        graph_data = {
            "object_object_triples": [
                {
                    "subject": "A",
                    "subject_type": "CAR",
                    "relation": "following",
                    "object": "C",
                    "object_type": "CAR",
                },
                {
                    "subject": "B",
                    "subject_type": "CAR",
                    "relation": "following",
                    "object": "C",
                    "object_type": "CAR",
                },
            ]
        }
        analyzer = TrafficGraphAnalyzer(graph_data)
        following = analyzer.diagnose_following_anomaly()
        self.assertIn("C", following["merge_nodes"])

    def test_following_cycle_detected(self):
        graph_data = {
            "object_object_triples": [
                {
                    "subject": "A",
                    "subject_type": "CAR",
                    "relation": "following",
                    "object": "B",
                    "object_type": "CAR",
                },
                {
                    "subject": "B",
                    "subject_type": "CAR",
                    "relation": "following",
                    "object": "A",
                    "object_type": "CAR",
                },
            ]
        }
        analyzer = TrafficGraphAnalyzer(graph_data)
        following = analyzer.diagnose_following_anomaly()
        self.assertTrue(following["cycle_detected"])
        self.assertEqual(following["max_following_chain"], -1)

    def test_spatial_filter_removes_reverse_following_edge(self):
        graph_data = {
            "object_object_triples": [
                {
                    "subject": "A",
                    "subject_type": "CAR",
                    "relation": "following",
                    "object": "B",
                    "object_type": "CAR",
                },
                {
                    "subject": "B",
                    "subject_type": "CAR",
                    "relation": "following",
                    "object": "A",
                    "object_type": "CAR",
                },
            ]
        }
        spatial_context = {
            "entity_geometry": {
                "A": {"x": 0.0, "y": 0.0, "heading_x": 1.0, "heading_y": 0.0},
                "B": {"x": 10.0, "y": 0.0, "heading_x": 1.0, "heading_y": 0.0},
            },
            "lane_by_entity": {
                "A": "lane_1",
                "B": "lane_1",
            },
            "source": "test",
            "calibrated_to_world": True,
        }

        analyzer = TrafficGraphAnalyzer(
            graph_data,
            spatial_context=spatial_context,
            following_filter={
                "enabled": True,
                "min_longitudinal_gap": 0.5,
                "max_longitudinal_gap": 50.0,
                "max_lateral_offset": 5.0,
                "min_heading_cos": 0.0,
                "require_same_lane": False,
            },
        )
        following = analyzer.diagnose_following_anomaly()

        self.assertEqual(following["raw_following_edge_count"], 2)
        self.assertEqual(following["filtered_following_edge_count"], 1)
        self.assertEqual(following["removed_following_edge_count"], 1)
        self.assertFalse(following["cycle_detected"])
        self.assertEqual(following["following_filter"]["reasons"].get("not_ahead", 0), 1)

    def test_spatial_filter_can_require_same_lane(self):
        graph_data = {
            "object_object_triples": [
                {
                    "subject": "A",
                    "subject_type": "CYCLIST",
                    "relation": "following",
                    "object": "B",
                    "object_type": "CYCLIST",
                }
            ],
            "object_map_triples": [
                {
                    "subject": "A",
                    "relation": "in",
                    "object": "lane_left",
                    "object_type": "LANE_CITY_DRIVING",
                },
                {
                    "subject": "B",
                    "relation": "in",
                    "object": "lane_right",
                    "object_type": "LANE_CITY_DRIVING",
                },
            ],
        }
        spatial_context = {
            "entity_geometry": {
                "A": {"x": 0.0, "y": 0.0, "heading_x": 1.0, "heading_y": 0.0},
                "B": {"x": 12.0, "y": 0.1, "heading_x": 1.0, "heading_y": 0.0},
            }
        }

        analyzer = TrafficGraphAnalyzer(
            graph_data,
            spatial_context=spatial_context,
            following_filter={
                "enabled": True,
                "min_longitudinal_gap": 0.5,
                "max_longitudinal_gap": 50.0,
                "max_lateral_offset": 5.0,
                "min_heading_cos": -0.5,
                "require_same_lane": True,
            },
        )
        following = analyzer.diagnose_following_anomaly()

        self.assertEqual(following["filtered_following_edge_count"], 0)
        self.assertEqual(following["removed_following_edge_count"], 1)
        self.assertEqual(following["following_filter"]["reasons"].get("lane_mismatch", 0), 1)

    def test_motorized_pair_uses_relaxed_lateral_threshold(self):
        graph_data = {
            "object_object_triples": [
                {
                    "subject": "A",
                    "subject_type": "CAR",
                    "relation": "following",
                    "object": "B",
                    "object_type": "CAR",
                }
            ]
        }
        spatial_context = {
            "entity_geometry": {
                "A": {"x": 0.0, "y": 0.0, "heading_x": 1.0, "heading_y": 0.0},
                "B": {"x": 12.0, "y": 3.8, "heading_x": 1.0, "heading_y": 0.0},
            }
        }

        analyzer = TrafficGraphAnalyzer(
            graph_data,
            spatial_context=spatial_context,
            following_filter={
                "enabled": True,
                "min_longitudinal_gap": 0.5,
                "max_longitudinal_gap": 50.0,
                "max_lateral_offset": 3.2,
                "min_heading_cos": 0.0,
                "require_same_lane": False,
            },
        )
        following = analyzer.diagnose_following_anomaly()

        self.assertEqual(following["filtered_following_edge_count"], 1)
        self.assertEqual(following["removed_following_edge_count"], 0)
        self.assertEqual(following["following_filter"]["edge_profile_counts"].get("motorized_pair", 0), 1)

    def test_non_motorized_pair_uses_stricter_lateral_threshold(self):
        graph_data = {
            "object_object_triples": [
                {
                    "subject": "A",
                    "subject_type": "CYCLIST",
                    "relation": "following",
                    "object": "B",
                    "object_type": "CYCLIST",
                }
            ]
        }
        spatial_context = {
            "entity_geometry": {
                "A": {"x": 0.0, "y": 0.0, "heading_x": 1.0, "heading_y": 0.0},
                "B": {"x": 10.0, "y": 2.8, "heading_x": 1.0, "heading_y": 0.0},
            }
        }

        analyzer = TrafficGraphAnalyzer(
            graph_data,
            spatial_context=spatial_context,
            following_filter={
                "enabled": True,
                "min_longitudinal_gap": 0.5,
                "max_longitudinal_gap": 50.0,
                "max_lateral_offset": 3.2,
                "min_heading_cos": 0.0,
                "require_same_lane": False,
            },
        )
        following = analyzer.diagnose_following_anomaly()

        self.assertEqual(following["filtered_following_edge_count"], 0)
        self.assertEqual(following["removed_following_edge_count"], 1)
        self.assertEqual(following["following_filter"]["reasons"].get("too_far_lateral", 0), 1)
        self.assertEqual(following["following_filter"]["edge_profile_counts"].get("non_motorized_pair", 0), 1)

    def test_motorized_lane_mismatch_is_soft_constraint(self):
        graph_data = {
            "object_object_triples": [
                {
                    "subject": "A",
                    "subject_type": "CAR",
                    "relation": "following",
                    "object": "B",
                    "object_type": "VAN",
                }
            ],
            "object_map_triples": [
                {
                    "subject": "A",
                    "relation": "in",
                    "object": "lane_left",
                    "object_type": "LANE_CITY_DRIVING",
                },
                {
                    "subject": "B",
                    "relation": "in",
                    "object": "lane_right",
                    "object_type": "LANE_CITY_DRIVING",
                },
            ],
        }
        spatial_context = {
            "entity_geometry": {
                "A": {"x": 0.0, "y": 0.0, "heading_x": 1.0, "heading_y": 0.0},
                "B": {"x": 12.0, "y": 1.2, "heading_x": 1.0, "heading_y": 0.0},
            }
        }

        analyzer = TrafficGraphAnalyzer(
            graph_data,
            spatial_context=spatial_context,
            following_filter={
                "enabled": True,
                "min_longitudinal_gap": 0.5,
                "max_longitudinal_gap": 50.0,
                "max_lateral_offset": 3.2,
                "min_heading_cos": 0.0,
                "require_same_lane": True,
            },
        )
        following = analyzer.diagnose_following_anomaly()

        self.assertEqual(following["filtered_following_edge_count"], 1)
        self.assertEqual(following["removed_following_edge_count"], 0)
        self.assertGreaterEqual(following["following_filter"].get("lane_mismatch_relaxed_kept", 0), 1)


if __name__ == "__main__":
    unittest.main()
