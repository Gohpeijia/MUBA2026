from flask import Blueprint, jsonify, request, g
from security import require_auth
from firebase_config import db
from zakat_service import get_current_nisab, get_current_gold_price
from datetime import datetime

zakat_bp = Blueprint('zakat', __name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. SERVE LIVE NISAB (For frontend calculations)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@zakat_bp.route('/nisab', methods=['GET'])
@require_auth
def fetch_nisab():
    try:
        gold_price = get_current_gold_price()
        current_nisab = gold_price * 85
        
        return jsonify({
            "success": True,
            "data": {
                "gold_price": round(gold_price, 2),     # RM per gram
                "nisab_value": round(current_nisab, 2)
            }
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. GET ZAKAT DATA (To populate frontend on page load)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@zakat_bp.route('/data', methods=['GET'])
@require_auth
def get_zakat_data():
    try:
        user_id = g.uid
        user_doc = db.collection('users').document(user_id).get()
        
        if not user_doc.exists:
            return jsonify({"success": True, "data": {}})
            
        user_data = user_doc.to_dict()
        zakat_profile = user_data.get('zakat_profile', {})
        
        return jsonify({
            "success": True,
            "data": zakat_profile
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. SAVE ZAKAT DATA (Zero Math, strictly saving frontend state)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@zakat_bp.route('/save-data', methods=['POST'])
@require_auth
def save_zakat_data():
    try:
        data = request.json
        user_id = g.uid
        
        # Define allowed keys exactly as you requested
        allowed_keys = [
            'nisab_amount', 'assets', 'liabilities', 
            'net_amount', 'zakat_due', 'haul_date', 'zakat_goals'
        ]
        
        # Filter the incoming data
        payload = {k: v for k, v in data.items() if k in allowed_keys}
        
        # Use SET with MERGE to prevent crashes for new users
        db.collection('users').document(user_id).set({
            "zakat_profile": payload,
            "zakat_last_updated": datetime.now().isoformat()
        }, merge=True)
        
        return jsonify({"success": True, "message": "Zakat data securely saved."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500