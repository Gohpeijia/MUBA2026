# finnhub_service.py
import os
import time
import requests
import yfinance as yf
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

API_KEY = os.getenv('FINNHUB_API_KEY')

# Maps frontend period strings → (resolution, days_back)
PERIOD_MAP = {
    '1D':  ('5m',  '1d'),   
    '1W':  ('15m', '5d'),  
    '1M':  ('1d',  '1mo'),
    '3M':  ('1d',  '3mo'),  
    '1Y':  ('1d',  '1y'),   
    'ALL': ('1wk', 'max'),  
}

def get_live_price(ticker: str):
    """Legacy helper — kept so nothing else breaks."""
    quote = get_rich_market_quote(ticker)
    return quote["price"] if quote else None


def get_rich_market_quote(ticker: str) -> dict:
    
    try:
        # Fetch the stock data
        stock = yf.Ticker(ticker)
        
        # We grab 2 days of history to calculate yesterday's close safely
        hist = stock.history(period="2d")
        if hist.empty:
            return None

        info = stock.info
        
        # Get Current and Previous prices
        current_price = info.get('currentPrice') or hist['Close'].iloc[-1]
        previous_close = info.get('regularMarketPreviousClose') or (hist['Close'].iloc[-2] if len(hist) > 1 else current_price)
        open_price = info.get('regularMarketOpen') or hist['Open'].iloc[-1]
        day_high = info.get('dayHigh') or hist['High'].iloc[-1]
        day_low = info.get('dayLow') or hist['Low'].iloc[-1]

        # Calculate math
        change = current_price - previous_close
        change_percent = (change / previous_close) * 100 if previous_close else 0
        
        change_from_open = current_price - open_price
        change_percent_open = (change_from_open / open_price) * 100 if open_price else 0

        return {
            "price": round(current_price, 2),
            "change": round(change, 2),
            "changePercent": round(change_percent, 2),
            "changeFromOpen": round(change_from_open, 2),
            "changePercentFromOpen": round(change_percent_open, 2),
            "marketStatus": "OPEN", # Yahoo doesn't provide strict market hours natively
            "high": round(day_high, 2),
            "low": round(day_low, 2),
            "open": round(open_price, 2),
            "previousClose": round(previous_close, 2)
        }
    except Exception as e:
        print(f"❌ [Yahoo Finance] Quote Error for {ticker}: {e}")
        return None


def get_company_fundamentals(ticker: str) -> dict:
    """P/E ratio, market cap, net profit margin, debt-to-equity, and more."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        
        # Format Market Cap to Millions (M) to match old code
        market_cap_raw = info.get('marketCap', 0)
        market_cap_m = round(market_cap_raw / 1_000_000, 2) if market_cap_raw else 0

        # Yahoo gives profit margin as decimal (e.g., 0.15 = 15%)
        margin = info.get('profitMargins', 0)
        margin_pct = round(margin * 100, 2) if margin else 0

        debt_equity = info.get('debtToEquity', 0)

        # Grab all the new info we need
        return {
            "name": info.get('shortName') or info.get('longName') or ticker,
            "exchange": info.get('exchange', 'US'),
            "peRatio": round(info.get('trailingPE', 0), 2) if info.get('trailingPE') else None,
            "marketCap": market_cap_m,
            "netProfitMargin": margin_pct,
            "debtToEquity": round(debt_equity, 2) if debt_equity else None,
            "sector": info.get('sector', 'N/A'),
            "industry": info.get('industry', 'N/A'),
            "dividendYield": info.get('dividendYield') if info.get('dividendYield') else None,
            "dividendRate": info.get('dividendRate', None),
            "eps": info.get('trailingEps', None),
            "beta": round(info.get('beta', 0), 2) if info.get('beta') else None,
            "avgVolume": info.get('averageVolume', None),
            "fiftyTwoWeekHigh": info.get('fiftyTwoWeekHigh', None),
            "fiftyTwoWeekLow": info.get('fiftyTwoWeekLow', None),
            "lotSize": 100 # Standard size for US/Bursa markets
        }
    except Exception as e:
        print(f"❌ [Yahoo Finance] Fundamental Error for {ticker}: {e}")
        return {"name": ticker, "peRatio": 0, "marketCap": 0, "netProfitMargin": 0, "debtToEquity": 0}

def get_historical_candles(ticker: str, timeframe: str = '1M') -> list:
    try:
        # 1. Ensure we have a valid timeframe, default to 1M if not
        if timeframe not in PERIOD_MAP:
            timeframe = '1M'
            
        interval, period = PERIOD_MAP[timeframe]
        
        # 2. Fetch from Yahoo Finance
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period, interval=interval)
        
        # 3. Format the data for your React frontend
        candles = []
        for date, row in hist.iterrows():
            # If it's intraday (1D or 1W), show the time. Otherwise, just the date.
            if timeframe in ['1D', '1W']:
                date_str = date.strftime('%Y-%m-%d %H:%M')
            else:
                date_str = date.strftime('%Y-%m-%d')
                
            candles.append({
                "date": date_str,
                "value": round(row['Close'], 2)
            })
            
        return candles
        
    except Exception as e:
        print(f"❌ [Yahoo Finance] Chart Error for {ticker} ({timeframe}): {e}")
        return []