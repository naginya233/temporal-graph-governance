import unittest

from governance.graph_analyzer import TrafficGraphAnalyzer


class TestTrafficGraphAnalyzer(unittest.TestCase):
    def test_yielding_disorder_detected_without_yield_edge(self):
        graph_data = {
            "object_object_triples": [
                {
                    "subject": "A",
                    "subject_type": "CAR",
                    "relation": "conflict_with",
                    "object": "B",
                    "object_type": "CAR",
                }
            ]
        }
        analyzer = TrafficGraphAnalyzer(graph_data)
        disorders = analyzer.identify_yielding_disorder()
        self.assertEqual(disorders, [("A", "B")])

    def test_yielding_disorder_resolved_by_yield_relation(self):
        graph_data = {
            "object_object_triples": [
                {
                    "subject": "A",
                    "subject_type": "CAR",
                    "relation": "conflict_with",
                    "object": "B",
                    "object_type": "CAR",
                },
                {
                    "subject": "B",
                    "subject_type": "CAR",
                    "relation": "yielding_to",
                    "object": "A",
                    "object_type": "CAR",
                },
            ]
        }
        analyzer = TrafficGraphAnalyzer(graph_data)
        disorders = analyzer.identify_yielding_disorder()
        self.assertEqual(disorders, [])

    def test_conflict_propagation_chain(self):
        graph_data = {
            "object_object_triples": [
                {
                    "subject": "A",
                    "subject_type": "CAR",
                    "relation": "conflict_with",
                    "object": "B",
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
        chains = analyzer.trace_conflict_propagation()
        self.assertIn(["A", "B", "C"], chains)

    def test_deadlock_cycle_detected(self):
        graph_data = {
            "object_object_triples": [
                {
                    "subject": "A",
                    "subject_type": "CAR",
                    "relation": "conflict_with",
                    "object": "B",
                    "object_type": "CAR",
                },
                {
                    "subject": "B",
                    "subject_type": "CAR",
                    "relation": "conflict_with",
                    "object": "A",
                    "object_type": "CAR",
                },
            ]
        }
        analyzer = TrafficGraphAnalyzer(graph_data)
        deadlocks = analyzer.detect_multi_agent_deadlocks()
        self.assertTrue(any(set(cycle) == {"A", "B"} for cycle in deadlocks))


if __name__ == "__main__":
    unittest.main()
