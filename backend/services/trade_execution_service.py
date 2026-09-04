import logging
from datetime import datetime

from ai_agent import trader, _log_thetanuts_trade, FORCE_DRY_RUN
from firebase_config import db
from trading.validator import validate_confirmation, MAX_PRICE_DRIFT_PCT

logger = logging.getLogger(__name__)


def _record_trade_for_dashboard(
    user_id: str,
    *,
    ticker: str,
    action: str,
    option_type: str = None,
    strike=None,
    expiry=None,
    collateral_usdc: float = None,
    proceeds_usdc: float = None,
    fill_price=None,
    reason: str = "",
) -> None:
    """
    Mirrors a completed options fill into users/{uid}/trades — the same
    Firestore subcollection portfolio_routes.py's _record_trade() writes
    to for equity buy/sell — so it shows up in InvestmentDashboard.jsx's
    "Trade History" card, sorted by date, alongside share trades.

    Tagged with assetType: "OPTION" so the frontend can keep options out
    of the equity average-cost-basis math (quantity/price mean something
    different here — see InvestmentDashboard.jsx's computeHoldings).

    Never raises — a logging failure must never break a live trade
    execution that already succeeded on-chain.
    """
    if not user_id:
        return
    try:
        db.collection("users").document(user_id).collection("trades").add({
            "ticker": ticker,
            "action": (action or "").lower(),   # 'buy' | 'sell'
            "assetType": "OPTION",
            "asset_type": "OPTION",
            "currency": "USDC",
            "optionType": option_type,
            "strike": strike,
            "expiry": expiry,
            # quantity/price kept for display parity with equity rows;
            # collateral_usdc is the actual dollar figure that moved.
            "quantity": 1,
            "price": collateral_usdc,
            "collateralUsdc": collateral_usdc,
            "proceedsUsdc": proceeds_usdc,
            "fillPrice": fill_price,
            "companyName": ticker,
            "reason": reason or "AI Thetanuts execution",
            "timestamp": datetime.now().isoformat(),
        })
    except Exception:
        logger.exception("Failed to record dashboard trade entry for user %s / %s", user_id, ticker)


def order_field(order: dict, *names):
    for name in names:
        value = (order or {}).get(name)
        if value is not None:
            return value
    return None


def parse_positive_float(value, field_name: str):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None, f"{field_name} must be a positive number."
    if parsed <= 0:
        return None, f"{field_name} must be greater than 0."
    return parsed, None


def same_contract(order: dict, option_type, strike, expiry) -> bool:
    order_type = order_field(order, "option_type", "optionType", "type")
    order_strike = order_field(order, "strike", "strikePrice", "strike_price")
    order_expiry = order_field(order, "expiry", "expiryTimestamp", "expiration", "expirationTimestamp")
    try:
        normalized_expiry = trader._normalize_expiry(order_expiry)
        expected_normalized_expiry = trader._normalize_expiry(expiry)
        same_strike = abs(float(order_strike) - float(strike)) <= 1e-8
    except (TypeError, ValueError):
        return False
    return (
        str(order_type).strip().upper() == str(option_type).strip().upper()
        and same_strike
        and normalized_expiry == expected_normalized_expiry
    )


def selector_from_current_order(ticker, order: dict) -> dict:
    return {
        "underlying": ticker,
        "option_type": order_field(order, "option_type", "optionType", "type"),
        "strike": order_field(order, "strike", "strikePrice", "strike_price"),
        "expiry": order_field(order, "expiry", "expiryTimestamp", "expiration", "expirationTimestamp"),
        "previewed_price": order_field(order, "price_per_contract", "price", "premium", "unitPrice"),
    }


def _price_drift_exceeded(previewed_price, current_price) -> bool:
    if not previewed_price or not current_price:
        return False
    try:
        return abs(float(current_price) - float(previewed_price)) / float(previewed_price) > MAX_PRICE_DRIFT_PCT
    except (TypeError, ValueError, ZeroDivisionError):
        return False


