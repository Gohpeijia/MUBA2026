# consensus_engine.py
import math
from typing import Optional


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TEMPORAL STATE — pass this in from your persistence layer (Redis, DB, etc.)
#  Shape: the return value of a previous calculate_swarm_consensus() call,
#  or None on the very first run.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def calculate_swarm_consensus(
    swarm_results: list,
    previous_consensus: Optional[dict] = None,   # ISSUE #5: temporal intelligence
) -> dict:
    """
    Full-fidelity swarm consensus engine.

    Round 2 Fixes (this version):
    - ISSUE #1: Split agreement into market_agreement_score + compliance_agreement_score.
    - ISSUE #2: compliance_confidence = None when no VETO (absence ≠ certainty).
    - ISSUE #3: Three-axis pressure (bullish / bearish / neutral) instead of BUY-only.
    - ISSUE #4: confidence_variance added as a dispersion / instability signal.
    - ISSUE #5: Temporal layer — confidence_delta, trend_direction, sentiment_velocity.
    """

    # ── 1. FILTER FAILURES ───────────────────────────────────────────────────
    valid_results = [r for r in swarm_results if r.get("decision") not in ("ERROR", None)]

    if not valid_results:
        return _empty_result(previous_consensus)

    # ── 2. PARTITION: VETO vs MARKET VOTES ───────────────────────────────────
    # VETO = structural invalidation. It is a separate axis, never a vote.
    veto_events  = [r for r in valid_results if r["decision"] == "VETO"]
    market_votes = [r for r in valid_results if r["decision"] != "VETO"]
    veto_triggered = len(veto_events) > 0

    # ── 3. TALLY WEIGHTED MARKET SCORES ──────────────────────────────────────
    scores = {"BUY": 0.0, "HOLD": 0.0, "SELL": 0.0}
    for res in market_votes:
        if res["decision"] in scores:
            scores[res["decision"]] += res["weight"] * (res["confidence"] / 100.0)

    total_market_score = sum(scores.values())

    # ── 4. MARKET WINNER & CONFIDENCE ────────────────────────────────────────
    if total_market_score == 0:
        market_winner     = "HOLD"
        market_confidence = 0
    else:
        market_winner     = max(scores, key=scores.get)
        market_confidence = int((scores[market_winner] / total_market_score) * 100)

    # ── 5. THREE-AXIS PRESSURE (ISSUE #3) ────────────────────────────────────
    # Replaces single bullish_pressure. Each axis is % of total weighted market score.
    if total_market_score > 0:
        bullish_pressure = round((scores["BUY"]  / total_market_score) * 100, 1)
        bearish_pressure = round((scores["SELL"] / total_market_score) * 100, 1)
        neutral_pressure = round((scores["HOLD"] / total_market_score) * 100, 1)
    else:
        bullish_pressure = bearish_pressure = neutral_pressure = 0.0

    # ── 6. MARKET SENTIMENT LABEL ─────────────────────────────────────────────
    if market_confidence >= 65:
        market_sentiment = f"STRONGLY_{market_winner}"
    elif market_confidence >= 45:
        market_sentiment = f"MILDLY_{market_winner}"
    else:
        market_sentiment = "DIVIDED"

    # ── 7. COMPLIANCE CONFIDENCE (ISSUE #2) ──────────────────────────────────
    # None  → no VETO fired, compliance layer was silent (absence ≠ certainty).
    # 0-100 → VETO fired; value = mean confidence of all VETO agents.
    if veto_triggered:
        veto_scores           = [v["confidence"] for v in veto_events]
        compliance_confidence = int(sum(veto_scores) / len(veto_scores))
    else:
        compliance_confidence = None   # ← explicit: we simply did not reject

    # ── 8. FINAL CONSENSUS ────────────────────────────────────────────────────
    winning_decision = "VETO" if veto_triggered else market_winner

    # ── 9. RISK via DISAGREEMENT RATIO ───────────────────────────────────────
    if total_market_score > 0:
        disagreement_ratio = 1.0 - (scores[market_winner] / total_market_score)
    else:
        disagreement_ratio = 1.0

    if veto_triggered:
        risk_level = "EXTREME"
    elif disagreement_ratio < 0.20:
        risk_level = "LOW"
    elif disagreement_ratio < 0.40:
        risk_level = "MEDIUM"
    elif disagreement_ratio < 0.60:
        risk_level = "HIGH"
    else:
        risk_level = "EXTREME"

    # ── 10. SPLIT AGREEMENT SCORES (ISSUE #1) ────────────────────────────────
    # market_agreement_score  → cohesion among market-vote agents only.
    # compliance_agreement_score → authority weight of VETO events vs all agents.
    #
    # Old bug: a single VETO agent (weight 1.0) measured against ALL agents
    # returned ~20% even when the 4 market agents were 100% aligned on BUY.
    # Now both dimensions are independently legible.

    market_weight_total = sum(r["weight"] for r in market_votes)
    winner_market_weight = sum(
        r["weight"] for r in market_votes if r["decision"] == market_winner
    )
    market_agreement_score = (
        int((winner_market_weight / market_weight_total) * 100)
        if market_weight_total > 0 else 0
    )

    if veto_triggered:
        all_weight_total    = sum(r["weight"] for r in valid_results)
        veto_weight_total   = sum(r["weight"] for r in veto_events)
        compliance_agreement_score = (
            int((veto_weight_total / all_weight_total) * 100)
            if all_weight_total > 0 else 0
        )
    else:
        compliance_agreement_score = None   # mirrors compliance_confidence: None = silent

    # ── 11. CONFIDENCE VARIANCE (ISSUE #4) ───────────────────────────────────
    # High variance = agents are cognitively unstable (e.g. 99 vs 5).
    # This is a strong independent risk signal separate from disagreement_ratio.
    all_confidences = [r["confidence"] for r in valid_results]
    if len(all_confidences) >= 2:
        mean_conf     = sum(all_confidences) / len(all_confidences)
        variance      = sum((c - mean_conf) ** 2 for c in all_confidences) / len(all_confidences)
        conf_std_dev  = round(math.sqrt(variance), 2)

        # Normalised 0-100: std_dev of 50 = maximally unstable
        confidence_variance = round(min((conf_std_dev / 50.0) * 100, 100), 1)
    else:
        conf_std_dev        = 0.0
        confidence_variance = 0.0   # single agent → no spread to measure

    # Elevate risk if swarm is cognitively split even if scores look aligned
    if confidence_variance > 60 and risk_level == "LOW":
        risk_level = "MEDIUM"  # promote: hidden instability
    elif confidence_variance > 80 and risk_level == "MEDIUM":
        risk_level = "HIGH"

    # ── 12. LOUDEST DISSENTER (weight × confidence) ───────────────────────────
    dissenters      = [r for r in valid_results if r["decision"] != winning_decision]
    minority_warning = "Swarm is fully aligned."

    if dissenters:
        loudest = max(dissenters, key=lambda x: x["weight"] * (x["confidence"] / 100.0))
        minority_warning = (
            f"[{loudest['agent']}] dissented ({loudest['decision']}, "
            f"{loudest['confidence']}% confidence): {loudest['reasoning']}"
        )

    # ── 13. CONTRADICTION DETECTION ──────────────────────────────────────────
    BULLISH_CONFLICT_THRESHOLD = 50
    conflict_detected = False
    market_state      = "NORMAL"

    if veto_triggered and bullish_pressure >= BULLISH_CONFLICT_THRESHOLD:
        conflict_detected = True
        market_state      = "ETHICAL_CONFLICT"
    elif veto_triggered:
        market_state      = "ETHICAL_REJECTION"
    elif disagreement_ratio >= 0.5:
        conflict_detected = True
        market_state      = "SPECULATIVE_CONFLICT"

    # ── 14. TEMPORAL INTELLIGENCE (ISSUE #5) ─────────────────────────────────
    # Requires previous_consensus to be passed in from your persistence layer.
    # On first run, all temporal fields are None — that is correct and expected.
    temporal = _calculate_temporal(
        current_consensus   = winning_decision,
        current_confidence  = market_confidence,
        current_sentiment   = market_sentiment,
        previous_consensus  = previous_consensus,
    )

    # ── 15. STRUCTURED RETURN ─────────────────────────────────────────────────
    return {
        # ── Core decision ──────────────────────────────────────────────────
        "consensus":       winning_decision,

        # ── Market layer ───────────────────────────────────────────────────
        "confidence":         market_confidence,      # market-vote strength (0-100)
        "market_sentiment":   market_sentiment,       # STRONGLY_BUY / DIVIDED / etc.

        # ISSUE #3: three-axis pressure
        "bullish_pressure":   bullish_pressure,       # % weighted BUY score
        "bearish_pressure":   bearish_pressure,       # % weighted SELL score
        "neutral_pressure":   neutral_pressure,       # % weighted HOLD score

        # ── Compliance layer ───────────────────────────────────────────────
        # ISSUE #2: None = silent (no rejection), int = VETO certainty
        "compliance_confidence":      compliance_confidence,

        # ── Cohesion ───────────────────────────────────────────────────────
        # ISSUE #1: split so VETO agent weight doesn't distort market cohesion
        "market_agreement_score":     market_agreement_score,
        "compliance_agreement_score": compliance_agreement_score,

        # ── Instability signal ─────────────────────────────────────────────
        # ISSUE #4: 0 = all agents equally certain; 100 = maximally split
        "confidence_variance":  confidence_variance,
        "conf_std_dev":         conf_std_dev,

        # ── Risk ───────────────────────────────────────────────────────────
        "risk_level":           risk_level,           # LOW/MEDIUM/HIGH/EXTREME

        # ── Conflict ──────────────────────────────────────────────────────
        "conflict_detected":    conflict_detected,
        "market_state":         market_state,         # NORMAL / ETHICAL_CONFLICT / etc.

        # ── Dissent ────────────────────────────────────────────────────────
        "minority_warning":     minority_warning,

        # ── Temporal (ISSUE #5) ────────────────────────────────────────────
        # All None on first call; populated once previous_consensus is passed in.
        **temporal,

        # ── Explainability (keep forever) ──────────────────────────────────
        "agent_breakdown":      valid_results,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TEMPORAL HELPER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_SENTIMENT_RANK = {
    "STRONGLY_BUY":   3,
    "MILDLY_BUY":     2,
    "DIVIDED":        1,
    "MILDLY_HOLD":    0,
    "STRONGLY_HOLD":  0,
    "MILDLY_SELL":   -2,
    "STRONGLY_SELL": -3,
}

def _calculate_temporal(
    current_consensus:  str,
    current_confidence: int,
    current_sentiment:  str,
    previous_consensus: Optional[dict],
) -> dict:
    """
    Derives trend_direction, confidence_delta, and sentiment_velocity
    by comparing the current run against the previous stored result.

    Call signature keeps the main function clean.
    Returns a flat dict that is ** unpacked into the final result.
    """
    if previous_consensus is None:
        return {
            "previous_consensus":  None,
            "confidence_delta":    None,   # +/- change since last run
            "trend_direction":     None,   # STRENGTHENING / WEAKENING / REVERSING / STABLE
            "sentiment_velocity":  None,   # numeric rank shift (-6 … +6)
        }

    prev_decision   = previous_consensus.get("consensus")
    prev_confidence = previous_consensus.get("confidence", 0)
    prev_sentiment  = previous_consensus.get("market_sentiment", "DIVIDED")

    # Confidence delta (signed integer, + = growing conviction)
    confidence_delta = current_confidence - prev_confidence

    # Trend direction
    if current_consensus != prev_decision:
        trend_direction = "REVERSING"
    elif confidence_delta > 5:
        trend_direction = "STRENGTHENING"
    elif confidence_delta < -5:
        trend_direction = "WEAKENING"
    else:
        trend_direction = "STABLE"

    # Sentiment velocity: how fast is market mood shifting?
    curr_rank     = _SENTIMENT_RANK.get(current_sentiment, 0)
    prev_rank     = _SENTIMENT_RANK.get(prev_sentiment,    0)
    sent_velocity = curr_rank - prev_rank   # e.g. +2 = moved two notches bullish

    return {
        "previous_consensus":  prev_decision,
        "confidence_delta":    confidence_delta,
        "trend_direction":     trend_direction,
        "sentiment_velocity":  sent_velocity,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  EMPTY / FAILURE RESULT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _empty_result(previous_consensus: Optional[dict]) -> dict:
    """Canonical null result when the entire swarm fails."""
    temporal = _calculate_temporal("HOLD", 0, "DIVIDED", previous_consensus)
    return {
        "consensus":                  "HOLD",
        "confidence":                 0,
        "market_sentiment":           "UNKNOWN",
        "bullish_pressure":           0.0,
        "bearish_pressure":           0.0,
        "neutral_pressure":           0.0,
        "compliance_confidence":      None,
        "market_agreement_score":     0,
        "compliance_agreement_score": None,
        "confidence_variance":        0.0,
        "conf_std_dev":               0.0,
        "risk_level":                 "EXTREME",
        "conflict_detected":          False,
        "market_state":               "SWARM_FAILURE",
        "minority_warning":           "All agents failed to respond.",
        "agent_breakdown":            [],
        **temporal,
    }