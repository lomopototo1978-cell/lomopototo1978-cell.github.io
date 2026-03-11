"""
ARIA Scout Agent — searches Google CSE → DuckDuckGo fallback,
fetches page content with Playwright, deduplicates with TF-IDF,
detects knowledge gaps with K-Means, enqueues to thinking-queue.
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
from azure.servicebus.aio import ServiceBusClient
from azure.servicebus import ServiceBusMessage
from duckduckgo_search import DDGS
try:
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout
    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

import numpy as np

from utils.config import (
    GOOGLE_API_KEY, GOOGLE_CSE_ID,
    SERVICE_BUS_CONN, QUEUE_RESEARCH, QUEUE_THINKING,
)
from utils.text_processor import clean, fingerprint, extract_keywords, word_count
from ml.source_scorer import source_score
from ml.bias_detector import bias_score

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
_GOOGLE_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"
_MIN_CONTENT_WORDS = 100        # skip pages shorter than this
_MAX_CONTENT_CHARS = 8000       # truncate to this before sending downstream
_DDG_FALLBACK_THRESHOLD = 3     # fall back to DDG if Google returns fewer results
_DEDUP_SIMILARITY_THRESHOLD = 0.85
_FETCH_TIMEOUT_MS = 20_000
_MAX_RESULTS_PER_QUERY = 10
_MAX_FETCH_CONCURRENCY = 3


# ── Google CSE search ─────────────────────────────────────────────────────────

async def _google_search(query: str, num: int = _MAX_RESULTS_PER_QUERY) -> list[dict]:
    """
    Call Google Custom Search API.
    Returns list of {"title", "url", "snippet"} dicts.
    """
    params = {
        "key": GOOGLE_API_KEY,
        "cx":  GOOGLE_CSE_ID,
        "q":   query,
        "num": min(num, 10),
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(_GOOGLE_SEARCH_URL, params=params)
        if resp.status_code != 200:
            logger.warning(f"Google CSE returned {resp.status_code} for query: {query}")
            return []
        data = resp.json()
    return [
        {"title": item.get("title", ""), "url": item["link"], "snippet": item.get("snippet", "")}
        for item in data.get("items", [])
    ]


# ── DuckDuckGo fallback search ────────────────────────────────────────────────

def _ddg_search(query: str, max_results: int = _MAX_RESULTS_PER_QUERY) -> list[dict]:
    """
    DuckDuckGo search (sync wrapper — run in executor).
    Returns list of {"title", "url", "snippet"} dicts.
    """
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title":   r.get("title", ""),
                    "url":     r.get("href", ""),
                    "snippet": r.get("body", ""),
                })
    except Exception as e:
        logger.warning(f"DDG search failed: {e}")
    return results


# ── Page content fetcher (Playwright) ─────────────────────────────────────────

async def _fetch_page(url: str, browser) -> Optional[str]:
    """
    Fetch and extract visible text from a URL using Playwright.
    Returns cleaned text or None on failure.
    """
    try:
        page = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=_FETCH_TIMEOUT_MS)
        # Extract body text, excluding nav/footer noise
        text = await page.evaluate("""() => {
            const remove = ['nav', 'footer', 'header', 'aside', 'script', 'style', 'noscript'];
            remove.forEach(tag => document.querySelectorAll(tag).forEach(el => el.remove()));
            return document.body ? document.body.innerText : '';
        }""")
        await page.close()
        cleaned = clean(text or "", remove_urls=True)
        return cleaned if word_count(cleaned) >= _MIN_CONTENT_WORDS else None
    except (PWTimeout if _HAS_PLAYWRIGHT else Exception):
        logger.debug(f"Timeout fetching: {url}")
        return None
    except Exception as e:
        logger.debug(f"Fetch error {url}: {e}")
        return None


async def _fetch_page_httpx(url: str, client: httpx.AsyncClient) -> Optional[str]:
    """Lightweight fallback fetcher using httpx when playwright is unavailable."""
    try:
        resp = await client.get(url, timeout=_FETCH_TIMEOUT_MS / 1000, follow_redirects=True)
        resp.raise_for_status()
        # Simple text extraction: strip HTML tags
        import re as _re
        text = _re.sub(r'<script[^>]*>[\s\S]*?</script>', '', resp.text)
        text = _re.sub(r'<style[^>]*>[\s\S]*?</style>', '', text)
        text = _re.sub(r'<[^>]+>', ' ', text)
        cleaned = clean(text, remove_urls=True)
        return cleaned if word_count(cleaned) >= _MIN_CONTENT_WORDS else None
    except Exception as e:
        logger.debug(f"httpx fetch error {url}: {e}")
        return None


# ── TF-IDF deduplication ──────────────────────────────────────────────────────

class TfidfDeduplicator:
    """Keep track of seen content and detect near-duplicates with TF-IDF cosine similarity."""

    def __init__(self, threshold: float = _DEDUP_SIMILARITY_THRESHOLD):
        self._seen: list[str] = []
        self._threshold = threshold

    def is_duplicate(self, text: str) -> bool:
        if not self._seen:
            return False
        try:
            vectorizer = TfidfVectorizer(max_features=2000)
            matrix = vectorizer.fit_transform(self._seen + [text])
            sims = cosine_similarity(matrix[-1], matrix[:-1])
            return float(sims.max()) >= self._threshold
        except Exception:
            return False

    def add(self, text: str) -> None:
        self._seen.append(text[:2000])  # store truncated to save memory


# ── K-Means gap detection ─────────────────────────────────────────────────────

def detect_knowledge_gaps(topics: list[str], existing_texts: list[str],
                           n_clusters: int = 5) -> list[str]:
    """
    Cluster existing_texts with K-Means. Find clusters with low coverage.
    Returns list of topics not well represented in existing knowledge.
    If not enough texts to cluster, returns all topics as gaps.
    """
    if len(existing_texts) < n_clusters:
        return topics

    try:
        vectorizer = TfidfVectorizer(max_features=1000)
        X = vectorizer.fit_transform(existing_texts)
        km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        km.fit(X)

        # Count docs per cluster
        labels = km.labels_
        counts = np.bincount(labels, minlength=n_clusters)
        sparse_clusters = set(np.where(counts < max(1, len(existing_texts) // (n_clusters * 2)))[0])

        # Transform query topics and find which fall into sparse clusters
        topic_vecs = vectorizer.transform(topics)
        topic_clusters = km.predict(topic_vecs)
        gaps = [t for t, c in zip(topics, topic_clusters) if c in sparse_clusters]
        return gaps if gaps else topics[:3]
    except Exception as e:
        logger.warning(f"Gap detection failed: {e}")
        return topics[:3]


# ── SearchManager ─────────────────────────────────────────────────────────────

class SearchManager:
    """
    Orchestrates: search → fetch → dedup → quality filter → enqueue.
    """

    def __init__(self):
        self._dedup = TfidfDeduplicator()

    async def search(self, query: str) -> list[dict]:
        """
        Search Google first, fall back to DDG if results < threshold.
        Returns list of {"title", "url", "snippet"} dicts.
        """
        results = await _google_search(query)
        if len(results) < _DDG_FALLBACK_THRESHOLD:
            logger.info(f"Google returned {len(results)} results — falling back to DDG")
            loop = asyncio.get_event_loop()
            ddg_results = await loop.run_in_executor(None, _ddg_search, query)
            # Merge, deduplicate by URL
            seen_urls = {r["url"] for r in results}
            for r in ddg_results:
                if r["url"] not in seen_urls:
                    results.append(r)
                    seen_urls.add(r["url"])
        return results[:_MAX_RESULTS_PER_QUERY]

    async def fetch_and_filter(self, search_results: list[dict],
                                browser) -> list[dict]:
        """
        Fetch page content for each result (concurrency limited).
        Filter by minimum length, bias, and deduplication.
        Returns enriched result dicts with 'content' field.
        """
        semaphore = asyncio.Semaphore(_MAX_FETCH_CONCURRENCY)
        enriched = []

        async def fetch_one(result: dict) -> Optional[dict]:
            async with semaphore:
                url = result["url"]
                content = await _fetch_page(url, browser)
                if not content:
                    return None
                # Quality filters
                b_score = bias_score(content)
                s_score = source_score(url)
                if b_score > 0.75:
                    logger.debug(f"Skipping high-bias content: {url} (bias={b_score:.2f})")
                    return None
                if self._dedup.is_duplicate(content):
                    logger.debug(f"Skipping duplicate content: {url}")
                    return None
                self._dedup.add(content)
                return {
                    **result,
                    "content":       content[:_MAX_CONTENT_CHARS],
                    "fingerprint":   fingerprint(content),
                    "keywords":      extract_keywords(content, top_n=10),
                    "bias_score":    round(b_score, 3),
                    "source_score":  round(s_score, 3),
                    "fetched_at":    datetime.now(timezone.utc).isoformat(),
                }

        tasks = [fetch_one(r) for r in search_results]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r is not None]


# ── Service Bus integration ───────────────────────────────────────────────────

async def _read_topics_from_queue(max_messages: int = 5) -> list[str]:
    """Read topic strings from research-queue. Returns list of topic strings."""
    topics = []
    async with ServiceBusClient.from_connection_string(SERVICE_BUS_CONN) as sb:
        async with sb.get_queue_receiver(QUEUE_RESEARCH, max_wait_time=5) as receiver:
            msgs = await receiver.receive_messages(max_message_count=max_messages)
            for msg in msgs:
                try:
                    body = json.loads(str(msg))
                    topics.append(body.get("topic", str(msg)))
                except Exception:
                    topics.append(str(msg))
                await receiver.complete_message(msg)
    return topics


async def _enqueue_for_thinking(items: list[dict]) -> None:
    """Send enriched content items to thinking-queue."""
    if not items:
        return
    async with ServiceBusClient.from_connection_string(SERVICE_BUS_CONN) as sb:
        async with sb.get_queue_sender(QUEUE_THINKING) as sender:
            for item in items:
                msg = ServiceBusMessage(json.dumps(item))
                await sender.send_messages(msg)


# ── Main research cycle ───────────────────────────────────────────────────────

async def run_research_cycle(topics: Optional[list[str]] = None) -> dict:
    """
    Full scout cycle:
    1. Read topics from research-queue (or use provided list)
    2. For each topic: search → fetch → filter
    3. Detect knowledge gaps
    4. Enqueue results to thinking-queue
    Returns summary stats dict.
    """
    if topics is None:
        topics = await _read_topics_from_queue()

    if not topics:
        logger.info("Scout: no topics in queue, skipping cycle")
        return {"topics": 0, "fetched": 0, "queued": 0}

    manager = SearchManager()
    all_results = []

    if _HAS_PLAYWRIGHT:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                for topic in topics:
                    logger.info(f"Scout searching: {topic}")
                    search_results = await manager.search(topic)
                    enriched = await manager.fetch_and_filter(search_results, browser)
                    for item in enriched:
                        item["topic"] = topic
                    all_results.extend(enriched)
                    logger.info(f"  → {len(enriched)} items fetched for '{topic}'")
            finally:
                await browser.close()
    else:
        async with httpx.AsyncClient() as client:
            for topic in topics:
                logger.info(f"Scout searching (httpx fallback): {topic}")
                search_results = await manager.search(topic)
                enriched = []
                for sr in search_results:
                    content = await _fetch_page_httpx(sr["url"], client)
                    if content:
                        sr["content"] = content
                        enriched.append(sr)
                for item in enriched:
                    item["topic"] = topic
                all_results.extend(enriched)
                logger.info(f"  → {len(enriched)} items fetched for '{topic}'")

    # Gap detection
    if all_results:
        texts = [r["content"] for r in all_results]
        gaps  = detect_knowledge_gaps(topics, texts)
        if gaps:
            logger.info(f"Knowledge gaps detected: {gaps}")

    await _enqueue_for_thinking(all_results)

    return {
        "topics":  len(topics),
        "fetched": len(all_results),
        "queued":  len(all_results),
    }
