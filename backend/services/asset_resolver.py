# services/asset_resolver.py
#
# Intelligent Asset Resolver for Amanah Investment Intelligence.
#
# Features:
#   - Canonical asset mapping across Equities, Indices, ETFs, Commodities, and Crypto
#   - Alias table matching (e.g. US100 -> QQQ, NDX -> QQQ, Gold -> GLD, Maybank -> 1155.KL)
#   - Typo tolerance & fuzzy matching (e.g. "NASDAS 100" -> QQQ, "Etherium" -> ETH-USD)
#   - Contextual intent extraction from natural language queries
#     ("Should I buy Apple?", "What do you think about NASDAS 100 INDEX?", "How about gold?")

import re
import difflib
from typing import Dict, Any, Optional

# Comprehensive Alias Dictionary
# Key: Normalized alias string (uppercase, no punctuation) -> Canonical asset info
ASSET_ALIAS_DATABASE = {
    # ── INDICES & INDEX ETFS ──
    "NASDAQ 100":       {"symbol": "QQQ",    "name": "NASDAQ 100 (Invesco QQQ)", "asset_type": "INDEX_ETF", "currency": "USD"},
    "NASDAQ100":        {"symbol": "QQQ",    "name": "NASDAQ 100 (Invesco QQQ)", "asset_type": "INDEX_ETF", "currency": "USD"},
    "NASDAQ":           {"symbol": "QQQ",    "name": "NASDAQ 100 (Invesco QQQ)", "asset_type": "INDEX_ETF", "currency": "USD"},
    "NASDAS 100":       {"symbol": "QQQ",    "name": "NASDAQ 100 (Invesco QQQ)", "asset_type": "INDEX_ETF", "currency": "USD"},
    "NASDAS100":        {"symbol": "QQQ",    "name": "NASDAQ 100 (Invesco QQQ)", "asset_type": "INDEX_ETF", "currency": "USD"},
    "NASDAS":           {"symbol": "QQQ",    "name": "NASDAQ 100 (Invesco QQQ)", "asset_type": "INDEX_ETF", "currency": "USD"},
    "NDX":              {"symbol": "QQQ",    "name": "NASDAQ 100 (Invesco QQQ)", "asset_type": "INDEX_ETF", "currency": "USD"},
    "US100":            {"symbol": "QQQ",    "name": "NASDAQ 100 (Invesco QQQ)", "asset_type": "INDEX_ETF", "currency": "USD"},
    "NQ":               {"symbol": "QQQ",    "name": "NASDAQ 100 (Invesco QQQ)", "asset_type": "INDEX_ETF", "currency": "USD"},
    "QQQ":              {"symbol": "QQQ",    "name": "Invesco QQQ Trust (NASDAQ 100)", "asset_type": "INDEX_ETF", "currency": "USD"},
    "TQQQ":             {"symbol": "TQQQ",   "name": "ProShares UltraPro QQQ", "asset_type": "INDEX_ETF", "currency": "USD"},
    "SQQQ":             {"symbol": "SQQQ",   "name": "ProShares UltraPro Short QQQ", "asset_type": "INDEX_ETF", "currency": "USD"},

    "S&P 500":          {"symbol": "SPY",    "name": "S&P 500 ETF Trust (SPY)", "asset_type": "INDEX_ETF", "currency": "USD"},
    "SP500":            {"symbol": "SPY",    "name": "S&P 500 ETF Trust (SPY)", "asset_type": "INDEX_ETF", "currency": "USD"},
    "SPX":              {"symbol": "SPY",    "name": "S&P 500 ETF Trust (SPY)", "asset_type": "INDEX_ETF", "currency": "USD"},
    "SPY":              {"symbol": "SPY",    "name": "SPDR S&P 500 ETF Trust", "asset_type": "INDEX_ETF", "currency": "USD"},
    "VOO":              {"symbol": "VOO",    "name": "Vanguard S&P 500 ETF", "asset_type": "INDEX_ETF", "currency": "USD"},
    "US500":            {"symbol": "SPY",    "name": "S&P 500 ETF Trust (SPY)", "asset_type": "INDEX_ETF", "currency": "USD"},

    "DOW JONES":        {"symbol": "DIA",    "name": "SPDR Dow Jones Industrial Average ETF", "asset_type": "INDEX_ETF", "currency": "USD"},
    "DOW":              {"symbol": "DIA",    "name": "SPDR Dow Jones Industrial Average ETF", "asset_type": "INDEX_ETF", "currency": "USD"},
    "DJI":              {"symbol": "DIA",    "name": "SPDR Dow Jones Industrial Average ETF", "asset_type": "INDEX_ETF", "currency": "USD"},
    "DIA":              {"symbol": "DIA",    "name": "SPDR Dow Jones Industrial Average ETF", "asset_type": "INDEX_ETF", "currency": "USD"},
    "US30":             {"symbol": "DIA",    "name": "SPDR Dow Jones Industrial Average ETF", "asset_type": "INDEX_ETF", "currency": "USD"},

    "RUSSELL 2000":     {"symbol": "IWM",    "name": "iShares Russell 2000 ETF", "asset_type": "INDEX_ETF", "currency": "USD"},
    "RUSSELL":          {"symbol": "IWM",    "name": "iShares Russell 2000 ETF", "asset_type": "INDEX_ETF", "currency": "USD"},
    "IWM":              {"symbol": "IWM",    "name": "iShares Russell 2000 ETF", "asset_type": "INDEX_ETF", "currency": "USD"},

    "KLCI":             {"symbol": "^KLSE",  "name": "FTSE Bursa Malaysia KLCI", "asset_type": "INDEX", "currency": "MYR"},
    "FBMKLCI":          {"symbol": "^KLSE",  "name": "FTSE Bursa Malaysia KLCI", "asset_type": "INDEX", "currency": "MYR"},
    "BURSA MALAYSIA":   {"symbol": "^KLSE",  "name": "FTSE Bursa Malaysia KLCI", "asset_type": "INDEX", "currency": "MYR"},

    # ── COMMODITIES ──
    "GOLD":             {"symbol": "GLD",    "name": "SPDR Gold Shares (GLD)", "asset_type": "COMMODITY_ETF", "currency": "USD"},
    "XAU":              {"symbol": "GLD",    "name": "SPDR Gold Shares (GLD)", "asset_type": "COMMODITY_ETF", "currency": "USD"},
    "XAUUSD":           {"symbol": "GLD",    "name": "SPDR Gold Shares (GLD)", "asset_type": "COMMODITY_ETF", "currency": "USD"},
    "GLD":              {"symbol": "GLD",    "name": "SPDR Gold Shares", "asset_type": "COMMODITY_ETF", "currency": "USD"},
    "SILVER":           {"symbol": "SLV",    "name": "iShares Silver Trust (SLV)", "asset_type": "COMMODITY_ETF", "currency": "USD"},
    "SLV":              {"symbol": "SLV",    "name": "iShares Silver Trust", "asset_type": "COMMODITY_ETF", "currency": "USD"},
    "OIL":              {"symbol": "USO",    "name": "United States Oil Fund (USO)", "asset_type": "COMMODITY_ETF", "currency": "USD"},
    "CRUDE OIL":        {"symbol": "USO",    "name": "United States Oil Fund (USO)", "asset_type": "COMMODITY_ETF", "currency": "USD"},
    "BRENT":            {"symbol": "BNO",    "name": "United States Brent Oil Fund", "asset_type": "COMMODITY_ETF", "currency": "USD"},

    # ── CRYPTOCURRENCIES ──
    "BITCOIN":          {"symbol": "BTC-USD", "name": "Bitcoin", "asset_type": "CRYPTO", "currency": "USD"},
    "BTC":              {"symbol": "BTC-USD", "name": "Bitcoin", "asset_type": "CRYPTO", "currency": "USD"},
    "BTCUSD":           {"symbol": "BTC-USD", "name": "Bitcoin", "asset_type": "CRYPTO", "currency": "USD"},
    "BTCOIN":           {"symbol": "BTC-USD", "name": "Bitcoin", "asset_type": "CRYPTO", "currency": "USD"},
    "ETHEREUM":         {"symbol": "ETH-USD", "name": "Ethereum", "asset_type": "CRYPTO", "currency": "USD"},
    "ETHER":            {"symbol": "ETH-USD", "name": "Ethereum", "asset_type": "CRYPTO", "currency": "USD"},
    "ETH":              {"symbol": "ETH-USD", "name": "Ethereum", "asset_type": "CRYPTO", "currency": "USD"},
    "ETHUSD":           {"symbol": "ETH-USD", "name": "Ethereum", "asset_type": "CRYPTO", "currency": "USD"},
    "ETHERIUM":         {"symbol": "ETH-USD", "name": "Ethereum", "asset_type": "CRYPTO", "currency": "USD"},
    "SOLANA":           {"symbol": "SOL-USD", "name": "Solana", "asset_type": "CRYPTO", "currency": "USD"},
    "SOL":              {"symbol": "SOL-USD", "name": "Solana", "asset_type": "CRYPTO", "currency": "USD"},
    "RIPPLE":           {"symbol": "XRP-USD", "name": "XRP", "asset_type": "CRYPTO", "currency": "USD"},
    "XRP":              {"symbol": "XRP-USD", "name": "XRP", "asset_type": "CRYPTO", "currency": "USD"},
    "BINANCE COIN":     {"symbol": "BNB-USD", "name": "BNB", "asset_type": "CRYPTO", "currency": "USD"},
    "BNB":              {"symbol": "BNB-USD", "name": "BNB", "asset_type": "CRYPTO", "currency": "USD"},
    "CARDANO":          {"symbol": "ADA-USD", "name": "Cardano", "asset_type": "CRYPTO", "currency": "USD"},
    "ADA":              {"symbol": "ADA-USD", "name": "Cardano", "asset_type": "CRYPTO", "currency": "USD"},
    "DOGECOIN":         {"symbol": "DOGE-USD", "name": "Dogecoin", "asset_type": "CRYPTO", "currency": "USD"},
    "DOGE":             {"symbol": "DOGE-USD", "name": "Dogecoin", "asset_type": "CRYPTO", "currency": "USD"},

    # ── US EQUITIES (MEGA-CAPS & TECH) ──
    "APPLE":            {"symbol": "AAPL",   "name": "Apple Inc.", "asset_type": "EQUITY_US", "currency": "USD"},
    "AAPL":             {"symbol": "AAPL",   "name": "Apple Inc.", "asset_type": "EQUITY_US", "currency": "USD"},
    "APLE":             {"symbol": "AAPL",   "name": "Apple Inc.", "asset_type": "EQUITY_US", "currency": "USD"},
    "MICROSOFT":        {"symbol": "MSFT",   "name": "Microsoft Corporation", "asset_type": "EQUITY_US", "currency": "USD"},
    "MSFT":             {"symbol": "MSFT",   "name": "Microsoft Corporation", "asset_type": "EQUITY_US", "currency": "USD"},
    "MICROSFT":         {"symbol": "MSFT",   "name": "Microsoft Corporation", "asset_type": "EQUITY_US", "currency": "USD"},
    "GOOGLE":           {"symbol": "GOOGL",  "name": "Alphabet Inc. (Google)", "asset_type": "EQUITY_US", "currency": "USD"},
    "ALPHABET":         {"symbol": "GOOGL",  "name": "Alphabet Inc. (Google)", "asset_type": "EQUITY_US", "currency": "USD"},
    "GOOGL":            {"symbol": "GOOGL",  "name": "Alphabet Inc. (Google)", "asset_type": "EQUITY_US", "currency": "USD"},
    "GOOG":             {"symbol": "GOOG",   "name": "Alphabet Inc. (Google)", "asset_type": "EQUITY_US", "currency": "USD"},
    "AMAZON":           {"symbol": "AMZN",   "name": "Amazon.com Inc.", "asset_type": "EQUITY_US", "currency": "USD"},
    "AMZN":             {"symbol": "AMZN",   "name": "Amazon.com Inc.", "asset_type": "EQUITY_US", "currency": "USD"},
    "NVIDIA":           {"symbol": "NVDA",   "name": "NVIDIA Corporation", "asset_type": "EQUITY_US", "currency": "USD"},
    "NVDA":             {"symbol": "NVDA",   "name": "NVIDIA Corporation", "asset_type": "EQUITY_US", "currency": "USD"},
    "NVDIA":            {"symbol": "NVDA",   "name": "NVIDIA Corporation", "asset_type": "EQUITY_US", "currency": "USD"},
    "MICRON": {
    "symbol": "MU",
    "name": "Micron Technology Inc.",
    "asset_type": "EQUITY_US",
    "currency": "USD"
},

"MU": {
    "symbol": "MU",
    "name": "Micron Technology Inc.",
    "asset_type": "EQUITY_US",
    "currency": "USD"
},
    "TESLA":            {"symbol": "TSLA",   "name": "Tesla Inc.", "asset_type": "EQUITY_US", "currency": "USD"},
    "TSLA":             {"symbol": "TSLA",   "name": "Tesla Inc.", "asset_type": "EQUITY_US", "currency": "USD"},
    "META":             {"symbol": "META",   "name": "Meta Platforms Inc. (Facebook)", "asset_type": "EQUITY_US", "currency": "USD"},
    "FACEBOOK":         {"symbol": "META",   "name": "Meta Platforms Inc. (Facebook)", "asset_type": "EQUITY_US", "currency": "USD"},
    "NETFLIX":          {"symbol": "NFLX",   "name": "Netflix Inc.", "asset_type": "EQUITY_US", "currency": "USD"},
    "NFLX":             {"symbol": "NFLX",   "name": "Netflix Inc.", "asset_type": "EQUITY_US", "currency": "USD"},
    "AMD":              {"symbol": "AMD",    "name": "Advanced Micro Devices Inc.", "asset_type": "EQUITY_US", "currency": "USD"},
    "INTEL":            {"symbol": "INTC",   "name": "Intel Corporation", "asset_type": "EQUITY_US", "currency": "USD"},
    "INTC":             {"symbol": "INTC",   "name": "Intel Corporation", "asset_type": "EQUITY_US", "currency": "USD"},
    "BERKSHIRE":        {"symbol": "BRK-B",  "name": "Berkshire Hathaway Inc.", "asset_type": "EQUITY_US", "currency": "USD"},
    "JPMORGAN":         {"symbol": "JPM",    "name": "JPMorgan Chase & Co.", "asset_type": "EQUITY_US", "currency": "USD"},
    "JPM":              {"symbol": "JPM",    "name": "JPMorgan Chase & Co.", "asset_type": "EQUITY_US", "currency": "USD"},
    "VISA":             {"symbol": "V",      "name": "Visa Inc.", "asset_type": "EQUITY_US", "currency": "USD"},
    "MASTERCARD":       {"symbol": "MA",     "name": "Mastercard Inc.", "asset_type": "EQUITY_US", "currency": "USD"},
    "EXXON":            {"symbol": "XOM",    "name": "Exxon Mobil Corporation", "asset_type": "EQUITY_US", "currency": "USD"},
    "XOM":              {"symbol": "XOM",    "name": "Exxon Mobil Corporation", "asset_type": "EQUITY_US", "currency": "USD"},
    "COCA COLA":        {"symbol": "KO",     "name": "The Coca-Cola Company", "asset_type": "EQUITY_US", "currency": "USD"},
    "COKE":             {"symbol": "KO",     "name": "The Coca-Cola Company", "asset_type": "EQUITY_US", "currency": "USD"},
    "KO":               {"symbol": "KO",     "name": "The Coca-Cola Company", "asset_type": "EQUITY_US", "currency": "USD"},
    "PEPSI":            {"symbol": "PEP",    "name": "PepsiCo Inc.", "asset_type": "EQUITY_US", "currency": "USD"},
    "DISNEY":           {"symbol": "DIS",    "name": "The Walt Disney Company", "asset_type": "EQUITY_US", "currency": "USD"},
    "DIS":              {"symbol": "DIS",    "name": "The Walt Disney Company", "asset_type": "EQUITY_US", "currency": "USD"},
    "ALIBABA":          {"symbol": "BABA",   "name": "Alibaba Group Holding Ltd.", "asset_type": "EQUITY_US", "currency": "USD"},
    "BABA":             {"symbol": "BABA",   "name": "Alibaba Group Holding Ltd.", "asset_type": "EQUITY_US", "currency": "USD"},
    "TSMC":             {"symbol": "TSM",    "name": "Taiwan Semiconductor Manufacturing Co.", "asset_type": "EQUITY_US", "currency": "USD"},
    "TSM":              {"symbol": "TSM",    "name": "Taiwan Semiconductor Manufacturing Co.", "asset_type": "EQUITY_US", "currency": "USD"},

    # ── BURSA MALAYSIA EQUITIES ──
    "MAYBANK":          {"symbol": "1155.KL", "name": "Malayan Banking Berhad (Maybank)", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "1155":             {"symbol": "1155.KL", "name": "Malayan Banking Berhad (Maybank)", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "1155.KL":          {"symbol": "1155.KL", "name": "Malayan Banking Berhad (Maybank)", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "MAYBNK":           {"symbol": "1155.KL", "name": "Malayan Banking Berhad (Maybank)", "asset_type": "EQUITY_BURSA", "currency": "MYR"},

    "CIMB":             {"symbol": "1023.KL", "name": "CIMB Group Holdings Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "1023":             {"symbol": "1023.KL", "name": "CIMB Group Holdings Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "1023.KL":          {"symbol": "1023.KL", "name": "CIMB Group Holdings Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},

    "PUBLIC BANK":      {"symbol": "1295.KL", "name": "Public Bank Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "PBBANK":           {"symbol": "1295.KL", "name": "Public Bank Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "1295":             {"symbol": "1295.KL", "name": "Public Bank Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "1295.KL":          {"symbol": "1295.KL", "name": "Public Bank Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},

    "TENAGA":           {"symbol": "5347.KL", "name": "Tenaga Nasional Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "TNB":              {"symbol": "5347.KL", "name": "Tenaga Nasional Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "5347":             {"symbol": "5347.KL", "name": "Tenaga Nasional Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "5347.KL":          {"symbol": "5347.KL", "name": "Tenaga Nasional Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},

    "PETRONAS CHEMICALS": {"symbol": "5183.KL", "name": "Petronas Chemicals Group Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "PCHEM":            {"symbol": "5183.KL", "name": "Petronas Chemicals Group Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "5183":             {"symbol": "5183.KL", "name": "Petronas Chemicals Group Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "5183.KL":          {"symbol": "5183.KL", "name": "Petronas Chemicals Group Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},

    "IHH":              {"symbol": "5225.KL", "name": "IHH Healthcare Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "5225":             {"symbol": "5225.KL", "name": "IHH Healthcare Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "5225.KL":          {"symbol": "5225.KL", "name": "IHH Healthcare Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},

    "CELCOMDIGI":       {"symbol": "6947.KL", "name": "CelcomDigi Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "DIGI":             {"symbol": "6947.KL", "name": "CelcomDigi Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "6947":             {"symbol": "6947.KL", "name": "CelcomDigi Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "6947.KL":          {"symbol": "6947.KL", "name": "CelcomDigi Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},

    "MAXIS":            {"symbol": "6012.KL", "name": "Maxis Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "6012":             {"symbol": "6012.KL", "name": "Maxis Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "6012.KL":          {"symbol": "6012.KL", "name": "Maxis Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},

    "AXIATA":           {"symbol": "6888.KL", "name": "Axiata Group Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "6888":             {"symbol": "6888.KL", "name": "Axiata Group Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "6888.KL":          {"symbol": "6888.KL", "name": "Axiata Group Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},

    "YTL":              {"symbol": "4677.KL", "name": "YTL Corporation Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "4677":             {"symbol": "4677.KL", "name": "YTL Corporation Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "4677.KL":          {"symbol": "4677.KL", "name": "YTL Corporation Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},

    "MISC":             {"symbol": "3816.KL", "name": "MISC Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "3816":             {"symbol": "3816.KL", "name": "MISC Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "3816.KL":          {"symbol": "3816.KL", "name": "MISC Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},

    "NESTLE":           {"symbol": "4707.KL", "name": "Nestle (Malaysia) Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "4707":             {"symbol": "4707.KL", "name": "Nestle (Malaysia) Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "4707.KL":          {"symbol": "4707.KL", "name": "Nestle (Malaysia) Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},

    "SIME DARBY":       {"symbol": "4197.KL", "name": "Sime Darby Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "SIME":             {"symbol": "4197.KL", "name": "Sime Darby Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "4197":             {"symbol": "4197.KL", "name": "Sime Darby Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "4197.KL":          {"symbol": "4197.KL", "name": "Sime Darby Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},

    "KLCC":             {"symbol": "5235SS.KL", "name": "KLCC Property Holdings Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "BIMB":             {"symbol": "5258.KL", "name": "Bank Islam Malaysia Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "INARI":            {"symbol": "0166.KL", "name": "Inari Amertron Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
    "GAMUDA":           {"symbol": "5398.KL", "name": "Gamuda Berhad", "asset_type": "EQUITY_BURSA", "currency": "MYR"},
}


def clean_text_for_matching(text: str) -> str:
    """Normalizes text by removing special chars and converting to uppercase."""
    # Replace punctuation with spaces
    cleaned = re.sub(r"[^A-Za-z0-9\.\s\-\^]", " ", text)
    return " ".join(cleaned.upper().split())


def resolve_asset_from_query(query: str, page_context: str = "") -> Optional[Dict[str, Any]]:
    """
    Intelligently extracts and resolves the underlying asset from user queries.
    Handles typos ('NASDAS 100'), aliases ('NDX', 'US100'), Bursa stock codes, and natural language.

    Returns:
      {
        "resolved": True,
        "symbol": "QQQ",
        "canonical_name": "NASDAQ 100 (Invesco QQQ)",
        "asset_type": "INDEX_ETF",
        "currency": "USD",
        "matched_term": "NASDAS 100"
      }
      or None if no financial asset is being inquired about.
    """
    if not query:
        return None

    full_text = f"{query} {page_context}"
    normalized_text = clean_text_for_matching(full_text)

    # 1. Exact Substring Match in Alias Database (longest matches first)
    # Sort aliases by length descending so "NASDAQ 100" matches before "NASDAQ"
    sorted_aliases = sorted(ASSET_ALIAS_DATABASE.keys(), key=lambda k: len(k), reverse=True)

    for alias in sorted_aliases:
        # Check boundary match
        pattern = r"(?:\b|^)" + re.escape(alias) + r"(?:\b|$)"
        if re.search(pattern, normalized_text):
            asset_info = ASSET_ALIAS_DATABASE[alias]
            return {
                "resolved":       True,
                "symbol":         asset_info["symbol"],
                "canonical_name": asset_info["name"],
                "asset_type":     asset_info["asset_type"],
                "currency":       asset_info["currency"],
                "matched_term":   alias,
            }

    # 2. Check for Bursa 4-digit codes: e.g. "1155.KL" or "1155"
    bursa_match = re.search(r"\b([0-9]{4})\.KL\b", normalized_text)
    if bursa_match:
        code = bursa_match.group(1)
        sym = f"{code}.KL"
        return {
            "resolved":       True,
            "symbol":         sym,
            "canonical_name": f"Bursa Security {sym}",
            "asset_type":     "EQUITY_BURSA",
            "currency":       "MYR",
            "matched_term":   sym,
        }

    # 3. Fuzzy / Typo Matching on Phrases (e.g. "NASDAS 100", "ETHERIUM", "APLE", "MAYBNK")
    words = normalized_text.split()
    # Check 1-word, 2-word, and 3-word n-grams
    ngrams = []
    for i in range(len(words)):
        ngrams.append(words[i])
        if i + 1 < len(words):
            ngrams.append(f"{words[i]} {words[i+1]}")
        if i + 2 < len(words):
            ngrams.append(f"{words[i]} {words[i+1]} {words[i+2]}")

    for candidate in ngrams:
        # Match against aliases
        matches = difflib.get_close_matches(candidate, ASSET_ALIAS_DATABASE.keys(), n=1, cutoff=0.82)
        if matches:
            best_alias = matches[0]
            # Ignore false matches on short words (e.g. 1-2 char words)
            if len(best_alias) >= 3 and len(candidate) >= 3:
                asset_info = ASSET_ALIAS_DATABASE[best_alias]
                print(f"🎯 [AssetResolver] Fuzzy match: '{candidate}' -> '{best_alias}' ({asset_info['symbol']})")
                return {
                    "resolved":       True,
                    "symbol":         asset_info["symbol"],
                    "canonical_name": asset_info["name"],
                    "asset_type":     asset_info["asset_type"],
                    "currency":       asset_info["currency"],
                    "matched_term":   candidate,
                }

    # 4. Standalone Ticker pattern (e.g. "$AAPL", "ticker TSLA", "stock GOOGL")
    ticker_match = re.search(r"(?:\$|ticker\s+|stock\s+|shares\s+)([A-Z]{1,5})\b", normalized_text)
    if ticker_match:
        sym = ticker_match.group(1)
        return {
            "resolved":       True,
            "symbol":         sym,
            "canonical_name": sym,
            "asset_type":     "EQUITY_US",
            "currency":       "USD",
            "matched_term":   sym,
        }

    return None
