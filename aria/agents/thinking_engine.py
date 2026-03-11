"""
ARIA Thinking Engine — analyses content across 10 dimensions via Qwen.
RandomForest depth scorer, PCA redundancy check, retry if < 7 dimensions pass.
"""
import asyncio
import json
import logging
from typing import Optional

import numpy as np
from sklearn.decomposition import PCA
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler

from agents.qwen_interface import analyse_dimensions
from utils.text_processor import (
    clean, word_count, sentence_count,
    avg_sentence_length, content_density, extract_keywords,
)

logger = logging.getLogger(__name__)

# ── 10 Thinking Dimensions ────────────────────────────────────────────────────

DIMENSIONS = [
    "Factual accuracy",
    "Source credibility",
    "Internal consistency",
    "Logical reasoning",
    "Cultural and geographic context",
    "Temporal relevance",
    "Bias and perspective",
    "Practical applicability",
    "Knowledge completeness",
    "Counterarguments and limitations",
]

_MIN_DIMENSIONS_REQUIRED = 7
_MAX_RETRIES = 2
_MIN_DIMENSION_LENGTH = 10  # chars — dimensions shorter than this are treated as failed


# ── RF depth scorer ────────────────────────────────────────────────────────────

def _text_features(text: str) -> list[float]:
    """Extract 6 numerical features used by the RF depth scorer."""
    return [
        word_count(text),
        sentence_count(text),
        avg_sentence_length(text),
        content_density(text),
        len(extract_keywords(text, top_n=20)),
        len(set(text.lower().split())) / max(word_count(text), 1),  # lexical diversity
    ]


class DepthScorer:
    """
    RandomForest regressor that scores how 'deep' (informational)
    a piece of content is, 0.0–1.0.
    Trained on heuristic-labelled samples — improves over time.
    """

    def __init__(self):
        self._model: Optional[RandomForestRegressor] = None
        self._scaler = StandardScaler()
        self._fitted = False

    def _build_seed(self) -> tuple[list, list]:
        """Seed training data: (features_list, scores_list)."""
        samples = [
            # (text, depth_score)
            ("a", 0.0),
            ("ok yes no", 0.05),
            ("The study found results.", 0.2),
            ("Researchers at MIT published a study in 2024 showing a 34% "
             "reduction in carbon emissions when renewable energy sources "
             "replaced coal in the manufacturing sector across five countries.", 0.75),
            ("The peer-reviewed meta-analysis synthesised 47 randomised "
             "controlled trials involving 12,000 participants and found "
             "statistically significant improvements across all primary "
             "endpoints with effect sizes ranging from 0.3 to 0.8 Cohen's d, "
             "with heterogeneity well within acceptable bounds (I²=23%).", 0.95),
        ]
        X = [_text_features(t) for t, _ in samples]
        y = [s for _, s in samples]
        return X, y

    def _ensure_fitted(self) -> None:
        if self._fitted:
            return
        X, y = self._build_seed()
        Xs = self._scaler.fit_transform(X)
        self._model = RandomForestRegressor(n_estimators=50, random_state=42)
        self._model.fit(Xs, y)
        self._fitted = True

    def score(self, text: str) -> float:
        """Return depth score 0.0–1.0 for a piece of text."""
        self._ensure_fitted()
        features = _text_features(text)
        Xs = self._scaler.transform([features])
        raw = float(self._model.predict(Xs)[0])
        return max(0.0, min(1.0, raw))


_depth_scorer = DepthScorer()


# ── PCA redundancy check ───────────────────────────────────────────────────────

def _pca_redundancy_ratio(dimension_analyses: dict[str, str]) -> float:
    """
    Embed dimension analyses as TF-IDF-like bag-of-words,
    run PCA, and return the ratio explained by the first component.
    High ratio (> 0.7) means analyses are redundant / saying the same thing.
    """
    texts = list(dimension_analyses.values())
    if len(texts) < 3:
        return 0.0
    from sklearn.feature_extraction.text import TfidfVectorizer
    try:
        vec = TfidfVectorizer(max_features=200).fit_transform(texts).toarray()
        if vec.shape[1] < 2:
            return 0.0
        pca = PCA(n_components=min(len(texts), vec.shape[1], 3))
        pca.fit(vec)
        return float(pca.explained_variance_ratio_[0])
    except Exception:
        return 0.0


# ── Main ThinkingEngine ────────────────────────────────────────────────────────

class ThinkingEngine:
    """
    Processes a content item through all 10 dimensions via Qwen.
    Retries if fewer than 7 dimensions return valid analyses.
    Adds depth score and redundancy flag.
    """

    async def analyse(self, content: str, topic: str = "") -> dict:
        """
        Full 10-dimension analysis of content.
        Returns enriched dict with dimension analyses, scores, flags.
        """
        cleaned = clean(content)
        if word_count(cleaned) < 50:
            return {
                "status": "SKIPPED",
                "reason": "Content too short for analysis",
                "content": content,
                "topic": topic,
            }

        dimension_analyses: dict[str, str] = {}
        attempts = 0

        while attempts <= _MAX_RETRIES:
            # Determine which dimensions still need filling
            pending = [d for d in DIMENSIONS
                       if len(dimension_analyses.get(d, "")) < _MIN_DIMENSION_LENGTH]
            if not pending:
                break

            try:
                batch = await analyse_dimensions(cleaned, pending)
                for dim, analysis in batch.items():
                    if len(analysis) >= _MIN_DIMENSION_LENGTH:
                        dimension_analyses[dim] = analysis
            except Exception as e:
                logger.warning(f"ThinkingEngine Qwen call failed (attempt {attempts}): {e}")

            passed = sum(
                1 for d in DIMENSIONS
                if len(dimension_analyses.get(d, "")) >= _MIN_DIMENSION_LENGTH
            )
            if passed >= _MIN_DIMENSIONS_REQUIRED:
                break

            attempts += 1
            if attempts <= _MAX_RETRIES:
                logger.info(f"ThinkingEngine retry {attempts}: {passed}/{len(DIMENSIONS)} dims passed")
                await asyncio.sleep(2)

        passed_count = sum(
            1 for d in DIMENSIONS
            if len(dimension_analyses.get(d, "")) >= _MIN_DIMENSION_LENGTH
        )

        if passed_count < _MIN_DIMENSIONS_REQUIRED:
            return {
                "status": "INCOMPLETE",
                "reason": f"Only {passed_count}/{len(DIMENSIONS)} dimensions analysed after {attempts} attempts",
                "content": content,
                "topic": topic,
                "dimension_analyses": dimension_analyses,
            }

        depth = _depth_scorer.score(cleaned)
        redundancy = _pca_redundancy_ratio(dimension_analyses)

        return {
            "status":               "COMPLETE",
            "content":              content,
            "topic":                topic,
            "dimension_analyses":   dimension_analyses,
            "dimensions_passed":    passed_count,
            "depth_score":          round(depth, 3),
            "redundancy_ratio":     round(redundancy, 3),
            "high_redundancy":      redundancy > 0.7,
            "keywords":             extract_keywords(cleaned, top_n=10),
        }


# Module-level singleton
_engine: Optional[ThinkingEngine] = None


def get_engine() -> ThinkingEngine:
    global _engine
    if _engine is None:
        _engine = ThinkingEngine()
    return _engine
