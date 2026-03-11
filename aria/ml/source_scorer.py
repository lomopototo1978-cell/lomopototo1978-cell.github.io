"""
ARIA source scorer — RandomForest source credibility 0.0–1.0.
Targets: Accuracy >88%, False positive <10%.
Tier list is built-in. Model auto-saves/loads as pkl.
"""
import os
import pickle
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import cross_val_score
from sklearn.preprocessing import LabelEncoder

_MODEL_DIR  = Path(__file__).parent / "models"
_MODEL_PATH = _MODEL_DIR / "source_scorer.pkl"

# ── Source tier definitions (from README) ─────────────────────────────────────
# Tier 1 = highest trust (score ~0.9–1.0)
# Tier 2 = trusted (score ~0.65–0.85)
# Tier 3 = low trust (score ~0.1–0.4)

TIER_1 = {
    "reuters.com", "bbc.com", "bbc.co.uk", "arxiv.org",
    "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov", "github.com",
    "theguardian.com", "herald.co.zw", "nature.com", "science.org",
    "who.int", "un.org", "worldbank.org", "imf.org",
}
TIER_2 = {
    "medium.com", "forbes.com", "bloomberg.com", "aljazeera.com",
    "nytimes.com", "washingtonpost.com", "economist.com",
    "techcrunch.com", "wired.com", "arstechnica.com",
    "stackoverflow.com", "wikipedia.org",
}
TIER_3_SIGNALS = {
    "blogspot.com", "wordpress.com", "tumblr.com", "weebly.com",
    "wix.com", "angelfire.com", "geocities.com",
}


def _domain_from_url(url: str) -> str:
    """Extract root domain (e.g. sub.example.com → example.com)."""
    try:
        parsed = urlparse(url if url.startswith("http") else f"https://{url}")
        host = parsed.netloc or parsed.path.split("/")[0]
        host = host.lower().replace("www.", "")
        parts = host.split(".")
        return ".".join(parts[-2:]) if len(parts) >= 2 else host
    except Exception:
        return url.lower()


def _extract_features(url: str) -> list[float]:
    """
    Extract 7 numerical features from a URL for the RandomForest.
    [tier_score, is_https, path_depth, has_date, domain_length,
     is_known_low_quality, subdomain_count]
    """
    domain = _domain_from_url(url)
    parsed = urlparse(url if url.startswith("http") else f"https://{url}")

    # Feature 1: tier score
    if domain in TIER_1:
        tier_score = 1.0
    elif domain in TIER_2:
        tier_score = 0.6
    elif any(domain.endswith(s) for s in TIER_3_SIGNALS):
        tier_score = 0.1
    else:
        tier_score = 0.35  # unknown

    # Feature 2: is https
    is_https = 1.0 if parsed.scheme == "https" else 0.0

    # Feature 3: path depth (longer paths = more specific = slightly higher trust)
    path_parts = [p for p in parsed.path.split("/") if p]
    path_depth = min(len(path_parts) / 5.0, 1.0)

    # Feature 4: URL contains date pattern (indicates news article, not blog spam)
    has_date = 1.0 if re.search(r"/20\d{2}/\d{2}/", url) else 0.0

    # Feature 5: domain length (shorter = more established)
    domain_length = 1.0 - min(len(domain) / 40.0, 1.0)

    # Feature 6: known low quality signal
    is_low = 1.0 if any(domain.endswith(s) for s in TIER_3_SIGNALS) else 0.0

    # Feature 7: number of subdomains (too many = suspicious)
    full_host = (parsed.netloc or "").replace("www.", "")
    subdomain_count = 1.0 - min(full_host.count(".") / 4.0, 1.0)

    return [tier_score, is_https, path_depth, has_date,
            domain_length, is_low, subdomain_count]


# ── Seed training data (url, credibility_label: 0=low, 1=high) ───────────────

