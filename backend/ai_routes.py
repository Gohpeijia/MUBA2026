# ai_routes.py
from flask import Blueprint, request, jsonify, g
from ai_agent import AIAgent, trader, _log_thetanuts_trade, FORCE_DRY_RUN
from trading.validator import validate_confirmation
from firebase_config import db
from security import require_auth
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
ai_bp = Blueprint('ai', __name__)
agent = AIAgent()

# How far the live book's premium is allowed to drift from what the user
# was shown in the preview before we treat it as a material change and
# stop to re-confirm rather than silently filling at a different price.
PRICE_MATERIAL_CHANGE_PCT = 0.03  # 3%
CONFIRMATION_MODE = "Suggest actions, I confirm each one"
AUTOMATED_MODE = "Fully automated recommendations"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  INTERNAL HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _messages_ref(user_id: str, session_id: str):
    """Returns the Firestore reference to the messages subcollection."""
    return (
        db.collection("users")
          .document(user_id)
          .collection("chat_sessions")
          .document(session_id)
          .collection("messages")
    )

def _save_message(user_id: str, session_id: str, role: str, content: str, ticker: str = None):
    """Appends one message and bumps the session's last_updated timestamp."""
    now = datetime.now().isoformat()

    _messages_ref(user_id, session_id).add({
        "role":      role,
        "content":   content,
        "ticker":    ticker,
        "timestamp": now,
    })

    (
        db.collection("users")
          .document(user_id)
          .collection("chat_sessions")
          .document(session_id)
          .set({"last_updated": now}, merge=True)
    )

def _load_history(user_id: str, session_id: str, limit: int = 20) -> list:
    """Returns the last `limit` messages, oldest-first."""
    docs = (
        _messages_ref(user_id, session_id)
        .order_by("timestamp")
        .limit_to_last(limit)
        .get()
    )
    return [
        {"role": d.get("role"), "content": d.get("content")}
        for d in docs
    ]

def _get_preferences(user_id: str) -> dict:
    """Loads user preferences from the existing users document."""
    doc = db.collection("users").document(user_id).get()
    if doc.exists:
        return doc.to_dict().get("preference", {})
    return {}


def _execution_mode(preferences: dict) -> str:
    """
    Normalize the saved preference used by both chat and confirmation.

    The current Preferences screen stores riskCopilotMode. The boolean
    confirmation_required is also accepted for older profiles so a user
    cannot accidentally get a confirmation modal after choosing automation.
    """
    mode = preferences.get("riskCopilotMode")
    if mode in (CONFIRMATION_MODE, AUTOMATED_MODE, "Alert me only, I act manually"):
        return mode
    if preferences.get("confirmation_required") is False:
        return AUTOMATED_MODE
    return CONFIRMATION_MODE


def _order_field(order: dict, *names):
    """Return the first populated field from a normalized/raw order."""
    for name in names:
        value = order.get(name)
        if value is not None:
            return value
    return None


