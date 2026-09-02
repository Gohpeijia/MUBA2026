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
#   committee_agent → [trade_bridge] → contract_selector → validator → trade_proposal
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
    Returns a float collateral amount.
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


def build_trade_proposal(
    symbol: str,
    decision: str,
    investment_analysis: dict,
    preferences: dict,
    portfolio: dict,
    trader,         # ThetanutsTrader instance
    spot_price: float = None,
) -> dict:
    """
    Main entry point. Called from ai_agent.py after the committee decision.

    Args:
        symbol:              Asset symbol from the committee (e.g. "BTC", "NVDA")
        decision:            "BUY", "SELL", or "HOLD"
        investment_analysis: Full committee output dict
        preferences:         User preferences (riskCopilotMode, riskTolerance, etc.)
        portfolio:           User portfolio summary (for open exposure check)
        trader:              ThetanutsTrader instance (already initialised in ai_agent.py)
        spot_price:          Current spot price (used for ATM selection & OTM check)

    Returns dict with keys:
        status:       "EXECUTABLE" | "RECOMMEND_ONLY"
        reason:       Human-readable explanation (shown when not tradeable)
        proposal:     dict | None — the /confirm-trade payload if EXECUTABLE
        action_mode:  mirrors riskCopilotMode
    """
    from trading.contract_selector import find_best_contract
    from trading.validator import validate_proposal

    risk_copilot_mode = preferences.get("riskCopilotMode", "Suggest actions, I confirm each one")
    risk_tolerance    = preferences.get("riskTolerance", "Moderate")
    confidence        = float(investment_analysis.get("confidence", 0.5))

    # ── 1. HOLD / INSUFFICIENT_DATA → never trade ───────────────────────
    if decision not in ("BUY", "SELL"):
        return {
            "status":      "RECOMMEND_ONLY",
            "reason":      f"Committee decision is '{decision}' — no trade action required.",
            "proposal":    None,
            "action_mode": risk_copilot_mode,
        }

    # ── 2. Low confidence guard ─────────────────────────────────────────
    if confidence < 0.55:
        return {
            "status": "RECOMMEND_ONLY",
            "reason": (
                f"Evidence conviction is only {int(confidence * 100)}% — below the 55% "
                f"threshold required to generate an executable trade proposal. "
                f"Monitoring recommended."
            ),
            "proposal":    None,
            "action_mode": risk_copilot_mode,
        }

    # ── 3. Tradeability check + ATM contract selection ──────────────────
    contract_result = find_best_contract(
        trader=trader,
        symbol=symbol,
        decision=decision,
        spot_price=spot_price or 0.0,
    )

    if not contract_result.get("tradeable"):
        return {
            "status":      "RECOMMEND_ONLY",
            "reason":      contract_result["reason"],
            "proposal":    None,
            "action_mode": risk_copilot_mode,
        }

    selector = contract_result["selector"]

    # ── 4. Wallet check ─────────────────────────────────────────────────
    wallet = trader.get_wallet_balance()
    tradable_usdc = wallet.get("tradable_usdc", 0.0)

    # ── 5. Compute collateral ───────────────────────────────────────────
    collateral_usdc = _compute_collateral(
        wallet_tradable_usdc=tradable_usdc,
        confidence=confidence,
        risk_tolerance=risk_tolerance,
        preferences=preferences,
    )

    # Attach collateral to the selector — /confirm-trade needs it
    selector["collateral_usdc"] = collateral_usdc

    # ── 6. Hard validation gate ─────────────────────────────────────────
    ok, validation_reason = validate_proposal(
        selector=selector,
        wallet=wallet,
        collateral_usdc=collateral_usdc,
        spot_price=spot_price,
    )

    if not ok:
        return {
            "status":      "RECOMMEND_ONLY",
            "reason":      f"Trade blocked by risk validator: {validation_reason}",
            "proposal":    None,
            "action_mode": risk_copilot_mode,
        }

    # ── 7. Build final proposal ─────────────────────────────────────────
    proposal = {
        # The exact selector /confirm-trade needs
        "selector": selector,

        # Metadata for the frontend UI
        "symbol":           symbol,
        "decision":         decision,
        "underlying":       contract_result["underlying"],
        "option_type":      selector["option_type"],
        "strike":           selector["strike"],
        "expiry":           selector["expiry"],
        "previewed_price":  selector.get("previewed_price"),
        "collateral_usdc":  collateral_usdc,
        "confidence_pct":   int(confidence * 100),
        "risk_level":       investment_analysis.get("risk_level", "MEDIUM"),

        # Wallet snapshot shown to user
        "wallet_snapshot": {
            "tradable_usdc": tradable_usdc,
            "has_gas":       wallet.get("has_gas"),
        },
    }

    logger.info(
        f"[TradeBridge] Proposal built: {decision} {symbol} → "
        f"{selector['option_type']} strike={selector['strike']} "
        f"collateral={collateral_usdc} USDC | mode={risk_copilot_mode}"
    )

    return {
        "status":      "EXECUTABLE",
        "reason":      "Valid trade proposal generated.",
        "proposal":    proposal,
        "action_mode": risk_copilot_mode,
    }
