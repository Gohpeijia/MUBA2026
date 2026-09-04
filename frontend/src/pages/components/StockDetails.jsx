import React, { memo } from 'react';

/**
 * StockDetails — fundamentals panel: sector, market cap, PE, dividend, etc.
 *
 * Props:
 *  details: {
 *    sector, industry, marketCap, peRatio, dividendYield,
 *    eps, beta, avgVolume, fiftyTwoWeekHigh, fiftyTwoWeekLow,
 *    ... any extra key-value pairs
 *  }
 *  loading: bool
 */
const FIELDS = [
  { key: 'sector',          label: 'Sector' },
  { key: 'industry',        label: 'Industry' },
  { key: 'marketCap',       label: 'Market Cap (Million)' },
  { key: 'peRatio',         label: 'PE Ratio' },
  { key: 'dividendYield',   label: 'Dividend Yield (%)' },
  { key: 'dividendRate',    label: 'Dividend ($)' },
  { key: 'eps',             label: 'EPS' },
  { key: 'beta',            label: 'Beta' },
  { key: 'avgVolume',       label: 'Average Volume' },
  { key: 'fiftyTwoWeekHigh',label: '52W High' },
  { key: 'fiftyTwoWeekLow', label: '52W Low' },
  { key: 'lotSize',         label: 'Lot Size' },
];

const StockDetails = memo(function StockDetails({ details, loading }) {
  if (loading) return <div className="stock-details-card">Loading...</div>;
  if (!details) return null;

  return (
    <div className="stock-details-card">
      <h3 className="details-title">Company Details</h3>
      <div className="details-grid">
        {FIELDS.map((field) => (
          <div key={field.key} className="detail-item">
            <span className="detail-label">{field.label}</span>
            <span className="detail-value">{details[field.key] || '—'}</span>
          </div>
        ))}
      </div>
    </div>
  );
});

export default StockDetails;
