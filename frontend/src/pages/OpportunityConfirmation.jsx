import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { FaBan, FaCheckCircle, FaClock, FaSpinner, FaTimesCircle } from 'react-icons/fa';
import {
  confirmOpportunity,
  getConfirmation,
  rejectOpportunity,
} from '../services/opportunityConfirmationApi';
import './OpportunityConfirmation.css';

const STATUS_COPY = {
  PENDING: 'Review the current proposal before execution.',
  NEEDS_RECONFIRMATION: 'Terms changed. Review the updated proposal before confirming again.',
  EXECUTING: 'Execution is in progress.',
  EXECUTED: 'Trade completed.',
  DRY_RUN_OK: 'Dry run completed. No blockchain transaction was sent.',
  REJECTED: 'You rejected this recommendation.',
  FAILED: 'Execution failed or was blocked.',
  EXPIRED: 'This confirmation link expired.',
  STALE: 'The live market or position no longer matches this opportunity.',
  RECOMMEND_ONLY: 'This opportunity is not executable through the current trading engine.',
};

function formatPercent(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 'N/A';
  return `${Math.round(n * 100)}%`;
}

function formatMoney(value, currency = 'USD') {
  const n = Number(value);
  if (!Number.isFinite(n)) return 'N/A';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: 4 }).format(n);
}

