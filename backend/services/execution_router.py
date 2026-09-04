import re
from typing import Any

PAPER_EQUITY = "PAPER_EQUITY"
THETANUTS_OPTION = "THETANUTS_OPTION"
UNSUPPORTED = "UNSUPPORTED"

_SUPPORTED_THETANUTS_UNDERLYINGS = {
    "BTC": "BTC",
    "BTC-USD": "BTC",
    "BTC/USD": "BTC",
    "WBTC": "BTC",
    "ETH": "ETH",
    "ETH-USD": "ETH",
    "ETH/USD": "ETH",
    "WETH": "ETH",
}

_EQUITY_ASSET_TYPES = {
    "EQUITY",
    "EQUITY_US",
    "EQUITY_BURSA",
    "ETF",
    "INDEX_ETF",
    "COMMODITY_ETF",
}

_EQUITY_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,9}$")


def normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def resolve_execution_target(symbol: str, asset_type: str | None = None) -> dict:
    normalized = normalize_symbol(symbol)
    normalized_asset_type = normalize_symbol(asset_type)

    if normalized in _SUPPORTED_THETANUTS_UNDERLYINGS:
        return {
            "execution_target": THETANUTS_OPTION,
            "symbol": normalized,
            "underlying": _SUPPORTED_THETANUTS_UNDERLYINGS[normalized],
            "asset_type": "CRYPTO_OPTION",
            "supported": True,
        }

    if normalized.endswith("-USD"):
        return {
            "execution_target": UNSUPPORTED,
            "symbol": normalized,
            "underlying": normalized,
            "asset_type": normalized_asset_type or "CRYPTO",
            "supported": False,
            "reason": "Only BTC and ETH are currently supported for Thetanuts option execution.",
        }

    if normalized_asset_type in _EQUITY_ASSET_TYPES or _EQUITY_SYMBOL_RE.match(normalized):
        return {
            "execution_target": PAPER_EQUITY,
            "symbol": normalized,
            "underlying": normalized,
            "asset_type": normalized_asset_type or "EQUITY",
            "supported": True,
        }

    return {
        "execution_target": UNSUPPORTED,
        "symbol": normalized,
        "underlying": normalized,
        "asset_type": normalized_asset_type or "UNKNOWN",
        "supported": False,
        "reason": "This asset is recommendation-only because no execution engine is configured for it.",
    }
