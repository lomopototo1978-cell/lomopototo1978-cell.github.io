"""
ARIA Checker Agent — 5-layer validation pipeline.
Verdicts: APPROVED / FLAGGED / REJECTED / INCOMPLETE
Reads from checker-queue, writes results to thinking-queue or memory agent.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from azure.servicebus.aio import ServiceBusClient
from azure.servicebus import ServiceBusMessage

from utils.config import SERVICE_BUS_CONN, QUEUE_CHECKER, QUEUE_THINKING, CONTAINER_LOGS
from utils.text_processor import word_count, clean
from ml.bias_detector import bias_score
from ml.source_scorer import source_score, get_scorer
from ml.knowledge_validator import get_validator
from agents.qwen_interface import review_flagged
from database.cosmos_client import AriaCosmosClient

logger = logging.getLogger(__name__)

# ── Thresholds ─────────────────────────────────────────────────────────────────
_BIAS_HARD_REJECT     = 0.80   # Layer 4: immediate reject if above this
_BIAS_FLAG_THRESHOLD  = 0.60   # Layer 2: flag for Qwen review if above this
_SOURCE_MIN_SCORE     = 0.25   # Layer 1: reject if below this
_MIN_WORD_COUNT       = 50     # Layer 5: incomplete if below this
_DEPTH_MIN            = 0.20   # Layer 3: flag if depth score below this


class CheckerAgent:
    """
    5-layer validation:
    Layer 1 — Source credibility (source_scorer)
    Layer 2 — Bias detection (bias_detector)
    Layer 3 — Content depth check (thinking_engine depth_score)
    Layer 4 — Safety / hard reject (bias > 0.80 or harmful signals)
    Layer 5 — Completeness (word count, dimension count)

    Verdict logic (per README):
      Layer 4 fails → REJECTED immediately
      All 5 pass    → APPROVED → Memory Agent
      Layers 1-3 partial → FLAGGED → Qwen reviews
      Layer 5 incomplete → INCOMPLETE → back to ThinkingEngine
    """

    def __init__(self):
        self._validator = get_validator()
        self._scorer    = get_scorer()

    # ── Individual layers ──────────────────────────────────────────────────────

    def _layer1_source(self, item: dict) -> dict:
        url = item.get("url", "")
        score = source_score(url) if url else 0.5
        passed = score >= _SOURCE_MIN_SCORE
        return {
            "layer":   1,
            "name":    "Source credibility",
            "passed":  passed,
            "score":   round(score, 3),
            "detail":  f"Source score {score:.2f} (min {_SOURCE_MIN_SCORE})" + (
                f" — Tier {self._scorer.tier(url)}" if url else ""),
        }

    def _layer2_bias(self, item: dict) -> dict:
        content = item.get("content", "")
        b = item.get("bias_score") or bias_score(content)
        flagged = b >= _BIAS_FLAG_THRESHOLD
        return {
            "layer":   2,
            "name":    "Bias detection",
            "passed":  not flagged,
            "score":   round(b, 3),
            "detail":  f"Bias score {b:.2f} (flag threshold {_BIAS_FLAG_THRESHOLD})",
        }

    def _layer3_depth(self, item: dict) -> dict:
        depth = item.get("depth_score", None)
        if depth is None:
            # Estimate from content length as fallback
            wc = word_count(item.get("content", ""))
            depth = min(wc / 500.0, 1.0)
        passed = depth >= _DEPTH_MIN
        return {
            "layer":   3,
            "name":    "Content depth",
            "passed":  passed,
            "score":   round(depth, 3),
            "detail":  f"Depth score {depth:.2f} (min {_DEPTH_MIN})",
        }

    def _layer4_safety(self, item: dict) -> dict:
        content = item.get("content", "")
        b = item.get("bias_score") or bias_score(content)
        # Hard safety signals
        _HARD_SIGNALS = [
            "bomb making", "how to kill", "child abuse", "csam",
            "synthesise methamphetamine", "manufacture weapons",
        ]
        text_lower = content.lower()
        has_harmful = any(sig in text_lower for sig in _HARD_SIGNALS)
        hard_bias   = b >= _BIAS_HARD_REJECT

        passed = not has_harmful and not hard_bias
        reason = "Safe" if passed else (
            "Harmful content signal detected" if has_harmful
            else f"Bias {b:.2f} exceeds hard reject threshold {_BIAS_HARD_REJECT}"
        )
        return {
            "layer":   4,
            "name":    "Safety check",
            "passed":  passed,
            "score":   0.0 if not passed else 1.0,
            "detail":  reason,
        }

    def _layer5_completeness(self, item: dict) -> dict:
        wc       = word_count(item.get("content", ""))
        dims     = item.get("dimensions_passed", None)
        dim_ok   = (dims is None) or (dims >= 7)
        word_ok  = wc >= _MIN_WORD_COUNT

        passed  = word_ok and dim_ok
        details = []
        if not word_ok:
            details.append(f"Only {wc} words (min {_MIN_WORD_COUNT})")
        if not dim_ok:
            details.append(f"Only {dims} dimensions (min 7)")

        return {
            "layer":   5,
            "name":    "Completeness",
            "passed":  passed,
            "score":   1.0 if passed else 0.0,
            "detail":  "; ".join(details) if details else "Complete",
        }

    # ── Main check ─────────────────────────────────────────────────────────────

    async def check(self, item: dict) -> dict:
        """
        Run all 5 layers. Determine verdict. Optionally escalate to Qwen.
        Returns item enriched with 'verdict', 'layers', 'checked_at'.
        """
        layers = [
            self._layer1_source(item),
            self._layer2_bias(item),
            self._layer3_depth(item),
            self._layer4_safety(item),
            self._layer5_completeness(item),
        ]

        # Layer 4 is a hard gate — immediate reject
        if not layers[3]["passed"]:
            verdict = "REJECTED"
            verdict_reason = layers[3]["detail"]

        # Layer 5 fail → incomplete → must go back to ThinkingEngine
        elif not layers[4]["passed"]:
            verdict = "INCOMPLETE"
            verdict_reason = layers[4]["detail"]

        # Layers 1-3 any fail → FLAGGED → Qwen review
        elif not all(l["passed"] for l in layers[:3]):
            failed = [l for l in layers[:3] if not l["passed"]]
            flag_reason = "; ".join(l["detail"] for l in failed)
            try:
                qwen_result = await review_flagged(
                    item.get("content", ""), flag_reason
                )
                verdict        = qwen_result.get("verdict", "FLAGGED")
                verdict_reason = qwen_result.get("reason", flag_reason)
            except Exception as e:
                logger.warning(f"Qwen review failed for flagged item: {e}")
                verdict        = "FLAGGED"
                verdict_reason = f"Awaiting Qwen review: {flag_reason}"

        # All 5 pass → validate against corpus
        else:
            val = self._validator.validate(
                item.get("content", ""),
                source_url=item.get("url", ""),
            )
            if val["is_duplicate"]:
                verdict        = "REJECTED"
                verdict_reason = val["reason"]
            elif val["passed"]:
                self._validator.add_to_corpus(item.get("content", ""), verified=True)
                verdict        = "APPROVED"
                verdict_reason = "All 5 layers passed; knowledge validation passed"
            else:
                verdict        = "FLAGGED"
                verdict_reason = val["reason"]

        return {
            **item,
            "verdict":        verdict,
            "verdict_reason": verdict_reason,
            "layers":         layers,
            "checked_at":     datetime.now(timezone.utc).isoformat(),
        }

    # ── Service Bus cycle ──────────────────────────────────────────────────────

    async def run_checker_cycle(self, max_messages: int = 20) -> dict:
        """
        Read from checker-queue, check each item, route by verdict:
        APPROVED  → stored via AriaCosmosClient (knowledge_base)
        FLAGGED   → re-queued to checker-queue with Qwen note
        REJECTED  → logged only
        INCOMPLETE → re-queued to thinking-queue for re-analysis
        """
        stats = {"processed": 0, "approved": 0, "flagged": 0,
                 "rejected": 0, "incomplete": 0}

        async with ServiceBusClient.from_connection_string(SERVICE_BUS_CONN) as sb:
            async with sb.get_queue_receiver(QUEUE_CHECKER, max_wait_time=5) as receiver:
                msgs = await receiver.receive_messages(max_message_count=max_messages)
                items = []
                for msg in msgs:
                    try:
                        items.append((msg, json.loads(str(msg))))
                        await receiver.complete_message(msg)
                    except Exception as e:
                        logger.error(f"Failed to parse checker-queue message: {e}")
                        await receiver.abandon_message(msg)

        async with AriaCosmosClient() as db:
            async with ServiceBusClient.from_connection_string(SERVICE_BUS_CONN) as sb:
                thinking_sender = sb.get_queue_sender(QUEUE_THINKING)
                checker_sender  = sb.get_queue_sender(QUEUE_CHECKER)

                async with thinking_sender, checker_sender:
                    for _, item in items:
                        result = await self.check(item)
                        verdict = result["verdict"]
                        stats["processed"] += 1
                        stats[verdict.lower()] = stats.get(verdict.lower(), 0) + 1

                        if verdict == "APPROVED":
                            await db.upsert("knowledge_base", {
                                "subject":            {"category": result.get("topic", "general")},
                                "content":            result.get("content", ""),
                                "source_url":         result.get("url", ""),
                                "keywords":           result.get("keywords", []),
                                "bias_score":         result.get("bias_score", 0),
                                "source_score":       result.get("source_score", 0),
                                "depth_score":        result.get("depth_score", 0),
                                "dimension_analyses": result.get("dimension_analyses", {}),
                                "fingerprint":        result.get("fingerprint", ""),
                                "verdict":            "APPROVED",
                            })
                            await db.log("checker_agent", "APPROVED", {
                                "url": result.get("url"), "topic": result.get("topic")
                            })

                        elif verdict == "INCOMPLETE":
                            await thinking_sender.send_messages(
                                ServiceBusMessage(json.dumps(item))
                            )

                        elif verdict == "FLAGGED":
                            flagged_item = {**item, "flag_note": result.get("verdict_reason")}
                            await checker_sender.send_messages(
                                ServiceBusMessage(json.dumps(flagged_item))
                            )

                        elif verdict == "REJECTED":
                            await db.log("checker_agent", "REJECTED", {
                                "url":    result.get("url"),
                                "reason": result.get("verdict_reason"),
                            })

        logger.info(f"Checker cycle complete: {stats}")
        return stats


# Module-level singleton
_checker: Optional[CheckerAgent] = None


def get_checker() -> CheckerAgent:
    global _checker
    if _checker is None:
        _checker = CheckerAgent()
    return _checker
