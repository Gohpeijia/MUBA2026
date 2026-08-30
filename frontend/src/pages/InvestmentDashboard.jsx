import React, { useState, useEffect, useMemo, useCallback } from 'react';
import axios from 'axios';
import { auth } from '../firebase';
import { onAuthStateChanged } from 'firebase/auth';
import './InvestmentDashboard.css';

const API_BASE = 'http://127.0.0.1:5000/api';

/* ── Helpers ── */
const fmtUSD = (n, opts = {}) =>
  `$${Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2, ...opts })}`;

const getGreeting = () => {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';
  return 'Good evening';
};

const fmtDate = (ts) =>
  new Date(ts).toLocaleDateString('en-US', { day: 'numeric', month: 'short', year: 'numeric' });

const fmtRM = (value) =>
  new Intl.NumberFormat("en-MY", {
    style: "currency",
    currency: "MYR",
  }).format(value);

/*
 * Derive per-ticker holdings + realized P&L from a flat trade log,
 * using the average-cost-basis method. Trades must be chronological.
 */
function computeHoldings(trades, currentPrices) {
  const byTicker = {};

  const sorted = [...trades].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));

  for (const t of sorted) {
    const qty = parseFloat(t.quantity) || 0;
    const price = parseFloat(t.price) || 0;
    if (!byTicker[t.ticker]) {
      byTicker[t.ticker] = {
        ticker: t.ticker,
        companyName: t.companyName || t.ticker,
        qty: 0,
        avgCost: 0,
        costBasis: 0,
        realizedPnl: 0,
        trades: [],
      };
    }
    const h = byTicker[t.ticker];
    h.trades.push(t);

    if (t.action === 'buy') {
      h.costBasis += qty * price;
      h.qty += qty;
      h.avgCost = h.qty > 0 ? h.costBasis / h.qty : 0;
    } else if (t.action === 'sell') {
      const sellQty = Math.min(qty, h.qty);
      const gain = sellQty * (price - h.avgCost);
      h.realizedPnl += gain;
      h.costBasis -= sellQty * h.avgCost;
      h.qty -= sellQty;
      if (h.qty <= 0) { h.qty = 0; h.costBasis = 0; h.avgCost = 0; }
    }
  }

  return Object.values(byTicker).map((h) => {
    const lastTrade = h.trades[h.trades.length - 1];
    const currentPrice = currentPrices?.[h.ticker] ?? lastTrade.price;
    const usingLivePrice = currentPrices?.[h.ticker] != null;
    const marketValue = h.qty * currentPrice;
    const unrealizedPnl = h.qty > 0 ? (currentPrice - h.avgCost) * h.qty : 0;
    const unrealizedPct = h.avgCost > 0 ? ((currentPrice - h.avgCost) / h.avgCost) * 100 : 0;
    return { ...h, currentPrice, usingLivePrice, marketValue, unrealizedPnl, unrealizedPct };
  });
}

/* ── Trade row badge ── */
function ActionBadge({ action }) {
  return (
    <span className={`trade-badge trade-badge--${action}`}>
      {action === 'buy' ? 'Buy' : 'Sell'}
    </span>
  );
}

/* ── Holding card ── */
function HoldingCard({ h }) {
  const isUp = h.unrealizedPnl >= 0;
  return (
    <div className="hold-card">
      <div className="hold-card-top">
        <div>
          <span className="hold-ticker">{h.ticker}</span>
          <span className="hold-company">{h.companyName}</span>
        </div>
        <span className={`hold-pnl-pct ${isUp ? 'inv-up' : 'inv-down'}`}>
          {isUp ? '+' : '-'}{Math.abs(h.unrealizedPct).toFixed(1)}%
        </span>
      </div>

      <div className="hold-stats-row">
        <div className="hold-stat">
          <span className="hold-stat-label">Shares</span>
          <span className="hold-stat-value">{h.qty}</span>
        </div>
        <div className="hold-stat">
          <span className="hold-stat-label">Avg cost</span>
          <span className="hold-stat-value">{fmtUSD(h.avgCost)}</span>
        </div>
        <div className="hold-stat">
          <span className="hold-stat-label">{h.usingLivePrice ? 'Price' : 'Last trade'}</span>
          <span className="hold-stat-value">{fmtUSD(h.currentPrice)}</span>
        </div>
      </div>

      <div className="hold-footer">
        <span className="hold-mv-label">Market value</span>
        <span className="hold-mv-value">{fmtUSD(h.marketValue)}</span>
        <span className={`hold-gain ${isUp ? 'inv-up' : 'inv-down'}`}>
          {isUp ? '+' : '-'}{fmtUSD(h.unrealizedPnl)}
        </span>
      </div>
    </div>
  );
}

