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
import InvestmentIntelligenceCard from './components/InvestmentIntelligenceCard';

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
    shariahStatus: d.isHalal !== undefined ? (d.isHalal ? 'Shariah Compliant ✅' : 'Not Shariah Compliant ❌') : '—',
    sector:        d.sector || '—',
    industry:      d.industry || '—',
    marketCap:     d.marketCap ? `$${(d.marketCap / 1000).toFixed(2)}B` : '—',
    peRatio:       d.peRatio ? d.peRatio.toFixed(2) : '—',
    eps:           d.eps !== undefined && d.eps !== null ? d.eps.toFixed(2) : '—',
    beta:          d.beta !== undefined && d.beta !== null ? d.beta.toFixed(2) : '—',
    
    // 1. ADDED BACK: Dividend Yield (%)
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

  // AI Multi-Agent Intelligence
  const [aiAnalysis,    setAiAnalysis]    = useState(null);
  const [aiLoading,     setAiLoading]     = useState(false);
  const [aiError,       setAiError]       = useState(null);

  /* ── Trigger Multi-Agent Investment Intelligence ── */
  const handleRunAIAnalysis = useCallback(async () => {
    if (!activeTicker) return;
    setAiLoading(true);
    setAiError(null);
    try {
      let headers = { 'Content-Type': 'application/json' };
      if (auth.currentUser) {
        const token = await auth.currentUser.getIdToken();
        headers['Authorization'] = `Bearer ${token}`;
      }

      const res = await fetch(`${BACKEND_URL}/api/investment/analyze`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ symbol: activeTicker, question: `Evaluate investment outlook for ${activeTicker}` })
      });
      const json = await res.json();
      if (json.success) {
        setAiAnalysis(json.data);
      } else {
        setAiError(json.error || 'Failed to complete multi-agent analysis.');
      }
    } catch (err) {
      console.error('Multi-Agent Analysis Error:', err);
      setAiError(err.message || 'Network error calling multi-agent engine.');
    } finally {
      setAiLoading(false);
    }
  }, [activeTicker]);

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
        console.error('data error:', err);
        setErrorMsg(`Failed to get data for ${activeTicker}. Check the ticker and try again.`);
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
    setAiAnalysis(null);
    setAiError(null);
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
            <h3 className="stocks-empty-title">Search for a stock to start</h3>
            <p className="stocks-empty-sub">
              Use the search bar above or click any of the stock from your watchlist
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

            {/* ── AMANAH MULTI-AGENT INVESTMENT INTELLIGENCE ── */}
            <div style={{ marginTop: '1.25rem', marginBottom: '1.5rem' }}>
              {!aiAnalysis && !aiLoading && (
                <div style={{
                  background: 'linear-gradient(135deg, rgba(26,107,107,0.06), rgba(26,107,107,0.12))',
                  border: '1.5px dashed var(--teal, #1a6b6b)',
                  borderRadius: 12,
                  padding: '1.25rem',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: '1rem',
                  flexWrap: 'wrap',
                }}>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 700, fontSize: '1rem', color: 'var(--teal, #1a6b6b)' }}>
                      <span>🧠</span>
                      <span>Amanah Multi-Agent Investment Intelligence</span>
                    </div>
                    <p style={{ margin: '0.25rem 0 0', fontSize: '0.82rem', color: 'var(--text-muted, #64748b)' }}>
                      Launch independent 5-agent deliberation (Technical, Fundamental, News, Devil's Advocate, and Committee).
                    </p>
                  </div>

                  <button
                    onClick={handleRunAIAnalysis}
                    style={{
                      background: 'var(--teal, #1a6b6b)',
                      color: '#ffffff',
                      border: 'none',
                      borderRadius: 8,
                      padding: '0.65rem 1.25rem',
                      fontWeight: 700,
                      fontSize: '0.88rem',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.5rem',
                      boxShadow: '0 2px 8px rgba(26,107,107,0.25)',
                      transition: 'transform 0.15s ease, background 0.15s ease',
                    }}
                    onMouseOver={(e) => e.currentTarget.style.transform = 'scale(1.03)'}
                    onMouseOut={(e) => e.currentTarget.style.transform = 'scale(1.0)'}
                  >
                    <span>⚡ Run 5-Agent Analysis</span>
                  </button>
                </div>
              )}

              {aiLoading && (
                <div style={{
                  background: '#f8fafc',
                  border: '1.5px solid var(--border, #e2e8f0)',
                  borderRadius: 12,
                  padding: '1.5rem',
                  textAlign: 'center',
                  color: 'var(--teal, #1a6b6b)',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: '0.75rem',
                }}>
                  <div style={{ fontSize: '1.5rem', animation: 'spin 1.5s linear infinite' }}>🧠</div>
                  <div style={{ fontWeight: 700, fontSize: '0.95rem' }}>
                    Multi-Agent Intelligence System Deliberating...
                  </div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-muted, #64748b)' }}>
                    Concurrently executing Technical, Fundamental, and News agents $\rightarrow$ Adversarial Risk Challenge $\rightarrow$ Investment Committee Synthesis
                  </div>
                </div>
              )}

              {aiError && (
                <div style={{
                  background: '#fef2f2',
                  border: '1px solid #dc2626',
                  color: '#dc2626',
                  borderRadius: 8,
                  padding: '0.75rem 1rem',
                  fontSize: '0.85rem',
                  marginTop: '0.5rem',
                }}>
                  ⚠️ {aiError}
                </div>
              )}

              {aiAnalysis && (
                <div style={{ marginTop: '0.5rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                    <span style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--teal, #1a6b6b)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                      AI Multi-Agent Research Dossier
                    </span>
                    <button
                      onClick={handleRunAIAnalysis}
                      style={{
                        background: 'none',
                        border: '1px solid var(--border, #cbd5e1)',
                        borderRadius: 6,
                        padding: '0.25rem 0.6rem',
                        fontSize: '0.75rem',
                        color: 'var(--text-muted, #64748b)',
                        cursor: 'pointer',
                        fontWeight: 600,
                      }}
                    >
                      🔄 Re-Analyze
                    </button>
                  </div>
                  <InvestmentIntelligenceCard data={aiAnalysis} />
                </div>
              )}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
