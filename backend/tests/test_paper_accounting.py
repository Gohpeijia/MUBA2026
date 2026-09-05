import unittest
import sys
from unittest.mock import MagicMock, patch
from services.paper_accounting import apply_fill, settle_paper_trade


class PaperAccountingTests(unittest.TestCase):
    def test_buy_partial_sell_and_full_close(self):
        account = {'paperCashUsd': 1000, 'portfolio': []}
        account, _ = apply_fill(account, 'ABC', 'BUY', 2, 100)
        self.assertEqual(account['paperCashUsd'], 800)
        self.assertEqual(account['portfolio'][0]['costBasisUsd'], 200)
        self.assertEqual(account['paperCashUsd'] + account['portfolio'][0]['market_value'], 1000)
        account, fill = apply_fill(account, 'ABC', 'SELL', 1, 120)
        self.assertEqual(account['paperCashUsd'], 920)
        self.assertEqual(fill['realizedPnlUsd'], 20)
        self.assertEqual(account['portfolio'][0]['averageCost'], 100)
        self.assertEqual(account['paperCashUsd'] + account['portfolio'][0]['market_value'], 1040)
        account, fill = apply_fill(account, 'ABC', 'SELL', 1, 90)
        self.assertEqual(account['paperCashUsd'], 1010)
        self.assertEqual(account['realizedPnlUsd'], 10)
        self.assertEqual(account['portfolio'], [])

    def test_weighted_average_cost(self):
        account, _ = apply_fill({'paperCashUsd': 1000}, 'ABC', 'BUY', 2, 100)
        account, _ = apply_fill(account, 'ABC', 'BUY', 1, 160)
        self.assertEqual(account['portfolio'][0]['averageCost'], 120)
        account, fill = apply_fill(account, 'ABC', 'SELL', 1, 130)
        self.assertEqual(fill['realizedPnlUsd'], 10)
        self.assertEqual(account['portfolio'][0]['costBasisUsd'], 240)

    def test_rejected_order_does_not_change_account(self):
        account = {'paperCashUsd': 10, 'portfolio': []}
        for action in ('BUY', 'SELL'):
            with self.assertRaises(ValueError):
                apply_fill(account, 'ABC', action, 1, 100)
        self.assertEqual(account, {'paperCashUsd': 10, 'portfolio': []})

    def test_money_rounding(self):
        account, _ = apply_fill({'paperCashUsd': 100}, 'ABC', 'BUY', 3, 0.1)
        self.assertEqual(account['paperCashUsd'], 99.7)
        account, _ = apply_fill(account, 'ABC', 'SELL', 3, 0.1)
        self.assertEqual(account['paperCashUsd'], 100)

    def test_non_finite_amounts_rejected(self):
        for value in (float('nan'), float('inf'), -1, 0):
            with self.assertRaises(ValueError):
                apply_fill({'paperCashUsd': 100}, 'ABC', 'BUY', 1, value)

    def test_settlement_groups_cash_holdings_summary_and_history_in_transaction(self):
        firebase = MagicMock()
        firebase.firestore.transactional.side_effect = lambda fn: fn
        config = MagicMock()
        portfolio_service = MagicMock()
        user_ref = config.db.collection.return_value.document.return_value
        user_ref.get.return_value.to_dict.return_value = {'paperCashUsd': 1000, 'portfolio': []}
        with patch.dict(sys.modules, {
            'firebase_admin': firebase, 'firebase_config': config,
            'services.portfolio_service': portfolio_service,
        }):
            self.assertEqual(settle_paper_trade('test', 'ABC', 'BUY', 2, 100), 800)
        transaction = config.db.transaction.return_value
        self.assertEqual(transaction.update.call_count, 1)
        self.assertEqual(transaction.set.call_count, 2)
        updates = transaction.update.call_args.args[1]
        self.assertEqual(updates['paperCashUsd'], 800)
        self.assertEqual(updates['portfolio'][0]['quantity'], 2)
        user_ref.update.assert_not_called()

    def test_settlement_rechecks_cash_before_writing(self):
        firebase = MagicMock()
        firebase.firestore.transactional.side_effect = lambda fn: fn
        config = MagicMock()
        user_ref = config.db.collection.return_value.document.return_value
        user_ref.get.return_value.to_dict.return_value = {'paperCashUsd': 50, 'portfolio': []}
        with patch.dict(sys.modules, {
            'firebase_admin': firebase, 'firebase_config': config,
            'services.portfolio_service': MagicMock(),
        }):
            with self.assertRaises(ValueError):
                settle_paper_trade('test', 'ABC', 'BUY', 1, 100)
        transaction = config.db.transaction.return_value
        transaction.update.assert_not_called()
        transaction.set.assert_not_called()


if __name__ == '__main__':
    unittest.main()
