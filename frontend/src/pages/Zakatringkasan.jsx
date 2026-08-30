import React from 'react';
import './Zakat.css';

// Removed zakatData from the props since we compute it locally now
export default function ZakatRingkasan({ nisabAmount = 0, totalAsset = 0, totalLiability = 0 }) {

  // 1. Calculate the net amount (Asset - Liability) locally
  const netAmount = totalAsset - totalLiability;
  const displayAmount = netAmount > 0 ? netAmount : 0.00;
  
  // 2. Check Nisab eligibility
  const isEligible = displayAmount >= nisabAmount;

  // 3. Calculate 2.5% zakat if eligible, otherwise 0
  const totalZakat = isEligible ? displayAmount * 0.025 : 0.00;

  return (
    <section className="zakat-section">
      <div className="ringkasan-grid">

        {/* Card 1: Zakat Perlu Dibayar */}
        <div className="zakat-card card--due">
          <div className="card-label">Zakat Perlu Dibayar</div>

          <div className="zakat-breakdown">
            <p>Jumlah Bersih:
              <span className="zakat-rate"> x 2.5%</span>
              <span className="price-container">
                <span className="currencyz">RM</span> 
                {/* FIXED: Replaced data.pendapatan with displayAmount */}
                <span className="amountz"> {displayAmount.toFixed(2)}</span>
              </span>
            </p>
          </div>

          <hr className="zakat-divider" />

          <div className="card-amount">
            <span className="total-label">JUMLAH: </span>
            <span className="price-container">
              <span className="currency">RM</span>
              <span className="amount">{totalZakat.toFixed(2)}</span>
            </span>
          </div>
          
          <div className="edit-hint-banner2">
            <span>
              {isEligible 
                ? '✨ Alhamdulillah, anda LAYAK dan WAJIB menunaikan zakat.' 
                : 'Anda BELUM LAYAK menunaikan zakat (Jumlah bersih di bawah paras Nisab).'}
            </span>
          </div>
        </div>
        
      </div>
    </section>
  );
}