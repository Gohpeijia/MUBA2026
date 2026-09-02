# agents/risk_agent.py
#
# Risk / Devil's Advocate Agent
#
# Actively challenges the investment thesis.
# Dissects the Technical, Fundamental, and News specialist reports to:
#   - Uncover unverified assumptions and data gaps
#   - Detect cross-report contradictions (e.g. bullish price vs stretched valuation)
#   - Identify worst-case downside failure modes and invalidation conditions

import json
import aiohttp
from typing import Dict, Any, Tuple, Optional
from agents.base_agent import BaseAgent


RISK_SYSTEM_PROMPT = """You are the Risk and Devil's Advocate Agent for an elite AI investment intelligence committee.
Your explicit job is to CHALLENGE the investment thesis and act as a critical counterweight.

Review the outputs from:
1. Technical Analysis Agent
2. Fundamental Analysis Agent
3. News Intelligence Agent
4. Raw Quantitative Data & Data Quality Summary

Strict Behavioral Rules:
1. Do NOT simply summarize the other agents.
2. Actively argue against the strongest bullish case. Even if all analysts are bullish, search for overlooked blindspots.
3. Identify contradictions across specialist findings (e.g. short-term momentum vs valuation stretch, or strong news vs declining free cash flow).
4. Identify unverified or weak assumptions.
5. Identify missing data risks (what don't we know?).
6. List explicit Invalidation Conditions: exact concrete events that would break the bull thesis (e.g. "Break below SMA-200 support at $150", "Margin contraction below 10% in Q4").
7. Return ONLY valid JSON matching the exact schema below.

Required JSON Schema:
{
  "agent": "risk",
  "risk_level": "MEDIUM",
  "major_risks": [
    {
      "risk": "Valuation Compression Risk",
      "severity": "HIGH",
      "explanation": "P/E of 38 leaves minimal margin of safety if earnings growth decelerates."
    }
  ],
  "contradictions": [
    {
      "finding": "Technical analyst notes strong upward momentum near 52-week high",
      "counterpoint": "Fundamental analyst notes net margins contracted 200 bps YoY"
    }
  ],
  "invalidation_conditions": [
    "Closing daily price breaks below 50-day SMA",
    "Upcoming earnings report misses top-line revenue consensus by >5%"
  ],
  "overall_assessment": "While momentum is supportive in the short term, valuation does not provide adequate margin of safety."
}

Allowed Values:
- risk_level: "LOW", "MEDIUM", "HIGH", "EXTREME"
- severity: "LOW", "MEDIUM", "HIGH", "CRITICAL"
"""


