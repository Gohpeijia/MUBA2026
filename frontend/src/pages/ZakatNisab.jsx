import React from 'react';
import './Zakat.css';

export default function ZakatNisab({ nisabAmount, goldPrice }) {
  // 🟢 No more hardcoded fallbacks! We use the exact data from the backend.
  const displayNisab = nisabAmount || 0;
  const displayGold = goldPrice || 0;

  return (
    <section className="zakat-section">
      <div className="ringkasan-grid">

        {/* Card: Nisab */}
        <div className="zakat-card card--due">
          
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
            <div className="card-label" style={{ margin: 0 }}>Nisab Semasa (85g Emas)</div>
            
            {/* 🟢 Display the dynamic Gold Price per gram here */}
            <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontWeight: '600' }}>
              Harga Emas: RM {displayGold.toFixed(2)}/g
            </div>
          </div>

          <div className="card-amount" style={{ width: '100%', display: 'flex', justifyContent: 'flex-start', alignItems: 'baseline' }}>
            <span className="price-container">
              <span className="currencyz">RM</span>
              <span className="amountz">{displayNisab.toLocaleString('en-MY', { minimumFractionDigits: 2 })}</span>
            </span>
          </div>
          
        </div>

      </div>
    </section>
  );
}