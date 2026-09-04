# advisor/trade_bridge.py
#
# The missing link between the AI committee decision and the Thetanuts
# execution layer.
#
# Takes the output of committee_agent (decision, confidence, risk_level)
# and the user's preferences (riskCopilotMode, riskTolerance, portfolio value)
# and produces EITHER:
#
#   A)  A fully-formed trade_proposal dict that /confirm-trade can act on, OR
#   B)  A recommend-only result explaining why no trade can be placed.
#
# Responsibility chain:
#   BUY:  committee_agent → [trade_bridge] → contract_selector (order book,
#         ATM pick) → validator → trade_proposal
#   SELL: committee_agent → [trade_bridge] → live on-chain RFQ position
#         (NOT the order book, NOT Firebase) → trade_proposal
#
# These two chains are deliberately different. A SELL isn't "pick a new
# contract" — it's "close the exact contract the wallet already holds" —
# so it must be built from the same source of truth that
# ThetanutsTrader.find_position()/close_rfq_position() use: the live
# on-chain position list. See _find_live_rfq_position() below.
#
# This module NEVER executes a trade. It only builds the proposal.
# Execution happens in ai_routes.py /confirm-trade after user confirmation.

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Default USDC collateral per trade for hackathon — small enough to be safe,
# large enough to be a real fill. Risk sizing overrides this downward, never up.
DEFAULT_COLLATERAL_USDC = 5.0
MAX_COLLATERAL_USDC     = 50.0   # Hard ceiling — matches validator.py

# SELL reserve_price floor, in USDC, keyed by risk tolerance.
#
# WHY ABSOLUTE, NOT A PERCENTAGE:
# reserve_price is a floor passed straight to `thetanuts position close
# --reserve-price` — the market maker's RFQ quote must clear this or the
# close doesn't fill. A percentage-based floor (e.g. "5% under mark")
# would need a current mark/premium price to discount from, but neither
# get_positions() nor get_live_orders() exposes one for an RFQ position
# before you request the close (RFQ = the quote doesn't exist until you
# ask for it). So this is a flat per-contract premium floor instead —
# tune these numbers based on real fills once there's live data to look
# at; they're a reasonable starting guess, not calibrated against actual
# quotes yet.
RESERVE_PRICE_FLOOR_USDC = {
    "Low (Conservative)": 1.00,
    "Moderate":           0.50,
    "High (Aggressive)":  0.10,
}
DEFAULT_RESERVE_PRICE_FLOOR_USDC = 0.50


def _recommend_only(reason: str, risk_copilot_mode: str) -> dict:
    """Small helper so every early-exit path returns the same shape."""
    return {
        "status":      "RECOMMEND_ONLY",
        "reason":      reason,
        "proposal":    None,
        "action_mode": risk_copilot_mode,
    }


def _compute_collateral(
    wallet_tradable_usdc: float,
    confidence: float,
    risk_tolerance: str,
    preferences: dict,
) -> float:
    """
    Determines USDC collateral from:
      1. User's stated max_trade_amount preference (if set)
      2. AI confidence (higher confidence → use slightly more of the budget)
      3. Risk tolerance tier
      4. Hard cap and wallet cap

    BUY-only. SELL never spends new collateral — see build_trade_proposal.
    """
    # 1. User preference overrides everything (if set)
    pref_max = preferences.get("maxTradeAmountUSDC") or preferences.get("max_trade_amount")
    if pref_max:
        try:
            base = float(pref_max)
        except (TypeError, ValueError):
            base = DEFAULT_COLLATERAL_USDC
    else:
        # Tiered defaults by risk tolerance
        tolerance_defaults = {
            "Low (Conservative)": 2.0,
            "Moderate":           5.0,
            "High (Aggressive)":  10.0,
        }
        base = tolerance_defaults.get(risk_tolerance, DEFAULT_COLLATERAL_USDC)

    # 2. Scale by AI confidence (confidence 0.5 → 50% of base, 1.0 → 100%)
    scaled = base * max(0.5, float(confidence))

    # 3. Apply hard caps
    collateral = min(scaled, MAX_COLLATERAL_USDC, wallet_tradable_usdc)
    collateral = round(collateral, 2)

    return collateral


