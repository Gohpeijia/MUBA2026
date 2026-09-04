"""API routes for automated investment opportunities and trade preparation.

Discovery is strictly separated from trade execution, AND (new) BUY
discovery is strictly separated from SELL discovery:

    opportunity_engine.py  → BUY  → scans the whole market
    sell_scanner.py        → SELL → scans only what users actually hold

Flow:
    BUY scanner (market-wide) ─┐
                                ├─→ backend cached analysis
    SELL scanner (holdings) ───┘
        ↓
    authenticated user
        ↓
    /prepare
        ↓
    user's preferences + portfolio  (+ ownership check for SELL)
        ↓
    advisor.trade_bridge.build_trade_proposal()
        ↓
    user confirmation
        ↓
    existing /confirm-trade
        ↓
    existing execution path
"""

import threading
import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, g

from investment.opportunity_engine import (
    execute_scan_pipeline,
    get_latest_buy_opportunities,
    get_cached_entry,
)
from investment.sell_scanner import (
    execute_sell_scan_pipeline,
    get_latest_sell_opportunities,
)

from services.opportunity_prepare_service import prepare_opportunity_for_user
from services.portfolio_service import get_portfolio_state, user_holds_symbol
from services.trade_confirmation_service import (
    get_confirmation,
    list_active_confirmations,
    confirm_confirmation,
    reject_confirmation,
)

from ai_agent import trader
from firebase_config import db
from security import require_auth

logger = logging.getLogger(__name__)

opportunities_bp = Blueprint(
    "opportunities",
    __name__,
    url_prefix="/api/opportunities",
)

_SCAN_STATUS = {
    "status": "IDLE",
    "started_at": None,
    "completed_at": None,
    "buy_opportunities": 0,
    "sell_opportunities": 0,
    "error": None,
}
_SCAN_STATUS_LOCK = threading.Lock()


def _update_scan_status(**updates):
    with _SCAN_STATUS_LOCK:
        _SCAN_STATUS.update(updates)
        return dict(_SCAN_STATUS)


def _current_scan_status():
    with _SCAN_STATUS_LOCK:
        return dict(_SCAN_STATUS)




# ─────────────────────────────────────────────────────────────────────────────
#  USER CONTEXT
# ─────────────────────────────────────────────────────────────────────────────

def _get_user_preferences(user_id: str) -> dict:
    """Load the user's saved investment/risk preferences."""
    try:
        doc = db.collection("users").document(user_id).get()

        if not doc.exists:
            return {}

        data = doc.to_dict() or {}
        preferences = data.get("preference", {})

        return preferences if isinstance(preferences, dict) else {}

    except Exception:
        logger.exception(
            "Failed to load preferences for user %s",
            user_id,
        )
        return {}


def _get_user_portfolio(user_id: str) -> dict:
    """Load the user's current portfolio summary."""
    try:
        portfolio_doc = (
            db.collection("users")
              .document(user_id)
              .collection("portfolio")
              .document("summary")
              .get()
        )

        if portfolio_doc.exists:
            portfolio_data = portfolio_doc.to_dict() or {}

            if isinstance(portfolio_data, dict):
                return portfolio_data

        # Same safe fallback used by /chat.
        return {
            "total_value": 0.0,
            "positions": {},
            "open_ai_risk_value": 0.0,
        }

    except Exception:
        logger.exception(
            "Failed to load portfolio for user %s",
            user_id,
        )

        return {
            "total_value": 0.0,
            "positions": {},
            "open_ai_risk_value": 0.0,
        }


def _user_holds_symbol(
    portfolio: dict,
    symbol: str,
) -> bool:
    """
    True when the user's portfolio contains a positive-quantity
    position matching the requested symbol.
    """
    positions = portfolio.get(
        "positions",
        {},
    )

    if not isinstance(positions, dict):
        return False

    target_symbol = str(
        symbol
    ).strip().upper()

    if not target_symbol:
        return False

    for position_symbol, position in positions.items():
        normalized_symbol = str(
            position_symbol
        ).strip().upper()

        if normalized_symbol != target_symbol:
            continue

        if isinstance(position, dict):
            qty = position.get(
                "quantity",
                position.get("qty"),
            )
        elif isinstance(position, (int, float)):
            qty = position
        else:
            qty = None

        try:
            return (
                qty is not None
                and float(qty) > 0
            )
        except (TypeError, ValueError):
            return False

    return False