def _parse_positive_float(value, field_name: str):
    """Parse user/client supplied numeric input without truthy-string surprises."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None, f"{field_name} must be a positive number."

    if parsed <= 0:
        return None, f"{field_name} must be greater than 0."

    return parsed, None


def _same_contract(order: dict, option_type, strike, expiry) -> bool:
    """Match a live order by stable contract identity, never by index."""
    order_type = _order_field(order, "option_type", "optionType", "type")
    order_strike = _order_field(order, "strike", "strikePrice", "strike_price")
    order_expiry = _order_field(
        order,
        "expiry",
        "expiryTimestamp",
        "expiration",
        "expirationTimestamp",
    )

    try:
        normalized_expiry = trader._normalize_expiry(order_expiry)
        expected_normalized_expiry = trader._normalize_expiry(expiry)
        same_strike = abs(float(order_strike) - float(strike)) <= 1e-8
    except (TypeError, ValueError):
        return False

    return (
        str(order_type).strip().upper() == str(option_type).strip().upper()
        and same_strike
        and normalized_expiry == expected_normalized_expiry
    )


def _execute_automated_trade(proposal: dict) -> dict:
    """
    Execute a proposal for the explicit fully-automated preference.

    BUY still re-reads the live order book and validates the risk gate.
    SELL still re-reads the live position and only closes an RFQ position.
    FORCE_DRY_RUN remains the final switch that prevents all blockchain
    writes while preserving the live preview path.
    """
    selector = (proposal or {}).get("selector") or {}
    decision = str(
        selector.get("decision")
        or proposal.get("decision")
        or ""
    ).upper().strip()

    ticker = selector.get("underlying") or proposal.get("underlying")
    option_type = selector.get("option_type") or proposal.get("option_type")
    strike = selector.get("strike") or proposal.get("strike")
    expiry = selector.get("expiry") or proposal.get("expiry")

    if not ticker or not option_type or strike is None or expiry is None:
        return {
            "ok": False,
            "status": "FAILED",
            "error": "Automated trade was blocked: incomplete stable contract selector.",
        }

    if decision == "BUY":
        collateral_usdc = selector.get("collateral_usdc")
        if collateral_usdc is None:
            collateral_usdc = proposal.get("collateral_usdc")

        collateral_usdc, collateral_error = _parse_positive_float(
            collateral_usdc,
            "collateral_usdc",
        )
        if collateral_error:
            return {
                "ok": False,
                "status": "FAILED",
                "error": f"Automated BUY was blocked: {collateral_error}",
            }

        orders = trader.get_live_orders(
            underlying=ticker,
            option_type=option_type,
        )
        if not orders.get("ok"):
            return {
                "ok": False,
                "status": "FAILED",
                "error": orders.get("error") or "Unable to read the live OptionBook.",
            }

        current_order = next(
            (
                order for order in orders.get("data", [])
                if isinstance(order, dict)
                and _same_contract(order, option_type, strike, expiry)
            ),
            None,
        )
        if current_order is None:
            return {
                "ok": False,
                "status": "FAILED",
                "error": (
                    "Automated BUY was blocked: the approved contract is "
                    "no longer available on the live OptionBook."
                ),
            }

        wallet = trader.get_wallet_balance()
        if not wallet.get("ok"):
            return {
                "ok": False,
                "status": "FAILED",
                "error": wallet.get("error") or "Unable to read wallet balance.",
            }

        valid, reason = validate_confirmation(
            selector=selector,
            wallet=wallet,
            collateral_usdc=collateral_usdc,
            current_order=current_order,
        )
        if not valid:
            return {
                "ok": False,
                "status": "FAILED",
                "error": f"Trade blocked by risk validator: {reason}",
            }

        execution = trader.execute_fill(
            collateral_usdc=collateral_usdc,
            underlying=str(ticker).upper(),
            option_type=str(option_type).upper(),
            strike=strike,
            expiry=expiry,
            dry_run=FORCE_DRY_RUN,
        )
        if not FORCE_DRY_RUN and execution.get("ok"):
            _log_thetanuts_trade({
                "ticker": ticker,
                "decision": "BUY",
                "action": "AUTO",
                "status": execution.get("status"),
                "amount_usdc": collateral_usdc,
                "tx_hash": execution.get("tx_hash"),
                "approval_tx_hash": execution.get("approval_tx_hash"),
                "fill_tx_hash": execution.get("fill_tx_hash"),
                "dry_run": False,
                "error": execution.get("error"),
            })
        return execution

    if decision == "SELL":
        live_position = trader.find_position(
            underlying=ticker,
            option_type=option_type,
            strike=strike,
            expiry=expiry,
        )
        position = live_position.get("position") if live_position.get("ok") else None
        if not live_position.get("ok") or position is None:
            return {
                "ok": False,
                "status": "FAILED",
                "error": (
                    live_position.get("error")
                    or "Automated SELL was blocked: no matching live position."
                ),
            }

        if trader.get_position_source(position) != "rfq":
            return {
                "ok": False,
                "status": "FAILED",
                "error": (
                    "Automated SELL was blocked: only live RFQ position "
                    "closing is supported."
                ),
            }

        position_address = trader.get_position_address(position)
        if not position_address:
            return {
                "ok": False,
                "status": "FAILED",
                "error": "Automated SELL was blocked: position address is missing.",
            }

        close_result = trader.close_rfq_position(
            position_address=position_address,
            reserve_price=selector.get("reserve_price") or proposal.get("reserve_price"),
            dry_run=FORCE_DRY_RUN,
        )
        if not close_result.get("ok") or FORCE_DRY_RUN:
            return close_result

        tx_hash = close_result.get("tx_hash")
        transaction = trader.wait_for_transaction(tx_hash=tx_hash)
        if not transaction.get("ok"):
            return {
                "ok": False,
                "status": "FAILED",
                "tx_hash": tx_hash,
                "receipt_confirmed": transaction.get("confirmed", False),
                "error": transaction.get("error") or "Automated SELL was not confirmed.",
                "transaction": transaction,
            }

        verification = trader.verify_position_closed(
            underlying=ticker,
            option_type=option_type,
            strike=strike,
            expiry=expiry,
        )
        if not verification.get("ok") or not verification.get("closed"):
            return {
                "ok": False,
                "status": "FAILED",
                "tx_hash": tx_hash,
                "receipt_confirmed": True,
                "error": (
                    "Automated SELL was confirmed on Base, but the live "
                    "position could not be verified as closed."
                ),
                "transaction": transaction,
                "verification": verification,
            }

        result = {
            **close_result,
            "ok": True,
            "status": "EXECUTED",
            "tx_hash": tx_hash,
            "receipt_confirmed": True,
            "transaction": transaction,
            "verification": verification,
        }
        _log_thetanuts_trade({
            "ticker": ticker,
            "decision": "SELL",
            "action": "AUTO",
            "status": result["status"],
            "tx_hash": tx_hash,
            "dry_run": False,
            "position_address": position_address,
            "error": None,
        })
        return result

    return {
        "ok": False,
        "status": "FAILED",
        "error": f"Unsupported automated trade decision: {decision or 'missing'}.",
    }

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /chat  —  send a message, get AI response
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@ai_bp.route('/chat', methods=['POST'])
@require_auth
def chat_with_agent():
    try:
        data         = request.json
        user_message = data.get('message') or data.get('text')
        ticker       = data.get('ticker')
        page_context = data.get('pageContext', 'Unknown Page')
        session_id   = data.get('session_id') or datetime.now().strftime("%Y-%m-%d")
        user_id      = g.uid

        if not user_message:
            return jsonify({"success": False, "error": "Message is required."}), 400

        print(f"🤖 [API] User={user_id} | Session={session_id} | Page={page_context} | Message={user_message}")

        # 1. Fetch user metadata profile context
        user_doc = db.collection("users").document(user_id).get()
        user_data = user_doc.to_dict() if user_doc.exists else {}
        preferences  = _get_preferences(user_id)
        tabung_goal  = user_data.get("tabung_goal", None)

        # ── START NEW: Fetch Portfolio Data ──
        portfolio_doc = db.collection("users").document(user_id).collection("portfolio").document("summary").get()
        portfolio_data = portfolio_doc.to_dict() if portfolio_doc.exists else {
            "total_value": 0.0,
            "positions": {},
            "open_ai_risk_value": 0.0
        }
        # ── END NEW ──

        # 2. Extract chat history directly from frontend payload instead of Firestore
        chat_history = data.get('chat_history', [])
        
        # Guardrails: limit history payload size to last 20 items max
        if len(chat_history) > 20:
            chat_history = chat_history[-20:]

        # 3. Run the AI agent
        result = agent.process(
            user_input   = user_message,
            ticker       = ticker,
            chat_history = chat_history,
            page_context = page_context,
            preferences  = preferences,
            user_goal    = tabung_goal,
            portfolio    = portfolio_data
        )

        if result.get("status") == "ERROR":
            return jsonify({"success": False, "error": result["final_advice"]}), 503

        # Respect the user's execution preference at the server boundary.
        # Confirmation mode leaves the proposal for the explicit confirm
        # action. Fully automated mode executes the proposal immediately
        # (or produces the same safe dry-run preview while FORCE_DRY_RUN is
        # enabled). Alert-only mode never exposes an executable action to
        # the frontend.
        if result.get("trade_status") == "EXECUTABLE":
            copilot_mode = _execution_mode(preferences)
            proposal = result.get("trade_proposal")

            if copilot_mode == AUTOMATED_MODE and proposal:
                auto_execution = _execute_automated_trade(proposal)
                result["auto_execution"] = auto_execution
                result["trade_proposal"] = None
                result["trade_status"] = auto_execution.get("status", "FAILED")
                result["trade_reason"] = auto_execution.get(
                    "error",
                    "Automated trade execution completed.",
                )

            elif copilot_mode != CONFIRMATION_MODE:
                result["trade_proposal"] = None
                result["trade_status"] = "RECOMMEND_ONLY"
                result["trade_reason"] = (
                    "Alert-only mode is enabled. No trade was executed."
                )

        # NOTE: Firestore persistence removed here to ensure browser-scoped privacy constraints

        return jsonify({
            "success":    True,
            "session_id": session_id,
            "data":       result,
        })

    except Exception as e:
        print(f"❌ [API Error] {str(e)}")
        return jsonify({"success": False, "error": "Internal server error."}), 500

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /confirm-trade  —  user approves a PENDING_CONFIRMATION proposal
#
#  Only reachable from "Suggest actions, I confirm each one" mode. The
#  book is re-checked fresh here — never against the stale preview from
#  /chat — because the order the user saw could have moved or rolled off
#  by the time they click Confirm. If the current best match differs
#  materially (contract terms changed, or price moved beyond the
#  tolerance below), this returns the updated details instead of filling,
#  so the frontend can show the user what changed and ask them to
#  confirm again. Pass "force": true once the user has seen that and
#  still wants to proceed.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@ai_bp.route('/confirm-trade', methods=['POST'])
@require_auth
def confirm_trade():
    try:
        data = request.json or {}
        user_id = g.uid

        selector = data.get("selector") or {}
        force = data.get("force") is True

        ticker = selector.get("underlying")
        option_type = selector.get("option_type")
        expected_strike = selector.get("strike")
        expected_expiry = selector.get("expiry")
        expected_price = selector.get("previewed_price")
        collateral_usdc = selector.get("collateral_usdc")
        reserve_price = selector.get("reserve_price")

        # ---------------------------------------------------------------
        # 0. Determine whether this is BUY or SELL
        # ---------------------------------------------------------------
        decision = (
            selector.get("decision")
            or data.get("decision")
            or selector.get("action")
            or data.get("action")
        )

        if not decision:
            return jsonify({
                "success": False,
                "error": "Trade decision is required.",
            }), 400

        decision = str(decision).upper().strip()

        if decision not in ("BUY", "SELL"):
            return jsonify({
            "success": False,
            "error": f"Unsupported trade decision: {decision}",
        }), 400

        # BUY requires collateral.
        # SELL does NOT — the collateral already belongs to the
        # existing option position.
        if (
            not ticker
            or not option_type
            or expected_strike is None
            or not expected_expiry
        ):
            return jsonify({
                "success": False,
                "error": "Incomplete trade selector — nothing to confirm.",
            }), 400

        if decision == "BUY":
            collateral_usdc, collateral_error = _parse_positive_float(
                collateral_usdc,
                "collateral_usdc",
            )
            if collateral_error:
                return jsonify({
                    "success": False,
                    "error": f"BUY requires valid collateral_usdc: {collateral_error}",
                }), 400

        else:
            # SELL does not use collateral_usdc.
            collateral_usdc = None

        # ---------------------------------------------------------------
        # 1. Server-side copilot mode check
        # ---------------------------------------------------------------
        preferences = _get_preferences(user_id)

        copilot_mode = _execution_mode(preferences)

        if copilot_mode != CONFIRMATION_MODE:
            return jsonify({
                "success": False,
                "error": (
                    f"Trade confirmation isn't used in "
                    f"'{copilot_mode}' mode."
                ),
            }), 400

        # ===============================================================
        # BUY
        # ===============================================================
        if decision == "BUY":

            # -----------------------------------------------------------
            # 2A. Re-fetch live order book
            # -----------------------------------------------------------
            orders = trader.get_live_orders(
                underlying=ticker,
                option_type=option_type,
            )

            if not orders.get("ok") or not orders.get("data"):
                return jsonify({
                    "success": False,
                    "error": (
                        orders.get("error")
                        or "No live orders available for this contract anymore."
                    ),
                }), 409

            # -----------------------------------------------------------
            # 3A. Find exact contract user approved
            # -----------------------------------------------------------
            current_order = next(
                (
                    o for o in orders["data"]
                    if _same_contract(
                        o,
                        option_type,
                        expected_strike,
                        expected_expiry,
                    )
                ),
                None,
            )

            rolled_off = current_order is None

            if rolled_off:
                replacement_order = orders["data"][0]
                return jsonify({
                    "success": True,
                    "data": {
                        "status": "NEEDS_RECONFIRMATION",
                        "reason": (
                            "That order rolled off the book — "
                            "please review and confirm the current order."
                        ),
                        "previous": selector,
                        "current": {
                            "underlying": ticker,
                            "option_type": _order_field(
                                replacement_order,
                                "option_type",
                                "optionType",
                                "type",
                            ),
                            "strike": _order_field(
                                replacement_order,
                                "strike",
                                "strikePrice",
                                "strike_price",
                            ),
                            "expiry": _order_field(
                                replacement_order,
                                "expiry",
                                "expiryTimestamp",
                                "expiration",
                                "expirationTimestamp",
                            ),
                            "price": _order_field(
                                replacement_order,
                                "price_per_contract",
                                "price",
                                "premium",
                                "unitPrice",
                            ),
                        },
                    },
                })

            current_type = _order_field(
                current_order,
                "option_type",
                "optionType",
                "type",
            )
            current_strike = _order_field(
                current_order,
                "strike",
                "strikePrice",
                "strike_price",
            )
            current_expiry = _order_field(
                current_order,
                "expiry",
                "expiryTimestamp",
                "expiration",
                "expirationTimestamp",
            )
            current_price = _order_field(
                current_order,
                "price_per_contract",
                "price",
                "premium",
                "unitPrice",
            )
            # -----------------------------------------------------------
            # 4A. Detect material change
            # -----------------------------------------------------------
            material_change = (
                rolled_off
                or current_strike != expected_strike
                or current_expiry != expected_expiry
            )

            if not material_change and expected_price and current_price:
                try:
                    material_change = (
                        abs(
                            float(current_price)
                            - float(expected_price)
                        )
                        / float(expected_price)
                        > PRICE_MATERIAL_CHANGE_PCT
                    )
                except (
                    TypeError,
                    ValueError,
                    ZeroDivisionError,
                ):
                    pass

            if material_change and not force:
                return jsonify({
                    "success": True,
                    "data": {
                        "status": "NEEDS_RECONFIRMATION",
                        "reason": (
                            "That order rolled off the book — "
                            "this is the closest current order instead."
                            if rolled_off
                            else
                            "Price or contract terms moved since "
                            "you approved this proposal."
                        ),
                        "previous": selector,
                        "current": {
                            "underlying": ticker,
                            "option_type": current_type,
                            "strike": current_strike,
                            "expiry": current_expiry,
                            "price": current_price,
                        },
                    },
                })

            # -----------------------------------------------------------
            # 5A. Re-check BUY funds immediately before execution
            # -----------------------------------------------------------
            wallet_balance = trader.get_wallet_balance()

            tradable_usdc = wallet_balance.get(
                "tradable_usdc",
                0.0,
            )

            if (
                not wallet_balance.get("ok")
                or tradable_usdc < 0.5
                or collateral_usdc > tradable_usdc
            ):
                return jsonify({
                    "success": False,
                    "error": (
                        "Insufficient tradable USDC "
                        "to fill this order right now."
                    ),
                }), 409

            # -----------------------------------------------------------
            # 6A. Risk validator
            # -----------------------------------------------------------
            ok, validation_reason = validate_confirmation(
                selector=selector,
                wallet=wallet_balance,
                collateral_usdc=collateral_usdc,
                current_order=current_order,
            )

            if not ok:
                return jsonify({
                    "success": False,
                    "error": (
                        "Trade blocked by risk validator: "
                        f"{validation_reason}"
                    ),
                }), 409

            # -----------------------------------------------------------
            # 7A. Execute BUY
            # -----------------------------------------------------------
            execution_result = trader.execute_fill(
                collateral_usdc=collateral_usdc,
                underlying=ticker,
                option_type=current_type,
                strike=current_strike,
                expiry=current_expiry,
                dry_run=FORCE_DRY_RUN,
            )

            if not FORCE_DRY_RUN:
                _log_thetanuts_trade({
                    "ticker": ticker,
                    "decision": "BUY",
                    "action": data.get("action", "CONFIRM"),
                    "status": execution_result["status"],
                    "amount_usdc": collateral_usdc,
                    "order_index": None,
                    "tx_hash": execution_result.get("tx_hash"),
                    "approval_tx_hash": execution_result.get("approval_tx_hash"),
                    "fill_tx_hash": execution_result.get("fill_tx_hash"),
                    "wallet_tradable_usdc": tradable_usdc,
                    "dry_run": False,
                    "error": execution_result.get("error"),
                })

            if not execution_result.get("ok"):
                return jsonify({
                    "success": False,
                    "error": (
                        execution_result.get("error")
                        or "BUY transaction failed."
                    ),
                    "data": {
                        "decision": "BUY",
                        "status": execution_result.get("status", "FAILED"),
                        "execution": execution_result,
                        "dry_run": FORCE_DRY_RUN,
                    },
                }), 409

            return jsonify({
                "success": True,
                "data": {
                    "decision": "BUY",
                    "status": execution_result["status"],
                    "execution": execution_result,
                },
            })

        # ===============================================================
        # SELL
        # ===============================================================

        # ---------------------------------------------------------------
        # 2B. SELL MUST use the live position, not the order book
        # ---------------------------------------------------------------
        live_position = trader.find_position(
            underlying=ticker,
            option_type=option_type,
            strike=expected_strike,
            expiry=expected_expiry,
        )

        if not live_position.get("ok"):
            return jsonify({
                "success": False,
                "error": (
                    live_position.get("error")
                    or "Unable to verify the live option position."
                ),
            }), 409

        if live_position.get("position") is None:
            return jsonify({
                "success": False,
                "error": (
                    "No matching live Thetanuts position exists. "
                    "SELL was blocked."
                ),
            }), 409

        position = live_position.get("position") or {}

        # ---------------------------------------------------------------
        # 3C. Identify the actual live position source/address
        # ---------------------------------------------------------------
        position_source = trader.get_position_source(position)

        if position_source != "rfq":
            return jsonify({
                "success": False,
                "error": (
                    f"SELL found a {position_source.upper()} position. "
                    "The current SELL implementation only supports "
                    "RFQ position closing. Book positions are blocked "
                    "until the correct OptionBook exit mechanism is "
                    "implemented."
                ),
            }), 409

        position_address = trader.get_position_address(position)

        if not position_address:
            return jsonify({
                "success": False,
                "error": (
                    "The live RFQ position has no option contract address. "
                    "SELL was blocked."
                ),
            }), 409

        # ---------------------------------------------------------------
        # 3B. SELL quantity safety
        #
        # The current RFQ close implementation closes the entire
        # position. Therefore a SELL request must either:
        #
        #   1. omit quantity entirely -> close the entire live position
        #   2. explicitly request the entire live position
        #
        # Partial SELL is blocked until partial-close execution exists.
        # ---------------------------------------------------------------
        requested_quantity = (
            selector.get("quantity")
            if selector.get("quantity") is not None
            else selector.get("contracts")
        )

        if requested_quantity is not None:
            try:
                requested_quantity = float(requested_quantity)

                if requested_quantity <= 0:
                    return jsonify({
                        "success": False,
                        "error": "SELL quantity must be greater than zero.",
                    }), 400

            except (TypeError, ValueError):
                return jsonify({
                    "success": False,
                    "error": "Invalid SELL quantity.",
                }), 400

            position_quantity = (
                position.get("quantity")
                if position.get("quantity") is not None
                else (
                    position.get("contracts")
                    if position.get("contracts") is not None
                    else position.get("size")
                )
            )

            if position_quantity is None:
                return jsonify({
                    "success": False,
                    "error": (
                        "The live position quantity could not be determined. "
                        "SELL was blocked to prevent an accidental full close."
                    ),
                }), 409

            try:
                position_quantity = float(position_quantity)
            except (TypeError, ValueError):
                return jsonify({
                    "success": False,
                    "error": (
                        "The live position has an invalid quantity. "
                        "SELL was blocked."
                    ),
                }), 409

            if abs(requested_quantity - position_quantity) > 1e-8:
                return jsonify({
                    "success": False,
                    "error": (
                        "Partial SELL is not supported by the current "
                        "RFQ close implementation. "
                        f"Requested {requested_quantity}, "
                        f"live position contains {position_quantity}."
                    ),
                }), 409

        # ---------------------------------------------------------------
        # 5B. Check gas before attempting RFQ close
        # ---------------------------------------------------------------
        wallet_balance = trader.get_wallet_balance()

        if not wallet_balance.get("ok"):
            return jsonify({
                "success": False,
                "error": (
                    wallet_balance.get("error")
                    or "Unable to read wallet balance."
                ),
            }), 409

        if not wallet_balance.get("has_gas"):
            return jsonify({
                "success": False,
                "error": (
                    "Insufficient Base ETH for transaction gas. "
                    "SELL was blocked."
                ),
            }), 409

        # ---------------------------------------------------------------
        # 6B. Close the RFQ position
        # ---------------------------------------------------------------
        close_result = trader.close_rfq_position(
            position_address=position_address,
            reserve_price=reserve_price,
            dry_run=FORCE_DRY_RUN,
        )

        
        if not close_result.get("ok"):
            if not FORCE_DRY_RUN:
                _log_thetanuts_trade({
                    "ticker": ticker,
                    "decision": "SELL",
                    "action": data.get("action", "CONFIRM"),
                    "status": close_result.get("status", "FAILED"),
                    "amount_usdc": None,
                    "order_index": None,
                    "reserve_price": reserve_price,
                    "tx_hash": close_result.get("tx_hash"),
                    "wallet_tradable_usdc": wallet_balance.get("tradable_usdc"),
                    "dry_run": False,
                    "position_source": position_source,
                    "position_address": position_address,
                    "error": close_result.get("error"),
                })

            return jsonify({
                "success": False,
                "error": (
                    close_result.get("error")
                    or "The RFQ close operation failed."
                ),
                "data": {
                    "decision": "SELL",
                    "execution": close_result,
                    "position_verified_closed": False,
                    "dry_run": FORCE_DRY_RUN,
                },
            }), 409

                # ---------------------------------------------------------------
        # 7B. If dry-run, don't pretend the position closed
        # ---------------------------------------------------------------
        if FORCE_DRY_RUN:
            return jsonify({
                "success": True,
                "data": {
                    "decision": "SELL",
                    "status": close_result.get("status"),
                    "execution": close_result,
                    "position_verified_closed": False,
                    "dry_run": True,
                },
            })

        # ---------------------------------------------------------------
        # 8B. Wait for blockchain confirmation
        # ---------------------------------------------------------------
        tx_hash = close_result.get("tx_hash")

        if not tx_hash:
            return jsonify({
                "success": False,
                "error": (
                    "SELL was submitted without a transaction hash. "
                    "The position was NOT verified as closed. "
                    "Firestore was NOT changed."
                ),
                "data": {
                    "decision": "SELL",
                    "execution": close_result,
                    "position_verified_closed": False,
                    "dry_run": False,
                },
            }), 409

        transaction = trader.wait_for_transaction(
            tx_hash=tx_hash,
            timeout=120,
            poll_latency=2.0,
        )

        if not transaction.get("ok"):
            return jsonify({
                "success": False,
                "error": (
                    transaction.get("error")
                    or "SELL transaction was not successfully confirmed on Base."
                ),
                "data": {
                    "decision": "SELL",
                    "execution": close_result,
                    "transaction": transaction,
                    "position_verified_closed": False,
                    "dry_run": False,
                },
            }), 409

        # ---------------------------------------------------------------
        # 9B. Confirm that the live position actually disappeared
        # ---------------------------------------------------------------
        verification = trader.verify_position_closed(
            underlying=ticker,
            option_type=option_type,
            strike=expected_strike,
            expiry=expected_expiry,
        )

        if not verification.get("ok"):
            return jsonify({
                "success": False,
                "error": (
                    "SELL transaction was confirmed on Base, but the live "
                    "position could not be verified as closed. "
                    "Firestore was NOT changed."
                ),
                "data": {
                    "decision": "SELL",
                    "execution": close_result,
                    "transaction": transaction,
                    "verification": verification,
                    "position_verified_closed": False,
                    "dry_run": False,
                },
            }), 409

        if not verification.get("closed"):
            return jsonify({
                "success": False,
                "error": (
                    "SELL transaction was confirmed on Base, but the live "
                    "Thetanuts position is still open. "
                    "Firestore was NOT changed."
                ),
                "data": {
                    "decision": "SELL",
                    "execution": close_result,
                    "transaction": transaction,
                    "verification": verification,
                    "position_verified_closed": False,
                    "dry_run": False,
                },
            }), 409

        # ---------------------------------------------------------------
        # 10B. Position is confirmed closed on-chain.
        #
        # Read the wallet again from Base.
        # ---------------------------------------------------------------
        wallet_after = trader.get_wallet_balance()

        # ---------------------------------------------------------------
        # 11B. Firestore update goes HERE.
        #
        # Do not update Firestore before the on-chain position has
        # disappeared.
        # ---------------------------------------------------------------

        return jsonify({
            "success": True,
            "data": {
                "decision": "SELL",
                "status": close_result.get("status"),
                "execution": close_result,
                "transaction": transaction,
                "verification": verification,
                "position_verified_closed": True,
                "wallet_after": wallet_after,
                "dry_run": False,
            },
        })

    except Exception as e:
        print(f"❌ [Confirm Trade Error] {str(e)}")
        return jsonify({
            "success": False,
            "error": "Could not confirm trade.",
        }), 500