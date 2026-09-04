# ai_agent.py  (Versi Diperbaiki)
#
# BUG DIPERBAIKI:
#   BUG 1 — Swarm dijalankan dengan "MARKET" + data kosong walaupun tiada ticker
#            → Penyelesaian: skip swarm terus jika tiada ticker
#   BUG 2 - Price and sentiment data were not sent to the swarm before agent decisions.
#            → Penyelesaian: ambil data kuantitatif dulu, hantar ke execute_rehearsal

import os
import asyncio
import time
import requests
import re
from datetime import datetime, timezone
from dotenv import load_dotenv
from prompt_engine import TradingAdvisorPromptManager
from agents.orchestrator import SwarmOrchestrator as SwarmSimulationEngine
from services.asset_resolver import resolve_asset_from_query
from thetanuts_trader import ThetanutsTrader

try:
    from firebase_config import db
except Exception:
    db = None

# Must run BEFORE ThetanutsTrader() is constructed below — its __init__
# reads WALLET_PRIVATE_KEY / BASE_RPC_URL from os.environ immediately, so
# if .env hasn't been loaded yet at that point, the wallet silently fails
# to initialize (self.w3/self.account stay None for the process lifetime)
# even when the .env file itself is correct.
load_dotenv()

trader = ThetanutsTrader()

# Real trades require FORCE_DRY_RUN=false in the environment — defaults to
# True (dry-run) so a missing/misconfigured env var fails safe rather than
# silently trading live.
FORCE_DRY_RUN = os.getenv("FORCE_DRY_RUN", "true").strip().lower() != "false"

def _log_thetanuts_trade(record: dict) -> None:
    if db is None:
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
    Fetch social sentiment score from Finnhub.
    Returns buzz, news_score, social_score, or None if fetching fails.
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
        print(f"⚠️ Sentiment fetch failed [{ticker}]: {e}")
        return None


