ALERT_ONLY_MODE = "Alert me only, I act manually"
CONFIRMATION_MODE = "Suggest actions, I confirm each one"
AUTOMATED_MODE = "Fully automated recommendations"

VALID_EXECUTION_MODES = {
    ALERT_ONLY_MODE,
    CONFIRMATION_MODE,
    AUTOMATED_MODE,
}


def get_execution_mode(preferences: dict) -> str:
    """Return the server-side execution mode for a user's preferences."""
    if not isinstance(preferences, dict):
        return CONFIRMATION_MODE

    mode = preferences.get("riskCopilotMode")
    if mode in VALID_EXECUTION_MODES:
        return mode

    # Temporary compatibility with older preference documents.
    if preferences.get("confirmation_required") is False:
        return AUTOMATED_MODE
    if preferences.get("confirmation_required") is True:
        return CONFIRMATION_MODE

    return CONFIRMATION_MODE