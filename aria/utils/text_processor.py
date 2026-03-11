"""
ARIA text processor — clean, extract, and fingerprint text content.
Uses nltk. Downloads required data on first run automatically.
"""
import hashlib
import re
import string
from functools import lru_cache
from typing import Optional

import nltk
from nltk.corpus import stopwords
from nltk.stem import PorterStemmer
from nltk.tokenize import sent_tokenize, word_tokenize

# Download required nltk data silently on first use
for _pkg in ("punkt", "punkt_tab", "stopwords", "averaged_perceptron_tagger"):
    try:
        nltk.data.find(f"tokenizers/{_pkg}" if "punkt" in _pkg else f"corpora/{_pkg}")
    except LookupError:
        nltk.download(_pkg, quiet=True)

_STEMMER = PorterStemmer()
_STOP_EN = set(stopwords.words("english"))

# ── HTML / noise stripping ────────────────────────────────────────────────────

_TAG_RE       = re.compile(r"<[^>]+>")
_ENTITY_RE    = re.compile(r"&[a-z]+;|&#\d+;", re.I)
_WHITESPACE   = re.compile(r"\s+")
_URL_RE       = re.compile(r"https?://\S+|www\.\S+")
_PUNCT_RE     = re.compile(r"[^\w\s]")


def strip_html(text: str) -> str:
    """Remove HTML tags and decode common entities."""
    text = _TAG_RE.sub(" ", text)
    text = _ENTITY_RE.sub(" ", text)
    return text


def clean(text: str, remove_urls: bool = True) -> str:
    """
    Full cleaning pipeline:
    - strip HTML tags and entities
    - remove URLs (optional)
    - collapse whitespace
    - lowercase
    Returns clean plain text.
    """
    text = strip_html(text)
    if remove_urls:
        text = _URL_RE.sub(" ", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text.lower()


def clean_for_ml(text: str) -> str:
    """
    Aggressive clean for ML features:
    - clean() pipeline
    - remove punctuation
    - remove stopwords
    - stem tokens
    Returns space-joined stemmed tokens.
    """
    text = clean(text)
    tokens = word_tokenize(text)
    tokens = [_STEMMER.stem(t) for t in tokens
              if t not in _STOP_EN and t not in string.punctuation and len(t) > 2]
    return " ".join(tokens)


# ── Keyword extraction ────────────────────────────────────────────────────────

def extract_keywords(text: str, top_n: int = 15) -> list[str]:
    """
    Simple frequency-based keyword extraction after stopword removal.
    Returns top_n keywords sorted by frequency.
    """
    text = clean(text)
    tokens = word_tokenize(text)
    freq: dict[str, int] = {}
    for t in tokens:
        if t not in _STOP_EN and t not in string.punctuation and len(t) > 3:
            freq[t] = freq.get(t, 0) + 1
    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [w for w, _ in sorted_words[:top_n]]


def extract_sentences(text: str, max_sentences: int = 10) -> list[str]:
    """Split text into sentences, return up to max_sentences non-empty ones."""
    text = strip_html(text)
    sentences = sent_tokenize(text)
    return [s.strip() for s in sentences if len(s.strip()) > 20][:max_sentences]


def extract_summary(text: str, max_chars: int = 500) -> str:
    """Return first max_chars characters of cleaned text as a summary."""
    cleaned = clean(text, remove_urls=True)
    return cleaned[:max_chars].rsplit(" ", 1)[0] if len(cleaned) > max_chars else cleaned


# ── Fingerprinting (deduplication) ───────────────────────────────────────────

def fingerprint(text: str) -> str:
    """
    Generate a stable SHA-256 fingerprint of normalised content.
    Used by scout_agent and memory_agent to detect duplicates.
    """
    normalised = _PUNCT_RE.sub("", clean(text))
    normalised = _WHITESPACE.sub(" ", normalised).strip()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def is_duplicate(text_a: str, text_b: str) -> bool:
    """True if both texts have the same fingerprint."""
    return fingerprint(text_a) == fingerprint(text_b)


# ── Token stats ───────────────────────────────────────────────────────────────

def word_count(text: str) -> int:
    return len(word_tokenize(clean(text)))


def sentence_count(text: str) -> int:
    return len(sent_tokenize(strip_html(text)))


def avg_sentence_length(text: str) -> float:
    sentences = extract_sentences(text, max_sentences=1000)
    if not sentences:
        return 0.0
    total_words = sum(len(word_tokenize(s)) for s in sentences)
    return total_words / len(sentences)


def content_density(text: str) -> float:
    """
    Ratio of non-stopword content words to total words (0.0–1.0).
    Higher = more informational.
    """
    tokens = word_tokenize(clean(text))
    if not tokens:
        return 0.0
    content = [t for t in tokens if t not in _STOP_EN and t not in string.punctuation]
    return len(content) / len(tokens)
