"""
ARIA Orchestrator (Phase 6)
Coordinates Scout, Checker, Memory maintenance, and Reporter cycles.
"""
import argparse
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from agents.scout_agent import run_research_cycle
from agents.checker_agent import get_checker
from agents.reporter_agent import ReporterAgent
from agents.memory_agent import get_memory_agent
from database.cosmos_client import AriaCosmosClient

logger = logging.getLogger("aria.orchestrator")


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


class AriaOrchestrator:
    def __init__(self):
        self._checker = get_checker()
        self._reporter = ReporterAgent()
        self._memory = get_memory_agent()

    async def run_scout(self, topics: Optional[list[str]] = None) -> dict:
        stats = await run_research_cycle(topics=topics)
        await self._log("orchestrator", "SCOUT_CYCLE", stats)
        return stats

    async def run_checker(self, max_messages: int = 20) -> dict:
        stats = await self._checker.run_checker_cycle(max_messages=max_messages)
        await self._log("orchestrator", "CHECKER_CYCLE", stats)
        return stats

    async def run_memory_maintenance(self) -> dict:
        dedup = await self._memory.dedup_sweep()
        expiry = await self._memory.expiry_sweep()
        stats = {
            "dedup": dedup,
            "expiry": expiry,
        }
        await self._log("orchestrator", "MEMORY_MAINTENANCE", stats)
        return stats

    async def run_daily_report(self) -> dict:
        report = await self._reporter.run_daily_report()
        summary = {
            "report_type": "daily",
            "generated_at": report.get("generated_at"),
            "items_approved": report.get("stats", {}).get("items_approved", 0),
            "items_flagged": report.get("stats", {}).get("items_flagged", 0),
        }
        await self._log("orchestrator", "DAILY_REPORT", summary)
        return summary

    async def run_weekly_report(self) -> dict:
        report = await self._reporter.run_weekly_report()
        summary = {
            "report_type": "weekly",
            "generated_at": report.get("generated_at"),
            "items_approved": report.get("stats", {}).get("items_approved", 0),
            "items_flagged": report.get("stats", {}).get("items_flagged", 0),
        }
        await self._log("orchestrator", "WEEKLY_REPORT", summary)
        return summary

    async def run_all_once(self) -> dict:
        started = datetime.now(timezone.utc).isoformat()
        scout = await self.run_scout()
        checker = await self.run_checker()
        maintenance = await self.run_memory_maintenance()
        report = await self.run_daily_report()
        completed = datetime.now(timezone.utc).isoformat()
        summary = {
            "started_at": started,
            "completed_at": completed,
            "scout": scout,
            "checker": checker,
            "memory": maintenance,
            "report": report,
        }
        await self._log("orchestrator", "RUN_ALL_ONCE", summary)
        return summary

    async def _log(self, agent_name: str, action: str, detail: dict) -> None:
        try:
            async with AriaCosmosClient() as db:
                await db.log(agent_name, action, detail)
        except Exception as exc:
            logger.warning("Log write failed for %s:%s: %s", agent_name, action, exc)


async def _run_cli(mode: str, topics: Optional[list[str]], max_messages: int) -> dict:
    app = AriaOrchestrator()
    if mode == "scout":
        return {"mode": mode, "result": await app.run_scout(topics=topics)}
    if mode == "checker":
        return {"mode": mode, "result": await app.run_checker(max_messages=max_messages)}
    if mode == "memory":
        return {"mode": mode, "result": await app.run_memory_maintenance()}
    if mode == "daily-report":
        return {"mode": mode, "result": await app.run_daily_report()}
    if mode == "weekly-report":
        return {"mode": mode, "result": await app.run_weekly_report()}
    return {"mode": "all", "result": await app.run_all_once()}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ARIA orchestrator")
    parser.add_argument(
        "--mode",
        choices=["all", "scout", "checker", "memory", "daily-report", "weekly-report"],
        default="all",
    )
    parser.add_argument("--topics", nargs="*", default=None)
    parser.add_argument("--max-messages", type=int, default=20)
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    configure_logging(args.log_level)
    result = asyncio.run(_run_cli(args.mode, args.topics, args.max_messages))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
