# trading/contract_selector.py
#
# Deterministic contract selection layer.
#
# The AI decides the DIRECTION ("BUY BTC" or "SELL ETH").
# This module decides THE EXACT CONTRACT — which strike, which expiry.
#
# Rules (ATM-first, hackathon-safe):
#   BUY  decision → select CALL option
#   SELL decision → select PUT  option
#   Strike: closest to current spot price (ATM)
#   Expiry: nearest valid expiry > MIN_EXPIRY_HOURS from now
#   If no suitable contract exists → returns None (caller degrades to RECOMMEND_ONLY)
#
# Never raises. Returns None on any failure so the pipeline degrades safely.

import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Minimum time-to-expiry in hours.
# Options expiring in < 24h have extreme Theta decay — never fill them.
MIN_EXPIRY_HOURS = 24
MIN_EXPIRY_SECONDS = MIN_EXPIRY_HOURS * 3600

# Maximum acceptable spread between listed strike and spot price, as a %.
# Reject any contract where abs(strike - spot) / spot > this threshold.
# Keeps the system from filling a deep OTM contract by accident.
MAX_STRIKE_OTM_PCT = 0.20   # 20% OTM max


# ─────────────────────────────────────────────────────────────────────────────
#  ASSET NORMALISATION
# ─────────────────────────────────────────────────────────────────────────────

# Maps the canonical asset names used by the AI (from asset_resolver.py)
# to the underlying strings the Thetanuts CLI actually understands.
# You MUST verify these against a live `thetanuts book orders -o json` call.
#
# Equities (AAPL, NVDA, MSFT) are intentionally absent — they are not
# listed on Thetanuts. Callers will receive None and degrade to RECOMMEND_ONLY.
THETANUTS_ASSET_MAP: dict[str, str] = {
    "BTC":     "BTC",
    "ETH":     "ETH",
    "BTC-USD": "BTC",
    "ETH-USD": "ETH",
    "WBTC":    "BTC",
    "WETH":    "ETH",
}


def resolve_thetanuts_underlying(symbol: str) -> Optional[str]:
    """
    Maps a canonical AI-side symbol to its Thetanuts underlying string.
    Returns None if the asset is not listed on Thetanuts (equities, unknown).
    """
    return THETANUTS_ASSET_MAP.get(symbol.upper())


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN SELECTION LOGIC
# ─────────────────────────────────────────────────────────────────────────────

def select_contract(
    orders: list,
    decision: str,          # "BUY" or "SELL"
    spot_price: float,      # Current spot price for the underlying
) -> Optional[dict]:
    """
    Given a list of live OptionBook orders from ThetanutsTrader.get_live_orders(),
    selects the single best contract for the given directional decision.

    Returns a dict matching the /confirm-trade selector shape, or None if no
    suitable contract exists.

    The selector returned contains ONLY the fields /confirm-trade needs:
      underlying, option_type, strike, expiry, previewed_price
    """
    if not orders or spot_price <= 0:
        return None

    # BUY → we want a CALL (right to buy = profits if price goes UP)
    # SELL → we want a PUT  (right to sell = profits if price goes DOWN)
    target_option_type = "CALL" if decision == "BUY" else "PUT"

    now_ts = int(time.time())
    min_expiry_ts = now_ts + MIN_EXPIRY_SECONDS

    candidates = []
    for order in orders:
        # ── Normalise field names (CLI output varies between versions) ──
        opt_type = (
            order.get("type") or
            order.get("optionType") or
            order.get("option_type") or ""
        ).upper()

        strike_raw = order.get("strike") or order.get("strikePrice")
        expiry_raw = order.get("expiry") or order.get("expiryTimestamp") or order.get("expiration")
        price_raw  = order.get("price") or order.get("premium") or order.get("unitPrice")

        # ── Skip if required fields are missing ──
        if not opt_type or strike_raw is None or expiry_raw is None:
            continue

        try:
            strike = float(strike_raw)
            expiry = int(expiry_raw)
            price  = float(price_raw) if price_raw is not None else None
        except (TypeError, ValueError):
            continue

        # ── Filter by option type ──
        if opt_type != target_option_type:
            continue

        # ── Filter by minimum expiry ──
        if expiry < min_expiry_ts:
            logger.debug(f"Skipping contract strike={strike} expiry={expiry}: expires too soon")
            continue

        # ── Filter by maximum OTM distance ──
        otm_pct = abs(strike - spot_price) / spot_price
        if otm_pct > MAX_STRIKE_OTM_PCT:
            logger.debug(f"Skipping contract strike={strike}: {otm_pct:.1%} OTM exceeds {MAX_STRIKE_OTM_PCT:.0%} limit")
            continue

        candidates.append({
            "underlying":    order.get("underlying") or order.get("asset"),
            "option_type":   opt_type,
            "strike":        strike,
            "expiry":        expiry,
            "previewed_price": str(price) if price is not None else None,
            "otm_pct":       otm_pct,
            "_raw":          order,   # kept for debugging; stripped before returning
        })

    if not candidates:
        logger.info(f"No valid {target_option_type} contracts found for decision={decision}, spot={spot_price}")
        return None

    # ── Sort: closest to ATM first, then nearest expiry as tiebreaker ──
    candidates.sort(key=lambda c: (c["otm_pct"], c["expiry"]))
    best = candidates[0]

    # Strip the internal debug field before returning
    best.pop("_raw", None)
    best.pop("otm_pct", None)

    logger.info(
        f"Selected contract: {best['option_type']} "
        f"strike={best['strike']} expiry={best['expiry']} "
        f"price={best['previewed_price']}"
    )
    return best


