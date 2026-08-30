# ai_agent.py  (Versi Diperbaiki)
#
# BUG DIPERBAIKI:
#   BUG 1 — Swarm dijalankan dengan "MARKET" + data kosong walaupun tiada ticker
#            → Penyelesaian: skip swarm terus jika tiada ticker
#   BUG 2 — Data harga & sentimen tidak dihantar ke swarm sebelum agen buat keputusan
#            → Penyelesaian: ambil data kuantitatif dulu, hantar ke execute_rehearsal

import os
import asyncio
import time
import requests
import re
from dotenv import load_dotenv
from prompt_engine import ShariahAdvisorPromptManager, bina_dan_format_prompt
from shariah_filter import shariahfilter
from mirofish_loop import SwarmSimulationEngine
from consensus_engine import calculate_swarm_consensus
from news_fetcher import bina_data_kuantitatif, format_data_untuk_prompt

load_dotenv()
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY")


def get_sentiment_data(ticker: str) -> dict:
    """
    Ambil skor sentimen sosial dari Finnhub.
    Mengembalikan buzz, news_score, social_score atau None jika gagal.
    """
    try:
        url  = f"https://finnhub.io/api/v1/stock/social-sentiment?symbol={ticker}&token={FINNHUB_KEY}"
        data = requests.get(url, timeout=5).json()

        reddit  = data.get("reddit",  [{}])
        twitter = data.get("twitter", [{}])

        reddit_score  = reddit[-1].get("score",  0.5) if reddit  else 0.5
        twitter_score = twitter[-1].get("score", 0.5) if twitter else 0.5
        avg_score     = round((reddit_score + twitter_score) / 2, 3)

        return {
            "buzz":         round(
                (reddit[-1].get("mention", 0) if reddit else 0) +
                (twitter[-1].get("mention", 0) if twitter else 0), 1
            ),
            "news_score":   avg_score,
            "social_score": avg_score,
        }
    except Exception as e:
        print(f"⚠️ Sentiment fetch gagal [{ticker}]: {e}")
        return None


