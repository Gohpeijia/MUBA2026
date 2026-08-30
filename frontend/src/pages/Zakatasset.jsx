import axios from 'axios';
import { auth } from '../firebase';
import React, { useState, useEffect } from 'react';
import './Zakat.css';

const assetTypes = [
  { key: 'simpanan', label: 'Simpanan Tunai', icon: '🏦' },
  { key: 'pelaburan', label: 'Pelaburan & Saham', icon: '📈' },
  { key: 'emas', label: 'Emas & Perak', icon: '🪙' },
  { key: 'perniagaan', label: 'Aset Perniagaan', icon: '💼' },
];

export default function ZakatAsset({ onTotalChange, savedAssets }) {

  // 1. Declare state FIRST
  const [assets, setAssets] = useState({
    simpanan: [
      { id: 'simp-1', label: 'Bank', amount: '' },
      { id: 'simp-2', label: 'Tunai Semasa', amount: '' }
    ],
    pelaburan: [
      { id: 'pel-1', label: 'Pelaburan / Saham', amount: '' }
    ],
    emas: [
      { id: 'emas-1', label: 'Emas Fizikal', amount: '' }
    ],
    perniagaan: [
      { id: 'pern-1', label: 'Aset Perniagaan', amount: '' }
    ]
  });

  const [expanded, setExpanded] = useState({
    simpanan: true,
    pelaburan: false,
    emas: false,
    perniagaan: false
  });

  const [isEditing, setIsEditing] = useState(false);

  useEffect(() => {
    if (savedAssets && Object.keys(savedAssets).length > 0) {
      setAssets(savedAssets);
    }
  }, [savedAssets]);

  // 2. Declare helper functions SECOND
  const getCategoryTotal = (key) => {
    return assets[key].reduce((sum, item) => sum + (parseFloat(item.amount) || 0), 0);
  };

  // 3. Perform calculations that depend on state and helpers THIRD
  const grandTotal = assetTypes.reduce((sum, type) => sum + getCategoryTotal(type.key), 0);

  // 4. Run effects FOURTH
  useEffect(() => {
    if (onTotalChange) {
      onTotalChange(grandTotal);
    }
  }, [grandTotal, onTotalChange]);

  // ... (The rest of your handler functions and return statement remain exactly the same)
  const toggleExpand = (key) => {
    setExpanded((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  // Mengemas kini nilai teks nama atau jumlah amaun dalam sub-kategori
  const handleItemChange = (categoryKey, itemId, field, value) => {
    setAssets((prev) => ({
      ...prev,
      [categoryKey]: prev[categoryKey].map((item) =>
        item.id === itemId ? { ...item, [field]: value } : item
      )
    }));
  };

  // Menambah item sub-kategori baru secara dinamik
  const handleAddItem = (categoryKey) => {
    const newItem = {
      id: `${categoryKey}-${Date.now()}`,
      label: '',
      amount: ''
    };
    setAssets((prev) => ({
      ...prev,
      [categoryKey]: [...prev[categoryKey], newItem]
    }));
  };

  // Memadam item sub-kategori
  const handleDeleteItem = (categoryKey, itemId) => {
    setAssets((prev) => ({
      ...prev,
      [categoryKey]: prev[categoryKey].filter((item) => item.id !== itemId)
    }));
  };

  const handleActionClick = async () => {
      if (isEditing) {
        try {
          const user = auth.currentUser;
          const token = await user.getIdToken();
          
          // Push the payload to Flask
          await axios.post('http://127.0.0.1:5000/api/zakat/save-data', 
            { assets: assets }, 
            { headers: { Authorization: `Bearer ${token}` } }
          );
          
          console.log("✅ Assets saved securely to database!");
          setIsEditing(false);
        } catch (error) {
          console.error("Gagal menyimpan data:", error);
        }
      } else {
        setIsEditing(true);
      }
    };

  return (
    <section className="zakat-section">
      <h2 className="section-title">Jumlah Aset</h2>
      <p className="section-desc">Masukkan nilai semasa aset anda untuk pengiraan yang tepat.</p>

      <div className="asset-card">
          <div className="edit-hint-banner">
            <span>Sila klik butang ikon pen (✎) di penjuru kanan bawah untuk mula mengemas kini atau menambah sub-kategori aset anda.</span>
          </div>
        

        <div className="asset-rows">
          {assetTypes.map(({ key, label, icon }) => {
            const isCategoryOpen = expanded[key];
            const catTotal = getCategoryTotal(key);

            return (
              <div key={key} className="asset-category-group">
                {/* Bar utama kategori berfungsi sebagai pengepala dropdown */}
                <div 
                  className={`asset-row clickable ${isCategoryOpen ? 'active-row' : ''}`}
                  onClick={() => toggleExpand(key)}
                  title="Klik untuk melihat pecahan"
                >
                  <div className="asset-row-label">
                    <span className={`dropdown-chevron ${isCategoryOpen ? 'open' : ''}`}>▶</span>
                    <span className="asset-icon">{icon}</span>
                    <span className="category-main-text">{label}</span>
                  </div>
                  <div className="category-total-display">
                    RM {catTotal.toLocaleString('en-MY', { minimumFractionDigits: 2 })}
                  </div>
                </div>

                {/* Kandungan Dropdown Sub-Kategori */}
                {isCategoryOpen && (
                  <div className="sub-items-container">
                    {assets[key].map((item) => (
                      <div className="sub-item-row" key={item.id}>
                        <input
                          className="sub-item-name-input"
                          type="text"
                          placeholder="Nama item (cth: Maybank, Tunai Buku)"
                          value={item.label}
                          onChange={(e) => handleItemChange(key, item.id, 'label', e.target.value)}
                          disabled={!isEditing}
                        />
                        
                        <div className={`asset-input-wrap ${!isEditing ? 'disabled-wrap' : ''}`}>
                          <span className="input-prefix">RM</span>
                          <input
                            className="asset-input"
                            type="number"
                            min="0"
                            placeholder="0.00"
                            value={item.amount}
                            onChange={(e) => handleItemChange(key, item.id, 'amount', e.target.value)}
                            disabled={!isEditing}
                          />
                        </div>

                        {isEditing && (
                          <button
                            type="button"
                            className="btn-delete-sub"
                            onClick={() => handleDeleteItem(key, item.id)}
                            title="Padam sub-kategori"
                          >
                            🗑️
                          </button>
                        )}
                      </div>
                    ))}

                    {/* Butang Tambah Sub-Kategori Baru */}
                    {isEditing && (
                      <button
                        type="button"
                        className="btn-add-sub"
                        onClick={() => handleAddItem(key)}
                      >
                        ＋ Tambah Item Baru
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Bar Jumlah Keseluruhan */}
        <div className="asset-total-row">
          <span className="total-label">Jumlah Keseluruhan</span>
          <span className="total-amount">
            RM {grandTotal.toLocaleString('en-MY', { minimumFractionDigits: 2 })}
          </span>
        </div>

        {/* Floating Action Button */}
        <button 
          className={`edit-fab ${isEditing ? 'save-mode' : ''}`} 
          onClick={handleActionClick}
          title={isEditing ? "Simpan Aset ke Database" : "Edit Aset"}
        >
          {isEditing ? '💾' : '✎'}
        </button>
      </div>
    </section>
  );
}