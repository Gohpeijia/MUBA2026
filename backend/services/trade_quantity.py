import re
from typing import Any


def parse_positive_int(value: Any, field_name: str = "quantity") -> tuple[int | None, str | None]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None, f"{field_name} must be a positive integer."
    if parsed <= 0:
        return None, f"{field_name} must be greater than 0."
    return parsed, None


def parse_explicit_trade_quantity(user_input: str, action: str | None) -> int | None:
    """Parse share count from commands such as `sell 5 NVDA` or `sell NVDA 5`."""
    if action not in ("BUY", "SELL"):
        return None
    text = (user_input or "").strip()
    patterns = (
        rf"\b{action.lower()}\s+(-?\d+)\s+(?:shares?\s+(?:of\s+)?)?[A-Za-z0-9.^-]+\b",
        rf"\b{action.lower()}\s+[A-Za-z0-9.^-]+\s+(-?\d+)\s*(?:shares?)?\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def recommended_quantity(analysis: dict) -> int | None:
    """Return the first usable AI sizing recommendation, if one exists."""
    analysis = analysis if isinstance(analysis, dict) else {}
    candidates = (
        analysis.get("recommended_shares"),
        analysis.get("recommended_quantity"),
        analysis.get("sell_quantity"),
        analysis.get("quantity"),
        (analysis.get("risk_sizing") or {}).get("recommended_shares")
        if isinstance(analysis.get("risk_sizing"), dict)
        else None,
    )
    for candidate in candidates:
        parsed, error = parse_positive_int(candidate)
        if not error:
            return parsed
    return None


def select_sell_quantity(analysis: dict, requested_quantity: Any, held_shares: int) -> tuple[int | None, str, str | None]:
    """User quantity wins, then AI sizing, then the safe one-share default."""
    if requested_quantity is not None:
        shares, error = parse_positive_int(requested_quantity)
        if error:
            return None, "USER", error
        if shares > held_shares:
            return None, "USER", f"You requested {shares} share(s), but only hold {held_shares}."
        return shares, "USER", None

    recommended = recommended_quantity(analysis)
    if recommended is not None:
        return min(recommended, held_shares), "AI_RECOMMENDED", None

    return min(1, held_shares), "DEFAULT", None