def _filter_opportunities_for_user(
    opportunities: list,
    user_id: str,
) -> list:
    """
    Return only opportunities the authenticated user is allowed to see.

    BUY opportunities are global.

    SELL opportunities are user-specific and are returned only when
    the authenticated user currently holds the symbol.
    """
    filtered = []

    for opportunity in opportunities:
        if not isinstance(opportunity, dict):
            continue

        kind = str(
            opportunity.get("kind", "BUY")
        ).upper()

        # BUY opportunities are market-wide.
        if kind != "SELL":
            safe_opportunity = dict(opportunity)

            # Never expose internal holder information.
            safe_opportunity.pop(
                "holder_user_ids",
                None,
            )

            filtered.append(safe_opportunity)
            continue

        # SELL opportunities must belong to the authenticated user.
        holder_user_ids = opportunity.get(
            "holder_user_ids",
            [],
        )

        if user_id not in holder_user_ids:
            continue

        safe_opportunity = dict(opportunity)

        # holder_user_ids is backend-only information.
        safe_opportunity.pop(
            "holder_user_ids",
            None,
        )

        filtered.append(safe_opportunity)

    return filtered


# ─────────────────────────────────────────────────────────────────────────────
#  GET /api/opportunities
# ─────────────────────────────────────────────────────────────────────────────

@opportunities_bp.route("", methods=["GET"])
@require_auth
def get_opportunities():
    """
    Return opportunities visible to the authenticated user.

    BUY opportunities are global.

    SELL opportunities are returned only when the authenticated
    user currently holds the relevant symbol.
    """
    try:
        user_id = g.uid

        buy = get_latest_buy_opportunities()
        sell = get_latest_sell_opportunities()

        buy_opportunities = buy.get(
            "opportunities",
            [],
        )

        sell_opportunities = sell.get(
            "opportunities",
            [],
        )

        visible_buy = _filter_opportunities_for_user(
            buy_opportunities,
            user_id,
        )

        visible_sell = _filter_opportunities_for_user(
            sell_opportunities,
            user_id,
        )

        all_opportunities = (
            visible_buy + visible_sell
        )

        generated_dates = list(
            filter(
                None,
                [
                    buy.get("generated_at"),
                    sell.get("generated_at"),
                ],
            )
        )

        merged = {
            "generated_at": max(
                generated_dates,
                default=None,
            ),
            "status": buy.get(
                "status",
                "AWAITING_SCAN",
            ),
            "opportunities": all_opportunities,
            "metadata": {
                "buy": buy.get(
                    "metadata",
                    {},
                ),
                "sell": sell.get(
                    "metadata",
                    {},
                ),
            },
        }

        return jsonify(merged), 200

    except Exception:
        logger.exception(
            "Failed to retrieve opportunities"
        )

        return jsonify({
            "status": "ERROR",
            "error": "Failed to retrieve opportunities",
        }), 500


# ─────────────────────────────────────────────────────────────────────────────
#  POST /api/opportunities/scan
# ─────────────────────────────────────────────────────────────────────────────

