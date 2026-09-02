# agents/fundamental_agent.py
#
# Fundamental Analysis Agent
# Time Horizon: MEDIUM_LONG_TERM
#
# Analyzes financial health, business quality, and valuation conditionally.
# Never invents numbers; explicitly handles loss-making, partial, and crypto data.

import json
import aiohttp
from typing import Dict, Any, Tuple, Optional
from agents.base_agent import BaseAgent


FUNDAMENTAL_SYSTEM_PROMPT = """You are the Fundamental Analysis Agent.
Analyze the company's financial health, business quality, and valuation.

Time Horizon: MEDIUM_LONG_TERM

Evaluate:
- Revenue and Revenue growth
- Earnings growth and EPS
- Profitability and Net profit margins
- Return on Equity (ROE)
- Debt-to-Equity and balance sheet stability
- Free Cash Flow
- Valuation (P/E ratio, Market Cap) — evaluate ONLY if applicable (e.g. not applicable for loss-making or crypto)

Strict Behavioral Rules:
1. Separate: Business quality, Financial strength, Valuation.
2. Do NOT make the final BUY/HOLD/SELL decision.
3. Never invent financial figures. If a metric is null/unavailable, explicitly state that it is unavailable.
4. If the asset is Crypto (e.g. ETH, BTC), set ratings to "NOT_APPLICABLE" and state that traditional corporate statements do not apply.
5. Every important claim must reference supplied figures.
6. Return ONLY valid JSON matching the exact schema below.

Required JSON Schema:
{
  "agent": "fundamental",
  "time_horizon": "MEDIUM_LONG_TERM",
  "business_quality": {
    "rating": "STRONG",
    "confidence": 0.81
  },
  "financial_health": {
    "rating": "HEALTHY",
    "confidence": 0.78
  },
  "valuation": {
    "rating": "FAIR",
    "confidence": 0.64
  },
  "bullish_factors": ["Healthy net profit margin >15%", "Positive revenue growth YoY"],
  "bearish_factors": ["Debt-to-equity ratio above industry average"],
  "evidence": [
    {
      "claim": "Profit margin is 16.2%",
      "field": "profit_margin",
      "value": 16.2
    }
  ]
}

Allowed Ratings:
- business_quality: "STRONG", "MODERATE", "WEAK", "NOT_APPLICABLE"
- financial_health: "HEALTHY", "MODERATE", "DISTRESSED", "NOT_APPLICABLE"
- valuation: "UNDERVALUED", "FAIR", "OVERVALUED", "NOT_APPLICABLE"
confidence: Float between 0.0 and 1.0 (evidence strength)
"""


class FundamentalAgent(BaseAgent):
    AGENT_ID = "fundamental"
    TIME_HORIZON = "MEDIUM_LONG_TERM"
    TEMPERATURE = 0.2

    @staticmethod
    def validate_report(data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        if not isinstance(data, dict):
            return False, "Output must be a JSON object"

        # Validate sub-objects
        for key, valid_ratings in [
            ("business_quality", ("STRONG", "MODERATE", "WEAK", "NOT_APPLICABLE")),
            ("financial_health", ("HEALTHY", "MODERATE", "DISTRESSED", "NOT_APPLICABLE")),
            ("valuation",        ("UNDERVALUED", "FAIR", "OVERVALUED", "NOT_APPLICABLE")),
        ]:
            sub = data.get(key)
            if not isinstance(sub, dict):
                data[key] = {"rating": "NOT_APPLICABLE", "confidence": 0.5}
            else:
                rating = str(sub.get("rating", "NOT_APPLICABLE")).upper()
                if rating not in valid_ratings:
                    rating = "NOT_APPLICABLE"
                sub["rating"] = rating
                
                # Confidence
                c = sub.get("confidence", 0.5)
                try:
                    c_val = float(c)
                    if c_val > 1.0:
                        c_val = c_val / 100.0
                    sub["confidence"] = round(max(0.0, min(1.0, c_val)), 2)
                except Exception:
                    sub["confidence"] = 0.5

        if not isinstance(data.get("bullish_factors"), list):
            data["bullish_factors"] = []
        if not isinstance(data.get("bearish_factors"), list):
            data["bearish_factors"] = []
        if not isinstance(data.get("evidence"), list):
            data["evidence"] = []

        data["agent"] = "fundamental"
        data["time_horizon"] = "MEDIUM_LONG_TERM"

        return True, None

    async def run(self, session: aiohttp.ClientSession, market_snapshot: Dict[str, Any], analysis_id: str = "local") -> Dict[str, Any]:
        """
        Runs Fundamental Analysis on normalized market snapshot.
        """
        payload = {
            "symbol":        market_snapshot.get("symbol"),
            "company_name":  market_snapshot.get("company_name"),
            "asset_type":    market_snapshot.get("asset_type"),
            "currency":      market_snapshot.get("currency"),
            "fundamentals":  market_snapshot.get("fundamentals", {}),
            "data_quality":  market_snapshot.get("data_quality", {}),
        }

        user_content = f"FUNDAMENTAL DATA SNAPSHOT:\n{json.dumps(payload, indent=2)}\n\nPlease evaluate financial health, business quality, and valuation. Return valid JSON."

        return await self.execute_with_validation(
            session=session,
            system_prompt=FUNDAMENTAL_SYSTEM_PROMPT,
            user_content=user_content,
            validator_func=self.validate_report,
            analysis_id=analysis_id,
        )
