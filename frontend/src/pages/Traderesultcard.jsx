import React, { useState } from 'react';
import { FaTimes, FaExternalLinkAlt, FaSpinner, FaBan, FaClock } from 'react-icons/fa';
import { useAIAdvisor } from './AIAdvisorContext';

// Base mainnet explorer — tx_hash comes from thetanuts_trader.py's
// execute_fill(), which reads it off the CLI's parsed JSON response.
const BASESCAN_TX_URL = 'https://basescan.org/tx/';

const STATUS_META = {
  PAPER_EXECUTED: {
  label: 'Paper trade executed',
  color: '#1a9e5c',
  bg: '#e8f8f0'
},
PAPER_FAILED: {
  label: 'Paper trade failed',
  color: '#c0392b',
  bg: '#fbeaea'
},
  EXECUTED:                   { label: 'Executed on-chain',            color: '#1a9e5c', bg: '#e8f8f0' },
  DRY_RUN_OK:                  { label: 'Dry run only — not sent',      color: '#a8710a', bg: '#fdf3e0' },
  FAILED:                      { label: 'Failed',                       color: '#c0392b', bg: '#fbeaea' },
  SKIPPED_INSUFFICIENT_FUNDS:  { label: 'Skipped — insufficient funds', color: '#666',    bg: '#f0f0f0' },
  ALERT_ONLY:                  { label: 'Alert only — no order sent',   color: '#1f5b96', bg: '#eaf2fb' },
  PENDING_CONFIRMATION:        { label: 'Awaiting your confirmation',   color: '#a8710a', bg: '#fdf3e0' },
  NEEDS_RECONFIRMATION:        { label: 'Terms changed — review below', color: '#a8710a', bg: '#fdf3e0' },
};

// ── Contract-term formatting (used by the PENDING_CONFIRMATION and
//    NEEDS_RECONFIRMATION panels to render confirm_selector / previous /
//    current objects: { option_type, strike, expiry, previewed_price|price }) ──
function fmtStrike(strike) {
  if (strike === null || strike === undefined) return '—';
  const n = Number(strike);
  return Number.isFinite(n) ? `$${n}` : String(strike);
}

function fmtExpiry(expiry) {
  if (!expiry) return '—';
  const n = Number(expiry);
  if (Number.isFinite(n) && n > 1_000_000_000) {
    const d = new Date(n < 1e12 ? n * 1000 : n);
    return Number.isNaN(d.getTime()) ? String(expiry) : d.toLocaleString();
  }
  return String(expiry);
}

function fmtPrice(price) {
  if (price === null || price === undefined) return '—';
  const n = Number(price);
  return Number.isFinite(n) ? `$${n.toFixed(4)}` : String(price);
}

function TermsLine({ selector, trade }) {
  // Paper equity trade
  if (trade?.execution_target === 'PAPER_EQUITY') {
    const shares = trade.shares ?? trade.quantity ?? trade.qty;
    const price = trade.price;

    return (
      <span>
        {shares != null ? `${shares} shares` : '—'}
        {' · '}
        Price {fmtStrike(price)}
        {' · '}
        Value {trade.estimated_value != null
          ? `$${Number(trade.estimated_value).toFixed(2)}`
          : '—'}
      </span>
    );
  }

  // Thetanuts option trade
  if (!selector) {
    return <span style={{ color: '#999' }}>—</span>;
  }

  const price = selector.previewed_price ?? selector.price;

  return (
    <span>
      {selector.option_type || '—'} · Strike {fmtStrike(selector.strike)} · Expiry{' '}
      {fmtExpiry(selector.expiry)} · Premium {fmtPrice(price)}
    </span>
  );
}

/**
 * trade shape (from ai_agent.py's `trade_proposal`, as mutated by
 * AIAdvisorContext's confirmTrade()):
 *   { action, ticker, confidence, risk_tolerance, risk_copilot_mode,
 *     wallet_tradable_usdc, proposed_amount_usdc,
 *     confirm_selector?: { underlying, option_type, strike, expiry,
 *                           collateral_usdc, previewed_price },
 *     thetanuts_execution?: {
 *       status: EXECUTED | DRY_RUN_OK | FAILED | SKIPPED_INSUFFICIENT_FUNDS
 *             | ALERT_ONLY | PENDING_CONFIRMATION | NEEDS_RECONFIRMATION,
 *       tx_hash, error, reason,
 *       previous?, current?,   // only on NEEDS_RECONFIRMATION
 *     }
 *   }
 *
 * thetanuts_execution is only present when the swarm reached BUY/SELL at
 * ≥50% confidence — otherwise this renders as a plain "no trade attempted"
 * summary (e.g. HOLD, or low confidence).
 *
 * PENDING_CONFIRMATION / NEEDS_RECONFIRMATION only ever happen in
 * "Suggest actions, I confirm each one" mode. Confirm Trade calls
 * confirmTrade(false) from AIAdvisorContext, which re-checks the book
 * fresh server-side; if terms moved it comes back as
 * NEEDS_RECONFIRMATION instead of filling, and the user has to press
 * "Confirm at New Terms" (confirmTrade(true)) to proceed. Reject/Cancel
 * only ever calls onDismiss — it never reaches the backend, so it can't
 * execute anything.
 */
