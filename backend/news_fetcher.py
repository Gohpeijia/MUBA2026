# pengambil_data_saham.py
# Fetch price, fundamentals, and sentiment before the AI agents make a decision.
# Menggunakan yfinance (percuma, tiada API key diperlukan).
#
# Pasang: pip install yfinance httpx

import yfinance as yf
import os
from dotenv import load_dotenv
import httpx
import asyncio
from datetime import datetime
from typing import Optional

load_dotenv()
# ── Konfigurasi ───────────────────────────────────────────────────────────────
YOUR_FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")  

# Peta ticker Bursa Malaysia → simbol Yahoo Finance
PETA_TICKER_BURSA = {
    "MAYBANK":  "1155.KL",
    "CIMB":     "1023.KL",
    "PBBANK":   "1295.KL",
    "TENAGA":   "5347.KL",
    "PCHEM":    "5183.KL",
    "AXIATA":   "6888.KL",
    "DIGI":     "6947.KL",
    "MAXIS":    "6012.KL",
    "GENTING":  "3182.KL",
    "IOICORP":  "1961.KL",
    "BIMB":     "5258.KL",
    "AFFIN":    "5185.KL",
    "RHBBANK":  "1066.KL",
    "AMBANK":   "1015.KL",
    "HLBANK":   "5819.KL",
    "KLCC":     "5235SS.KL",
    "IHH":      "5225.KL",
    "NESTLE":   "4707.KL",
    "PETDAG":   "5681.KL",
    "DIALOG":   "7277.KL",
}

# Peta ticker Bursa → simbol Finnhub
PETA_TICKER_FINNHUB = {
    "MAYBANK":  "MBBM.KL",
    "CIMB":     "CIMB.KL",
    "PBBANK":   "PBKF.KL",
}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 - Fetch price and financial fundamentals (yfinance)
# ══════════════════════════════════════════════════════════════════════════════

def _adalah_simbol_lengkap(ticker: str) -> bool:
    return "-" in ticker.upper()

def ambil_data_harga_dan_asas(ticker: str) -> dict:
    """
    Fetch current price data and financial fundamentals from Yahoo Finance.
    No API key required.

    Data fetched:
    - Current price, percent change, volume
    - P/E ratio, debt ratio, return on equity (ROE)
    - 52-week high/low
    - 50-day and 200-day moving averages
    """
    ticker_bersih = ticker.upper().replace(".KL", "")
    if ticker_bersih in ("ETH", "BTC", "ETH-USD", "BTC-USD") or "-USD" in ticker_bersih:
        simbol_yahoo = f"{ticker_bersih.replace('-USD', '')}-USD"
    else:
        simbol_yahoo = PETA_TICKER_BURSA.get(ticker_bersih, f"{ticker_bersih}.KL")

    try:
        saham = yf.Ticker(simbol_yahoo)
        maklumat = saham.info

        if not maklumat or maklumat.get("regularMarketPrice") is None:
            return _data_kosong(ticker, "Yahoo Finance did not return data.")

        # Price.
        harga_semasa   = maklumat.get("regularMarketPrice",         None)
        harga_buka     = maklumat.get("regularMarketOpen",          None)
        harga_tutup    = maklumat.get("previousClose",              None)
        perubahan_pct  = maklumat.get("regularMarketChangePercent", None)
        volum          = maklumat.get("regularMarketVolume",        None)
        tinggi_52mggu  = maklumat.get("fiftyTwoWeekHigh",           None)
        rendah_52mggu  = maklumat.get("fiftyTwoWeekLow",            None)
        ma_50          = maklumat.get("fiftyDayAverage",            None)
        ma_200         = maklumat.get("twoHundredDayAverage",       None)

        # Financial fundamentals.
        nisbah_pe         = maklumat.get("trailingPE",            None)
        nisbah_pb         = maklumat.get("priceToBook",           None)
        nisbah_hutang     = maklumat.get("debtToEquity",          None)  # percent
        pulangan_ekuiti   = maklumat.get("returnOnEquity",        None)
        margin_keuntungan = maklumat.get("profitMargins",         None)
        perolehan_sesaham = maklumat.get("trailingEps",           None)
        dividen_hasil     = maklumat.get("dividendYield",         None)
        permodalan_pasaran= maklumat.get("marketCap",             None)
        hasil_semasa      = maklumat.get("totalRevenue",          None)

        # Technical signal based on moving averages.
        isyarat_teknikal = "Neutral ⏸️"
        if harga_semasa and ma_50 and ma_200:
            if harga_semasa > ma_50 > ma_200:
                isyarat_teknikal = "Bullish 📈"
            elif harga_semasa < ma_50 < ma_200:
                isyarat_teknikal = "Bearish 📉"
            elif harga_semasa > ma_50:
                isyarat_teknikal = "Slightly Positive 📈"
            else:
                isyarat_teknikal = "Slightly Negative 📉"

        # Debt ratio for Shariah screening.
        # Convert nisbah_hutang from percent to decimal (33% Shariah threshold = 0.33).
        nisbah_hutang_syariah = None
        if nisbah_hutang is not None:
            nisbah_hutang_syariah = round(nisbah_hutang / 100, 4)

        return {
            "ticker":         ticker,
            "simbol_yahoo":   simbol_yahoo,
            "berjaya":        True,
            "harga": {
                "semasa":        harga_semasa,
                "buka":          harga_buka,
                "tutup_semalam": harga_tutup,
                "perubahan_pct": round(perubahan_pct, 2) if perubahan_pct else None,
                "volum":         volum,
                "tinggi_52mggu": tinggi_52mggu,
                "rendah_52mggu": rendah_52mggu,
                "ma_50":         round(ma_50, 4) if ma_50 else None,
                "ma_200":        round(ma_200, 4) if ma_200 else None,
                "isyarat_teknikal": isyarat_teknikal,
            },
            "asas_kewangan": {
                "nisbah_pe":          round(nisbah_pe, 2) if nisbah_pe else None,
                "nisbah_pb":          round(nisbah_pb, 2) if nisbah_pb else None,
                "nisbah_hutang":      nisbah_hutang_syariah,
                "pulangan_ekuiti":    round(pulangan_ekuiti * 100, 2) if pulangan_ekuiti else None,
                "margin_keuntungan":  round(margin_keuntungan * 100, 2) if margin_keuntungan else None,
                "perolehan_sesaham":  perolehan_sesaham,
                "dividen_hasil":      round(dividen_hasil * 100, 2) if dividen_hasil else None,
                "permodalan_pasaran": permodalan_pasaran,
                "hasil_semasa":       hasil_semasa,
            },
            "masa_dikemaskini": datetime.now().isoformat(),
        }

    except Exception as ralat:
        return _data_kosong(ticker, str(ralat))


