# services/indicators.py
#
# Programmatic technical indicator engine.
# Performs exact mathematical calculations for Technical Analysis:
#   - RSI (14-period Wilder smoothing)
#   - MACD (12-EMA, 26-EMA, 9-EMA Signal, Histogram)
#   - Moving Averages (SMA-20, SMA-50, SMA-200)
#   - Realized Volatility (30-day annualized standard deviation)
#   - 52-Week Range & Distance Metrics
#   - Pivot Support & Resistance
#
# Zero arithmetic required by LLM.

import math
from typing import List, Dict, Optional


def calculate_rsi(prices: List[float], period: int = 14) -> Optional[float]:
    """Calculate 14-period Wilder's Smoothed RSI."""
    if len(prices) < period + 1:
        return None

    gains = []
    losses = []
    for i in range(1, len(prices)):
        change = prices[i] - prices[i - 1]
        gains.append(max(0.0, change))
        losses.append(max(0.0, -change))

    if len(gains) < period:
        return None

    # Initial average
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # Wilder's smoothing for subsequent periods
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return round(rsi, 2)


def calculate_ema(prices: List[float], period: int) -> List[float]:
    """Calculate Exponential Moving Average series."""
    if not prices or len(prices) < period:
        return []
    
    k = 2.0 / (period + 1)
    ema_series = [sum(prices[:period]) / period]
    
    for price in prices[period:]:
        ema_series.append((price * k) + (ema_series[-1] * (1.0 - k)))
        
    return ema_series


def calculate_macd(prices: List[float]) -> Dict[str, Optional[float]]:
    """Calculate MACD Line, Signal Line (9-EMA), and Histogram."""
    if len(prices) < 35:  # Need at least 26 + 9 periods
        return {"macd": None, "signal": None, "histogram": None}

    ema_12 = calculate_ema(prices, 12)
    ema_26 = calculate_ema(prices, 26)

    # Align EMA lengths to the 26-period start
    diff_len = len(ema_12) - len(ema_26)
    ema_12_aligned = ema_12[diff_len:]

    macd_line = [f - s for f, s in zip(ema_12_aligned, ema_26)]

    if len(macd_line) < 9:
        return {"macd": round(macd_line[-1], 4), "signal": None, "histogram": None}

    signal_line = calculate_ema(macd_line, 9)
    current_macd = macd_line[-1]
    current_signal = signal_line[-1]
    histogram = current_macd - current_signal

    return {
        "macd": round(current_macd, 4),
        "signal": round(current_signal, 4),
        "histogram": round(histogram, 4),
    }


def calculate_sma(prices: List[float], period: int) -> Optional[float]:
    """Calculate Simple Moving Average for a given period."""
    if len(prices) < period:
        return None
    return round(sum(prices[-period:]) / period, 2)


def calculate_volatility(prices: List[float], period: int = 30) -> Optional[float]:
    """Calculate 30-day annualized realized volatility from daily closing prices."""
    if len(prices) < period + 1:
        return None

    subset = prices[-period - 1:]
    returns = []
    for i in range(1, len(subset)):
        if subset[i - 1] > 0:
            returns.append(math.log(subset[i] / subset[i - 1]))

    if len(returns) < 2:
        return None

    mean_ret = sum(returns) / len(returns)
    variance = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
    std_dev = math.sqrt(variance)
    annualized_vol = std_dev * math.sqrt(252) * 100.0  # Percentage

    return round(annualized_vol, 2)


def calculate_support_resistance(prices: List[float], highs: List[float], lows: List[float]) -> Dict[str, Optional[float]]:
    """Determine estimated support and resistance from recent pivot levels."""
    if not prices or not highs or not lows:
        return {"support_1": None, "resistance_1": None}

    recent_highs = highs[-60:] if len(highs) >= 60 else highs
    recent_lows = lows[-60:] if len(lows) >= 60 else lows

    curr = prices[-1]
    # Local resistance = highest high above current price, or max high
    above_curr = [h for h in recent_highs if h > curr]
    resistance = min(above_curr) if above_curr else max(recent_highs)

    # Local support = lowest low below current price, or min low
    below_curr = [l for l in recent_lows if l < curr]
    support = max(below_curr) if below_curr else min(recent_lows)

    return {
        "support_1": round(support, 2),
        "resistance_1": round(resistance, 2),
    }


def compute_all_technical_indicators(prices: List[float], highs: List[float] = None, lows: List[float] = None) -> Dict:
    """
    Main aggregator for all technical metrics.
    Takes price series and produces full programmatic indicators bundle.
    """
    if not prices:
        return {
            "rsi_14": None,
            "macd": {"macd": None, "signal": None, "histogram": None},
            "sma_20": None,
            "sma_50": None,
            "sma_200": None,
            "crossover_signal": "INSUFFICIENT_DATA",
            "volatility_30d_annualized_pct": None,
            "support_resistance": {"support_1": None, "resistance_1": None},
        }

    highs = highs or prices
    lows = lows or prices

    rsi = calculate_rsi(prices, 14)
    macd = calculate_macd(prices)
    sma_20 = calculate_sma(prices, 20)
    sma_50 = calculate_sma(prices, 50)
    sma_200 = calculate_sma(prices, 200)
    volatility = calculate_volatility(prices, 30)
    sup_res = calculate_support_resistance(prices, highs, lows)

    # Determine crossover signal
    crossover = "NEUTRAL"
    if sma_50 is not None and sma_200 is not None:
        if sma_50 > sma_200:
            crossover = "GOLDEN_CROSS"  # Bullish
        elif sma_50 < sma_200:
            crossover = "DEATH_CROSS"   # Bearish

    return {
        "rsi_14": rsi,
        "macd": macd,
        "sma_20": sma_20,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "crossover_signal": crossover,
        "volatility_30d_annualized_pct": volatility,
        "support_resistance": sup_res,
    }