def execute_confirmed_buy(proposal: dict, *, action: str = "CONFIRM", user_id: str = None) -> dict:
    selector = (proposal or {}).get("selector") or {}
    ticker = selector.get("underlying") or proposal.get("underlying")
    option_type = selector.get("option_type") or proposal.get("option_type")
    strike = selector.get("strike") or proposal.get("strike")
    expiry = selector.get("expiry") or proposal.get("expiry")

    if not ticker or not option_type or strike is None or expiry is None:
        return {"ok": False, "status": "FAILED", "error": "Incomplete stable contract selector."}

    collateral_usdc = selector.get("collateral_usdc")
    if collateral_usdc is None:
        collateral_usdc = proposal.get("collateral_usdc")
    collateral_usdc, collateral_error = parse_positive_float(collateral_usdc, "collateral_usdc")
    if collateral_error:
        return {"ok": False, "status": "FAILED", "error": collateral_error}

    orders = trader.get_live_orders(underlying=ticker, option_type=option_type)
    if not orders.get("ok") or not orders.get("data"):
        return {"ok": False, "status": "STALE", "error": orders.get("error") or "No live orders available."}

    current_order = next((o for o in orders.get("data", []) if isinstance(o, dict) and same_contract(o, option_type, strike, expiry)), None)
    if current_order is None:
        replacement = selector_from_current_order(ticker, orders["data"][0])
        replacement.update({"decision": "BUY", "collateral_usdc": collateral_usdc})
        return {
            "ok": False,
            "status": "NEEDS_RECONFIRMATION",
            "reason": "The original order is no longer available. Review the current order before execution.",
            "previous": selector,
            "current": replacement,
        }

    current_price = order_field(current_order, "price_per_contract", "price", "premium", "unitPrice")
    if _price_drift_exceeded(selector.get("previewed_price"), current_price):
        current = dict(selector)
        current["previewed_price"] = current_price
        return {
            "ok": False,
            "status": "NEEDS_RECONFIRMATION",
            "reason": "Option premium moved since the proposal was generated. Review the new terms before execution.",
            "previous": selector,
            "current": current,
        }

    wallet = trader.get_wallet_balance()
    if not wallet.get("ok"):
        return {"ok": False, "status": "FAILED", "error": wallet.get("error") or "Unable to read wallet balance."}

    if collateral_usdc > float(wallet.get("tradable_usdc", 0.0) or 0.0):
        return {"ok": False, "status": "FAILED", "error": "Insufficient tradable USDC to fill this order."}

    ok, reason = validate_confirmation(selector=selector, wallet=wallet, collateral_usdc=collateral_usdc, current_order=current_order)
    if not ok:
        return {"ok": False, "status": "FAILED", "error": f"Trade blocked by risk validator: {reason}"}

    execution = trader.execute_fill(
        collateral_usdc=collateral_usdc,
        underlying=ticker,
        option_type=order_field(current_order, "option_type", "optionType", "type"),
        strike=order_field(current_order, "strike", "strikePrice", "strike_price"),
        expiry=order_field(current_order, "expiry", "expiryTimestamp", "expiration", "expirationTimestamp"),
        dry_run=FORCE_DRY_RUN,
    )

    if FORCE_DRY_RUN and execution.get("ok"):
        execution["status"] = execution.get("status") or "DRY_RUN_OK"
        _record_trade_for_dashboard(
            user_id,
            ticker=ticker,
            action="buy",
            option_type=order_field(current_order, "option_type", "optionType", "type"),
            strike=order_field(current_order, "strike", "strikePrice", "strike_price"),
            expiry=order_field(current_order, "expiry", "expiryTimestamp", "expiration", "expirationTimestamp"),
            collateral_usdc=collateral_usdc,
            fill_price=current_price,
            reason=f"AI {action} (dry run)",
        )
        return execution

    if not FORCE_DRY_RUN:
        _log_thetanuts_trade({
            "ticker": ticker,
            "decision": "BUY",
            "action": action,
            "status": execution.get("status", "FAILED"),
            "amount_usdc": collateral_usdc,
            "order_index": None,
            "tx_hash": execution.get("tx_hash"),
            "approval_tx_hash": execution.get("approval_tx_hash"),
            "fill_tx_hash": execution.get("fill_tx_hash"),
            "wallet_tradable_usdc": wallet.get("tradable_usdc"),
            "dry_run": False,
            "error": execution.get("error"),
        })
        if execution.get("ok"):
            _record_trade_for_dashboard(
                user_id,
                ticker=ticker,
                action="buy",
                option_type=order_field(current_order, "option_type", "optionType", "type"),
                strike=order_field(current_order, "strike", "strikePrice", "strike_price"),
                expiry=order_field(current_order, "expiry", "expiryTimestamp", "expiration", "expirationTimestamp"),
                collateral_usdc=collateral_usdc,
                fill_price=current_price,
                reason=f"AI {action}",
            )
    return execution


