"""
ARIA Training Builder — ranks approved knowledge for BaobabGPT fine-tuning.
XGBRanker scores each item on 6 quality features, saves a ranked JSON dataset.
"""
import json
import logging
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.preprocessing import MinMaxScaler

from database.cosmos_client import AriaCosmosClient
from utils.config import CONTAINER_KNOWLEDGE, CONTAINER_TRAINING, CONTAINER_LOGS
from utils.decay_manager import days_until_expiry
from utils.text_processor import word_count, content_density

logger = logging.getLogger(__name__)

_MODELS_DIR  = Path(__file__).parent.parent / "ml" / "models"
_RANKER_PATH = _MODELS_DIR / "training_ranker.pkl"
_DATA_DIR    = Path(__file__).parent.parent / "data"
_OUTPUT_JSON = _DATA_DIR / "training_ranked.json"

# ── 6 quality features ─────────────────────────────────────────────────────────
#   source_score, bias_score (inverted), depth_score,
#   word_count_norm, content_density, freshness_score

FEATURE_NAMES = [
    "source_score",
    "bias_score_inv",     # 1 - bias_score (lower bias = better)
    "depth_score",
    "word_count_norm",    # normalised 0-1 by MinMaxScaler
    "content_density",
    "freshness_score",    # 0-1 based on days_until_expiry / max_ttl
]


def _extract_features(doc: dict) -> list[float]:
    """Extract the 6 quality features from a Cosmos document."""
    content = doc.get("content", "")
    ktype   = doc.get("knowledge_type", "general")
    created = doc.get("created_at", datetime.now(timezone.utc).isoformat())

    wc = word_count(content)
    cd = content_density(content)

    days = days_until_expiry(ktype, created)
    if days is None:          # never expires = maximum freshness
        freshness = 1.0
    elif days <= 0:
        freshness = 0.0
    else:
        # Map to 0-1: cap at 365 days
        freshness = min(days / 365.0, 1.0)

    return [
        float(doc.get("source_score", 0.5)),
        1.0 - float(doc.get("bias_score", 0.5)),
        float(doc.get("depth_score", 0.5)),
        float(min(wc, 2000) / 2000),   # raw word count normalised to 2000-word cap
        float(cd),
        freshness,
    ]


