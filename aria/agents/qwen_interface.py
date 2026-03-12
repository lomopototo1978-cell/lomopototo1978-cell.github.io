"""ARIA LLM interface for calling the configured chat model via Groq.
No other module calls the LLM directly; always go through here.
"""
import json
import logging
from typing import Any

import httpx

from utils.config import LLM_ENDPOINT, LLM_API_KEY, LLM_MODEL

logger = logging.getLogger(__name__)

_HEADERS = {
    "Authorization": f"Bearer {LLM_API_KEY}",
    "Content-Type": "application/json",
}
_TIMEOUT = 90.0
_MAX_TOKENS_DEFAULT = 1000


async def _call(messages: list[dict], max_tokens: int = _MAX_TOKENS_DEFAULT,
                temperature: float = 0.7) -> dict[str, Any]:
    """Low-level POST to Qwen endpoint. Returns parsed JSON response."""
    body = {
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(LLM_ENDPOINT, headers=_HEADERS, json=body)
        resp.raise_for_status()
        return resp.json()


def _extract_text(response: dict) -> str:
    """Pull the assistant message text out of a chat completion response."""
    try:
        return response["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as e:
        raise ValueError(f"Unexpected Qwen response shape: {e} — {response}") from e


# ── 1. Guide a stuck Scout ────────────────────────────────────────────────────

async def guide_search(topic: str, failed_queries: list[str]) -> list[str]:
    """
    Scout is stuck. Ask Qwen for 5 better search query suggestions.
    Returns a list of query strings.
    """
    messages = [
        {"role": "system", "content": "You are a research assistant. Output only valid JSON."},
        {"role": "user", "content": (
            f"Topic: {topic}\n"
            f"Failed queries: {json.dumps(failed_queries)}\n"
            "Suggest 5 new search queries that will find high-quality, factual content about this topic. "
            "Return a JSON array of strings only."
        )},
    ]
    text = _extract_text(await _call(messages, max_tokens=300, temperature=0.5))
    try:
        queries = json.loads(text)
        return [str(q) for q in queries[:5]]
    except json.JSONDecodeError:
        logger.warning("guide_search: Qwen returned non-JSON, falling back to raw text split")
        return [line.strip("- ").strip() for line in text.splitlines() if line.strip()][:5]


# ── 2. Review a flagged item ──────────────────────────────────────────────────

async def review_flagged(content: str, flag_reason: str) -> dict[str, str]:
    """
    Checker flagged content. Qwen returns a verdict and explanation.
    Returns {"verdict": "APPROVED"|"REJECTED", "reason": str}
    """
    messages = [
        {"role": "system", "content": "You are a fact-checking assistant. Output only valid JSON."},
        {"role": "user", "content": (
            f"The following content was flagged by an automated checker.\n"
            f"Flag reason: {flag_reason}\n\n"
            f"Content:\n{content[:3000]}\n\n"
            "Decide: APPROVED or REJECTED. "
            'Return JSON: {"verdict": "APPROVED"|"REJECTED", "reason": "<one sentence>"}'
        )},
    ]
    text = _extract_text(await _call(messages, max_tokens=200, temperature=0.2))
    try:
        result = json.loads(text)
        if result.get("verdict") not in ("APPROVED", "REJECTED"):
            result["verdict"] = "REJECTED"
        return result
    except json.JSONDecodeError:
        return {"verdict": "REJECTED", "reason": "Qwen returned unparseable response"}


# ── 3. Teach ARIA after a mistake ─────────────────────────────────────────────

async def teach_correction(wrong_content: str, correct_explanation: str) -> str:
    """
    Generate a structured lesson document from a known mistake.
    Returns a plain-text lesson string to store in qwen_lessons container.
    """
    messages = [
        {"role": "system", "content": "You are an AI trainer creating structured lessons."},
        {"role": "user", "content": (
            f"ARIA stored incorrect information:\n{wrong_content[:2000]}\n\n"
            f"Correct explanation:\n{correct_explanation}\n\n"
            "Write a concise structured lesson (max 300 words) explaining what was wrong, "
            "why it was wrong, and what the correct understanding is. "
            "Format: MISTAKE / WHY / CORRECT / KEY TAKEAWAY"
        )},
    ]
    return _extract_text(await _call(messages, max_tokens=400, temperature=0.3))


# ── 4. Generate training data for BaobabGPT ───────────────────────────────────

async def generate_training_example(knowledge: str, subject: str) -> dict[str, str]:
    """
    Turn a verified knowledge document into a BaobabGPT training Q&A pair.
    Returns {"question": str, "answer": str, "reasoning": str}
    """
    messages = [
        {"role": "system", "content": "You are a training data generator. Output only valid JSON."},
        {"role": "user", "content": (
            f"Subject: {subject}\n\n"
            f"Knowledge:\n{knowledge[:3000]}\n\n"
            "Generate one high-quality question-answer pair for training an AI assistant. "
            "Include a chain-of-thought reasoning trace. "
            'Return JSON: {"question": str, "answer": str, "reasoning": str}'
        )},
    ]
    text = _extract_text(await _call(messages, max_tokens=600, temperature=0.4))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"question": subject, "answer": knowledge[:500], "reasoning": ""}


# ── 5. Generate weekly progress report ───────────────────────────────────────

async def generate_report(stats: dict[str, Any]) -> str:
    """
    Given a stats dict (knowledge count, accuracy, weak spots, etc.),
    produce a human-readable weekly report for Sean.
    Returns markdown-formatted report string.
    """
    messages = [
        {"role": "system", "content": "You are ARIA's reporting agent. Write clear, concise reports."},
        {"role": "user", "content": (
            f"ARIA weekly stats:\n{json.dumps(stats, indent=2)}\n\n"
            "Write a weekly progress report in markdown. Include: "
            "1) What was learned, 2) Accuracy trend, 3) Weak spots identified, "
            "4) Recommendations for next week. Max 400 words."
        )},
    ]
    return _extract_text(await _call(messages, max_tokens=600, temperature=0.5))


# ── 6. Analyse 10 thinking dimensions ────────────────────────────────────────

async def analyse_dimensions(content: str, dimensions: list[str]) -> dict[str, str]:
    """
    ThinkingEngine calls this to analyse content across provided dimensions.
    Returns {dimension: analysis_text} for each dimension.
    """
    dim_list = "\n".join(f"{i+1}. {d}" for i, d in enumerate(dimensions))
    messages = [
        {"role": "system", "content": "You are a deep analytical reasoning engine. Output only valid JSON."},
        {"role": "user", "content": (
            f"Analyse the following content across these dimensions:\n{dim_list}\n\n"
            f"Content:\n{content[:3000]}\n\n"
            "Return a JSON object where each key is the dimension name and each value is "
            "a 2-3 sentence analysis (max 80 words per dimension)."
        )},
    ]
    text = _extract_text(await _call(messages, max_tokens=1200, temperature=0.6))
    try:
        result = json.loads(text)
        return {str(k): str(v) for k, v in result.items()}
    except json.JSONDecodeError:
        logger.warning("analyse_dimensions: Qwen returned non-JSON")
        return {d: "" for d in dimensions}
