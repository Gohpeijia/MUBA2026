import os
import uuid
import logging
import threading
from datetime import datetime, timezone, timedelta

from investment.asset_universe import get_scan_universe
from investment.screener import screen_asset
from investment.candidate_ranker import rank_candidates
from agents.orchestrator import MultiAgentOrchestrator

logger = logging.getLogger(__name__)

ANALYSIS_CACHE_TTL_MINUTES = int(os.getenv("ANALYSIS_CACHE_TTL_MINUTES", 30))
TOP_N = int(os.getenv("TOP_N_OPPORTUNITIES", 5))
CONFIDENCE_THRESHOLD = 0.55

# Prevent overlapping manual/scheduled scans.
_SCAN_LOCK = threading.Lock()

_ANALYSIS_CACHE = {}
_LATEST_OPPORTUNITIES = {
    "generated_at": None,
    "status": "AWAITING_SCAN",
    "opportunities": [],
    "metadata": {},
}


def _execute_scan_pipeline():
    """Internal discovery implementation. Caller must hold _SCAN_LOCK."""
    global _LATEST_OPPORTUNITIES

    logger.info("Starting automated opportunity scan...")

    universe = get_scan_universe()
    screened_results = []
    failed_screenings = 0

    for symbol in universe:
        result = screen_asset(symbol)
        screened_results.append(result)

        if result.get("status") == "FAILED":
            failed_screenings += 1

    top_candidates = rank_candidates(
        screened_results,
        limit=TOP_N,
    )

    orchestrator = MultiAgentOrchestrator()
    valid_opportunities = []

    for candidate in top_candidates:
        symbol = candidate["symbol"]

        try:
            analysis = orchestrator.analyze_stock_sync(
                symbol,
                quantitative_screen=candidate,
            )

            decision = analysis.get("decision", "HOLD")
            confidence = float(
                analysis.get("confidence", 0.0)
            )

            if decision in ("BUY", "SELL") and confidence >= CONFIDENCE_THRESHOLD:

                analysis_id = (
                    analysis.get("analysis_id")
                    or str(uuid.uuid4())
                )

                analysis["analysis_id"] = analysis_id

                _ANALYSIS_CACHE[analysis_id] = {
                    "analysis": analysis,
                    "symbol": symbol,
                    "decision": decision,
                    "confidence": confidence,
                    "spot_price": analysis.get("current_price"),
                    "created_at": datetime.now(timezone.utc),
                    "screen_score": candidate["score"],
                }

                valid_opportunities.append({
                    "symbol": symbol,
                    "decision": decision,
                    "confidence": confidence,
                    "risk_level": analysis.get(
                        "risk_level",
                        "UNKNOWN",
                    ),
                    "screen_score": candidate["score"],
                    "analysis_id": analysis_id,
                })

        except Exception as e:
            logger.error(
                f"MultiAgentOrchestrator failed for {symbol}: {e}"
            )
            continue

    valid_opportunities.sort(
        key=lambda x: x["confidence"],
        reverse=True,
    )

    _LATEST_OPPORTUNITIES = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "SUCCESS",
        "opportunities": valid_opportunities,
        "metadata": {
            "successful_screenings": (
                len(universe) - failed_screenings
            ),
            "failed_screenings": failed_screenings,
            "candidates_analyzed": len(top_candidates),
        },
    }

    logger.info(
        f"Scan complete. {len(valid_opportunities)} opportunities found."
    )

    return _LATEST_OPPORTUNITIES


def execute_scan_pipeline():
    """
    Public entry point for manual and scheduled scans.

    Uses one shared process-local lock so a scheduled scan and a
    manually triggered scan cannot run simultaneously.
    """
    if not _SCAN_LOCK.acquire(blocking=False):
        logger.warning(
            "Opportunity scan skipped: another scan is already running."
        )

        return {
            "status": "SCAN_ALREADY_IN_PROGRESS",
            "opportunities": [],
            "metadata": {},
        }

    try:
        return _execute_scan_pipeline()

    finally:
        _SCAN_LOCK.release()


def get_latest_opportunities():
    return _LATEST_OPPORTUNITIES


def get_cached_entry(analysis_id: str):
    """Returns the full backend cache entry (analysis + symbol + decision +
    spot_price), or None if missing/expired. Internal use by the /prepare
    route only — never exposed directly to the frontend."""
    entry = _ANALYSIS_CACHE.get(analysis_id)

    if not entry:
        return None

    if (
        datetime.now(timezone.utc) - entry["created_at"]
        > timedelta(minutes=ANALYSIS_CACHE_TTL_MINUTES)
    ):
        del _ANALYSIS_CACHE[analysis_id]
        return None

    return entry