import React, {useState, useEffect} from 'react';
import axios from 'axios';
import { auth } from '../firebase';
import { onAuthStateChanged } from 'firebase/auth';
import ZakatRingkasan from './ZakatRingkasan';
import ZakatAsset from './ZakatAsset';
import ZakatCalculator from './ZakatCalculator';
import ZakatNisab from './ZakatNisab';
import ZakatLiabiliti from './ZakatLiabiliti';
import Zakatbleamount from './Zakatbleamount';
import ZakatGoals from './ZakatGoals';   
import './Zakat.css';
import '../shared.css';

export default function Zakat() {

  const [nisabAmount, setNisabAmount] = useState(0);
  const [goldPrice, setGoldPrice] = useState(0);
  const [totalAsset, setTotalAsset] = useState(0);
  const [totalLiability, setTotalLiability] = useState(0);
  const [dbData, setDbData] = useState({});

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, async (user) => {
      if (user) {
        try {
          const token = await user.getIdToken();
          const headers = { Authorization: `Bearer ${token}` };

          // 1. Ambil nilai Nisab semasa
          const nisabRes = await axios.get('http://127.0.0.1:5000/api/zakat/nisab', { headers });
          if (nisabRes.data.success) {
            setNisabAmount(nisabRes.data.data.nisab_value);
            setGoldPrice(nisabRes.data.data.gold_price);
          }

          // 2. Ambil profil zakat pengguna yang tersimpan di database
          const profileRes = await axios.get('http://127.0.0.1:5000/api/zakat/data', { headers });
          if (profileRes.data.success && profileRes.data.data) {
            setDbData(profileRes.data.data);
          }
        } catch (error) {
          console.error("Gagal memuatkan data Zakat dari pangkalan data:", error);
        }
      }
    });

    return () => unsubscribe();
  }, []);

  return (
    <div className="zakat-page">
      <div className="zakat-header">
        <h1 className="zakat-main-title">Ringkasan Zakat</h1>
        <p className="zakat-subtitle">Pantau dan kira zakat anda dengan mudah</p>
      </div>

      {/*Section 1: Nisab */}
      <ZakatNisab nisabAmount={nisabAmount} goldPrice={goldPrice}/>

      {/* Section 2: Jumlah Bersih (Aset - Liabiliti) */}
      <Zakatbleamount totalAsset={totalAsset} totalLiability={totalLiability} nisabAmount={nisabAmount} savedHaul={dbData.haul_date}/>

      {/* Section 5: Ringkasan Zakat */}
      <ZakatRingkasan 
        nisabAmount={nisabAmount}
        totalAsset={totalAsset} 
        totalLiability={totalLiability} 
      />

      {/* Section 3: Jumlah Asset */}
      <ZakatAsset onTotalChange={setTotalAsset} savedAssets={dbData.assets}/>

      {/* Section 4: Jumlah Liabiliti */}
      <ZakatLiabiliti onTotalChange={setTotalLiability} 
      savedLiabilities={dbData.liabilities}
      />

      {/* Section 6: Matlamat Kewangan ← NEW */}
      <ZakatGoals savedGoals={dbData.zakat_goals}/>
    </div>
  );
}