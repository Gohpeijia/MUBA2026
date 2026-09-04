# trading/validator.py
#
# Hard execution gate — the LAST barrier before any blockchain transaction.
#
# Rules are deterministic and cannot be overridden by AI output.
# If ANY rule fails, the response is (False, reason_string) and NO trade fires.
#
# Called from two places:
#   1. advisor/trade_bridge.py  — when building the initial trade proposal
#   2. ai_routes.py /confirm-trade — fresh re-check right before execution
#
# Never raises. Returns (bool, str) always.

import logging
import time
from typing import Tuple

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
#  HARD LIMITS  (edit these, not the logic below)
# ─────────────────────────────────────────────────────────────────────────────

# Maximum USDC that can ever be spent on a single fill, regardless of what
# risk sizing calculated. This is a hard ceiling, not a target.
MAX_SINGLE_TRADE_USDC = 50.0

# Minimum USDC collateral — don't attempt a fill so small the gas would dwarf it.
MIN_SINGLE_TRADE_USDC = 0.50

# Minimum ETH required in the wallet to cover gas for a fill.
MIN_ETH_FOR_GAS = 0.0003

# Minimum hours until contract expiry. Options expiring imminently are
# almost certain to be worthless by the time the tx lands.
MIN_EXPIRY_HOURS = 24

# Maximum % spread between previewed price and current live price.
# If the premium moved more than this since the user was shown the proposal,
# we refuse to auto-fill and force a re-confirmation.
MAX_PRICE_DRIFT_PCT = 0.05   # 5%

# Maximum % the strike can be out of the money relative to spot.
MAX_STRIKE_OTM_PCT = 0.20    # 20%


# ─────────────────────────────────────────────────────────────────────────────
#  INDIVIDUAL RULE CHECKS
# ─────────────────────────────────────────────────────────────────────────────

def _check_wallet(wallet: dict) -> Tuple[bool, str]:
    if not wallet.get("ok"):
        return False, f"Wallet check failed: {wallet.get('error', 'unknown error')}"
    if not wallet.get("has_gas"):
        eth = wallet.get("eth", 0)
        return False, f"Insufficient ETH for gas: {eth:.6f} ETH (need ≥ {MIN_ETH_FOR_GAS} ETH)"
    return True, "OK"


def _check_collateral(collateral_usdc: float, wallet: dict) -> Tuple[bool, str]:
    if collateral_usdc < MIN_SINGLE_TRADE_USDC:
        return False, f"Trade size {collateral_usdc} USDC is below minimum {MIN_SINGLE_TRADE_USDC} USDC"

    if collateral_usdc > MAX_SINGLE_TRADE_USDC:
        return False, (
            f"Trade size {collateral_usdc} USDC exceeds the hard cap of "
            f"{MAX_SINGLE_TRADE_USDC} USDC. Reduce collateral."
        )

    tradable = wallet.get("tradable_usdc", 0.0)
    if collateral_usdc > tradable:
        return False, (
            f"Insufficient USDC: need {collateral_usdc} USDC but only "
            f"{tradable} USDC is tradable (after safety buffer)."
        )

    return True, "OK"


def _check_expiry(expiry_ts: int) -> Tuple[bool, str]:
    if not expiry_ts:
        return False, "Contract expiry timestamp is missing."

    hours_remaining = (expiry_ts - int(time.time())) / 3600
    if hours_remaining < MIN_EXPIRY_HOURS:
        return False, (
            f"Contract expires in {hours_remaining:.1f}h — "
            f"minimum required is {MIN_EXPIRY_HOURS}h. Option has too little time remaining."
        )

    return True, "OK"


def _check_strike_vs_spot(strike: float, spot_price: float) -> Tuple[bool, str]:
    if not strike or not spot_price or spot_price <= 0:
        return False, "Strike or spot price is missing — cannot validate contract."

    otm_pct = abs(strike - spot_price) / spot_price
    if otm_pct > MAX_STRIKE_OTM_PCT:
        return False, (
            f"Strike {strike} is {otm_pct:.1%} away from spot {spot_price} — "
            f"exceeds max OTM threshold of {MAX_STRIKE_OTM_PCT:.0%}."
        )

    return True, "OK"


def _check_price_drift(previewed_price: float, current_price: float) -> Tuple[bool, str]:
    """
    Checks whether the option premium has drifted materially since the
    user was shown the proposal. Skipped if either price is unavailable.
    """
    if not previewed_price or not current_price:
        return True, "Price drift check skipped (prices unavailable)"

    try:
        drift = abs(float(current_price) - float(previewed_price)) / float(previewed_price)
    except (TypeError, ValueError, ZeroDivisionError):
        return True, "Price drift check skipped (parse error)"

    if drift > MAX_PRICE_DRIFT_PCT:
        return False, (
            f"Option premium moved {drift:.1%} since proposal was generated "
            f"(max allowed: {MAX_PRICE_DRIFT_PCT:.0%}). Please re-confirm with current price."
        )

    return True, "OK"


# ─────────────────────────────────────────────────────────────────────────────
#  PUBLIC ENTRY POINTS
# ─────────────────────────────────────────────────────────────────────────────

def validate_proposal(
    selector: dict,
    wallet: dict,
    collateral_usdc: float,
    spot_price: float = None,
) -> Tuple[bool, str]:
    """
    Pre-execution validation called when building a trade proposal.
    Runs all hard-limit checks EXCEPT price drift (no live comparison yet).

    Args:
        selector:        Contract selector from contract_selector.find_best_contract()
        wallet:          Live wallet state from ThetanutsTrader.get_wallet_balance()
        collateral_usdc: Proposed USDC collateral amount
        spot_price:      Current spot price for OTM check (optional but recommended)

    Returns:
        (True, "OK") or (False, human-readable failure reason)
    """
    checks = [
        _check_wallet(wallet),
        _check_collateral(collateral_usdc, wallet),
        _check_expiry(selector.get("expiry")),
    ]

    if spot_price and spot_price > 0:
        checks.append(_check_strike_vs_spot(selector.get("strike"), spot_price))

    for passed, reason in checks:
        if not passed:
            logger.warning(f"[Validator] BLOCKED: {reason}")
            return False, reason

    return True, "OK"


def validate_confirmation(
    selector: dict,
    wallet: dict,
    collateral_usdc: float,
    current_order: dict = None,
    spot_price: float = None,
) -> Tuple[bool, str]:
    """
    Final gate at /confirm-trade — re-runs ALL checks against FRESH live data.
    Also checks whether the option premium has drifted since the proposal.

    Args:
        selector:       Original selector from the /chat proposal
        wallet:         FRESH wallet state fetched right now
        collateral_usdc: Collateral the user confirmed
        current_order:  The FRESH OptionBook order fetched right now
        spot_price:     Current spot price (optional)

    Returns:
        (True, "OK") or (False, human-readable failure reason)
    """
    # Re-run all base checks against fresh data
    ok, reason = validate_proposal(selector, wallet, collateral_usdc, spot_price)
    if not ok:
        return False, reason

    # Price drift check — only possible at confirmation because we have both
    # the previewed price (from /chat) and the current live price
    if current_order:
        current_price = (
            current_order.get("price_per_contract") or
            current_order.get("price") or
            current_order.get("premium") or
            current_order.get("unitPrice")
        )
        previewed = selector.get("previewed_price")
        ok, reason = _check_price_drift(previewed, current_price)
        if not ok:
            return False, reason

    return True, "OK"
