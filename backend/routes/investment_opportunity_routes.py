"""API routes for automated investment opportunities and trade preparation.

Discovery is strictly separated from trade execution.

Flow:
    scanner
        ↓
    backend cached analysis
        ↓
    authenticated user
        ↓
    /prepare
        ↓
    user's preferences + portfolio
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

from flask import Blueprint, jsonify, request, g

from investment.opportunity_engine import (
    execute_scan_pipeline,
    get_latest_opportunities,
    get_cached_entry,
)

from advisor.trade_bridge import build_trade_proposal

from ai_agent import trader
from firebase_config import db
from security import require_auth

logger = logging.getLogger(__name__)

opportunities_bp = Blueprint(
    "opportunities",
    __name__,
    url_prefix="/api/opportunities",
)




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


# ─────────────────────────────────────────────────────────────────────────────
#  GET /api/opportunities
# ─────────────────────────────────────────────────────────────────────────────

@opportunities_bp.route("", methods=["GET"])
def get_opportunities():
    """
    Return the latest globally discovered opportunities.

    Discovery itself is not user-specific.
    User-specific risk/portfolio information is applied later by /prepare.
    """
    try:
        opportunities = get_latest_opportunities()

        return jsonify(opportunities), 200

    except Exception:
        logger.exception("Failed to retrieve opportunities")

        return jsonify({
            "status": "ERROR",
            "error": "Failed to retrieve opportunities",
        }), 500


# ─────────────────────────────────────────────────────────────────────────────
#  POST /api/opportunities/scan
# ─────────────────────────────────────────────────────────────────────────────

@opportunities_bp.route("/scan", methods=["POST"])
def trigger_scan():
    """
    Start a manual discovery scan asynchronously.

    This endpoint ONLY discovers opportunities.
    It never prepares or executes a trade.

    The shared scan lock is owned by opportunity_engine.py,
    so manual and scheduled scans cannot overlap.
    """

    def run_scan_async():
        try:
            logger.info("Starting manual opportunity scan...")

            result = execute_scan_pipeline()

            if not isinstance(result, dict):
                logger.info(
                    "Manual opportunity scan completed."
                )
                return

            if result.get("status") == "SCAN_ALREADY_IN_PROGRESS":
                logger.info(
                    "Manual opportunity scan skipped: "
                    "another scan is already running."
                )
                return

            opportunities = result.get(
                "opportunities",
                [],
            )

            logger.info(
                "Manual opportunity scan completed: "
                "%d opportunities found.",
                len(opportunities),
            )

        except Exception:
            logger.exception(
                "Opportunity scan failed."
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
    - The full investment analysis comes from the trusted backend cache.
    - User preferences come from Firebase.
    - User portfolio comes from Firebase.
    - This function NEVER executes a trade.
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
    portfolio = _get_user_portfolio(user_id)

    logger.info(
        "Preparing opportunity %s for user %s | symbol=%s | decision=%s",
        analysis_id,
        user_id,
        symbol,
        decision,
    )

    # ── 4. Build trade proposal ────────────────────────────────────────────
    #
    # This calls the EXISTING trade bridge.
    # It does NOT execute anything.

    try:
        trade_result = build_trade_proposal(
            symbol=symbol,
            decision=decision,
            investment_analysis=analysis,
            preferences=preferences,
            portfolio=portfolio,
            trader=trader,
            spot_price=spot_price,
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