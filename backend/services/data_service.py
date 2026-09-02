# services/data_service.py
#
# Unified Data Collection, Normalization, Indicator Calculation,
# and Data Quality Validation service.
#
# Integrates Yahoo Finance (yfinance) and Finnhub (Company News).
# Caches normalized snapshots (120s TTL) so all agents share the same data.

import os
import time
import math
import requests
import yfinance as yf
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

from services.indicators import compute_all_technical_indicators
from services.asset_resolver import resolve_asset_from_query, ASSET_ALIAS_DATABASE

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")

# In-memory snapshot cache: { symbol: { "data": dict, "expires_at": timestamp } }
_DATA_CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SECONDS = 120


def resolve_ticker_symbols(raw_ticker: str) -> Dict[str, str]:
    """Resolves raw user input into canonical Yahoo and Finnhub symbols."""
    clean = raw_ticker.strip().upper()

    # 1. Use the intelligent Asset Resolver first
    resolved = resolve_asset_from_query(clean)
    if resolved:
        sym = resolved["symbol"]
        atype = resolved["asset_type"]

        # Finnhub mapping
        if atype == "CRYPTO":
            base = sym.replace("-USD", "")
            finnhub_sym = f"BINANCE:{base}USDT"
        else:
            finnhub_sym = sym

        return {
            "canonical":  sym,
            "yahoo":      sym,
            "finnhub":    finnhub_sym,
            "asset_type": atype,
            "name":       resolved["canonical_name"],
            "currency":   resolved["currency"],
        }

    # 2. Crypto check fallback
    if clean in ("ETH", "BTC", "ETH-USD", "BTC-USD") or "-USD" in clean:
        base = clean.replace("-USD", "")
        return {
            "canonical": f"{base}-USD",
            "yahoo":     f"{base}-USD",
            "finnhub":   f"BINANCE:{base}USDT",
            "asset_type": "CRYPTO",
            "name":      base,
            "currency":  "USD",
        }

    # 3. Bursa check fallback
    if clean.endswith(".KL") or (clean.isdigit() and len(clean) == 4):
        bursa_sym = clean if clean.endswith(".KL") else f"{clean}.KL"
        return {
            "canonical": bursa_sym,
            "yahoo":     bursa_sym,
            "finnhub":   bursa_sym,
            "asset_type": "EQUITY_BURSA",
            "name":      bursa_sym,
            "currency":  "MYR",
        }

    # 4. Default US Equities
    return {
        "canonical":  clean,
        "yahoo":      clean,
        "finnhub":    clean,
        "asset_type": "EQUITY_US",
        "name":       clean,
        "currency":   "USD",
    }


def fetch_finnhub_news(finnhub_symbol: str, limit: int = 15) -> List[Dict]:
    """
    Fetches, deduplicates, and filters company news from Finnhub.
    Limits to the latest `limit` articles (default 15).
    """
    if not FINNHUB_API_KEY:
        return []

    try:
        now = datetime.now(timezone.utc)
        from_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        to_date = now.strftime("%Y-%m-%d")

        url = f"https://finnhub.io/api/v1/company-news?symbol={finnhub_symbol}&from={from_date}&to={to_date}&token={FINNHUB_API_KEY}"
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            return []

        raw_news = resp.json()
        if not isinstance(raw_news, list):
            return []

        cleaned_news = []
        seen_headlines = set()

        for article in raw_news:
            headline = str(article.get("headline", "")).strip()
            if not headline or headline.lower() in seen_headlines:
                continue

            seen_headlines.add(headline.lower())

            # Convert unix timestamp to ISO string
            pub_ts = article.get("datetime")
            published_at = datetime.fromtimestamp(pub_ts, timezone.utc).isoformat() if pub_ts else now.isoformat()

            cleaned_news.append({
                "title":        headline,
                "summary":      str(article.get("summary", ""))[:300],
                "published_at": published_at,
                "source":       str(article.get("source", "Finnhub")),
                "url":          str(article.get("url", "")),
            })

            if len(cleaned_news) >= limit:
                break

        return cleaned_news

    except Exception as e:
        print(f"⚠️ [DataService] Finnhub news error for {finnhub_symbol}: {e}")
        return []


