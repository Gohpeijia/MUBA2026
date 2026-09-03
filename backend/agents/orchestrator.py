# agents/orchestrator.py
#
# Multi-Agent Workflow Orchestrator
#
# Coordinates the evidence-based investment analysis pipeline:
#   1. Collects Yahoo Finance + Finnhub data
#   2. Builds a canonical normalized investment snapshot
#   3. Runs quantitative screening
#   4. Runs Technical, Fundamental, and News agents in parallel
#   5. Runs Adversarial Risk Agent
#   6. Runs Chief Investment Committee Agent
#   7. Assembles complete analysis response
#
# Provides both async analyze_stock() and synchronous analyze_stock_sync().

import time
import uuid
import asyncio
import aiohttp
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from services.data_service import collect_market_data

from investment.snapshot import build_canonical_snapshot
from investment.screener import screen_asset

from agents.technical_agent import TechnicalAgent
from agents.fundamental_agent import FundamentalAgent
from agents.news_agent import NewsAgent
from agents.risk_agent import RiskAgent
from agents.committee_agent import CommitteeAgent


class MultiAgentOrchestrator:
    """
    Workflow coordinator for Amanah Investment Intelligence.

    The orchestrator creates one canonical factual snapshot and passes
    that same snapshot to every agent.
    """

    def __init__(self):
        self.technical_agent = TechnicalAgent()
        self.fundamental_agent = FundamentalAgent()
        self.news_agent = NewsAgent()
        self.risk_agent = RiskAgent()
        self.committee_agent = CommitteeAgent()

        print(
            "🧠 [Orchestrator] Amanah Multi-Agent Investment "
            "Intelligence Engine initialized."
        )

    async def analyze_stock(
        self,
        symbol: str,
        user_question: Optional[str] = None,
        bypass_cache: bool = False,
        quantitative_screen: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        start_time = time.time()

        analysis_id = uuid.uuid4().hex[:8]

        now_iso = datetime.now(
            timezone.utc
        ).isoformat()

        print(
            f"\n🚀 [Orchestrator] [{analysis_id}] "
            f"Initiating Multi-Agent Analysis for '{symbol}'..."
        )

        # =====================================================
        # 1. Collect provider data
        # =====================================================

        raw_market_snapshot = collect_market_data(
            symbol,
            bypass_cache=bypass_cache,
        )

        # =====================================================
        # 2. Build canonical snapshot
        # =====================================================

        market_snapshot = build_canonical_snapshot(
            raw_market_snapshot
        )

        resolved_sym = market_snapshot["symbol"]

        company_name = market_snapshot["company_name"]

        data_quality = market_snapshot["data_quality"]

        print(
            f"  📊 [{analysis_id}] Canonical snapshot ready for "
            f"{resolved_sym} ({company_name}) | "
            f"Data Quality: {data_quality.get('overall')}"
        )

                # =====================================================
        # 3. Quantitative screening
        #
        # Reuse an existing screening result when supplied
        # by the Opportunity Engine. Otherwise run screening
        # normally for direct analysis requests.
        # =====================================================

        if quantitative_screen is not None:
            screening_result = quantitative_screen

            print(
                f"  ♻️ [{analysis_id}] Reusing existing "
                f"quantitative screen: "
                f"{screening_result.get('screening_signal')} "
                f"score={screening_result.get('score')}"
            )

        else:
            try:
                screening_result = screen_asset(
                    resolved_sym
                )
            except Exception as exc:
                print(
                    f"  ⚠️ [{analysis_id}] Quantitative screening "
                    f"failed: {exc}"
                )

                screening_result = {
                    "symbol": resolved_sym,
                    "status": "FAILED",
                    "score": None,
                    "screening_signal": "UNAVAILABLE",
                    "component_scores": {},
                    "signals": {},
                }

            print(
                f"  📈 [{analysis_id}] Quantitative screen: "
                f"{screening_result.get('screening_signal')} "
                f"score={screening_result.get('score')}"
            )

        # =====================================================
        # 4. Parallel specialist agents
        # =====================================================

        providers_used = set()

        agents_completed = []
        agents_failed = []

        timeout = aiohttp.ClientTimeout(
            total=50
        )

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            print(
                f"  📡 [{analysis_id}] Concurrently executing "
                f"Technical, Fundamental, and News agents..."
            )

            specialist_tasks = [
                asyncio.create_task(
                    self.technical_agent.run(
                        session,
                        market_snapshot,
                        analysis_id,
                        screening_result,
                    )
                ),
                asyncio.create_task(
                    self.fundamental_agent.run(
                        session,
                        market_snapshot,
                        analysis_id,
                        screening_result,
                    )
                ),
                asyncio.create_task(
                    self.news_agent.run(
                        session,
                        market_snapshot,
                        analysis_id,
                        screening_result,
                    )
                ),
            ]

            (
                tech_report,
                fund_report,
                news_report,
            ) = await asyncio.gather(
                *specialist_tasks
            )

            for name, report in [
                ("technical", tech_report),
                ("fundamental", fund_report),
                ("news", news_report),
            ]:

                if report.get("status") == "SUCCESS":
                    agents_completed.append(name)

                    provider = report.get(
                        "provider_used"
                    )

                    if provider:
                        providers_used.add(provider)

                else:
                    agents_failed.append(name)

            # =================================================
            # 5. Risk Agent
            # =================================================

            print(
                f"  ⚔️ [{analysis_id}] Executing Risk / "
                f"Devil's Advocate Agent..."
            )

            risk_report = await self.risk_agent.run(
                session=session,
                market_snapshot=market_snapshot,
                technical_report=tech_report,
                fundamental_report=fund_report,
                news_report=news_report,
                screening_result=screening_result,
                analysis_id=analysis_id,
            )

            if risk_report.get("status") == "SUCCESS":
                agents_completed.append("risk")

                provider = risk_report.get(
                    "provider_used"
                )

                if provider:
                    providers_used.add(provider)

            else:
                agents_failed.append("risk")

            # =================================================
            # 6. Committee
            # =================================================

            print(
                f"  🏛️ [{analysis_id}] Executing "
                f"Investment Committee Synthesis..."
            )

            committee_report = await self.committee_agent.run(
                session=session,
                market_snapshot=market_snapshot,
                technical_report=tech_report,
                fundamental_report=fund_report,
                news_report=news_report,
                risk_report=risk_report,
                screening_result=screening_result,
                analysis_id=analysis_id,
            )

            if committee_report.get("status") == "SUCCESS":
                agents_completed.append("committee")

                provider = committee_report.get(
                    "provider_used"
                )

                if provider:
                    providers_used.add(provider)

            else:
                agents_failed.append("committee")

        # =====================================================
        # 7. Final metadata
        # =====================================================

        duration_ms = round(
            (time.time() - start_time) * 1000,
            1,
        )

        decision = committee_report.get(
            "decision",
            "HOLD",
        )

        confidence = committee_report.get(
            "confidence",
            0,
        )

        decision_source = committee_report.get(
            "decision_source",
            "UNKNOWN",
        )
        
        fallback_used = committee_report.get(
            "fallback_used",
            False,
        )

        print(
            f"✅ [Orchestrator] [{analysis_id}] "
            f"Analysis finished in {duration_ms}ms | "
            f"Decision: {decision} @ "
            f"{int(confidence * 100)}% | "
            f"Source: {decision_source}"
        )

        # =====================================================
        # 8. Assemble final payload
        # =====================================================

        final_payload = {
            "analysis_id": analysis_id,

            "symbol": resolved_sym,

            "company_name": company_name,

            "asset_type": market_snapshot.get(
                "asset_type",
                "EQUITY",
            ),

            "currency": market_snapshot.get(
                "currency",
                "USD",
            ),

            "current_price": market_snapshot.get(
                "price",
                {},
            ).get("current_price"),

            "change_1d_pct": market_snapshot.get(
                "price",
                {},
            ).get("change_1d_pct"),

            "chart_data": market_snapshot.get(
                "chart_data",
                [],
            ),

            "user_question": user_question,

            "decision": decision,
            
            "decision_source": decision_source,
            
            "fallback_used": fallback_used,

            "confidence": confidence,

            "risk_level": committee_report.get(
                "risk_level",
                "MEDIUM",
            ),

            "summary": committee_report.get(
                "summary",
                "",
            ),

            "bull_case": committee_report.get(
                "bull_case",
                [],
            ),

            "bear_case": committee_report.get(
                "bear_case",
                [],
            ),

            "key_reasons": committee_report.get(
                "key_reasons",
                [],
            ),

            "major_risks": committee_report.get(
                "major_risks",
                [],
            ),

            "invalidation_conditions": committee_report.get(
                "invalidation_conditions",
                [],
            ),

            "agent_consensus": committee_report.get(
                "agent_consensus",
                {
                    "technical": tech_report.get(
                        "outlook",
                        "NEUTRAL",
                    ),
                    "fundamental": fund_report.get(
                        "business_quality",
                        {},
                    ).get(
                        "rating",
                        "NOT_APPLICABLE",
                    ),
                    "news": news_report.get(
                        "overall_sentiment",
                        "NEUTRAL",
                    ),
                    "risk": risk_report.get(
                        "risk_level",
                        "MEDIUM",
                    ),
                },
            ),

            "agents": {
                "technical": tech_report,
                "fundamental": fund_report,
                "news": news_report,
                "risk": risk_report,
            },

            # Quantitative screening is useful to the frontend
            # and opportunity engine without exposing raw provider data.
            "screening": screening_result,

            "data_quality": data_quality,

            "data_freshness": market_snapshot.get(
                "data_freshness",
                {},
            ),

            "analysis_metadata": {
                "analysis_id": analysis_id,

                "generated_at": now_iso,

                "data_timestamp": market_snapshot.get(
                    "data_freshness",
                    {},
                ).get(
                    "data_timestamp",
                    now_iso,
                ),

                "providers_used": list(
                    providers_used
                ),

                "agents_completed": agents_completed,

                "agents_failed": agents_failed,

                "duration_ms": duration_ms,

                "quantitative_screen_score":
                    screening_result.get("score"),
            },

            "disclaimer": (
                "AI-generated investment analysis for "
                "informational purposes only. It is not "
                "financial advice and does not guarantee "
                "future performance."
            ),
        }

        return final_payload

    def analyze_stock_sync(
        self,
        symbol: str,
        user_question: Optional[str] = None,
        quantitative_screen: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        loop = asyncio.new_event_loop()

        asyncio.set_event_loop(loop)

        try:
            return loop.run_until_complete(
                self.analyze_stock(
                    symbol,
                    user_question,
                    quantitative_screen=quantitative_screen,
                )
            )
        finally:
            loop.close()


# Backward-compatible alias
SwarmOrchestrator = MultiAgentOrchestrator