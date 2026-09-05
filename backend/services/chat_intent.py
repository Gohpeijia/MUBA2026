"""Conservative chat intent: recommendations are never execution consent."""
import re


def explicit_trade_action(message: str) -> str | None:
    text = str(message or '').strip().lower().replace('’', "'")
    # Questions, conditions, negation and quoted examples require discussion.
    if re.search(r"[?\"“”]|\b(should|whether|if|unless|when|why|how|check|analy[sz]e|explain|compare|consider|maybe|might|don't|dont|do not|not|never|avoid|stop|cancel|without)\b", text):
        return None
    actions = set(re.findall(r'\b(buy|purchase|sell|dispose)\b', text))
    if actions & {'buy', 'purchase'} and actions & {'sell', 'dispose'}:
        return None
    # Only a direct command, optionally preceded by a request phrase, qualifies.
    match = re.fullmatch(
        r"(?:please\s+)?(?:(?:i (?:want|would like) to|i'd like to|can you|could you|help me)\s+)?"
        r"(?:please\s+)?(buy|purchase|sell|dispose of)\s+([a-z0-9.$^\-]+(?:\s+[a-z0-9.$^\-]+)*)(?:[.!])?",
        text,
    )
    if not match:
        return None
    # Do not execute hypothetical, future, or reported instructions.
    if re.search(r'\b(tomorrow|later|example|said|says|told|before|after|or|and|thinking|planning)\b', match[2]):
        return None
    return 'BUY' if match[1] in ('buy', 'purchase') else 'SELL'
