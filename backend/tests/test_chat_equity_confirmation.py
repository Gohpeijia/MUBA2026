"""Exercise the actual chat confirmation handler without live services."""
import ast
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from services.paper_accounting import apply_fill

BACKEND = Path(__file__).resolve().parents[1]


class ChatEquityConfirmationTests(unittest.TestCase):
    def setUp(self):
        # Load the handler body without initializing AI providers or Firebase.
        tree = ast.parse((BACKEND / 'ai_routes.py').read_text(encoding='utf-8'))
        handler = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'confirm_trade')
        handler.decorator_list = []
        module = ast.Module(body=[handler], type_ignores=[])
        self.account = {'paperCashUsd': 1000, 'portfolio': []}
        self.executor = MagicMock(side_effect=self.execute)
        self.env = {
            'request': SimpleNamespace(json={}), 'g': SimpleNamespace(uid='test-user'),
            'jsonify': lambda payload: payload,
            '_get_preferences': lambda uid: {},
            '_execution_mode': lambda prefs: 'confirmation', 'CONFIRMATION_MODE': 'confirmation',
            'execute_prepared_proposal': self.executor,
        }
        exec(compile(module, str(BACKEND / 'ai_routes.py'), 'exec'), self.env)

    def execute(self, *, user_id, proposal, action):
        self.assertEqual(user_id, 'test-user')
        self.assertEqual(proposal['execution_target'], 'PAPER_EQUITY')
        try:
            self.account, _ = apply_fill(self.account, proposal['symbol'], proposal['decision'], proposal['shares'], proposal['price'])
            return {'ok': True, 'status': 'PAPER_EXECUTED', 'paper_cash_usd': self.account['paperCashUsd']}
        except ValueError as exc:
            return {'ok': False, 'status': 'FAILED', 'error': str(exc)}

    def confirm(self, decision='BUY', price=100):
        self.env['request'].json = {
            'symbol': 'AAPL', 'decision': decision, 'execution_target': 'PAPER_EQUITY',
            'shares': 2, 'quantity': 2, 'price': price,
        }
        return self.env['confirm_trade']()

    def test_chat_aapl_buy_debits_paper_wallet_and_returns_final_balance(self):
        response = self.confirm()
        self.assertTrue(response['success'])
        self.assertEqual(response['data']['decision'], 'BUY')
        self.assertEqual(response['data']['execution']['paper_cash_usd'], 800)
        self.assertEqual(self.account['portfolio'][0]['quantity'], 2)
        self.executor.assert_called_once()

    def test_chat_sell_credits_same_wallet(self):
        self.confirm()
        response = self.confirm('SELL', 120)
        self.assertEqual(response['data']['execution']['paper_cash_usd'], 1040)
        self.assertEqual(self.account['portfolio'], [])

    def test_insufficient_cash_is_failure_not_success(self):
        response, status = self.confirm(price=600)
        self.assertEqual(status, 409)
        self.assertFalse(response['success'])
        self.assertEqual(self.account['paperCashUsd'], 1000)

    def test_confirmation_still_requires_confirmation_mode(self):
        self.env['_execution_mode'] = lambda prefs: 'manual'
        response, status = self.confirm()
        self.assertEqual(status, 400)
        self.executor.assert_not_called()

    def test_aapl_proposal_uses_user_cash_service_not_options_builder(self):
        equity = MagicMock()
        equity.prepare_equity_proposal.return_value = {'status': 'EXECUTABLE'}
        spec = importlib.util.spec_from_file_location('chat_bridge_test', BACKEND / 'advisor/trade_bridge.py')
        bridge = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'services.equity_execution_service': equity}):
            spec.loader.exec_module(bridge)
        trader = MagicMock()
        bridge.build_trade_proposal(
            symbol='AAPL', decision='BUY', investment_analysis={'confidence': 0.9},
            preferences={}, portfolio={}, trader=trader, spot_price=100,
            asset_type='EQUITY_US', user_id='test-user',
        )
        args = equity.prepare_equity_proposal.call_args.kwargs
        self.assertEqual((args['user_id'], args['symbol'], args['decision']), ('test-user', 'AAPL', 'BUY'))
        self.assertEqual(trader.mock_calls, [])


if __name__ == '__main__':
    unittest.main()
