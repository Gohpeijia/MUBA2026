# agents/orchestrator.py
#
# Multi-Agent Workflow Orchestrator
#
# Coordinates the evidence-based investment analysis pipeline:
#   1. Collects & normalizes Yahoo Finance + Finnhub data (with 120s snapshot cache)
#   2. Runs Technical, Fundamental, and News agents in parallel (asyncio.gather)
#   3. Runs Adversarial Risk / Devil's Advocate Agent
#   4. Runs Chief Investment Committee Agent for final decision
#   5. Assembles complete analysis response with metadata and disclaimer
#
# Provides both async analyze_stock() and synchronous analyze_stock_sync() for Flask safety.

import time
import uuid
import asyncio
import aiohttp
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from services.data_service import collect_market_data
from agents.technical_agent import TechnicalAgent
from agents.fundamental_agent import FundamentalAgent
from agents.news_agent import NewsAgent
from agents.risk_agent import RiskAgent
from agents.committee_agent import CommitteeAgent


class MultiAgentOrchestrator:
    """
    Workflow coordinator for Amanah Investment Intelligence.
    Zero LLM routing overhead — pure asynchronous pipeline execution.
    """

    def __init__(self):
        self.technical_agent   = TechnicalAgent()
        self.fundamental_agent = FundamentalAgent()
        self.news_agent        = NewsAgent()
        self.risk_agent        = RiskAgent()
        self.committee_agent   = CommitteeAgent()
        print("🧠 [Orchestrator] Amanah Multi-Agent Investment Intelligence Engine initialized.")

    async def analyze_stock(
        self,
        symbol: str,
        user_question: Optional[str] = None,
        bypass_cache: bool = False,
    ) -> Dict[str, Any]:
        """
        Main asynchronous analysis entrypoint.
        """
        start_time = time.time()
        analysis_id = uuid.uuid4().hex[:8]
        now_iso = datetime.now(timezone.utc).isoformat()

        print(f"\n🚀 [Orchestrator] [{analysis_id}] Initiating Multi-Agent Analysis for '{symbol}'...")

        # 1. Collect & Normalize Market Data Snapshot
        market_snapshot = collect_market_data(symbol, bypass_cache=bypass_cache)
        resolved_sym = market_snapshot["symbol"]
        company_name = market_snapshot["company_name"]
        data_quality = market_snapshot["data_quality"]

        print(f"  📊 [{analysis_id}] Snapshot ready for {resolved_sym} ({company_name}) | Data Quality: {data_quality['overall']}")

        providers_used = set()
        agents_completed = []
        agents_failed = []

        timeout = aiohttp.ClientTimeout(total=50)
        async with aiohttp.ClientSession(timeout=timeout) as session:

            # 2. Parallel Execution of the 3 Specialists
            print(f"  📡 [{analysis_id}] Concurrently executing Technical, Fundamental, and News agents...")
            specialist_tasks = [
                asyncio.create_task(self.technical_agent.run(session, market_snapshot, analysis_id)),
                asyncio.create_task(self.fundamental_agent.run(session, market_snapshot, analysis_id)),
                asyncio.create_task(self.news_agent.run(session, market_snapshot, analysis_id)),
            ]
            tech_report, fund_report, news_report = await asyncio.gather(*specialist_tasks)

            for name, report in [("technical", tech_report), ("fundamental", fund_report), ("news", news_report)]:
                if report.get("status") == "SUCCESS":
                    agents_completed.append(name)
                    if report.get("provider_used"):
                        providers_used.add(report["provider_used"])
                else:
                    agents_failed.append(name)

            # 3. Adversarial Risk Agent
            print(f"  ⚔️  [{analysis_id}] Executing Risk / Devil's Advocate Agent...")
            risk_report = await self.risk_agent.run(
                session=session,
                market_snapshot=market_snapshot,
                technical_report=tech_report,
                fundamental_report=fund_report,
                news_report=news_report,
                analysis_id=analysis_id,
            )

            if risk_report.get("status") == "SUCCESS":
                agents_completed.append("risk")
                if risk_report.get("provider_used"):
                    providers_used.add(risk_report["provider_used"])
            else:
                agents_failed.append("risk")

            # 4. Investment Committee Agent
            print(f"  🏛️  [{analysis_id}] Executing Investment Committee Synthesis...")
            committee_report = await self.committee_agent.run(
                session=session,
                market_snapshot=market_snapshot,
                technical_report=tech_report,
                fundamental_report=fund_report,
                news_report=news_report,
                risk_report=risk_report,
                analysis_id=analysis_id,
            )

            if committee_report.get("status") == "SUCCESS":
                agents_completed.append("committee")
                if committee_report.get("provider_used"):
                    providers_used.add(committee_report["provider_used"])
            else:
                agents_failed.append("committee")

        duration_ms = round((time.time() - start_time) * 1000, 1)
        print(f"✅ [Orchestrator] [{analysis_id}] Analysis finished in {duration_ms}ms | Decision: {committee_report.get('decision')} @ {int(committee_report.get('confidence', 0) * 100)}%")

        # 5. Assemble Final Response Payload
        final_payload = {
            "analysis_id":             analysis_id,
            "symbol":                  resolved_sym,
            "company_name":            company_name,
            "asset_type":              market_snapshot.get("asset_type", "EQUITY"),
            "currency":                market_snapshot.get("currency", "USD"),
            "current_price":           market_snapshot.get("price", {}).get("current_price"),
            "change_1d_pct":           market_snapshot.get("price", {}).get("change_1d_pct"),
            "chart_data":              market_snapshot.get("chart_data", []),
            "user_question":           user_question,
            "decision":                committee_report.get("decision", "HOLD"),
            "confidence":              committee_report.get("confidence", 0.5),
            "risk_level":              committee_report.get("risk_level", "MEDIUM"),
            "summary":                 committee_report.get("summary", ""),
            "bull_case":               committee_report.get("bull_case", []),
            "bear_case":               committee_report.get("bear_case", []),
            "key_reasons":             committee_report.get("key_reasons", []),
            "major_risks":             committee_report.get("major_risks", []),
            "invalidation_conditions": committee_report.get("invalidation_conditions", []),
            "agent_consensus":         committee_report.get("agent_consensus", {
                "technical":   tech_report.get("outlook", "NEUTRAL"),
                "fundamental": fund_report.get("business_quality", {}).get("rating", "NOT_APPLICABLE"),
                "news":        news_report.get("overall_sentiment", "NEUTRAL"),
                "risk":        risk_report.get("risk_level", "MEDIUM"),
            }),
            "agents": {
                "technical":   tech_report,
                "fundamental": fund_report,
                "news":        news_report,
                "risk":        risk_report,
            },
            "data_quality":   data_quality,
            "data_freshness": market_snapshot.get("data_freshness", {}),
            "analysis_metadata": {
                "analysis_id":      analysis_id,
                "generated_at":     now_iso,
                "data_timestamp":   market_snapshot.get("data_freshness", {}).get("data_timestamp", now_iso),
                "providers_used":   list(providers_used),
                "agents_completed": agents_completed,
                "agents_failed":    agents_failed,
                "duration_ms":      duration_ms,
            },
            "disclaimer": "AI-generated investment analysis for informational purposes only. It is not financial advice and does not guarantee future performance.",
        }

        return final_payload

    def analyze_stock_sync(self, symbol: str, user_question: Optional[str] = None) -> Dict[str, Any]:
        """
        Synchronous wrapper safe for Flask WSGI worker execution.
        Creates a dedicated event loop per request to prevent event loop collisions.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.analyze_stock(symbol, user_question))
        finally:
            loop.close()


# Backward-compatible alias for existing imports
SwarmOrchestrator = MultiAgentOrchestrator
