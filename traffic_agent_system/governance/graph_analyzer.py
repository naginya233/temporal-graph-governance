from typing import Any, Dict, List, Set, Tuple

import networkx as nx

from core.constants import ALLOWED_RELATIONS

class TrafficGraphAnalyzer:
    """
    Traffic Scene Graph Analyzer for relation-driven governance.
    Implements advanced graph-theoretic algorithms to detect traffic anomalies based on the Section 6 of the research report.
    """
    def __init__(self, graph_data: Dict[str, Any]):
        self.raw_data = graph_data
        self.G = self._build_multigraph(graph_data)
        self.relation_index = self._build_relation_index()

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
        治理三：跟驰结构异常治理 (Following Structure Anomaly)
        Analyzes the 'following' tree structure to find bottlenecks (nodes acting as root blockers).
        """
        following_edges = list(self.relation_index.get("following", set()))
        FG = nx.DiGraph()
        FG.add_edges_from(following_edges)

        bottlenecks: List[str] = []
        max_chain_length = 0
        cycle_detected = False
        node_count = FG.number_of_nodes()
        edge_count = FG.number_of_edges()

        if len(FG.nodes) > 0:
            if nx.is_directed_acyclic_graph(FG):
                longest_path = nx.dag_longest_path(FG)
                max_chain_length = max(0, len(longest_path) - 1)
            else:
                cycle_detected = True
                max_chain_length = -1

            for node in FG.nodes():
                if FG.in_degree(node) >= 2 and FG.out_degree(node) <= 1:
                    bottlenecks.append(node)

        return {
            "max_following_chain": max_chain_length,
            "cycle_detected": cycle_detected,
            "node_count": node_count,
            "edge_count": edge_count,
            "structural_bottlenecks": sorted(bottlenecks),
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
