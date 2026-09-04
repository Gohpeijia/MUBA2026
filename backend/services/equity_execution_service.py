import logging
import os
from datetime import datetime
from typing import Any

from firebase_config import db
from finnhub_service import get_rich_market_quote
from Risk_sizing import calculate_position_size, check_risk_limits
from services.execution_router import PAPER_EQUITY
from services.portfolio_service import (
    adjust_paper_cash,
    get_paper_cash_balance,
    get_portfolio_state,
    normalize_symbol,
    sync_portfolio_summary,
)
from services.trade_proposal_serializer import serialize_trade_proposal
from services.trade_quantity import select_sell_quantity

logger = logging.getLogger(__name__)
DEFAULT_PAPER_PORTFOLIO_VALUE = float(os.getenv("PAPER_PORTFOLIO_VALUE_USD", "10000"))
MAX_CONFIRMATION_PRICE_DRIFT_PCT = float(os.getenv("EQUITY_PRICE_DRIFT_PCT", "0.03"))


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_positive_float(value: Any, field_name: str) -> tuple[float | None, str | None]:
    parsed = _to_float(value, -1.0)
    if parsed <= 0:
        return None, f"{field_name} must be a positive number."
    return parsed, None


def _parse_positive_int(value: Any, field_name: str) -> tuple[int | None, str | None]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None, f"{field_name} must be a positive integer."
    if parsed <= 0:
        return None, f"{field_name} must be greater than 0."
    return parsed, None


def _risk_tolerance(preferences: dict | None) -> str:
    prefs = preferences if isinstance(preferences, dict) else {}
    return prefs.get("riskTolerance") or prefs.get("risk_tolerance") or "Moderate"


def _portfolio_value_for_paper_trading(portfolio: dict) -> float:
    portfolio_value = _to_float((portfolio or {}).get("total_value"))
    if portfolio_value > 0:
        return portfolio_value
    return DEFAULT_PAPER_PORTFOLIO_VALUE


def _analysis_price(analysis: dict | None, spot_price: Any = None) -> float:
    data = analysis if isinstance(analysis, dict) else {}
    for value in (
        spot_price,
        data.get("current_price"),
        data.get("price"),
        data.get("last_price"),
        data.get("market_price"),
    ):
        parsed = _to_float(value)
        if parsed > 0:
            return parsed
    return 0.0


def _position_for_symbol(portfolio: dict, symbol: str) -> dict:
    positions = portfolio.get("positions", {}) if isinstance(portfolio, dict) else {}
    if not isinstance(positions, dict):
        return {}
    return positions.get(normalize_symbol(symbol), {}) if isinstance(positions.get(normalize_symbol(symbol)), dict) else {}


def _position_quantity(position: dict) -> float:
    if not isinstance(position, dict):
        return 0.0
    return _to_float(position.get("quantity", position.get("shares", position.get("qty", 0.0))))


def _position_market_value(position: dict, fallback_price: float) -> float:
    if not isinstance(position, dict):
        return 0.0
    quantity = _position_quantity(position)
    return _to_float(
        position.get("market_value", position.get("positionValue")),
        quantity * fallback_price,
    )


def _record_paper_trade(user_id: str, proposal: dict, action: str, shares: int, price: float) -> None:
    symbol = normalize_symbol(proposal.get("symbol") or proposal.get("ticker"))
    db.collection("users").document(user_id).collection("trades").add({
        "ticker": symbol,
        "symbol": symbol,
        "action": action.lower(),
        "assetType": "EQUITY",
        "executionTarget": PAPER_EQUITY,
        "quantity": shares,
        "price": price,
        "companyName": proposal.get("name") or symbol,
        "reason": proposal.get("reason") or "AI paper equity execution",
        "timestamp": datetime.now().isoformat(),
    })


def _find_legacy_holding(portfolio: list, symbol: str) -> dict | None:
    target = normalize_symbol(symbol)
    for item in portfolio:
        if not isinstance(item, dict):
            continue
        item_symbol = normalize_symbol(item.get("symbol") or item.get("ticker") or item.get("sticker"))
        if item_symbol == target:
            return item
    return None


