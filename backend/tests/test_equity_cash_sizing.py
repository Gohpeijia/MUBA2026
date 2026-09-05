"""Cash/risk regression checks; all account storage is mocked."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch


class EquityCashSizingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "equity_cash_test_subject",
            Path(__file__).resolve().parents[1] / "services/equity_execution_service.py",
        )
        cls.service = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "firebase_config": MagicMock(),
            "services.portfolio_service": MagicMock(),
        }):
            spec.loader.exec_module(cls.service)

    def setUp(self):
        self.s = self.service
        self.s.normalize_symbol.side_effect = lambda s: str(s or '').strip().upper()
        self.s.get_paper_cash_balance.reset_mock()
        self.s.get_paper_cash_balance.return_value = 1000.0
        self.portfolio = {"total_value": 0, "positions": {}, "open_ai_risk_value": 0}
        self.s.get_portfolio_state.return_value = self.portfolio

    def prepare(self, price=100, decision="BUY"):
        return self.s.prepare_equity_proposal(
            user_id="test", symbol="ABC", decision=decision,
            investment_analysis={}, preferences={}, portfolio=self.portfolio,
            spot_price=price,
        )

    def test_new_account_uses_actual_cash_not_ten_thousand_fallback(self):
        proposal = self.prepare()["proposal"]
        self.assertEqual(proposal["shares"], 1)
        self.assertEqual(proposal["estimated_value"], 100)
        self.assertTrue(self.s._risk_gate("test", "ABC", 1, 100)[0])
        self.assertFalse(self.s._risk_gate("test", "ABC", 10, 100)[0])

    def test_holdings_are_added_to_cash_and_order_is_cash_capped(self):
        self.portfolio["positions"] = {
            "OTHER": {"quantity": 90, "market_value": 9000, "average_cost": 100}
        }
        self.s.get_paper_cash_balance.return_value = 100
        proposal = self.prepare()["proposal"]
        self.assertEqual(proposal["shares"], 1)
        self.assertEqual(proposal["risk_sizing"]["capped_by"], "paper_cash")
        self.assertEqual(proposal["risk_sizing"]["dollar_risk"], 7)

    def test_no_cash_does_not_fabricate_capital(self):
        self.s.get_paper_cash_balance.return_value = 0
        self.assertIsNone(self.prepare()["proposal"])

    def test_expensive_share_does_not_bypass_risk_limits(self):
        self.assertIsNone(self.prepare(price=500)["proposal"])

    def test_sell_uses_existing_holdings_without_requiring_cash(self):
        self.portfolio["positions"] = {"ABC": {"quantity": 2}}
        self.s.get_paper_cash_balance.return_value = 0
        proposal = self.prepare(decision="SELL")["proposal"]
        self.assertEqual(proposal["shares"], 2)
        self.s.get_paper_cash_balance.assert_not_called()

    def test_cannot_sell_missing_holdings(self):
        self.assertIsNone(self.prepare(decision="SELL")["proposal"])


if __name__ == "__main__":
    unittest.main()
