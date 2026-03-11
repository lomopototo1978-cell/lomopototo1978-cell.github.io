"""
ARIA Knowledge Graph — networkx DiGraph, gpickle persistence.
Tracks relationships between knowledge items and detects sparse clusters.
"""
import logging
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import networkx as nx
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

_GRAPH_PATH = Path(__file__).parent.parent / "data" / "knowledge_graph.gpickle"
_LINK_SIMILARITY_THRESHOLD = 0.35   # min cosine sim to auto-link two nodes
_SPARSE_CLUSTER_MAX_DEGREE = 2      # nodes with <= this many edges = sparse


class KnowledgeGraph:
    """
    DiGraph where each node is a knowledge item (id = Cosmos doc id).
    Edges are directional relationships (cites, contradicts, supports, related).
    """

    def __init__(self):
        self._graph: nx.DiGraph = nx.DiGraph()

    # ── Persistence ────────────────────────────────────────────────────────────

    def save(self) -> None:
        _GRAPH_PATH.parent.mkdir(exist_ok=True)
        with open(_GRAPH_PATH, "wb") as f:
            pickle.dump(self._graph, f)

    def load(self) -> None:
        if _GRAPH_PATH.exists():
            with open(_GRAPH_PATH, "rb") as f:
                self._graph = pickle.load(f)
        else:
            self._graph = nx.DiGraph()

    def load_or_init(self) -> None:
        self.load()

    # ── Node management ────────────────────────────────────────────────────────

    def add_node(self, doc_id: str, metadata: dict) -> None:
        """Add or update a knowledge node."""
        self._graph.add_node(doc_id, **{
            "topic":      metadata.get("topic", ""),
            "keywords":   metadata.get("keywords", []),
            "subject":    metadata.get("subject", {}),
            "added_at":   datetime.now(timezone.utc).isoformat(),
            "content_snippet": (metadata.get("content", ""))[:200],
        })

    def remove_node(self, doc_id: str) -> None:
        if self._graph.has_node(doc_id):
            self._graph.remove_node(doc_id)

    def node_exists(self, doc_id: str) -> bool:
        return self._graph.has_node(doc_id)

    # ── Edge management ────────────────────────────────────────────────────────

    def add_edge(self, from_id: str, to_id: str,
                 relation: str = "related", weight: float = 1.0) -> None:
        """
        Add a directional edge.
        relation: 'related' | 'supports' | 'contradicts' | 'cites'
        """
        self._graph.add_edge(from_id, to_id, relation=relation, weight=weight)

    # ── Auto-linking ───────────────────────────────────────────────────────────

    def auto_link(self, doc_id: str, content: str, top_k: int = 5) -> list[str]:
        """
        Compare `content` against all existing nodes using TF-IDF cosine similarity.
        Auto-link to the top_k most similar nodes above threshold.
        Returns list of linked node IDs.
        """
        nodes = list(self._graph.nodes)
        if not nodes:
            return []

        snippets = [
            self._graph.nodes[n].get("content_snippet", "") for n in nodes
        ]
        snippets_nonempty = [(n, s) for n, s in zip(nodes, snippets) if s.strip()]
        if not snippets_nonempty:
            return []

        node_ids, texts = zip(*snippets_nonempty)
        all_texts = list(texts) + [content[:200]]

        try:
            vec = TfidfVectorizer(max_features=1000).fit_transform(all_texts)
            sims = cosine_similarity(vec[-1], vec[:-1])[0]
            top_indices = np.argsort(sims)[::-1][:top_k]
            linked = []
            for idx in top_indices:
                sim = float(sims[idx])
                if sim >= _LINK_SIMILARITY_THRESHOLD:
                    target = node_ids[idx]
                    if target != doc_id:
                        self.add_edge(doc_id, target, relation="related", weight=round(sim, 3))
                        linked.append(target)
            return linked
        except Exception as e:
            logger.warning(f"Auto-link failed: {e}")
            return []

    # ── Sparse cluster detection ───────────────────────────────────────────────

    def sparse_nodes(self, max_degree: int = _SPARSE_CLUSTER_MAX_DEGREE) -> list[str]:
        """
        Return list of node IDs that are poorly connected (degree <= max_degree).
        These represent knowledge gaps or isolated facts.
        """
        return [
            n for n in self._graph.nodes
            if self._graph.degree(n) <= max_degree
        ]

    def sparse_topics(self) -> list[str]:
        """Return unique topics of sparse nodes — useful for directing Scout."""
        sparse = self.sparse_nodes()
        topics = set()
        for n in sparse:
            t = self._graph.nodes[n].get("topic", "")
            if t:
                topics.add(t)
        return list(topics)

    # ── Stats ──────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        g = self._graph
        return {
            "nodes":         g.number_of_nodes(),
            "edges":         g.number_of_edges(),
            "sparse_nodes":  len(self.sparse_nodes()),
            "sparse_topics": self.sparse_topics(),
            "avg_degree":    round(
                sum(d for _, d in g.degree()) / max(g.number_of_nodes(), 1), 2
            ),
        }

    def get_neighbours(self, doc_id: str) -> list[str]:
        return list(self._graph.successors(doc_id))

    def get_path(self, from_id: str, to_id: str) -> list[str]:
        try:
            return nx.shortest_path(self._graph, from_id, to_id)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []


# Module-level singleton
_graph: Optional[KnowledgeGraph] = None


def get_graph() -> KnowledgeGraph:
    global _graph
    if _graph is None:
        _graph = KnowledgeGraph()
        _graph.load_or_init()
    return _graph
