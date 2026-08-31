import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { auth } from "../firebase";
import './Preferences.css';
import '../shared.css';

/* ─── Survey definition ─────────────────────────────────────
   Each step has a field key, question, and input type.
   'chips'  → pick one option from a list
   'number' → numeric input with prefix
   'text'   → free-text input
────────────────────────────────────────────────────────────── */
const STEPS = [
  {
    key: 'employmentStatus',
    question: 'What is your employment status?',
    type: 'chips',
    options: ['Employed (Private)', 'Employed (Government)', 'Self-Employed', 'Student', 'Not Employed'],
  },
  {
    key: 'monthlyIncome',
    question: 'What is your estimated monthly income?',
    type: 'number',
    prefix: 'RM',
    placeholder: 'e.g. 5000',
  },
  {
    key: 'investmentExperience',
    question: 'What is your experience with on-chain options trading (Thetanuts, DeFi options)?',
    type: 'chips',
    options: ['No Experience', 'Beginner (< 1 year)', 'Intermediate (1–5 years)', 'Experienced (> 5 years)'],
  },
  {
    key: 'riskTolerance',
    question: 'What is your risk tolerance level?',
    type: 'chips',
    options: ['Low (Conservative)', 'Moderate', 'High (Aggressive)'],
  },
  {
    key: 'riskCopilotMode',
    question: 'How should your Risk Copilot assist you?',
    type: 'chips',
    options: [
      'Alert me only, I act manually',
      'Suggest actions, I confirm each one',
      'Fully automated recommendations',
    ],
  },
  {
    key: 'autoHedgingAgent',
    question: 'Do you want to enable the Autonomous Hedging Agent for your OptionBook / OptionFactory positions?',
    type: 'chips',
    options: [
      'Yes, fully autonomous hedging',
      'Yes, but confirm before executing on-chain',
      'No, I will hedge manually',
    ],
  },
  {
    key: 'primaryGoal',
    question: 'What is your main goal for using this agent?',
    type: 'chips',
    options: [
      'Track & analyze my options positions',
      'Manage risk & automate hedging',
      'Get AI trading advice & insights',
      'All of the above',
    ],
  },
];

