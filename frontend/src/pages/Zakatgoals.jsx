import React, { useState, useRef, useEffect } from 'react';
import axios from 'axios';
import { auth } from '../firebase';
import './Zakat.css';
import './ZakatGoals.css';

const generateId = () => `goal-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

const DEFAULT_GOALS = [
  {
    id: generateId(),
    title: 'Umrah',
    icon: '🕋',
    targetAmount: 800000, 
    savedAmount: 0,  
    targetDate: '2026-12-31',
  },
];

/* ── Modal: Save Money ── */
function SaveMoneyModal({ goal, onClose, onSave }) {
  const [amount, setAmount] = useState('');
  const inputRef = useRef(null);

  useEffect(() => {
    setTimeout(() => inputRef.current?.focus(), 80);
  }, []);

  const handleSubmit = () => {
    const valRM = parseFloat(amount);
    if (!valRM || valRM <= 0) return;
    const valCents = Math.round(valRM * 100); 
    onSave(goal.id, valCents);
    onClose();
  };

  return (
    <div className="goal-modal-overlay" onClick={onClose}>
      <div className="goal-modal" onClick={e => e.stopPropagation()}>
        <div className="goal-modal-header">
          <span className="goal-modal-icon">{goal.icon}</span>
          <div>
            <p className="goal-modal-label">Simpan Wang untuk</p>
            <h3 className="goal-modal-title">{goal.title}</h3>
          </div>
          <button className="goal-modal-close" onClick={onClose}>✕</button>
        </div>

        <div className="goal-modal-body">
          <div className="goal-modal-progress-info">
            <span>Terkumpul: <strong>RM {(goal.savedAmount / 100).toLocaleString('en-MY', { minimumFractionDigits: 2 })}</strong></span>
            <span>Sasaran: <strong>RM {(goal.targetAmount / 100).toLocaleString('en-MY', { minimumFractionDigits: 2 })}</strong></span>
          </div>

          <label className="goal-modal-field-label">Jumlah Simpanan (RM)</label>
          <div className="goal-modal-input-wrap">
            <span className="goal-modal-prefix">RM</span>
            <input
              ref={inputRef}
              className="goal-modal-input"
              type="number"
              min="0.01"
              step="0.01"
              placeholder="0.00"
              value={amount}
              onChange={e => setAmount(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSubmit()}
            />
          </div>
        </div>

        <div className="goal-modal-footer">
          <button className="goal-btn-cancel" onClick={onClose}>Batal</button>
          <button
            className="goal-btn-save-money"
            onClick={handleSubmit}
            disabled={!amount || parseFloat(amount) <= 0}
          >
            💰 Simpan Wang
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Modal: Edit / Add Goal ── */
function EditGoalModal({ goal, onClose, onSave }) {
  const [form, setForm] = useState(
    goal
      ? { title: goal.title, icon: goal.icon, targetAmount: (goal.targetAmount / 100).toString(), targetDate: goal.targetDate }
      : { title: '', icon: '🎯', targetAmount: '', targetDate: '' }
  );

  const ICONS = ['🕋', '🏠', '🚗', '✈️', '🎓', '💍', '💻', '🏖️', '🎯', '💡', '🌙', '📦'];

  const set = (field, value) => setForm(prev => ({ ...prev, [field]: value }));

  const handleSave = () => {
    const targetRM = parseFloat(form.targetAmount);
    if (!form.title.trim() || !targetRM || targetRM <= 0) return;
    onSave({ ...form, targetAmount: Math.round(targetRM * 100) });
    onClose();
  };

  return (
    <div className="goal-modal-overlay" onClick={onClose}>
      <div className="goal-modal goal-modal--edit" onClick={e => e.stopPropagation()}>
        <div className="goal-modal-header">
          <span className="goal-modal-icon">{form.icon}</span>
          <div>
            <p className="goal-modal-label">{goal ? 'Edit Matlamat' : 'Matlamat Baru'}</p>
            <h3 className="goal-modal-title">{form.title || '—'}</h3>
          </div>
          <button className="goal-modal-close" onClick={onClose}>✕</button>
        </div>

        <div className="goal-modal-body">
          <label className="goal-modal-field-label">Pilih Ikon</label>
          <div className="goal-icon-picker">
            {ICONS.map(ic => (
              <button key={ic} className={`goal-icon-btn ${form.icon === ic ? 'selected' : ''}`} onClick={() => set('icon', ic)}>{ic}</button>
            ))}
          </div>

          <label className="goal-modal-field-label">Nama Matlamat</label>
          <input className="goal-edit-text-input" type="text" placeholder="cth: Umrah, Kereta Baru..." value={form.title} onChange={e => set('title', e.target.value)} />

          <label className="goal-modal-field-label">Jumlah Sasaran (RM)</label>
          <div className="goal-modal-input-wrap">
            <span className="goal-modal-prefix">RM</span>
            <input className="goal-modal-input" type="number" min="0.01" step="0.01" placeholder="0.00" value={form.targetAmount} onChange={e => set('targetAmount', e.target.value)} />
          </div>

          <label className="goal-modal-field-label">Tarikh Sasaran</label>
          <input className="goal-edit-text-input" type="date" value={form.targetDate} onChange={e => set('targetDate', e.target.value)} />
        </div>

        <div className="goal-modal-footer">
          <button className="goal-btn-cancel" onClick={onClose}>Batal</button>
          <button className="goal-btn-save-money" onClick={handleSave} disabled={!form.title.trim() || !form.targetAmount || parseFloat(form.targetAmount) <= 0}>
            ✓ Simpan Matlamat
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Single Goal Card ── */
function GoalCard({ goal, index, total, onSaveClick, onEdit, onDelete, onMoveUp, onMoveDown }) {
  const pct = Math.min(100, (goal.savedAmount / goal.targetAmount) * 100);
  const remainingCents = Math.max(0, goal.targetAmount - goal.savedAmount);
  const isComplete = pct >= 100;

  const formatDate = (dateStr) => {
    if (!dateStr) return '—';
    const d = new Date(dateStr);
    return d.toLocaleDateString('ms-MY', { day: 'numeric', month: 'long', year: 'numeric' });
  };

  return (
    <div className={`goal-card ${isComplete ? 'goal-card--complete' : ''}`}>
      <div className="goal-card-top">
        <div className="goal-card-icon-title">
          <span className="goal-card-icon">{goal.icon}</span>
          <div>
            <h3 className="goal-card-title">{goal.title}</h3>
            <p className="goal-card-date">Sasaran: {formatDate(goal.targetDate)}</p>
          </div>
        </div>

        <div className="goal-card-controls">
          <button className="goal-ctrl-btn" onClick={() => onMoveUp(index)} disabled={index === 0} title="Alih ke atas">↑</button>
          <button className="goal-ctrl-btn" onClick={() => onMoveDown(index)} disabled={index === total - 1} title="Alih ke bawah">↓</button>
          <button className="goal-ctrl-btn goal-ctrl-edit" onClick={() => onEdit(goal)} title="Edit">✎</button>
          <button className="goal-ctrl-btn goal-ctrl-del" onClick={() => onDelete(goal.id)} title="Padam">✕</button>
        </div>
      </div>

      <div className="goal-progress-section">
        <div className="goal-progress-bar-track">
          <div className={`goal-progress-bar-fill ${isComplete ? 'fill--complete' : ''}`} style={{ width: `${pct}%` }} />
        </div>
        <div className="goal-progress-labels">
          <span className={`goal-pct-badge ${isComplete ? 'badge--complete' : ''}`}>
            {isComplete ? '✓ Selesai' : `${pct.toFixed(1)}%`}
          </span>
          <span className="goal-remaining-text">
            {isComplete ? 'Tahniah! Matlamat tercapai 🎉' : `Baki: RM ${(remainingCents / 100).toLocaleString('en-MY', { minimumFractionDigits: 2 })}`}
          </span>
        </div>
      </div>

      <div className="goal-amounts-row">
        <div className="goal-amount-block">
          <span className="goal-amount-label">Terkumpul</span>
          <span className="goal-amount-value goal-amount-saved">
            <span className="goal-amount-rm">RM</span>
            {(goal.savedAmount / 100).toLocaleString('en-MY', { minimumFractionDigits: 2 })}
          </span>
        </div>
        <div className="goal-amount-divider" />
        <div className="goal-amount-block">
          <span className="goal-amount-label">Sasaran</span>
          <span className="goal-amount-value">
            <span className="goal-amount-rm">RM</span>
            {(goal.targetAmount / 100).toLocaleString('en-MY', { minimumFractionDigits: 2 })}
          </span>
        </div>
      </div>

      <button className="goal-save-money-btn" onClick={() => onSaveClick(goal)}>
        <span>💰</span> Simpan Wang
      </button>
    </div>
  );
}

//* ── Main ZakatGoals Component ── */
export default function ZakatGoals({ savedGoals }) {
  const [goals, setGoals] = useState(DEFAULT_GOALS);
  const [saveModal, setSaveModal] = useState(null);   
  const [editModal, setEditModal] = useState(null);   

  const isInitialMount = useRef(true);
  
  // 1. Pull database records on initial load
  useEffect(() => {
    if (savedGoals && savedGoals.length > 0) {
      setGoals(savedGoals);
    }
  }, [savedGoals]);

  // 2. 🟢 AUTO-SAVE MAGIC
  // This automatically runs and saves to the database every time 'goals' changes!
  useEffect(() => {
    if (isInitialMount.current) {
      isInitialMount.current = false;
      return;
    }

    const syncToDatabase = async () => {
      try {
        const user = auth.currentUser;
        if (!user) return;
        const token = await user.getIdToken();
        
        await axios.post('http://127.0.0.1:5000/api/zakat/save-data', 
          { zakat_goals: goals }, 
          { headers: { Authorization: `Bearer ${token}` } }
        );
        console.log("✅ Matlamat auto-saved ke database!");
      } catch (error) {
        console.error("Gagal menyimpan matlamat:", error);
      }
    };

    syncToDatabase();
  }, [goals]); // <- This tells React to watch the 'goals' array

  // 🟢 CLEAN HANDLERS: Notice there is NO syncToDatabase() in here anymore.
  // The useEffect above does it automatically for us!
  const handleAddSavings = (goalId, amountCents) => {
    setGoals(prev => prev.map(g => g.id === goalId ? { ...g, savedAmount: g.savedAmount + amountCents } : g));
  };

  const handleDelete = (goalId) => {
    setGoals(prev => prev.filter(g => g.id !== goalId));
  };

  const handleEdit = (goal) => {
    setEditModal(goal);
  };

  const handleSaveEdit = (updated) => {
    setGoals(prev => {
      if (editModal === 'new') {
        return [...prev, { ...updated, id: generateId(), savedAmount: 0 }];
      } else {
        return prev.map(g => g.id === editModal.id ? { ...g, ...updated } : g);
      }
    });
  };

  const handleMoveUp = (index) => {
    if (index === 0) return;
    setGoals(prev => {
      const next = [...prev];
      [next[index - 1], next[index]] = [next[index], next[index - 1]];
      return next;
    });
  };

  const handleMoveDown = (index) => {
    setGoals(prev => {
      if (index === prev.length - 1) return prev;
      const next = [...prev];
      [next[index], next[index + 1]] = [next[index + 1], next[index]];
      return next;
    });
  };

  const totalSavedCents = goals.reduce((s, g) => s + g.savedAmount, 0);
  const totalTargetCents = goals.reduce((s, g) => s + g.targetAmount, 0);

  return (
    <section className="zakat-section">
      <h2 className="section-title">Matlamat Kewangan</h2>
      <p className="section-desc">Tetapkan dan jejaki matlamat simpanan anda dengan mudah.</p>

      {/* Summary banner */}
      {goals.length > 0 && (
        <div className="goal-summary-banner">
          <div className="goal-summary-item">
            <span className="goal-summary-label">Jumlah Matlamat</span>
            <span className="goal-summary-value">{goals.length}</span>
          </div>
          <div className="goal-summary-sep" />
          <div className="goal-summary-item">
            <span className="goal-summary-label">Jumlah Terkumpul</span>
            <span className="goal-summary-value goal-summary-saved">RM {(totalSavedCents / 100).toLocaleString('en-MY', { minimumFractionDigits: 2 })}</span>
          </div>
          <div className="goal-summary-sep" />
          <div className="goal-summary-item">
            <span className="goal-summary-label">Jumlah Sasaran</span>
            <span className="goal-summary-value">RM {(totalTargetCents / 100).toLocaleString('en-MY', { minimumFractionDigits: 2 })}</span>
          </div>
        </div>
      )}

      {/* Goal cards */}
      {goals.length === 0 ? (
        <div className="goal-empty-state">
          <span className="goal-empty-icon">🎯</span>
          <p>Tiada matlamat lagi. Tambah matlamat pertama anda!</p>
        </div>
      ) : (
        <div className="goal-cards-grid">
          {goals.map((goal, index) => (
            <GoalCard
              key={goal.id}
              goal={goal}
              index={index}
              total={goals.length}
              onSaveClick={setSaveModal}
              onEdit={handleEdit}
              onDelete={handleDelete}
              onMoveUp={handleMoveUp}
              onMoveDown={handleMoveDown}
            />
          ))}
        </div>
      )}

      {/* Add new goal button */}
      <button className="goal-add-btn" onClick={() => setEditModal('new')}>
        ＋ Tambah Matlamat Baru
      </button>

      {/* Modals */}
      {saveModal && (
        <SaveMoneyModal
          goal={saveModal}
          onClose={() => setSaveModal(null)}
          onSave={handleAddSavings}
        />
      )}

      {editModal && (
        <EditGoalModal
          goal={editModal === 'new' ? null : editModal}
          onClose={() => setEditModal(null)}
          onSave={handleSaveEdit}
        />
      )}
    </section>
  );
}