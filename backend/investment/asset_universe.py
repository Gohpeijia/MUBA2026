"""Curated asset universe for automated scanning.

Separate from services.asset_resolver.ASSET_ALIAS_DATABASE (the ~150-symbol
master database used for user-driven /chat asset resolution). This universe
is only for the automated scanner and is intentionally curated.
"""

SCAN_UNIVERSE = {
    "crypto": [
        "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD",
        "XRP-USD", "DOGE-USD", "ADA-USD", "AVAX-USD",
    ],
    "us_equities": [
        "AAPL", "MSFT", "NVDA", "AMZN", "META",
        "GOOGL", "GOOG", "TSLA", "AVGO", "AMD",
        "NFLX", "COST", "JPM", "V", "MA", "WMT",
        "LLY", "ORCL", "CRM", "ADBE", "QCOM",
        "INTC", "MU", "UBER", "COIN",
    ],
    "etfs": [
        "SPY", "QQQ", "IWM", "DIA",
    ],
}


def get_scan_universe() -> list:
    """Returns a stable-ordered, deduplicated list of canonical symbols."""
    symbols = []
    seen = set()
    for category in SCAN_UNIVERSE.values():
        for symbol in category:
            if symbol not in seen:
                seen.add(symbol)
                symbols.append(symbol)
    return symbols