def _risk_gate(user_id: str, symbol: str, shares: int, price: float, preferences: dict | None = None) -> tuple[bool, str, dict]:
    portfolio = get_portfolio_state(user_id)
    portfolio_value = _portfolio_value_for_paper_trading(portfolio)
    if portfolio_value <= 0:
        return False, "Portfolio value is zero or unknown.", {}

    position = _position_for_symbol(portfolio, symbol)
    existing_exposure = _position_market_value(position, price)
    sizing = calculate_position_size(
        portfolio_value=portfolio_value,
        entry_price=price,
        risk_tolerance=_risk_tolerance(preferences),
        existing_exposure_value=existing_exposure,
        open_ai_risk_value=_to_float(portfolio.get("open_ai_risk_value")),
        direction="BUY",
    )

    max_shares = int(sizing.get("recommended_shares") or 0)
    if shares > max_shares:
        return (
            False,
            f"Requested {shares} share(s), but risk sizing allows {max_shares}.",
            sizing,
        )

    proposal_for_gate = {
        **sizing,
        "recommended_shares": shares,
        "position_value": round(shares * price, 2),
        "position_pct_of_portfolio": round((shares * price / portfolio_value) * 100, 2),
        "passes_risk_limits": shares > 0,
    }
    ok, reason = check_risk_limits(
        portfolio_value=portfolio_value,
        proposal=proposal_for_gate,
    )
    return ok, reason, proposal_for_gate


def prepare_equity_proposal(
    *,
    user_id: str,
    symbol: str,
    decision: str,
    investment_analysis: dict | None,
    preferences: dict | None,
    portfolio: dict | None = None,
    spot_price: Any = None,
    requested_quantity: Any = None,
) -> dict:
    symbol = normalize_symbol(symbol)
    decision = str(decision or "").upper().strip()
    portfolio = portfolio if isinstance(portfolio, dict) else get_portfolio_state(user_id)
    price = _analysis_price(investment_analysis, spot_price)
    analysis = investment_analysis if isinstance(investment_analysis, dict) else {}

    if not symbol or decision not in ("BUY", "SELL"):
        return {"status": "RECOMMEND_ONLY", "reason": "No supported equity trade decision was found.", "proposal": None}

    if price <= 0:
        return {"status": "RECOMMEND_ONLY", "reason": f"No valid live price is available for {symbol}.", "proposal": None}

    if decision == "SELL":
        position = _position_for_symbol(portfolio, symbol)
        held_shares = int(_position_quantity(position))
        if held_shares <= 0:
            return {"status": "RECOMMEND_ONLY", "reason": f"You do not currently hold {symbol}.", "proposal": None}
        shares, quantity_source, quantity_error = select_sell_quantity(analysis, requested_quantity, held_shares)
        if quantity_error:
            return {"status": "RECOMMEND_ONLY", "reason": quantity_error, "proposal": None}
        risk = {}
    else:
        portfolio_value = _portfolio_value_for_paper_trading(portfolio)
        if portfolio_value <= 0:
            return {"status": "RECOMMEND_ONLY", "reason": "Portfolio value is unavailable, so no paper equity order was prepared.", "proposal": None}

        position = _position_for_symbol(portfolio, symbol)
        sizing = calculate_position_size(
            portfolio_value=portfolio_value,
            entry_price=price,
            risk_tolerance=_risk_tolerance(preferences),
            existing_exposure_value=_position_market_value(position, price),
            open_ai_risk_value=_to_float(portfolio.get("open_ai_risk_value")),
            direction="BUY",
        )
        shares = int(sizing.get("recommended_shares") or 0)
        if shares <= 0 or not sizing.get("passes_risk_limits"):
            return {"status": "RECOMMEND_ONLY", "reason": "; ".join(sizing.get("notes", [])) or "Risk limits leave no room for this paper equity trade.", "proposal": None}
        risk = sizing

    proposal = {
        "execution_target": PAPER_EQUITY,
        "asset_type": "EQUITY",
        "symbol": symbol,
        "ticker": symbol,
        "action": decision,
        "decision": decision,
        "name": analysis.get("company_name") or analysis.get("name") or symbol,
        "price": price,
        "shares": shares,
        "quantity": shares,
        "quantity_source": quantity_source if decision == "SELL" else "AI_RECOMMENDED",
        "estimated_value": round(shares * price, 2),
        "confidence_pct": int((_to_float(analysis.get("confidence")) or 0.0) * 100),
        "risk_level": analysis.get("risk_level", "MEDIUM"),
        "risk_tolerance": _risk_tolerance(preferences),
        "risk_sizing": risk,
        "reason": analysis.get("summary") or analysis.get("rationale") or "AI paper equity recommendation",
    }

    return {
        "status": "EXECUTABLE",
        "reason": "Paper equity proposal generated.",
        "proposal": serialize_trade_proposal(proposal, execution_target=PAPER_EQUITY),
        "action_mode": (preferences or {}).get("riskCopilotMode"),
    }


