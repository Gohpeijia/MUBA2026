import logging
import os
from datetime import datetime, timezone
from typing import Any

from firebase_admin import firestore
from firebase_config import db

logger = logging.getLogger(__name__)
DEFAULT_PAPER_CASH_USD = float(os.getenv("PAPER_CASH_USD", "10000"))
PAPER_CASH_VERSION = 1


EMPTY_PORTFOLIO_STATE = {
    "total_value": 0.0,
    "positions": {},
    "open_ai_risk_value": 0.0,
}


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _position_symbol(item: dict) -> str:
    return normalize_symbol(
        item.get("symbol")
        or item.get("ticker")
        or item.get("sticker")
        or item.get("underlying")
    )


def _position_quantity(item: Any) -> float:
    if isinstance(item, dict):
        return _to_float(
            item.get("quantity", item.get("shares", item.get("qty", 0.0)))
        )
    return _to_float(item)


def _normalize_positions(positions: Any) -> dict:
    normalized = {}
    if not isinstance(positions, dict):
        return normalized

    for raw_symbol, raw_position in positions.items():
        symbol = normalize_symbol(raw_symbol)
        if not symbol:
            continue

        if isinstance(raw_position, dict):
            position = dict(raw_position)
            quantity = _position_quantity(position)
        else:
            position = {}
            quantity = _to_float(raw_position)

        if quantity <= 0:
            continue

        average_cost = _to_float(
            position.get(
                "average_cost",
                position.get("averageCost", position.get("avgCost", 0.0)),
            )
        )
        current_price = _to_float(
            position.get("current_price", position.get("currentPrice", average_cost)),
            average_cost,
        )
        market_value = _to_float(
            position.get("market_value", position.get("positionValue", 0.0)),
            quantity * current_price,
        )

        normalized[symbol] = {
            **position,
            "symbol": symbol,
            "ticker": position.get("ticker") or symbol,
            "sticker": position.get("sticker") or symbol,
            "quantity": quantity,
            "shares": quantity,
            "average_cost": average_cost,
            "averageCost": average_cost,
            "current_price": current_price,
            "market_value": market_value,
            "asset_type": position.get("asset_type") or position.get("assetType") or "EQUITY",
        }

    return normalized


def _positions_from_legacy_portfolio(portfolio: Any) -> dict:
    positions = {}
    if not isinstance(portfolio, list):
        return positions

    for item in portfolio:
        if not isinstance(item, dict):
            continue

        symbol = _position_symbol(item)
        quantity = _position_quantity(item)
        if not symbol or quantity <= 0:
            continue

        average_cost = _to_float(
            item.get("average_cost", item.get("averageCost", item.get("price", 0.0)))
        )
        current_price = _to_float(
            item.get("current_price", item.get("currentPrice", average_cost)),
            average_cost,
        )
        market_value = _to_float(
            item.get("market_value", item.get("positionValue", 0.0)),
            quantity * current_price,
        )

        positions[symbol] = {
            "symbol": symbol,
            "ticker": symbol,
            "sticker": symbol,
            "name": item.get("name") or item.get("companyName") or symbol,
            "quantity": quantity,
            "shares": quantity,
            "average_cost": average_cost,
            "averageCost": average_cost,
            "current_price": current_price,
            "market_value": market_value,
            "asset_type": item.get("asset_type") or item.get("assetType") or "EQUITY",
        }

    return positions


