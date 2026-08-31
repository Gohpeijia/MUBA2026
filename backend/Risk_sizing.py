# risk_sizing.py
"""
Pure risk-based position sizing math. No DB, no network calls — everything
here takes plain numbers/dicts in and returns plain dicts out, so it can be
unit tested in isolation and reused by:
  - ai_agent.py   (to attach a sized trade_proposal to a BUY/SELL consensus)
  - ai_routes.py  (final risk-limit gate right before an auto-trade executes)

Model: risk-per-trade % (tiered by risk tolerance) -> dollar risk budget ->
divided by per-share stop distance -> capped by a max position size and a
max portfolio-wide "at risk" ceiling.
"""

from typing import Optional

# Risk-per-trade budget as a % of total portfolio value, tiered by the
# user's stated risk tolerance (preferences.riskTolerance).
RISK_PCT_BY_TOLERANCE = {
    "Low (Conservative)": 0.005,   # risk 0.5% of portfolio per trade
    "Moderate":           0.01,    # 1%
    "High (Aggressive)":  0.02,    # 2%
}
DEFAULT_RISK_PCT = 0.01

# Default stop-loss distance as a % away from entry, tiered by risk
# tolerance. Used only when the caller hasn't supplied an explicit stop.
STOP_PCT_BY_TOLERANCE = {
    "Low (Conservative)": 0.04,    # tight 4% stop
    "Moderate":           0.07,    # 7%
    "High (Aggressive)":  0.12,    # 12%, gives more room to run
}
DEFAULT_STOP_PCT = 0.07

# Hard ceilings, independent of what the risk-per-trade math produces.
MAX_POSITION_PCT_OF_PORTFOLIO = 0.20   # never let AI sizing put more than
                                        # 20% of the portfolio into one ticker
MAX_PORTFOLIO_RISK_PCT = 0.06          # never let total open AI-sized risk
                                        # across all positions exceed 6%


def estimate_stop_loss(entry_price: float, risk_tolerance: str, direction: str = "BUY") -> float:
    """
    Derive a stop-loss price when none is supplied. 'BUY' places the stop
    below entry (long); 'SELL' places it above entry (covering a short /
    protecting an exit).
    """
    stop_pct = STOP_PCT_BY_TOLERANCE.get(risk_tolerance, DEFAULT_STOP_PCT)
    if direction == "SELL":
        return round(entry_price * (1 + stop_pct), 4)
    return round(entry_price * (1 - stop_pct), 4)