# ─────────────────────────────────────────────────────────────────────────────
#  PUBLIC ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def find_best_contract(
    trader,             # ThetanutsTrader instance
    symbol: str,        # AI-side asset name e.g. "BTC", "ETH", "NVDA"
    decision: str,      # "BUY" or "SELL"
    spot_price: float,  # Live spot price used for ATM selection
) -> dict:
    """
    Full tradeability check + contract selection in one call.

    Returns:
      {
        "tradeable":     bool,
        "reason":        str,            # human-readable (shown to user if not tradeable)
        "underlying":    str | None,     # Thetanuts underlying e.g. "BTC"
        "selector":      dict | None,    # /confirm-trade payload fields
      }
    """
    # ── 1. Map symbol to Thetanuts underlying ──
    underlying = resolve_thetanuts_underlying(symbol)
    if underlying is None:
        return {
            "tradeable": False,
            "reason": (
                f"{symbol} is not currently listed on the Thetanuts OptionBook. "
                f"This analysis is provided as a research recommendation only — "
                f"no on-chain trade can be placed for this asset."
            ),
            "underlying": None,
            "selector":   None,
        }

    # ── 2. Fetch live orders from the OptionBook ──
    option_type = "CALL" if decision == "BUY" else "PUT"
    orders_result = trader.get_live_orders(
        underlying=underlying,
        option_type=option_type,
        min_expiry=int(time.time()) + MIN_EXPIRY_SECONDS,
    )

    if not orders_result.get("ok"):
        return {
            "tradeable": False,
            "reason": (
                f"Could not fetch live orders for {underlying}: "
                f"{orders_result.get('error', 'unknown error')}. "
                f"Trade recommendation stands, but execution is unavailable right now."
            ),
            "underlying": underlying,
            "selector":   None,
        }

    orders = orders_result.get("data", [])
    if not orders:
        return {
            "tradeable": False,
            "reason": (
                f"No active {option_type} orders found for {underlying} on the Thetanuts OptionBook "
                f"with sufficient time to expiry. The recommendation stands — check back when "
                f"market makers post new contracts."
            ),
            "underlying": underlying,
            "selector":   None,
        }

    # ── 3. Deterministically select the best contract ──
    selector = select_contract(orders, decision, spot_price)
    if selector is None:
        return {
            "tradeable": False,
            "reason": (
                f"Orders exist for {underlying} but none passed the contract selection criteria "
                f"(ATM within 20%, expiry > {MIN_EXPIRY_HOURS}h). No trade placed."
            ),
            "underlying": underlying,
            "selector":   None,
        }

    # Ensure underlying is set in the selector (some CLI responses omit it)
    if not selector.get("underlying"):
        selector["underlying"] = underlying

    return {
        "tradeable": True,
        "reason":    "Valid contract found on Thetanuts OptionBook.",
        "underlying": underlying,
        "selector":   selector,
    }
