
"""Background scheduler for automated investment opportunity scanning."""

import os
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from investment.opportunity_engine import execute_scan_pipeline


logger = logging.getLogger(__name__)

OPPORTUNITY_SCAN_INTERVAL_MINUTES = int(
    os.getenv("OPPORTUNITY_SCAN_INTERVAL_MINUTES", 30)
)

_scheduler = None


def _run_scheduled_scan():
    """Run one scheduled opportunity scan safely."""
    try:
        logger.info("Starting scheduled opportunity scan...")

        result = execute_scan_pipeline()

        if isinstance(result, dict):
            opportunities = result.get("opportunities", [])
            logger.info(
                "Scheduled opportunity scan completed: %d opportunities found.",
                len(opportunities),
            )
        else:
            logger.info("Scheduled opportunity scan completed.")

    except Exception:
        logger.exception("Scheduled opportunity scan failed.")


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
        "Opportunity scanner scheduled every %d minutes.",
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

