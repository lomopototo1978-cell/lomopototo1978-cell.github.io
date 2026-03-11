"""
ARIA Reporter Agent — daily/weekly intelligence reports.
Uses Linear Regression for trend detection and Thompson Sampling for
selecting the most informative topics to cover in each report.
"""
import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
from sklearn.linear_model import LinearRegression

import agents.qwen_interface as qwen
from database.cosmos_client import AriaCosmosClient
from utils.aria_persona import MORNING_BRIEFING_TEMPLATE, SEAN_TIMEZONE, MORNING_BRIEFING_HOUR
from utils.config import (
    CONTAINER_KNOWLEDGE, CONTAINER_LOGS, CONTAINER_REPORTS, CONTAINER_TRAINING
)
from utils.decay_manager import classify_knowledge_type
from utils.text_processor import extract_keywords

logger = logging.getLogger(__name__)

_TREND_WINDOW_DAYS   = 14    # days of history to compute trend over
_THOMPSON_ALPHA_INIT = 1.0   # Beta distribution alpha seed
_THOMPSON_BETA_INIT  = 1.0   # Beta distribution beta seed
_MAX_REPORT_TOPICS   = 8     # topics per report


# ── Thompson Sampling topic selector ──────────────────────────────────────────

class TopicSelector:
    """
    Multi-armed bandit (Thompson Sampling) that learns which topics
    generate the most valuable knowledge. Topics with more approved items
    get higher reward; topics with many flagged/rejected items get penalty.
    """

    def __init__(self):
        self._alpha: dict[str, float] = defaultdict(lambda: _THOMPSON_ALPHA_INIT)
        self._beta:  dict[str, float] = defaultdict(lambda: _THOMPSON_BETA_INIT)

    def update(self, topic: str, approved: int, rejected: int) -> None:
        """Update Beta distribution parameters for a topic."""
        self._alpha[topic] += approved
        self._beta[topic]  += rejected

    def select(self, candidates: list[str], n: int) -> list[str]:
        """
        Sample from Beta distribution for each candidate topic.
        Returns top n topics by sampled value.
        """
        if not candidates:
            return []
        scores = {
            t: float(np.random.beta(self._alpha[t], self._beta[t]))
            for t in candidates
        }
        return sorted(scores, key=scores.__getitem__, reverse=True)[:n]

    def get_weights(self) -> dict[str, float]:
        """Return expected value (alpha / (alpha+beta)) per topic."""
        return {
            t: round(self._alpha[t] / (self._alpha[t] + self._beta[t]), 3)
            for t in self._alpha
        }


# ── Trend detector ─────────────────────────────────────────────────────────────

class TrendDetector:
    """
    Fits a LinearRegression over (day_number, count) time series.
    Positive slope → growing topic; negative → declining.
    """

    def detect(self, daily_counts: list[int]) -> dict:
        """
        `daily_counts` is a list of floats/ints representing daily activity counts
        ordered from oldest to newest.
        Returns: {slope, direction, r2, current, average}
        """
        n = len(daily_counts)
        if n < 2:
            return {"slope": 0.0, "direction": "stable", "r2": 0.0,
                    "current": daily_counts[-1] if daily_counts else 0,
                    "average": daily_counts[0] if daily_counts else 0}

        X = np.arange(n).reshape(-1, 1)
        y = np.array(daily_counts, dtype=float)
        model = LinearRegression().fit(X, y)
        slope = float(model.coef_[0])
        r2    = float(model.score(X, y))

        direction = "growing" if slope > 0.3 else ("declining" if slope < -0.3 else "stable")

        return {
            "slope":     round(slope, 3),
            "direction": direction,
            "r2":        round(r2, 3),
            "current":   int(daily_counts[-1]),
            "average":   round(float(np.mean(daily_counts)), 1),
        }

    def analyse_topics(self, topic_daily: dict[str, list[int]]) -> dict[str, dict]:
        """Detect trends for multiple topics simultaneously."""
        return {topic: self.detect(counts) for topic, counts in topic_daily.items()}


# ── Reporter Agent ──────────────────────────────────────────────────────────────

