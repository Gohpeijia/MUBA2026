import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

from firebase_admin import messaging, firestore

logger = logging.getLogger(__name__)

# Repeated SELL alerts are suppressed for this long unless the SELL
# condition materially worsens.
SELL_ALERT_COOLDOWN_MINUTES = 360  # 6 hours

# A SELL signal that becomes materially stronger can bypass the cooldown.
SELL_CONFIDENCE_REALERT_DELTA = 0.10

# A price deterioration of this percentage can bypass the cooldown.
SELL_PRICE_REALERT_PERCENT = 5.0


def _collect_broadcast_tokens(db):
    """
    Opted-in users regardless of holdings.

    Used for BUY opportunities, which are market-wide discoveries.
    """
    target_tokens = []
    token_to_user = {}

    users_query = db.collection("users").stream()

    for user_doc in users_query:
        data = user_doc.to_dict() or {}
        prefs = data.get("preference", {})

        if prefs.get("confirmation_required") is True:
            fcm_tokens = data.get("fcm_tokens", [])

            if isinstance(fcm_tokens, list):
                for token in fcm_tokens:
                    if isinstance(token, str) and token.strip():
                        token = token.strip()

                        target_tokens.append(token)
                        token_to_user[token] = user_doc.id

    return list(set(target_tokens)), token_to_user


def _collect_holder_tokens(db, holder_user_ids: List[str]):
    """
    Collect FCM tokens only from the users who currently hold the asset.

    Used for SELL opportunities.
    """
    target_tokens = []
    token_to_user = {}

    for user_id in holder_user_ids:
        try:
            doc = (
                db.collection("users")
                .document(user_id)
                .get()
            )
        except Exception:
            logger.exception(
                "Failed to load user %s for SELL notification",
                user_id,
            )
            continue

        if not doc.exists:
            continue

        data = doc.to_dict() or {}
        prefs = data.get("preference", {})

        if prefs.get("confirmation_required") is not True:
            continue

        fcm_tokens = data.get("fcm_tokens", [])

        if not isinstance(fcm_tokens, list):
            continue

        for token in fcm_tokens:
            if isinstance(token, str) and token.strip():
                token = token.strip()

                target_tokens.append(token)
                token_to_user[token] = user_id

    return list(set(target_tokens)), token_to_user


def _parse_datetime(value):
    """
    Converts stored ISO timestamps into timezone-aware datetimes.
    """
    if not value:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)

        return value

    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )

            if parsed.tzinfo is None:
                parsed = parsed.replace(
                    tzinfo=timezone.utc
                )

            return parsed

        except ValueError:
            return None

    return None


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sell_price_deteriorated(
    current_price,
    previous_price,
):
    """
    Returns True when the current price has fallen materially
    compared with the price at the previous SELL alert.

    Example:

        Previous alert: BTC = 100,000
        Current price:   BTC = 94,000

        Drop = 6%
        → material deterioration
        → re-alert allowed
    """
    current = _to_float(current_price)
    previous = _to_float(previous_price)

    if current is None or previous is None:
        return False

    if previous <= 0:
        return False

    price_drop_percent = (
        (previous - current)
        / previous
        * 100
    )

    return price_drop_percent >= SELL_PRICE_REALERT_PERCENT


def _sell_condition_changed_materially(
    state,
    opportunity,
):
    """
    Determines whether a repeated SELL signal is materially stronger.

    A re-alert is allowed when either:

    1. SELL confidence increases significantly, OR
    2. price has fallen significantly since the previous alert.
    """
    previous_confidence = _to_float(
        state.get("confidence")
    )

    current_confidence = _to_float(
        opportunity.get("confidence")
    )

    confidence_improved = False

    if (
        previous_confidence is not None
        and current_confidence is not None
    ):
        confidence_improved = (
            current_confidence - previous_confidence
            >= SELL_CONFIDENCE_REALERT_DELTA
        )

    price_deteriorated = _sell_price_deteriorated(
        opportunity.get("spot_price"),
        state.get("spot_price"),
    )

    return (
        confidence_improved
        or price_deteriorated
    )


def _get_sell_notification_state(
    db,
    user_id: str,
    symbol: str,
):
    """
    Reads the last SELL notification state for one user + symbol.

    State is deliberately keyed by user and symbol rather than
    analysis_id because every scanner run creates a new analysis_id.
    """
    state_id = f"{user_id}_{symbol}"

    ref = (
        db.collection("sell_notification_state")
        .document(state_id)
    )

    snapshot = ref.get()

    if not snapshot.exists:
        return None

    return snapshot.to_dict() or {}