def _data_kosong(ticker: str, sebab: str) -> dict:
    """Return an empty data structure when fetching fails."""
    return {
        "ticker":           ticker,
        "berjaya":          False,
        "sebab_gagal":      sebab,
        "harga":            {},
        "asas_kewangan":    {},
        "masa_dikemaskini": datetime.now().isoformat(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 - Fetch news sentiment (Finnhub)
# ══════════════════════════════════════════════════════════════════════════════

async def ambil_sentimen_berita(ticker: str) -> dict:
    
    if _adalah_simbol_lengkap(ticker):
        return {
        "berjaya": False,
        "sebab":   "Company news sentiment does not apply to crypto.",
        "skor":    0.5,
        "label":   "Neutral ⏸️",
        "isyarat": "HOLD",
        }
    
    """
    Fetch news sentiment score from Finnhub.
    Returns a 0.0-1.0 score and an English label.
    """
    ticker_bersih = ticker.upper().replace(".KL", "")
    if ticker_bersih in ("ETH", "BTC", "ETH-USD", "BTC-USD") or "-USD" in ticker_bersih:
        clean_crypto = ticker_bersih.replace("-USD", "")
        simbol = f"BINANCE:{clean_crypto}USDT"
    else:
        simbol = PETA_TICKER_FINNHUB.get(ticker_bersih, f"{ticker_bersih}.KL")
    url    = "https://finnhub.io/api/v1/news-sentiment"
    params = {"symbol": simbol, "token": YOUR_FINNHUB_API_KEY}

    try:
        async with httpx.AsyncClient(timeout=10) as klien:
            resp = await klien.get(url, params=params)
            if resp.status_code != 200:
                raise ValueError(f"Kod HTTP {resp.status_code}")
            data = resp.json()

        skor = data.get("companyNewsScore", 0.5)

        if skor >= 0.65:
            label = "Sangat Positif 📈"
            isyarat = "STRONGLY_BUY"
        elif skor >= 0.55:
            label = "Positif 📈"
            isyarat = "BUY"
        elif skor >= 0.45:
            label = "Neutral ⏸️"
            isyarat = "HOLD"
        elif skor >= 0.35:
            label = "Negatif 📉"
            isyarat = "SELL"
        else:
            label = "Sangat Negatif 📉"
            isyarat = "STRONGLY_SELL"

        return {
            "berjaya":        True,
            "skor":           round(skor, 3),
            "label":          label,
            "isyarat":        isyarat,
            "bilangan_artikel": data.get("buzz", {}).get("articlesInLastWeek", 0),
            "purata_sektor":  round(data.get("sectorAverageBullishPercent", 0.5), 3),
        }

    except Exception as ralat:
        return {
            "berjaya": False,
            "sebab":   str(ralat),
            "skor":    0.5,
            "label":   "Neutral ⏸️",
            "isyarat": "HOLD",
        }


# ══════════════════════════════════════════════════════════════════════════════
# BAHAGIAN 3 — Gabung semua data ke dalam `quantitative` dict
# ══════════════════════════════════════════════════════════════════════════════

async def bina_data_kuantitatif(
    ticker:        str,
    is_compliant:  bool,
    sebab_syariah: str,
) -> dict:
    """
    Fungsi UTAMA — bina dict `quantitative` yang lengkap untuk dihantar ke agen AI.

    Dict ini MENGGANTIKAN dict quantitative kosong dalam pipeline anda.
    Semua agen (TREND_AGENT, SENTIMENT_AGENT, FUNDAMENTALS_AGENT, dll.)
    akan membaca dari sini.

    Cara guna:
        quant = await bina_data_kuantitatif("MAYBANK", is_compliant=False, sebab_syariah="...")
        prompt = manager.format_agent_input(user_input, quant, page, consensus)
    """
    # Jalankan serentak untuk jimat masa
    data_saham, data_sentimen = await asyncio.gather(
        asyncio.to_thread(ambil_data_harga_dan_asas, ticker),
        ambil_sentimen_berita(ticker),
    )

    harga = data_saham.get("harga", {})
    asas  = data_saham.get("asas_kewangan", {})

    return {
        # ── Medan sedia ada (dikekalkan supaya kod lama tidak pecah) ────────
        "ticker":        ticker,
        "is_compliant":  is_compliant,
        "reason":        sebab_syariah,

        # ── Data harga (untuk TREND_AGENT) ──────────────────────────────────
        "harga_semasa":         harga.get("semasa"),
        "perubahan_harga_pct":  harga.get("perubahan_pct"),
        "volum":                harga.get("volum"),
        "tinggi_52_minggu":     harga.get("tinggi_52mggu"),
        "rendah_52_minggu":     harga.get("rendah_52mggu"),
        "purata_bergerak_50":   harga.get("ma_50"),
        "purata_bergerak_200":  harga.get("ma_200"),
        "isyarat_teknikal":     harga.get("isyarat_teknikal", "Neutral ⏸️"),

        # Core financial data for FUNDAMENTALS_AGENT and VALUE_SNIPER.
        "nisbah_pe":            asas.get("nisbah_pe"),
        "nisbah_pb":            asas.get("nisbah_pb"),
        "nisbah_hutang":        asas.get("nisbah_hutang"),       # for Shariah screening
        "pulangan_ekuiti":      asas.get("pulangan_ekuiti"),
        "margin_keuntungan":    asas.get("margin_keuntungan"),
        "perolehan_sesaham":    asas.get("perolehan_sesaham"),
        "dividen_hasil":        asas.get("dividen_hasil"),
        "permodalan_pasaran":   asas.get("permodalan_pasaran"),

        # News sentiment data for SENTIMENT_AGENT.
        "skor_sentimen":        data_sentimen.get("skor", 0.5),
        "label_sentimen":       data_sentimen.get("label", "Neutral ⏸️"),
        "isyarat_sentimen":     data_sentimen.get("isyarat", "HOLD"),
        "bilangan_artikel_berita": data_sentimen.get("bilangan_artikel", 0),

        # ── Metadata ──────────────────────────────────────────────────────────
        "data_harga_tersedia":     data_saham.get("berjaya", False),
        "data_sentimen_tersedia":  data_sentimen.get("berjaya", False),
        "masa_dikemaskini":        datetime.now().isoformat(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# BAHAGIAN 4 — Format data untuk dimasukkan ke dalam prompt teks
# ══════════════════════════════════════════════════════════════════════════════

def format_data_untuk_prompt(quant: dict) -> str:
    """
    Tukar dict quantitative kepada blok teks ringkas untuk disuntik
    ke dalam ShariahAdvisorPromptManager.format_agent_input()
    sebagai bahagian 'DATA BERITA TERKINI'.
    """
    def fmt(nilai, suffix="", tiada="Tiada data"):
        return f"{nilai}{suffix}" if nilai is not None else tiada

    harga    = quant.get("harga_semasa")
    perubahan= quant.get("perubahan_harga_pct")
    arah     = "▲" if (perubahan or 0) > 0 else "▼"

    return f"""
📊 LATEST MARKET DATA ({quant.get('ticker', '')}):

💹 Price & Technicals:
  • Current Price   : {fmt(harga)}  {arah} {fmt(perubahan, "%")}
  • 52-Week High    : {fmt(quant.get('tinggi_52_minggu'))}
  • 52-Week Low     : {fmt(quant.get('rendah_52_minggu'))}
  • 50-Day MA       : {fmt(quant.get('purata_bergerak_50'))}
  • 200-Day MA      : {fmt(quant.get('purata_bergerak_200'))}
  • Technical Signal: {quant.get('isyarat_teknikal', 'Neutral ⏸️')}

📋 Financial Fundamentals:
  • P/E Ratio       : {fmt(quant.get('nisbah_pe'), "x")}
  • P/B Ratio       : {fmt(quant.get('nisbah_pb'), "x")}
  • Debt/Equity     : {fmt(quant.get('nisbah_hutang'), " (Shariah limit: 0.33)")}
  • Return on Equity: {fmt(quant.get('pulangan_ekuiti'), "%")}
  • Profit Margin   : {fmt(quant.get('margin_keuntungan'), "%")}
  • Dividend Yield  : {fmt(quant.get('dividen_hasil'), "%")}

💬 News Sentiment:
  • Sentiment Score : {fmt(quant.get('skor_sentimen'))} → {quant.get('label_sentimen', 'Neutral')}
  • Article Count   : {fmt(quant.get('bilangan_artikel_berita'), " articles (last 7 days)")}
"""