def evaluate_data_quality(market_data: Dict, fundamentals: Dict, news: List[Dict], asset_type: str) -> Dict:
    """
    Programmatically evaluates data completeness and quality.
    Missing fields are explicitly catalogued so agents never hallucinate.
    """
    missing_fields = []
    notes = []

    has_market_data = market_data.get("current_price") is not None
    if not has_market_data:
        missing_fields.append("current_price")
        notes.append("Market price data unavailable")

    # Fundamentals completeness check
    if asset_type == "CRYPTO":
        fund_status = "NOT_APPLICABLE"
        notes.append("Traditional corporate fundamentals not applicable for crypto assets")
    else:
        key_fund_fields = ["pe_ratio", "market_cap", "profit_margin", "debt_to_equity", "revenue", "eps"]
        fund_available_count = 0
        for f in key_fund_fields:
            if fundamentals.get(f) is not None:
                fund_available_count += 1
            else:
                missing_fields.append(f)

        if fund_available_count >= 5:
            fund_status = "FULL"
        elif fund_available_count >= 2:
            fund_status = "PARTIAL"
            notes.append("Some corporate fundamentals missing from provider feed")
        else:
            fund_status = "UNAVAILABLE"
            notes.append("Corporate financial statements unavailable")

    has_news = len(news) > 0
    if not has_news:
        notes.append("No recent company news articles found in provider feed")

    # Determine overall quality
    if has_market_data and (fund_status in ("FULL", "NOT_APPLICABLE")) and has_news:
        overall = "GOOD"
    elif has_market_data and (fund_status in ("PARTIAL", "FULL") or has_news):
        overall = "PARTIAL"
    else:
        overall = "POOR"

    return {
        "overall":            overall,
        "market_data":        has_market_data,
        "fundamentals":       fund_status,
        "news":               has_news,
        "news_count":         len(news),
        "missing_fields":     missing_fields,
        "notes":              notes,
    }