def _should_send_sell_notification(
    db,
    user_id: str,
    opportunity: Dict[str, Any],
):
    """
    Decides whether a SELL opportunity should notify this particular user.

    First SELL:
        → notify

    Same SELL during cooldown:
        → suppress

    After cooldown:
        → still suppress unless condition materially worsened

    Materially stronger SELL:
        → notify even during cooldown
    """
    symbol = str(
        opportunity.get("symbol", "")
    ).strip().upper()

    if not symbol:
        return False

    state = _get_sell_notification_state(
        db,
        user_id,
        symbol,
    )

    # First SELL alert for this user/symbol.
    if not state:
        return True

    last_alert_at = _parse_datetime(
        state.get("last_alert_at")
    )

    if last_alert_at is None:
        return True

    now = datetime.now(timezone.utc)

    cooldown_until = (
        last_alert_at
        + timedelta(
            minutes=SELL_ALERT_COOLDOWN_MINUTES
        )
    )

    # Material deterioration/stronger signal can re-alert
    # immediately without waiting for the cooldown.
    if _sell_condition_changed_materially(
        state,
        opportunity,
    ):
        return True

    # Otherwise suppress repeated alerts during cooldown.
    if now < cooldown_until:
        logger.info(
            "Suppressing repeated SELL notification "
            "for %s / %s — cooldown active.",
            user_id,
            symbol,
        )
        return False

    # Cooldown expired, but condition did not materially worsen.
    #
    # We intentionally keep suppressing here. The next notification
    # should be triggered by a materially changed SELL condition,
    # rather than sending the same alert every 6 hours forever.
    logger.info(
        "Suppressing repeated SELL notification "
        "for %s / %s — no material change.",
        user_id,
        symbol,
    )

    return False


def _record_sell_notification(
    db,
    user_id: str,
    opportunity: Dict[str, Any],
):
    """
    Records the last successful SELL alert for this user/symbol.
    """
    symbol = str(
        opportunity.get("symbol", "")
    ).strip().upper()

    if not symbol:
        return

    state_id = f"{user_id}_{symbol}"

    ref = (
        db.collection("sell_notification_state")
        .document(state_id)
    )

    ref.set(
        {
            "user_id": user_id,
            "symbol": symbol,
            "last_alert_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "confidence": _to_float(
                opportunity.get("confidence")
            ),
            "spot_price": _to_float(
                opportunity.get("spot_price")
            ),
            "analysis_id": opportunity.get(
                "analysis_id"
            ),
            "decision": "SELL",
        },
        merge=True,
    )


def _filter_sell_opportunity_for_notification(
    db,
    opportunity: Dict[str, Any],
):
    """
    Returns:

        {
            user_id: True/False
        }

    for the users who should receive this particular SELL alert.
    """
    holder_user_ids = opportunity.get(
        "holder_user_ids",
        [],
    )

    if not isinstance(holder_user_ids, list):
        return {}

    eligible_users = {}

    for user_id in holder_user_ids:
        if not user_id:
            continue

        if _should_send_sell_notification(
            db,
            user_id,
            opportunity,
        ):
            eligible_users[user_id] = True

    return eligible_users


