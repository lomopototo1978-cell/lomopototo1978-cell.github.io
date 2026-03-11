"""
Azure Function Timer Trigger: Daily reporter cycle.
Target: 23:00 Africa/Harare daily.
Azure timer schedules are UTC by default, so this is set to 21:00 UTC.
"""
import asyncio
import logging
import os
import sys

import azure.functions as func

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from main import AriaOrchestrator

logger = logging.getLogger(__name__)


def main(mytimer: func.TimerRequest) -> None:
    try:
        report = asyncio.run(AriaOrchestrator().run_daily_report())
        logger.info("reporter_trigger complete: %s", report)
    except Exception as exc:
        logger.exception("reporter_trigger failed: %s", exc)
        raise
