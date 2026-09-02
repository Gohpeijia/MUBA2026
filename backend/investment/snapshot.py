# investment/snapshot.py
#
# Canonical investment snapshot.
#
# Purpose:
# - Normalize Yahoo/Finnhub provider fields
# - Remove suspicious/untrusted values
# - Give every AI agent the same factual dataset
# - Prevent agents from inventing alternative financial figures

from copy import deepcopy
from typing import Dict, Any


def _valid_number(value):
    """Return a numeric value or None."""
    if value is None:
        return None

    try:
        number = float(value)

        if number != number:  # NaN
            return None

        return number
    except (TypeError, ValueError):
        return None


def _clean_percentage(
    value,
    *,
    minimum: float = -1000.0,
    maximum: float = 1000.0,
):
    """
    Validate a percentage supplied by the provider.

    Returns None when the value is clearly invalid/suspicious.
    """
    value = _valid_number(value)

    if value is None:
        return None

    if value < minimum or value > maximum:
        return None

    return value


def build_canonical_snapshot(
    market_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Convert provider market data into one canonical schema.

    Agents should use this snapshot instead of raw provider data.
    """

    snapshot = deepcopy(market_snapshot)

    price = snapshot.get("price") or {}
    technical = snapshot.get("technical_indicators") or {}
    raw_fundamentals = snapshot.get("fundamentals") or {}
    data_quality = deepcopy(snapshot.get("data_quality") or {})

    # ---------------------------------------------------------
    # Basic identity
    # ---------------------------------------------------------

    symbol = snapshot.get("symbol")
    asset_type = snapshot.get("asset_type", "EQUITY")
    currency = snapshot.get("currency", "USD")

    # ---------------------------------------------------------
    # Normalize price
    # ---------------------------------------------------------

    normalized_price = {
        "current_price": _valid_number(
            price.get("current_price")
        ),
        "previous_close": _valid_number(
            price.get("previous_close")
        ),
        "change_1d_pct": _valid_number(
            price.get("change_1d_pct")
        ),
        "change_30d_pct": _valid_number(
            price.get("change_30d_pct")
        ),
        "fifty_two_week_high": _valid_number(
            price.get("fifty_two_week_high")
        ),
        "fifty_two_week_low": _valid_number(
            price.get("fifty_two_week_low")
        ),
        "average_volume": _valid_number(
            price.get("average_volume")
        ),
    }

    # ---------------------------------------------------------
    # Normalize technical indicators
    # ---------------------------------------------------------

    macd = technical.get("macd") or {}

    normalized_technical = {
        "rsi_14": _valid_number(
            technical.get("rsi_14")
        ),
        "macd": {
            "macd": _valid_number(macd.get("macd")),
            "signal": _valid_number(macd.get("signal")),
            "histogram": _valid_number(macd.get("histogram")),
        },
        "sma_20": _valid_number(
            technical.get("sma_20")
        ),
        "sma_50": _valid_number(
            technical.get("sma_50")
        ),
        "sma_200": _valid_number(
            technical.get("sma_200")
        ),
        "crossover_signal": technical.get(
            "crossover_signal"
        ),
        "volatility_30d_annualized_pct": _valid_number(
            technical.get("volatility_30d_annualized_pct")
        ),
        "support_resistance": technical.get(
            "support_resistance",
            {},
        ),
    }

    # ---------------------------------------------------------
    # Normalize fundamentals
    #
    # IMPORTANT:
    # Provider data uses percentage-style values for fields such
    # as profit_margin, revenue_growth, ROE, etc.
    #
    # We expose explicit *_pct names so agents cannot confuse
    # 63.66 with 0.6366.
    # ---------------------------------------------------------

    normalized_fundamentals = {
        "pe_ratio": _valid_number(
            raw_fundamentals.get("pe_ratio")
        ),

        "market_cap_mil": _valid_number(
            raw_fundamentals.get("market_cap_mil")
        ),

        "profit_margin_pct": _clean_percentage(
            raw_fundamentals.get("profit_margin")
        ),

        "debt_to_equity": _valid_number(
            raw_fundamentals.get("debt_to_equity")
        ),

        "roe_pct": _clean_percentage(
            raw_fundamentals.get("roe")
        ),

        "revenue_mil": _valid_number(
            raw_fundamentals.get("revenue_mil")
        ),

        "revenue_growth_pct": _clean_percentage(
            raw_fundamentals.get("revenue_growth")
        ),

        "earnings_growth_pct": _clean_percentage(
            raw_fundamentals.get("earnings_growth")
        ),

        "eps": _valid_number(
            raw_fundamentals.get("eps")
        ),

        "free_cash_flow_mil": _valid_number(
            raw_fundamentals.get("free_cash_flow_mil")
        ),
    }

    # ---------------------------------------------------------
    # Suspicious dividend yield handling
    # ---------------------------------------------------------
    #
    # NVDA was previously reported with:
    #
    #     dividend_yield = 46.0
    #
    # which is clearly inconsistent with the rest of the data.
    #
    # Do NOT pass suspicious values to LLM agents.
    # ---------------------------------------------------------

    raw_dividend_yield = _valid_number(
        raw_fundamentals.get("dividend_yield")
    )

    if raw_dividend_yield is not None:
        # Conservative sanity check for this investment universe.
        if 0 <= raw_dividend_yield <= 20:
            normalized_fundamentals["dividend_yield_pct"] = (
                raw_dividend_yield
            )
        else:
            normalized_fundamentals["dividend_yield_pct"] = None

            notes = data_quality.setdefault("notes", [])
            notes.append(
                "Provider dividend yield was excluded because "
                "the reported value failed plausibility checks."
            )
    else:
        normalized_fundamentals["dividend_yield_pct"] = None

    # ---------------------------------------------------------
    # Normalize news
    # ---------------------------------------------------------

    news = snapshot.get("news") or []

    normalized_news = []

    for item in news[:10]:
        if not isinstance(item, dict):
            continue

        normalized_news.append({
            "headline": item.get("headline", ""),
            "summary": item.get("summary", ""),
            "source": item.get("source"),
            "datetime": item.get("datetime"),
            "url": item.get("url"),
        })

    # ---------------------------------------------------------
    # Normalize data quality
    # ---------------------------------------------------------

    missing_fields = list(
        data_quality.get("missing_fields") or []
    )

    # Provider may report market_cap/revenue as missing even though
    # the canonical *_mil fields are present.
    if (
        normalized_fundamentals["market_cap_mil"] is not None
        and "market_cap" in missing_fields
    ):
        missing_fields.remove("market_cap")

    if (
        normalized_fundamentals["revenue_mil"] is not None
        and "revenue" in missing_fields
    ):
        missing_fields.remove("revenue")

    data_quality["missing_fields"] = missing_fields

    # ---------------------------------------------------------
    # Final canonical snapshot
    # ---------------------------------------------------------

    canonical_snapshot = {
        "symbol": symbol,
        "company_name": snapshot.get(
            "company_name",
            symbol,
        ),
        "asset_type": asset_type,
        "currency": currency,

        "price": normalized_price,

        "technical_indicators": normalized_technical,

        "fundamentals": normalized_fundamentals,

        "news": normalized_news,

        "data_quality": data_quality,

        "data_freshness": snapshot.get(
            "data_freshness",
            {},
        ),

        "chart_data": snapshot.get(
            "chart_data",
            [],
        ),
    }

    return canonical_snapshot