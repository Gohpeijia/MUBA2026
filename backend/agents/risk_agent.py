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


RISK_SYSTEM_PROMPT = """You are the Risk and Devil's Advocate Agent for an AI investment intelligence committee.

Your job is to challenge the investment thesis using ONLY the supplied evidence.

You receive:
1. Canonical Market Data
2. Quantitative Screening
3. Technical Report
4. Fundamental Report
5. News Report
6. Data Quality

IMPORTANT EVIDENCE RULES:

1. NEVER use outside financial knowledge.
2. NEVER invent or recall a financial metric.
3. NEVER replace a supplied value with another remembered value.
4. If P/E is supplied as 28.47, you MUST use 28.47.
5. Do not say P/E is 38, 40, 50, etc. unless that exact value appears in the dossier.
6. Do not mention revenue CAGR, FCF yield, debt-to-EBITDA, market share, earnings consensus, or other metrics unless they are explicitly supplied.
7. Do not claim that a ratio is high/low versus an industry unless an industry benchmark is supplied.
8. Missing data is UNKNOWN, not bearish evidence.
9. No news is NOT negative news.
10. Distinguish genuine contradictions from simply different time horizons.
11. Quantitative screening is independent evidence and should be considered.
12. Risk analysis must challenge the thesis without fabricating risks as facts.
13. Invalidation conditions must use supplied technical levels when available.
14. Future events may be described generically, but do not invent numerical thresholds unless supplied.
15. Return ONLY valid JSON.

Examples of VALID reasoning:
- "Price is above SMA-50 and SMA-200, but short-term resistance may limit upside."
- "Fundamental data shows strong revenue growth, while valuation remains dependent on continued earnings growth."
- "News evidence is unavailable, so news provides no directional confirmation."

Examples of INVALID reasoning:
- "P/E is 38x" when supplied P/E is 28.47.
- "Debt-to-EBITDA is above 4x" when debt-to-EBITDA was not supplied.
- "Revenue consensus was missed by 5%" when no earnings report was supplied.

Required JSON Schema:
{
  "agent": "risk",
  "risk_level": "MEDIUM",
  "major_risks": [],
  "contradictions": [],
  "invalidation_conditions": [],
  "overall_assessment": ""
}

Allowed risk levels:
"LOW", "MEDIUM", "HIGH", "EXTREME"

Allowed severity:
"LOW", "MEDIUM", "HIGH", "CRITICAL"
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
    screening_result: Optional[Dict[str, Any]] = None,
    analysis_id: str = "local",
) -> Dict[str, Any]:
        """
        Runs Adversarial Risk Analysis against the 3 specialist reports and raw data.
        Falls back to rule-based risk synthesis if LLMs fail.
        """
        screening_result = screening_result or {}

        payload = {
            "canonical_market_data": {
                "symbol": market_snapshot.get("symbol"),
                "company_name": market_snapshot.get("company_name"),
                "asset_type": market_snapshot.get("asset_type"),
                "currency": market_snapshot.get("currency"),
                "price": market_snapshot.get("price", {}),
                "technical_indicators": market_snapshot.get(
                    "technical_indicators",
                    {},
                ),
                "fundamentals": market_snapshot.get(
                    "fundamentals",
                    {},
                ),
            },

            "quantitative_screen": {
                "score": screening_result.get("score"),
                "screening_signal": screening_result.get(
                    "screening_signal"
                ),
                "component_scores": screening_result.get(
                    "component_scores",
                    {},
                ),
                "signals": screening_result.get(
                    "signals",
                    {},
                ),
            },

            "data_quality": market_snapshot.get(
                "data_quality",
                {},
            ),

            "technical_report": technical_report,

            "fundamental_report": fundamental_report,

            "news_report": news_report,
        }

        user_content = (
    "RISK ANALYSIS DOSSIER:\n"
    f"{json.dumps(payload, indent=2)}\n\n"
    "Challenge the thesis using only supplied evidence. "
    "Do not invent financial metrics. "
    "Return valid JSON."
)

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
