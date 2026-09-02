"""Ranks screened assets and selects the top candidates."""
import os

TOP_N = int(os.getenv("TOP_N_OPPORTUNITIES", 5))


def rank_candidates(screened_results, limit: int = None) -> list:
    """Filters failed scans, sorts by score descending, returns TOP_N with rank."""
    if limit is None:
        limit = TOP_N

    valid_results = [res for res in screened_results if res.get("status") == "SUCCESS"]
    ranked = sorted(valid_results, key=lambda x: x.get("score", 0), reverse=True)

    top = ranked[:limit]
    for i, candidate in enumerate(top):
        candidate["rank"] = i + 1
    return top