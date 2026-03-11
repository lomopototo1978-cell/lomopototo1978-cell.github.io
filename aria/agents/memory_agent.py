"""
ARIA Memory Agent — stores approved knowledge to Cosmos, manages the knowledge
graph, deduplicates with Agglomerative Clustering + PCA, retrieves via TF-IDF.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.decomposition import PCA
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from database.cosmos_client import AriaCosmosClient
from database.knowledge_graph import get_graph
from utils.config import CONTAINER_KNOWLEDGE, CONTAINER_LOGS
from utils.decay_manager import classify_knowledge_type, expiry_datetime, is_expired
from utils.text_processor import clean_for_ml, fingerprint, extract_keywords

logger = logging.getLogger(__name__)

_CLUSTER_DISTANCE_THRESHOLD = 0.5   # Agglomerative linkage threshold for dedup
_PCA_VARIANCE_THRESHOLD     = 0.95  # keep components that explain this much variance
_RETRIEVAL_TOP_K            = 10    # default results for retrieve()


class MemoryAgent:
    """
    Handles all Cosmos DB writes for approved knowledge.
    Manages knowledge graph auto-linking.
    Provides TF-IDF retrieval.
    Runs periodic dedup and expiry sweeps.
    """

    # ── Store ──────────────────────────────────────────────────────────────────

    async def store(self, item: dict) -> Optional[str]:
        """
        Store an APPROVED knowledge item.
        - Classifies knowledge type and sets expiry
        - Auto-links in knowledge graph
        - Returns the stored document id, or None if duplicate detected
        """
        content = item.get("content", "")
        topic   = item.get("topic", "")
        fp      = item.get("fingerprint") or fingerprint(content)

        knowledge_type = classify_knowledge_type(content, topic)
        expiry = expiry_datetime(knowledge_type)

        doc = {
            "subject":            {"category": topic or "general"},
            "content":            content,
            "source_url":         item.get("url", ""),
            "keywords":           item.get("keywords") or extract_keywords(content),
            "bias_score":         item.get("bias_score", 0),
            "source_score":       item.get("source_score", 0),
            "depth_score":        item.get("depth_score", 0),
            "dimension_analyses": item.get("dimension_analyses", {}),
            "fingerprint":        fp,
            "knowledge_type":     knowledge_type,
            "expires_at":         expiry.isoformat() if expiry else None,
            "topic":              topic,
            "verdict":            "APPROVED",
        }

        async with AriaCosmosClient() as db:
            # Check for exact fingerprint duplicate
            existing = await db.query(
                CONTAINER_KNOWLEDGE,
                "SELECT c.id FROM c WHERE c.fingerprint = @fp",
                params=[{"name": "@fp", "value": fp}],
            )
            if existing:
                logger.debug(f"Memory: duplicate fingerprint, skipping store: {fp[:16]}")
                return None

            stored = await db.upsert(CONTAINER_KNOWLEDGE, doc)
            doc_id = stored["id"]

            await db.log("memory_agent", "STORED", {
                "id": doc_id, "topic": topic, "type": knowledge_type
            })

        # Update knowledge graph
        graph = get_graph()
        graph.add_node(doc_id, {**doc, "id": doc_id})
        linked = graph.auto_link(doc_id, content)
        graph.save()

        logger.info(f"Memory: stored {doc_id} ({knowledge_type}), linked to {len(linked)} nodes")
        return doc_id

    # ── Retrieve ───────────────────────────────────────────────────────────────

    async def retrieve(self, query: str, topic: str = "",
                       top_k: int = _RETRIEVAL_TOP_K) -> list[dict]:
        """
        TF-IDF retrieval of relevant knowledge from Cosmos.
        Returns top_k most relevant non-expired documents.
        """
        async with AriaCosmosClient() as db:
            if topic:
                docs = await db.query(
                    CONTAINER_KNOWLEDGE,
                    "SELECT * FROM c WHERE c.topic = @topic AND c.verdict = 'APPROVED'",
                    params=[{"name": "@topic", "value": topic}],
                )
            else:
                docs = await db.query(
                    CONTAINER_KNOWLEDGE,
                    "SELECT * FROM c WHERE c.verdict = 'APPROVED'",
                )

        if not docs:
            return []

        # Filter out expired docs
        live_docs = [
            d for d in docs
            if not is_expired(d.get("knowledge_type", "general"), d.get("created_at", ""))
        ]

        if not live_docs:
            return []

        # TF-IDF rank
        texts = [clean_for_ml(d.get("content", "")) for d in live_docs]
        query_clean = clean_for_ml(query)

        try:
            vec = TfidfVectorizer(max_features=3000)
            matrix = vec.fit_transform(texts + [query_clean])
            sims = cosine_similarity(matrix[-1], matrix[:-1])[0]
            top_indices = np.argsort(sims)[::-1][:top_k]
            return [live_docs[i] for i in top_indices if sims[i] > 0]
        except Exception as e:
            logger.warning(f"TF-IDF retrieval failed: {e}")
            return live_docs[:top_k]

    # ── Dedup sweep (Agglomerative + PCA) ─────────────────────────────────────

    async def dedup_sweep(self) -> dict:
        """
        Fetch all knowledge, cluster with Agglomerative Clustering.
        Within each cluster, keep the highest depth_score doc and mark others
        as duplicates (verdict = 'DUPLICATE') in Cosmos.
        Returns stats.
        """
        async with AriaCosmosClient() as db:
            docs = await db.query(
                CONTAINER_KNOWLEDGE,
                "SELECT * FROM c WHERE c.verdict = 'APPROVED'",
            )

        if len(docs) < 4:
            return {"swept": 0, "duplicates_found": 0}

        texts = [clean_for_ml(d.get("content", "")) for d in docs]

        try:
            vec  = TfidfVectorizer(max_features=2000).fit_transform(texts).toarray()
            # PCA to reduce dimensionality before clustering
            n_components = min(len(docs) - 1, vec.shape[1], 50)
            if n_components >= 2:
                pca = PCA(n_components=n_components, random_state=42)
                vec = pca.fit_transform(vec)

            clustering = AgglomerativeClustering(
                n_clusters=None,
                distance_threshold=_CLUSTER_DISTANCE_THRESHOLD,
                metric="cosine",
                linkage="average",
            )
            labels = clustering.fit_predict(vec)
        except Exception as e:
            logger.warning(f"Dedup sweep clustering failed: {e}")
            return {"swept": len(docs), "duplicates_found": 0}

        duplicates_found = 0
        async with AriaCosmosClient() as db:
            # Group by cluster label
            from collections import defaultdict
            clusters: dict[int, list] = defaultdict(list)
            for doc, label in zip(docs, labels):
                clusters[label].append(doc)

            for cluster_docs in clusters.values():
                if len(cluster_docs) < 2:
                    continue
                # Keep highest depth_score
                best = max(cluster_docs, key=lambda d: d.get("depth_score", 0))
                for doc in cluster_docs:
                    if doc["id"] != best["id"]:
                        doc["verdict"] = "DUPLICATE"
                        await db.upsert(CONTAINER_KNOWLEDGE, doc)
                        duplicates_found += 1

        logger.info(f"Dedup sweep: {len(docs)} docs, {duplicates_found} duplicates marked")
        return {"swept": len(docs), "duplicates_found": duplicates_found}

    # ── Expiry sweep ───────────────────────────────────────────────────────────

    async def expiry_sweep(self) -> dict:
        """
        Mark expired knowledge items as EXPIRED in Cosmos.
        Returns count of expired items found.
        """
        async with AriaCosmosClient() as db:
            docs = await db.query(
                CONTAINER_KNOWLEDGE,
                "SELECT * FROM c WHERE c.verdict = 'APPROVED'",
            )

        expired_count = 0
        async with AriaCosmosClient() as db:
            for doc in docs:
                if is_expired(doc.get("knowledge_type", "general"),
                              doc.get("created_at", "")):
                    doc["verdict"] = "EXPIRED"
                    await db.upsert(CONTAINER_KNOWLEDGE, doc)
                    # Remove from graph
                    get_graph().remove_node(doc["id"])
                    expired_count += 1

        if expired_count:
            get_graph().save()

        logger.info(f"Expiry sweep: {expired_count} items expired")
        return {"expired": expired_count}

    # ── Stats ──────────────────────────────────────────────────────────────────

    async def stats(self) -> dict:
        async with AriaCosmosClient() as db:
            total    = await db.count(CONTAINER_KNOWLEDGE)
            approved = await db.count(CONTAINER_KNOWLEDGE, "c.verdict = 'APPROVED'")
            rejected = await db.count(CONTAINER_KNOWLEDGE, "c.verdict = 'REJECTED'")
            expired  = await db.count(CONTAINER_KNOWLEDGE, "c.verdict = 'EXPIRED'")
            dupes    = await db.count(CONTAINER_KNOWLEDGE, "c.verdict = 'DUPLICATE'")
        graph_stats = get_graph().stats()
        return {
            "total_docs":  total,
            "approved":    approved,
            "rejected":    rejected,
            "expired":     expired,
            "duplicates":  dupes,
            "graph":       graph_stats,
        }


# Module-level singleton
_agent: Optional[MemoryAgent] = None


def get_memory_agent() -> MemoryAgent:
    global _agent
    if _agent is None:
        _agent = MemoryAgent()
    return _agent
