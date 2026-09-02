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
5. If data quality is POOR or essential metrics are missing across multiple agents, set decision to "INSUFFICIENT_DATA" or "HOLD".
6. ETF & Index Assets: When analyzing Index ETFs (e.g. SPY, QQQ, DIA) where Fundamental corporate metrics are NOT_APPLICABLE, base the deliberation on technical trend, macro environment, news sentiment, and systemic risk.
7. Construct the strongest Bull Case and Bear Case from the evidence.
8. Explain clearly WHY the decision was reached in a comprehensive "summary" string (2-3 complete sentences). NEVER leave "summary" empty.
9. Confidence represents evidence conviction (strength and consistency of data), NOT a probability of future returns.
10. Return ONLY valid JSON matching the exact schema below.

Required JSON Schema:
{
  "symbol": "SPY",
  "decision": "HOLD",
  "confidence": 0.78,
  "risk_level": "MEDIUM",
  "summary": "While broad market technical momentum remains healthy above key moving averages, mixed news sentiment and macro rate sensitivities suggest entering with caution. We recommend a HOLD / Dollar-Cost-Averaging posture.",
  "bull_case": [
    "Sustained uptrend with price holding above 50-day and 200-day moving averages",
    "Positive institutional liquidity support across mega-cap constituents"
  ],
  "bear_case": [
    "Overbought momentum oscillators hinting at potential short-term pullback",
    "Macro geopolitical and interest rate uncertainties creating volatility"
  ],
  "key_reasons": [
    "Technical trend remains structurally positive above support",
    "Risk/reward is balanced at current levels favoring incremental allocation over aggressive buying"
  ],
  "major_risks": [
    "Unexpected macroeconomic inflation prints impacting discount rates",
    "Breakdown below major technical moving average support"
  ],
  "invalidation_conditions": [
    "Daily close below 200-day moving average",
    "Sharp deterioration in broader macroeconomic earnings breadth"
  ],
  "agent_consensus": {
    "technical": "BULLISH",
    "fundamental": "NOT_APPLICABLE",
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

        if not isinstance(data.get("bull_case"), list) or not data.get("bull_case"):
            data["bull_case"] = ["Constructive price momentum supported by constituent liquidity."]
        if not isinstance(data.get("bear_case"), list) or not data.get("bear_case"):
            data["bear_case"] = ["Macroeconomic resistance and potential short-term multiple compression."]
        if not isinstance(data.get("key_reasons"), list) or not data.get("key_reasons"):
            data["key_reasons"] = ["Balanced risk-reward profile based on current technical and sentiment indicators."]
        if not isinstance(data.get("major_risks"), list) or not data.get("major_risks"):
            data["major_risks"] = ["Systemic market volatility and interest rate policy shifts."]
        if not isinstance(data.get("invalidation_conditions"), list) or not data.get("invalidation_conditions"):
            data["invalidation_conditions"] = ["Sustained violation of key technical moving average support levels."]

        if not isinstance(data.get("agent_consensus"), dict):
            data["agent_consensus"] = {
                "technical":   "NEUTRAL",
                "fundamental": "NOT_APPLICABLE",
                "news":        "NEUTRAL",
                "risk":        "MEDIUM",
            }

        # Ensure summary is never empty
        summary_str = str(data.get("summary", "")).strip()
        if not summary_str or len(summary_str) < 15:
            sym = data.get("symbol", "the asset")
            tech_c = data.get("agent_consensus", {}).get("technical", "NEUTRAL")
            news_c = data.get("agent_consensus", {}).get("news", "NEUTRAL")
            data["summary"] = (
                f"The Investment Committee evaluated evidence for {sym}. Technical indicators reflect a {tech_c} outlook, "
                f"while news sentiment is {news_c}. Taking into account downside risks and market dynamics, "
                f"the consensus recommendation is {decision} with {risk_level} risk."
            )
        else:
            data["summary"] = summary_str[:800]

        data["agent"] = "committee"
        return True, None

    def generate_fallback_synthesis(
        self,
        market_snapshot: Dict[str, Any],
        technical_report: Dict[str, Any],
        fundamental_report: Dict[str, Any],
        news_report: Dict[str, Any],
        risk_report: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Deterministic, rule-based committee synthesis fallback when all LLM calls time out or fail.
        Guarantees that a complete, explainable committee verdict is always produced.
        """
        symbol = market_snapshot.get("symbol", "N/A")
        company = market_snapshot.get("company_name", symbol)
        asset_type = market_snapshot.get("asset_type", "EQUITY")

        tech_outlook = technical_report.get("outlook", "NEUTRAL").upper()
        fund_rating = fundamental_report.get("business_quality", {}).get("rating", "NOT_APPLICABLE").upper()
        news_sentiment = news_report.get("overall_sentiment", "NEUTRAL").upper()
        risk_level = risk_report.get("risk_level", "MEDIUM").upper()

        # Decision scoring
        score = 0
        if tech_outlook == "BULLISH":
            score += 2
        elif tech_outlook == "BEARISH":
            score -= 2

        if news_sentiment in ("POSITIVE", "BULLISH"):
            score += 1
        elif news_sentiment in ("NEGATIVE", "BEARISH"):
            score -= 1

        if fund_rating in ("EXCELLENT", "STRONG", "GOOD"):
            score += 2
        elif fund_rating in ("POOR", "WEAK", "DISTRESSED"):
            score -= 2

        if score >= 3 and risk_level != "HIGH":
            decision = "BUY"
            confidence = 0.76
        elif score <= -2 or risk_level == "EXTREME":
            decision = "SELL"
            confidence = 0.72
        else:
            decision = "HOLD"
            confidence = 0.70

        # Construct comprehensive summary
        if asset_type in ("INDEX_ETF", "COMMODITY_ETF"):
            fund_clause = "As an index ETF / composite vehicle, traditional single-company ratios are not applicable."
        elif fund_rating != "NOT_APPLICABLE":
            fund_clause = f"Fundamental evaluation reflects a '{fund_rating}' quality profile."
        else:
            fund_clause = "Fundamental metrics are evaluated on broader market dynamics."

        summary = (
            f"The Investment Committee conducted a synthesized review of {company} ({symbol}). "
            f"Technical signals indicate a '{tech_outlook}' trajectory, while market news sentiment is '{news_sentiment}'. "
            f"{fund_clause} With an overall downside risk assessed as '{risk_level}', "
            f"the Committee establishes a '{decision}' stance with disciplined risk management."
        )

        bull_case = []
        if tech_outlook == "BULLISH":
            bull_case.append(f"Technical momentum for {symbol} is in a supportive uptrend.")
        if news_sentiment in ("POSITIVE", "BULLISH"):
            bull_case.append(f"Current news flow exhibits positive sentiment catalysts.")
        if not bull_case:
            bull_case.append(f"Resilient institutional interest and core asset stability.")

        bear_case = []
        if tech_outlook == "BEARISH":
            bear_case.append(f"Technical price structure is facing downward pressure or resistance.")
        if risk_level in ("MEDIUM", "HIGH", "EXTREME"):
            bear_case.append(f"Downside volatility risk and macro sensitivities present near-term headwinds.")
        if not bear_case:
            bear_case.append(f"Potential multiple compression if market liquidity tightens.")

        key_reasons = [
            f"Consensus weight between technical momentum ({tech_outlook}) and sentiment ({news_sentiment}).",
            f"Risk profile ({risk_level}) suggests {decision.lower()} allocation strategy is optimal at current valuation."
        ]

        major_risks = [
            f"Systemic market risk and macroeconomic shift in interest rate expectations.",
            f"Breaching key technical support levels on heightened trading volume."
        ]

        invalidation_conditions = [
            f"Daily closing price breaking below major moving average support (e.g. 50-day / 200-day SMA).",
            f"Sudden sharp reversal in broader market news sentiment and constituent earnings."
        ]

        return {
            "agent": "committee",
            "status": "SUCCESS",
            "time_horizon": self.TIME_HORIZON,
            "provider_used": "Rule-Based Synthesis (Deterministic Fallback)",
            "symbol": symbol,
            "decision": decision,
            "confidence": confidence,
            "risk_level": risk_level,
            "summary": summary,
            "bull_case": bull_case,
            "bear_case": bear_case,
            "key_reasons": key_reasons,
            "major_risks": major_risks,
            "invalidation_conditions": invalidation_conditions,
            "agent_consensus": {
                "technical": tech_outlook,
                "fundamental": fund_rating,
                "news": news_sentiment,
                "risk": risk_level,
            }
        }

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
        Falls back gracefully to deterministic rule synthesis if LLMs fail.
        """
        # Compact payload to prevent token bloat and rate limits
        payload = {
            "symbol":             market_snapshot.get("symbol"),
            "company_name":       market_snapshot.get("company_name"),
            "asset_type":         market_snapshot.get("asset_type"),
            "currency":           market_snapshot.get("currency"),
            "price":              market_snapshot.get("price", {}).get("current_price"),
            "data_quality":       market_snapshot.get("data_quality", {}).get("overall", "MODERATE"),
            "reports": {
                "technical": {
                    "outlook": technical_report.get("outlook", "NEUTRAL"),
                    "confidence": technical_report.get("confidence", 0.5),
                    "signals": technical_report.get("signals", [])[:3],
                },
                "fundamental": {
                    "rating": fundamental_report.get("business_quality", {}).get("rating", "NOT_APPLICABLE"),
                    "financial_health": fundamental_report.get("financial_health", {}).get("rating", "NOT_APPLICABLE"),
                    "valuation_verdict": fundamental_report.get("valuation", {}).get("valuation_verdict", "NOT_APPLICABLE"),
                },
                "news": {
                    "overall_sentiment": news_report.get("overall_sentiment", "NEUTRAL"),
                    "thesis_impact": news_report.get("thesis_impact", "NEUTRAL"),
                    "key_catalysts": news_report.get("key_catalysts", [])[:3],
                },
                "risk": {
                    "risk_level": risk_report.get("risk_level", "MEDIUM"),
                    "major_risks": risk_report.get("major_risks", [])[:2],
                    "contradictions": risk_report.get("contradictions", [])[:2],
                },
            },
        }

        user_content = f"INVESTMENT COMMITTEE DOSSIER:\n{json.dumps(payload, indent=2)}\n\nPlease deliberate, reconcile time horizons, evaluate evidence quality, and issue the final investment decision. Return valid JSON."

        report = await self.execute_with_validation(
            session=session,
            system_prompt=COMMITTEE_SYSTEM_PROMPT,
            user_content=user_content,
            validator_func=self.validate_report,
            analysis_id=analysis_id,
        )

        if report.get("status") == "SUCCESS" and report.get("summary"):
            return report

        # Trigger deterministic fallback synthesis if LLM failed
        print(f"  🛡️ [{analysis_id}] [committee] LLM call unavailable — generating deterministic rule-based synthesis.")
        return self.generate_fallback_synthesis(
            market_snapshot=market_snapshot,
            technical_report=technical_report,
            fundamental_report=fundamental_report,
            news_report=news_report,
            risk_report=risk_report,
        )
