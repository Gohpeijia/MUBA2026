"""Quantitative-only investment opportunity screener.

The screener is intentionally deterministic and AI-free.

It uses the real services.data_service.collect_market_data() schema and
combines momentum, trend, technical indicators, fundamentals, volatility,
and data quality into a 0-100 screening score.

The screener DOES NOT make a BUY/SELL decision.
It only ranks assets for expensive multi-agent analysis.
"""

import logging
from datetime import datetime, timezone

from services.data_service import collect_market_data

logger = logging.getLogger(__name__)


def _clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    """Clamp a numeric value to a fixed range."""
    return max(minimum, min(maximum, value))


def _score_momentum(change_1d, change_30d) -> float:
    """Score short- and medium-term momentum."""
    score = 50.0

    if change_1d is not None:
        score += _clamp(float(change_1d) * 3.0, -20.0, 20.0)

    if change_30d is not None:
        score += _clamp(float(change_30d) * 1.0, -20.0, 20.0)

    return _clamp(score)


def _score_trend(current_price, sma_20, sma_50, sma_200, crossover_signal) -> float:
    """Score price trend using moving averages and crossover."""
    if current_price is None:
        return 50.0

    score = 50.0
    price = float(current_price)

    if sma_20 is not None:
        score += 8.0 if price > float(sma_20) else -8.0

    if sma_50 is not None:
        score += 10.0 if price > float(sma_50) else -10.0

    if sma_200 is not None:
        score += 12.0 if price > float(sma_200) else -12.0

    if crossover_signal == "GOLDEN_CROSS":
        score += 10.0
    elif crossover_signal == "DEATH_CROSS":
        score -= 10.0

    return _clamp(score)


def _score_technicals(rsi, macd, volatility) -> float:
    """Score RSI/MACD while penalizing excessive volatility."""
    score = 50.0

    # RSI:
    # Prefer healthy bullish momentum without rewarding extreme
    # overbought conditions.
    if rsi is not None:
        rsi = float(rsi)

        if 50 <= rsi <= 65:
            score += 15.0
        elif 45 <= rsi < 50:
            score += 5.0
        elif 65 < rsi <= 70:
            score += 5.0
        elif rsi > 75:
            score -= 15.0
        elif rsi < 30:
            score -= 10.0
        elif rsi < 40:
            score -= 5.0

    # MACD
    if isinstance(macd, dict):
        macd_value = macd.get("macd")
        signal = macd.get("signal")
        histogram = macd.get("histogram")

        if (
            macd_value is not None
            and signal is not None
        ):
            if float(macd_value) > float(signal):
                score += 15.0
            else:
                score -= 10.0

        if histogram is not None:
            if float(histogram) > 0:
                score += 5.0
            elif float(histogram) < 0:
                score -= 5.0

    # Volatility penalty.
    if volatility is not None:
        volatility = float(volatility)

        if volatility <= 25:
            score += 10.0
        elif volatility <= 40:
            score += 5.0
        elif volatility <= 60:
            score -= 5.0
        else:
            score -= 15.0

    return _clamp(score)


def _score_fundamentals(fundamentals: dict) -> float:
    """Score available fundamental quality metrics."""
    if not isinstance(fundamentals, dict):
        return 50.0

    score = 50.0

    pe_ratio = fundamentals.get("pe_ratio")
    profit_margin = fundamentals.get("profit_margin")
    debt_to_equity = fundamentals.get("debt_to_equity")
    roe = fundamentals.get("roe")
    revenue_growth = fundamentals.get("revenue_growth")
    earnings_growth = fundamentals.get("earnings_growth")
    free_cash_flow = fundamentals.get("free_cash_flow_mil")

    # Valuation
    if pe_ratio is not None:
        pe = float(pe_ratio)

        if 0 < pe <= 25:
            score += 8.0
        elif 25 < pe <= 40:
            score += 3.0
        elif pe > 60:
            score -= 8.0

    # Profitability
    if profit_margin is not None:
        margin = float(profit_margin)

        if margin >= 30:
            score += 8.0
        elif margin >= 15:
            score += 4.0
        elif margin < 0:
            score -= 8.0

    # ROE
    if roe is not None:
        roe_value = float(roe)

        if roe_value >= 25:
            score += 8.0
        elif roe_value >= 15:
            score += 4.0
        elif roe_value < 0:
            score -= 5.0

    # Growth
    if revenue_growth is not None:
        growth = float(revenue_growth)

        if growth >= 20:
            score += 6.0
        elif growth >= 10:
            score += 3.0
        elif growth < 0:
            score -= 5.0

    if earnings_growth is not None:
        growth = float(earnings_growth)

        if growth >= 20:
            score += 6.0
        elif growth >= 10:
            score += 3.0
        elif growth < 0:
            score -= 5.0

    # Debt
    if debt_to_equity is not None:
        debt = float(debt_to_equity)

        if debt <= 50:
            score += 5.0
        elif debt >= 150:
            score -= 8.0

    # Positive free cash flow
    if free_cash_flow is not None:
        if float(free_cash_flow) > 0:
            score += 5.0
        else:
            score -= 5.0

    return _clamp(score)


