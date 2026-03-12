"""
Azure Function Timer Trigger: Scout cycle
Schedule target: every 4 hours.
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
        stats = asyncio.run(AriaOrchestrator().run_scout())
        logger.info("scout_trigger complete: %s", stats)
    except Exception as exc:
        logger.exception("scout_trigger failed: %s", exc)
        raise