def notify_users_of_opportunities(
    opportunities: List[Dict[str, Any]]
) -> List[str]:
    """
    Sends notifications for a batch of opportunities.

    BUY:
        Broadcast to every opted-in user.

    SELL:
        Notify only current holders of the symbol.
        Repeated SELL signals are suppressed using per-user/symbol
        cooldown state.

    Returns analysis_ids successfully delivered to at least one device.
    """
    if not opportunities:
        return []

    successful_analysis_ids = []

    try:
        db = firestore.client()

        # BUY broadcast pool is loaded only when required.
        broadcast_tokens = None
        broadcast_token_to_user = None

        for opportunity in opportunities:
            analysis_id = opportunity.get(
                "analysis_id"
            )

            symbol = opportunity.get(
                "symbol",
                "N/A",
            )

            decision = str(
                opportunity.get(
                    "decision",
                    "N/A",
                )
            ).upper()

            confidence = _to_float(
                opportunity.get("confidence")
            ) or 0.0

            confidence_pct = int(
                confidence * 100
            )

            holder_user_ids = opportunity.get(
                "holder_user_ids"
            )

            is_sell = (
                decision == "SELL"
                and isinstance(
                    holder_user_ids,
                    list,
                )
            )

            if not analysis_id:
                continue

            # ---------------------------------------------------------
            # SELL
            # ---------------------------------------------------------
            if is_sell:
                eligible_users = (
                    _filter_sell_opportunity_for_notification(
                        db,
                        opportunity,
                    )
                )

                if not eligible_users:
                    logger.info(
                        "SELL opportunity %s for %s "
                        "has no users eligible for notification.",
                        analysis_id,
                        symbol,
                    )
                    continue

                target_tokens = []
                token_to_user = {}

                # Re-collect holder tokens. This is intentional:
                # ownership and opt-in status should be current at
                # notification time, not only at scan time.
                holder_tokens, holder_token_to_user = (
                    _collect_holder_tokens(
                        db,
                        list(eligible_users.keys()),
                    )
                )

                for token in holder_tokens:
                    user_id = holder_token_to_user.get(
                        token
                    )

                    if user_id in eligible_users:
                        target_tokens.append(token)
                        token_to_user[token] = user_id

                target_tokens = list(
                    set(target_tokens)
                )

                if not target_tokens:
                    logger.info(
                        "No eligible holder tokens for SELL "
                        "opportunity %s (%s).",
                        analysis_id,
                        symbol,
                    )
                    continue

            # ---------------------------------------------------------
            # BUY
            # ---------------------------------------------------------
            else:
                if broadcast_tokens is None:
                    (
                        broadcast_tokens,
                        broadcast_token_to_user,
                    ) = _collect_broadcast_tokens(db)

                target_tokens = broadcast_tokens
                token_to_user = (
                    broadcast_token_to_user
                )

                if not target_tokens:
                    logger.info(
                        "No users/tokens found for "
                        "opportunity notification."
                    )
                    continue

            title = (
                "🔔 Portfolio alert"
                if is_sell
                else "🔔 New investment opportunity"
            )

            body = (
                f"{symbol} — {decision} — "
                f"{confidence_pct}% confidence. "
                f"Tap to review."
            )

            chunk_size = 500
            total_success = 0
            successful_users = set()
            tokens_to_remove = []

            for i in range(
                0,
                len(target_tokens),
                chunk_size,
            ):
                chunk = target_tokens[
                    i:i + chunk_size
                ]

                message = (
                    messaging.MulticastMessage(
                        notification=(
                            messaging.Notification(
                                title=title,
                                body=body,
                            )
                        ),
                        data={
                            "analysis_id": str(
                                analysis_id
                            ),
                            "symbol": str(symbol),
                            "decision": str(
                                decision
                            ),
                        },
                        tokens=chunk,
                    )
                )

                try:
                    response = (
                        messaging
                        .send_each_for_multicast(
                            message
                        )
                    )

                    total_success += (
                        response.success_count
                    )

                    for idx, resp in enumerate(
                        response.responses
                    ):
                        if resp.success:
                            user_id = (
                                token_to_user.get(
                                    chunk[idx]
                                )
                            )

                            if user_id:
                                successful_users.add(
                                    user_id
                                )

                        else:
                            err_code = (
                                resp.exception.code
                                if resp.exception
                                else ""
                            )

                            if err_code in (
                                "UNREGISTERED",
                                "INVALID_ARGUMENT",
                            ):
                                tokens_to_remove.append(
                                    chunk[idx]
                                )

                except Exception:
                    logger.exception(
                        "FCM multicast batch failed "
                        "for %s",
                        analysis_id,
                    )

            # Remove permanently invalid tokens.
            if tokens_to_remove:
                _cleanup_invalid_tokens(
                    db,
                    tokens_to_remove,
                    token_to_user,
                )

            if total_success > 0:
                successful_analysis_ids.append(
                    analysis_id
                )

                # Only record SELL state after FCM successfully
                # delivered to at least one device for that user.
                if is_sell:
                    for user_id in successful_users:
                        if user_id in eligible_users:
                            try:
                                _record_sell_notification(
                                    db,
                                    user_id,
                                    opportunity,
                                )
                            except Exception:
                                logger.exception(
                                    "Failed to record SELL "
                                    "notification state for "
                                    "%s / %s",
                                    user_id,
                                    symbol,
                                )

                logger.info(
                    "Successfully notified %d devices "
                    "for %s",
                    total_success,
                    analysis_id,
                )

            else:
                logger.warning(
                    "Zero successful FCM deliveries "
                    "for %s",
                    analysis_id,
                )

    except Exception:
        logger.exception(
            "Fatal error in notification service"
        )

    return successful_analysis_ids




def _get_user_tokens(db, user_id: str) -> List[str]:
    try:
        doc = db.collection("users").document(user_id).get()
    except Exception:
        logger.exception("Failed to load FCM tokens for user %s", user_id)
        return []

    if not doc.exists:
        return []

    data = doc.to_dict() or {}
    tokens = data.get("fcm_tokens", [])
    if not isinstance(tokens, list):
        return []

    return list({token.strip() for token in tokens if isinstance(token, str) and token.strip()})


