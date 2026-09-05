import { useState } from 'react';
import { Link } from 'react-router-dom';

const STATUS_LABELS = {
  FAILED: 'Blocked', RECOMMEND_ONLY: 'Recommendation only',
  PENDING: 'Awaiting approval', PENDING_CONFIRMATION: 'Awaiting approval',
  NEEDS_RECONFIRMATION: 'Review updated terms', EXECUTED: 'Executed',
  PAPER_EXECUTED: 'Paper trade completed', DRY_RUN_OK: 'Simulation completed',
  PREPARING: 'Preparing', EXECUTING: 'Executing', REJECTED: 'Declined',
  EXPIRED: 'Expired', ALERT_ONLY: 'Alert only', MANUAL_IGNORED: 'Manual mode',
};

export default function OpportunityActivity({ items, error }) {
  const [expanded, setExpanded] = useState(false);
  const visibleItems = expanded ? items : items.slice(0, 3);
  return (
    <section className="inv-card inv-card--wide" id="ai-activity">
      <div className="inv-card-head">
        <span className="card-label" style={{ margin: 0 }}>AI buy/sell activity</span>
      </div>
      <p className="inv-card-sub">Recent recommendations and execution results. Completed trades appear in Trade History below.</p>
      {error && <p role="status">{error}</p>}
      {!error && items.length === 0 && <p className="inv-card-sub">No AI activity yet. Run a scan to look for opportunities.</p>}
      <div className="trade-list" id="ai-activity-list">
        {visibleItems.map((item) => (
          <article className="trade-row" key={item.id}>
            <span className={`trade-badge trade-badge--${String(item.decision).toLowerCase()}`}>{item.decision || 'Signal'}</span>
            <div className="trade-row-main">
              <strong className="trade-row-ticker">{item.symbol || 'Opportunity'}</strong>
              <span className="trade-row-detail">{STATUS_LABELS[item.status] || item.status}</span>
              {item.quantity != null && item.price != null && (
                <span className="trade-row-detail">{item.quantity} shares · ${Number(item.price).toFixed(2)} per share</span>
              )}
            </div>
            <div className="trade-row-right">
              {item.updated_at && <time className="trade-row-date">{new Date(item.updated_at).toLocaleString()}</time>}
              {item.confirmation_id && ['PENDING', 'PENDING_CONFIRMATION', 'NEEDS_RECONFIRMATION'].includes(item.status) && (
                <Link to={`/opportunities/confirm/${item.confirmation_id}`}>Review {item.decision}</Link>
              )}
            </div>
            {item.reason && <p className="trade-row-reason">{item.reason}</p>}
          </article>
        ))}
      </div>
      {items.length > 3 && (
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls="ai-activity-list"
          onClick={() => setExpanded(value => !value)}
          style={{ background: 'none', border: 0, padding: '12px 0 0', color: 'var(--teal, #176b6b)', font: 'inherit', textDecoration: 'underline', cursor: 'pointer' }}
        >
          {expanded ? 'Less' : 'More'}
        </button>
      )}
    </section>
  );
}