def execute_equity_buy(user_id: str, proposal: dict, *, action: str = "CONFIRM") -> dict:
    symbol = normalize_symbol(proposal.get("symbol") or proposal.get("ticker"))
    shares, shares_error = _parse_positive_int(proposal.get("shares", proposal.get("quantity")), "shares")
    price, price_error = _parse_positive_float(proposal.get("price"), "price")

    if not symbol:
        return {"ok": False, "status": "FAILED", "error": "Paper equity BUY requires symbol."}
    if shares_error:
        return {"ok": False, "status": "FAILED", "error": shares_error}
    if price_error:
        return {"ok": False, "status": "FAILED", "error": price_error}

    user_ref = db.collection("users").document(user_id)
    user_doc = user_ref.get()
    if not user_doc.exists:
        return {"ok": False, "status": "FAILED", "error": "User not found."}

    user_data = user_doc.to_dict() or {}
    preferences = user_data.get("preference", {})
    ok, reason, risk = _risk_gate(user_id, symbol, shares, price, preferences)
    if not ok:
        return {"ok": False, "status": "FAILED", "error": f"Trade rejected by risk management: {reason}", "risk_sizing": risk}

    estimated_value = round(shares * price, 2)
    paper_cash = get_paper_cash_balance(user_id)
    if estimated_value > paper_cash:
        return {
            "ok": False,
            "status": "FAILED",
            "error": f"Insufficient paper cash. Need ${estimated_value:.2f}, available ${paper_cash:.2f}.",
            "paper_cash_usd": paper_cash,
        }

    portfolio = user_data.get("portfolio", [])
    if not isinstance(portfolio, list):
        portfolio = []

    holding = _find_legacy_holding(portfolio, symbol)
    if holding:
        old_shares = _to_float(holding.get("shares", holding.get("quantity", 0.0)))
        old_cost = _to_float(holding.get("averageCost", holding.get("average_cost", price)), price)
        new_shares = old_shares + shares
        average_cost = ((old_shares * old_cost) + (shares * price)) / new_shares if new_shares > 0 else price
        holding.update({
            "symbol": symbol,
            "ticker": symbol,
            "sticker": symbol,
            "shares": new_shares,
            "quantity": new_shares,
            "averageCost": round(average_cost, 4),
            "average_cost": round(average_cost, 4),
            "name": proposal.get("name") or holding.get("name") or symbol,
        })
    else:
        portfolio.append({
            "symbol": symbol,
            "ticker": symbol,
            "sticker": symbol,
            "name": proposal.get("name") or symbol,
            "shares": shares,
            "quantity": shares,
            "averageCost": price,
            "average_cost": price,
            "assetType": "EQUITY",
            "asset_type": "EQUITY",
            "watchlist": False,
        })

    user_ref.update({"portfolio": portfolio})
    paper_cash = adjust_paper_cash(user_id, -estimated_value)
    _record_paper_trade(user_id, proposal, "buy", shares, price)
    sync_portfolio_summary(user_id)

    return {
        "ok": True,
        "status": "PAPER_EXECUTED",
        "execution_target": PAPER_EQUITY,
        "decision": "BUY",
        "symbol": symbol,
        "shares": shares,
        "price": price,
        "estimated_value": estimated_value,
        "paper_cash_usd": paper_cash,
        "dry_run": True,
        "message": "Paper equity BUY recorded. No broker or blockchain transaction was sent.",
    }