def _send_to_user(user_id: str, title: str, body: str, data: Dict[str, Any]) -> bool:
    db = firestore.client()
    tokens = _get_user_tokens(db, user_id)
    if not tokens:
        logger.info("No FCM tokens for user %s", user_id)
        return False

    message = messaging.MulticastMessage(
        notification=messaging.Notification(title=title, body=body),
        data={key: str(value) for key, value in (data or {}).items() if value is not None},
        tokens=tokens,
    )

    try:
        response = messaging.send_each_for_multicast(message)
    except Exception:
        logger.exception("FCM send failed for user %s", user_id)
        return False

    tokens_to_remove = []
    for idx, resp in enumerate(response.responses):
        if resp.success:
            continue
        err_code = resp.exception.code if resp.exception else ""
        if err_code in ("UNREGISTERED", "INVALID_ARGUMENT"):
            tokens_to_remove.append(tokens[idx])

    if tokens_to_remove:
        _cleanup_invalid_tokens(db, tokens_to_remove, {token: user_id for token in tokens_to_remove})

    return response.success_count > 0


def notify_alert_only(user_id: str, opportunity: Dict[str, Any]) -> bool:
    symbol = opportunity.get("symbol", "N/A")
    decision = str(opportunity.get("decision", "N/A")).upper()
    confidence = _to_float(opportunity.get("confidence")) or 0.0
    return _send_to_user(
        user_id=user_id,
        title="Portfolio alert" if decision == "SELL" else "New investment opportunity",
        body=f"{symbol} {decision} signal detected. {int(confidence * 100)}% AI confidence.",
        data={
            "type": "OPPORTUNITY_ALERT",
            "analysis_id": opportunity.get("analysis_id"),
            "symbol": symbol,
            "decision": decision,
            "route": "/dashboard",
        },
    )


def notify_confirmation_required(user_id: str, opportunity: Dict[str, Any], confirmation: Dict[str, Any]) -> bool:
    symbol = opportunity.get("symbol") or confirmation.get("symbol") or "N/A"
    decision = str(opportunity.get("decision") or confirmation.get("decision") or "N/A").upper()
    confirmation_id = confirmation.get("confirmation_id")
    route = f"/opportunities/confirm/{confirmation_id}"
    confidence = _to_float(opportunity.get("confidence") or confirmation.get("confidence")) or 0.0

    if decision == "SELL":
        body = f"{symbol} SELL signal detected. Review your current position before closing it."
    else:
        body = f"{symbol} BUY opportunity detected. {int(confidence * 100)}% AI confidence. Review before execution."

    return _send_to_user(
        user_id=user_id,
        title="Trade confirmation required",
        body=body,
        data={
            "type": "TRADE_CONFIRMATION",
            "confirmation_id": confirmation_id,
            "analysis_id": opportunity.get("analysis_id") or confirmation.get("analysis_id"),
            "symbol": symbol,
            "decision": decision,
            "route": route,
        },
    )


def notify_execution_result(user_id: str, opportunity: Dict[str, Any], result: Dict[str, Any]) -> bool:
    symbol = opportunity.get("symbol", "N/A")
    decision = str(opportunity.get("decision", "N/A")).upper()
    status = (result or {}).get("status", "FAILED")
    ok = bool((result or {}).get("ok"))
    title = "Trade execution completed" if ok else "Trade execution blocked"
    body = f"{symbol} {decision}: {status}."
    if (result or {}).get("error"):
        body = f"{body} {result.get('error')}"

    return _send_to_user(
        user_id=user_id,
        title=title,
        body=body,
        data={
            "type": "TRADE_EXECUTION_RESULT",
            "analysis_id": opportunity.get("analysis_id"),
            "symbol": symbol,
            "decision": decision,
            "status": status,
            "route": "/dashboard",
        },
    )

def _cleanup_invalid_tokens(
    db,
    tokens_to_remove: List[str],
    token_to_user: Dict[str, str],
):
    """
    Removes invalid FCM tokens from user documents.
    """
    try:
        user_removals = {}

        for token in tokens_to_remove:
            user_id = token_to_user.get(token)

            if user_id:
                user_removals.setdefault(
                    user_id,
                    [],
                ).append(token)

        for user_id, tokens in user_removals.items():
            (
                db.collection("users")
                .document(user_id)
                .update(
                    {
                        "fcm_tokens": firestore.ArrayRemove(
                            tokens
                        )
                    }
                )
            )

            logger.info(
                "Removed %d invalid FCM token(s) "
                "for user %s",
                len(tokens),
                user_id,
            )

    except Exception:
        logger.exception(
            "Failed to cleanup invalid FCM tokens"
        )