def _summary_from_user_data(user_data: dict) -> dict:
    positions = _positions_from_legacy_portfolio(user_data.get("portfolio", []))
    calculated_total = sum(
        _to_float(position.get("market_value")) for position in positions.values()
    )
    total_value = calculated_total

    return {
        "total_value": total_value,
        "positions": positions,
        "open_ai_risk_value": _to_float(user_data.get("open_ai_risk_value", 0.0)),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def normalize_portfolio_state(data: dict | None) -> dict:
    if not isinstance(data, dict):
        return dict(EMPTY_PORTFOLIO_STATE)

    positions = _normalize_positions(data.get("positions", {}))
    total_value = _to_float(
        data.get("total_value", data.get("totalPortfolioValue")),
        sum(_to_float(position.get("market_value")) for position in positions.values()),
    )

    return {
        "total_value": total_value,
        "positions": positions,
        "open_ai_risk_value": _to_float(data.get("open_ai_risk_value", 0.0)),
        "updated_at": data.get("updated_at"),
    }


def sync_portfolio_summary(user_id: str, user_data: dict | None = None) -> dict:
    state = dict(EMPTY_PORTFOLIO_STATE)
    try:
        user_ref = db.collection("users").document(user_id)
        if user_data is None:
            snap = user_ref.get()
            user_data = snap.to_dict() if snap.exists else {}

        state = _summary_from_user_data(user_data or {})
        user_ref.collection("portfolio").document("summary").set(state, merge=True)
    except Exception:
        logger.exception("Failed to sync portfolio summary for user %s", user_id)
    return state


def get_portfolio_state(user_id: str, *, writeback_if_missing: bool = True) -> dict:
    try:
        user_ref = db.collection("users").document(user_id)
        summary_ref = user_ref.collection("portfolio").document("summary")
        summary_doc = summary_ref.get()
        if summary_doc.exists:
            return normalize_portfolio_state(summary_doc.to_dict() or {})

        if writeback_if_missing:
            return sync_portfolio_summary(user_id)
    except Exception:
        logger.exception("Failed to load portfolio summary for user %s", user_id)

    return dict(EMPTY_PORTFOLIO_STATE)


def get_positions(user_id: str) -> dict:
    return get_portfolio_state(user_id).get("positions", {})


def get_total_portfolio_value(user_id: str) -> float:
    return _to_float(get_portfolio_state(user_id).get("total_value"))


def _paper_cash_from_trades(user_id: str) -> float:
    cash = DEFAULT_PAPER_CASH_USD
    try:
        trades = db.collection("users").document(user_id).collection("trades").stream()
        for trade in trades:
            data = trade.to_dict() or {}
            asset_type = str(data.get("assetType") or data.get("asset_type") or "EQUITY").upper()
            if asset_type != "EQUITY":
                continue

            quantity = _to_float(data.get("quantity"))
            price = _to_float(data.get("price"))
            value = quantity * price
            action = str(data.get("action") or "").lower()

            if action == "buy":
                cash -= value
            elif action == "sell":
                cash += value
    except Exception:
        logger.exception("Failed to derive paper cash from trades for user %s", user_id)
        raise

    return round(cash, 2)


def get_paper_cash_balance(user_id: str) -> float:
    user_ref = db.collection("users").document(user_id)
    snap = user_ref.get()
    data = snap.to_dict() if snap.exists else {}

    logger.info(
        "PAPER CASH DEBUG user=%s paperCashUsd=%s version=%s",
        user_id,
        data.get("paperCashUsd"),
        data.get("paperCashVersion"),
    )

    if (
        isinstance(data, dict)
        and data.get("paperCashUsd") is not None
        and data.get("paperCashVersion") == PAPER_CASH_VERSION
    ):
        return round(_to_float(data.get("paperCashUsd"), DEFAULT_PAPER_CASH_USD), 2)

    cash = _paper_cash_from_trades(user_id)
    @firestore.transactional
    def initialize(transaction):
        current = user_ref.get(transaction=transaction).to_dict() or {}
        if current.get("paperCashVersion") == PAPER_CASH_VERSION and current.get("paperCashUsd") is not None:
            return float(current["paperCashUsd"])
        transaction.set(user_ref, {
            "paperCashUsd": cash, "paperCashVersion": PAPER_CASH_VERSION,
        }, merge=True)
        return cash
    return initialize(db.transaction())


def adjust_paper_cash(user_id: str, delta: float) -> float:
    user_ref = db.collection("users").document(user_id)

    current_cash = get_paper_cash_balance(user_id)
    new_cash = round(current_cash + delta, 2)

    if new_cash < 0:
        raise ValueError(
            f"Paper cash cannot become negative. "
            f"Current={current_cash:.2f}, delta={delta:.2f}"
        )

    user_ref.update({
        "paperCashUsd": new_cash,
        "paperCashVersion": PAPER_CASH_VERSION,
    })

    return new_cash

def reset_paper_cash(user_id: str) -> float:
    """Reset the user's paper equity cash to the default starting balance."""
    user_ref = db.collection("users").document(user_id)

    reset_amount = round(DEFAULT_PAPER_CASH_USD, 2)

    user_ref.set({
        "paperCashUsd": reset_amount,
        "paperCashVersion": PAPER_CASH_VERSION,
    }, merge=True)

    logger.info(
        "PAPER CASH RESET user=%s cash=%.2f",
        user_id,
        reset_amount,
    )

    return reset_amount

def user_holds_symbol(portfolio: dict, symbol: str) -> bool:
    target = normalize_symbol(symbol)
    if not target:
        return False

    positions = portfolio.get("positions", {}) if isinstance(portfolio, dict) else {}
    if not isinstance(positions, dict):
        return False

    for position_symbol, position in positions.items():
        if normalize_symbol(position_symbol) != target:
            continue
        return _position_quantity(position) > 0

    return False