def execute_equity_sell(user_id: str, proposal: dict, *, action: str = "CONFIRM") -> dict:
    symbol = normalize_symbol(proposal.get("symbol") or proposal.get("ticker"))
    shares, shares_error = _parse_positive_int(proposal.get("shares", proposal.get("quantity")), "shares")
    price, price_error = _parse_positive_float(proposal.get("price"), "price")

    if not symbol:
        return {"ok": False, "status": "FAILED", "error": "Paper equity SELL requires symbol."}
    if shares_error:
        return {"ok": False, "status": "FAILED", "error": shares_error}
    if price_error:
        return {"ok": False, "status": "FAILED", "error": price_error}

    user_ref = db.collection("users").document(user_id)
    user_doc = user_ref.get()
    if not user_doc.exists:
        return {"ok": False, "status": "FAILED", "error": "User not found."}

    user_data = user_doc.to_dict() or {}
    portfolio = user_data.get("portfolio", [])
    if not isinstance(portfolio, list):
        portfolio = []

    holding = _find_legacy_holding(portfolio, symbol)
    held_shares = _to_float(holding.get("shares", holding.get("quantity", 0.0))) if holding else 0.0
    if not holding or held_shares <= 0:
        return {"ok": False, "status": "FAILED", "error": f"You do not hold any {symbol} to sell."}
    if shares > held_shares:
        return {"ok": False, "status": "FAILED", "error": f"You only hold {held_shares:g} share(s) of {symbol}."}

    quote = get_rich_market_quote(symbol)
    current_price = _to_float((quote or {}).get("price"))
    if current_price <= 0:
        return {"ok": False, "status": "FAILED", "error": f"A current market price for {symbol} is unavailable."}

    drift = abs(current_price - price) / price if price else 0.0
    if action == "CONFIRMATION_LINK" and drift > MAX_CONFIRMATION_PRICE_DRIFT_PCT:
        return {
            "ok": False,
            "status": "NEEDS_RECONFIRMATION",
            "reason": f"{symbol} moved {drift * 100:.2f}% since the preview. Review the updated sell price.",
            "previous": {"price": price, "shares": shares, "quantity": shares},
            "current": {
                "price": current_price,
                "shares": shares,
                "quantity": shares,
                "estimated_value": round(shares * current_price, 2),
            },
        }

    # Automated orders use the latest quote. Confirmed orders use it once it
    # remains within the accepted tolerance (or after reconfirmation).
    price = current_price

    remaining = held_shares - shares
    if remaining <= 0:
        portfolio = [item for item in portfolio if _find_legacy_holding([item], symbol) is None]
    else:
        holding.update({
            "symbol": symbol,
            "ticker": symbol,
            "sticker": symbol,
            "shares": remaining,
            "quantity": remaining,
        })

    estimated_value = round(shares * price, 2)

    user_ref.update({"portfolio": portfolio})
    paper_cash = adjust_paper_cash(user_id, estimated_value)
    _record_paper_trade(user_id, proposal, "sell", shares, price)
    sync_portfolio_summary(user_id)

    return {
        "ok": True,
        "status": "PAPER_EXECUTED",
        "execution_target": PAPER_EQUITY,
        "decision": "SELL",
        "symbol": symbol,
        "shares": shares,
        "price": price,
        "estimated_value": estimated_value,
        "paper_cash_usd": paper_cash,
        "dry_run": True,
        "message": "Paper equity SELL recorded. No broker or blockchain transaction was sent.",
    }


def execute_equity_proposal(user_id: str, proposal: dict, *, action: str = "CONFIRM") -> dict:
    decision = str(proposal.get("decision") or proposal.get("action") or "").upper().strip()
    if decision == "BUY":
        return execute_equity_buy(user_id, proposal, action=action)
    if decision == "SELL":
        return execute_equity_sell(user_id, proposal, action=action)
    return {"ok": False, "status": "FAILED", "error": f"Unsupported paper equity decision: {decision or 'missing'}."}