function formatExpiry(value) {
  if (!value) return 'N/A';
  const n = Number(value);
  const date = Number.isFinite(n) && n > 1_000_000_000 ? new Date(n < 1e12 ? n * 1000 : n) : new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function Detail({ label, value }) {
  return (
    <div className="opp-confirm-detail">
      <dt>{label}</dt>
      <dd>{value ?? 'N/A'}</dd>
    </div>
  );
}

export default function OpportunityConfirmation() {
  const { confirmationId } = useParams();
  const [confirmation, setConfirmation] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  const loadConfirmation = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getConfirmation(confirmationId);
      setConfirmation(data.confirmation);
    } catch (err) {
      setError(err.data?.error || err.message || 'Could not load confirmation.');
      setConfirmation(err.data?.confirmation || null);
    } finally {
      setLoading(false);
    }
  }, [confirmationId]);

  useEffect(() => {
    loadConfirmation();
  }, [loadConfirmation]);

  const proposal = confirmation?.proposal || confirmation?.proposal_snapshot || {};
  const selector = confirmation?.selector || proposal.selector || confirmation?.selector_snapshot || {};
  const decision = (confirmation?.decision || selector.decision || proposal.action || '').toUpperCase();
  const isSell = decision === 'SELL';
  const executionTarget = confirmation?.execution_target || proposal.execution_target;
  const isPaperEquity = executionTarget === 'PAPER_EQUITY' || proposal.asset_type === 'EQUITY' || proposal.assetType === 'EQUITY';
  const displaySymbol = confirmation?.symbol || proposal.symbol || proposal.ticker || selector.underlying || 'Opportunity';
  const status = confirmation?.status || 'PENDING';
  const canAct = ['PENDING', 'NEEDS_RECONFIRMATION'].includes(status);

  const title = useMemo(() => {
    if (isPaperEquity) return isSell ? 'AI Paper Sell Confirmation' : 'AI Paper Buy Confirmation';
    if (isSell) return 'AI Sell Recommendation';
    return 'AI Trade Confirmation';
  }, [isPaperEquity, isSell]);

  const handleReject = async () => {
    setBusy('reject');
    setError(null);
    try {
      const data = await rejectOpportunity(confirmationId);
      setConfirmation(data.confirmation);
    } catch (err) {
      setError(err.data?.error || err.message || 'Could not reject confirmation.');
      if (err.data?.confirmation) setConfirmation(err.data.confirmation);
    } finally {
      setBusy(null);
    }
  };

  const handleConfirm = async () => {
    setBusy('confirm');
    setError(null);
    try {
      const data = await confirmOpportunity(
        confirmationId,
        confirmation?.proposal_version,
        confirmation?.terms_hash,
      );
      setConfirmation(data.confirmation);
      if (['EXECUTED', 'DRY_RUN_OK', 'PAPER_EXECUTED'].includes(data.confirmation?.status)) {
        window.dispatchEvent(new CustomEvent('wallet:refresh'));
      }
    } catch (err) {
      setError(err.data?.error || err.message || 'Could not confirm opportunity.');
      if (err.data?.confirmation) setConfirmation(err.data.confirmation);
    } finally {
      setBusy(null);
    }
  };

  if (loading) {
    return (
      <main className="opp-confirm-page">
        <div className="opp-confirm-panel opp-confirm-loading">
          <FaSpinner className="opp-confirm-spin" />
          <span>Loading confirmation...</span>
        </div>
      </main>
    );
  }

  return (
    <main className="opp-confirm-page">
      <section className="opp-confirm-panel">
        <div className={`opp-confirm-status opp-confirm-status--${status.toLowerCase()}`}>
          {['EXECUTED', 'DRY_RUN_OK'].includes(status) ? <FaCheckCircle /> : status === 'FAILED' ? <FaTimesCircle /> : <FaClock />}
          <span>{status.replaceAll('_', ' ')}</span>
        </div>

        <div className="opp-confirm-header">
          <span className="opp-confirm-eyebrow">{title}</span>
          <h1>{decision || 'REVIEW'} {displaySymbol}</h1>
          <p>{STATUS_COPY[status] || 'Review this AI opportunity.'}</p>
          {error && <p className="opp-confirm-error">{error}</p>}
        </div>

        <div className="opp-confirm-summary">
          <Detail label="AI confidence" value={formatPercent(confirmation?.confidence)} />
          <Detail label="Risk" value={confirmation?.risk_level || 'N/A'} />
          <Detail label="Reference" value={confirmation?.analysis_id || confirmationId} />
          <Detail label="Version" value={confirmation?.proposal_version || 1} />
        </div>

        <h2>{isPaperEquity ? 'Paper Equity Order' : (isSell ? 'Current Position' : 'Contract')}</h2>
        {isPaperEquity ? (
          <dl className="opp-confirm-details">
            <Detail label="Symbol" value={displaySymbol} />
            <Detail label="Side" value={decision || 'N/A'} />
            <Detail label="Shares" value={proposal.shares || proposal.quantity || 'N/A'} />
            <Detail label="Price" value={formatMoney(proposal.price)} />
            <Detail label="Estimated value" value={formatMoney(proposal.estimated_value || (Number(proposal.price) * Number(proposal.shares || proposal.quantity)))} />
          </dl>
        ) : (
          <dl className="opp-confirm-details">
            <Detail label="Type" value={selector.option_type || proposal.option_type || 'N/A'} />
            <Detail label="Strike" value={formatMoney(selector.strike || proposal.strike)} />
            <Detail label="Expiry" value={formatExpiry(selector.expiry || proposal.expiry)} />
            <Detail label={isSell ? 'Quantity' : 'Premium'} value={isSell ? (selector.quantity || selector.contracts || 'Full position') : formatMoney(selector.previewed_price || selector.price)} />
            {!isSell && <Detail label="Proposed allocation" value={`${selector.collateral_usdc || proposal.collateral_usdc || proposal.proposed_amount_usdc || 'N/A'} USDC`} />}
          </dl>
        )}

        {confirmation?.error && <p className="opp-confirm-note">{confirmation.error}</p>}

        <div className="opp-confirm-actions">
          <button className="opp-confirm-secondary" onClick={handleReject} disabled={!canAct || Boolean(busy)}>
            {busy === 'reject' ? <FaSpinner className="opp-confirm-spin" /> : <FaBan />}
            {isSell ? 'Keep Position' : 'Reject'}
          </button>
          <button className="opp-confirm-primary" onClick={handleConfirm} disabled={!canAct || Boolean(busy)}>
            {busy === 'confirm' ? <FaSpinner className="opp-confirm-spin" /> : <FaCheckCircle />}
            {isSell ? 'Confirm Sell' : 'Confirm Buy'}
          </button>
        </div>

        <Link className="opp-confirm-back" to="/dashboard">Back to Dashboard</Link>
      </section>
    </main>
  );
}

