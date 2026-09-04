import hashlib
import json
import logging
import os
import uuid
from copy import deepcopy
from datetime import datetime, timezone, timedelta

from firebase_admin import firestore

from firebase_config import db
from services.opportunity_prepare_service import prepare_opportunity_for_user
from services.trade_execution_service import execute_trade_proposal
from trading.execution_modes import CONFIRMATION_MODE

logger = logging.getLogger(__name__)

CONFIRMATION_TTL_MINUTES = int(os.getenv("CONFIRMATION_TTL_MINUTES", 30))
PENDING = "PENDING"
VALIDATING = "VALIDATING"
NEEDS_RECONFIRMATION = "NEEDS_RECONFIRMATION"
EXECUTING = "EXECUTING"
EXECUTED = "EXECUTED"
REJECTED = "REJECTED"
FAILED = "FAILED"
EXPIRED = "EXPIRED"
STALE = "STALE"
RECOMMEND_ONLY = "RECOMMEND_ONLY"

ACTIVE_CONFIRM_STATUSES = {PENDING, NEEDS_RECONFIRMATION}
TERMINAL_STATUSES = {EXECUTED, REJECTED, FAILED, EXPIRED, STALE, RECOMMEND_ONLY}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_dt(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def confirmation_ref(user_id: str, confirmation_id: str):
    return (
        db.collection("users")
        .document(user_id)
        .collection("trade_confirmations")
        .document(confirmation_id)
    )


def normalize_terms(proposal: dict) -> dict:
    selector = (proposal or {}).get("selector") or {}
    return {
        "underlying": selector.get("underlying") or proposal.get("underlying"),
        "option_type": selector.get("option_type") or proposal.get("option_type"),
        "strike": selector.get("strike") or proposal.get("strike"),
        "expiry": selector.get("expiry") or proposal.get("expiry"),
        "previewed_price": selector.get("previewed_price") or selector.get("price"),
        "collateral_usdc": selector.get("collateral_usdc") or proposal.get("collateral_usdc"),
        "decision": selector.get("decision") or proposal.get("decision") or proposal.get("action"),
        "reserve_price": selector.get("reserve_price") or proposal.get("reserve_price"),
        "quantity": selector.get("quantity") or selector.get("contracts"),
    }


def compute_terms_hash(proposal: dict) -> str | None:
    terms = normalize_terms(proposal)
    if not any(value is not None for value in terms.values()):
        return None
    payload = json.dumps(terms, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def public_confirmation(doc: dict) -> dict:
    if not isinstance(doc, dict):
        return {}
    public = deepcopy(doc)
    public["proposal"] = public.get("proposal_snapshot")
    public["selector"] = public.get("selector_snapshot")
    return public


def create_confirmation(user_id: str, opportunity: dict) -> dict:
    prepared = prepare_opportunity_for_user(user_id=user_id, opportunity_entry=opportunity)
    analysis_id = prepared.get("analysis_id") or opportunity.get("analysis_id")
    proposal = prepared.get("proposal")
    status = prepared.get("status")
    confirmation_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)
    expires_at = created_at + timedelta(minutes=CONFIRMATION_TTL_MINUTES)

    if status == "RECOMMEND_ONLY" or not proposal:
        record_status = RECOMMEND_ONLY
    else:
        record_status = PENDING

    selector = (proposal or {}).get("selector") if isinstance(proposal, dict) else None
    terms_hash = compute_terms_hash(proposal) if proposal else None

    record = {
        "confirmation_id": confirmation_id,
        "analysis_id": analysis_id,
        "user_id": user_id,
        "symbol": opportunity.get("symbol") or (proposal or {}).get("ticker") or (proposal or {}).get("underlying"),
        "decision": str(opportunity.get("decision") or (proposal or {}).get("decision") or (proposal or {}).get("action") or "").upper(),
        "kind": str(opportunity.get("kind") or opportunity.get("decision") or "BUY").upper(),
        "mode": CONFIRMATION_MODE,
        "status": record_status,
        "confidence": prepared.get("confidence") or opportunity.get("confidence"),
        "risk_level": prepared.get("risk_level") or opportunity.get("risk_level"),
        "spot_price": prepared.get("spot_price") or opportunity.get("spot_price"),
        "analysis_snapshot": prepared.get("analysis_snapshot") or opportunity.get("analysis") or opportunity.get("analysis_snapshot") or {},
        "proposal_snapshot": proposal,
        "selector_snapshot": selector,
        "proposal_version": 1,
        "terms_hash": terms_hash,
        "created_at": created_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "notified_at": None,
        "acted_at": None,
        "rejected_at": None,
        "confirmed_at": None,
        "execution_started_at": None,
        "execution_completed_at": None,
        "execution_status": None,
        "execution_result": None,
        "idempotency_key": f"{user_id}:{confirmation_id}",
        "error": prepared.get("reason") or prepared.get("error"),
    }

    confirmation_ref(user_id, confirmation_id).set(record)
    return {"success": True, "confirmation": public_confirmation(record), "http_status": 201}


def get_confirmation(user_id: str, confirmation_id: str) -> dict:
    snap = confirmation_ref(user_id, confirmation_id).get()
    if not snap.exists:
        return {"success": False, "status": "CONFIRMATION_NOT_FOUND", "error": "Confirmation not found.", "http_status": 404}
    return {"success": True, "confirmation": public_confirmation(snap.to_dict() or {}), "http_status": 200}


def reject_confirmation(user_id: str, confirmation_id: str) -> dict:
    ref = confirmation_ref(user_id, confirmation_id)
    transaction = db.transaction()

    @firestore.transactional
    def reject_txn(txn):
        snap = ref.get(transaction=txn)
        if not snap.exists:
            return None, {"success": False, "status": "CONFIRMATION_NOT_FOUND", "error": "Confirmation not found.", "http_status": 404}
        data = snap.to_dict() or {}
        status = data.get("status")
        if status in TERMINAL_STATUSES:
            return data, {"success": False, "status": "ALREADY_PROCESSED", "error": "This confirmation has already been processed.", "http_status": 409}
        now = now_iso()
        updates = {"status": REJECTED, "acted_at": now, "rejected_at": now, "execution_status": REJECTED}
        txn.update(ref, updates)
        data.update(updates)
        return data, {"success": True, "confirmation": public_confirmation(data), "http_status": 200}

    _, result = reject_txn(transaction)
    return result


def _mark_expired(ref, data: dict) -> dict:
    now = now_iso()
    updates = {"status": EXPIRED, "acted_at": now, "execution_status": EXPIRED, "error": "Confirmation expired."}
    ref.update(updates)
    data.update(updates)
    return {"success": False, "status": EXPIRED, "error": "Confirmation expired.", "confirmation": public_confirmation(data), "http_status": 410}


def _update_for_reconfirmation(ref, data: dict, execution: dict) -> dict:
    current = execution.get("current") or {}
    proposal = deepcopy(data.get("proposal_snapshot") or {})
    selector = proposal.setdefault("selector", {})
    selector.update(current)
    if data.get("decision"):
        selector["decision"] = data.get("decision")
    version = int(data.get("proposal_version") or 1) + 1
    terms_hash = compute_terms_hash(proposal)
    now = now_iso()
    updates = {
        "status": NEEDS_RECONFIRMATION,
        "proposal_snapshot": proposal,
        "selector_snapshot": selector,
        "proposal_version": version,
        "terms_hash": terms_hash,
        "execution_status": NEEDS_RECONFIRMATION,
        "execution_result": execution,
        "error": execution.get("reason") or execution.get("error"),
        "acted_at": None,
        "confirmed_at": None,
        "execution_started_at": None,
        "execution_completed_at": now,
    }
    ref.update(updates)
    data.update(updates)
    return {"success": False, "status": NEEDS_RECONFIRMATION, "error": updates["error"], "confirmation": public_confirmation(data), "http_status": 409}


def confirm_confirmation(user_id: str, confirmation_id: str, proposal_version: int = None, terms_hash: str = None) -> dict:
    ref = confirmation_ref(user_id, confirmation_id)
    transaction = db.transaction()

    @firestore.transactional
    def claim_txn(txn):
        snap = ref.get(transaction=txn)
        if not snap.exists:
            return None, {"success": False, "status": "CONFIRMATION_NOT_FOUND", "error": "Confirmation not found.", "http_status": 404}
        data = snap.to_dict() or {}
        status = data.get("status")
        if status in TERMINAL_STATUSES or status in {VALIDATING, EXECUTING}:
            return data, {"success": False, "status": "ALREADY_PROCESSED", "error": "This confirmation has already been processed.", "http_status": 409}
        if status not in ACTIVE_CONFIRM_STATUSES:
            return data, {"success": False, "status": "INVALID_STATE", "error": f"Confirmation is not confirmable from {status}.", "http_status": 409}
        expires_at = parse_dt(data.get("expires_at"))
        if expires_at and datetime.now(timezone.utc) >= expires_at:
            updates = {"status": EXPIRED, "acted_at": now_iso(), "execution_status": EXPIRED, "error": "Confirmation expired."}
            txn.update(ref, updates)
            data.update(updates)
            return data, {"success": False, "status": EXPIRED, "error": "Confirmation expired.", "confirmation": public_confirmation(data), "http_status": 410}
        if proposal_version is not None and int(proposal_version) != int(data.get("proposal_version") or 1):
            return data, {"success": False, "status": "STALE_TERMS", "error": "Confirmation terms changed. Refresh before confirming.", "confirmation": public_confirmation(data), "http_status": 409}
        if terms_hash is not None and terms_hash != data.get("terms_hash"):
            return data, {"success": False, "status": "STALE_TERMS", "error": "Confirmation terms changed. Refresh before confirming.", "confirmation": public_confirmation(data), "http_status": 409}
        now = now_iso()
        updates = {"status": EXECUTING, "acted_at": now, "confirmed_at": now, "execution_started_at": now, "execution_status": EXECUTING}
        txn.update(ref, updates)
        data.update(updates)
        return data, None

    data, early = claim_txn(transaction)
    if early:
        return early

    proposal = data.get("proposal_snapshot")
    if not proposal:
        return mark_confirmation_failed(user_id, confirmation_id, "No proposal snapshot is available.", data=data)

    execution = execute_trade_proposal(proposal, action="CONFIRMATION_LINK", user_id=user_id)
    status = execution.get("status") or (EXECUTED if execution.get("ok") else FAILED)

    if status == NEEDS_RECONFIRMATION:
        return _update_for_reconfirmation(ref, data, execution)
    if status == STALE:
        final_status = STALE
        success = False
        http_status = 409
    elif execution.get("ok"):
        final_status = status if status == "DRY_RUN_OK" else EXECUTED
        success = True
        http_status = 200
    else:
        final_status = FAILED
        success = False
        http_status = 422

    now = now_iso()
    updates = {
        "status": final_status,
        "execution_status": final_status,
        "execution_result": execution,
        "execution_completed_at": now,
        "error": execution.get("error") or execution.get("reason"),
    }
    ref.update(updates)
    data.update(updates)
    return {"success": success, "status": final_status, "confirmation": public_confirmation(data), "execution": execution, "error": updates["error"], "http_status": http_status}


def mark_confirmation_failed(user_id: str, confirmation_id: str, error: str, data: dict = None) -> dict:
    ref = confirmation_ref(user_id, confirmation_id)
    if data is None:
        snap = ref.get()
        data = snap.to_dict() if snap.exists else {}
    now = now_iso()
    updates = {"status": FAILED, "execution_status": FAILED, "execution_completed_at": now, "error": error}
    ref.update(updates)
    data.update(updates)
    return {"success": False, "status": FAILED, "error": error, "confirmation": public_confirmation(data), "http_status": 422}


def mark_confirmation_notified(user_id: str, confirmation_id: str) -> None:
    confirmation_ref(user_id, confirmation_id).update({"notified_at": now_iso()})