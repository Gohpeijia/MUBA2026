import unittest

from services.execution_router import PAPER_EQUITY, THETANUTS_OPTION, UNSUPPORTED, resolve_execution_target
from services.trade_proposal_serializer import serialize_trade_proposal
from services.trade_quantity import parse_explicit_trade_quantity, select_sell_quantity


class ExecutionRoutingTests(unittest.TestCase):
    def test_equity_routes_to_paper_execution(self):
        result = resolve_execution_target("AAPL", "EQUITY_US")
        self.assertEqual(result["execution_target"], PAPER_EQUITY)
        self.assertEqual(result["symbol"], "AAPL")

    def test_supported_crypto_routes_to_thetanuts_underlying(self):
        result = resolve_execution_target("BTC-USD", "CRYPTO")
        self.assertEqual(result["execution_target"], THETANUTS_OPTION)
        self.assertEqual(result["underlying"], "BTC")

    def test_unsupported_crypto_is_recommendation_only(self):
        result = resolve_execution_target("SOL-USD", "CRYPTO")
        self.assertEqual(result["execution_target"], UNSUPPORTED)
        self.assertFalse(result["supported"])

    def test_serializer_mirrors_selector_to_confirm_selector(self):
        proposal = serialize_trade_proposal({
            "ticker": "BTC",
            "action": "BUY",
            "selector": {
                "underlying": "BTC",
                "option_type": "CALL",
                "strike": 100000,
                "expiry": 1800000000,
                "previewed_price": "123.45",
            },
        })

        self.assertEqual(proposal["symbol"], "BTC")
        self.assertEqual(proposal["decision"], "BUY")
        self.assertEqual(proposal["confirm_selector"], proposal["selector"])

    def test_sell_quantity_prefers_user_request(self):
        quantity, source, error = select_sell_quantity(
            {"recommended_shares": 4}, 2, 10
        )
        self.assertEqual((quantity, source, error), (2, "USER", None))

    def test_sell_quantity_uses_ai_then_defaults_to_one(self):
        self.assertEqual(
            select_sell_quantity({"recommended_shares": 4}, None, 10),
            (4, "AI_RECOMMENDED", None),
        )
        self.assertEqual(
            select_sell_quantity({}, None, 10),
            (1, "DEFAULT", None),
        )

    def test_user_cannot_sell_more_than_holdings(self):
        quantity, source, error = select_sell_quantity({}, 11, 10)
        self.assertIsNone(quantity)
        self.assertEqual(source, "USER")
        self.assertIn("only hold 10", error)

    def test_manual_sell_quantity_parser(self):
        self.assertEqual(parse_explicit_trade_quantity("sell 3 NVDA", "SELL"), 3)
        self.assertEqual(parse_explicit_trade_quantity("sell NVDA 2 shares", "SELL"), 2)
        self.assertIsNone(parse_explicit_trade_quantity("sell NVDA", "SELL"))


if __name__ == "__main__":
    unittest.main()