class AIAgent:
    def __init__(self):
        groq_key       = os.getenv("GROQ_API_KEY")
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        gemini_key     = os.getenv("GEMINI_API_KEY")

        self.providers = []

        if groq_key:
            self.providers.append({
                "name":    "Groq",
                "url":     "https://api.groq.com/openai/v1/chat/completions",
                "headers": {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                "model":   "llama-3.3-70b-versatile",
            })

        if openrouter_key:
            self.providers.append({
                "name":    "Qwen (OpenRouter)",
                "url":     "https://openrouter.ai/api/v1/chat/completions",
                "headers": {"Authorization": f"Bearer {openrouter_key}", "Content-Type": "application/json"},
                "model":   "qwen/qwen-2.5-72b-instruct",
            })

        if gemini_key:
            self.providers.append({
                "name":    "Gemini 2.5 Flash",
                "url":     "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                "headers": {"Authorization": f"Bearer {gemini_key}", "Content-Type": "application/json"},
                "model":   "gemini-2.5-flash",
            })

        if not self.providers:
            print("🚨 AMARAN: Tiada kunci API dijumpai dalam .env!")

        self._consensus_history: dict = {}
        self.prompt_engine  = ShariahAdvisorPromptManager()
        self.shariah        = shariahfilter()
        self.swarm_engine   = SwarmSimulationEngine()

    def process(
        self,
        user_input:         str,
        ticker:             str  = None,
        chat_history:       list = None,
        page_context:       str  = "Unknown",
        preferences:        dict = None,
        previous_consensus: dict = None,
        user_goal:          dict = None,
    ):
        # ── Auto-detect ticker ────────────────────────────────────────────────
        if not ticker:
            match = re.search(r'\b([A-Z0-9]+\.KL)\b', user_input.upper())
            if not match:
                match = re.search(r'\b([A-Z0-9]+\.KL)\b', page_context.upper())
            if match:
                ticker = match.group(1)
                print(f"🔍 Ticker dikesan: {ticker}")

        if previous_consensus is None and ticker:
            previous_consensus = self._consensus_history.get(ticker)

        system_prompt = self.prompt_engine.get_system_prompt(preferences)

        # ── Semakan Syariah ───────────────────────────────────────────────────
        is_compliant = False
        reason       = "No specific stock analyzed."
        cash_ratio   = 15.0
        debt_ratio   = 20.0

        if ticker:
            compliance_data = self.shariah.check_compliance(ticker)
            is_compliant    = compliance_data.get("isHalal", False)
            reason          = compliance_data.get("reason", "Unknown")
            cash_ratio      = compliance_data.get("cash_ratio", 15.0)
            debt_ratio      = compliance_data.get("debt_ratio", 20.0)

        # ── FIX BUG 1 & 2: Swarm hanya dijalankan jika ada ticker ────────────
        # Sebelum fix: swarm dijalankan dengan "MARKET" + data kosong walaupun
        #              tiada ticker → agen sentiasa kata "data unavailable"
        # Selepas fix: jika tiada ticker, skip swarm terus → jimat masa & token
        #              jika ada ticker, ambil data kuantitatif DULU, baru swarm

        structured_consensus = None  # ← nilai lalai untuk soalan am
        kuantitatif          = {
            "is_compliant": is_compliant,
            "reason":       reason,
            "cash_ratio":   cash_ratio,
            "debt_ratio":   debt_ratio,
        }
        blok_data_pasaran = ""

        if ticker:
            # LANGKAH 1: Ambil data harga + asas + sentimen sebelum swarm berjalan
            # (ini menyelesaikan masalah "data unavailable" dalam agen)
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    kuantitatif = loop.run_until_complete(
                        bina_data_kuantitatif(ticker, is_compliant, reason)
                    )
                finally:
                    loop.close()

                blok_data_pasaran = format_data_untuk_prompt(kuantitatif)
                print(f"✅ Data kuantitatif berjaya diambil untuk {ticker}")

            except Exception as e:
                print(f"⚠️ Gagal ambil data kuantitatif: {e}")
                # Fallback ke dict asas jika gagal
                kuantitatif = {
                    "is_compliant": is_compliant,
                    "reason":       reason,
                    "cash_ratio":   cash_ratio,
                    "debt_ratio":   debt_ratio,
                }

            # LANGKAH 2: Ambil data tambahan dari Finnhub untuk swarm
            quote_data = {
                "price": kuantitatif.get("harga_semasa"),
                "changePercent": kuantitatif.get("perubahan_harga_pct"),
                "high": kuantitatif.get("tinggi_52_minggu"),
                "low": kuantitatif.get("rendah_52_minggu"),
                "previousClose": None 
            } if kuantitatif.get("data_harga_tersedia") else None

            fundamentals = {
                "peRatio": kuantitatif.get("nisbah_pe"),
                "marketCap": kuantitatif.get("permodalan_pasaran"),
                "netProfitMargin": kuantitatif.get("margin_keuntungan"),
                "debtToEquity": (kuantitatif.get("nisbah_hutang") * 100) if kuantitatif.get("nisbah_hutang") else None
            } if kuantitatif.get("data_harga_tersedia") else None

            sentiment = {
                "buzz": kuantitatif.get("bilangan_artikel_berita"),
                "news_score": kuantitatif.get("skor_sentimen"),
                "social_score": kuantitatif.get("skor_sentimen")
            } if kuantitatif.get("data_sentimen_tersedia") else None

            # LANGKAH 3: Jalankan swarm dengan data yang telah dipetakan
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    raw_swarm_results = loop.run_until_complete(
                        self.swarm_engine.execute_rehearsal(
                            ticker       = ticker,
                            audit_data   = kuantitatif,
                            user_goal    = user_goal,
                            quote_data   = quote_data,       
                            fundamentals = fundamentals,     
                            sentiment    = sentiment,        
                        )
                    )
                finally:
                    loop.close()

                structured_consensus = calculate_swarm_consensus(
                    raw_swarm_results,
                    previous_consensus=previous_consensus,
                )
                print(
                    f"📊 Konsensus Swarm: {structured_consensus['consensus']} "
                    f"pada {structured_consensus['confidence']}%"
                )
                self._consensus_history[ticker] = structured_consensus

            except Exception as e:
                print(f"⚠️ Swarm gagal: {e}")
                structured_consensus = None

        else:
            # Tiada ticker → soalan am → skip swarm sepenuhnya
            print("ℹ️ Tiada ticker dikesan — swarm diskip, balas soalan am.")

        # ── Bina prompt ───────────────────────────────────────────────────────
        prompt_content = self.prompt_engine.format_agent_input(
            input_pengguna    = user_input,
            kuantitatif       = kuantitatif,
            konteks_halaman   = page_context,
            konsensus_teratur = structured_consensus,
            blok_data_pasaran = blok_data_pasaran,
        )

        return self.build_final_response(
            system_prompt,
            prompt_content,
            chat_history,
            kuantitatif,
        )

    def build_final_response(self, system_prompt, prompt_content, chat_history, shariah_result):
        messages = [{"role": "system", "content": system_prompt}]

        if chat_history:
            for msg in chat_history[-6:]:
                role = "assistant" if msg["role"] in ["ai", "assistant"] else "user"
                messages.append({"role": role, "content": msg["content"]})

        messages.append({"role": "user", "content": prompt_content})

        errors = []

        for provider in self.providers:
            try:
                print(f"🌐 [AIAgent] Menghantar ke: {provider['name']}...")

                payload = {
                    "model":       provider["model"],
                    "messages":    messages,
                    "temperature": 0.2,
                }

                response = requests.post(
                    provider["url"],
                    headers=provider["headers"],
                    json=payload,
                    timeout=20,
                )
                response.raise_for_status()

                data = response.json()
                
                # Gunakan .get() untuk elak crash jika 'content' tiada akibat filter keselamatan
                message_data = data.get("choices", [{}])[0].get("message", {})
                final_advice = message_data.get("content")

                if not final_advice:
                    raise ValueError("Content blocked or missing in response (likely AI safety filter).")

                print(f"✅ [AIAgent] Berjaya melalui {provider['name']}")

                return {
                    "status":       "SUCCESS",
                    "final_advice": final_advice,
                    "raw_data":     {"shariah_status": shariah_result},
                }

            except Exception as e:
                err_msg = f"{provider['name']} gagal: {str(e)}"
                print(f"❌ [AIAgent] {err_msg}")
                errors.append(err_msg)
                time.sleep(1)

        return {
            "status":        "ERROR",
            "final_advice":  "Saya sedang mengalami gangguan rangkaian. Sila cuba sebentar lagi.",
            "error_details": errors,
        }