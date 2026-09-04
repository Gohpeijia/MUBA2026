import os
import uuid
import logging
import threading
import concurrent.futures
from datetime import datetime, timezone, timedelta

from firebase_admin import firestore
from services.notification_service import notify_users_of_opportunities

from investment.asset_universe import get_scan_universe
from investment.screener import screen_asset
from investment.candidate_ranker import rank_candidates
from agents.orchestrator import MultiAgentOrchestrator

logger = logging.getLogger(__name__)

ANALYSIS_CACHE_TTL_MINUTES = int(os.getenv("ANALYSIS_CACHE_TTL_MINUTES", 30))
TOP_N = int(os.getenv("TOP_N_OPPORTUNITIES", 5))
CONFIDENCE_THRESHOLD = 0.55

_NOTIFICATION_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=1)

def _handle_notification_result(future):
    try:
        successful_ids = future.result()

        if not successful_ids:
            return

        db = firestore.client()

        for analysis_id in successful_ids:
            try:
                doc_ref = (
                    db.collection(
                        "opportunity_notifications"
                    )
                    .document(analysis_id)
                )

                doc_ref.update(
                    {
                        "status": "NOTIFIED",
                        "notified_at": datetime.now(
                            timezone.utc
                        ).isoformat(),
                    }
                )

                logger.info(
                    "Successfully marked opportunity %s "
                    "as NOTIFIED.",
                    analysis_id,
                )

            except Exception:
                logger.exception(
                    "Failed to mark opportunity %s as NOTIFIED.",
                    analysis_id,
                )

    except Exception:
        logger.exception(
            "Notification task failed entirely."
        )


def submit_notification_job(opportunities):
    """
    Public wrapper around the shared notification executor + callback.

    Exists so sibling scanners (e.g. sell_scanner.py) can push notifications
    through the exact same async path as the BUY scanner without reaching
    into this module's private executor/callback.
    """
    future = _NOTIFICATION_EXECUTOR.submit(notify_users_of_opportunities, opportunities)
    future.add_done_callback(_handle_notification_result)


def _dispatch_opportunities_sync(opportunities, dispatch_fn):
    """
    Runs dispatch_fn (dispatch_buy_opportunity / dispatch_sell_opportunity)
    for every opportunity, one at a time. Each call is itself per-user and
    mode-aware — it reads riskCopilotMode and does the right thing (alert,
    create a confirmation, or execute) for every targeted user.

    Returns the union of analysis_ids that were successfully dispatched to
    at least one user, in the same shape _handle_notification_result expects.
    """
    successful_ids = set()
    for opportunity in opportunities or []:
        try:
            for analysis_id in dispatch_fn(opportunity):
                successful_ids.add(analysis_id)
        except Exception:
            logger.exception(
                "Dispatch failed for opportunity %s",
                opportunity.get("analysis_id"),
            )
    return list(successful_ids)


def submit_dispatch_job(opportunities, *, kind: str = "BUY"):
    """
    Public entry point for actually acting on newly-claimed opportunities,
    per user preference — as opposed to submit_notification_job, which only
    sends the generic "new opportunity found" broadcast push.

    This is what makes "Fully automated recommendations" actually execute,
    "Suggest actions, I confirm each one" actually pop the confirmation
    card, and "Alert me only" actually stay hands-off. Without this call,
    services/opportunity_action_service.py's per-mode logic is never
    reached by the scanners — only by the ad-hoc chat/confirm-trade paths.

    Runs on the same background executor as notifications so a slow batch
    of trade preparations/executions never blocks the scan loop itself.
    """
    from services.opportunity_action_service import dispatch_buy_opportunity, dispatch_sell_opportunity

    dispatch_fn = dispatch_sell_opportunity if kind == "SELL" else dispatch_buy_opportunity
    future = _NOTIFICATION_EXECUTOR.submit(_dispatch_opportunities_sync, opportunities, dispatch_fn)
    future.add_done_callback(_handle_notification_result)


# Prevent overlapping scans. Shared by BUY and SELL — both hit the same
# rate-limited data/AI providers, so they must never run concurrently.
_SCAN_LOCK = threading.Lock()


def acquire_scan_lock(blocking: bool = False) -> bool:
    """Acquire the shared scan lock. Used by both this module's
    execute_scan_pipeline() and sell_scanner.execute_sell_scan_pipeline()."""
    return _SCAN_LOCK.acquire(blocking=blocking)


def release_scan_lock() -> None:
    _SCAN_LOCK.release()


# Shared analysis cache. BUY and SELL entries both live here, tagged with
# "kind": "BUY" / "kind": "SELL", so /prepare's get_cached_entry() works
# identically regardless of which scanner produced the entry.
_ANALYSIS_CACHE = {}