from advisor.trade_bridge import build_trade_proposal

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
                "model":   "qwen/qwen3.6-27b",
            })

        if openrouter_key:
            self.providers.append({
                "name":    "OpenRouter (Llama 3.1)",
                "url":     "https://openrouter.ai/api/v1/chat/completions",
                "headers": {"Authorization": f"Bearer {openrouter_key}", "Content-Type": "application/json"},
                "model":   "meta-llama/llama-3.1-8b-instruct",
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
        self.prompt_engine  = TradingAdvisorPromptManager()
        self.swarm_engine   = SwarmSimulationEngine()

    def process(
        self,
        user_input: str,
        ticker: str = None,
        chat_history: list = None,
        page_context: str = "Unknown",
        preferences: dict = None,
        previous_consensus: dict = None,
        user_goal: dict = None,
        portfolio: dict = None,
    ):
        # ── 1. INTELLIGENT ASSET RESOLUTION ──────────────────────────────────
        # Resolves queries with typos (e.g. "NASDAS 100"), aliases ("NDX", "US100", "Gold"),
        # Bursa codes ("1155.KL"), or US tickers ("AAPL") into canonical asset info.
        resolved_asset = resolve_asset_from_query(user_input, page_context)
        if not resolved_asset and ticker:
            resolved_asset = resolve_asset_from_query(ticker, page_context)

        # ── 2. IF ASSET RESOLVED -> TRIGGER MULTI-AGENT INVESTMENT INTELLIGENCE ──
        if resolved_asset:
            sym = resolved_asset["symbol"]
            canonical_name = resolved_asset["canonical_name"]
        
            print(
                f"🎯 [AIAgent] Asset resolved: '{user_input}' -> "
                f"{canonical_name} ({sym}). Triggering 5-Agent Intelligence..."
            )
        
            try:
                # Run the full 5-agent pipeline
                investment_analysis = self.swarm_engine.analyze_stock_sync(
                    sym,
                    user_question=user_input
                )
        
                # ── CANONICAL CURRENT PRICE ─────────────────────────────────
                # Price comes from the same canonical market snapshot used by
                # the investment-analysis pipeline.
                spot_price = investment_analysis.get("current_price")
        
                try:
                    spot_price = float(spot_price)
                except (TypeError, ValueError):
                    spot_price = None
        
                print(
                    f"💰 [AIAgent] Current spot price for {sym}: {spot_price}"
                )
        
                # ── EXPLICIT USER BUY ───────────────────────────────────────
                # Local testing: explicit "buy ..." overrides committee decision.
                
        
                # AI's independent recommendation
                ai_decision = investment_analysis.get("decision", "HOLD")

                # User's explicit trading intent
                user_text = (user_input or "").strip().lower()
                explicit_action = None

                if re.search(r"\b(buy|purchase)\b", user_text):
                    explicit_action = "BUY"
                elif re.search(r"\b(sell|dispose)\b", user_text):
                    explicit_action = "SELL"

                # User's explicit BUY/SELL command controls the trade direction.
                # AI recommendation is advisory only.
                trade_decision = explicit_action or ai_decision

                print(
                    f"🎯 [AIAgent] User intent: {explicit_action or 'NONE'} | "
                    f"AI assessment: {ai_decision} | "
                    f"Trade decision: {trade_decision}"
                )
                conf_pct = int(
                    investment_analysis.get("confidence", 0.5) * 100
                )
                risk_lvl = investment_analysis.get("risk_level", "MEDIUM")
                summary = investment_analysis.get("summary", "")
                bulls = investment_analysis.get("bull_case", [])
                bears = investment_analysis.get("bear_case", [])
        
                summary_md = (
                    f"### 📊 Investment Assessment: "
                    f"{canonical_name} ({sym})\n\n"
                )
        
                if explicit_action:
                    summary_md += (
                        f"**Your Requested Action:** `{explicit_action}`\n\n"
                        f"**AI Assessment:** `{ai_decision}` "
                        f"(Evidence Conviction: **{conf_pct}%**) · "
                        f"Risk Level: **{risk_lvl}**\n\n"
                    )
                else:
                    summary_md += (
                        f"**Committee Decision:** `{ai_decision}` "
                        f"(Evidence Conviction: **{conf_pct}%**) · "
                        f"Risk Level: **{risk_lvl}**\n\n"
                    )
        
                summary_md += f"{summary}\n\n"
        
                if bulls:
                    summary_md += f"**Key Catalyst:** {bulls[0]}\n"
        
                if bears:
                    summary_md += f"**Primary Concern:** {bears[0]}\n\n"
        
                summary_md += (
                    "_Explore the full multi-agent breakdown, bull/bear cases, "
                    "chart, and invalidation triggers in the research card below._"
                )
        
                # ── Build trade proposal ────────────────────────────────────
                trade_result = build_trade_proposal(
                    symbol=sym,
                    decision=trade_decision,
                    investment_analysis=investment_analysis,
                    preferences=preferences or {},
                    portfolio=portfolio or {},
                    trader=trader,
                    spot_price=spot_price,
                    explicit_user_action=explicit_action,
                )
        
                # Append trade status
                if trade_result["status"] == "EXECUTABLE":
                    prop = trade_result["proposal"]
        
                    summary_md += (
                        f"\n\n---\n"
                        f"🔗 **Live Thetanuts Contract Found** · "
                        f"{prop['option_type']} Strike: `{prop['strike']}` · "
                        f"Collateral: `{prop['collateral_usdc']} USDC`"
                    )
        
                elif trade_decision in ("BUY", "SELL"):
                    summary_md += (
                        f"\n\n---\n"
                        f"⚠️ **Trade Note:** {trade_result['reason']}"
                    )
        
                return {
                    "status": "SUCCESS",
                    "response_type": "investment_intelligence",
                    "final_advice": summary_md,
                    "investment_analysis": investment_analysis,
                    "trade_proposal": trade_result.get("proposal"),
                    "trade_status": trade_result["status"],
                    "trade_reason": trade_result["reason"],
                }
        
            except Exception as e:
                print(
                    f"⚠️ [AIAgent] Multi-Agent Pipeline error for {sym}: {e}"
                )

        # ── 3. GENERAL CONVERSATION / GENERAL FINANCE QUESTION ────────────────
        print(f"ℹ️ [AIAgent] General financial inquiry. Generating conversational guidance...")

        # Was previously hardcoded to {"ok": False}, which told the LLM to
        # "treat as zero funds, do not recommend execution" regardless of
        # the wallet's actual on-chain balance — matching wallet_routes.py
        # here so the chat sees the same live numbers the wallet pill does.
        try:
            live_wallet_balance = trader.get_wallet_balance()
        except Exception as e:
            print(f"⚠️ [AIAgent] Failed to fetch live wallet balance: {e}")
            live_wallet_balance = {"ok": False, "eth": 0.0, "usdc": 0.0, "tradable_usdc": 0.0}

        system_prompt = self.prompt_engine.get_system_prompt(
            preferences,
            portfolio=portfolio or {},
            wallet_balance=live_wallet_balance,
        )
        prompt_content = f"User Question: {user_input}\nContext: {page_context}\nPlease provide a helpful, professional, and structured financial response."

        return self.build_final_response(
            system_prompt,
            prompt_content,
            chat_history,
            trade_proposal=None,
        )

    def build_final_response(self, system_prompt, prompt_content, chat_history, trade_proposal, investment_analysis=None):
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
                    "max_tokens":  1200, 
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

                # Strip <think>...</think> reasoning blocks emitted by Qwen3/DeepSeek
                # thinking models — users should only see the final answer.
                import re as _re
                # Strip <think>...</think> reasoning blocks (Qwen3 / DeepSeek thinking models).
                # Pass 1: remove any complete <think>...</think> sections (DOTALL = across newlines)
                final_advice = _re.sub(r"<think>.*?</think>", "", final_advice, flags=_re.DOTALL)
                # Pass 2: remove any unclosed leading <think> block (model may not close it before answer)
                final_advice = _re.sub(r"<think>.*$", "", final_advice, flags=_re.DOTALL)
                # Pass 3: remove stray </think> tags left behind
                final_advice = final_advice.replace("</think>", "").strip()

                if not final_advice:
                    raise ValueError("Model returned only a thinking block with no final answer.")

                print(f"✅ [AIAgent] Successfully passed through {provider['name']}")

                return {
                    "status":              "SUCCESS",
                    "final_advice":        final_advice,
                    "trade_proposal":      trade_proposal,
                    "investment_analysis": investment_analysis,
                }

            except Exception as e:
                err_msg = f"{provider['name']} failed: {str(e)}"
                print(f"❌ [AIAgent] {err_msg}")
                errors.append(err_msg)
                time.sleep(1)

        return {
            "status":        "ERROR",
            "final_advice":  "I am experiencing a network issue. Please try again shortly.",
            "error_details": errors,
        }
