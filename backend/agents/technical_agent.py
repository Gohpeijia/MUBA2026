# agents/technical_agent.py
#
# Technical Analysis Agent
# Time Horizon: SHORT_TERM
#
# Analyzes price behavior, momentum, programmatic RSI, MACD, SMAs, volume, and volatility.
# Focuses strictly on interpretation without doing math or making the final BUY/SELL decision.

import json
import aiohttp
from typing import Dict, Any, Tuple, Optional
from agents.base_agent import BaseAgent


TECHNICAL_SYSTEM_PROMPT = """You are the Technical Analysis Agent for an AI investment research system.
Your role is ONLY to analyze market price behavior.

Time Horizon: SHORT_TERM

Analyze:
- Price momentum
- Trend
- RSI (pre-computed 14-period)
- MACD (pre-computed line, signal, histogram)
- Moving averages (SMA 20, 50, 200, crossover signals)
- Volume and 30-day average volume
- Realized Volatility (30-day annualized)
- Potential support and resistance levels
- Bullish and bearish signals

Strict Behavioral Rules:
1. Do NOT make the final BUY/HOLD/SELL decision.
2. Do NOT invent missing data. If an indicator is null, state that it is unavailable.
3. Every important conclusion must reference the supplied technical data.
4. Separate facts (e.g. "RSI is 63.2") from interpretation.
5. Return ONLY valid JSON matching the exact schema below with no extra text or markdown fences.

Required JSON Schema:
{
  "agent": "technical",
  "time_horizon": "SHORT_TERM",
  "outlook": "BULLISH",
  "confidence": 0.76,
  "bullish_signals": ["Price above SMA-50 and SMA-200", "MACD histogram positive"],
  "bearish_signals": ["RSI approaching overbought territory at 68.5"],
  "evidence": [
    {
      "claim": "Golden cross active",
      "field": "crossover_signal",
      "value": "GOLDEN_CROSS"
    }
  ],
  "key_risk": "Short-term momentum exhaustion near resistance level."
}

Allowed outlook values: "BULLISH", "BEARISH", "NEUTRAL"
confidence: Float between 0.0 and 1.0 (evidence strength)
"""


class TechnicalAgent(BaseAgent):
    AGENT_ID = "technical"
    TIME_HORIZON = "SHORT_TERM"
    TEMPERATURE = 0.2

    @staticmethod
    def validate_report(data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        if not isinstance(data, dict):
            return False, "Output must be a JSON object"

        outlook = str(data.get("outlook", "")).upper()
        if outlook not in ("BULLISH", "BEARISH", "NEUTRAL"):
            return False, f"Invalid outlook '{outlook}'. Must be BULLISH, BEARISH, or NEUTRAL"

        data["outlook"] = outlook

        # Confidence normalization (e.g. 76 -> 0.76)
        conf = data.get("confidence")
        if conf is None:
            return False, "Missing 'confidence' field"
        try:
            conf_val = float(conf)
            if conf_val > 1.0:
                conf_val = conf_val / 100.0
            data["confidence"] = round(max(0.0, min(1.0, conf_val)), 2)
        except (ValueError, TypeError):
            data["confidence"] = 0.5

        if not isinstance(data.get("bullish_signals"), list):
            data["bullish_signals"] = []
        if not isinstance(data.get("bearish_signals"), list):
            data["bearish_signals"] = []
        if not isinstance(data.get("evidence"), list):
            data["evidence"] = []

        data["key_risk"] = str(data.get("key_risk", ""))[:300]
        data["agent"] = "technical"
        data["time_horizon"] = "SHORT_TERM"

        return True, None

    async def run(self, session: aiohttp.ClientSession, market_snapshot: Dict[str, Any], analysis_id: str = "local") -> Dict[str, Any]:
        """
        Runs Technical Analysis on normalized market snapshot.
        """
        price_info = market_snapshot.get("price", {})
        indicators = market_snapshot.get("technical_indicators", {})

        payload = {
            "symbol":               market_snapshot.get("symbol"),
            "company_name":         market_snapshot.get("company_name"),
            "current_price":        price_info.get("current_price"),
            "change_1d_pct":        price_info.get("change_1d_pct"),
            "change_30d_pct":       price_info.get("change_30d_pct"),
            "52w_high":             price_info.get("fifty_two_week_high"),
            "52w_low":              price_info.get("fifty_two_week_low"),
            "technical_indicators": indicators,
        }

        user_content = f"TECHNICAL DATA SNAPSHOT:\n{json.dumps(payload, indent=2)}\n\nPlease analyze market price behavior and return valid JSON."

        return await self.execute_with_validation(
            session=session,
            system_prompt=TECHNICAL_SYSTEM_PROMPT,
            user_content=user_content,
            validator_func=self.validate_report,
            analysis_id=analysis_id,
        )
