import React, { useEffect, useState, useCallback } from 'react';
import { FaWallet, FaSyncAlt, FaExclamationTriangle } from 'react-icons/fa';
import { auth } from '../firebase';
import './WalletBalance.css';

const API_BASE = 'http://localhost:5000/api/wallet';
const REFRESH_INTERVAL_MS = 30000;

/**
 * WalletBalance — shows the AI trader's spendable paper cash for equities.
 *
 * variant="pill"  → compact, for the NavBar (icon + tradable USDC only)
 * variant="card"  → fuller detail, for the Dashboard or AI Advisor panel
 *                   (tradable + total USDC + ETH gas + a no-funds notice)
 *
 * Reads from GET /api/wallet/balance. The backend keeps the on-chain
 * wallet snapshot too, but the headline balance is the paper equity fund.
 */
export default function WalletBalance({ variant = 'pill' }) {
  const [balance, setBalance] = useState(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(null);

  const fetchBalance = useCallback(async () => {
    setLoading(true);
    setFetchError(null);
    try {
      const user = auth.currentUser;
      if (!user) throw new Error('Not signed in');
      const token = await user.getIdToken();

      const res = await fetch(`${API_BASE}/balance`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`Server returned ${res.status}`);

      const json = await res.json();
      setBalance(json.data || null);
    } catch (e) {
      setFetchError(e.message || 'Could not reach the wallet service.');
      setBalance(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchBalance();
    const interval = setInterval(fetchBalance, REFRESH_INTERVAL_MS);
    
    // Listen for global sync events from other components
    const handleGlobalRefresh = () => {
      fetchBalance();
    };
    window.addEventListener('wallet:refresh', handleGlobalRefresh);

    return () => {
      clearInterval(interval);
      window.removeEventListener('wallet:refresh', handleGlobalRefresh);
    };
  }, [fetchBalance]);
  // Two different kinds of "not good": the request itself failed
  // (network/auth), or it succeeded but the wallet reports ok=false
  // (no key configured, RPC unreachable, etc). Both render as a
  // warning state, but the message differs.
  const walletUnreachable = !fetchError && balance && balance.ok === false;
  const hasLiveBalance = !fetchError && balance && balance.ok === true;
  const noTradableFunds =
  hasLiveBalance && Number(balance.paper_tradable_usd || 0) === 0;

  return (
    <div
      className={[
        'wallet-balance',
        `wallet-balance--${variant}`,
        (fetchError || walletUnreachable) ? 'wallet-balance--warning' : '',
      ].join(' ').trim()}
    >
      <div className="wallet-balance__icon">
        {fetchError || walletUnreachable ? (
          <FaExclamationTriangle size={variant === 'pill' ? 12 : 15} />
        ) : (
          <FaWallet size={variant === 'pill' ? 12 : 15} />
        )}
      </div>

      <div className="wallet-balance__body">
        {loading && !balance && !fetchError && (
          <span className="wallet-balance__status">Reading wallet…</span>
        )}

        {fetchError && (
          <span className="wallet-balance__status">
            {variant === 'pill' ? 'Wallet offline' : `Wallet offline — ${fetchError}`}
          </span>
        )}

        {walletUnreachable && (
          <span className="wallet-balance__status">
            {variant === 'pill'
              ? 'No wallet'
              : (balance.error || 'Wallet not configured.')}
          </span>
        )}

        {hasLiveBalance && (
          <>
            <div className="wallet-balance__row">
              <span className="wallet-balance__amount">
                {Number(balance.paper_tradable_usd || 0).toFixed(2)}
                <span className="wallet-balance__unit"> USDC</span>
              </span>
              {variant === 'card' && (
                <span className="wallet-balance__label">paper cash</span>
              )}
            </div>

            {variant === 'card' && (
              <div className="wallet-balance__meta">
                <span>{Number(balance.usdc || 0).toFixed(2)} USDC on-chain</span>
                {balance.chain_wallet && (
                  <>
                    <span className="wallet-balance__dot">·</span>
                    <span>{Number(balance.chain_wallet.eth || 0).toFixed(5)} ETH gas</span>
                  </>
                )}
              </div>
            )}

            {variant === 'card' && noTradableFunds && (
              <div className="wallet-balance__notice">
                No paper cash available. Stock paper trades will be blocked until the fake fund is topped up.
              </div>
            )}
          </>
        )}
      </div>

      <button
        type="button"
        className="wallet-balance__refresh"
       onClick={() => {
          fetchBalance(); // Refresh this instance
          window.dispatchEvent(new CustomEvent('wallet:refresh')); // Tell the other instance to refresh too
        }}
        disabled={loading}
        aria-label="Refresh wallet balance"
        title="Refresh"
      >
        <FaSyncAlt
          size={variant === 'pill' ? 10 : 12}
          className={loading ? 'wallet-balance__refresh-icon--spinning' : ''}
        />
      </button>
    </div>
  );
}
