# prompt_engine_v2.py  (Versi Diperbaiki)
#
# BUG DIPERBAIKI:
#   BUG 2 — Apabila tiada ticker, blok `if tiada_ticker` membuang
#            structured_consensus terus → Amanah jawab soalan am sahaja
#            tanpa sebarang konteks swarm atau pasaran.
#
#   PENYELESAIAN:
#   - Jika tiada ticker DAN tiada konsensus → balas mesra biasa (sama seperti dulu)
#   - Jika tiada ticker TETAPI ada konsensus (soalan pasaran am) →
#     sertakan ringkasan pandangan swarm dalam prompt supaya
#     Amanah boleh bagi jawapan yang lebih bermakna

from news_fetcher import bina_data_kuantitatif, format_data_untuk_prompt
import asyncio


class ShariahAdvisorPromptManager:

    def get_system_prompt(self, preferences: dict = None) -> str:
        konteks_pengguna = ""
        if preferences:
            konteks_pengguna = f"""
Maklumat Pengguna:
- Pekerjaan       : {preferences.get('employmentStatus', 'Tidak diketahui')}
- Pendapatan      : RM{preferences.get('monthlyIncome', 0)}
- Pengalaman      : {preferences.get('investmentExperience', 'Tidak diketahui')}
- Toleransi Risiko: {preferences.get('riskTolerance', 'Sederhana')}
- Matlamat        : {preferences.get('zakatGoal', 'Umum')}
"""
        return f"""Anda ialah 'Amanah', Penasihat Kewangan dan Syariah AI yang pakar, ramah, dan sangat profesional.

{konteks_pengguna}

ARAHAN SANGAT KETAT (MESTI DIPATUHI):
1.  BAHASA MALAYSIA SAHAJA: Anda MESTI menjawab 100% dalam Bahasa Melayu. Jangan gunakan Bahasa Inggeris.
2.  RINGKAS & MUDAH DIBACA: Gunakan bullet points (•) dan emoji supaya mudah dibaca.
3.  MESRA & EMOJI: Gunakan emoji yang sesuai (📈, 💡, 🛑, 🤖) untuk menjadikan perbualan lebih menarik.
4.  JANGAN perkenalkan diri anda berulang kali dalam setiap mesej. Terus jawab soalan pengguna melainkan ini adalah sapaan pertama mereka..
5.  SEMBUNYIKAN JARGON TEKNIKAL MENTAH: Jangan sebut "ETHICAL_CONFLICT" atau "BULLISH_PRESSURE" secara literal.
6.  ANALISIS TETAP DIBENARKAN UNTUK SAHAM TIDAK HALAL: Berikan analisis pasaran tetapi WAJIB tambah amaran Syariah.
7.  TUNJUKKAN SUARA SETIAP AGEN AI: Terangkan pandangan setiap agen dengan ringkas apabila data swarm tersedia.
8.  GUNA DATA SEBENAR: Jika harga, asas kewangan, atau sentimen tersedia, MESTI sebut angka sebenar.
9.  SOALAN AM (TIADA SAHAM SPESIFIK): Jawab berdasarkan pengetahuan kewangan dan Syariah anda. Jika pandangan
    swarm am tersedia, gunakan ia untuk memperkukuh jawapan anda.
"""

    # ── Nama & emoji setiap agen ──────────────────────────────────────────────
    PAPARAN_AGEN = {
        "ETHICAL_COMPLIANCE_OFFICER": ("🕌 Pegawai Syariah",      "Semak had hutang 33% Syariah"),
        "CONSERVATIVE_PRESERVER":     ("🛡️ Pelindung Modal",       "Utamakan keselamatan & risiko rendah"),
        "VALUE_SNIPER":               ("🔍 Pemburu Nilai",         "Cari syarikat kukuh yang dipandang rendah"),
        "MOMENTUM_FOLLOWER":          ("📊 Pengikut Momentum",     "Ikut arah aliran pasaran semasa"),
        "AGGRESSIVE_SPECULATOR":      ("🚀 Spekulator Agresif",    "Kejar pulangan tinggi, toleransi risiko tinggi"),
        "TREND_AGENT":                ("📈 Analis Teknikal",       "Analisis pergerakan harga & corak carta"),
        "SENTIMENT_AGENT":            ("💬 Penganalisis Sentimen", "Nilai berita & media sosial"),
        "FUNDAMENTALS_AGENT":         ("📋 Analis Asas",           "Semak kesihatan kewangan & penilaian"),
    }

    PAPARAN_KEPUTUSAN = {
        "BUY":  "✅ BELI",
        "HOLD": "⏸️ TAHAN",
        "SELL": "📉 JUAL",
        "VETO": "🚫 VETO",
    }

    def _format_senarai_agen(self, senarai_agen: list) -> str:
        if not senarai_agen:
            return ""
        baris = ["\n🤖 *Suara Setiap Agen AI:*\n"]
        for agen in senarai_agen:
            id_agen    = agen.get("agent", "UNKNOWN")
            keputusan  = agen.get("decision", "HOLD").upper()
            keyakinan  = agen.get("confidence", 0)
            sebab      = agen.get("reasoning", "Tiada sebab diberikan.")
            nama_paparan, huraian_peranan = self.PAPARAN_AGEN.get(
                id_agen, (f"🤖 {id_agen}", "Agen AI")
            )
            label_keputusan = self.PAPARAN_KEPUTUSAN.get(keputusan, f"❓ {keputusan}")
            penuh = round(keyakinan / 20)
            bar   = "█" * penuh + "░" * (5 - penuh)
            baris.append(
                f"• {nama_paparan} ({huraian_peranan})\n"
                f"  → Keputusan: {label_keputusan}  |  Keyakinan: {bar} {keyakinan}%\n"
                f"  💬 \"{sebab}\"\n"
            )
        return "\n".join(baris)

    # ── FIX BUG 2: Fungsi baru untuk format ringkasan swarm am ───────────────
    def _format_ringkasan_swarm_am(self, konsensus: dict) -> str:
        """
        Bina ringkasan swarm yang boleh digunakan untuk soalan am
        (tiada ticker spesifik). Digunakan dalam Senario 1 yang diperbaiki.
        """
        if not konsensus:
            return ""

        senarai_agen  = konsensus.get("agent_breakdown", [])
        keyakinan     = konsensus.get("confidence", 0)
        sentimen      = konsensus.get("market_sentiment", "HOLD")
        minority_warn = konsensus.get("minority_warning", "")

        peta_sentimen = {
            "STRONGLY_BUY":  "Sangat Positif 📈",
            "BUY":           "Positif 📈",
            "HOLD":          "Neutral ⏸️",
            "SELL":          "Negatif 📉",
            "STRONGLY_SELL": "Sangat Negatif 📉",
        }
        sentimen_boleh_baca = peta_sentimen.get(sentimen, sentimen)
        teks_agen           = self._format_senarai_agen(senarai_agen)

        return f"""
--- PANDANGAN SWARM AI (KONTEKS AM) ---
- Sentimen Pasaran Am : {sentimen_boleh_baca}
- Keyakinan Swarm     : {keyakinan}%
- Amaran              : {minority_warn if minority_warn else "Tiada"}
{teks_agen}
"""

    def format_agent_input(
        self,
        input_pengguna:    str,
        kuantitatif:       dict,
        konteks_halaman:   str,
        konsensus_teratur: dict,
        blok_data_pasaran: str = "",
    ) -> str:

        tiada_ticker = (
            kuantitatif.get("reason") == "No specific stock analyzed."
        )

        # ── FIX BUG 2: Senario 1 diperbaiki ──────────────────────────────────
        # SEBELUM: terus balas tanpa sebarang konteks swarm
        # SELEPAS: semak sama ada ada konsensus swarm → sertakan jika ada
        if tiada_ticker:
            ringkasan_swarm = self._format_ringkasan_swarm_am(konsensus_teratur)

            if ringkasan_swarm:
                # Soalan am TETAPI swarm ada pandangan — sertakan dalam prompt
                return f"""
Pengguna (berada di halaman '{konteks_halaman}') berkata: "{input_pengguna}"

Ini adalah soalan am tentang kewangan atau pasaran Islam, bukan tentang saham spesifik.
{ringkasan_swarm}

ARAHAN CARA MENJAWAB:
1. Jawab soalan am pengguna berdasarkan pengetahuan kewangan dan Syariah anda.
2. Gunakan pandangan swarm di atas sebagai KONTEKS tambahan jika berkaitan.
3. Jika ada agen yang memberi pandangan relevan, sebut dengan ringkas.
4. Pastikan jawapan ringkas, mesra, dan mudah difahami dalam Bahasa Melayu!
"""
            else:
                # Sapaan biasa atau soalan am tanpa sebarang konteks swarm
                return f"""
Pengguna (berada di halaman '{konteks_halaman}') berkata: "{input_pengguna}"

Sila balas mesej ini mengikut ARAHAN SANGAT KETAT anda (Ringkas, Bahasa Melayu, Mesra).
"""

        # ── Senario 2: Ticker ditemui — analisis penuh ────────────────────────
        patuh_syariah  = kuantitatif.get("is_compliant", False)
        status_syariah = "✅ Patuh Syariah" if patuh_syariah else "🛑 TIDAK Patuh Syariah"
        konsensus      = konsensus_teratur.get("consensus",        "HOLD")    if konsensus_teratur else "HOLD"
        keyakinan      = konsensus_teratur.get("confidence",       50)        if konsensus_teratur else 50
        sentimen       = konsensus_teratur.get("market_sentiment", "Neutral") if konsensus_teratur else "Neutral"
        amaran_kecil   = konsensus_teratur.get("minority_warning", "")        if konsensus_teratur else ""

        peta_sentimen = {
            "STRONGLY_BUY":  "Sangat Positif 📈",
            "BUY":           "Positif 📈",
            "HOLD":          "Neutral ⏸️",
            "SELL":          "Negatif 📉",
            "STRONGLY_SELL": "Sangat Negatif 📉",
            "VETO":          "Diveto — Isu Syariah 🚫",
        }
        sentimen_boleh_baca  = peta_sentimen.get(sentimen, sentimen)
        konsensus_boleh_baca = self.PAPARAN_KEPUTUSAN.get(konsensus, konsensus)

        if keyakinan < 60:
            huraian_keyakinan = "Keyakinan rendah kerana agen-agen AI tidak bersetuju antara satu sama lain."
        elif keyakinan < 80:
            huraian_keyakinan = "Keyakinan sederhana — ada persetujuan tetapi beberapa agen berbeza pendapat."
        else:
            huraian_keyakinan = "Keyakinan tinggi — majoriti agen bersetuju dengan keputusan ini."

        senarai_agen      = konsensus_teratur.get("agent_breakdown", []) if konsensus_teratur else []
        teks_senarai_agen = self._format_senarai_agen(senarai_agen)

        amaran_syariah = ""
        if not patuh_syariah:
            amaran_syariah = f"""
⚠️ ARAHAN KHAS — SAHAM TIDAK HALAL:
Saham ini TIDAK patuh Syariah. Berikan analisis pasaran yang berguna,
TETAPI WAJIB tambahkan amaran berikut di hujung jawapan:
"⚠️ Peringatan Syariah: Saham ini TIDAK halal untuk dibeli kerana: {kuantitatif.get('reason', 'tidak patuh Syariah')}. Sila pertimbangkan alternatif yang patuh Syariah."
"""

        return f"""
Pengguna (berada di halaman '{konteks_halaman}') berkata: "{input_pengguna}"

--- DATA ANALISIS SISTEM ---
- Status Syariah  : {status_syariah}
- Sebab Syariah   : {kuantitatif.get("reason", "Tiada info")}
- Keputusan Swarm : {konsensus_boleh_baca}
- Keyakinan AI    : {keyakinan}% — {huraian_keyakinan}
- Sentimen Pasaran: {sentimen_boleh_baca}
- Amaran Minoriti : {amaran_kecil if amaran_kecil else "Tiada"}
{teks_senarai_agen}

--- DATA PASARAN TERKINI (REAL-TIME) ---
{blok_data_pasaran if blok_data_pasaran else "⚠️ Data pasaran terkini tidak tersedia."}

{amaran_syariah}

ARAHAN CARA MENJAWAB — IKUT FORMAT INI:
1. Ringkaskan keadaan saham ini dalam 1-2 ayat menggunakan DATA PASARAN TERKINI di atas.
2. Tunjukkan suara setiap agen AI secara mesra.
3. Terangkan MENGAPA keyakinan AI berada pada {keyakinan}%.
4. WAJIB sebut angka sebenar (harga, P/E, MA, sentimen) dari DATA PASARAN TERKINI — jangan kata "tiada data" jika data ada.
5. Berikan cadangan ringkas yang boleh diambil tindakan.
Pastikan jawapan ringkas, mesra, dan mudah difahami!
"""


# ══════════════════════════════════════════════════════════════════════════════
# FUNGSI PEMBANTU
# ══════════════════════════════════════════════════════════════════════════════

async def bina_dan_format_prompt(
    pengurus:          ShariahAdvisorPromptManager,
    ticker:            str,
    is_compliant:      bool,
    sebab_syariah:     str,
    input_pengguna:    str,
    konteks_halaman:   str,
    konsensus_teratur: dict,
) -> tuple[dict, str]:
    """
    Fungsi pembantu lengkap:
      1. Ambil data harga + asas + sentimen dari API
      2. Bina dict kuantitatif yang lengkap
      3. Format blok data pasaran untuk prompt
      4. Kembalikan (kuantitatif, prompt_lengkap)
    """
    kuantitatif = await bina_data_kuantitatif(ticker, is_compliant, sebab_syariah)
    blok_data   = format_data_untuk_prompt(kuantitatif)

    prompt = pengurus.format_agent_input(
        input_pengguna    = input_pengguna,
        kuantitatif       = kuantitatif,
        konteks_halaman   = konteks_halaman,
        konsensus_teratur = konsensus_teratur,
        blok_data_pasaran = blok_data,
    )

    return kuantitatif, prompt