def _position_field(position: dict, *names):
    """Return the first non-None field from a live position dict.

    Mirrors ThetanutsTrader._position_field's alias list exactly, so a
    SELL proposal built here matches what /confirm-trade will look up
    again later via trader.find_position()."""
    for name in names:
        value = position.get(name)
        if value is not None:
            return value
    return None


def _find_live_rfq_position(trader, symbol: str) -> dict:
    """
    Locate the wallet's live RFQ position for `symbol` — the ONLY source
    of truth a SELL proposal should be built from.

    Deliberately does NOT touch Firebase/portfolio data. ThetanutsTrader's
    own find_position() docstring is explicit about this: "Firestore is
    deliberately NOT used as the source of truth." /confirm-trade's SELL
    branch re-derives the position the same way (trader.find_position by
    underlying/option_type/strike/expiry), so if this function and that
    lookup disagree, the confirm step will simply fail to find anything
    to close — building the proposal from the same data avoids that.

    Returns:
        {
            "ok":       bool,
            "position": dict | None,   # None means "not held, not an error"
            "error":    str | None,
        }
    """
    result = trader.get_positions(source="rfq")

    if not result.get("ok"):
        return {"ok": False, "position": None, "error": result.get("error")}

    target = str(symbol).strip().upper()
    matches = []

    for position in result.get("data", []):
        if not isinstance(position, dict):
            continue

        pos_underlying = _position_field(
            position, "underlying", "asset", "underlyingAsset", "underlying_asset",
        )

        if pos_underlying is None:
            continue

        if str(pos_underlying).strip().upper() != target:
            continue

        matches.append(position)

    if not matches:
        return {"ok": True, "position": None, "error": None}

    if len(matches) > 1:
        return {
            "ok": False,
            "position": None,
            "error": (
                f"Multiple live RFQ positions found for {symbol} — "
                "SELL requires an unambiguous position."
            ),
        }

    return {"ok": True, "position": matches[0], "error": None}


def _build_buy_proposal(
    symbol: str,
    investment_analysis: dict,
    preferences: dict,
    trader,
    spot_price,
    confidence: float,
    risk_tolerance: str,
    risk_copilot_mode: str,
) -> dict:
    """BUY: pick the best current order-book contract, size collateral,
    validate, done. Unchanged in spirit from the original implementation."""
    from trading.contract_selector import find_best_contract
    from trading.validator import validate_proposal

    if spot_price is None or spot_price <= 0:
        return _recommend_only(
            f"Trade blocked: no valid current spot price is available for {symbol}.",
            risk_copilot_mode,
        )

    contract_result = find_best_contract(
        trader=trader,
        symbol=symbol,
        decision="BUY",
        spot_price=spot_price,
    )

    if not contract_result.get("tradeable"):
        return _recommend_only(contract_result["reason"], risk_copilot_mode)

    selector = contract_result["selector"]
    selector["decision"] = "BUY"

    wallet = trader.get_wallet_balance()
    tradable_usdc = float(wallet.get("tradable_usdc", 0.0) or 0.0)

    collateral_usdc = _compute_collateral(
        wallet_tradable_usdc=tradable_usdc,
        confidence=confidence,
        risk_tolerance=risk_tolerance,
        preferences=preferences,
    )

    selector["collateral_usdc"] = collateral_usdc

    ok, validation_reason = validate_proposal(
        selector=selector,
        wallet=wallet,
        collateral_usdc=collateral_usdc,
        spot_price=spot_price,
    )

    if not ok:
        return _recommend_only(
            f"Trade blocked by risk validator: {validation_reason}",
            risk_copilot_mode,
        )

    proposal = {
        "selector":         selector,
        "symbol":           symbol,
        "decision":         "BUY",
        "underlying":       contract_result["underlying"],
        "option_type":      selector["option_type"],
        "strike":           selector["strike"],
        "expiry":           selector["expiry"],
        "previewed_price":  selector.get("previewed_price"),
        "quantity":         None,
        "collateral_usdc":  collateral_usdc,
        "confidence_pct":   int(confidence * 100),
        "risk_level":       investment_analysis.get("risk_level", "MEDIUM"),
        "wallet_snapshot": {
            "tradable_usdc": tradable_usdc,
            "has_gas":       wallet.get("has_gas"),
        },
    }

    logger.info(
        f"[TradeBridge] BUY proposal built: {symbol} → "
        f"{selector['option_type']} strike={selector['strike']} "
        f"collateral={collateral_usdc} USDC | mode={risk_copilot_mode}"
    )

    return {
        "status":      "EXECUTABLE",
        "reason":      "Valid trade proposal generated.",
        "proposal":    proposal,
        "action_mode": risk_copilot_mode,
    }


