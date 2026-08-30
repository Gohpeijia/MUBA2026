import React, { useState, useCallback, useEffect, useRef } from 'react';
import './stocks.css';

import { db, auth } from '../firebase';
import { doc, getDoc, setDoc } from 'firebase/firestore';
import { onAuthStateChanged } from 'firebase/auth';

import StockSidePanel  from './components/StockSidePanel';
import StockSearchBar  from './components/StockSearchBar';
import StockHeader     from './components/StockHeader';
import StockChart      from './components/StockChart';
import StockDetails    from './components/StockDetails';

/* ─────────────────────────────────────────────────────────────────────────────
   CONFIG
   ───────────────────────────────────────────────────────────────────────────── */
const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:5000';

async function getAuthToken() {
  if (!auth.currentUser) throw new Error('User not logged in');
  return auth.currentUser.getIdToken();
}

/* ─────────────────────────────────────────────────────────────────────────────
   API HELPERS
   ───────────────────────────────────────────────────────────────────────────── */

/**
 * Search — /market/search?q=<query>
 * Now correctly receives { ticker, name, exchange } from the fixed backend.
 */
async function apiSearchStocks(query) {
  try {
    // If not logged in, search without auth so you can still see results
    const headers = {};
    if (auth.currentUser) {
      const token = await auth.currentUser.getIdToken();
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(
       `${BACKEND_URL}/api/stocks/market/search?q=${encodeURIComponent(query)}`,
        { headers }
    );
    const result = await response.json();
    if (result.success) return result.data;
    console.error('Search failed:', result.error);
    return [];
  } catch (err) {
    console.error('Search error:', err);
    return [];
  }
}

/**
 * Quote + Details — /market/details/<ticker>
 * ONE call returns everything needed for both StockHeader and StockDetails.
 * No more duplicate Finnhub round-trips.
 */
async function apiFetchStockData(ticker) {
  const token    = await getAuthToken();
  const response = await fetch(
    `${BACKEND_URL}/api/stocks/market/details/${ticker}`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  const result = await response.json();
  if (!result.success) throw new Error(result.error);

  const d = result.data;

  const quote = {
    ticker:     d.ticker,
    name:       d.ticker,   // Finnhub /details doesn't return a display name; ticker is fine here
    exchange:   'US',
    price:      d.price,
    change:     d.change,
    changePct:  d.changePercent,
    marketStatus: d.marketStatus,
  };

  const details = {
    statusSyariah: d.isHalal !== undefined ? (d.isHalal ? 'Patuh Syariah ✅' : 'Tidak Patuh Syariah ❌') : '—',
    sector:        d.sector || '—',
    industry:      d.industry || '—',
    marketCap:     d.marketCap ? `$${(d.marketCap / 1000).toFixed(2)}B` : '—',
    peRatio:       d.peRatio ? d.peRatio.toFixed(2) : '—',
    eps:           d.eps !== undefined && d.eps !== null ? d.eps.toFixed(2) : '—',
    beta:          d.beta !== undefined && d.beta !== null ? d.beta.toFixed(2) : '—',
    
    // 1. ADDED BACK: Hasil Dividen (%)
    dividendYield: d.dividendYield !== undefined && d.dividendYield !== null ? `${Number(d.dividendYield).toFixed(2)}%` : '—',
    
    // 2. FIXED: Checking for undefined/null so $0 dividends and 0 metrics still display correctly
    dividendAmount: d.dividendAmount !== undefined && d.dividendAmount !== null ? `$${Number(d.dividendAmount).toFixed(2)}` : '—',
    volume:         d.volume !== undefined && d.volume !== null ? Number(d.volume).toLocaleString() : '—',
    high52:         d.high52 !== undefined && d.high52 !== null ? `$${Number(d.high52).toFixed(2)}` : '—',
    low52:          d.low52 !== undefined && d.low52 !== null ? `$${Number(d.low52).toFixed(2)}` : '—',
    
    lotSize:        '100', 
  };

  return { quote, details };
}

/**
 * Chart — /market/chart/<ticker>?period=<period>
 * Uses the new dedicated chart endpoint (no more /portfolio/stock/).
 */
async function apiFetchChart(ticker, period) {
  const token    = await getAuthToken();
  const response = await fetch(
  `${BACKEND_URL}/api/stocks/market/chart/${ticker}?period=${period}`,
  { headers: { Authorization: `Bearer ${token}` } }
);
  const result = await response.json();
  if (!result.success) throw new Error(result.error);

  // Backend returns [{ date, value }]; map to [{ label, price }] for recharts
  const chartData = result.data.chartData.map(item => ({
    label: item.date,
    price: item.value,
  }));

  return { data: chartData, high: result.data.high, low: result.data.low };
}

/* ─────────────────────────────────────────────────────────────────────────────
   MAIN COMPONENT
   ───────────────────────────────────────────────────────────────────────────── */
export default function Stocks() {
  const [watchlist,     setWatchlist]     = useState([]);
  const watchlistLoaded = useRef(false); 
  const [activeTicker,  setActiveTicker]  = useState(null);
  const [errorMsg,      setErrorMsg]      = useState(null);

  // Quote
  const [quote,         setQuote]         = useState(null);
  const [quoteLoading,  setQuoteLoading]  = useState(false);

  // Chart
  const [chartData,     setChartData]     = useState(null);
  const [chartHigh,     setChartHigh]     = useState(null);
  const [chartLow,      setChartLow]      = useState(null);
  const [period,        setPeriod]        = useState('1Y');
  const [chartLoading,  setChartLoading]  = useState(false);

  // Details
  const [details,       setDetails]       = useState(null);
  const [detailsLoading,setDetailsLoading]= useState(false);

  /* ── Firebase: load watchlist on login ── */
  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, async (user) => {
      if (user) {
        try {
          const snap = await getDoc(doc(db, 'users', user.uid));
          if (snap.exists() && snap.data().watchlist) {
            setWatchlist(snap.data().watchlist);
          }
        } catch (err) {
          console.error('Failed to load watchlist:', err);
        }finally {
          watchlistLoaded.current = true;
        }
      } else {
        watchlistLoaded.current = false;
        setWatchlist([]);
      }
    });
    return () => unsubscribe();
  }, []);

  /* ── Firebase: save watchlist whenever it changes ── */
  useEffect(() => {
    if (!auth.currentUser || !watchlistLoaded.current) return;
    const docRef = doc(db, 'users', auth.currentUser.uid);
    setDoc(docRef, { watchlist }, { merge: true }).catch(err =>
      console.error('Failed to save watchlist:', err)
    );
  }, [watchlist]);

  /* ── Load quote + details (single consolidated API call) ── */
  useEffect(() => {
    if (!activeTicker) return;
    let cancelled = false;

    setErrorMsg(null);
    setQuoteLoading(true);
    setDetailsLoading(true);

    apiFetchStockData(activeTicker)
      .then(({ quote, details }) => {
        if (cancelled) return;
        setQuote(quote);
        setDetails(details);
      })
      .catch(err => {
        if (cancelled) return;
        console.error('Stock data error:', err);
        setErrorMsg(`Gagal mendapatkan data untuk ${activeTicker}. Semak ticker dan cuba lagi.`);
      })
      .finally(() => {
        if (!cancelled) {
          setQuoteLoading(false);
          setDetailsLoading(false);
        }
      });

    return () => { cancelled = true; };
  }, [activeTicker]);

  /* ── Load chart (re-runs when ticker OR period changes) ── */
  useEffect(() => {
    if (!activeTicker) return;
    let cancelled = false;

    setChartLoading(true);
    apiFetchChart(activeTicker, period)
      .then(({ data, high, low }) => {
        if (cancelled) return;
        setChartData(data);
        setChartHigh(high);
        setChartLow(low);
      })
      .catch(err => {
        if (cancelled) return;
        console.error('Chart error:', err);
        setChartData(null);
      })
      .finally(() => { if (!cancelled) setChartLoading(false); });

    return () => { cancelled = true; };
  }, [activeTicker, period]);

  /* ── Select stock ── */
  const handleSelectStock = useCallback((item) => {
    setActiveTicker(item.ticker);
    setQuote(null);
    setChartData(null);
    setDetails(null);
    setPeriod('1Y');
    setErrorMsg(null);
  }, []);

  /* ── Watchlist actions ── */
  const isSaved = watchlist.some(s => s.ticker === activeTicker);

  const handleToggleSave = useCallback(() => {
    if (!activeTicker) return;
    const stock = quote ?? {
      ticker: activeTicker, name: activeTicker,
      exchange: '', price: null, change: null, changePct: null,
    };
    setWatchlist(prev => {
      if (prev.some(s => s.ticker === stock.ticker)) {
        return prev.filter(s => s.ticker !== stock.ticker);
      }
      return [...prev, {
        ticker: stock.ticker, name: stock.name, exchange: stock.exchange,
        price: stock.price, change: stock.change, changePct: stock.changePct,
      }];
    });
  }, [quote, activeTicker]);

  const handleDeleteFromWatchlist = useCallback((ticker) => {
    setWatchlist(prev => prev.filter(s => s.ticker !== ticker));
  }, []);

  const handleReorder = useCallback((newList) => {
    setWatchlist(newList);
  }, []);

  /* ── Derived display values ── */
  const displayName    = quote?.name      ?? activeTicker ?? '';
  const displayExchange= quote?.exchange  ?? '';
  const displayPrice   = quote?.price     ?? null;
  const displayChange  = quote?.change    ?? null;
  const displayChangePct = quote?.changePct ?? null;
  const isPositive     = (displayChange ?? 0) >= 0;

  /* ── Render ── */
  return (
    <div className="stocks-page">
      <StockSidePanel
        watchlist={watchlist}
        activeTicker={activeTicker}
        onSelect={(ticker) => {
          const stock = watchlist.find(s => s.ticker === ticker);
          handleSelectStock(stock ?? { ticker, name: ticker, exchange: '' });
        }}
        onReorder={handleReorder}
        onDelete={handleDeleteFromWatchlist}
      />

      <main className="stocks-main">
        <StockSearchBar
          onSelect={handleSelectStock}
          fetchSearchResults={apiSearchStocks}
        />

        {/* Error banner */}
        {errorMsg && (
          <div style={{
            background: 'var(--red-soft, #fee2e2)',
            color: 'var(--red, #dc2626)',
            border: '1px solid var(--red, #dc2626)',
            borderRadius: 8,
            padding: '0.75rem 1rem',
            marginTop: '0.75rem',
            fontSize: '0.875rem',
          }}>
            ⚠️ {errorMsg}
          </div>
        )}

        {/* Empty state */}
        {!activeTicker && !errorMsg && (
          <div className="stocks-empty-state">
            <div className="stocks-empty-icon">📈</div>
            <h3 className="stocks-empty-title">Cari saham untuk mula</h3>
            <p className="stocks-empty-sub">
              Gunakan bar carian di atas untuk mencari saham, atau pilih satu daripada senarai pantauan anda
            </p>
          </div>
        )}

        {/* Stock view */}
        {activeTicker && (
          <>
            <StockHeader
              ticker={activeTicker}
              name={displayName}
              exchange={displayExchange}
              price={displayPrice}
              change={displayChange}
              changePct={displayChangePct}
              loading={quoteLoading}
            />

            <StockChart
              chartData={chartData}
              period={period}
              onPeriod={setPeriod}
              high={chartHigh}
              low={chartLow}
              isSaved={isSaved}
              onToggleSave={handleToggleSave}
              loading={chartLoading}
              isPositive={isPositive}
            />

            <StockDetails
              details={details}
              loading={detailsLoading}
            />
          </>
        )}
      </main>
    </div>
  );
}