import React, { memo } from 'react';
/**
 * StockHeader — shows company name, ticker badge, live price + change.
 *
 * Props:
 *  ticker   : string
 *  name     : string
 *  exchange : string
 *  price    : number | null
 *  change   : number | null  (absolute)
 *  changePct: number | null  (percentage)
 *  loading  : bool
 */
const StockHeader = memo(function StockHeader({
  ticker, name, exchange, price, change, changePct, loading,
}) {
  const direction =
    change == null ? 'neutral' : change > 0 ? 'positive' : change < 0 ? 'negative' : 'neutral';

  const fmtPrice = price != null ? price.toFixed(3) : '—';
  const fmtChange =
    change != null
      ? `${change > 0 ? '+' : ''}${change.toFixed(3)}`
      : '—';
  const fmtPct =
    changePct != null
      ? `${changePct > 0 ? '+' : ''}${changePct.toFixed(2)}%`
      : '—';

  return (
    <div className="stock-header-card">
      <div className="stock-header-left">
        <span className="stock-ticker-badge">
          <span>⬡</span>
          {ticker} · {exchange || '—'}
        </span>
        <h2 className="stock-name">{loading ? 'Loading…' : name}</h2>
      </div>

      <div className="stock-header-right">
        <span className={`stock-price ${direction}`}>
          {loading ? '—' : fmtPrice}
        </span>
        <div className="stock-change-row">
          <span className={`stock-change-abs change-${direction}`}>{loading ? '—' : fmtChange}</span>
          <span className={`stock-change-pct change-${direction}`}>{loading ? '—' : fmtPct}</span>
        </div>
      </div>
    </div>
  );
});

export default StockHeader;