def collect_market_data(raw_ticker: str, bypass_cache: bool = False) -> Dict[str, Any]:
    """
    Main Data Collection entrypoint.
    Fetches Yahoo Finance price & fundamentals + Finnhub news,
    calculates technical indicators, and packages into a normalized contract.
    """
    symbols = resolve_ticker_symbols(raw_ticker)
    canonical = symbols["canonical"]
    now_iso = datetime.now(timezone.utc).isoformat()

    # Check cache
    if not bypass_cache and canonical in _DATA_CACHE:
        entry = _DATA_CACHE[canonical]
        if time.time() < entry["expires_at"]:
            return entry["data"]

    yahoo_sym = symbols["yahoo"]
    finnhub_sym = symbols["finnhub"]
    asset_type = symbols["asset_type"]

    # 1. Fetch Yahoo Finance data
    stock = yf.Ticker(yahoo_sym)
    
    # 1 Year history for reliable 50/200-day SMAs, RSI, and MACD
    hist = stock.history(period="1y")
    info = {}
    try:
        info = stock.info or {}
    except Exception as e:
        print(f"⚠️ [DataService] Failed to read stock.info for {yahoo_sym}: {e}")

    # Extract historical series
    prices = []
    highs = []
    lows = []
    volumes = []
    if not hist.empty:
        for _, row in hist.iterrows():
            c = row.get("Close")
            h = row.get("High", c)
            l = row.get("Low", c)
            v = row.get("Volume", 0)
            if c is not None and not math.isnan(c):
                prices.append(round(float(c), 4))
                highs.append(round(float(h), 4))
                lows.append(round(float(l), 4))
                volumes.append(int(v) if v and not math.isnan(v) else 0)

    # 2. Extract historical chart series (sampled daily points for UI chart)
    chart_data = []
    if not hist.empty:
        for idx, (dt, row) in enumerate(hist.iterrows()):
            c = row.get("Close")
            if c is not None and not math.isnan(c):
                date_str = dt.strftime("%Y-%m-%d")
                p_slice = prices[: idx + 1]
                s50 = round(sum(p_slice[-50:]) / 50, 2) if len(p_slice) >= 50 else None
                s200 = round(sum(p_slice[-200:]) / 200, 2) if len(p_slice) >= 200 else None
                chart_data.append({
                    "date": date_str,
                    "price": round(float(c), 2),
                    "sma_50": s50,
                    "sma_200": s200,
                })

    # 3. Programmatic Technical Indicators
    technical_indicators = compute_all_technical_indicators(prices, highs, lows)

    # Price summary
    curr_price = info.get("currentPrice") or (prices[-1] if prices else None)
    prev_close = info.get("regularMarketPreviousClose") or (prices[-2] if len(prices) > 1 else curr_price)
    
    change_1d_pct = None
    if curr_price and prev_close:
        change_1d_pct = round(((curr_price - prev_close) / prev_close) * 100.0, 2)

    change_30d_pct = None
    if len(prices) >= 30 and prices[-30] > 0 and curr_price:
        change_30d_pct = round(((curr_price - prices[-30]) / prices[-30]) * 100.0, 2)

    price_data = {
        "current_price":  round(float(curr_price), 4) if curr_price else None,
        "previous_close": round(float(prev_close), 4) if prev_close else None,
        "change_1d_pct":  change_1d_pct,
        "change_30d_pct": change_30d_pct,
        "fifty_two_week_high": info.get("fiftyTwoWeekHigh") or (max(highs) if highs else None),
        "fifty_two_week_low":  info.get("fiftyTwoWeekLow") or (min(lows) if lows else None),
        "average_volume":      info.get("averageVolume") or (int(sum(volumes[-30:]) / 30) if len(volumes) >= 30 else None),
    }

    # 3. Fundamentals
    pe_raw = info.get("trailingPE")
    mcap_raw = info.get("marketCap")
    margin_raw = info.get("profitMargins")
    debt_eq_raw = info.get("debtToEquity")
    roe_raw = info.get("returnOnEquity")
    rev_raw = info.get("totalRevenue")
    rev_growth_raw = info.get("revenueGrowth")
    earn_growth_raw = info.get("earningsGrowth")
    eps_raw = info.get("trailingEps")
    fcf_raw = info.get("freeCashflow")

    fundamentals = {
        "pe_ratio":        round(float(pe_raw), 2) if pe_raw and not math.isnan(pe_raw) else None,
        "market_cap_mil":  round(float(mcap_raw) / 1_000_000, 2) if mcap_raw and not math.isnan(mcap_raw) else None,
        "profit_margin":   round(float(margin_raw) * 100.0, 2) if margin_raw and not math.isnan(margin_raw) else None,
        "debt_to_equity":  round(float(debt_eq_raw), 2) if debt_eq_raw and not math.isnan(debt_eq_raw) else None,
        "roe":             round(float(roe_raw) * 100.0, 2) if roe_raw and not math.isnan(roe_raw) else None,
        "revenue_mil":     round(float(rev_raw) / 1_000_000, 2) if rev_raw and not math.isnan(rev_raw) else None,
        "revenue_growth":  round(float(rev_growth_raw) * 100.0, 2) if rev_growth_raw and not math.isnan(rev_growth_raw) else None,
        "earnings_growth": round(float(earn_growth_raw) * 100.0, 2) if earn_growth_raw and not math.isnan(earn_growth_raw) else None,
        "eps":             round(float(eps_raw), 4) if eps_raw and not math.isnan(eps_raw) else None,
        "free_cash_flow_mil": round(float(fcf_raw) / 1_000_000, 2) if fcf_raw and not math.isnan(fcf_raw) else None,
        "dividend_yield":  round(float(info.get("dividendYield")) * 100.0, 2) if info.get("dividendYield") else None,
    }

    # 4. News from Finnhub
    news = fetch_finnhub_news(finnhub_sym, limit=15)

    # 5. Data Quality Layer
    data_quality = evaluate_data_quality(price_data, fundamentals, news, asset_type)

    # Assemble complete shared snapshot
    snapshot = {
        "symbol":               canonical,
        "company_name":         info.get("shortName") or info.get("longName") or canonical,
        "asset_type":           asset_type,
        "currency":             info.get("currency", "USD" if asset_type == "CRYPTO" else "MYR" if canonical.endswith(".KL") else "USD"),
        "price":                price_data,
        "chart_data":           chart_data,
        "technical_indicators": technical_indicators,
        "fundamentals":         fundamentals,
        "news":                 news,
        "data_quality":         data_quality,
        "data_freshness": {
            "data_timestamp":      now_iso,
            "market_data_as_of":   now_iso,
            "fundamentals_as_of":  now_iso,
            "news_as_of":          now_iso,
        },
    }

    # Save to cache
    _DATA_CACHE[canonical] = {
        "data": snapshot,
        "expires_at": time.time() + CACHE_TTL_SECONDS,
    }

    return snapshot