def _build_sell_proposal(
    symbol: str,
    investment_analysis: dict,
    preferences: dict,
    trader,
    confidence: float,
    risk_tolerance: str,
    risk_copilot_mode: str,
) -> dict:
    """
    SELL: close the wallet's actual live RFQ position — never a
    freshly-selected order-book contract, never a Firebase-reported
    quantity.

    No collateral, no contract_selector, no validate_proposal here —
    those are BUY-only concerns (sizing new capital against a fresh
    contract). A SELL is either backed by a real live position or it
    isn't.

    RESERVE PRICE: derived from the user's riskTolerance via
    RESERVE_PRICE_FLOOR_USDC — a flat per-contract premium floor, not a
    percentage, since there's no live mark/quote available for an RFQ
    position ahead of the close (see the constant's docstring above for
    why). Passed through in the selector so /confirm-trade's
    close_rfq_position(...) call can use it directly.
    """
    lookup = _find_live_rfq_position(trader, symbol)

    if not lookup["ok"]:
        return _recommend_only(
            lookup["error"] or f"Could not verify a live position for {symbol}.",
            risk_copilot_mode,
        )

    position = lookup["position"]

    if position is None:
        return _recommend_only(
            f"SELL blocked: no live RFQ position found for {symbol}.",
            risk_copilot_mode,
        )

    underlying = _position_field(
        position, "underlying", "asset", "underlyingAsset", "underlying_asset",
    )
    option_type = _position_field(
        position, "optionType", "type", "option_type", "option_type_name",
    )
    strike = _position_field(position, "strike", "strikePrice", "strike_price")
    expiry = _position_field(
        position, "expiry", "expiration", "expirationTimestamp", "expiration_timestamp",
    )
    quantity = _position_field(position, "quantity", "contracts", "size")

    if underlying is None or option_type is None or strike is None or expiry is None:
        return _recommend_only(
            f"SELL blocked: the live {symbol} position is missing contract details.",
            risk_copilot_mode,
        )

    position_address = trader.get_position_address(position)

    if not position_address:
        return _recommend_only(
            f"SELL blocked: the live {symbol} position has no contract address.",
            risk_copilot_mode,
        )

    wallet = trader.get_wallet_balance()

    if not wallet.get("ok"):
        return _recommend_only(
            wallet.get("error") or "Unable to read wallet balance.",
            risk_copilot_mode,
        )

    if not wallet.get("has_gas"):
        return _recommend_only(
            "SELL blocked: insufficient Base ETH for transaction gas.",
            risk_copilot_mode,
        )

    reserve_price = RESERVE_PRICE_FLOOR_USDC.get(
        risk_tolerance, DEFAULT_RESERVE_PRICE_FLOOR_USDC
    )

    # Selector carries exactly the fields /confirm-trade's SELL branch
    # re-derives the position from (underlying/option_type/strike/expiry)
    # plus the resolved position_address, so confirm-trade doesn't have to
    # re-search — it can use this directly if it chooses to, and it will
    # still match if it re-looks-up via find_position().
    selector = {
        "underlying":       underlying,
        "option_type":      option_type,
        "strike":           strike,
        "expiry":           expiry,
        "position_address": position_address,
        "decision":         "SELL",
        # SELL spends no new collateral — the collateral already belongs
        # to the existing option position being closed.
        "collateral_usdc":  0.0,
        # Floor passed straight through to close_rfq_position(). If the
        # RFQ market maker's quote comes in below this, the CLI should
        # fail to fill rather than close at a bad price.
        "reserve_price":    reserve_price,
    }

    proposal = {
        "selector":         selector,
        "symbol":           symbol,
        "decision":         "SELL",
        "underlying":       underlying,
        "option_type":      option_type,
        "strike":           strike,
        "expiry":           expiry,
        "previewed_price":  None,
        "quantity":         quantity,
        "collateral_usdc":  0.0,
        "reserve_price":    reserve_price,
        "confidence_pct":   int(confidence * 100),
        "risk_level":       investment_analysis.get("risk_level", "MEDIUM"),
        "wallet_snapshot": {
            "tradable_usdc": wallet.get("tradable_usdc"),
            "has_gas":       wallet.get("has_gas"),
        },
    }

    logger.info(
        f"[TradeBridge] SELL proposal built: {symbol} → "
        f"{option_type} strike={strike} expiry={expiry} "
        f"position={position_address} qty={quantity} "
        f"reserve_price={reserve_price} | mode={risk_copilot_mode}"
    )

    return {
        "status":      "EXECUTABLE",
        "reason":      "Valid SELL proposal generated from your live RFQ position.",
        "proposal":    proposal,
        "action_mode": risk_copilot_mode,
    }


