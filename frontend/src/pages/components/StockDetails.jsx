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
  { key: 'shariahStatus',   label: 'Status Syariah' },
  { key: 'sector',          label: 'Sektor' },
  { key: 'industry',        label: 'Industri' },
  { key: 'marketCap',       label: 'Modal Pasaran (Juta)' },
  { key: 'peRatio',         label: 'Nisbah PE' },
  { key: 'dividendYield',   label: 'Hasil Dividen (%)' },
  { key: 'dividendRate',        label: 'Dividen ($)' },
  { key: 'eps',             label: 'EPS' },
  { key: 'beta',            label: 'Beta' },
  { key: 'avgVolume',       label: 'Purata Volum' },
  { key: 'fiftyTwoWeekHigh',label: 'Tinggi 52M' },
  { key: 'fiftyTwoWeekLow', label: 'Rendah 52M' },
  { key: 'lotSize',         label: 'Saiz Lot' },
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