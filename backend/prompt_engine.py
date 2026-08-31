import json

class TradingAdvisorPromptManager:
    """
    Manages prompt generation for the AI Options Copilot & Risk Engine.
    Incorporates user trading survey preferences and real-time Investment Dashboard context
    for defined-risk options trading on Base Mainnet (Thetanuts V4).
    """

    def __init__(self):
        pass

    def get_system_prompt(self, preferences: dict = None, portfolio: dict = None) -> str:
        """
        Generates the system prompt tailored to user survey responses, copilot configuration,
        auto-hedging settings, and portfolio metrics from the Investment Dashboard.
        """
        preferences = preferences or {}
        portfolio = portfolio or {}

        # ── Survey Preferences from Preferences.jsx ──────────────────────────────
        employment_status = preferences.get("employmentStatus", "Not specified")
        monthly_income = preferences.get("monthlyIncome", "Not specified")
        investment_exp = preferences.get("investmentExperience", "Intermediate")
        risk_tolerance = preferences.get("riskTolerance", "Moderate")
        copilot_mode = preferences.get("riskCopilotMode", "Suggest actions, I confirm each one")
        auto_hedging = preferences.get("autoHedgingAgent", "Yes, but confirm before executing on-chain")
        primary_goal = preferences.get("primaryGoal", "Manage risk & automate hedging")

        # ── Investment Dashboard Context from InvestmentDashboard.jsx ───────────
        portfolio_val = portfolio.get("total_value", portfolio.get("marketValue", 0.0))
        realized_pnl = portfolio.get("realizedPnl", 0.0)
        unrealized_pnl = portfolio.get("unrealizedPnl", 0.0)

        system_prompt = f"""
You are an autonomous AI Risk Copilot and Options Trading Advisor operating on Base Mainnet (Chain ID: 8453).
Your purpose is to assist the user with options position analysis, automated risk management, auto-hedging strategies, and trade execution on Thetanuts V4.

=== USER TRADING PROFILE & PREFERENCES ===
- Employment Status: {employment_status}
- Estimated Monthly Income: {monthly_income}
- On-Chain Options Experience: {investment_exp}
- Risk Tolerance Level: {risk_tolerance}
- Risk Copilot Mode: {copilot_mode}
- Auto-Hedging Configuration: {auto_hedging}
- Primary Platform Goal: {primary_goal}

=== INVESTMENT DASHBOARD METRICS ===
- Portfolio Market Value: ${portfolio_val:,.2f}
- Realized P&L: ${realized_pnl:,.2f}
- Unrealized P&L: ${unrealized_pnl:,.2f}

=== PROTOCOL & ON-CHAIN EXECUTION RULES (THETANUTS V4) ===
1. EXECUTION VENUE:
   - Operating Environment: Base Mainnet (chainId 8453).
   - Core Protocol: Thetanuts V4 OptionBook & OptionFactory (Cash-settled options contracts).

2. RISK GATE & POSITION SIZING:
   - Order Collateral: Standard options orders utilize 1 to 3 USDC as collateral per fill.
   - Defined Risk Constraint: Maximum loss is strictly capped upfront to the option premium paid. No margin calls or liquidations.
   - Swarm Signal Gate: Trigger or recommend on-chain executions ONLY if the Swarm consensus confidence is 50% or higher with a clear BUY or SELL action.
   - Hold State: If Swarm confidence is below 50% or consensus is HOLD, do NOT trigger execution. Explain the wait-and-see stance.

3. COPILOT & HEDGING BEHAVIOR:
   - Align all recommendations with the user's selected Risk Copilot Mode ("{copilot_mode}") and Auto-Hedging choice ("{auto_hedging}").
   - Tailor all position sizing and advice to the user's declared risk tolerance ({risk_tolerance}).

=== OUTPUT FORMAT REQUIREMENTS ===
- Provide a concise quantitative analysis of the asset or market request.
- Include a clear Swarm Consensus summary (Action & Confidence %).
- If proposing a trade, explicitly outline parameters matching the execution modal: Action (BUY/SELL), Ticker, Recommended Quantity, Current Market Price, Stop Loss Price (if applicable), and any Risk Gate Constraints.
- Maintain a direct, analytical, and professional tone.
"""
        return system_prompt.strip()

    def format_agent_input(
        self,
        user_input: str = "",
        quantitative_data: dict = None,
        page_context: str = "Unknown",
        structured_consensus: dict = None,
        market_data_block: str = "",
        # Backward-compatibility aliases for legacy parameters:
        input_pengguna: str = None,
        kuantitatif: dict = None,
        konteks_halaman: str = None,
        konsensus_teratur: dict = None,
        blok_data_pasaran: str = None,
    ) -> str:
        """
        Formats user input and market data into a structured prompt payload.
        Supports both English and legacy parameters seamlessly.
        """
        # Resolve aliases
        user_input = input_pengguna if input_pengguna is not None else user_input
        quantitative_data = kuantitatif if kuantitatif is not None else (quantitative_data or {})
        page_context = konteks_halaman if konteks_halaman is not None else page_context
        structured_consensus = konsensus_teratur if konsensus_teratur is not None else structured_consensus
        market_data_block = blok_data_pasaran if blok_data_pasaran is not None else market_data_block

        # Format Swarm Consensus summary
        consensus_str = "No active Swarm consensus available."
        if structured_consensus:
            action = structured_consensus.get("consensus", "HOLD")
            confidence = structured_consensus.get("confidence", 0)
            breakdown = structured_consensus.get("breakdown", {})
            consensus_str = f"Action: {action} | Confidence: {confidence}%\nBreakdown: {json.dumps(breakdown)}"

        prompt = f"""
=== APP CONTEXT ===
Page Context: {page_context}

=== QUANTITATIVE MARKET & RISK DATA ===
{market_data_block if market_data_block else json.dumps(quantitative_data, indent=2)}

=== SWARM CONSENSUS RESULTS ===
{consensus_str}

=== USER REQUEST ===
{user_input}

Please analyze the request using the quantitative market data, risk context, and Swarm consensus provided above. Deliver a clear recommendation or execution plan.
"""
        return prompt.strip()


# Alias for backward compatibility with existing imports in ai_agent.py
ShariahAdvisorPromptManager = TradingAdvisorPromptManager


def bina_dan_format_prompt(
    input_pengguna: str,
    kuantitatif: dict = None,
    konteks_halaman: str = "Unknown",
    konsensus_teratur: dict = None,
    blok_data_pasaran: str = "",
) -> str:
    """
    Legacy wrapper function for backwards compatibility with existing codebase callers.
    """
    manager = TradingAdvisorPromptManager()
    return manager.format_agent_input(
        user_input=input_pengguna,
        quantitative_data=kuantitatif,
        page_context=konteks_halaman,
        structured_consensus=konsensus_teratur,
        market_data_block=blok_data_pasaran,
    )