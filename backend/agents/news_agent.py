# agents/news_agent.py
#
# Financial News Intelligence Agent
# Time Horizon: SHORT_MEDIUM_TERM
#
# Evaluates curated Finnhub news flow, conflicting narratives, relevance, and material thesis impact.
# Never assumes positive headlines automatically guarantee stock appreciation.

import json
import aiohttp
from typing import Dict, Any, Tuple, Optional
from agents.base_agent import BaseAgent


NEWS_SYSTEM_PROMPT = """You are the Financial News Intelligence Agent.

Analyze ONLY the supplied recent news articles.

Time Horizon: SHORT_MEDIUM_TERM

IMPORTANT DATA RULES:

1. Use ONLY articles supplied in the dossier.
2. Never invent news, events, companies, earnings, regulations, or catalysts.
3. Do not use outside knowledge.
4. If article_count is 0, set:
   - overall_sentiment = "UNAVAILABLE"
   - thesis_impact = "NEUTRAL"
   - confidence = 0.0
   - key_events = []
5. Absence of news must NOT be interpreted as positive or negative evidence.
6. Do not create hypothetical headlines.
7. Every event must correspond to a supplied article.
8. Separate reported facts from interpretation.
9. Return ONLY valid JSON.

Analyze:
- Sentiment
- Financial relevance
- Impact
- Time horizon
- Conflicting narratives
- Thesis impact

Required JSON Schema:
{
  "agent": "news",
  "time_horizon": "SHORT_MEDIUM_TERM",
  "overall_sentiment": "POSITIVE",
  "confidence": 0.73,
  "key_events": [],
  "bullish_narrative": "",
  "bearish_narrative": "",
  "thesis_impact": "MODERATELY_POSITIVE"
}

Allowed overall_sentiment:
"POSITIVE", "NEGATIVE", "NEUTRAL", "UNAVAILABLE"

Allowed thesis_impact:
"STRONGLY_POSITIVE",
"MODERATELY_POSITIVE",
"NEUTRAL",
"MODERATELY_NEGATIVE",
"STRONGLY_NEGATIVE"

confidence:
Float between 0.0 and 1.0.
"""


class NewsAgent(BaseAgent):
    AGENT_ID = "news"
    TIME_HORIZON = "SHORT_MEDIUM_TERM"
    TEMPERATURE = 0.2

    @staticmethod
    def validate_report(data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        if not isinstance(data, dict):
            return False, "Output must be a JSON object"

        sentiment = str(data.get("overall_sentiment", "NEUTRAL")).upper()
        if sentiment not in ("POSITIVE", "NEGATIVE", "NEUTRAL", "UNAVAILABLE"):
            sentiment = "NEUTRAL"
        data["overall_sentiment"] = sentiment

        thesis_impact = str(data.get("thesis_impact", "NEUTRAL")).upper()
        valid_impacts = ("STRONGLY_POSITIVE", "MODERATELY_POSITIVE", "NEUTRAL", "MODERATELY_NEGATIVE", "STRONGLY_NEGATIVE")
        if thesis_impact not in valid_impacts:
            thesis_impact = "NEUTRAL"
        data["thesis_impact"] = thesis_impact

        conf = data.get("confidence", 0.5)
        try:
            conf_val = float(conf)
            if conf_val > 1.0:
                conf_val = conf_val / 100.0
            data["confidence"] = round(max(0.0, min(1.0, conf_val)), 2)
        except Exception:
            data["confidence"] = 0.5

        if not isinstance(data.get("key_events"), list):
            data["key_events"] = []

        data["bullish_narrative"] = str(data.get("bullish_narrative", ""))[:300]
        data["bearish_narrative"] = str(data.get("bearish_narrative", ""))[:300]
        data["agent"] = "news"
        data["time_horizon"] = "SHORT_MEDIUM_TERM"

        return True, None

    def generate_fallback_report(
        self,
        market_snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
    
        symbol = market_snapshot.get(
            "symbol",
            "N/A",
        )
    
        news_items = market_snapshot.get(
            "news",
            [],
        )
    
        key_events = []
    
        for item in news_items[:4]:
        
            headline = item.get(
                "headline",
                "",
            )
    
            summary = item.get(
                "summary",
                "",
            )
    
            if not headline:
                continue
            
            key_events.append({
                "headline": headline[:120],
                "sentiment": "NEUTRAL",
                "impact": "MEDIUM",
                "horizon": "SHORT_TERM",
                "reason": (
                    summary[:150]
                    if summary
                    else "Recent supplied news article."
                ),
            })
    
        if not key_events:
            return {
                "agent": "news",
                "status": "SUCCESS",
                "time_horizon": "SHORT_MEDIUM_TERM",
                "provider_used": (
                    "News Stream Parser "
                    "(Deterministic Fallback)"
                ),
                "overall_sentiment": "UNAVAILABLE",
                "confidence": 0.0,
                "thesis_impact": "NEUTRAL",
                "key_events": [],
                "bullish_narrative": "",
                "bearish_narrative": "",
            }
    
        return {
            "agent": "news",
            "status": "SUCCESS",
            "time_horizon": "SHORT_MEDIUM_TERM",
            "provider_used": (
                "News Stream Parser "
                "(Deterministic Fallback)"
            ),
            "overall_sentiment": "NEUTRAL",
            "confidence": 0.30,
            "thesis_impact": "NEUTRAL",
            "key_events": key_events,
            "bullish_narrative": (
                f"Recent supplied news coverage exists for {symbol}, "
                "but deterministic sentiment classification is neutral."
            ),
            "bearish_narrative": "",
        }

    async def run(
    self,
    session: aiohttp.ClientSession,
    market_snapshot: Dict[str, Any],
    analysis_id: str = "local",
    screening_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Runs News Intelligence Analysis on normalized market snapshot.
        Falls back to news stream parser if LLMs fail.
        """
        news_items = market_snapshot.get("news", [])
        
        payload = {
            "symbol": market_snapshot.get("symbol"),
            "company_name": market_snapshot.get("company_name"),
            "article_count": len(news_items),
            "articles": news_items[:10],
            "data_quality": market_snapshot.get(
                "data_quality",
                {},
            ),
        }       

        user_content = (
    "CANONICAL NEWS DOSSIER:\n"
    f"{json.dumps(payload, indent=2)}\n\n"
    "Analyze only supplied articles. "
    "If article_count is zero, report UNAVAILABLE. "
    "Return valid JSON."
)

        report = await self.execute_with_validation(
            session=session,
            system_prompt=NEWS_SYSTEM_PROMPT,
            user_content=user_content,
            validator_func=self.validate_report,
            analysis_id=analysis_id,
        )

        if report.get("status") == "SUCCESS":
            return report

        print(f"  🛡️ [{analysis_id}] [news] LLM call unavailable — generating deterministic news report.")
        return self.generate_fallback_report(market_snapshot)