export default function Preferences() {
  const navigate = useNavigate();

  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);

  const current = STEPS[step];
  const totalSteps = STEPS.length;
  const progressPct = Math.round(((step) / totalSteps) * 100);

  /* ─── Handlers ──────────────────────────────────────────── */

  function handleChip(value) {
    setAnswers(prev => ({ ...prev, [current.key]: value }));
  }

  function handleInput(e) {
    setAnswers(prev => ({ ...prev, [current.key]: e.target.value }));
  }

  function isCurrentAnswered() {
    const val = answers[current.key];
    if (!val) return false;
    if (typeof val === 'string') return val.trim().length > 0;
    return true;
  }

  async function handleNext() {
    setError('');

    if (!isCurrentAnswered()) {
      setError('Please select or fill in an answer before continuing.');
      return;
    }

    if (step < totalSteps - 1) {
      setStep(s => s + 1);
      return;
    }

    // Last step — save to Firestore
    setSaving(true);
    try {
      const user = auth.currentUser;
      if (!user) throw new Error('User not found. Please sign in again.');

      // 1. Get the secure token for the backend @require_auth decorator
      const token = await user.getIdToken();

      // 2. Format the payload exactly how portfolio_routes.py expects it
      const payload = {
        preference: {
          employmentStatus: answers.employmentStatus || '',
          monthlyIncome: Number(answers.monthlyIncome) || 0,
          investmentExperience: answers.investmentExperience || '',
          riskTolerance: answers.riskTolerance || '',
          riskCopilotMode: answers.riskCopilotMode || '',
          autoHedgingAgent: answers.autoHedgingAgent || '',
          primaryGoal: answers.primaryGoal || ''
        }
      };

      // 3. Send the data to your Flask server
      const response = await axios.post(
        'http://127.0.0.1:5000/api/stocks/portfolio/update',
        payload,
        {
          headers: {
            Authorization: `Bearer ${token}` // Passes the firewall security
          }
        }
      );

      if (!response.data.success) {
        throw new Error(response.data.error || 'Error saving data.');
      }

      setDone(true);
      setTimeout(() => navigate('/dashboard'), 2000);

    } catch (err) {
      // Catch backend errors or network errors safely
      setError(err.response?.data?.error || err.message || 'Error saving data. Please try again.');
    } finally {
      setSaving(false);
    }
  }

  function handleBack() {
    setError('');
    if (step > 0) setStep(s => s - 1);
  }

  /* ─── Completion Screen ─────────────────────────────────── */
  if (done) {
    return (
      <div className="pref-page">
        <div className="pref-card">
          <div className="pref-complete">
            <div className="pref-complete-icon">✅</div>
            <h2 className="pref-complete-title">Thank you!</h2>
            <p className="pref-complete-text">
              Your profile has been saved. We're setting up your Risk Copilot and Hedging Agent…
            </p>
            <div style={{ display: 'flex', justifyContent: 'center' }}>
              <span className="pref-spinner" style={{
                borderColor: 'rgba(26,107,107,0.25)',
                borderTopColor: 'var(--teal)',
                width: 28, height: 28, borderWidth: 3
              }} />
            </div>
          </div>
        </div>
      </div>
    );
  }

  /* ─── Main Survey Render ────────────────────────────────── */
  return (
    <div className="pref-page">
      <div className="pref-card">

        {/* Header */}
        <div className="pref-header">
          <h1 className="pref-title">Trading Profile</h1>
          <p className="pref-subtitle">Help us configure your Risk Copilot and Hedging Agent</p>
        </div>

        {/* Progress */}
        <div className="pref-progress-wrap">
          <div className="pref-progress-label">
            <span>Question {step + 1} of {totalSteps}</span>
            <span>{progressPct}%</span>
          </div>
          <div className="pref-progress-bar">
            <div
              className="pref-progress-fill"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="pref-error">
            <span>⚠️</span> {error}
          </div>
        )}

        {/* Question */}
        <div className="pref-question">
          <div className="pref-question-label">Question {step + 1}</div>
          <p className="pref-question-text">{current.question}</p>

          {/* Chips */}
          {current.type === 'chips' && (
            <div className="pref-options">
              {current.options.map(opt => (
                <button
                  key={opt}
                  className={`pref-option ${answers[current.key] === opt ? 'selected' : ''}`}
                  type="button"
                  onClick={() => handleChip(opt)}
                >
                  {opt}
                </button>
              ))}
            </div>
          )}

          {/* Number input */}
          {current.type === 'number' && (
            <div className="pref-input-wrap">
              {current.prefix && (
                <span className="pref-input-prefix">{current.prefix}</span>
              )}
              <input
                className="pref-input"
                type="number"
                placeholder={current.placeholder}
                value={answers[current.key] || ''}
                onChange={handleInput}
                min={0}
              />
            </div>
          )}

          {/* Text input */}
          {current.type === 'text' && (
            <div className="pref-input-wrap">
              <input
                className="pref-input"
                type="text"
                placeholder={current.placeholder}
                value={answers[current.key] || ''}
                onChange={handleInput}
              />
            </div>
          )}
        </div>

        {/* Nav buttons */}
        <div className="pref-nav">
          <button
            className="pref-btn-back"
            type="button"
            onClick={handleBack}
            disabled={step === 0 || saving}
          >
            ← Back
          </button>

          <button
            className="pref-btn-next"
            type="button"
            onClick={handleNext}
            disabled={saving}
          >
            {saving ? (
              <span className="pref-spinner" />
            ) : step < totalSteps - 1 ? (
              'Next →'
            ) : (
              'Save & Start ✓'
            )}
          </button>
        </div>

      </div>
    </div>
  );
}