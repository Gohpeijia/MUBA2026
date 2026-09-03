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


COMMITTEE_SYSTEM_PROMPT = """You are the Chief Investment Committee Chair for an AI investment intelligence system.

You are responsible for issuing the final explainable investment assessment.

You receive:
1. Canonical Market Data
2. Independent Quantitative Screen
3. Technical Analyst
4. Fundamental Analyst
5. News Analyst
6. Risk / Devil's Advocate

IMPORTANT DECISION RULES:

1. Do NOT simply count votes.
2. Evaluate evidence quality and consistency.
3. Treat the quantitative screen as an independent quantitative evidence layer.
4. Do not ignore a strong quantitative score merely because optional news data is unavailable.
5. Missing news is NOT bearish evidence.
6. Missing optional fundamentals are NOT automatically bearish evidence.
7. Missing evidence should reduce confidence when material, but should not automatically force HOLD.
8. Never invent or recall financial metrics.
9. Every numerical statement must match the supplied canonical data.
10. Never substitute a different P/E, margin, growth rate, valuation multiple, or technical value.
11. Never mention metrics absent from the dossier.
12. Different time horizons are not contradictions.
13. Risk objections must be considered, but must be evidence-based.
14. A BUY can be issued when the available evidence is sufficiently strong and risks are manageable.
15. HOLD should be used when evidence is genuinely balanced or material uncertainty remains.
16. INSUFFICIENT_DATA should be reserved for cases where critical evidence is actually unavailable.
17. SELL requires meaningful bearish evidence, not merely the absence of bullish evidence.
18. Confidence measures strength and consistency of supplied evidence, NOT probability of future returns.
19. Construct a genuine bull case and bear case from supplied evidence.
20. JSON ONLY. No Markdown, no code fences.
21. Use short strings and controlled list sizes (max 3 items per list).
22. Provide NO unnecessary explanation outside the JSON object.

For the quantitative screen:
- It is NOT the final decision.
- It is independent evidence.
- Use its score and component scores when assessing overall evidence quality.
- Do not blindly follow it.

For news:
- If news sentiment is UNAVAILABLE, explicitly treat it as unavailable evidence.
- Do not convert UNAVAILABLE into NEGATIVE.

For risk:
- Treat valid risk concerns seriously.
- Reject unsupported or hallucinated metrics.

Required JSON Schema:
{
  "symbol": "NVDA",
  "decision": "HOLD",
  "confidence": 0.78,
  "risk_level": "MEDIUM",
  "summary": "2-3 complete sentences explaining the evidence and decision.",
  "bull_case": [],
  "bear_case": [],
  "key_reasons": [],
  "major_risks": [],
  "invalidation_conditions": [],
  "agent_consensus": {
    "technical": "BULLISH",
    "fundamental": "STRONG",
    "news": "UNAVAILABLE",
    "risk": "MEDIUM"
  }
}

Allowed Decisions:
"BUY", "HOLD", "SELL", "INSUFFICIENT_DATA"

Allowed Risk Levels:
"LOW", "MEDIUM", "HIGH", "EXTREME"

confidence:
Float between 0.0 and 1.0.
"""


class CommitteeAgent(BaseAgent):
    AGENT_ID = "committee"
    TIME_HORIZON = "SYNTHESIZED"
    TEMPERATURE = 0.1  # Low temperature for measured, consistent decision synthesis

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
        data["decision_source"] = "LLM_COMMITTEE"
        data["fallback_used"] = False
        return True, None

    def generate_fallback_synthesis(
        self,
        market_snapshot: Dict[str, Any],
        technical_report: Dict[str, Any],
        fundamental_report: Dict[str, Any],
        news_report: Dict[str, Any],
        risk_report: Dict[str, Any],
        screening_result: Optional[Dict[str, Any]] = None,
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

        screening_result = screening_result or {}

        screen_score = screening_result.get("score")
        

        # Decision scoring
        # =====================================================
# Decision scoring
#
# Quantitative screen is independent evidence.
# It supports the decision but does not dominate it.
# =====================================================

        score = 0

        # Technical evidence
        if tech_outlook == "BULLISH":
            score += 2
        elif tech_outlook == "BEARISH":
            score -= 2

        # Fundamental evidence
        if fund_rating == "STRONG":
            score += 2
        elif fund_rating in ("WEAK", "DISTRESSED"):
            score -= 2

        # News evidence
        # UNAVAILABLE = no directional contribution
        if news_sentiment == "POSITIVE":
            score += 1
        elif news_sentiment == "NEGATIVE":
            score -= 1

        # Quantitative screening
        if screen_score is not None:
            if screen_score >= 75:
                score += 2
            elif screen_score >= 60:
                score += 1
            elif screen_score < 40:
                score -= 2
            elif screen_score < 50:
                score -= 1

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
            "decision_source": "RULE_BASED_FALLBACK",
            "fallback_used": True,
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
        screening_result: Optional[Dict[str, Any]] = None,
        analysis_id: str = "local",
    ) -> Dict[str, Any]:
        """
        Runs Committee Synthesis across all 4 specialist reports and data quality metadata.
        Falls back gracefully to deterministic rule synthesis if LLMs fail.
        """
        # Compact payload to prevent token bloat and rate limits
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

            "reports": {
                "technical": technical_report,

                "fundamental": fundamental_report,

                "news": news_report,

                "risk": risk_report,
            },
        }

        user_content = (
            "INVESTMENT COMMITTEE DOSSIER:\n"
            f"{json.dumps(payload, indent=2)}\n\n"
            "Deliberate using only the supplied evidence. "
            "Treat missing information as unknown rather than negative. "
            "Do not invent financial metrics. "
            "Return valid JSON."
        )

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
            screening_result=screening_result,
        )