def _score_data_quality(data_quality: dict) -> float:
    """Score reliability of the available data."""
    if not isinstance(data_quality, dict):
        return 50.0

    overall = data_quality.get("overall", "UNKNOWN")

    if overall == "GOOD":
        return 100.0

    if overall == "PARTIAL":
        return 70.0

    if overall == "POOR":
        return 20.0

    return 50.0


def screen_asset(symbol: str) -> dict:
    """Evaluate one asset quantitatively.

    Returns a deterministic screening result and never raises.
    """
    try:
        data = collect_market_data(symbol)

        if not data or not isinstance(data, dict):
            raise ValueError(
                "collect_market_data returned no usable data"
            )

        price = data.get("price") or {}
        technicals = data.get("technical_indicators") or {}
        fundamentals = data.get("fundamentals") or {}
        data_quality = data.get("data_quality") or {}

        current_price = price.get("current_price")
        change_1d = price.get("change_1d_pct")
        change_30d = price.get("change_30d_pct")

        if current_price is None or change_1d is None:
            return {
                "symbol": symbol,
                "score": 0,
                "status": "FAILED",
                "reason": "Required market data unavailable",
            }

        if data_quality.get("overall") == "POOR":
            return {
                "symbol": symbol,
                "score": 0,
                "status": "FAILED",
                "reason": "Market data quality is POOR",
            }

        momentum_score = _score_momentum(
            change_1d,
            change_30d,
        )

        trend_score = _score_trend(
            current_price,
            technicals.get("sma_20"),
            technicals.get("sma_50"),
            technicals.get("sma_200"),
            technicals.get("crossover_signal"),
        )

        technical_score = _score_technicals(
            technicals.get("rsi_14"),
            technicals.get("macd"),
            technicals.get("volatility_30d_annualized_pct"),
        )

        fundamental_score = _score_fundamentals(
            fundamentals
        )

        quality_score = _score_data_quality(
            data_quality
        )

        # Weighted composite.
        #
        # Momentum       25%
        # Trend          25%
        # Technicals     20%
        # Fundamentals   20%
        # Data quality   10%
        #
        # This remains a screening score, not an investment decision.
        score = (
            momentum_score * 0.25
            + trend_score * 0.25
            + technical_score * 0.20
            + fundamental_score * 0.20
            + quality_score * 0.10
        )

        score = round(_clamp(score), 2)

        # Human-readable signals for debugging and later frontend use.
        if score >= 75:
            screening_signal = "STRONG"
        elif score >= 60:
            screening_signal = "POSITIVE"
        elif score >= 45:
            screening_signal = "NEUTRAL"
        else:
            screening_signal = "WEAK"

        return {
            "symbol": symbol,
            "score": score,
            "status": "SUCCESS",
            "screening_signal": screening_signal,
            "component_scores": {
                "momentum": round(momentum_score, 2),
                "trend": round(trend_score, 2),
                "technicals": round(technical_score, 2),
                "fundamentals": round(fundamental_score, 2),
                "data_quality": round(quality_score, 2),
            },
            "signals": {
                "change_1d_pct": change_1d,
                "change_30d_pct": change_30d,
                "rsi_14": technicals.get("rsi_14"),
                "macd_histogram": (
                    technicals.get("macd") or {}
                ).get("histogram"),
                "sma_20": technicals.get("sma_20"),
                "sma_50": technicals.get("sma_50"),
                "sma_200": technicals.get("sma_200"),
                "crossover_signal": technicals.get(
                    "crossover_signal"
                ),
                "volatility_30d_annualized_pct": technicals.get(
                    "volatility_30d_annualized_pct"
                ),
            },
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
        }

    except Exception as e:
        logger.warning(
            "Screening failed for %s: %s",
            symbol,
            e,
        )

        return {
            "symbol": symbol,
            "score": 0,
            "status": "FAILED",
            "reason": str(e),
        }