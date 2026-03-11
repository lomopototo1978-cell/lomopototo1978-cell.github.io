"""
ARIA Decay Manager — knowledge expiry rules.
Types: breaking_news (24h) | economic_data (30d) | scientific_fact (1y) | mathematics (never)
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── Expiry rules (from README) ─────────────────────────────────────────────────

_EXPIRY_RULES: dict[str, Optional[timedelta]] = {
    "breaking_news":    timedelta(hours=24),
    "economic_data":    timedelta(days=30),
    "scientific_fact":  timedelta(days=365),
    "mathematics":      None,   # Never expires
    "general":          timedelta(days=90),   # default for unlabelled
    "fintech":          timedelta(days=30),
    "politics":         timedelta(days=14),
    "technology":       timedelta(days=60),
    "history":          None,   # Never expires
    "geography":        None,   # Never expires
    "law":              timedelta(days=180),
    "health":           timedelta(days=90),
    "sports":           timedelta(days=7),
}

_KEYWORD_TYPE_MAP: list[tuple[list[str], str]] = [
    (["breaking", "urgent", "just in", "developing", "live update"], "breaking_news"),
    (["gdp", "inflation", "interest rate", "currency", "bond", "stock", "economic"], "economic_data"),
    (["study", "research", "journal", "peer reviewed", "clinical trial", "meta-analysis"], "scientific_fact"),
    (["theorem", "equation", "proof", "formula", "calculus", "algebra", "geometry"], "mathematics"),
    (["law", "court", "ruling", "legislation", "act", "regulation"], "law"),
    (["fintech", "mobile money", "ecocash", "zipit", "payment"], "fintech"),
    (["match", "tournament", "league", "score", "champion", "sport"], "sports"),
]


def classify_knowledge_type(content: str, topic: str = "") -> str:
    """
    Infer knowledge type from content and topic keywords.
    Falls back to 'general'.
    """
    text = (content + " " + topic).lower()
    for keywords, ktype in _KEYWORD_TYPE_MAP:
        if any(kw in text for kw in keywords):
            return ktype
    return "general"


def expiry_datetime(knowledge_type: str,
                    created_at: Optional[datetime] = None) -> Optional[datetime]:
    """
    Return the expiry datetime for a knowledge item.
    Returns None if the type never expires.
    `created_at` defaults to now if not provided.
    """
    delta = _EXPIRY_RULES.get(knowledge_type, _EXPIRY_RULES["general"])
    if delta is None:
        return None  # never expires
    base = created_at or datetime.now(timezone.utc)
    return base + delta


def is_expired(knowledge_type: str, created_at_iso: str) -> bool:
    """
    Check if a knowledge item of given type is past its expiry.
    `created_at_iso` is an ISO 8601 string.
    """
    delta = _EXPIRY_RULES.get(knowledge_type, _EXPIRY_RULES["general"])
    if delta is None:
        return False  # never expires
    try:
        created = datetime.fromisoformat(created_at_iso.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) > created + delta
    except Exception as e:
        logger.warning(f"Could not parse created_at '{created_at_iso}': {e}")
        return False


def days_until_expiry(knowledge_type: str, created_at_iso: str) -> Optional[float]:
    """
    Return days remaining until expiry. Negative = already expired.
    Returns None if the item never expires.
    """
    delta = _EXPIRY_RULES.get(knowledge_type, _EXPIRY_RULES["general"])
    if delta is None:
        return None
    try:
        created = datetime.fromisoformat(created_at_iso.replace("Z", "+00:00"))
        expiry  = created + delta
        remaining = (expiry - datetime.now(timezone.utc)).total_seconds() / 86400
        return round(remaining, 1)
    except Exception:
        return None


def time_to_live_label(knowledge_type: str) -> str:
    """Human-readable TTL label for a knowledge type."""
    delta = _EXPIRY_RULES.get(knowledge_type, _EXPIRY_RULES["general"])
    if delta is None:
        return "Never expires"
    hours = delta.total_seconds() / 3600
    if hours < 48:
        return f"{int(hours)} hours"
    days = delta.days
    if days < 60:
        return f"{days} days"
    return f"{days // 30} months"


def get_all_rules() -> dict[str, str]:
    """Return all expiry rules as human-readable dict."""
    return {k: time_to_live_label(k) for k in _EXPIRY_RULES}
