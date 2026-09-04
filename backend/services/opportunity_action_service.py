import logging

from firebase_config import db
from services.opportunity_prepare_service import get_user_preferences
from services.trade_confirmation_service import create_confirmation, mark_confirmation_notified
from services.trade_execution_service import execute_trade_proposal
from services.notification_service import (
    notify_alert_only,
    notify_confirmation_required,
    notify_execution_result,
)
from trading.execution_modes import ALERT_ONLY_MODE, CONFIRMATION_MODE, AUTOMATED_MODE, get_execution_mode

logger = logging.getLogger(__name__)


def _all_user_ids() -> list[str]:
    return [doc.id for doc in db.collection("users").stream()]


def _target_user_ids(opportunity: dict) -> list[str]:
    decision = str(opportunity.get("decision") or opportunity.get("kind") or "BUY").upper()
    holder_user_ids = opportunity.get("holder_user_ids")
    if decision == "SELL" and isinstance(holder_user_ids, list):
        return [uid for uid in holder_user_ids if uid]
    return _all_user_ids()


def process_opportunity_for_user(opportunity: dict, user_id: str) -> dict:
    prefs = get_user_preferences(user_id)
    mode = get_execution_mode(prefs)
    analysis_id = opportunity.get("analysis_id")

    if mode == ALERT_ONLY_MODE:
        notify_alert_only(user_id=user_id, opportunity=opportunity)
        return {"user_id": user_id, "analysis_id": analysis_id, "mode": mode, "status": "ALERT_ONLY"}

    if mode == CONFIRMATION_MODE:
        created = create_confirmation(user_id, opportunity)
        confirmation = created.get("confirmation") or {}
        confirmation_id = confirmation.get("confirmation_id")
        if confirmation_id and confirmation.get("status") == "PENDING":
            delivered = notify_confirmation_required(
                user_id=user_id,
                opportunity=opportunity,
                confirmation=confirmation,
            )
            if delivered:
                try:
                    mark_confirmation_notified(user_id, confirmation_id)
                except Exception:
                    logger.exception("Failed to mark confirmation %s notified", confirmation_id)
        return {"user_id": user_id, "analysis_id": analysis_id, "mode": mode, "status": confirmation.get("status"), "confirmation_id": confirmation_id}

    if mode == AUTOMATED_MODE:
        from services.opportunity_prepare_service import prepare_opportunity_for_user

        prepared = prepare_opportunity_for_user(user_id=user_id, opportunity_entry=opportunity)
        proposal = prepared.get("proposal")
        if not proposal:
            result = {"ok": False, "status": prepared.get("status") or "RECOMMEND_ONLY", "error": prepared.get("reason") or prepared.get("error")}
        else:
            result = execute_trade_proposal(proposal, action="AUTO_OPPORTUNITY", user_id=user_id)
        notify_execution_result(user_id=user_id, opportunity=opportunity, result=result)
        return {"user_id": user_id, "analysis_id": analysis_id, "mode": mode, "status": result.get("status"), "result": result}

    return {"user_id": user_id, "analysis_id": analysis_id, "mode": mode, "status": "UNKNOWN_MODE"}


def dispatch_opportunity(opportunity: dict) -> list[str]:
    successful_ids = set()
    for user_id in _target_user_ids(opportunity):
        try:
            result = process_opportunity_for_user(opportunity, user_id)
            if result.get("status") not in (None, "UNKNOWN_MODE"):
                if opportunity.get("analysis_id"):
                    successful_ids.add(opportunity["analysis_id"])
        except Exception:
            logger.exception("Opportunity dispatch failed for %s / %s", opportunity.get("analysis_id"), user_id)
    return list(successful_ids)


def dispatch_opportunities(opportunities: list[dict]) -> list[str]:
    successful_ids = set()
    for opportunity in opportunities or []:
        for analysis_id in dispatch_opportunity(opportunity):
            successful_ids.add(analysis_id)
    return list(successful_ids)


def dispatch_buy_opportunity(opportunity: dict) -> list[str]:
    return dispatch_opportunity({**opportunity, "kind": "BUY", "decision": opportunity.get("decision", "BUY")})


def dispatch_sell_opportunity(opportunity: dict) -> list[str]:
    return dispatch_opportunity({**opportunity, "kind": "SELL", "decision": opportunity.get("decision", "SELL")})