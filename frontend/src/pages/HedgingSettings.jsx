import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { auth } from '../firebase';
import './preferences.css';
import '../shared.css';

const HEDGING_OPTIONS = [
  'Yes, fully autonomous hedging',
  'Yes, but confirm before executing on-chain',
  'No, I will hedge manually',
];

export default function HedgingSettings() {
  const [current, setCurrent] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    async function loadCurrent() {
      try {
        const user = auth.currentUser;
        if (!user) throw new Error('Not signed in.');
        const token = await user.getIdToken();
        const res = await axios.get(
          'http://127.0.0.1:5000/api/stocks/portfolio/me',
          { headers: { Authorization: `Bearer ${token}` } }
        );
        setCurrent(res.data.data?.preference?.autoHedgingAgent || null);
      } catch (err) {
        setError(err.response?.data?.error || err.message || 'Could not load current setting.');
      } finally {
        setLoading(false);
      }
    }
    loadCurrent();
  }, []);

  async function handleSelect(option) {
    if (option === current || saving) return;
    setSaving(true);
    setError('');
    setSaved(false);
    try {
      const user = auth.currentUser;
      if (!user) throw new Error('Not signed in.');
      const token = await user.getIdToken();
      const res = await axios.patch(
        'http://127.0.0.1:5000/api/stocks/portfolio/preference/hedging-agent',
        { autoHedgingAgent: option },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (!res.data.success) throw new Error(res.data.error || 'Failed to save.');
      setCurrent(option);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setError(err.response?.data?.error || err.message || 'Error saving setting.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="pref-page">
      <div className="pref-card">
        <div className="pref-header">
          <h1 className="pref-title">Settings</h1>
          <p className="pref-subtitle">Update how your Autonomous Hedging Agent behaves</p>
        </div>

        {error && <div className="pref-error"><span>⚠️</span> {error}</div>}

        {loading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 20 }}>
            <span className="pref-spinner" />
          </div>
        ) : (
          <div className="pref-question">
            <div className="pref-question-label">Autonomous Hedging Agent</div>
            <p className="pref-question-text">
              Do you want to enable the Autonomous Hedging Agent for your OptionBook / OptionFactory positions?
            </p>
            <div className="pref-options">
              {HEDGING_OPTIONS.map(opt => (
                <button
                  key={opt}
                  type="button"
                  className={`pref-option ${current === opt ? 'selected' : ''}`}
                  onClick={() => handleSelect(opt)}
                  disabled={saving}
                >
                  {opt}
                </button>
              ))}
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 16 }}>
              {saving && <span className="pref-spinner" />}
              {saved && <span style={{ color: 'var(--teal)' }}>✓ Saved</span>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}