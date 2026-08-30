import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { auth } from '../firebase';
import './Zakat.css';

export default function Zakatbleamount({ totalAsset = 0, totalLiability = 0, nisabAmount = 0, savedHaul }) {
  const [isEditing, setIsEditing] = useState(false);
  const [haulDate, setHaulDate] = useState('2026-01-01'); // Default fallback date

  useEffect(() => {
    if (savedHaul) setHaulDate(savedHaul);
  }, [savedHaul]);

  const saveDateToDB = async (dateStr) => {
    try {
        const user = auth.currentUser;
        if (!user) return;
        const token = await user.getIdToken();
        
        await axios.post('http://127.0.0.1:5000/api/zakat/save-data', 
          { haul_date: dateStr }, 
          { headers: { Authorization: `Bearer ${token}` } }
        );
    } catch (err) {
        console.error("Error saving Haul Date", err);
    }
  };

  const handleDateChange = (e) => {
    const selectedDate = e.target.value;
    if (!selectedDate) return; 
    
    setHaulDate(selectedDate);
    saveDateToDB(selectedDate); // 🟢 Auto-save!
    setIsEditing(false);
  };

  const netAmount = totalAsset - totalLiability;
  const displayAmount = netAmount > 0 ? netAmount : 0.00;

  // Helper function to get today's date in YYYY-MM-DD format
  const getTodayString = () => {
    const today = new Date();
    const year = today.getFullYear();
    const month = String(today.getMonth() + 1).padStart(2, '0');
    const day = String(today.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  };

  const formatDateDisplay = (dateString) => {
    if (!dateString) return '';
    const date = new Date(dateString);
    if (isNaN(date.getTime())) return dateString;
    
    return date.toLocaleDateString('en-MY', {
      day: '2-digit',
      month: 'short',
      year: 'numeric'
    }).replace(/ /g, '-');
  };

  // Function to calculate remaining days based on 364 days Haul cycle
  const calculateRemainingDays = (startDateString) => {
    if (!startDateString) return 364;
    
    const start = new Date(startDateString);
    start.setHours(0, 0, 0, 0);
    
    const today = new Date();
    today.setHours(0, 0, 0, 0);

    const diffTime = today.getTime() - start.getTime();
    const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
    
    const remaining = 364 - diffDays;
    return remaining;
  };

  const remainingDays = calculateRemainingDays(haulDate);

  return (
    <section className="zakat-section">
      
      {/* Hides the internal webkit clear 'X' in the input box */}
      <style>{`
        input[type="date"]::-webkit-clear-button,
        input[type="date"]::-webkit-inner-spin-button {
          display: none;
          -webkit-appearance: none;
        }
      `}</style>

      <div className="ringkasan-grid">

        {/* Card: Zakatble Amount (Strictly Read-Only) */}
        <div className="zakat-card card--history">
          <div>
            <div className="card-label">Jumlah Bersih <br/>(Aset - Liabiliti)</div>
            
            <span className="price-container">
              <span className="currencyz">RM</span>
              <span className="amountz">
                {displayAmount.toLocaleString('en-MY', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
            </span>
          </div>
        </div>

        {/* Card: Haul Date & Countdown */}
        <div className="zakat-card card--history" style={{ position: 'relative' }}>
          <div className="card-label">Haul</div>
          
          {/* Flex container to place Date and Countdown side by side */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginTop: '0.4rem', marginRight: '2.5rem' }}>
            
            {/* Left Side: Tarikh Mula */}
            <div>
              <div style={{ fontSize: '0.85rem', fontWeight: '600', color: 'var(--text-muted)', marginBottom: '0.2rem' }}>
                Tarikh Mula
              </div>
              <div className="card-amount">
                {isEditing ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                    <div className="asset-input-wrap">
                      <input 
                        type="date" 
                        className="asset-input" 
                        value={haulDate} 
                        max={getTodayString()}
                        required /* 🟢 NEW: Forces browser to hide the 'Clear' button in the popup */
                        onChange={handleDateChange} 
                        onBlur={() => setIsEditing(false)} 
                        autoFocus 
                      />
                    </div>
                    
                    {/* Custom Instant Save Today Button */}
                    <button 
                      onMouseDown={(e) => {
                        e.preventDefault(); 
                        const today = getTodayString();
                        setHaulDate(today);
                        console.log("Auto-saving Haul Date to database:", today);
                        setIsEditing(false);
                      }}
                      style={{
                        background: 'var(--teal-light, #e0f2f1)',
                        color: 'var(--teal, #1a6b6b)',
                        border: '1px solid #b8d8d8',
                        padding: '0.4rem 0.8rem',
                        borderRadius: 'var(--radius-sm, 6px)',
                        fontSize: '0.8rem',
                        fontWeight: '700',
                        cursor: 'pointer',
                        whiteSpace: 'nowrap'
                      }}
                    >
                      Hari Ini
                    </button>
                  </div>
                ) : (
                  <span className="date">{formatDateDisplay(haulDate)}</span>
                )}
              </div>
            </div>

            {/* Right Side: Countdown (Hidden while editing) */}
            {!isEditing && (
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: '0.85rem', fontWeight: '600', color: 'var(--text-muted)', marginBottom: '0.2rem' }}>
                  Baki Haul
                </div>
                {remainingDays > 0 ? (
                  <div className="price-container" style={{ marginTop: 0 }}>
                    <span className="amountz">{remainingDays}</span>
                    <span className="currencyz" style={{ marginLeft: '0.3rem' }}>Hari</span>
                  </div>
                ) : (
                  <span className="amountz" style={{ fontSize: '1.4rem' }}>Cukup Haul</span>
                )}
              </div>
            )}
            
          </div>
          
          {/* Floating Edit Button */}
          {!isEditing && (
            <button 
              className="edit-fab" 
              onClick={() => setIsEditing(true)}
              title="Edit Haul"
            >
              ✎
            </button>
          )}
        </div>

      </div>
    </section>
  );
}