@opportunities_bp.route("/scan", methods=["POST"])
@require_auth
def trigger_scan():
    """
    Start a manual discovery scan asynchronously: BUY first, then SELL.

    This endpoint ONLY discovers opportunities.
    It never prepares or executes a trade.

    BUY and SELL share opportunity_engine's scan lock, so running them
    sequentially in one background thread (rather than two separate
    threads) avoids either one skipping because the other is running.
    """

    def run_scan_async():
        buy_count = 0
        sell_count = 0
        failed = False

        try:
            logger.info("Starting manual opportunity scan (BUY)...")

            buy_result = execute_scan_pipeline()

            if isinstance(buy_result, dict):
                if buy_result.get("status") == "SCAN_ALREADY_IN_PROGRESS":
                    failed = True
                    _update_scan_status(
                        status="RUNNING",
                        error="Another scan is already running.",
                    )
                    logger.info(
                        "Manual BUY scan skipped: another scan is already running."
                    )
                else:
                    buy_count = len(buy_result.get("opportunities", []))
                    logger.info(
                        "Manual BUY scan completed: %d opportunities found.",
                        buy_count,
                    )

        except Exception as exc:
            failed = True
            _update_scan_status(status="FAILED", error=str(exc))
            logger.exception("BUY opportunity scan failed.")

        try:
            logger.info("Starting manual opportunity scan (SELL)...")

            sell_result = execute_sell_scan_pipeline()

            if isinstance(sell_result, dict):
                if sell_result.get("status") == "SCAN_ALREADY_IN_PROGRESS":
                    failed = True
                    logger.info(
                        "Manual SELL scan skipped: another scan is already running."
                    )
                else:
                    sell_count = len(sell_result.get("opportunities", []))
                    logger.info(
                        "Manual SELL scan completed: %d opportunities found.",
                        sell_count,
                    )

        except Exception as exc:
            failed = True
            _update_scan_status(status="FAILED", error=str(exc))
            logger.exception("SELL opportunity scan failed.")

        if failed:
            _update_scan_status(
                status="FAILED",
                completed_at=datetime.now(timezone.utc).isoformat(),
                buy_opportunities=buy_count,
                sell_opportunities=sell_count,
            )
        else:
            _update_scan_status(
                status="COMPLETED",
                completed_at=datetime.now(timezone.utc).isoformat(),
                buy_opportunities=buy_count,
                sell_opportunities=sell_count,
                error=None,
            )

    current = _current_scan_status()
    if current.get("status") == "RUNNING":
        return jsonify(current), 409

    _update_scan_status(
        status="RUNNING",
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=None,
        buy_opportunities=0,
        sell_opportunities=0,
        error=None,
    )

    thread = threading.Thread(
        target=run_scan_async,
        name="opportunity-scan",
        daemon=True,
    )

    thread.start()

    return jsonify({
        "status": "SCAN_STARTED"
    }), 202


@opportunities_bp.route("/scan/status", methods=["GET"])
@require_auth
def get_scan_status():
    return jsonify(_current_scan_status()), 200


# ─────────────────────────────────────────────────────────────────────────────
#  POST /api/opportunities/<analysis_id>/prepare
# ─────────────────────────────────────────────────────────────────────────────