/* ── Main Dashboard ── */
export default function InvestmentDashboard({ userName }) {
  const [trades, setTrades] = useState([]);
  const [currentPrices, setCurrentPrices] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('all'); // all | buy | sell

  const fetchData = useCallback(async () => {
    const user = auth.currentUser;
    if (!user) return;
    try {
      setError(null);
      const token = await user.getIdToken();
      const headers = { Authorization: `Bearer ${token}` };

      const tradesRes = await axios.get(`${API_BASE}/trades`, { headers });
      const tradeList = tradesRes.data.success ? tradesRes.data.data.trades || [] : [];
      setTrades(tradeList);

      const tickers = [...new Set(tradeList.map((t) => t.ticker))];
      if (tickers.length > 0) {
        try {
          const quoteRes = await axios.get(`${API_BASE}/stocks/quote`, {
            headers,
            params: { symbols: tickers.join(',') },
          });
          if (quoteRes.data.success) setCurrentPrices(quoteRes.data.data || {});
        } catch {
          // Live price endpoint not available yet — holdings will fall back
          // to each ticker's last trade price instead of failing outright.
        }
      }
    } catch (err) {
      console.error('Failed to load trade data:', err);
      setError('Could not load trade history.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (user) => {
      if (user) fetchData();
    });
    return () => unsubscribe();
  }, [fetchData]);

  useEffect(() => {
    const onFocus = () => fetchData();
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [fetchData]);

  const holdings = useMemo(() => computeHoldings(trades, currentPrices), [trades, currentPrices]);

  const openHoldings = holdings.filter((h) => h.qty > 0).sort((a, b) => b.marketValue - a.marketValue);

  const totals = useMemo(() => {
    const marketValue = openHoldings.reduce((s, h) => s + h.marketValue, 0);
    const unrealizedPnl = openHoldings.reduce((s, h) => s + h.unrealizedPnl, 0);
    const realizedPnl = holdings.reduce((s, h) => s + h.realizedPnl, 0);
    return { marketValue, unrealizedPnl, realizedPnl, totalPnl: unrealizedPnl + realizedPnl };
  }, [holdings, openHoldings]);

  const sortedTrades = useMemo(
    () =>
      [...trades]
        .filter((t) => filter === 'all' || t.action === filter)
        .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp)),
    [trades, filter]
  );

  if (loading) {
    return (
      <div className="risk-page inv-page">
        <p className="risk-subtitle">Loading trade history…</p>
      </div>
    );
  }

  const isTotalUp = totals.totalPnl >= 0;

  return (
    <div className="risk-page inv-page">
      <div className="risk-header">
        <h1 className="risk-main-title inv-greeting">
          {getGreeting()}{userName ? `, ${userName}` : ''} 👋
        </h1>
        <p className="risk-subtitle">Here's what the AI has bought, sold, and earned so far.</p>
        {error && <p className="risk-subtitle" style={{ color: 'var(--red, #c0392b)' }}>{error}</p>}
      </div>

      <div className="inv-grid">

        {/* Portfolio value + total P&L */}
        <section className="inv-card inv-card--hero">
          <span className="card-label">Portfolio Value</span>
          <div className="inv-hero-value">{fmtRM(totals.marketValue)}</div>
          <div className={`inv-hero-delta ${isTotalUp ? 'inv-up' : 'inv-down'}`}>
            <span>{isTotalUp ? '▲' : '▼'}</span>
            <span>{isTotalUp ? '+' : '-'}{fmtRM(totals.totalPnl)} total P&L</span>
          </div>
          <div className="inv-pnl-split">
            <span>Realized: <strong className={totals.realizedPnl >= 0 ? 'inv-up-text' : 'inv-down-text'}>{totals.realizedPnl >= 0 ? '+' : '-'}{fmtUSD(totals.realizedPnl)}</strong></span>
            <span>Unrealized: <strong className={totals.unrealizedPnl >= 0 ? 'inv-up-text' : 'inv-down-text'}>{totals.unrealizedPnl >= 0 ? '+' : '-'}{fmtUSD(totals.unrealizedPnl)}</strong></span>
          </div>
        </section>

        {/* Current holdings */}
        <section className="inv-card inv-card--wide">
          <div className="inv-card-head">
            <span className="inv-icon-badge">📊</span>
            <span className="card-label" style={{ margin: 0 }}>Current Holdings</span>
          </div>

          {openHoldings.length === 0 ? (
            <p className="inv-card-sub">No open positions yet — the AI hasn't bought anything.</p>
          ) : (
            <div className="hold-grid">
              {openHoldings.map((h) => <HoldingCard key={h.ticker} h={h} />)}
            </div>
          )}
        </section>

        {/* Trade history */}
        <section className="inv-card inv-card--wide">
          <div className="inv-card-head" style={{ justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
              <span className="inv-icon-badge">🤖</span>
              <span className="card-label" style={{ margin: 0 }}>Trade History</span>
            </div>
            <div className="trade-filter-group">
              {['all', 'buy', 'sell'].map((f) => (
                <button
                  key={f}
                  className={`trade-filter-btn ${filter === f ? 'active' : ''}`}
                  onClick={() => setFilter(f)}
                >
                  {f === 'all' ? 'All' : f === 'buy' ? 'Buys' : 'Sells'}
                </button>
              ))}
            </div>
          </div>

          {sortedTrades.length === 0 ? (
            <p className="inv-card-sub">No trades logged yet.</p>
          ) : (
            <div className="trade-list">
              {sortedTrades.map((t) => {
                const total = (parseFloat(t.quantity) || 0) * (parseFloat(t.price) || 0);
                return (
                  <div className="trade-row" key={t.id}>
                    <ActionBadge action={t.action} />
                    <div className="trade-row-main">
                      <span className="trade-row-ticker">{t.ticker}</span>
                      <span className="trade-row-detail">{t.quantity} sh @ {fmtUSD(t.price)}</span>
                    </div>
                    <div className="trade-row-right">
                      <span className="trade-row-total">{fmtUSD(total)}</span>
                      <span className="trade-row-date">{fmtDate(t.timestamp)}</span>
                    </div>
                    {t.reason && <p className="trade-row-reason">{t.reason}</p>}
                  </div>
                );
              })}
            </div>
          )}
        </section>

      </div>
    </div>
  );
}