_SEED: list[tuple[str, int]] = [
    ("https://www.reuters.com/article/economy-2025", 1),
    ("https://arxiv.org/abs/2501.12345", 1),
    ("https://pubmed.ncbi.nlm.nih.gov/39123456/", 1),
    ("https://github.com/openai/gpt", 1),
    ("https://www.bbc.com/news/world-africa-12345678", 1),
    ("https://www.theguardian.com/world/2025/jan/article", 1),
    ("https://www.nature.com/articles/s41586-025-00001-x", 1),
    ("https://who.int/news-room/fact-sheets/detail/malaria", 1),
    ("https://worldbank.org/en/topic/poverty/overview", 1),
    ("https://medium.com/@user/interesting-tech-2025", 1),
    ("https://www.bloomberg.com/news/articles/2025-01-01", 1),
    ("https://www.forbes.com/sites/contributor/article", 1),
    ("https://aljazeera.com/news/2025/1/12/report", 1),
    ("https://stackoverflow.com/questions/12345678", 1),
    ("https://en.wikipedia.org/wiki/Zimbabwe", 1),
    ("http://randomconspiracyblog.blogspot.com/post", 0),
    ("http://miracle-cure-secrets.wordpress.com/2025", 0),
    ("http://wakeup-truth.weebly.com/chemtrails", 0),
    ("http://freeinfosite.wix.com/health-hidden-cures", 0),
    ("http://deepstaterevealed.tumblr.com/post/123", 0),
    ("http://unknown-forum-post.net/thread/12345", 0),
    ("http://spam-site-no-https.com/clickbait-article", 0),
    ("http://sketchy-news.info/shocking-truth-2025", 0),
]


class SourceScorer:
    """
    Score URL source credibility 0.0–1.0.
    0.0 = untrustworthy, 1.0 = highly credible.
    """

    def __init__(self):
        self._model: Optional[RandomForestClassifier] = None

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        if _MODEL_PATH.exists():
            self.load()
        else:
            self.train()

    def train(self, extra_data: list[tuple[str, int]] | None = None) -> dict:
        """Train on seed + optional extra data. Returns CV metrics. Auto-saves."""
        data   = _SEED + (extra_data or [])
        X      = [_extract_features(url) for url, _ in data]
        y      = [label for _, label in data]

        model = RandomForestClassifier(
            n_estimators=100,
            max_depth=6,
            random_state=42,
            class_weight="balanced",
        )

        scores_acc = cross_val_score(model, X, y, cv=3, scoring="accuracy")
        model.fit(X, y)
        self._model = model
        self.save()

        return {
            "accuracy": float(np.mean(scores_acc)),
            "samples":  len(data),
        }

    def score(self, url: str) -> float:
        """Return credibility score 0.0–1.0 for a given URL."""
        self._ensure_model()
        features = _extract_features(url)
        proba = self._model.predict_proba([features])[0]
        # class 1 = credible
        classes = list(self._model.classes_)
        if 1 in classes:
            return float(proba[classes.index(1)])
        return 0.5

    def tier(self, url: str) -> int:
        """Return tier 1/2/3 for a URL based on known domain lists."""
        domain = _domain_from_url(url)
        if domain in TIER_1:
            return 1
        if domain in TIER_2:
            return 2
        return 3

    def required_sources(self, url: str) -> int:
        """How many corroborating sources are needed per README spec."""
        t = self.tier(url)
        return {1: 2, 2: 3, 3: 5}.get(t, 5)

    def save(self) -> None:
        _MODEL_DIR.mkdir(exist_ok=True)
        with open(_MODEL_PATH, "wb") as f:
            pickle.dump(self._model, f)

    def load(self) -> None:
        with open(_MODEL_PATH, "rb") as f:
            self._model = pickle.load(f)


# Module-level singleton
_scorer: Optional[SourceScorer] = None


def get_scorer() -> SourceScorer:
    global _scorer
    if _scorer is None:
        _scorer = SourceScorer()
    return _scorer


def source_score(url: str) -> float:
    """Convenience function — returns credibility score 0.0–1.0."""
    return get_scorer().score(url)
