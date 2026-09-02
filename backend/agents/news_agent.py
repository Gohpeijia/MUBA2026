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
Analyze the supplied recent news articles for the asset.

Time Horizon: SHORT_MEDIUM_TERM

For the relevant articles:
- Determine sentiment (POSITIVE, NEGATIVE, NEUTRAL)
- Determine financial relevance and impact (HIGH, MEDIUM, LOW)
- Identify whether impact is SHORT_TERM or LONG_TERM
- Detect conflicting narratives (e.g. strong earnings vs regulatory headwinds)
- Assess impact on the core investment thesis

Strict Behavioral Rules:
1. Do NOT assume that positive news automatically means the stock will rise.
2. Do NOT invent news or fabricate events not present in the supplied articles.
3. If no articles are supplied, set overall_sentiment to "NEUTRAL" or "UNAVAILABLE" and state that no recent news flow was available.
4. Return ONLY valid JSON matching the exact schema below.

Required JSON Schema:
{
  "agent": "news",
  "time_horizon": "SHORT_MEDIUM_TERM",
  "overall_sentiment": "POSITIVE",
  "confidence": 0.73,
  "key_events": [
    {
      "headline": "Q3 Revenue beats consensus by 8%",
      "sentiment": "POSITIVE",
      "impact": "MEDIUM",
      "horizon": "LONG_TERM",
      "reason": "Core operating division expanded gross margin."
    }
  ],
  "bullish_narrative": "Strong earnings momentum and international market expansion.",
  "bearish_narrative": "Currency volatility and sector-wide margin pressure.",
  "thesis_impact": "MODERATELY_POSITIVE"
}

Allowed Values:
- overall_sentiment: "POSITIVE", "NEGATIVE", "NEUTRAL", "UNAVAILABLE"
- thesis_impact: "STRONGLY_POSITIVE", "MODERATELY_POSITIVE", "NEUTRAL", "MODERATELY_NEGATIVE", "STRONGLY_NEGATIVE"
confidence: Float between 0.0 and 1.0 (evidence strength)
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

    async def run(self, session: aiohttp.ClientSession, market_snapshot: Dict[str, Any], analysis_id: str = "local") -> Dict[str, Any]:
        """
        Runs News Intelligence Analysis on normalized market snapshot.
        """
        news_items = market_snapshot.get("news", [])
        
        payload = {
            "symbol":        market_snapshot.get("symbol"),
            "company_name":  market_snapshot.get("company_name"),
            "article_count": len(news_items),
            "articles":      news_items[:15],
        }

        user_content = f"NEWS STREAM SNAPSHOT:\n{json.dumps(payload, indent=2)}\n\nPlease evaluate recent news flow and thesis impact. Return valid JSON."

        return await self.execute_with_validation(
            session=session,
            system_prompt=NEWS_SYSTEM_PROMPT,
            user_content=user_content,
            validator_func=self.validate_report,
            analysis_id=analysis_id,
        )
