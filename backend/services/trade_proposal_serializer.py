from copy import deepcopy

from services.execution_router import PAPER_EQUITY, THETANUTS_OPTION, UNSUPPORTED


def _first_present(*values):
    for value in values:
        if value is not None:
            return value
    return None


def serialize_trade_proposal(proposal: dict | None, *, execution_target: str | None = None) -> dict | None:
    if not isinstance(proposal, dict):
        return proposal

    normalized = deepcopy(proposal)
    selector = normalized.get("selector")
    confirm_selector = normalized.get("confirm_selector")

    if isinstance(confirm_selector, dict) and not isinstance(selector, dict):
        selector = dict(confirm_selector)
        normalized["selector"] = selector
    elif isinstance(selector, dict):
        confirm_selector = dict(selector)
        normalized["confirm_selector"] = confirm_selector

    symbol = _first_present(
        normalized.get("symbol"),
        normalized.get("ticker"),
        normalized.get("underlying"),
        selector.get("underlying") if isinstance(selector, dict) else None,
    )
    if symbol:
        symbol = str(symbol).strip().upper()
        normalized["symbol"] = symbol
        normalized.setdefault("ticker", symbol)

    action = _first_present(
        normalized.get("decision"),
        normalized.get("action"),
        selector.get("decision") if isinstance(selector, dict) else None,
    )
    if action:
        action = str(action).upper().strip()
        normalized["decision"] = action
        normalized["action"] = action

    if execution_target:
        normalized["execution_target"] = execution_target
    else:
        normalized.setdefault("execution_target", THETANUTS_OPTION if isinstance(selector, dict) and selector.get("option_type") else PAPER_EQUITY)

    if isinstance(normalized.get("selector"), dict):
        if symbol:
            normalized["selector"].setdefault("underlying", symbol)
        if action:
            normalized["selector"].setdefault("decision", action)
        normalized["confirm_selector"] = dict(normalized["selector"])

    if normalized.get("execution_target") == PAPER_EQUITY:
        normalized.setdefault("asset_type", "EQUITY")
    elif normalized.get("execution_target") == THETANUTS_OPTION:
        normalized.setdefault("asset_type", "OPTION")
    elif normalized.get("execution_target") == UNSUPPORTED:
        normalized.setdefault("asset_type", "UNKNOWN")

    return normalized
