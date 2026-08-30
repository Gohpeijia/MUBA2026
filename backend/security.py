import logging
from flask import request, jsonify, g
from functools import wraps
from firebase_admin import auth
from firebase_admin.auth import InvalidIdTokenError, ExpiredIdTokenError, RevokedIdTokenError

def require_auth(f):
    """
    Enterprise-grade security using Firebase JWT.
    Includes token revocation checks and empty payload defenses.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')

        if not auth_header:
            return jsonify({"success": False, "error": "Missing Authorization header"}), 401

        parts = auth_header.split()

        if len(parts) != 2 or parts[0] != "Bearer":
            return jsonify({"success": False, "error": "Invalid Authorization format. Expected 'Bearer <token>'"}), 401

        token = parts[1]

        try:
            # UPGRADE: check_revoked=True instantly blocks stolen/logged-out tokens
            decoded_token = auth.verify_id_token(token, check_revoked=True)
            
            # UPGRADE: Defense against empty UID edge case
            uid = decoded_token.get("uid")
            if not uid:
                logging.warning("Invalid token payload: missing UID")
                return jsonify({"success": False, "error": "Invalid token payload"}), 401

            g.uid = uid
            return f(*args, **kwargs)

        except (InvalidIdTokenError, ExpiredIdTokenError, RevokedIdTokenError) as e:
            logging.warning(f"Firebase auth failed: {str(e)}")
            return jsonify({"success": False, "error": "Unauthorized. Invalid, expired, or revoked token."}), 401
            
        except Exception as e:
             logging.error(f"Unexpected error during auth: {str(e)}")
             return jsonify({"success": False, "error": "Internal server error during authentication."}), 500

    return decorated_function