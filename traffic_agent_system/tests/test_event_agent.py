import unittest

from agents.cognitive_agents import EventAgent


class TestEventAgentSourceWeighting(unittest.TestCase):
    def test_truck_source_has_higher_priority(self):
        scene_insights = {
            "frame_id": "000001",
            "following_health": {
                "convoy_chains": [["A", "B", "C"]],
                "merge_nodes": ["A", "B"],
                "following_nodes": ["A", "B", "C"],
                "following_edges": [
                    {"subject": "A", "object": "B"},
                    {"subject": "B", "object": "C"},
                ],
                "following_node_geometry": {
                    "A": {"x": 0.0, "y": 0.0, "heading_x": 1.0, "heading_y": 0.0, "object_type": "CAR"},
                    "B": {"x": 10.0, "y": 0.0, "heading_x": 1.0, "heading_y": 0.0, "object_type": "TRUCK"},
                    "C": {"x": 20.0, "y": 0.0, "heading_x": 1.0, "heading_y": 0.0, "object_type": "CAR"},
                },
                "following_lane_by_node": {},
                "following_lane_geometry": {},
                "cycle_detected": False,
            },
        }

        event_agent = EventAgent(use_llm=False)
        payload = event_agent._build_slowdown_objects(scene_insights)

        self.assertGreaterEqual(len(payload["source_entities"]), 1)
        self.assertEqual(payload["source_entities"][0], "B")

        ranking = payload["source_summary"].get("source_weighted_ranking", [])
        self.assertTrue(ranking)
        self.assertEqual(ranking[0].get("entity"), "B")
        self.assertEqual(ranking[0].get("object_type"), "TRUCK")


if __name__ == "__main__":
    unittest.main()
