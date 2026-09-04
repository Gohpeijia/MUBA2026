import logging

from advisor.trade_bridge import build_trade_proposal
from ai_agent import trader
from firebase_config import db
from investment.opportunity_engine import get_cached_entry

logger = logging.getLogger(__name__)


def get_user_preferences(user_id: str) -> dict:
    try:
        doc = db.collection("users").document(user_id).get()
        if not doc.exists:
            return {}
        data = doc.to_dict() or {}
        prefs = data.get("preference", {})
        return prefs if isinstance(prefs, dict) else {}
    except Exception:
        logger.exception("Failed to load preferences for user %s", user_id)
        return {}


def get_user_portfolio(user_id: str) -> dict:
    fallback = {
        "total_value": 0.0,
        "positions": {},
        "open_ai_risk_value": 0.0,
    }
    try:
        doc = (
            db.collection("users")
            .document(user_id)
            .collection("portfolio")
            .document("summary")
            .get()
        )
        if doc.exists:
            data = doc.to_dict() or {}
            return data if isinstance(data, dict) else fallback
    except Exception:
        logger.exception("Failed to load portfolio for user %s", user_id)
    return fallback


def user_holds_symbol(portfolio: dict, symbol: str) -> bool:
    positions = portfolio.get("positions", {}) if isinstance(portfolio, dict) else {}
    if not isinstance(positions, dict):
        return False

    target = str(symbol or "").strip().upper()
    if not target:
        return False

    for position_symbol, position in positions.items():
        if str(position_symbol).strip().upper() != target:
            continue
        if isinstance(position, dict):
            qty = position.get("quantity", position.get("qty"))
        else:
            qty = position
        try:
            return float(qty) > 0
        except (TypeError, ValueError):
            return False
    return False


def normalize_opportunity_entry(opportunity_entry: dict) -> dict | None:
    if not isinstance(opportunity_entry, dict):
        return None

    if "analysis" in opportunity_entry:
        return opportunity_entry

    analysis_id = opportunity_entry.get("analysis_id")
    cached = get_cached_entry(analysis_id) if analysis_id else None
    if cached:
        enriched = dict(cached)
        enriched.setdefault("analysis_id", analysis_id)
        enriched.setdefault("kind", opportunity_entry.get("kind", "BUY"))
        return enriched

    analysis = opportunity_entry.get("analysis") or opportunity_entry.get("analysis_snapshot") or {}
    if not isinstance(analysis, dict):
        analysis = {}

    return {
        "analysis": analysis,
        "symbol": opportunity_entry.get("symbol"),
        "decision": opportunity_entry.get("decision"),
        "confidence": opportunity_entry.get("confidence"),
        "spot_price": opportunity_entry.get("spot_price") or analysis.get("current_price"),
        "kind": opportunity_entry.get("kind", opportunity_entry.get("decision", "BUY")),
        "holder_user_ids": opportunity_entry.get("holder_user_ids", []),
        "analysis_id": analysis_id,
    }


def prepare_opportunity_for_user(*, user_id: str, opportunity_entry: dict) -> dict:
    entry = normalize_opportunity_entry(opportunity_entry)
    if not entry:
        return {
            "status": "ERROR",
            "error": "Opportunity entry is invalid.",
            "proposal": None,
        }

    analysis = entry.get("analysis") or {}
    symbol = entry.get("symbol")
    decision = str(entry.get("decision") or "").upper()
    spot_price = entry.get("spot_price")
    kind = str(entry.get("kind") or decision or "BUY").upper()
    analysis_id = entry.get("analysis_id") or analysis.get("analysis_id")

    if decision not in ("BUY", "SELL"):
        return {
            "analysis_id": analysis_id,
            "status": "RECOMMEND_ONLY",
            "reason": f"Committee decision is '{decision or 'UNKNOWN'}' - no executable trade is required.",
            "proposal": None,
        }

    preferences = get_user_preferences(user_id)
    portfolio = get_user_portfolio(user_id)

    if kind == "SELL" and not user_holds_symbol(portfolio, symbol):
        return {
            "analysis_id": analysis_id,
            "status": "RECOMMEND_ONLY",
            "reason": f"You don't currently hold {symbol} - nothing to sell.",
            "proposal": None,
        }

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
    except Exception as exc:
        logger.exception("Failed to prepare opportunity %s for user %s", analysis_id, user_id)
        return {
            "analysis_id": analysis_id,
            "status": "ERROR",
            "error": str(exc) or "Failed to prepare trade proposal.",
            "proposal": None,
        }

    return {
        "analysis_id": analysis_id,
        "status": trade_result.get("status"),
        "reason": trade_result.get("reason"),
        "proposal": trade_result.get("proposal"),
        "action_mode": trade_result.get("action_mode"),
        "analysis_snapshot": analysis,
        "spot_price": spot_price,
        "kind": kind,
        "confidence": entry.get("confidence") or analysis.get("confidence"),
        "risk_level": analysis.get("risk_level", entry.get("risk_level", "UNKNOWN")),
    }