ALERT_ONLY_MODE = "Alert me only, I act manually"
CONFIRMATION_MODE = "Suggest actions, I confirm each one"
AUTOMATED_MODE = "Fully automated recommendations"
MANUAL_MODE = "No, I will hedge manually"

AUTO_HEDGING_TO_EXECUTION_MODE = {
    "Yes, fully autonomous hedging": AUTOMATED_MODE,
    "Yes, but confirm before executing on-chain": CONFIRMATION_MODE,
    "No, I will hedge manually": MANUAL_MODE,
    "fully_autonomous": AUTOMATED_MODE,
    "confirmation_required": CONFIRMATION_MODE,
    "manual": MANUAL_MODE,
}

VALID_EXECUTION_MODES = {
    ALERT_ONLY_MODE,
    CONFIRMATION_MODE,
    AUTOMATED_MODE,
    MANUAL_MODE,
}


def get_execution_mode(preferences: dict) -> str:
    """Return the latest server-side mode from the user's saved preferences."""
    if not isinstance(preferences, dict):
        return CONFIRMATION_MODE

    auto_mode = preferences.get("opportunityAutoActionMode")
    if auto_mode in AUTO_HEDGING_TO_EXECUTION_MODE:
        return AUTO_HEDGING_TO_EXECUTION_MODE[auto_mode]

    hedging_mode = preferences.get("autoHedgingAgent")
    if hedging_mode in AUTO_HEDGING_TO_EXECUTION_MODE:
        return AUTO_HEDGING_TO_EXECUTION_MODE[hedging_mode]

    copilot_mode = preferences.get("riskCopilotMode")
    if copilot_mode in VALID_EXECUTION_MODES:
        return copilot_mode

    if preferences.get("confirmation_required") is False:
        return AUTOMATED_MODE
    if preferences.get("confirmation_required") is True:
        return CONFIRMATION_MODE

    return CONFIRMATION_MODE