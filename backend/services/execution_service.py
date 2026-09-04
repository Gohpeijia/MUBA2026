from services.equity_execution_service import execute_equity_proposal
from services.execution_router import PAPER_EQUITY, THETANUTS_OPTION, UNSUPPORTED, resolve_execution_target
from services.trade_execution_service import execute_trade_proposal as execute_thetanuts_proposal


def _proposal_target(proposal: dict) -> str:
    if not isinstance(proposal, dict):
        return UNSUPPORTED

    explicit = proposal.get("execution_target")
    if explicit in (PAPER_EQUITY, THETANUTS_OPTION, UNSUPPORTED):
        return explicit

    selector = proposal.get("selector") if isinstance(proposal.get("selector"), dict) else {}
    if selector.get("option_type"):
        return THETANUTS_OPTION

    symbol = proposal.get("symbol") or proposal.get("ticker") or selector.get("underlying")
    asset_type = proposal.get("asset_type") or proposal.get("assetType")
    return resolve_execution_target(symbol, asset_type).get("execution_target", UNSUPPORTED)


def execute_prepared_proposal(*, user_id: str, proposal: dict, action: str = "CONFIRM") -> dict:
    target = _proposal_target(proposal)

    if target == PAPER_EQUITY:
        return execute_equity_proposal(user_id, proposal, action=action)

    if target == THETANUTS_OPTION:
        return execute_thetanuts_proposal(proposal, action=action, user_id=user_id)

    return {
        "ok": False,
        "status": "RECOMMEND_ONLY",
        "execution_target": UNSUPPORTED,
        "error": "No execution engine is configured for this proposal.",
    }
