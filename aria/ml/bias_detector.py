"""
ARIA bias detector — MultinomialNB classifier, bias score 0.0–1.0.
Targets: Precision >90%, Recall >85%, F1 >87%.
Seed training data is built-in. Model auto-saves/loads as pkl.
"""
import os
import pickle
from pathlib import Path
from typing import Optional

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline
from sklearn.model_selection import cross_val_score

from utils.text_processor import clean_for_ml

_MODEL_DIR  = Path(__file__).parent / "models"
_MODEL_PATH = _MODEL_DIR / "bias_detector.pkl"

# ── Seed training data ────────────────────────────────────────────────────────
# label 1 = biased/unreliable, label 0 = neutral/factual

_SEED_DATA: list[tuple[str, int]] = [
    # Biased / emotionally charged / one-sided
    ("shocking truth they dont want you to know", 1),
    ("mainstream media lies cover up scandal exposed", 1),
    ("globalists destroying your country wake up sheeple", 1),
    ("scientists baffled by miracle cure big pharma hiding", 1),
    ("radical left agenda destroying society protest riots chaos", 1),
    ("fake news propaganda corrupt government elite control", 1),
    ("unbelievable you wont believe what happened next clickbait", 1),
    ("doctors hate him one weird trick cure all diseases", 1),
    ("insider reveals explosive secret bombshell revelation", 1),
    ("conspiracy proven beyond doubt deep state exposed", 1),
    ("emotional outrage must share viral injustice unfair", 1),
    ("they are coming for your freedom rights stripped away", 1),
    ("only we tell the truth everyone else lying to you", 1),
    ("satanic elite drinking blood children ritual sacrifice", 1),
    ("biased opinion this is terrible worst policy ever", 1),
    ("100 percent guaranteed results instant miracle solution", 1),
    ("anonymous source claims without evidence rumor spreads", 1),
    ("clickbait you wont believe this shocking video inside", 1),
    # Neutral / factual / evidence-based
    ("study published peer reviewed journal found correlation", 0),
    ("according to official statistics reported by government", 0),
    ("researchers conducted randomised controlled trial results", 0),
    ("data shows gradual increase over five year period analysis", 0),
    ("economists project moderate growth inflation forecast", 0),
    ("parliament passed legislation effective new fiscal year", 0),
    ("satellite images confirm location coordinates geographic", 0),
    ("clinical trial phase three results efficacy safety profile", 0),
    ("central bank raised interest rates basis points inflation", 0),
    ("world health organisation guidelines updated recommendations", 0),
    ("university study examined sample population methodology", 0),
    ("court ruling upheld constitutional rights decision appealed", 0),
    ("annual report financial results revenue operating margin", 0),
    ("scientists discovered new species habitat conservation", 0),
    ("census data population demographic trends urbanisation", 0),
    ("technical report describes algorithm performance benchmark", 0),
    ("historical records archive documents primary source evidence", 0),
    ("independent audit verified financial statements compliance", 0),
]


def _build_pipeline() -> Pipeline:
    return Pipeline([
        ("tfidf", TfidfVectorizer(
            ngram_range=(1, 2),
            max_features=5000,
            sublinear_tf=True,
            min_df=1,
        )),
        ("nb", MultinomialNB(alpha=0.5)),
    ])


class BiasDetector:
    """
    Detect content bias. Call score(text) → float 0.0–1.0.
    0.0 = neutral/factual, 1.0 = highly biased/unreliable.
    """

    def __init__(self):
        self._pipeline: Optional[Pipeline] = None

    def _ensure_model(self) -> None:
        if self._pipeline is not None:
            return
        if _MODEL_PATH.exists():
            self.load()
        else:
            self.train()

    def train(self, extra_data: list[tuple[str, int]] | None = None) -> dict:
        """
        Train on seed data + optional extra_data.
        Returns cross-validation metrics.
        Saves model to pkl automatically.
        """
        data = _SEED_DATA + (extra_data or [])
        texts  = [clean_for_ml(t) for t, _ in data]
        labels = [l for _, l in data]

        pipeline = _build_pipeline()

        # Cross-val metrics
        scores_p = cross_val_score(pipeline, texts, labels, cv=3, scoring="precision_macro")
        scores_r = cross_val_score(pipeline, texts, labels, cv=3, scoring="recall_macro")
        scores_f = cross_val_score(pipeline, texts, labels, cv=3, scoring="f1_macro")

        # Final fit on all data
        pipeline.fit(texts, labels)
        self._pipeline = pipeline
        self.save()

        return {
            "precision": float(np.mean(scores_p)),
            "recall":    float(np.mean(scores_r)),
            "f1":        float(np.mean(scores_f)),
            "samples":   len(data),
        }

    def score(self, text: str) -> float:
        """
        Return bias score 0.0–1.0.
        Uses predict_proba class 1 (biased) probability.
        """
        self._ensure_model()
        cleaned = clean_for_ml(text)
        if not cleaned.strip():
            return 0.5  # unknown
        proba = self._pipeline.predict_proba([cleaned])[0]
        return float(proba[1])  # probability of class 1 (biased)

    def is_biased(self, text: str, threshold: float = 0.6) -> bool:
        return self.score(text) >= threshold

    def save(self) -> None:
        _MODEL_DIR.mkdir(exist_ok=True)
        with open(_MODEL_PATH, "wb") as f:
            pickle.dump(self._pipeline, f)

    def load(self) -> None:
        with open(_MODEL_PATH, "rb") as f:
            self._pipeline = pickle.load(f)


# Module-level singleton — lazy loaded
_detector: Optional[BiasDetector] = None


def get_detector() -> BiasDetector:
    global _detector
    if _detector is None:
        _detector = BiasDetector()
    return _detector


def bias_score(text: str) -> float:
    """Convenience function — returns bias score 0.0–1.0."""
    return get_detector().score(text)