def cache_analysis(analysis_id: str, entry: dict) -> None:
    """Public setter so sell_scanner.py can populate the same cache that
    /prepare reads from via get_cached_entry()."""
    _ANALYSIS_CACHE[analysis_id] = entry


_LATEST_OPPORTUNITIES = {
    "generated_at": None,
    "status": "AWAITING_SCAN",
    "opportunities": [],
    "metadata": {},
}

def claim_new_opportunities(opportunities):
    """
    Atomically claims notification records for opportunities that have not
    already been claimed.

    Returns only opportunities that this process successfully claimed.

    Both BUY and SELL scanners use this function.
    """

    if not opportunities:
        return []

    db = firestore.client()
    new_opportunities = []

    @firestore.transactional
    def claim_opportunity(transaction, ref):
        snapshot = ref.get(transaction=transaction)

        if snapshot.exists:
            return False

        transaction.set(
            ref,
            {
                "status": "PENDING",
                "created_at": datetime.now(
                    timezone.utc
                ).isoformat(),
                "notified_at": None,
            },
        )

        return True

    for opportunity in opportunities:
        analysis_id = opportunity.get("analysis_id")

        if not analysis_id:
            logger.warning(
                "Skipping opportunity without analysis_id: %s",
                opportunity,
            )
            continue

        doc_ref = (
            db.collection("opportunity_notifications")
            .document(analysis_id)
        )

        transaction = db.transaction()

        try:
            claimed = claim_opportunity(
                transaction,
                doc_ref,
            )

            if claimed:
                new_opportunities.append(opportunity)

        except Exception:
            logger.exception(
                "Failed to claim opportunity %s",
                analysis_id,
            )

    return new_opportunities

def _execute_scan_pipeline():
    """Internal BUY discovery implementation. Caller must hold _SCAN_LOCK.

    Scans the ENTIRE market universe for new entry opportunities. This
    scanner is deliberately blind to any individual user's portfolio —
    that's the SELL scanner's job (see investment/sell_scanner.py).
    """
    global _LATEST_OPPORTUNITIES

    logger.info("Starting automated opportunity scan (BUY)...")

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

            # BUY scanner only ever surfaces BUY. A SELL decision here is
            # meaningless (nothing was bought yet) and is intentionally
            # dropped — SELL signals only come from sell_scanner.py, and
            # only for symbols a user actually holds.
            if decision == "BUY" and confidence >= CONFIDENCE_THRESHOLD:

                analysis_id = analysis.get("analysis_id")

                if not analysis_id:
                    analysis_id = str(uuid.uuid4())
                    analysis["analysis_id"] = analysis_id
                
                analysis["analysis_id"] = analysis_id

                cache_analysis(analysis_id, {
                    "analysis": analysis,
                    "symbol": symbol,
                    "decision": decision,
                    "confidence": confidence,
                    "spot_price": analysis.get("current_price"),
                    "created_at": datetime.now(timezone.utc),
                    "screen_score": candidate["score"],
                    "kind": "BUY",
                })

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
                    "kind": "BUY",
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

    new_opportunities = claim_new_opportunities(
         valid_opportunities
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
        f"BUY scan complete. {len(valid_opportunities)} opportunities found. {len(new_opportunities)} new."
    )

    if new_opportunities:
        # BUY opportunities broadcast to every opted-in user — discovery is
        # not user-specific, unlike SELL. This is the generic "new
        # opportunity found" push only.
        submit_notification_job(new_opportunities)

        # Separately, actually act on it per each user's saved execution
        # mode (alert-only / confirm-each / fully automated). Without this,
        # AUTOMATED_MODE users never get an auto-executed trade from the
        # scanner — only the passive discovery notification above.
        submit_dispatch_job(new_opportunities, kind="BUY")

    return _LATEST_OPPORTUNITIES


def execute_scan_pipeline():
    """
    Public entry point for manual and scheduled BUY scans.

    Uses the shared process-local lock so a scheduled/manual BUY scan and
    a SELL scan (or another BUY scan) can never run simultaneously.
    """
    if not acquire_scan_lock(blocking=False):
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
        release_scan_lock()


def get_latest_buy_opportunities():
    return _LATEST_OPPORTUNITIES


# Kept for backward compatibility with existing callers (e.g. market_routes
# or older frontend code) that expect the BUY-only shape. New code should
# prefer investment_opportunity_routes.get_opportunities(), which merges
# BUY and SELL.
def get_latest_opportunities():
    return _LATEST_OPPORTUNITIES


def get_cached_entry(analysis_id: str):
    """Returns the full backend cache entry (analysis + symbol + decision +
    spot_price), or None if missing/expired. Internal use by the /prepare
    route only — never exposed directly to the frontend.

    Shared by both BUY and SELL entries (see cache_analysis() above)."""
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