class TrainingBuilder:
    """
    Loads approved knowledge from Cosmos, scores with XGBRanker,
    and saves a ranked training JSON file ready for BaobabGPT fine-tuning.
    """

    def __init__(self):
        self._ranker: Optional[xgb.XGBRanker] = None
        self._scaler = MinMaxScaler()
        self._load_ranker()

    # ── Ranker bootstrap ───────────────────────────────────────────────────────

    def _build_seed_ranker(self) -> xgb.XGBRanker:
        """
        Seed the ranker with synthetic preference pairs so it can score
        before real feedback accumulates.
        High-quality: source_score=0.9, bias=0.1, depth=0.8, wc=0.7, cd=0.7, fresh=0.9
        Low-quality:  source_score=0.2, bias=0.8, depth=0.2, wc=0.1, cd=0.1, fresh=0.1
        """
        n_high, n_low = 20, 20
        high = np.tile([0.9, 0.9, 0.8, 0.7, 0.7, 0.9], (n_high, 1))
        low  = np.tile([0.2, 0.2, 0.2, 0.1, 0.1, 0.1], (n_low,  1))
        X    = np.vstack([high, low])
        y    = np.array([2] * n_high + [1] * n_low)   # relevance labels
        qid  = np.zeros(n_high + n_low, dtype=np.int32)

        ranker = xgb.XGBRanker(
            objective="rank:pairwise",
            n_estimators=50,
            max_depth=4,
            learning_rate=0.1,
            random_state=42,
        )
        ranker.fit(X, y, qid=qid)
        return ranker

    def _load_ranker(self) -> None:
        if _RANKER_PATH.exists():
            with open(_RANKER_PATH, "rb") as f:
                data = pickle.load(f)
                self._ranker = data["ranker"]
                self._scaler = data.get("scaler", MinMaxScaler())
        else:
            self._ranker = self._build_seed_ranker()
            self._save_ranker()

    def _save_ranker(self) -> None:
        _MODELS_DIR.mkdir(exist_ok=True)
        with open(_RANKER_PATH, "wb") as f:
            pickle.dump({"ranker": self._ranker, "scaler": self._scaler}, f)

    # ── Score document ─────────────────────────────────────────────────────────

    def score(self, doc: dict) -> float:
        """Return a quality score 0-1 for a single document."""
        features = np.array([_extract_features(doc)])
        raw = self._ranker.predict(features)
        # Normalise prediction to 0-1 via sigmoid
        val = float(1 / (1 + np.exp(-raw[0])))
        return round(val, 4)

    # ── Retrain on feedback ────────────────────────────────────────────────────

    async def retrain(self) -> dict:
        """
        Fetch labelled training_data from Cosmos (adversarial + manual corrections),
        add feature vectors, retrain XGBRanker. Returns updated stats.
        """
        async with AriaCosmosClient() as db:
            approved = await db.query(
                CONTAINER_KNOWLEDGE,
                "SELECT * FROM c WHERE c.verdict = 'APPROVED'",
            )
            training_docs = await db.query(
                CONTAINER_TRAINING,
                "SELECT * FROM c WHERE c.type = 'qwen_correction'",
            )

        if len(approved) < 10:
            return {"status": "skipped", "reason": f"only {len(approved)} approved docs (need 10+)"}

        # Build feature matrix from approved knowledge
        X_list, y_list = [], []
        for doc in approved:
            feats = _extract_features(doc)
            label = 2 if doc.get("depth_score", 0) > 0.5 else 1
            X_list.append(feats)
            y_list.append(label)

        # Add corrections as high-quality examples (label=3)
        for doc in training_docs:
            if doc.get("corrected_content"):
                feats = _extract_features({
                    "content":      doc["corrected_content"],
                    "source_score": 0.85,
                    "bias_score":   0.1,
                    "depth_score":  0.8,
                    "knowledge_type": "scientific_fact",
                    "created_at":   doc.get("created_at", ""),
                })
                X_list.append(feats)
                y_list.append(3)

        X   = np.array(X_list)
        y   = np.array(y_list)
        qid = np.zeros(len(y), dtype=np.int32)

        # Scale features
        X = self._scaler.fit_transform(X)

        self._ranker = xgb.XGBRanker(
            objective="rank:pairwise",
            n_estimators=100,
            max_depth=5,
            learning_rate=0.05,
            random_state=42,
        )
        self._ranker.fit(X, y, qid=qid)
        self._save_ranker()

        return {"status": "ok", "samples": len(X), "feature_importance": self._feature_importance()}

    def _feature_importance(self) -> dict:
        if self._ranker is None:
            return {}
        scores = self._ranker.feature_importances_
        return {name: round(float(score), 4) for name, score in zip(FEATURE_NAMES, scores)}

    # ── Build ranked dataset ───────────────────────────────────────────────────

    async def build(self, min_score: float = 0.4) -> dict:
        """
        Fetch all approved knowledge, score all items, save ranked JSON.
        Returns path to output file and stats.
        """
        async with AriaCosmosClient() as db:
            docs = await db.query(
                CONTAINER_KNOWLEDGE,
                "SELECT * FROM c WHERE c.verdict = 'APPROVED'",
            )

        if not docs:
            return {"status": "empty", "items": 0}

        # Score and rank
        scored = []
        for doc in docs:
            s = self.score(doc)
            if s >= min_score:
                scored.append({
                    "id":            doc.get("id", ""),
                    "topic":         doc.get("topic", ""),
                    "content":       doc.get("content", ""),
                    "source_url":    doc.get("source_url", ""),
                    "keywords":      doc.get("keywords", []),
                    "knowledge_type": doc.get("knowledge_type", "general"),
                    "quality_score": s,
                    "depth_score":   doc.get("depth_score", 0),
                    "bias_score":    doc.get("bias_score", 0),
                    "source_score":  doc.get("source_score", 0),
                    "dimensions":    doc.get("dimension_analyses", {}),
                })

        # Sort by quality score descending
        scored.sort(key=lambda d: d["quality_score"], reverse=True)

        # Write output
        _DATA_DIR.mkdir(exist_ok=True)
        with open(_OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total":        len(scored),
                "items":        scored,
            }, f, indent=2, ensure_ascii=False)

        # Log
        async with AriaCosmosClient() as db:
            await db.log("training_builder", "BUILD_COMPLETE", {
                "total_scored": len(scored),
                "output": str(_OUTPUT_JSON),
                "top_score": scored[0]["quality_score"] if scored else 0,
            })

        logger.info(f"TrainingBuilder: built {len(scored)} items → {_OUTPUT_JSON}")
        return {
            "status":        "ok",
            "items":         len(scored),
            "output":        str(_OUTPUT_JSON),
            "top_score":     scored[0]["quality_score"] if scored else 0,
            "importance":    self._feature_importance(),
        }

    def score_item(self, doc: dict) -> dict:
        """Convenience: score a single doc and return feature breakdown."""
        feats = _extract_features(doc)
        return {
            "score":    self.score(doc),
            "features": {name: round(v, 4) for name, v in zip(FEATURE_NAMES, feats)},
        }
