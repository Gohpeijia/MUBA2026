import logging
from datetime import datetime, timezone
from typing import Any

from firebase_config import db

logger = logging.getLogger(__name__)


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
    total_value = _to_float(
        user_data.get("total_value", user_data.get("totalPortfolioValue")),
        calculated_total,
    )

    if total_value <= 0 and calculated_total > 0:
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
