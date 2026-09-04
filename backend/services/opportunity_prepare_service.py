import logging

from advisor.trade_bridge import build_trade_proposal
from ai_agent import trader
from firebase_config import db
from investment.opportunity_engine import get_cached_entry
from services.equity_execution_service import prepare_equity_proposal
from services.execution_router import PAPER_EQUITY, THETANUTS_OPTION, UNSUPPORTED, resolve_execution_target
from services.portfolio_service import get_portfolio_state, user_holds_symbol
from services.trade_proposal_serializer import serialize_trade_proposal

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
        "symbol": opportunity_entry.get("symbol") or analysis.get("symbol") or analysis.get("ticker"),
        "asset_type": opportunity_entry.get("asset_type") or analysis.get("asset_type"),
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
    symbol = entry.get("symbol") or analysis.get("symbol") or analysis.get("ticker")
    decision = str(entry.get("decision") or "").upper()
    spot_price = entry.get("spot_price") or analysis.get("current_price")
    kind = str(entry.get("kind") or decision or "BUY").upper()
    analysis_id = entry.get("analysis_id") or analysis.get("analysis_id")
    asset_type = entry.get("asset_type") or analysis.get("asset_type")

    if decision not in ("BUY", "SELL"):
        return {
            "analysis_id": analysis_id,
            "status": "RECOMMEND_ONLY",
            "reason": f"Committee decision is '{decision or 'UNKNOWN'}' - no executable trade is required.",
            "proposal": None,
        }

    preferences = get_user_preferences(user_id)
    portfolio = get_portfolio_state(user_id)
    route = resolve_execution_target(symbol, asset_type)
    execution_target = route.get("execution_target")

    if execution_target == UNSUPPORTED:
        return {
            "analysis_id": analysis_id,
            "status": "RECOMMEND_ONLY",
            "reason": route.get("reason") or "No execution engine is configured for this asset.",
            "proposal": None,
            "analysis_snapshot": analysis,
            "spot_price": spot_price,
            "kind": kind,
            "confidence": entry.get("confidence") or analysis.get("confidence"),
            "risk_level": analysis.get("risk_level", entry.get("risk_level", "UNKNOWN")),
            "execution_target": execution_target,
        }

    if kind == "SELL" and execution_target == PAPER_EQUITY and not user_holds_symbol(portfolio, route.get("symbol") or symbol):
        return {
            "analysis_id": analysis_id,
            "status": "RECOMMEND_ONLY",
            "reason": f"You don't currently hold {symbol} - nothing to sell.",
            "proposal": None,
        }

    try:
        if execution_target == PAPER_EQUITY:
            trade_result = prepare_equity_proposal(
                user_id=user_id,
                symbol=route.get("symbol") or symbol,
                decision=decision,
                investment_analysis=analysis,
                preferences=preferences,
                portfolio=portfolio,
                spot_price=spot_price,
            )
        elif execution_target == THETANUTS_OPTION:
            trade_result = build_trade_proposal(
                symbol=route.get("underlying") or symbol,
                decision=decision,
                investment_analysis=analysis,
                preferences=preferences,
                portfolio=portfolio,
                trader=trader,
                spot_price=spot_price,
            )
            if isinstance(trade_result.get("proposal"), dict):
                trade_result["proposal"] = serialize_trade_proposal(
                    {
                        **trade_result["proposal"],
                        "execution_target": THETANUTS_OPTION,
                        "source_symbol": symbol,
                    },
                    execution_target=THETANUTS_OPTION,
                )
        else:
            trade_result = {
                "status": "RECOMMEND_ONLY",
                "reason": "No execution engine is configured for this asset.",
                "proposal": None,
            }
    except Exception as exc:
        logger.exception("Failed to prepare opportunity %s for user %s", analysis_id, user_id)
        return {
            "analysis_id": analysis_id,
            "status": "ERROR",
            "error": str(exc) or "Failed to prepare trade proposal.",
            "proposal": None,
        }

    proposal = serialize_trade_proposal(
        trade_result.get("proposal"),
        execution_target=execution_target if trade_result.get("proposal") else None,
    )

    return {
        "analysis_id": analysis_id,
        "status": trade_result.get("status"),
        "reason": trade_result.get("reason"),
        "proposal": proposal,
        "action_mode": trade_result.get("action_mode"),
        "analysis_snapshot": analysis,
        "spot_price": spot_price,
        "kind": kind,
        "confidence": entry.get("confidence") or analysis.get("confidence"),
        "risk_level": analysis.get("risk_level", entry.get("risk_level", "UNKNOWN")),
        "execution_target": execution_target,
    }
