# investment_routes.py
#
# Flask endpoints for Amanah Multi-Agent Investment Intelligence.
# Exposes POST /api/investment/analyze

from flask import Blueprint, request, jsonify
from agents.orchestrator import MultiAgentOrchestrator

investment_bp = Blueprint('investment', __name__)
orchestrator = MultiAgentOrchestrator()


@investment_bp.route('/analyze', methods=['POST'])
def analyze_stock_endpoint():
    """
    POST /api/investment/analyze
    Body:
      {
        "symbol": "1155.KL",
        "question": "Should I buy Maybank stock?" (optional),
        "bypass_cache": false (optional)
      }
    """
    try:
        data = request.get_json(silent=True) or {}
        symbol = data.get("symbol") or data.get("ticker")
        question = data.get("question") or data.get("message")
        bypass_cache = bool(data.get("bypass_cache", False))

        if not symbol:
            return jsonify({
                "success": False,
                "error": "Missing required 'symbol' parameter (e.g. '1155.KL', 'AAPL', 'ETH-USD')."
            }), 400

        # Execute multi-agent analysis synchronously in worker thread
        result = orchestrator.analyze_stock_sync(
            symbol=symbol,
            user_question=question,
        )

        return jsonify({
            "success": True,
            "data": result,
        }), 200

    except Exception as e:
        print(f"❌ [InvestmentAPI] Analysis error: {e}")
        return jsonify({
            "success": False,
            "error": f"Analysis failed: {str(e)}",
        }), 500
