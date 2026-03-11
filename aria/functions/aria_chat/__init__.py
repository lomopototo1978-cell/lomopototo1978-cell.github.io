"""
Azure Function HTTP trigger — ARIA chat endpoint.
Called by admin.html. Accepts POST {"message": str, "history": [...]}
Returns {"reply": str}

Auth: function-level key (set in Azure Portal → Functions → aria-chat → Function Keys)
CORS: configured in Azure Portal to allow https://mvumi.me
"""
import json
import logging
import os
import sys

import azure.functions as func

# Allow importing from the aria package root
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from utils.aria_persona import SYSTEM_PROMPT
from utils.config import QWEN_ENDPOINT, QWEN_API_KEY

import httpx

logger = logging.getLogger(__name__)

_HEADERS = {
    "Authorization": f"Bearer {QWEN_API_KEY}",
    "Content-Type": "application/json",
}
_CORS_HEADERS = {
    "Access-Control-Allow-Origin":  "https://mvumi.me",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, x-functions-key",
}
_MAX_HISTORY = 20   # keep last N messages for context window
_MAX_TOKENS  = 800


async def main(req: func.HttpRequest) -> func.HttpResponse:
    # Handle CORS preflight
    if req.method == "OPTIONS":
        return func.HttpResponse("", status_code=204, headers=_CORS_HEADERS)

    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Invalid JSON"}),
            status_code=400,
            mimetype="application/json",
            headers=_CORS_HEADERS,
        )

    message = (body.get("message") or "").strip()
    history = body.get("history") or []

    if not message:
        return func.HttpResponse(
            json.dumps({"error": "message is required"}),
            status_code=400,
            mimetype="application/json",
            headers=_CORS_HEADERS,
        )

    # Build messages array: system prompt + trimmed history + new message
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    # Trim history to last _MAX_HISTORY entries
    for entry in history[-_MAX_HISTORY:]:
        role = entry.get("role")
        content = entry.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                QWEN_ENDPOINT,
                headers=_HEADERS,
                json={
                    "model": "qwen2.5-9b-instruct",
                    "messages": messages,
                    "max_tokens": _MAX_TOKENS,
                    "temperature": 0.4,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            reply = data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Qwen call failed: {e}")
        return func.HttpResponse(
            json.dumps({"error": "ARIA backend error. Check Azure Function logs."}),
            status_code=502,
            mimetype="application/json",
            headers=_CORS_HEADERS,
        )

    return func.HttpResponse(
        json.dumps({"reply": reply}),
        status_code=200,
        mimetype="application/json",
        headers=_CORS_HEADERS,
    )
