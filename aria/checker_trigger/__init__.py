"""
Azure Function Timer Trigger: Checker cycle
Schedule target: every 1 hour.
"""
import asyncio
import logging
import os
import sys

import azure.functions as func

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from main import AriaOrchestrator

logger = logging.getLogger(__name__)


def main(mytimer: func.TimerRequest) -> None:
    try:
        stats = asyncio.run(AriaOrchestrator().run_checker(max_messages=50))
        logger.info("checker_trigger complete: %s", stats)
    except Exception as exc:
        logger.exception("checker_trigger failed: %s", exc)
        raise
