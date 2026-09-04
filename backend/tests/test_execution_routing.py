import unittest

from services.execution_router import PAPER_EQUITY, THETANUTS_OPTION, UNSUPPORTED, resolve_execution_target
from services.trade_proposal_serializer import serialize_trade_proposal


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


if __name__ == "__main__":
    unittest.main()