def execute_confirmed_sell(proposal: dict, *, action: str = "CONFIRM", user_id: str = None) -> dict:
    selector = (proposal or {}).get("selector") or {}
    ticker = selector.get("underlying") or proposal.get("underlying")
    option_type = selector.get("option_type") or proposal.get("option_type")
    strike = selector.get("strike") or proposal.get("strike")
    expiry = selector.get("expiry") or proposal.get("expiry")
    reserve_price = selector.get("reserve_price") or proposal.get("reserve_price")

    live_position = trader.find_position(underlying=ticker, option_type=option_type, strike=strike, expiry=expiry)
    if not live_position.get("ok"):
        return {"ok": False, "status": "FAILED", "error": live_position.get("error") or "Unable to verify live position."}
    position = live_position.get("position")
    if position is None:
        return {"ok": False, "status": "STALE", "error": "Position is no longer open."}

    position_source = trader.get_position_source(position)
    if position_source != "rfq":
        return {"ok": False, "status": "FAILED", "error": "Only RFQ position closing is supported."}

    position_address = trader.get_position_address(position)
    if not position_address:
        return {"ok": False, "status": "FAILED", "error": "Position address is missing."}

    wallet = trader.get_wallet_balance()
    if not wallet.get("ok"):
        return {"ok": False, "status": "FAILED", "error": wallet.get("error") or "Unable to read wallet balance."}
    if not wallet.get("has_gas"):
        return {"ok": False, "status": "FAILED", "error": "Insufficient Base ETH for transaction gas."}

    close_result = trader.close_rfq_position(position_address=position_address, reserve_price=reserve_price, dry_run=FORCE_DRY_RUN)
    if not close_result.get("ok") or FORCE_DRY_RUN:
        return close_result

    tx_hash = close_result.get("tx_hash")
    transaction = trader.wait_for_transaction(tx_hash=tx_hash, timeout=120, poll_latency=2.0)
    if not transaction.get("ok"):
        return {"ok": False, "status": "FAILED", "tx_hash": tx_hash, "error": transaction.get("error") or "SELL transaction was not confirmed.", "transaction": transaction}

    verification = trader.verify_position_closed(underlying=ticker, option_type=option_type, strike=strike, expiry=expiry)
    if not verification.get("ok") or not verification.get("closed"):
        return {"ok": False, "status": "FAILED", "tx_hash": tx_hash, "error": "SELL transaction confirmed, but the live position could not be verified as closed.", "transaction": transaction, "verification": verification}

    # USDC gas is not charged on Anvil/Base (gas is ETH), so the wallet's
    # post-close USDC increase is the actual option closing proceeds.
    wallet_after = trader.get_wallet_balance()
    proceeds_usdc = None
    if wallet_after.get("ok"):
        proceeds_usdc = max(
            0.0,
            round(
                float(wallet_after.get("usdc", 0.0) or 0.0)
                - float(wallet.get("usdc", 0.0) or 0.0),
                6,
            ),
        )

    result = {**close_result, "ok": True, "status": "EXECUTED", "tx_hash": tx_hash, "receipt_confirmed": True, "transaction": transaction, "verification": verification, "proceeds_usdc": proceeds_usdc}
    _log_thetanuts_trade({
        "ticker": ticker,
        "decision": "SELL",
        "action": action,
        "status": result["status"],
        "tx_hash": tx_hash,
        "dry_run": False,
        "position_address": position_address,
        "error": None,
    })
    _record_trade_for_dashboard(
        user_id,
        ticker=ticker,
        action="sell",
        option_type=option_type,
        strike=strike,
        expiry=expiry,
        proceeds_usdc=proceeds_usdc,
        reason=f"AI {action}",
    )
    return result


def execute_trade_proposal(proposal: dict, *, action: str = "CONFIRM", user_id: str = None) -> dict:
    selector = (proposal or {}).get("selector") or {}
    decision = str(selector.get("decision") or proposal.get("decision") or proposal.get("action") or "").upper().strip()
    if decision == "BUY":
        return execute_confirmed_buy(proposal, action=action, user_id=user_id)
    if decision == "SELL":
        return execute_confirmed_sell(proposal, action=action, user_id=user_id)
    return {"ok": False, "status": "FAILED", "error": f"Unsupported trade decision: {decision or 'missing'}."}
