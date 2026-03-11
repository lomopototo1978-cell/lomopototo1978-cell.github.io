"""
ARIA Knowledge Validator — KFold(10) consistency checker + TF-IDF cross-reference.
Targets: Consistency >85%, Cross-source agreement >80%.
"""
import logging
from typing import Optional

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.model_selection import StratifiedKFold, cross_val_score

from utils.text_processor import clean_for_ml, fingerprint

logger = logging.getLogger(__name__)

_MIN_CONSISTENCY_SCORE = 0.85
_MIN_CROSS_SOURCE_AGREEMENT = 0.80
_MIN_SAMPLES_FOR_KFOLD = 10      # need at least this many to run KFold
_COSINE_AGREEMENT_THRESHOLD = 0.40  # minimum cosine sim to count as "agreeing"


class KnowledgeValidator:
    """
    Validates a knowledge item against an existing corpus.

    Steps:
    1. TF-IDF cross-reference: does the item agree with existing knowledge?
    2. KFold(10) consistency: does the item score stably across folds?
    3. Fingerprint duplicate check.

    Returns verdict dict with detailed breakdown.
    """

    def __init__(self):
        self._corpus: list[str] = []          # cleaned texts of verified knowledge
        self._corpus_labels: list[int] = []   # 1 = verified, 0 = rejected

    def add_to_corpus(self, text: str, verified: bool = True) -> None:
        """Add a document to the validation corpus."""
        self._corpus.append(clean_for_ml(text))
        self._corpus_labels.append(1 if verified else 0)

    def _cross_reference_score(self, text: str) -> float:
        """
        Compute cosine similarity of `text` against the corpus.
        Returns mean of top-5 similarities (0.0–1.0).
        0.0 = totally novel/unsupported, 1.0 = well corroborated.
        """
        if len(self._corpus) < 3:
            return 1.0  # can't check — assume ok when corpus too small

        cleaned = clean_for_ml(text)
        all_texts = self._corpus + [cleaned]
        try:
            vec = TfidfVectorizer(max_features=3000).fit_transform(all_texts)
            sims = cosine_similarity(vec[-1], vec[:-1])[0]
            top_k = min(5, len(sims))
            return float(np.sort(sims)[-top_k:].mean())
        except Exception as e:
            logger.warning(f"Cross-reference failed: {e}")
            return 0.5

    def _kfold_consistency(self, text: str) -> float:
        """
        Add text as a positive sample, run KFold(10) LR on corpus,
        return mean accuracy across folds as consistency score.
        Falls back to cross-reference score if corpus too small.
        """
        if len(self._corpus) < _MIN_SAMPLES_FOR_KFOLD:
            return self._cross_reference_score(text)

        cleaned = clean_for_ml(text)
        all_texts  = self._corpus + [cleaned]
        all_labels = self._corpus_labels + [1]

        # Need at least 2 classes for classification
        if len(set(all_labels)) < 2:
            return 1.0

        try:
            vec = TfidfVectorizer(max_features=2000)
            X = vec.fit_transform(all_texts)
            clf = LogisticRegression(max_iter=500, random_state=42)
            k = min(10, len(all_texts))
            cv = StratifiedKFold(n_splits=k, shuffle=True, random_state=42)
            scores = cross_val_score(clf, X, all_labels, cv=cv, scoring="accuracy")
            return float(np.mean(scores))
        except Exception as e:
            logger.warning(f"KFold consistency check failed: {e}")
            return self._cross_reference_score(text)

    def validate(self, text: str, source_url: str = "",
                 existing_fingerprints: Optional[set] = None) -> dict:
        """
        Full validation of a knowledge item.
        Returns verdict dict:
          {
            "passed": bool,
            "consistency_score": float,
            "cross_source_score": float,
            "is_duplicate": bool,
            "fingerprint": str,
            "reason": str,
          }
        """
        fp = fingerprint(text)

        # 1. Duplicate check
        if existing_fingerprints and fp in existing_fingerprints:
            return {
                "passed": False,
                "consistency_score": 0.0,
                "cross_source_score": 0.0,
                "is_duplicate": True,
                "fingerprint": fp,
                "reason": "Exact duplicate — already in knowledge base",
            }

        # 2. Cross-source agreement
        cross_score = self._cross_reference_score(text)

        # 3. KFold consistency
        consistency = self._kfold_consistency(text)

        passed = (
            consistency  >= _MIN_CONSISTENCY_SCORE and
            cross_score  >= _MIN_CROSS_SOURCE_AGREEMENT
        )

        reasons = []
        if consistency < _MIN_CONSISTENCY_SCORE:
            reasons.append(f"Consistency {consistency:.0%} < {_MIN_CONSISTENCY_SCORE:.0%} required")
        if cross_score < _MIN_CROSS_SOURCE_AGREEMENT:
            reasons.append(f"Cross-source agreement {cross_score:.0%} < {_MIN_CROSS_SOURCE_AGREEMENT:.0%} required")
        if not reasons:
            reasons.append("All validation checks passed")

        return {
            "passed":             passed,
            "consistency_score":  round(consistency, 3),
            "cross_source_score": round(cross_score, 3),
            "is_duplicate":       False,
            "fingerprint":        fp,
            "reason":             "; ".join(reasons),
        }


# Module-level singleton
_validator: Optional[KnowledgeValidator] = None


def get_validator() -> KnowledgeValidator:
    global _validator
    if _validator is None:
        _validator = KnowledgeValidator()
    return _validator
