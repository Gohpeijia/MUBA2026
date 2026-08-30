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
    question: 'Apakah status pekerjaan anda?',
    type: 'chips',
    options: ['Bekerja (Swasta)', 'Bekerja (Kerajaan)', 'Bekerja Sendiri', 'Pelajar', 'Tidak Bekerja'],
  },
  {
    key: 'monthlyIncome',
    question: 'Berapakah anggaran pendapatan bulanan anda?',
    type: 'number',
    prefix: 'RM',
    placeholder: 'cth: 5000',
  },
  {
    key: 'investmentExperience',
    question: 'Apakah pengalaman pelaburan anda?',
    type: 'chips',
    options: ['Tiada Pengalaman', 'Pemula (< 1 tahun)', 'Pertengahan (1–5 tahun)', 'Berpengalaman (> 5 tahun)'],
  },
  {
    key: 'riskTolerance',
    question: 'Apakah tahap toleransi risiko anda?',
    type: 'chips',
    options: ['Rendah (Selamat)', 'Sederhana', 'Tinggi (Agresif)'],
  },
  {
    key: 'zakatGoal',
    question: 'Apakah matlamat utama anda menggunakan Amanah?',
    type: 'chips',
    options: [
      'Kira & jejak zakat saya',
      'Urus aset & liabiliti',
      'Dapatkan nasihat pelaburan',
      'Kesemuanya',
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
      setError('Sila pilih atau isi jawapan sebelum meneruskan.');
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
      if (!user) throw new Error('Pengguna tidak dijumpai. Sila log masuk semula.');

      // 1. Get the secure token for the backend @require_auth decorator
      const token = await user.getIdToken();

      // 2. Format the payload exactly how portfolio_routes.py expects it
      const payload = {
        preference: {
          employmentStatus: answers.employmentStatus || '',
          monthlyIncome: Number(answers.monthlyIncome) || 0,
          investmentExperience: answers.investmentExperience || '',
          riskTolerance: answers.riskTolerance || '',
          zakatGoal: answers.zakatGoal || ''
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
        throw new Error(response.data.error || 'Ralat menyimpan data.');
      }

      setDone(true);
      setTimeout(() => navigate('/zakat'), 2000);

    } catch (err) {
      // Catch backend errors or network errors safely
      setError(err.response?.data?.error || err.message || 'Ralat menyimpan data. Sila cuba lagi.');
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
            <h2 className="pref-complete-title">Terima kasih!</h2>
            <p className="pref-complete-text">
              Profil anda telah disimpan. Kami sedang menyediakan pengalaman terbaik untuk anda…
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
          <h1 className="pref-title">Profil Kewangan</h1>
          <p className="pref-subtitle">Bantu kami memahami keperluan zakat anda</p>
        </div>

        {/* Progress */}
        <div className="pref-progress-wrap">
          <div className="pref-progress-label">
            <span>Soalan {step + 1} daripada {totalSteps}</span>
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
          <div className="pref-question-label">Soalan {step + 1}</div>
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
            ← Kembali
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
              'Seterusnya →'
            ) : (
              'Simpan & Mulakan ✓'
            )}
          </button>
        </div>

      </div>
    </div>
  );
}