def build_trade_proposal(
    symbol: str,
    decision: str,
    investment_analysis: dict,
    preferences: dict,
    portfolio: dict,
    trader,         # ThetanutsTrader instance
    spot_price: float = None,
    explicit_user_action: str = None,
) -> dict:
    """
    Main entry point. Called from ai_agent.py after the committee decision.

    Args:
        symbol:              Asset symbol from the committee (e.g. "BTC", "NVDA")
        decision:            "BUY", "SELL", or "HOLD"
        investment_analysis: Full committee output dict
        preferences:         User preferences (riskCopilotMode, riskTolerance, etc.)
        portfolio:           User portfolio summary. NOTE: no longer used to
                              gate SELL — kept as a parameter for backward
                              compatibility with existing callers, but SELL
                              ownership is now checked against the live
                              on-chain position (see _find_live_rfq_position),
                              since that's what /confirm-trade actually acts
                              on. Firebase can drift from that; the chain
                              can't.
        trader:               ThetanutsTrader instance (already initialised in ai_agent.py)
        spot_price:          Current spot price (BUY only — used for ATM
                              selection & OTM check; ignored for SELL, which
                              is sourced from the live position instead)

    Returns dict with keys:
        status:       "EXECUTABLE" | "RECOMMEND_ONLY"
        reason:       Human-readable explanation (shown when not tradeable)
        proposal:     dict | None — the /confirm-trade payload if EXECUTABLE
        action_mode:  mirrors riskCopilotMode
    """
    risk_copilot_mode = preferences.get("riskCopilotMode", "Suggest actions, I confirm each one")
    risk_tolerance    = preferences.get("riskTolerance", "Moderate")
    confidence        = float(investment_analysis.get("confidence", 0.5))

    # ── 1. HOLD / INSUFFICIENT_DATA → never trade ───────────────────────
    if decision not in ("BUY", "SELL"):
        return _recommend_only(
            f"Committee decision is '{decision}' — no trade action required.",
            risk_copilot_mode,
        )

    # ── 2. Low confidence guard ─────────────────────────────────────────
    if confidence < 0.55 and not explicit_user_action:
        return _recommend_only(
            f"Evidence conviction is only {int(confidence * 100)}% — below the 55% "
            f"threshold required to generate an executable trade proposal. "
            f"Monitoring recommended.",
            risk_copilot_mode,
        )

    # ── 3. Dispatch — BUY and SELL are genuinely different pipelines ────
    if decision == "BUY":
        return _build_buy_proposal(
            symbol=symbol,
            investment_analysis=investment_analysis,
            preferences=preferences,
            trader=trader,
            spot_price=spot_price,
            confidence=confidence,
            risk_tolerance=risk_tolerance,
            risk_copilot_mode=risk_copilot_mode,
        )

    return _build_sell_proposal(
        symbol=symbol,
        investment_analysis=investment_analysis,
        preferences=preferences,
        trader=trader,
        confidence=confidence,
        risk_tolerance=risk_tolerance,
        risk_copilot_mode=risk_copilot_mode,
    )