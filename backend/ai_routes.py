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
        force = bool(data.get("force"))

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
            if collateral_usdc is None or float(collateral_usdc) <= 0:
                return jsonify({
                    "success": False,
                    "error": "BUY requires a positive collateral_usdc amount.",
                }), 400

            collateral_usdc = float(collateral_usdc)

        else:
            # SELL does not use collateral_usdc.
            collateral_usdc = None

        # ---------------------------------------------------------------
        # 1. Server-side copilot mode check
        # ---------------------------------------------------------------
        preferences = _get_preferences(user_id)

        copilot_mode = preferences.get(
            "riskCopilotMode",
            "Suggest actions, I confirm each one"
        )

        if copilot_mode != "Suggest actions, I confirm each one":
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
                    if (o.get("type") or o.get("optionType")) == option_type
                    and o.get("strike") == expected_strike
                    and (
                        o.get("expiry")
                        or o.get("expiryTimestamp")
                    ) == expected_expiry
                ),
                None,
            )

            rolled_off = current_order is None

            if rolled_off:
                current_order = orders["data"][0]

            current_type = (
                current_order.get("type")
                or current_order.get("optionType")
            )

            current_strike = current_order.get("strike")

            current_expiry = (
                current_order.get("expiry")
                or current_order.get("expiryTimestamp")
            )

            current_price = (
                current_order.get("price")
                or current_order.get("premium")
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

            _log_thetanuts_trade({
                "ticker": ticker,
                "decision": "BUY",
                "action": data.get("action", "CONFIRM"),
                "status": execution_result["status"],
                "amount_usdc": collateral_usdc,
                "order_index": execution_result.get("order_index"),
                "tx_hash": execution_result.get("tx_hash"),
                "wallet_tradable_usdc": tradable_usdc,
                "dry_run": FORCE_DRY_RUN,
                "error": execution_result.get("error"),
            })

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

        if not live_position.get("found"):
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

        _log_thetanuts_trade({
            "ticker": ticker,
            "decision": "SELL",
            "action": data.get("action", "CONFIRM"),
            "status": close_result["status"],
            "amount_usdc": None,
            "order_index": None,
            "reserve_price": reserve_price,
            "tx_hash": close_result.get("tx_hash"),
            "wallet_tradable_usdc": wallet_balance.get(
                "tradable_usdc"
            ),
            "dry_run": FORCE_DRY_RUN,
            "position_source": position_source,
            "position_address": position_address,
            "error": close_result.get("error"),
        })

        # ---------------------------------------------------------------
        # 7B. If dry-run, don't pretend the position closed
        # ---------------------------------------------------------------
        if FORCE_DRY_RUN:
            return jsonify({
                "success": True,
                "data": {
                    "decision": "SELL",
                    "status": close_result["status"],
                    "execution": close_result,
                    "position_verified_closed": False,
                    "dry_run": True,
                },
            })

        # ---------------------------------------------------------------
        # 8B. IMPORTANT:
        # A successful CLI call / tx submission does NOT by itself mean
        # the position is actually gone.
        #
        # Re-query the live position.
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
                    "SELL transaction was submitted, but the live "
                    "position could not be verified as closed. "
                    "Firestore was NOT changed."
                ),
                "data": {
                    "decision": "SELL",
                    "execution": close_result,
                    "verification": verification,
                },
            }), 409

        if not verification.get("closed"):
            return jsonify({
                "success": False,
                "error": (
                    "SELL transaction completed, but the live "
                    "Thetanuts position is still open. "
                    "Firestore was NOT changed."
                ),
                "data": {
                    "decision": "SELL",
                    "execution": close_result,
                    "verification": verification,
                },
            }), 409

        # ---------------------------------------------------------------
        # 9B. Position is confirmed closed on-chain.
        #
        # DO NOT calculate wallet balance manually.
        # Read it again from Base.
        # ---------------------------------------------------------------
        wallet_after = trader.get_wallet_balance()

        # ---------------------------------------------------------------
        # 10B. Only NOW should Firestore position state be changed.
        #
        # IMPORTANT:
        # Insert your existing Firestore position-removal/update logic
        # here. Do not delete/update it before verification above.
        # ---------------------------------------------------------------

        return jsonify({
            "success": True,
            "data": {
                "decision": "SELL",
                "status": close_result["status"],
                "execution": close_result,
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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /history  —  called on page load to repopulate the chat window
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@ai_bp.route('/history', methods=['GET'])
@require_auth
def get_history():
    try:
        user_id    = g.uid
        session_id = request.args.get('session_id') or datetime.now().strftime("%Y-%m-%d")
        limit      = int(request.args.get('limit', 20))

        history = _load_history(user_id, session_id, limit=limit)

        return jsonify({
            "success":    True,
            "session_id": session_id,
            "history":    history,
        })

    except Exception as e:
        print(f"❌ [History Error] {str(e)}")
        return jsonify({"success": False, "error": "Could not load history."}), 500

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DELETE /history  —  clear chat button
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@ai_bp.route('/history', methods=['DELETE'])
@require_auth
def clear_history():
    try:
        user_id    = g.uid
        session_id = (request.json or {}).get('session_id') or datetime.now().strftime("%Y-%m-%d")

        docs  = _messages_ref(user_id, session_id).get()
        batch = db.batch()
        for doc in docs:
            batch.delete(doc.reference)
        batch.commit()

        (
            db.collection("users")
              .document(user_id)
              .collection("chat_sessions")
              .document(session_id)
              .delete()
        )

        return jsonify({"success": True, "cleared": session_id})

    except Exception as e:
        print(f"❌ [Clear History Error] {str(e)}")
        return jsonify({"success": False, "error": "Could not clear history."}), 500