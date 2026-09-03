"""Background scheduler for automated investment opportunity scanning.

Each tick runs the market-wide BUY scanner, then the portfolio-aware SELL
scanner, sequentially. They share a lock (opportunity_engine._SCAN_LOCK) so
running them back-to-back in one job — rather than as two competing jobs —
avoids one silently skipping because the other grabbed the lock first.
"""

import os
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from investment.opportunity_engine import execute_scan_pipeline
from investment.sell_scanner import execute_sell_scan_pipeline


logger = logging.getLogger(__name__)

OPPORTUNITY_SCAN_INTERVAL_MINUTES = int(
    os.getenv("OPPORTUNITY_SCAN_INTERVAL_MINUTES", 30)
)

_scheduler = None


def _run_scheduled_buy_scan():
    try:
        logger.info("Starting scheduled opportunity scan (BUY)...")

        result = execute_scan_pipeline()

        if isinstance(result, dict):
            opportunities = result.get("opportunities", [])
            logger.info(
                "Scheduled BUY scan completed: %d opportunities found.",
                len(opportunities),
            )
        else:
            logger.info("Scheduled BUY scan completed.")

    except Exception:
        logger.exception("Scheduled BUY scan failed.")


def _run_scheduled_sell_scan():
    try:
        logger.info("Starting scheduled opportunity scan (SELL)...")

        result = execute_sell_scan_pipeline()

        if isinstance(result, dict):
            opportunities = result.get("opportunities", [])
            logger.info(
                "Scheduled SELL scan completed: %d opportunities found.",
                len(opportunities),
            )
        else:
            logger.info("Scheduled SELL scan completed.")

    except Exception:
        logger.exception("Scheduled SELL scan failed.")


def _run_scheduled_scan():
    """Run one BUY scan followed by one SELL scan, safely."""
    _run_scheduled_buy_scan()
    _run_scheduled_sell_scan()


def init_scheduler(app):
    """Initialize and start the background opportunity scanner."""
    global _scheduler

    # Prevent accidental duplicate scheduler instances.
    if _scheduler is not None:
        logger.info("Opportunity scheduler already initialized.")
        return _scheduler

    # Protect against Flask debug reloader creating two schedulers.
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        logger.info(
            "Skipping scheduler in Flask reloader parent process."
        )
        return None

    _scheduler = BackgroundScheduler(
        daemon=True,
        timezone="UTC",
    )

    _scheduler.add_job(
        func=_run_scheduled_scan,
        trigger="interval",
        minutes=OPPORTUNITY_SCAN_INTERVAL_MINUTES,
        id="opportunity_scanner",
        replace_existing=True,

        # Never allow multiple scans to run simultaneously.
        max_instances=1,

        # If a scheduled run is missed, execute only once.
        coalesce=True,
    )

    _scheduler.start()

    logger.info(
        "Opportunity scanner (BUY + SELL) scheduled every %d minutes.",
        OPPORTUNITY_SCAN_INTERVAL_MINUTES,
    )

    return _scheduler


def shutdown_scheduler():
    """Safely stop the background scheduler."""
    global _scheduler

    if _scheduler is None:
        return

    try:
        _scheduler.shutdown(wait=False)
        logger.info("Opportunity scheduler stopped.")
    except Exception:
        logger.exception("Failed to shut down opportunity scheduler.")
    finally:
        _scheduler = None