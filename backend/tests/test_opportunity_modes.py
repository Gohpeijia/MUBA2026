"""Exercise BUY/SELL dispatch without Firebase writes or real executions."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch


class OpportunityModeTests(unittest.TestCase):
    def setUp(self):
        self.prepare = MagicMock()
        self.confirmations = MagicMock()
        self.execution = MagicMock()
        self.notifications = MagicMock()
        self.modules = {
            "firebase_config": MagicMock(),
            "services.opportunity_prepare_service": self.prepare,
            "services.trade_confirmation_service": self.confirmations,
            "services.execution_service": self.execution,
            "services.notification_service": self.notifications,
        }
        spec = importlib.util.spec_from_file_location(
            "opportunity_mode_test_subject",
            Path(__file__).resolve().parents[1] / "services/opportunity_action_service.py",
        )
        self.s = importlib.util.module_from_spec(spec)
        self.module_patch = patch.dict(sys.modules, self.modules)
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        spec.loader.exec_module(self.s)
        self.s.save_action_status = MagicMock()

    def test_confirmation_mode_creates_prompt_and_never_executes(self):
        self.prepare.get_user_preferences.return_value = {
            "opportunityAutoActionMode": "confirmation_required"
        }
        self.confirmations.create_confirmation.return_value = {
            "confirmation": {"confirmation_id": "test-confirm", "status": "PENDING"}
        }
        for decision in ("BUY", "SELL"):
            with self.subTest(decision=decision):
                opportunity = {"analysis_id": "test", "symbol": "ABC", "decision": decision}
                result = self.s.process_opportunity_for_user(opportunity, "test-user")
                self.assertEqual(result["status"], "PENDING")
                self.notifications.notify_confirmation_required.assert_called_with(
                    user_id="test-user", opportunity=opportunity,
                    confirmation={"confirmation_id": "test-confirm", "status": "PENDING"},
                )
                self.execution.execute_prepared_proposal.assert_not_called()

    def test_automatic_mode_executes_prepared_buy_and_sell(self):
        self.prepare.get_user_preferences.return_value = {
            "opportunityAutoActionMode": "fully_autonomous"
        }
        self.execution.execute_prepared_proposal.return_value = {"ok": True, "status": "PAPER_EXECUTED"}
        for decision in ("BUY", "SELL"):
            with self.subTest(decision=decision):
                proposal = {"symbol": "ABC", "decision": decision}
                self.prepare.prepare_opportunity_for_user.return_value = {"proposal": proposal}
                result = self.s.process_opportunity_for_user(proposal, "test-user")
                self.assertEqual(result["status"], "PAPER_EXECUTED")
                self.execution.execute_prepared_proposal.assert_called_with(
                    user_id="test-user", proposal=proposal, action="AUTO_OPPORTUNITY"
                )
                self.confirmations.create_confirmation.assert_not_called()

    def test_failed_push_preserves_pending_confirmation_for_in_app_polling(self):
        self.prepare.get_user_preferences.return_value = {
            "opportunityAutoActionMode": "confirmation_required"
        }
        self.confirmations.create_confirmation.return_value = {
            "confirmation": {"confirmation_id": "test-confirm", "status": "PENDING"}
        }
        self.notifications.notify_confirmation_required.return_value = False
        result = self.s.process_opportunity_for_user({"decision": "BUY"}, "test-user")
        self.assertEqual(result["status"], "PENDING")
        self.confirmations.mark_confirmation_notified.assert_not_called()
        self.execution.execute_prepared_proposal.assert_not_called()


if __name__ == "__main__":
    unittest.main()
