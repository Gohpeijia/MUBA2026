from flask import Blueprint, jsonify, request, g
from firebase_admin import firestore

from firebase_config import db
from security import require_auth

notifications_bp = Blueprint("notifications", __name__, url_prefix="/api/notifications")


@notifications_bp.route("/register-token", methods=["POST"])
@require_auth
def register_fcm_token():
    payload = request.get_json(silent=True) or {}
    token = str(payload.get("token") or "").strip()

    if not token:
        return jsonify({
            "success": False,
            "error": "FCM token is required.",
        }), 400

    platform = str(payload.get("platform") or "web").strip() or "web"

    db.collection("users").document(g.uid).set({
        "fcm_tokens": firestore.ArrayUnion([token]),
        "lastFcmRegistration": {
            "platform": platform,
            "userAgent": str(payload.get("userAgent") or ""),
            "updatedAt": firestore.SERVER_TIMESTAMP,
        },
    }, merge=True)

    return jsonify({
        "success": True,
        "registered": True,
    }), 200
