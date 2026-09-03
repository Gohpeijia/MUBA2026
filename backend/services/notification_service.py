import logging
from typing import List, Dict, Any
import firebase_admin
from firebase_admin import messaging, firestore

logger = logging.getLogger(__name__)


def notify_users_of_opportunities(opportunities: List[Dict[str, Any]]) -> List[str]:
    """
    Broadcasts notifications to users who have confirmation_required=True.
    Returns a list of analysis_ids that were successfully sent to at least one token.
    """
    if not opportunities:
        return []

    successful_analysis_ids = []

    try:
        db = firestore.client()
        # Find eligible users: confirmation_required == True
        # For a production app with a large userbase, this would need an index.
        users_query = db.collection("users").stream()
        
        target_tokens = []
        token_to_user = {}  # Map token to user_id to handle cleanup

        for user_doc in users_query:
            data = user_doc.to_dict() or {}
            prefs = data.get("preference", {})
            
            # Only opt-in users
            if prefs.get("confirmation_required") is True:
                fcm_tokens = data.get("fcm_tokens", [])
                if isinstance(fcm_tokens, list):
                    for token in fcm_tokens:
                        if isinstance(token, str) and token.strip():
                            target_tokens.append(token.strip())
                            token_to_user[token.strip()] = user_doc.id

        if not target_tokens:
            logger.info("No users/tokens found for opportunity notification.")
            return []

        # Deduplicate tokens just in case
        target_tokens = list(set(target_tokens))

        for opp in opportunities:
            analysis_id = opp.get("analysis_id")
            symbol = opp.get("symbol", "N/A")
            decision = opp.get("decision", "N/A")
            confidence = opp.get("confidence", 0)
            confidence_pct = int(confidence * 100) if isinstance(confidence, (float, int)) else 0

            if not analysis_id:
                continue

            title = "🔔 New investment opportunity"
            body = f"{symbol} — {decision} — {confidence_pct}% confidence. Tap to review."
            
            # Send in chunks of 500 (FCM limit)
            chunk_size = 500
            total_success = 0
            tokens_to_remove = []

            for i in range(0, len(target_tokens), chunk_size):
                chunk = target_tokens[i:i + chunk_size]
                
                message = messaging.MulticastMessage(
                    notification=messaging.Notification(
                        title=title,
                        body=body,
                    ),
                    data={
                        "analysis_id": str(analysis_id),
                        "symbol": str(symbol),
                        "decision": str(decision),
                    },
                    tokens=chunk
                )
                
                try:
                    response = messaging.send_each_for_multicast(message)
                    total_success += response.success_count
                    
                    # Token cleanup
                    for idx, resp in enumerate(response.responses):
                        if not resp.success:
                            # e.g., Unregistered, InvalidArgument
                            err_code = resp.exception.code if resp.exception else ""
                            if err_code in ('UNREGISTERED', 'INVALID_ARGUMENT'):
                                failed_token = chunk[idx]
                                tokens_to_remove.append(failed_token)
                except Exception as e:
                    logger.error(f"FCM multicast batch failed for {analysis_id}: {e}")

            # Remove permanently failed tokens from users
            if tokens_to_remove:
                _cleanup_invalid_tokens(db, tokens_to_remove, token_to_user)

            if total_success > 0:
                successful_analysis_ids.append(analysis_id)
                logger.info(f"Successfully notified {total_success} devices for {analysis_id}")
            else:
                logger.warning(f"Zero successful FCM deliveries for {analysis_id}")

    except Exception as e:
        logger.exception(f"Fatal error in notification service: {e}")

    return successful_analysis_ids


def _cleanup_invalid_tokens(db, tokens_to_remove: List[str], token_to_user: Dict[str, str]):
    """Removes invalid FCM tokens from user documents."""
    try:
        # Group by user_id
        user_removals = {}
        for t in tokens_to_remove:
            uid = token_to_user.get(t)
            if uid:
                user_removals.setdefault(uid, []).append(t)
                
        for uid, tokens in user_removals.items():
            db.collection("users").document(uid).update({
                "fcm_tokens": firestore.ArrayRemove(tokens)
            })
            logger.info(f"Removed {len(tokens)} invalid FCM token(s) for user {uid}")
    except Exception as e:
        logger.error(f"Failed to cleanup invalid FCM tokens: {e}")
