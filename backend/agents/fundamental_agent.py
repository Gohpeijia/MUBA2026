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

IMPORTANT DATA RULES:

1. Use ONLY financial figures explicitly supplied in the CANONICAL FUNDAMENTAL SNAPSHOT.
2. Never recall financial figures from your pretrained knowledge.
3. Never estimate or substitute a different P/E, margin, ROE, debt ratio, revenue, or growth rate.
4. If a metric is null or unavailable, mark it UNKNOWN.
5. Missing data is NOT negative evidence.
6. Do not use excluded or suspicious provider fields.
7. Never mention a financial metric that is not present in the canonical snapshot.
8. Do not claim that a ratio is above/below an industry average unless an explicit industry benchmark is supplied.
9. Do NOT make the final BUY/HOLD/SELL decision.
10. Every important numerical claim must match the supplied value exactly.

Evaluate:
- Revenue
- Revenue growth
- Earnings growth
- EPS
- Profit margin
- ROE
- Debt-to-equity
- Free cash flow
- P/E
- Market capitalization
- Valuation condition

For crypto:
- Traditional corporate fundamentals are NOT_APPLICABLE.

Return ONLY valid JSON.

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
  "bullish_factors": [],
  "bearish_factors": [],
  "evidence": [
    {
      "claim": "Profit margin is 63.66%",
      "field": "profit_margin_pct",
      "value": 63.66
    }
  ]
}

Allowed Ratings:
business_quality:
"STRONG", "MODERATE", "WEAK", "NOT_APPLICABLE"

financial_health:
"HEALTHY", "MODERATE", "DISTRESSED", "NOT_APPLICABLE"

valuation:
"UNDERVALUED", "FAIR", "OVERVALUED", "NOT_APPLICABLE"

confidence:
Float between 0.0 and 1.0.
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

    def generate_fallback_report(self, market_snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """
        Deterministic, programmatic fundamental evaluation fallback.
        """
        symbol = market_snapshot.get("symbol", "N/A")
        asset_type = market_snapshot.get("asset_type", "EQUITY")
        funds = market_snapshot.get("fundamentals", {})

        if asset_type in ("INDEX_ETF", "COMMODITY_ETF", "CRYPTO"):
            return {
                "agent": "fundamental",
                "status": "SUCCESS",
                "time_horizon": "MEDIUM_LONG_TERM",
                "provider_used": "Programmatic Fundamentals Engine (ETF/Basket)",
                "business_quality": {
                    "rating": "NOT_APPLICABLE",
                    "confidence": 0.85,
                    "notes": f"{symbol} is an ETF/Index composite vehicle; corporate financial statement metrics are not applicable."
                },
                "financial_health": {
                    "rating": "NOT_APPLICABLE",
                    "confidence": 0.85,
                    "notes": "Balance sheet debt metrics are not applicable to index basket assets."
                },
                "valuation": {
                    "rating": "NOT_APPLICABLE",
                    "confidence": 0.80,
                    "notes": "Valuation is tied to weighted index constituent performance."
                },
                "bullish_factors": [
                    f"Broad multi-sector exposure across top market constituents.",
                    f"Inherent risk mitigation through index diversification."
                ],
                "bearish_factors": [
                    f"Aggregate index valuation is sensitive to broader macroeconomic interest rate cycles."
                ],
                "evidence": [
                    {"claim": f"Asset is classified as {asset_type}", "field": "asset_type", "value": asset_type}
                ]
            }

        # Single equity evaluation
        pe = funds.get("pe_ratio")
        margin_pct = funds.get("profit_margin_pct")
        de = funds.get("debt_to_equity")

        bullish_factors = []
        bearish_factors = []

        if margin_pct is not None and margin_pct > 15:
            bullish_factors.append(
                f"Healthy net profit margin at {margin_pct:.2f}%."
            )
            bq_rating = "STRONG"

        elif margin_pct is not None and margin_pct < 5:
            bearish_factors.append(
                f"Compressed net profit margin at {margin_pct:.2f}%."
            )
            bq_rating = "WEAK"

        elif margin_pct is not None:
            bq_rating = "MODERATE"

        else:
            bq_rating = "NOT_APPLICABLE"

        if de is not None and de < 1.0:
            bullish_factors.append(f"Conservative leverage with Debt-to-Equity of {de:.2f}.")
            fh_rating = "HEALTHY"
        elif de is not None and de > 2.0:
            bearish_factors.append(f"Elevated financial leverage with Debt-to-Equity of {de:.2f}.")
            fh_rating = "DISTRESSED"
        else:
            fh_rating = "MODERATE"

        if pe is not None and 0 < pe < 18:
            bullish_factors.append(f"Attractive valuation with trailing P/E of {pe:.1f}x.")
            val_rating = "UNDERVALUED"
        elif pe is not None and pe > 35:
            bearish_factors.append(f"Premium valuation with trailing P/E of {pe:.1f}x.")
            val_rating = "OVERVALUED"
        else:
            val_rating = "FAIR"

        return {
            "agent": "fundamental",
            "status": "SUCCESS",
            "time_horizon": "MEDIUM_LONG_TERM",
            "provider_used": "Programmatic Fundamentals Engine (Deterministic Fallback)",
            "business_quality": {"rating": bq_rating, "confidence": 0.75 if margin_pct is not None else 0.45, "notes": f"Evaluated based on profitability margins."},
            "financial_health": {"rating": fh_rating, "confidence": 0.75, "notes": f"Evaluated based on balance sheet leverage."},
            "valuation": {"rating": val_rating, "confidence": 0.75, "notes": f"Evaluated based on P/E multiples."},
            "bullish_factors": bullish_factors if bullish_factors else ["Financial operations maintain baseline stability."],
            "bearish_factors": bearish_factors if bearish_factors else ["Sector competition requires ongoing capital investment."],
            "evidence": [
            {
                "claim": f"Trailing P/E is {pe}",
                "field": "pe_ratio",
                "value": pe,
            },
            {
                "claim": f"Profit margin is {margin_pct}%",
                "field": "profit_margin_pct",
                "value": margin_pct,
            },
            ]       
        }

    async def run(
    self,
    session: aiohttp.ClientSession,
    market_snapshot: Dict[str, Any],
    analysis_id: str = "local",
    screening_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:

        screening_result = screening_result or {}

        asset_type = market_snapshot.get(
            "asset_type"
        )

        payload = {
            "canonical_fundamentals": {
                "symbol": market_snapshot.get("symbol"),
                "company_name": market_snapshot.get("company_name"),
                "asset_type": asset_type,
                "currency": market_snapshot.get("currency"),
                "fundamentals": market_snapshot.get(
                    "fundamentals",
                    {},
                ),
                "data_quality": market_snapshot.get(
                    "data_quality",
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
            },
        }

        user_content = (
            "CANONICAL FUNDAMENTAL DOSSIER:\n"
            f"{json.dumps(payload, indent=2)}\n\n"
            "Evaluate only the supplied financial evidence. "
            "Return valid JSON."
        )

        report = await self.execute_with_validation(
            session=session,
            system_prompt=FUNDAMENTAL_SYSTEM_PROMPT,
            user_content=user_content,
            validator_func=self.validate_report,
            analysis_id=analysis_id,
        )

        if report.get("status") == "SUCCESS":
            return report

        print(
            f"  🛡️ [{analysis_id}] [fundamental] "
            "LLM call unavailable — generating deterministic "
            "fundamental report."
        )

        return self.generate_fallback_report(
            market_snapshot
        )
