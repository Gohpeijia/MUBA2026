"""Read-only, user-scoped activity for the investment dashboard."""
from datetime import datetime, timezone

from firebase_config import db


def activity_item(action_id, action, confirmation=None):
    result = action.get("result") or {}
    confirmation = confirmation or {}
    proposal = confirmation.get("proposal_snapshot") or {}
    status = str(confirmation.get("status") or action.get("status") or "UNKNOWN").upper()
    expires_at = confirmation.get("expires_at")
    if status in ("PENDING", "NEEDS_RECONFIRMATION") and expires_at:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= datetime.now(timezone.utc):
            status = "EXPIRED"
    return {
        "id": action_id,
        "symbol": action.get("symbol"),
        "decision": action.get("decision") or action.get("kind"),
        "status": status,
        "reason": confirmation.get("error") or action.get("error") or result.get("reason") or result.get("message"),
        "quantity": proposal.get("shares", result.get("shares")),
        "price": proposal.get("price", result.get("price")),
        "updated_at": confirmation.get("acted_at") or action.get("updated_at"),
        "confirmation_id": confirmation.get("confirmation_id"),
    }


def list_opportunity_activity(user_id):
    user_ref = db.collection("users").document(user_id)
    docs = user_ref.collection("opportunity_actions").order_by(
        "updated_at", direction="DESCENDING"
    ).limit(30).stream()
    items = []
    for doc in docs:
        action = doc.to_dict() or {}
        confirmation_id = (action.get("result") or {}).get("confirmation_id")
        confirmation = None
        if confirmation_id:
            confirmation = user_ref.collection("trade_confirmations").document(confirmation_id).get().to_dict()
        items.append(activity_item(doc.id, action, confirmation))
    return items
