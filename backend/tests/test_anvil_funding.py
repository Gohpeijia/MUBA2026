import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

from services.paper_accounting import apply_fill


class AnvilFundingTests(unittest.TestCase):
    def setUp(self):
        self.account = {}
        self.funding = {'address': '0xabc', 'usdc': 10000, 'eth': 2}
        firebase = MagicMock()
        firebase.firestore.transactional.side_effect = lambda fn: fn
        config = MagicMock()
        user_ref = config.db.collection.return_value.document.return_value
        user_ref.get.return_value.to_dict.side_effect = lambda: dict(self.account)
        config.db.transaction.return_value.set.side_effect = lambda ref, updates, **kw: self.account.update(updates)
        funding_module = MagicMock()
        funding_module.read_anvil_funding.side_effect = lambda: dict(self.funding)
        self.modules = patch.dict(sys.modules, {
            'firebase_admin': firebase, 'firebase_config': config,
            'services.anvil_funding': funding_module,
        })
        self.modules.start()
        self.addCleanup(self.modules.stop)
        path = Path(__file__).resolve().parents[1] / 'services/portfolio_service.py'
        spec = importlib.util.spec_from_file_location('anvil_portfolio_test', path)
        self.service = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.service)
        self.service._paper_cash_from_trades = MagicMock(return_value=-1200)

    def test_import_existing_spending_then_accept_new_funding(self):
        self.assertEqual(self.service.get_paper_cash_balance('user'), 8800)
        self.assertEqual(self.service.get_paper_cash_balance('user'), 8800)
        self.funding['usdc'] += 2000
        self.assertEqual(self.service.get_paper_cash_balance('user'), 10800)
        self.service._paper_cash_from_trades.assert_called_once()

    def test_trade_changes_survive_funding_refresh(self):
        self.service.get_paper_cash_balance('user')
        updates, _ = apply_fill(self.account, 'ABC', 'BUY', 2, 100)
        self.account.update(updates)
        self.assertEqual(self.service.get_paper_cash_balance('user'), 8600)
        updates, _ = apply_fill(self.account, 'ABC', 'SELL', 2, 120)
        self.account.update(updates)
        self.assertEqual(self.service.get_paper_cash_balance('user'), 8840)
        self.assertEqual(self.funding['usdc'], 10000)

    def test_eth_funding_does_not_create_usdc(self):
        self.service.get_paper_cash_balance('user')
        self.funding['eth'] = 200
        self.assertEqual(self.service.get_paper_cash_balance('user'), 8800)

    def test_wallet_change_is_blocked(self):
        self.service.get_paper_cash_balance('user')
        self.funding['address'] = '0xdef'
        with self.assertRaisesRegex(ValueError, 'wallet changed'):
            self.service.get_paper_cash_balance('user')

    def test_insufficient_funding_is_not_reset_to_fake_cash(self):
        self.funding['usdc'] = 100
        with self.assertRaisesRegex(ValueError, 'below simulated spending'):
            self.service.get_paper_cash_balance('user')
        self.assertEqual(self.account, {})


if __name__ == '__main__':
    unittest.main()
