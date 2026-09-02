# agents/committee_agent.py
#
# Chief Investment Committee Agent
#
# Final decision-making authority that synthesizes:
#   1. Technical Analysis (SHORT_TERM)
#   2. Fundamental Analysis (MEDIUM_LONG_TERM)
#   3. News Intelligence (SHORT_MEDIUM_TERM)
#   4. Risk / Devil's Advocate (Contradictions & Invalidation Triggers)
#   5. Data Quality & Freshness Assessment
#
# Crucial Rule: NO SIMPLE MAJORITY VOTING.
# Evaluates evidence weight, reconciles time horizons, and emits INSUFFICIENT_DATA if data is too sparse.

import json
import aiohttp
from typing import Dict, Any, Tuple, Optional
from agents.base_agent import BaseAgent


COMMITTEE_SYSTEM_PROMPT = """You are the Chief Investment Committee Chair for an elite AI investment intelligence system.
You are responsible for issuing the explainable final investment assessment.

You receive independent reports from:
1. Technical Analyst (Time Horizon: SHORT_TERM)
2. Fundamental Analyst (Time Horizon: MEDIUM_LONG_TERM)
3. News Intelligence Analyst (Time Horizon: SHORT_MEDIUM_TERM)
4. Risk / Devil's Advocate (Contradiction and downside risk challenge)
5. Data Quality Summary (Verification of data completeness)

Strict Behavioral Rules:
1. Do NOT simply count votes (e.g. 3 bullish vs 1 bearish does NOT automatically equal BUY).
2. Compare evidence quality and data quality.
3. Reconcile differences in time horizon (e.g. a short-term technical pullback is NOT contradictory with multi-year fundamental strength).
4. Evaluate the Risk Agent's counterpoints seriously. If valuation or risk objections are strong, HOLD is safer than BUY.
5. If data quality is POOR or essential metrics are missing across multiple agents, set decision to "INSUFFICIENT_DATA".
6. Construct the strongest Bull Case and Bear Case from the evidence.
7. Explain clearly WHY the decision was reached.
8. Confidence represents evidence conviction (strength and consistency of data), NOT a probability of future returns.
9. Return ONLY valid JSON matching the exact schema below.

Required JSON Schema:
{
  "symbol": "1155.KL",
  "decision": "HOLD",
  "confidence": 0.81,
  "risk_level": "MEDIUM",
  "summary": "While the company displays robust profitability and dividend yields, current price momentum is testing resistance with elevated valuation multiples. We recommend waiting for a consolidation pullback.",
  "bull_case": [
    "Consistent net profit margins above 15% with reliable cash generation",
    "Positive sector tailwinds and stable institutional dividend support"
  ],
  "bear_case": [
    "Short-term technical RSI indicates overbought condition near 52-week high",
    "Risk analyst highlighted thin margin of safety given slowing top-line growth"
  ],
  "key_reasons": [
    "Strong balance sheet health confirms downside resilience",
    "Short-term technical exhaustion suggests better risk/reward entry point on a pullback"
  ],
  "major_risks": [
    "Macro interest rate shifts compressing net interest margins",
    "Valuation multiple compression if quarterly earnings disappoint"
  ],
  "invalidation_conditions": [
    "Sustained breakout above resistance on 2x average daily volume",
    "Unexpected dividend cut or quarterly margin deterioration"
  ],
  "agent_consensus": {
    "technical": "BULLISH",
    "fundamental": "STRONG",
    "news": "POSITIVE",
    "risk": "MEDIUM"
  }
}

Allowed Decisions: "BUY", "HOLD", "SELL", "INSUFFICIENT_DATA"
Allowed Risk Levels: "LOW", "MEDIUM", "HIGH", "EXTREME"
confidence: Float between 0.0 and 1.0 (evidence strength)
"""


class CommitteeAgent(BaseAgent):
    AGENT_ID = "committee"
    TIME_HORIZON = "SYNTHESIZED"
    TEMPERATURE = 0.15  # Low temperature for measured, consistent decision synthesis

    @staticmethod
    def validate_report(data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        if not isinstance(data, dict):
            return False, "Output must be a JSON object"

        decision = str(data.get("decision", "HOLD")).upper()
        if decision not in ("BUY", "HOLD", "SELL", "INSUFFICIENT_DATA"):
            decision = "HOLD"
        data["decision"] = decision

        risk_level = str(data.get("risk_level", "MEDIUM")).upper()
        if risk_level not in ("LOW", "MEDIUM", "HIGH", "EXTREME"):
            risk_level = "MEDIUM"
        data["risk_level"] = risk_level

        conf = data.get("confidence", 0.5)
        try:
            conf_val = float(conf)
            if conf_val > 1.0:
                conf_val = conf_val / 100.0
            data["confidence"] = round(max(0.0, min(1.0, conf_val)), 2)
        except Exception:
            data["confidence"] = 0.5

        if not isinstance(data.get("bull_case"), list):
            data["bull_case"] = []
        if not isinstance(data.get("bear_case"), list):
            data["bear_case"] = []
        if not isinstance(data.get("key_reasons"), list):
            data["key_reasons"] = []
        if not isinstance(data.get("major_risks"), list):
            data["major_risks"] = []
        if not isinstance(data.get("invalidation_conditions"), list):
            data["invalidation_conditions"] = []

        if not isinstance(data.get("agent_consensus"), dict):
            data["agent_consensus"] = {
                "technical":   "NEUTRAL",
                "fundamental": "NOT_APPLICABLE",
                "news":        "NEUTRAL",
                "risk":        "MEDIUM",
            }

        data["summary"] = str(data.get("summary", ""))[:800]
        data["agent"] = "committee"

        return True, None

    async def run(
        self,
        session: aiohttp.ClientSession,
        market_snapshot: Dict[str, Any],
        technical_report: Dict[str, Any],
        fundamental_report: Dict[str, Any],
        news_report: Dict[str, Any],
        risk_report: Dict[str, Any],
        analysis_id: str = "local",
    ) -> Dict[str, Any]:
        """
        Runs Committee Synthesis across all 4 specialist reports and data quality metadata.
        """
        payload = {
            "symbol":             market_snapshot.get("symbol"),
            "company_name":       market_snapshot.get("company_name"),
            "asset_type":         market_snapshot.get("asset_type"),
            "currency":           market_snapshot.get("currency"),
            "data_quality":       market_snapshot.get("data_quality", {}),
            "data_freshness":     market_snapshot.get("data_freshness", {}),
            "reports": {
                "technical":   technical_report,
                "fundamental": fundamental_report,
                "news":        news_report,
                "risk":        risk_report,
            },
        }

        user_content = f"INVESTMENT COMMITTEE DOSSIER:\n{json.dumps(payload, indent=2)}\n\nPlease deliberate, reconcile time horizons, evaluate evidence quality, and issue the final investment decision. Return valid JSON."

        return await self.execute_with_validation(
            session=session,
            system_prompt=COMMITTEE_SYSTEM_PROMPT,
            user_content=user_content,
            validator_func=self.validate_report,
            analysis_id=analysis_id,
        )
