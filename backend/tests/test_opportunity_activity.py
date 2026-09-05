import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch


class OpportunityActivityTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "activity_test_subject",
            Path(__file__).resolve().parents[1] / "services/opportunity_activity_service.py",
        )
        self.s = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"firebase_config": MagicMock()}):
            spec.loader.exec_module(self.s)

    def test_blocked_buy_keeps_symbol_decision_and_reason(self):
        item = self.s.activity_item("a", {
            "symbol": "ABC", "decision": "BUY", "status": "failed",
            "error": "Risk limits leave no room", "user_id": "private",
        })
        self.assertEqual(item["status"], "FAILED")
        self.assertEqual(item["decision"], "BUY")
        self.assertEqual(item["symbol"], "ABC")
        self.assertEqual(item["reason"], "Risk limits leave no room")
        self.assertNotIn("user_id", item)

    def test_completed_sell_has_fill_details(self):
        item = self.s.activity_item("a", {
            "decision": "SELL", "status": "executed",
            "result": {"shares": 2, "price": 100},
        })
        self.assertEqual((item["quantity"], item["price"]), (2, 100))

    def test_confirmation_current_status_overrides_stale_action(self):
        item = self.s.activity_item("a", {"status": "pending_confirmation"}, {
            "status": "PAPER_EXECUTED", "confirmation_id": "c",
            "proposal_snapshot": {"shares": 1, "price": 50},
        })
        self.assertEqual(item["status"], "PAPER_EXECUTED")
        self.assertEqual(item["quantity"], 1)

    def test_expired_confirmation_is_not_shown_as_awaiting_approval(self):
        item = self.s.activity_item("a", {}, {
            "status": "PENDING", "expires_at": "2020-01-01T00:00:00+00:00"
        })
        self.assertEqual(item["status"], "EXPIRED")

    def test_activity_query_is_scoped_to_requested_user_and_bounded(self):
        self.s.list_opportunity_activity("test-user")
        self.s.db.collection.assert_called_once_with("users")
        user_ref = self.s.db.collection.return_value.document
        user_ref.assert_called_once_with("test-user")
        query = user_ref.return_value.collection.return_value.order_by
        query.assert_called_once_with("updated_at", direction="DESCENDING")
        query.return_value.limit.assert_called_once_with(30)


if __name__ == "__main__":
    unittest.main()