@opportunities_bp.route("/<analysis_id>/prepare", methods=["POST"])
@require_auth
def prepare_trade(analysis_id):
    """
    Prepare a trade proposal for the authenticated user.

    IMPORTANT:
    - The frontend only supplies analysis_id.
    - The full investment analysis comes from the trusted backend cache
      (populated by EITHER the BUY scanner or the SELL scanner).
    - User preferences come from Firebase.
    - User portfolio comes from Firebase.
    - This function NEVER executes a trade.
    - For SELL entries, the requesting user must actually hold the symbol —
      the SELL scanner only notifies holders, but this route re-checks
      rather than trusting that implicitly.
    """

    # ── 1. Retrieve trusted backend analysis ────────────────────────────────

    entry = get_cached_entry(analysis_id)

    if not entry:
        return jsonify({
            "status": "NOT_FOUND",
            "error": "Analysis not found or expired",
        }), 404

    try:
        analysis = entry["analysis"]
        symbol = entry["symbol"]
        decision = entry["decision"]
        spot_price = entry.get("spot_price")
        kind = entry.get("kind", "BUY")

    except (KeyError, TypeError):
        logger.exception(
            "Malformed cached opportunity entry: %s",
            analysis_id,
        )

        return jsonify({
            "status": "ERROR",
            "error": "Cached analysis is malformed",
        }), 500

    if not isinstance(analysis, dict):
        return jsonify({
            "status": "ERROR",
            "error": "Cached investment analysis is invalid",
        }), 500

    # ── 2. Validate cached decision ────────────────────────────────────────

    if decision not in ("BUY", "SELL"):
        return jsonify({
            "status": "RECOMMEND_ONLY",
            "reason": (
                f"Committee decision is '{decision}' — "
                "no executable trade is required."
            ),
            "proposal": None,
            "analysis_id": analysis_id,
        }), 200

    # ── 3. Load authenticated user's context ───────────────────────────────

    user_id = g.uid

    preferences = _get_user_preferences(user_id)
    portfolio = get_portfolio_state(user_id)

    # ── 3b. SELL-specific ownership guard ───────────────────────────────────
    #
    # A SELL entry is only useful to a user who actually holds the symbol.
    # The SELL scanner already scopes notifications to holders, but this
    # route doesn't take that on faith — it re-checks against the user's
    # own live portfolio before ever building a proposal.

    if kind == "SELL" and not user_holds_symbol(portfolio, symbol):
        logger.info(
            "Blocked SELL prepare for %s: user %s does not hold %s",
            analysis_id,
            user_id,
            symbol,
        )

        return jsonify({
            "status": "RECOMMEND_ONLY",
            "reason": f"You don't currently hold {symbol} — nothing to sell.",
            "proposal": None,
            "analysis_id": analysis_id,
        }), 200

    logger.info(
        "Preparing opportunity %s for user %s | symbol=%s | decision=%s | kind=%s",
        analysis_id,
        user_id,
        symbol,
        decision,
        kind,
    )

    # ── 4. Build trade proposal ────────────────────────────────────────────
    #
    # This calls the EXISTING trade bridge.
    # It does NOT execute anything.

    try:
        trade_result = prepare_opportunity_for_user(
            user_id=user_id,
            opportunity_entry=entry,
        )

    except Exception:
        logger.exception(
            "Trade proposal preparation failed for %s",
            analysis_id,
        )

        return jsonify({
            "status": "ERROR",
            "error": "Failed to prepare trade proposal",
        }), 500

    # ── 5. Return proposal to frontend ─────────────────────────────────────
    #
    # The frontend can display this proposal.
    # Actual execution still requires the existing /confirm-trade endpoint.

    return jsonify({
        "analysis_id": analysis_id,
        "status": trade_result.get("status"),
        "reason": trade_result.get("reason"),
        "proposal": trade_result.get("proposal"),
        "action_mode": trade_result.get("action_mode"),
    }), 200

# ─────────────────────────────────────────────────────────────────────────────
#  GET /api/opportunities/confirmations
# ─────────────────────────────────────────────────────────────────────────────

@opportunities_bp.route("/confirmations", methods=["GET"])
@require_auth
def get_pending_trade_confirmations():
    result = list_active_confirmations(user_id=g.uid)
    http_status = result.pop("http_status", 200)
    return jsonify(result), http_status


# ─────────────────────────────────────────────────────────────────────────────
#  GET /api/opportunities/confirmations/<confirmation_id>
# ─────────────────────────────────────────────────────────────────────────────

@opportunities_bp.route("/confirmations/<confirmation_id>", methods=["GET"])
@require_auth
def get_trade_confirmation(confirmation_id):
    result = get_confirmation(
        user_id=g.uid,
        confirmation_id=confirmation_id,
    )

    http_status = result.pop("http_status", 200)
    return jsonify(result), http_status


# ─────────────────────────────────────────────────────────────────────────────
#  POST /api/opportunities/confirmations/<confirmation_id>/decision
# ─────────────────────────────────────────────────────────────────────────────

@opportunities_bp.route("/confirmations/<confirmation_id>/decision", methods=["POST"])
@require_auth
def decide_trade_confirmation(confirmation_id):
    payload = request.get_json(silent=True) or {}
    action = str(payload.get("decision", "")).upper().strip()

    if action not in ("CONFIRM", "REJECT"):
        return jsonify({
            "success": False,
            "status": "INVALID_REQUEST",
            "error": "decision must be CONFIRM or REJECT",
        }), 400

    if action == "REJECT":
        result = reject_confirmation(
            user_id=g.uid,
            confirmation_id=confirmation_id,
        )
    else:
        result = confirm_confirmation(
            user_id=g.uid,
            confirmation_id=confirmation_id,
            proposal_version=payload.get("proposal_version"),
            terms_hash=payload.get("terms_hash"),
        )

    http_status = result.pop("http_status", 200)
    return jsonify(result), http_status
