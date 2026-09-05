import ast
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

from services.chat_intent import explicit_trade_action


class ChatIntentTests(unittest.TestCase):
    def test_clear_commands(self):
        for message, action in [
            ('buy AAPL', 'BUY'), ('Please buy 2 shares of AAPL', 'BUY'),
            ('I want to purchase Apple', 'BUY'), ('I would like to buy AAPL', 'BUY'),
            ('sell AAPL', 'SELL'), ('Please sell my AAPL shares.', 'SELL'),
        ]:
            with self.subTest(message=message):
                self.assertEqual(explicit_trade_action(message), action)

    def test_analysis_negation_and_ambiguity_never_authorize_trading(self):
        for message in [
            'Should I buy AAPL?', "Don't buy AAPL", 'Don’t sell AAPL',
            'Check AAPL', 'Analyze AAPL', 'AAPL', 'Is AAPL a buy',
            'buy AAPL if it drops', 'buy AAPL tomorrow', 'buy or sell AAPL',
            'buy AAPL and sell MSFT', 'My friend said buy AAPL',
            'Explain "buy AAPL"', 'Can you check whether I should sell AAPL',
        ]:
            with self.subTest(message=message):
                self.assertIsNone(explicit_trade_action(message))

    def test_api_blocks_agent_proposal_for_analysis_even_in_automatic_mode(self):
        for message in ('Check AAPL', 'Should I buy AAPL?', "Don't buy AAPL"):
            with self.subTest(message=message):
                response, executor = self.call_chat(message)
                self.assertTrue(response['success'])
                self.assertIsNone(response['data']['trade_proposal'])
                self.assertEqual(response['data']['trade_status'], 'RECOMMEND_ONLY')
                executor.assert_not_called()

    def test_explicit_buy_still_uses_automatic_mode(self):
        response, executor = self.call_chat('buy AAPL')
        executor.assert_called_once()
        self.assertEqual(response['data']['trade_status'], 'PAPER_EXECUTED')

    def call_chat(self, message):
        path = Path(__file__).resolve().parents[1] / 'ai_routes.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        handler = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'chat_with_agent')
        handler.decorator_list = []
        agent = MagicMock()
        agent.process.return_value = {
            'status': 'SUCCESS', 'trade_status': 'EXECUTABLE',
            'trade_proposal': {'symbol': 'AAPL', 'decision': 'BUY'},
        }
        executor = MagicMock(return_value={'ok': True, 'status': 'PAPER_EXECUTED'})
        env = {
            'print': lambda *args, **kwargs: None,
            'request': SimpleNamespace(json={'message': message}),
            'g': SimpleNamespace(uid='test'), 'datetime': datetime, 'db': MagicMock(),
            '_get_preferences': lambda uid: {}, 'get_portfolio_state': lambda uid: {},
            'agent': agent, 'explicit_trade_action': explicit_trade_action,
            '_execution_mode': lambda prefs: 'AUTO', 'AUTOMATED_MODE': 'AUTO',
            'CONFIRMATION_MODE': 'CONFIRM', 'execute_prepared_proposal': executor,
            'jsonify': lambda payload: payload,
        }
        exec(compile(ast.Module(body=[handler], type_ignores=[]), str(path), 'exec'), env)
        return env['chat_with_agent'](), executor


if __name__ == '__main__':
    unittest.main()
