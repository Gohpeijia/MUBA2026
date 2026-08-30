# ai_routes.py
from flask import Blueprint, request, jsonify, g
from ai_agent import AIAgent
from firebase_config import db
from security import require_auth
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
ai_bp = Blueprint('ai', __name__)
agent = AIAgent()

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
            user_goal    = tabung_goal
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