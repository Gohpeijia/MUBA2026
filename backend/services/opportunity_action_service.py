import logging
from datetime import datetime, timezone

from firebase_config import db
from services.opportunity_prepare_service import get_user_preferences
from services.trade_confirmation_service import create_confirmation, mark_confirmation_notified
from services.trade_execution_service import execute_trade_proposal
from services.notification_service import (
    notify_alert_only,
    notify_confirmation_required,
    notify_execution_result,
)

from trading.execution_modes import ALERT_ONLY_MODE, CONFIRMATION_MODE, AUTOMATED_MODE, MANUAL_MODE, get_execution_mode

logger = logging.getLogger(__name__)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _all_user_ids() -> list[str]:
    return [doc.id for doc in db.collection("users").stream()]


def _target_user_ids(opportunity: dict) -> list[str]:
    decision = str(opportunity.get("decision") or opportunity.get("kind") or "BUY").upper()
    holder_user_ids = opportunity.get("holder_user_ids")
    if decision == "SELL" and isinstance(holder_user_ids, list):
        return [uid for uid in holder_user_ids if uid]
    return _all_user_ids()


def action_ref(user_id: str, analysis_id: str):
    action_id = analysis_id or f"missing-analysis-{now_iso()}"
    return (
        db.collection("users")
        .document(user_id)
        .collection("opportunity_actions")
        .document(action_id)
    )


def save_action_status(
    user_id: str,
    opportunity: dict,
    *,
    mode: str,
    status: str,
    result: dict = None,
    error: str = None,
) -> None:
    analysis_id = opportunity.get("analysis_id")
    payload = {
        "analysis_id": analysis_id,
        "user_id": user_id,
        "symbol": opportunity.get("symbol"),
        "decision": str(opportunity.get("decision") or opportunity.get("kind") or "").upper(),
        "kind": str(opportunity.get("kind") or opportunity.get("decision") or "").upper(),
        "confidence": opportunity.get("confidence"),
        "mode": mode,
        "status": status,
        "result": result,
        "error": error,
        "updated_at": now_iso(),
    }

    try:
        ref = action_ref(user_id, analysis_id)
        snap = ref.get()
        if not snap.exists:
            payload["created_at"] = payload["updated_at"]
        ref.set(payload, merge=True)
    except Exception:
        logger.exception(
            "Failed to save opportunity action status for user=%s analysis_id=%s",
            user_id,
            analysis_id,
        )


def process_opportunity_for_user(opportunity: dict, user_id: str) -> dict:
    prefs = get_user_preferences(user_id)
    mode = get_execution_mode(prefs)
    analysis_id = opportunity.get("analysis_id")
    decision = str(opportunity.get("decision") or opportunity.get("kind") or "").upper()
    logger.info(
        "Opportunity handler: user=%s analysis_id=%s symbol=%s decision=%s mode=%s",
        user_id,
        analysis_id,
        opportunity.get("symbol"),
        decision,
        mode,
    )

    if decision not in ("BUY", "SELL"):
        save_action_status(user_id, opportunity, mode=mode, status="ignored")
        return {"user_id": user_id, "analysis_id": analysis_id, "mode": mode, "status": "IGNORED"}

    if mode == MANUAL_MODE:
        save_action_status(user_id, opportunity, mode=mode, status="manual_ignored")
        return {"user_id": user_id, "analysis_id": analysis_id, "mode": mode, "status": "MANUAL_IGNORED"}

    if mode == ALERT_ONLY_MODE:
        notify_alert_only(user_id=user_id, opportunity=opportunity)
        save_action_status(user_id, opportunity, mode=mode, status="alert_only")
        return {"user_id": user_id, "analysis_id": analysis_id, "mode": mode, "status": "ALERT_ONLY"}

    if mode == CONFIRMATION_MODE:
        created = create_confirmation(user_id, opportunity)
        confirmation = created.get("confirmation") or {}
        confirmation_id = confirmation.get("confirmation_id")
        save_action_status(
            user_id,
            opportunity,
            mode=mode,
            status="pending_confirmation" if confirmation.get("status") == "PENDING" else str(confirmation.get("status") or "failed").lower(),
            result={"confirmation_id": confirmation_id},
            error=confirmation.get("error"),
        )
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

        save_action_status(user_id, opportunity, mode=mode, status="preparing")
        prepared = prepare_opportunity_for_user(user_id=user_id, opportunity_entry=opportunity)
        proposal = prepared.get("proposal")
        logger.info(
            "Auto opportunity prepared: user=%s analysis_id=%s status=%s reason=%s has_proposal=%s",
            user_id,
            analysis_id,
            prepared.get("status"),
            prepared.get("reason") or prepared.get("error"),
            bool(proposal),
        )
        if not proposal:
            result = {"ok": False, "status": prepared.get("status") or "RECOMMEND_ONLY", "error": prepared.get("reason") or prepared.get("error")}
        else:
            save_action_status(user_id, opportunity, mode=mode, status="executing")
            result = execute_trade_proposal(proposal, action="AUTO_OPPORTUNITY", user_id=user_id)
        logger.info(
            "Auto opportunity execution result: user=%s analysis_id=%s ok=%s status=%s error=%s reason=%s",
            user_id,
            analysis_id,
            result.get("ok"),
            result.get("status"),
            result.get("error"),
            result.get("reason"),
        )
        final_status = "executed" if result.get("ok") else "failed"
        save_action_status(
            user_id,
            opportunity,
            mode=mode,
            status=final_status,
            result=result,
            error=result.get("error") or result.get("reason"),
        )
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