def calculate_position_size(
    portfolio_value:         float,
    entry_price:              float,
    risk_tolerance:           str             = "Moderate",
    stop_loss_price:          Optional[float] = None,
    existing_exposure_value:  float           = 0.0,  # $ already held in this ticker
    open_ai_risk_value:       float           = 0.0,  # $ already "at risk" across all AI-sized positions
    max_position_pct:         float           = MAX_POSITION_PCT_OF_PORTFOLIO,
    max_portfolio_risk_pct:   float           = MAX_PORTFOLIO_RISK_PCT,
    direction:                str             = "BUY",
) -> dict:
    """
    Returns:
      {
        recommended_shares, dollar_risk, risk_pct_used, stop_loss_price,
        position_value, position_pct_of_portfolio, capped_by,
        passes_risk_limits, notes
      }
    recommended_shares is always an int >= 0. capped_by is None or one of
    'portfolio_risk_limit' / 'max_position_size' / 'invalid_input' /
    'zero_stop_distance'.
    """
    notes = []

    if portfolio_value <= 0 or entry_price <= 0:
        return {
            "recommended_shares": 0, "dollar_risk": 0, "risk_pct_used": 0,
            "stop_loss_price": stop_loss_price, "position_value": 0,
            "position_pct_of_portfolio": 0, "capped_by": "invalid_input",
            "passes_risk_limits": False,
            "notes": ["Portfolio value or entry price is zero/invalid — cannot size a trade."],
        }

    if stop_loss_price is None:
        stop_loss_price = estimate_stop_loss(entry_price, risk_tolerance, direction)
        notes.append(f"No stop-loss provided — estimated at {stop_loss_price} based on '{risk_tolerance}' tolerance.")

    per_share_risk = abs(entry_price - stop_loss_price)
    if per_share_risk <= 0:
        return {
            "recommended_shares": 0, "dollar_risk": 0, "risk_pct_used": 0,
            "stop_loss_price": stop_loss_price, "position_value": 0,
            "position_pct_of_portfolio": 0, "capped_by": "zero_stop_distance",
            "passes_risk_limits": False,
            "notes": ["Stop-loss equals entry price — cannot compute a safe size."],
        }

    risk_pct = RISK_PCT_BY_TOLERANCE.get(risk_tolerance, DEFAULT_RISK_PCT)
    dollar_risk_budget = portfolio_value * risk_pct

    # ── Portfolio-wide risk ceiling ──────────────────────────────────────
    remaining_risk_budget = max(0.0, (portfolio_value * max_portfolio_risk_pct) - open_ai_risk_value)
    capped_by = None
    if dollar_risk_budget > remaining_risk_budget:
        dollar_risk_budget = remaining_risk_budget
        capped_by = "portfolio_risk_limit"
        notes.append("Sized down: this trade's risk budget was capped by the portfolio-wide risk limit.")

    shares_by_risk = int(dollar_risk_budget // per_share_risk) if per_share_risk > 0 else 0

    # ── Position-size ceiling ────────────────────────────────────────────
    max_position_value = portfolio_value * max_position_pct
    remaining_position_room = max(0.0, max_position_value - existing_exposure_value)
    shares_by_position_cap = int(remaining_position_room // entry_price) if entry_price > 0 else 0

    recommended_shares = max(0, min(shares_by_risk, shares_by_position_cap))

    if shares_by_position_cap < shares_by_risk:
        capped_by = "max_position_size"
        notes.append("Sized down: hitting this position's max-size limit relative to the portfolio.")

    position_value = recommended_shares * entry_price
    actual_dollar_risk = recommended_shares * per_share_risk
    position_pct_of_portfolio = (position_value / portfolio_value) * 100 if portfolio_value > 0 else 0

    passes_risk_limits = recommended_shares > 0
    if recommended_shares == 0:
        notes.append("Recommended size rounded to 0 shares — risk/position limits leave no room for this trade.")

    return {
        "recommended_shares":        recommended_shares,
        "dollar_risk":               round(actual_dollar_risk, 2),
        "risk_pct_used":             round(risk_pct * 100, 2),
        "stop_loss_price":           stop_loss_price,
        "position_value":            round(position_value, 2),
        "position_pct_of_portfolio": round(position_pct_of_portfolio, 2),
        "capped_by":                 capped_by,
        "passes_risk_limits":        passes_risk_limits,
        "notes":                     notes,
    }


def check_risk_limits(
    portfolio_value:        float,
    proposal:                dict,
    max_position_pct:        float = MAX_POSITION_PCT_OF_PORTFOLIO,
) -> "tuple[bool, str]":
    """
    Final gate right before an auto-trade executes. calculate_position_size
    already caps the size, but this is a second, explicit check run at
    execution time — so if anything upstream changed (stale portfolio
    value, a hand-edited proposal, a race between two proposals) a trade
    still can't slip through unchecked.
    """
    if not proposal.get("passes_risk_limits"):
        return False, "Proposal was already flagged as failing risk limits."

    if proposal.get("recommended_shares", 0) <= 0:
        return False, "Recommended share count is zero."

    if portfolio_value <= 0:
        return False, "Portfolio value is zero or unknown."

    position_pct = proposal.get("position_pct_of_portfolio", 0)
    if position_pct > (max_position_pct * 100) + 0.01:  # small float tolerance
        return False, f"Position size {position_pct}% exceeds the {max_position_pct * 100:.0f}% max-position limit."

    return True, "OK"