class RiskAgent(BaseAgent):
    AGENT_ID = "risk"
    TIME_HORIZON = "ALL_HORIZONS"
    TEMPERATURE = 0.3  # Slightly higher for contrarian critical thought

    @staticmethod
    def validate_report(data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        if not isinstance(data, dict):
            return False, "Output must be a JSON object"

        risk_level = str(data.get("risk_level", "MEDIUM")).upper()
        if risk_level not in ("LOW", "MEDIUM", "HIGH", "EXTREME"):
            risk_level = "MEDIUM"
        data["risk_level"] = risk_level

        if not isinstance(data.get("major_risks"), list):
            data["major_risks"] = []
        if not isinstance(data.get("contradictions"), list):
            data["contradictions"] = []
        if not isinstance(data.get("invalidation_conditions"), list):
            data["invalidation_conditions"] = []

        data["overall_assessment"] = str(data.get("overall_assessment", ""))[:600]
        data["agent"] = "risk"
        data["time_horizon"] = "ALL_HORIZONS"

        return True, None

    def generate_fallback_assessment(
        self,
        market_snapshot: Dict[str, Any],
        technical_report: Dict[str, Any],
        fundamental_report: Dict[str, Any],
        news_report: Dict[str, Any],
    ) -> Dict[str, Any]:
        symbol = market_snapshot.get("symbol", "N/A")
        tech_outlook = technical_report.get("outlook", "NEUTRAL")
        fund_rating = fundamental_report.get("business_quality", {}).get("rating", "NOT_APPLICABLE")
        news_sentiment = news_report.get("overall_sentiment", "NEUTRAL")

        major_risks = [
            {
                "risk": "Macroeconomic Sensitivity",
                "severity": "MEDIUM",
                "explanation": f"Broader market volatility and interest rate policy shifts may pressure {symbol}."
            },
            {
                "risk": "Momentum Reversal Risk",
                "severity": "MEDIUM",
                "explanation": f"Current technical signals ({tech_outlook}) could face sudden profit-taking at resistance."
            }
        ]

        contradictions = []
        if tech_outlook == "BULLISH" and news_sentiment in ("NEGATIVE", "BEARISH"):
            contradictions.append({
                "finding": f"Technical momentum is {tech_outlook}",
                "counterpoint": f"News flow reflects cautious or negative sentiment ({news_sentiment})"
            })
        elif tech_outlook == "BULLISH" and fund_rating in ("POOR", "WEAK"):
            contradictions.append({
                "finding": "Price action shows bullish short-term strength",
                "counterpoint": "Underlying business fundamentals show signs of weakness or margin compression"
            })
        else:
            contradictions.append({
                "finding": f"Baseline consensus leans towards {tech_outlook} outlook",
                "counterpoint": "Downside tail risks in broader macro liquidity remain unpriced"
            })

        invalidation_conditions = [
            f"Sustained breakdown below key technical moving average support levels.",
            f"Deterioration in sector liquidity or unexpected macroeconomic headwinds."
        ]

        return {
            "agent": "risk",
            "status": "SUCCESS",
            "time_horizon": "ALL_HORIZONS",
            "provider_used": "Rule-Based Risk Synthesis (Deterministic Fallback)",
            "risk_level": "MEDIUM",
            "major_risks": major_risks,
            "contradictions": contradictions,
            "invalidation_conditions": invalidation_conditions,
            "overall_assessment": f"While baseline indicators for {symbol} remain active, systemic volatility and unexpected technical breakdown represent the primary downside risks."
        }

    async def run(
        self,
        session: aiohttp.ClientSession,
        market_snapshot: Dict[str, Any],
        technical_report: Dict[str, Any],
        fundamental_report: Dict[str, Any],
        news_report: Dict[str, Any],
        analysis_id: str = "local",
    ) -> Dict[str, Any]:
        """
        Runs Adversarial Risk Analysis against the 3 specialist reports and raw data.
        Falls back to rule-based risk synthesis if LLMs fail.
        """
        payload = {
            "symbol":             market_snapshot.get("symbol"),
            "company_name":       market_snapshot.get("company_name"),
            "asset_type":         market_snapshot.get("asset_type"),
            "data_quality":       market_snapshot.get("data_quality", {}).get("overall", "MODERATE"),
            "technical_report": {
                "outlook": technical_report.get("outlook", "NEUTRAL"),
                "confidence": technical_report.get("confidence", 0.5),
                "signals": technical_report.get("signals", [])[:3],
            },
            "fundamental_report": {
                "rating": fundamental_report.get("business_quality", {}).get("rating", "NOT_APPLICABLE"),
                "financial_health": fundamental_report.get("financial_health", {}).get("rating", "NOT_APPLICABLE"),
            },
            "news_report": {
                "overall_sentiment": news_report.get("overall_sentiment", "NEUTRAL"),
                "thesis_impact": news_report.get("thesis_impact", "NEUTRAL"),
            },
        }

        user_content = f"SPECIALIST ANALYST DOSSIER:\n{json.dumps(payload, indent=2)}\n\nPlease critique the thesis, find contradictions, and identify key downside failure conditions. Return valid JSON."

        report = await self.execute_with_validation(
            session=session,
            system_prompt=RISK_SYSTEM_PROMPT,
            user_content=user_content,
            validator_func=self.validate_report,
            analysis_id=analysis_id,
        )

        if report.get("status") == "SUCCESS":
            return report

        print(f"  🛡️ [{analysis_id}] [risk] LLM call unavailable — generating deterministic rule-based risk critique.")
        return self.generate_fallback_assessment(
            market_snapshot=market_snapshot,
            technical_report=technical_report,
            fundamental_report=fundamental_report,
            news_report=news_report,
        )
