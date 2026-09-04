"""Portfolio-aware SELL scanner.

Deliberately the mirror image of opportunity_engine.py's BUY scanner:

    BUY scanner  → entire market universe → "what should I buy?"
    SELL scanner → only symbols a user already holds → "should I exit?"

A symbol NEVER appears as a SELL opportunity unless at least one user is
currently holding it. If nobody owns NVDA, NVDA is never analyzed here,
let alone surfaced.

Flow:
    Firestore (every user's portfolio/summary)
        ↓
    aggregate held symbols → { symbol: {holder_user_ids} }
        ↓
    same MultiAgentOrchestrator used by the BUY scanner
        ↓
    keep SELL decisions only, above the confidence threshold
        ↓
    cached in opportunity_engine's shared analysis cache
        ↓
    notification — scoped ONLY to the users who actually hold that symbol
        ↓
    /api/opportunities/<id>/prepare
"""

import uuid
import logging
from datetime import datetime, timezone

from firebase_admin import firestore

from investment import opportunity_engine
from agents.orchestrator import MultiAgentOrchestrator
from services.portfolio_service import get_portfolio_state

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.55

_LATEST_SELL_OPPORTUNITIES = {
    "generated_at": None,
    "status": "AWAITING_SCAN",
    "opportunities": [],
    "metadata": {},
}


def _extract_quantity(position) -> float:
    """Extract a numeric quantity from a portfolio position."""

    if isinstance(position, dict):
        qty = position.get("quantity", position.get("shares", position.get("qty")))
    else:
        qty = position

    try:
        return float(qty)
    except (TypeError, ValueError):
        return 0.0


def _get_held_symbols() -> dict:
    """
    Scans every user's portfolio summary doc and returns:

        {
            "AAPL": {"uid_1", "uid_4"},
            "NVDA": {"uid_2"}
        }

    This dict IS the SELL scanner's entire universe — it never looks at
    the broader market. Closed/zeroed-out positions are excluded.
    """

    db = firestore.client()
    holders = {}

    try:
        users = db.collection("users").stream()
    except Exception:
        logger.exception("Failed to list users for SELL scan")
        return holders

    for user_doc in users:
        user_id = user_doc.id

        try:
            portfolio_state = get_portfolio_state(user_id)
        except Exception:
            logger.exception(
                "Failed to load portfolio for user %s",
                user_id,
            )
            continue

        positions = portfolio_state.get("positions", {})

        if not isinstance(positions, dict):
            continue

        for symbol, position in positions.items():
            quantity = _extract_quantity(position)

            # User does not currently hold this asset.
            if quantity <= 0:
                continue

            normalized_symbol = str(symbol).strip().upper()

            if not normalized_symbol:
                continue

            holders.setdefault(
                normalized_symbol,
                set(),
            ).add(user_id)

    return holders


def _execute_sell_scan_pipeline():
    """Internal SELL discovery implementation.

    Caller must hold the shared scan lock.
    """

    global _LATEST_SELL_OPPORTUNITIES

    logger.info(
        "Starting portfolio-aware opportunity scan (SELL)..."
    )

    holders = _get_held_symbols()

    if not holders:
        logger.info(
            "SELL scan: no user currently holds any position."
        )

        _LATEST_SELL_OPPORTUNITIES = {
            "generated_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "status": "SUCCESS",
            "opportunities": [],
            "metadata": {
                "symbols_analyzed": 0,
                "failed_analyses": 0,
            },
        }

        return _LATEST_SELL_OPPORTUNITIES

    orchestrator = MultiAgentOrchestrator()

    valid_opportunities = []
    failed = 0

    for symbol, holder_ids in holders.items():

        try:
            analysis = orchestrator.analyze_stock_sync(
                symbol,
                quantitative_screen=None,
            )

            if not isinstance(analysis, dict):
                logger.warning(
                    "SELL analysis returned invalid data for %s",
                    symbol,
                )
                failed += 1
                continue

            decision = str(
                analysis.get("decision", "HOLD")
            ).upper()

            try:
                confidence = float(
                    analysis.get("confidence", 0.0)
                )
            except (TypeError, ValueError):
                confidence = 0.0

            # SELL scanner only surfaces SELL decisions.
            if (
                decision == "SELL"
                and confidence >= CONFIDENCE_THRESHOLD
            ):
                # Backend owns the opportunity ID.
                analysis_id = analysis.get("analysis_id")

                if not analysis_id:
                    analysis_id = str(uuid.uuid4())
                    analysis["analysis_id"] = analysis_id

                opportunity_engine.cache_analysis(
                    analysis_id,
                    {
                        "analysis": analysis,
                        "symbol": symbol,
                        "decision": decision,
                        "confidence": confidence,
                        "spot_price": analysis.get(
                            "current_price"
                        ),
                        "created_at": datetime.now(
                            timezone.utc
                        ),
                        "kind": "SELL",
                        "holder_user_ids": sorted(
                            holder_ids
                        ),
                    },
                )

                valid_opportunities.append(
                    {
                        "symbol": symbol,
                        "decision": decision,
                        "confidence": confidence,
                        "risk_level": analysis.get(
                            "risk_level",
                            "UNKNOWN",
                        ),
                        "analysis_id": analysis_id,
                        "kind": "SELL",
                        "holder_user_ids": sorted(
                            holder_ids
                        ),
                    }
                )

        except Exception:
            failed += 1

            logger.exception(
                "SELL analysis failed for %s",
                symbol,
            )

            continue

    valid_opportunities.sort(
        key=lambda x: x["confidence"],
        reverse=True,
    )

    _LATEST_SELL_OPPORTUNITIES = {
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "status": "SUCCESS",
        "opportunities": valid_opportunities,
        "metadata": {
            "symbols_analyzed": len(holders),
            "failed_analyses": failed,
        },
    }

    logger.info(
    "SELL scan complete. %d SELL opportunities "
    "found across %d held symbols.",
    len(valid_opportunities),
    len(holders),
    )

    # Claim notification records before sending.
    # This prevents the same analysis_id from being submitted
    # multiple times.
    new_opportunities = opportunity_engine.claim_new_opportunities(
        valid_opportunities
    )
    
    logger.info(
        "SELL notification claim complete. %d new opportunities.",
        len(new_opportunities),
    )
    
    if new_opportunities:
        # Actually act on it per each holder's saved execution mode
        # (alert-only / confirm-each / fully automated). dispatch_sell_
        # opportunity already scopes to opportunity['holder_user_ids'],
        # matching the SELL scanner's "only people who hold it" rule.
        opportunity_engine.submit_dispatch_job(
            new_opportunities, kind="SELL"
        )

    return _LATEST_SELL_OPPORTUNITIES


def execute_sell_scan_pipeline():
    """
    Public entry point for manual and scheduled SELL scans.

    Shares opportunity_engine's scan lock with the BUY scanner.
    """

    if not opportunity_engine.acquire_scan_lock(
        blocking=False
    ):
        logger.warning(
            "SELL scan skipped: another scan is already running."
        )

        return {
            "status": "SCAN_ALREADY_IN_PROGRESS",
            "opportunities": [],
            "metadata": {},
        }

    try:
        return _execute_sell_scan_pipeline()

    finally:
        opportunity_engine.release_scan_lock()


def get_latest_sell_opportunities():
    return _LATEST_SELL_OPPORTUNITIES
