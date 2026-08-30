import os
import logging
from flask import Flask, jsonify
from flask_cors import CORS
from flask_limiter import Limiter               
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix
load_dotenv()
# Import your route blueprints
from portfolio_routes import portfolio_bp
from market_routes import market_bp
from zakat_endpoints import zakat_bp
from ai_routes import ai_bp


logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s"
)


app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
CORS(app, resources={r"/api/*": {"origins": "*"}})

limiter = Limiter(
    get_remote_address,
    app=app,
    # Increase these limits significantly! 
    # 120 per minute allows ~2 requests per second.
    default_limits=["1000 per day", "120 per minute"], 
    storage_uri="memory://"
)

# Register the blueprints
app.register_blueprint(portfolio_bp, url_prefix='/api/stocks/portfolio')
app.register_blueprint(market_bp, url_prefix='/api/stocks/market')
app.register_blueprint(zakat_bp, url_prefix='/api/zakat')
app.register_blueprint(ai_bp, url_prefix='/api/aiagent/ai')

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "message": "Welcome to the FinHack2026 Backend! 🚀",
        "status": "Online",
        "docs": "Go to /api/health to check server health."
    })

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({"message": "Modular Islamic Stocks API is running! 🐍🚀"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    # 🟢 NEW: host='0.0.0.0' explicitly set here just in case you run it directly
    app.run(host='0.0.0.0', port=port, debug=False)