import os
import json
import asyncio
import aiohttp
from dotenv import load_dotenv

load_dotenv()


class SwarmSimulationEngine:
    def __init__(self):
        self.groq_key = os.getenv("GROQ_API_KEY")
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY")
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        
        # Decide which API to use for the Swarm
        if self.groq_key:
            self.api_key = self.groq_key
            self.api_url = "https://api.groq.com/openai/v1/chat/completions"
            self.model = "llama-3.3-70b-versatile"
        elif self.openrouter_key:
            self.api_key = self.openrouter_key
            self.api_url = "https://openrouter.ai/api/v1/chat/completions"
            self.model = "xai/grok-2-1212"
        elif self.gemini_key:
            self.api_key = self.gemini_key
            self.api_url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
            self.model = "gemini-2.5-flash"
        else:
            print("🚨 CRITICAL: No API keys found for Swarm Engine!")

        self.personas = [
            # ── ORIGINAL 5 ──────────────────────────────────────────────────
            {
                "id":          "ETHICAL_COMPLIANCE_OFFICER",
                "prompt":      "You are a strict Shariah compliance officer. Your ONLY concern is whether the debt ratio exceeds the 33% haram threshold. If it does, you must VETO. Analyze the data and output ONLY valid JSON.",
                "temperature": 0.1,
                "weight":      1.0,
            },
            {
                "id":          "CONSERVATIVE_PRESERVER",
                "prompt":      "You are a conservative wealth preserver. Priority is zero risk and capital protection. High debt terrifies you. Output ONLY valid JSON.",
                "temperature": 0.2,
                "weight":      0.8,
            },
            {
                "id":          "VALUE_SNIPER",
                "prompt":      "You look for fundamentally strong companies ignored by the market. You accept moderate debt if intrinsic value is high. Output ONLY valid JSON.",
                "temperature": 0.3,
                "weight":      0.7,
            },
            {
                "id":          "MOMENTUM_FOLLOWER",
                "prompt":      "You follow market trends and crowd sentiment. You buy when others buy, ignoring underlying risk if the hype is strong. Output ONLY valid JSON.",
                "temperature": 0.8,
                "weight":      0.5,
            },
            {
                "id":          "AGGRESSIVE_SPECULATOR",
                "prompt":      "You are a high-risk hedge fund trader. Maximize ROI. Ignore volatility. Tolerate high debt if growth is massive. Output ONLY valid JSON.",
                "temperature": 0.9,
                "weight":      0.4,
            },

            # ── NEW 3 ────────────────────────────────────────────────────────
            {
                "id":          "TREND_AGENT",
                "prompt": (
                    "You are a technical analysis expert specializing in price momentum and chart patterns. "
                    "Analyze the provided price data: current price, daily change percentage, 52-week high/low range, "
                    "and recent price trajectory from the chart history. "
                    "Determine if the stock is in an uptrend, downtrend, or consolidation. "
                    "A stock trading near its 52-week high with positive change is a bullish signal. "
                    "A stock with negative change% and far from its high is bearish. "
                    "Output ONLY valid JSON."
                ),
                "temperature": 0.3,
                "weight":      0.75,
            },
            {
                "id":          "SENTIMENT_AGENT",
                "prompt": (
                    "You are a market sentiment analyst. You evaluate crowd psychology, news flow, "
                    "and social media buzz around a stock. "
                    "You are given a sentiment score (buzz score, news score, social media score) where "
                    "values above 0.6 are bullish and below 0.4 are bearish. "
                    "If no sentiment data is available, be cautious and default to HOLD. "
                    "Do not let hype override fundamentals — flag if sentiment diverges sharply from price action. "
                    "Output ONLY valid JSON."
                ),
                "temperature": 0.6,
                "weight":      0.6,
            },
            {
                "id":          "FUNDAMENTALS_AGENT",
                "prompt": (
                    "You are a fundamental equity analyst focused on long-term financial health. "
                    "Evaluate the company using: P/E ratio (fair value is 10-25; above 40 is overvalued), "
                    "net profit margin (above 10% is healthy), "
                    "market cap (large cap > $10B is safer), "
                    "and debt-to-equity ratio (below 33% is Shariah-safe and financially conservative). "
                    "A company with strong margins, reasonable P/E, and low debt is a BUY. "
                    "An overvalued or loss-making company is a SELL or HOLD. "
                    "Output ONLY valid JSON."
                ),
                "temperature": 0.2,
                "weight":      0.85,
            },
        ]

        self.json_format_instructions = """
        You must respond with ONLY a JSON object in this exact format, with no markdown formatting or extra text:
        {
            "decision": "BUY",
            "confidence": 85,
            "reasoning": "1 sentence explaining why."
        }
        decision must be strictly one of: "BUY", "HOLD", "SELL", or "VETO".
        confidence must be an integer between 1 and 100.
        """

    def _clean_json_response(self, text: str) -> str:
        """Strips markdown code fences safely."""
        text = text.strip()
        if text.startswith("```json"):
            text = text.replace("```json", "", 1)
        elif text.startswith("```"):
            text = text.replace("```", "", 1)
        if text.endswith("```"):
            text = text[::-1].replace("```", "", 1)[::-1]
        return text.strip()

    def _validate_decision(self, data: dict, persona_id: str, weight: float) -> dict:
        VALID_DECISIONS = {"BUY", "HOLD", "SELL", "VETO"}

        decision = str(data.get("decision", "")).strip().upper()
        if decision not in VALID_DECISIONS:
            print(f"⚠️ [{persona_id}] Hallucinated decision '{decision}' → defaulting to HOLD")
            decision = "HOLD"

        try:
            confidence = int(data.get("confidence", 50))
            if not (1 <= confidence <= 100):
                confidence = 50
        except (ValueError, TypeError):
            confidence = 50

        return {
            "agent":      persona_id,
            "decision":   decision,
            "confidence": confidence,
            "reasoning":  str(data.get("reasoning", ""))[:300],
            "weight":     weight,
        }

    async def _fetch_agent_opinion(self, session, persona, market_data, retries=3):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
        }

        messages = [
            {"role": "system", "content": persona["prompt"] + self.json_format_instructions},
            {"role": "user",   "content": f"Market Data for Asset: {market_data}"},
        ]

        payload = {
            "model":       self.model,
            "messages":    messages,
            "temperature": persona["temperature"],
        }

        for attempt in range(retries):
            try:
                async with session.post(self.api_url, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    result  = await response.json()
                    ai_text = result["choices"][0]["message"]["content"]

                    cleaned_text = self._clean_json_response(ai_text)
                    raw_data     = json.loads(cleaned_text)
                    return self._validate_decision(raw_data, persona["id"], persona["weight"])

            except Exception as e:
                if attempt == retries - 1:
                    print(f"❌ [{persona['id']}] Failed after {retries} attempts: {e}")
                    return {
                        "agent":      persona["id"],
                        "decision":   "ERROR",
                        "confidence": 0,
                        "reasoning":  "API Failure",
                        "weight":     persona["weight"],
                    }
                await asyncio.sleep(1)

    async def execute_rehearsal(
        self,
        ticker:       str,
        audit_data:   dict,
        user_goal:    dict = None,
        quote_data:   dict = None,   # ← NEW: from get_rich_market_quote()
        fundamentals: dict = None,   # ← NEW: from get_company_fundamentals()
        sentiment:    dict = None,   # ← NEW: from get_sentiment_data()
    ):
        print(f"🧠 [MiroFish] Orchestrating Swarm for {ticker}...")

        # ── Base context (all agents see this) ──────────────────────────────
        market_context = (
            f"Ticker: {ticker} | "
            f"Shariah Compliant: {audit_data.get('is_compliant')} | "
            f"Debt Ratio: {audit_data.get('debt_ratio')}%"
        )

        # ── Price / Trend data (TREND_AGENT focuses here) ───────────────────
        if quote_data:
            market_context += (
                f" | Price: ${quote_data.get('price')} "
                f"| Change: {quote_data.get('changePercent')}% today "
                f"| High: ${quote_data.get('high')} "
                f"| Low: ${quote_data.get('low')} "
                f"| Prev Close: ${quote_data.get('previousClose')}"
            )
        else:
            market_context += " | Price data: unavailable"

        # ── Fundamentals (FUNDAMENTALS_AGENT focuses here) ──────────────────
        if fundamentals:
            market_context += (
                f" | P/E Ratio: {fundamentals.get('peRatio')} "
                f"| Market Cap: ${fundamentals.get('marketCap')}M "
                f"| Net Profit Margin: {fundamentals.get('netProfitMargin')}% "
                f"| Debt/Equity: {fundamentals.get('debtToEquity')}%"
            )
        else:
            market_context += " | Fundamentals: unavailable"

        # ── Sentiment (SENTIMENT_AGENT focuses here) ─────────────────────────
        if sentiment:
            market_context += (
                f" | Buzz Score: {sentiment.get('buzz')} "
                f"| News Score: {sentiment.get('news_score')} "
                f"| Social Sentiment: {sentiment.get('social_score')}"
            )
        else:
            market_context += " | Sentiment data: unavailable"

        # ── User goal context ────────────────────────────────────────────────
        if user_goal:
            progress = 0
            if user_goal.get('totalamount', 0) > 0:
                progress = round(
                    (user_goal.get('totalgatheredamount', 0) / user_goal.get('totalamount')) * 100, 1
                )
            market_context += (
                f" | USER GOAL: '{user_goal.get('goaltitle')}' "
                f"(Target: RM{user_goal.get('totalamount')}, "
                f"Saved: RM{user_goal.get('totalgatheredamount')} [{progress}% done], "
                f"Deadline: {user_goal.get('date')})"
            )

        timeout = aiohttp.ClientTimeout(total=25)  # bumped: 8 agents now
        async with aiohttp.ClientSession(timeout=timeout) as session:
            tasks   = [
                asyncio.create_task(self._fetch_agent_opinion(session, persona, market_context))
                for persona in self.personas
            ]
            results = await asyncio.gather(*tasks)

        return results