export default function TradeResultCard({ trade, onDismiss }) {
  const { confirmTrade } = useAIAdvisor();
  const [isConfirming, setIsConfirming] = useState(false);

  if (!trade) return null;

  const exec = trade.thetanuts_execution;
  const status = exec?.status;

  const isPaperEquity =
  trade.execution_target === 'PAPER_EQUITY' ||
  trade.asset_type === 'EQUITY';

  const isPendingProposal = !status;
  const meta = STATUS_META[status] || (
    isPendingProposal
      ? {
          label: 'Awaiting your confirmation',
          color: '#a8710a',
          bg: '#fdf3e0',
        }
      : {
          label: 'No trade attempted',
          color: '#666',
          bg: '#f0f0f0',
        }
  );

  const confidence =
  trade.confidence != null
    ? Number(trade.confidence)
    : trade.evidence_conviction != null
      ? Number(trade.evidence_conviction)
      : null;

  // Only show the generic error/reason line for terminal states — the
  // pending/needs-reconfirmation panels below render `reason` themselves
  // as part of their own layout, so this would otherwise duplicate it.
  const showErrorLine = status !== 'PENDING_CONFIRMATION' && status !== 'NEEDS_RECONFIRMATION';
  const errorMsg = showErrorLine ? (exec?.error || exec?.reason) : null;
  const txUrl = exec?.tx_hash ? `${BASESCAN_TX_URL}${exec.tx_hash}` : null;

  const actionColor = trade.action === 'BUY' ? '#1a9e5c' : trade.action === 'SELL' ? '#c0392b' : '#666';

  const handleConfirm = async (force = false) => {
    setIsConfirming(true);
    try {
      await confirmTrade(force);
    } finally {
      setIsConfirming(false);
    }
  };

  // Reject/Cancel never calls confirmTrade or hits the backend — it only
  // clears local state, so it can never trigger an execution.
  const handleReject = () => {
    if (isConfirming) return;
    onDismiss?.();
  };

  return (
    <div
      style={{
        margin: '0 12px 10px',
        padding: '10px 12px',
        borderRadius: 10,
        border: '1px solid #e2e2e2',
        background: '#fff',
        fontSize: 13,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontWeight: 700, color: actionColor }}>{trade.action}</span>
          <span style={{ fontWeight: 700 }}>{trade.ticker}</span>
          {confidence != null && (
            <span style={{ color: '#888' }}>· {confidence > 1 ? confidence : confidence * 100}% confidence</span>
          )}
        </div>
        {onDismiss && (
          <button
            onClick={handleReject}
            aria-label="Dismiss trade result"
            disabled={isConfirming}
            style={{
              background: 'none', border: 'none', color: '#999', padding: 2,
              cursor: isConfirming ? 'not-allowed' : 'pointer',
            }}
          >
            <FaTimes size={11} />
          </button>
        )}
      </div>

      {isPaperEquity ? (
        <div style={{ color: '#555', marginBottom: 6 }}>
          {trade.shares ?? trade.quantity ?? 0} shares
          {trade.price != null && <> · ${Number(trade.price).toFixed(2)} per share</>}
          {trade.estimated_value != null && (
            <> · Estimated value ${Number(trade.estimated_value).toFixed(2)}</>
          )}
          {trade.risk_tolerance && <> · {trade.risk_tolerance} risk</>}
        </div>
      ) : trade.proposed_amount_usdc != null && (
        <div style={{ color: '#555', marginBottom: 6 }}>
          Proposed {trade.proposed_amount_usdc} USDC
          {trade.wallet_tradable_usdc != null && (
            <> · wallet has {trade.wallet_tradable_usdc} USDC tradable</>
          )}
          {trade.risk_tolerance && <> · {trade.risk_tolerance} risk</>}
        </div>
      )}

      <div
        style={{
          display: 'inline-block',
          padding: '3px 8px',
          borderRadius: 999,
          fontWeight: 600,
          fontSize: 12,
          color: meta.color,
          background: meta.bg,
        }}
      >
        {meta.label}
      </div>

      {errorMsg && (
        <div style={{ color: '#c0392b', marginTop: 6, fontSize: 12 }}>{errorMsg}</div>
      )}

      {/* PENDING_CONFIRMATION — "Suggest actions, I confirm each one" mode.
          Nothing has been sent on-chain yet; Confirm re-checks the book
          fresh on the backend before ever filling. */}
      {(status === 'PENDING_CONFIRMATION' || isPendingProposal) && (
        <div style={{ marginTop: 8 }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 6, color: '#8a5c0b', fontSize: 12 }}>
            <FaClock size={11} style={{ marginTop: 2, flexShrink: 0 }} />
            <div>
              <div>Preview ready — nothing has been sent on-chain yet.</div>
              <div style={{ marginTop: 3, color: '#666' }}>
                <TermsLine selector={trade.confirm_selector} 
                trade={trade} />
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button
              onClick={() => handleConfirm(false)}
              disabled={isConfirming}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 6,
                fontSize: 12.5, fontWeight: 600, borderRadius: 7, border: 'none',
                padding: '7px 14px', color: '#fff',
                background: isConfirming ? '#a9c9c9' : '#1a6b6b',
                cursor: isConfirming ? 'not-allowed' : 'pointer',
              }}
            >
              {isConfirming ? (
                <>
                  <FaSpinner size={11} style={{ animation: 'trc-spin 0.8s linear infinite' }} />
                  Confirming…
                </>
              ) : (
                'Confirm Trade'
              )}
            </button>
            <button
              onClick={handleReject}
              disabled={isConfirming}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 6,
                fontSize: 12.5, fontWeight: 600, borderRadius: 7,
                padding: '7px 14px', color: '#c0392b',
                background: '#fff', border: '1px solid #e0554f',
                cursor: isConfirming ? 'not-allowed' : 'pointer',
                opacity: isConfirming ? 0.6 : 1,
              }}
            >
              <FaBan size={11} /> Reject
            </button>
          </div>
        </div>
      )}

      {/* NEEDS_RECONFIRMATION — the book moved since the preview above.
          Show exactly what changed and require a second, explicit
          confirm before proceeding at the new terms. */}
      {status === 'NEEDS_RECONFIRMATION' && (
        <div style={{ marginTop: 8 }}>
          <div style={{ color: '#8a5c0b', fontSize: 12 }}>
            {exec.reason || 'Price or contract terms moved since you approved this proposal.'}
          </div>

          <div style={{ display: 'flex', gap: 16, marginTop: 8, fontSize: 12 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 700, color: '#999', fontSize: 10.5, textTransform: 'uppercase', letterSpacing: 0.3 }}>
                Previously shown
              </div>
              <div style={{ color: '#666', marginTop: 2 }}>
                <TermsLine selector={exec.previous} trade={trade} />
              </div>
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 700, color: '#999', fontSize: 10.5, textTransform: 'uppercase', letterSpacing: 0.3 }}>
                Current on book
              </div>
              <div style={{ color: '#666', marginTop: 2 }}>
                <TermsLine selector={exec.current} trade={trade} />
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button
              onClick={() => handleConfirm(true)}
              disabled={isConfirming}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 6,
                fontSize: 12.5, fontWeight: 600, borderRadius: 7, border: 'none',
                padding: '7px 14px', color: '#fff',
                background: isConfirming ? '#a9c9c9' : '#1a6b6b',
                cursor: isConfirming ? 'not-allowed' : 'pointer',
              }}
            >
              {isConfirming ? (
                <>
                  <FaSpinner size={11} style={{ animation: 'trc-spin 0.8s linear infinite' }} />
                  Confirming…
                </>
              ) : (
                'Confirm at New Terms'
              )}
            </button>
            <button
              onClick={handleReject}
              disabled={isConfirming}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 6,
                fontSize: 12.5, fontWeight: 600, borderRadius: 7,
                padding: '7px 14px', color: '#c0392b',
                background: '#fff', border: '1px solid #e0554f',
                cursor: isConfirming ? 'not-allowed' : 'pointer',
                opacity: isConfirming ? 0.6 : 1,
              }}
            >
              <FaBan size={11} /> Cancel
            </button>
          </div>
        </div>
      )}

      {txUrl && (
        <div style={{ marginTop: 6 }}>
          <a
            href={txUrl}
            target="_blank"
            rel="noreferrer"
            style={{ color: '#1a6b6b', fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 4 }}
          >
            View transaction <FaExternalLinkAlt size={9} />
          </a>
        </div>
      )}

      <style>{`@keyframes trc-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}