class ReporterAgent:
    """
    Generates daily and weekly intelligence reports for Sean.
    Stores reports in Cosmos CONTAINER_REPORTS.
    """

    def __init__(self):
        self._selector = TopicSelector()
        self._trends   = TrendDetector()

    # ── Data gathering ─────────────────────────────────────────────────────────

    async def _gather_stats(self, days: int = 1) -> dict:
        """Gather knowledge stats from the last `days` days."""
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        async with AriaCosmosClient() as db:
            all_approved = await db.query(
                CONTAINER_KNOWLEDGE,
                "SELECT c.topic, c.depth_score, c.bias_score, c.created_at "
                "FROM c WHERE c.verdict = 'APPROVED' AND c.created_at >= @since",
                params=[{"name": "@since", "value": since}],
            )
            all_flagged = await db.query(
                CONTAINER_KNOWLEDGE,
                "SELECT c.topic FROM c "
                "WHERE c.verdict IN ('FLAGGED','REJECTED') AND c.created_at >= @since",
                params=[{"name": "@since", "value": since}],
            )
            logs = await db.query(
                CONTAINER_LOGS,
                "SELECT c.agent_name, c.action, c.detail FROM c "
                "WHERE c.timestamp >= @since",
                params=[{"name": "@since", "value": since}],
            )

        # Aggregate by topic
        topic_approved: dict[str, int] = defaultdict(int)
        topic_rejected: dict[str, int] = defaultdict(int)
        for doc in all_approved:
            topic_approved[doc.get("topic", "general")] += 1
        for doc in all_flagged:
            topic_rejected[doc.get("topic", "general")] += 1

        # Update Thompson Sampling weights
        all_topics = set(list(topic_approved.keys()) + list(topic_rejected.keys()))
        for t in all_topics:
            self._selector.update(t, topic_approved[t], topic_rejected[t])

        # Average quality
        avg_depth = (
            round(float(np.mean([d.get("depth_score", 0) for d in all_approved])), 3)
            if all_approved else 0.0
        )
        avg_bias = (
            round(float(np.mean([d.get("bias_score", 0) for d in all_approved])), 3)
            if all_approved else 0.0
        )

        return {
            "period_days":     days,
            "items_approved":  len(all_approved),
            "items_flagged":   len(all_flagged),
            "avg_depth":       avg_depth,
            "avg_bias":        avg_bias,
            "topics_active":   list(all_topics),
            "topic_counts":    dict(topic_approved),
            "agent_actions":   len(logs),
            "topic_weights":   self._selector.get_weights(),
        }

    async def _gather_trend_data(self) -> dict[str, list[int]]:
        """Build daily count timeseries per topic over _TREND_WINDOW_DAYS."""
        since = (datetime.now(timezone.utc) - timedelta(days=_TREND_WINDOW_DAYS)).isoformat()

        async with AriaCosmosClient() as db:
            docs = await db.query(
                CONTAINER_KNOWLEDGE,
                "SELECT c.topic, c.created_at FROM c "
                "WHERE c.verdict = 'APPROVED' AND c.created_at >= @since",
                params=[{"name": "@since", "value": since}],
            )

        # Build day → topic → count
        day_topic: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for doc in docs:
            try:
                day = doc["created_at"][:10]   # YYYY-MM-DD
                day_topic[day][doc.get("topic", "general")] += 1
            except Exception:
                pass

        # Pivot to topic → [count_day0, count_day1, ...]
        all_days = sorted(day_topic.keys())
        topics   = set(t for d in day_topic.values() for t in d)
        return {
            topic: [day_topic[day].get(topic, 0) for day in all_days]
            for topic in topics
        }

    # ── Report generation ──────────────────────────────────────────────────────

    async def _compose_report(self, report_type: str, stats: dict,
                               trends: dict, featured_topics: list[str]) -> str:
        """Use Qwen to write the narrative report."""
        trend_lines = "\n".join(
            f"  - {t}: {v['direction']} (slope={v['slope']}, avg={v['average']} items/day)"
            for t, v in trends.items()
        )
        topic_lines = "\n".join(f"  - {t}" for t in featured_topics)

        prompt = (
            f"You are ARIA writing a {report_type} intelligence briefing for Sean.\n\n"
            f"STATS ({stats['period_days']} days):\n"
            f"  Items approved: {stats['items_approved']}\n"
            f"  Items flagged: {stats['items_flagged']}\n"
            f"  Avg depth score: {stats['avg_depth']}\n"
            f"  Avg bias score: {stats['avg_bias']}\n"
            f"  Agent actions logged: {stats['agent_actions']}\n\n"
            f"TOPIC TRENDS:\n{trend_lines or '  No trend data yet.'}\n\n"
            f"FEATURED TOPICS (highest value by Thompson Sampling):\n{topic_lines or '  None yet.'}\n\n"
            f"Write a concise, direct intelligence briefing in ARIA's voice. "
            f"Use bullet points. Highlight what BaobabGPT learned, what gaps remain, "
            f"and recommended focus areas for the next cycle. Keep under 400 words."
        )

        try:
            raw = await qwen.generate_report({"prompt": prompt, "period": f"{stats['period_days']} days"})
            return raw if isinstance(raw, str) else str(raw)
        except Exception as e:
            logger.warning(f"Qwen report generation failed: {e}")
            return self._fallback_report(stats, trends, featured_topics)

    def _fallback_report(self, stats: dict, trends: dict, featured_topics: list) -> str:
        """Plain-text fallback if Qwen is unavailable."""
        lines = [
            f"ARIA Daily Briefing — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            f"- Items approved: {stats['items_approved']}",
            f"- Items flagged:  {stats['items_flagged']}",
            f"- Avg depth:      {stats['avg_depth']}",
            f"- Avg bias:       {stats['avg_bias']}",
            "",
            "Trending topics:",
        ]
        for topic, trend in list(trends.items())[:5]:
            lines.append(f"  • {topic}: {trend['direction']} (slope={trend['slope']})")
        lines.append("")
        lines.append("Featured topics: " + ", ".join(featured_topics[:5] or ["None yet"]))
        return "\n".join(lines)

    # ── Public run methods ─────────────────────────────────────────────────────

    async def run_daily_report(self) -> dict:
        """Generate and store a daily report. Called nightly at 23:00 Harare."""
        logger.info("ReporterAgent: generating daily report")

        stats    = await self._gather_stats(days=1)
        td       = await self._gather_trend_data()
        trends   = self._trends.analyse_topics(td)
        featured = self._selector.select(stats["topics_active"], _MAX_REPORT_TOPICS)

        narrative = await self._compose_report("Daily", stats, trends, featured)

        report = {
            "report_type":     "daily",
            "generated_at":    datetime.now(timezone.utc).isoformat(),
            "stats":           stats,
            "trends":          trends,
            "featured_topics": featured,
            "narrative":       narrative,
        }

        async with AriaCosmosClient() as db:
            stored = await db.upsert(CONTAINER_REPORTS, report)
            await db.log("reporter_agent", "DAILY_REPORT", {
                "items": stats["items_approved"],
                "topics": featured,
            })

        logger.info(f"ReporterAgent: daily report stored {stored['id']}")
        return report

    async def run_weekly_report(self) -> dict:
        """Generate and store a weekly report (summarises 7 days)."""
        logger.info("ReporterAgent: generating weekly report")

        stats    = await self._gather_stats(days=7)
        td       = await self._gather_trend_data()
        trends   = self._trends.analyse_topics(td)
        featured = self._selector.select(stats["topics_active"], _MAX_REPORT_TOPICS)

        narrative = await self._compose_report("Weekly", stats, trends, featured)

        report = {
            "report_type":     "weekly",
            "generated_at":    datetime.now(timezone.utc).isoformat(),
            "stats":           stats,
            "trends":          trends,
            "featured_topics": featured,
            "narrative":       narrative,
        }

        async with AriaCosmosClient() as db:
            stored = await db.upsert(CONTAINER_REPORTS, report)
            await db.log("reporter_agent", "WEEKLY_REPORT", {
                "items_7d": stats["items_approved"],
                "top_topics": featured[:3],
            })

        logger.info(f"ReporterAgent: weekly report stored {stored['id']}")
        return report

    async def get_latest_report(self, report_type: str = "daily") -> Optional[dict]:
        """Fetch the most recent report of a given type from Cosmos."""
        async with AriaCosmosClient() as db:
            results = await db.query(
                CONTAINER_REPORTS,
                "SELECT TOP 1 * FROM c WHERE c.report_type = @type ORDER BY c.generated_at DESC",
                params=[{"name": "@type", "value": report_type}],
            )
        return results[0] if results else None

    async def morning_briefing_text(self) -> str:
        """Return a short morning briefing string for the admin UI."""
        import json as _json
        report = await self.get_latest_report("daily")
        if not report:
            return "ARIA: No recent activity data yet. I'm still building my knowledge base."
        stats = report.get("stats", {})
        featured = report.get("featured_topics", [])
        stats_json = _json.dumps({
            "date":            datetime.now(timezone.utc).strftime("%A %d %B %Y"),
            "items_approved":  stats.get("items_approved", 0),
            "items_flagged":   stats.get("items_flagged", 0),
            "top_topic":       featured[0] if featured else "general",
            "avg_depth":       stats.get("avg_depth", 0),
            "agent_actions":   stats.get("agent_actions", 0),
            "topic_weights":   stats.get("topic_weights", {}),
        }, indent=2)
        return MORNING_BRIEFING_TEMPLATE.format(stats_json=stats_json)
