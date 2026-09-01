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
from datetime import datetime, timezone
from dotenv import load_dotenv
from prompt_engine import ShariahAdvisorPromptManager, bina_dan_format_prompt
from shariah_filter import shariahfilter
from mirofish_loop import SwarmSimulationEngine
from consensus_engine import calculate_swarm_consensus
from news_fetcher import bina_data_kuantitatif, format_data_untuk_prompt
from Risk_sizing import calculate_position_size
from thetanuts_trader import ThetanutsTrader

try:
    from firebase_config import db
except Exception:
    db = None  # trade history logging becomes a no-op if Firestore isn't configured

trader = ThetanutsTrader()

# ── Global execution kill-switch ─────────────────────────────────────────
# The wallet isn't funded yet. Until it is, every fill this backend ever
# sends — regardless of riskCopilotMode, confidence, or which code path
# triggers it (auto-execute here in ai_agent.py, or the confirm-trade
# endpoint in ai_routes.py) — goes out with dry_run=True. This is checked
# in addition to, not instead of, the riskCopilotMode gating below: it's a
# blanket safety net, not a substitute for per-mode confirmation logic.
# Flip to False once the wallet is funded and you're ready for live fills.
FORCE_DRY_RUN = True


def _log_thetanuts_trade(record: dict) -> None:
    """
    Appends one execution attempt (successful, failed, dry-run, or skipped)
    to Firestore, grouped by calendar date so trade history reads back
    naturally as "what happened on this day".

    Path: thetanuts_trades / {YYYY-MM-DD} / entries / {auto-id}

    Never raises — a logging failure should never take down a trade
    response to the user, so this swallows and prints instead.
    """
    if db is None:
        print("⚠️ [TradeHistory] Firestore not configured — trade not persisted.")
        return
    try:
        now = datetime.now(timezone.utc)
        date_key = now.strftime("%Y-%m-%d")
        (
            db.collection("thetanuts_trades")
              .document(date_key)
              .collection("entries")
              .add({**record, "date": date_key, "logged_at": now.isoformat()})
        )
    except Exception as e:
        print(f"⚠️ [TradeHistory] Failed to log trade: {e}")

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
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
                "model":   "qwen/qwen-2.5-72b-instruct:free",
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
        portfolio:          dict = None,
    ):
        # ── Auto-detect underlying (ETH/BTC) ─────────────────────────────────
        # Thetanuts only trades options on ETH/BTC — this used to detect
        # Bursa Malaysia stock tickers (the ".KL" suffix from the old
        # Shariah-stocks app), which meant the swarm reasoned about a stock
        # while execution filled whatever order happened to be first on a
        # completely unrelated OptionBook. `ticker` below is now always
        # "ETH", "BTC", or None — the one asset space the swarm, the
        # Firestore consensus log, and the actual on-chain fill all share.
        if not ticker:
            text = f"{user_input} {page_context}".upper()
            if re.search(r'\bBTC\b|\bBITCOIN\b', text):
                ticker = "BTC"
            elif re.search(r'\bETH\b|\bETHEREUM\b|\bETHER\b', text):
                ticker = "ETH"
            if ticker:
                print(f"🔍 Underlying detected: {ticker}")

        if previous_consensus is None and ticker:
            previous_consensus = self._consensus_history.get(ticker)

        # ── Read the REAL on-chain wallet balance up front ─────────────────
        # This is the actual spendable capital on Base mainnet — separate
        # from any Firestore `portfolio` bookkeeping, which is legacy from
        # the earlier stock-trading version and no longer represents real
        # funds. The system prompt gets this so the AI never reasons about
        # sizing without knowing what's actually available.
        wallet_balance = trader.get_wallet_balance()
        if not wallet_balance["ok"]:
            print(f"⚠️ [Wallet] Could not read live balance: {wallet_balance['error']}")

        system_prompt = self.prompt_engine.get_system_prompt(preferences, wallet_balance=wallet_balance)

        # ── Semakan Syariah ───────────────────────────────────────────────────
        # check_compliance() reads equity debt/cash-ratio filings — meaningless
        # for ETH/BTC, so it's skipped for the crypto underlyings this agent
        # now trades. If Shariah screening of the crypto asset itself matters
        # for your pitch, that needs separate logic — this just avoids running
        # a stock-specific check against a ticker it was never built for.
        is_compliant = False
        reason       = "No specific stock analyzed."
        cash_ratio   = 15.0
        debt_ratio   = 20.0

        if ticker in ("ETH", "BTC"):
            is_compliant = True
            reason       = "Crypto underlying — equity Shariah debt/cash-ratio check not applicable."
        elif ticker:
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
        trade_proposal       = None
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
                # yfinance/Finnhub want "ETH-USD"/"BTC-USD", not the bare
                # "ETH"/"BTC" the Thetanuts CLI takes — `ticker` stays bare
                # everywhere else (Thetanuts calls, Firestore logs, swarm
                # labeling); this is purely the symbol used for the market
                # data lookup. UNVERIFIED: confirm bina_data_kuantitatif()
                # (in news_fetcher.py, not reviewed here) actually resolves
                # this format the same way it resolves stock tickers.
                market_symbol = f"{ticker}-USD" if ticker in ("ETH", "BTC") else ticker
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    kuantitatif = loop.run_until_complete(
                        bina_data_kuantitatif(market_symbol, is_compliant, reason)
                    )
                finally:
                    loop.close()

                blok_data_pasaran = format_data_untuk_prompt(kuantitatif)
                print(f"✅ Quantitative data successfully retrieved for {ticker}")

            except Exception as e:
                print(f"⚠️ Failed to retrieve quantitative data: {e}")
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
                    f"📊 Swarm Consensus: {structured_consensus['consensus']} "
                    f"at {structured_consensus['confidence']}%"
                )
                self._consensus_history[ticker] = structured_consensus

                # ── START: WALLET-AWARE SIZING & THETANUTS ON-CHAIN EXECUTION ──────
                consensus_action = structured_consensus.get("consensus", "").upper()
                confidence = structured_consensus.get("confidence", 0)
                prefs = preferences or {}
                risk_tolerance = prefs.get("riskTolerance", "Moderate")

                # Premium budget as a % of TRADABLE (real, live) USDC — tiered by
                # risk tolerance. This replaces the old share-based sizing, which
                # assumed a stock portfolio value that no longer exists; on
                # Thetanuts, max loss is capped at the premium paid, so sizing is
                # simply "how much of the wallet's live USDC to put on this trade".
                RISK_PCT_BY_TOLERANCE = {"Low (Conservative)": 0.10, "Moderate": 0.20, "High (Aggressive)": 0.35}
                risk_pct = RISK_PCT_BY_TOLERANCE.get(risk_tolerance, 0.20)

                tradable_usdc = wallet_balance.get("tradable_usdc", 0.0)
                proposed_amount = round(tradable_usdc * risk_pct, 4)

                # riskCopilotMode governs whether ANY on-chain action is
                # taken here without a separate, explicit user confirmation.
                # Only "Fully automated recommendations" is allowed to reach
                # execute_fill(dry_run=False) from this code path — every
                # other mode either stays purely informational or stops at
                # a preview that /confirm-trade must be called to complete.
                copilot_mode = prefs.get("riskCopilotMode", "Suggest actions, I confirm each one")

                trade_proposal = {
                    "action": consensus_action,
                    "ticker": ticker,
                    "confidence": confidence,
                    "risk_tolerance": risk_tolerance,
                    "risk_copilot_mode": copilot_mode,
                    "wallet_tradable_usdc": tradable_usdc,
                    "proposed_amount_usdc": proposed_amount,
                }

                execution_record = None

                if consensus_action in ["BUY", "SELL"] and confidence >= 50:

                    # ── Mode 1: Alert me only, I act manually ───────────────
                    # No CLI call at all — not even a dry-run preview. The
                    # user asked to be told, not shown a simulated fill.
                    if copilot_mode == "Alert me only, I act manually":
                        print(f"🔔 [Thetanuts] Alert-only mode — surfacing {consensus_action} {ticker} without previewing or filling.")
                        trade_proposal["thetanuts_execution"] = {
                            "status": "ALERT_ONLY",
                            "reason": "Risk Copilot is set to alert-only — no order was previewed or sent. Trade manually on Thetanuts if you agree with this signal.",
                        }
                        execution_record = {
                            "ticker": ticker, "action": consensus_action, "confidence": confidence,
                            "status": "ALERT_ONLY", "amount_usdc": 0,
                            "order_index": None, "tx_hash": None,
                            "wallet_tradable_usdc": tradable_usdc, "dry_run": True,
                        }

                    elif not wallet_balance.get("ok") or tradable_usdc < 0.5:
                        # No point calling the CLI at all — we already know it'll fail.
                        print(f"⏭️ [Thetanuts] Skipping execution — wallet balance unavailable or below 0.5 USDC (have {tradable_usdc}).")
                        trade_proposal["thetanuts_execution"] = {
                            "status": "SKIPPED_INSUFFICIENT_FUNDS",
                            "tradable_usdc": tradable_usdc,
                        }
                        execution_record = {
                            "ticker": ticker, "action": consensus_action, "confidence": confidence,
                            "status": "SKIPPED_INSUFFICIENT_FUNDS", "amount_usdc": 0,
                            "order_index": None, "tx_hash": None,
                            "wallet_tradable_usdc": tradable_usdc, "dry_run": False,
                        }

                    else:
                        print(f"🚀 [Thetanuts] {copilot_mode} — resolving book for {consensus_action} {ticker} at {proposed_amount} USDC...")
                        # Filtered to `ticker` — previously this fetched the
                        # WHOLE book and took index [0] regardless of asset,
                        # so a BUY/SELL decided about one underlying could
                        # fill a completely unrelated order. Only ETH/BTC
                        # orders for the asset the swarm just analyzed come
                        # back here.
                        orders = trader.get_live_orders(underlying=ticker)

                        if orders.get("ok") and isinstance(orders.get("data"), list) and len(orders["data"]) > 0:
                            target_order = orders["data"][0]

                            # Prefer the explicit selector (pins the exact
                            # contract) over --order-index (position-based,
                            # only correct if it resolves against the same
                            # filtered list — unverified against a live
                            # response). Field names below are a best guess
                            # from the CLI's own flag names — confirm with
                            # one real `book orders --underlying ETH -o json`
                            # dry run and adjust if they don't match.
                            order_type   = target_order.get("type") or target_order.get("optionType")
                            order_strike = target_order.get("strike")
                            order_expiry = target_order.get("expiry") or target_order.get("expiryTimestamp")
                            order_price  = target_order.get("price") or target_order.get("premium")
                            has_schema   = order_type and order_strike is not None and order_expiry

                            # ── Mode 2: Suggest actions, I confirm each one ──
                            # Preview only (always dry_run=True — this mode
                            # must NEVER fill on its own). Hand back the exact
                            # selector so the frontend can send it to
                            # /confirm-trade, which re-checks the book fresh
                            # at confirmation time before ever filling for
                            # real.
                            if copilot_mode == "Suggest actions, I confirm each one":
                                if has_schema:
                                    preview_result = trader.execute_fill(
                                        collateral_usdc=proposed_amount,
                                        underlying=ticker,
                                        option_type=order_type,
                                        strike=order_strike,
                                        expiry=order_expiry,
                                        dry_run=True,
                                    )
                                else:
                                    print("⚠️ [Thetanuts] Order fields didn't match expected schema — previewing with --order-index 0 (unverified).")
                                    preview_result = trader.execute_fill(
                                        collateral_usdc=proposed_amount,
                                        order_index=0,
                                        dry_run=True,
                                    )

                                trade_proposal["thetanuts_execution"] = {
                                    "status": "PENDING_CONFIRMATION",
                                    "preview": preview_result,
                                }
                                # Everything /confirm-trade needs to re-fetch
                                # the book and refill this exact contract —
                                # never the stale preview_result itself.
                                trade_proposal["confirm_selector"] = {
                                    "underlying": ticker,
                                    "option_type": order_type,
                                    "strike": order_strike,
                                    "expiry": order_expiry,
                                    "collateral_usdc": proposed_amount,
                                    "previewed_price": order_price,
                                }
                                execution_record = {
                                    "ticker": ticker, "action": consensus_action, "confidence": confidence,
                                    "status": "PENDING_CONFIRMATION", "amount_usdc": proposed_amount,
                                    "order_index": None, "tx_hash": None,
                                    "wallet_tradable_usdc": tradable_usdc, "dry_run": True,
                                }
                                print(f"⏸️ [Thetanuts] Preview only — waiting on user confirmation via /confirm-trade.")

                            # ── Mode 3: Fully automated recommendations ──────
                            # The only mode allowed to reach a real fill from
                            # this code path. Still forced through dry_run
                            # while FORCE_DRY_RUN is True (wallet unfunded).
                            else:
                                effective_dry_run = FORCE_DRY_RUN
                                if effective_dry_run:
                                    print("🧪 [Thetanuts] FORCE_DRY_RUN is on — running as a dry-run even in fully-automated mode.")

                                if has_schema:
                                    execution_result = trader.execute_fill(
                                        collateral_usdc=proposed_amount,
                                        underlying=ticker,
                                        option_type=order_type,
                                        strike=order_strike,
                                        expiry=order_expiry,
                                        dry_run=effective_dry_run,
                                    )
                                else:
                                    print("⚠️ [Thetanuts] Order fields didn't match expected schema — falling back to --order-index 0 (unverified).")
                                    execution_result = trader.execute_fill(
                                        collateral_usdc=proposed_amount,
                                        order_index=0,
                                        dry_run=effective_dry_run,
                                    )

                                trade_proposal["thetanuts_execution"] = execution_result
                                execution_record = {
                                    "ticker": ticker, "action": consensus_action, "confidence": confidence,
                                    "status": execution_result["status"], "amount_usdc": proposed_amount,
                                    "order_index": execution_result.get("order_index"), "tx_hash": execution_result["tx_hash"],
                                    "wallet_tradable_usdc": tradable_usdc, "dry_run": effective_dry_run,
                                    "error": execution_result["error"],
                                }
                                if execution_result["ok"]:
                                    print(f"✅ [Thetanuts] {'Dry-run' if effective_dry_run else 'Live'} trade result: {execution_result}")
                                else:
                                    print(f"❌ [Thetanuts] Trade failed: {execution_result['error']}")
                        else:
                            print("⚠️ [Thetanuts] No active orders available on OptionBook to fill.")
                            trade_proposal["thetanuts_execution"] = {
                                "status": "FAILED",
                                "reason": orders.get("error") or "No active orders on OptionBook",
                            }
                            execution_record = {
                                "ticker": ticker, "action": consensus_action, "confidence": confidence,
                                "status": "FAILED", "amount_usdc": 0, "order_index": None, "tx_hash": None,
                                "wallet_tradable_usdc": tradable_usdc, "dry_run": True,
                                "error": orders.get("error") or "No active orders on OptionBook",
                            }

                # Every attempt gets logged — success, failure, or skip — so the
                # history is a complete record, not just a highlight reel.
                if execution_record is not None:
                    _log_thetanuts_trade(execution_record)
                # ── END: WALLET-AWARE SIZING & EXECUTION ────────────────────────

            except Exception as e:
                print(f"⚠️ AI Swarm failed: {e}")
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
            trade_proposal
        )

    def build_final_response(self, system_prompt, prompt_content, chat_history, shariah_result, trade_proposal):
        messages = [{"role": "system", "content": system_prompt}]

        if chat_history:
            for msg in chat_history[-6:]:
                role = "assistant" if msg["role"] in ["ai", "assistant"] else "user"
                messages.append({"role": role, "content": msg["content"]})

        messages.append({"role": "user", "content": prompt_content})

        errors = []

        for provider in self.providers:
            try:
                print(f"🌐 [AIAgent] Send to: {provider['name']}...")

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

                print(f"✅ [AIAgent] Successfully passed through {provider['name']}")

                return {
                    "status":       "SUCCESS",
                    "final_advice": final_advice,
                    "raw_data":     {"shariah_status": shariah_result},
                    "trade_proposal": trade_proposal
                }

            except Exception as e:
                err_msg = f"{provider['name']} failed: {str(e)}"
                print(f"❌ [AIAgent] {err_msg}")
                errors.append(err_msg)
                time.sleep(1)

        return {
            "status":        "ERROR",
            "final_advice":  "Saya sedang mengalami gangguan rangkaian. Sila cuba sebentar lagi.",
            "error_details": errors,
        }