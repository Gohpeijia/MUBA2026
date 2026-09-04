# wallet_routes.py
#
# Exposes the ThetanutsTrader wallet layer to the frontend:
#   GET /api/wallet/balance       — live ETH/USDC balance for the trading wallet
#   GET /api/wallet/transactions  — recent fill attempts from the local tx log
#
# Register in your main app file the same way the other blueprints are
# registered, e.g.:
#   from wallet_routes import wallet_bp
#   app.register_blueprint(wallet_bp, url_prefix='/api/wallet')

from flask import Blueprint, jsonify, request, g
from security import require_auth
from services.portfolio_service import get_paper_cash_balance
from thetanuts_trader import ThetanutsTrader

wallet_bp = Blueprint('wallet', __name__)

# One shared trader instance — mirrors the pattern in ai_agent.py, so the
# balance the frontend shows is read the same way the AI reads it.
trader = ThetanutsTrader()


@wallet_bp.route('/balance', methods=['GET'])
@require_auth
def get_wallet_balance():
    """
    Live on-chain balance for the configured trading wallet. Always
    returns 200 — even when the wallet can't be reached — with
    data.ok telling the frontend whether the numbers are real. This
    lets the UI show "wallet unreachable" instead of a broken request.
    """
    chain_balance = trader.get_wallet_balance()
    paper_cash = get_paper_cash_balance(g.uid)
    balance = {
        **chain_balance,
        "paper_cash_usd": paper_cash,
        "paper_tradable_usd": paper_cash,
        # Do not replace the Anvil/on-chain USDC fields with the unrelated
        # paper-equity cash balance.  The top-level `usdc` and
        # `tradable_usdc` values must always describe the configured wallet.
        "balance_source": "ONCHAIN_USDC",
        "chain_wallet": chain_balance,
    }
    return jsonify({"success": True, "data": balance})


@wallet_bp.route('/transactions', methods=['GET'])
@require_auth
def get_wallet_transactions():
    """Recent fill attempts (success, failure, or dry-run), most-recent-first."""
    try:
        limit = int(request.args.get('limit', 20))
    except (TypeError, ValueError):
        limit = 20

    history = trader.get_transaction_history(limit=limit)
    return jsonify({"success": True, "data": history})
