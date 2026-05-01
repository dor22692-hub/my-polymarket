"""
Confidence Score: 0–100 per market.

Weights
-------
50 pts  Smart Money  – win-rate-weighted fraction of expert wallets on the dominant side.
                       8/10 on same side → full 50 pts.
30 pts  Sentiment    – keyword match against Tavily headlines (YES / NO keywords).
20 pts  Volume Rank  – percentile of this market's volume vs all evaluated markets.

Direction is the dominant whale side (YES or NO).  When no whale data exists
(fallback mode) whale_pts = 0 and max score is 50.
"""
from __future__ import annotations

_YES_KW = {
    "yes", "win", "pass", "approve", "approved", "confirm", "rise", "rises",
    "surge", "surges", "gains", "success", "increase", "positive", "strong",
    "high", "record", "growth", "boost", "up", "ahead", "lead", "leads",
    "likely", "expected", "favored", "advances", "beat", "beats",
}
_NO_KW = {
    "no", "lose", "loses", "fail", "fails", "reject", "rejected", "decline",
    "declines", "fall", "falls", "crash", "drop", "drops", "down", "decrease",
    "negative", "weak", "low", "poor", "loss", "miss", "misses", "cut",
    "behind", "unlikely", "doubt", "concern", "risk", "disappoints", "struggles",
}


def keyword_sentiment(articles: list[dict]) -> float:
    """Returns raw sentiment in [-1, 1] based on headline + description keywords."""
    pos = neg = 0
    for a in articles:
        text = f"{a.get('title', '')} {a.get('description', '')}".lower()
        words = set(text.split())
        pos += len(words & _YES_KW)
        neg += len(words & _NO_KW)
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total


def compute_confidence_score(
    positions: list,
    articles: list[dict],
    market_volume: float,
    all_volumes: list[float],
) -> dict:
    """
    Parameters
    ----------
    positions      List of Position dataclass objects (empty list = no whale data).
    articles       Serialised article dicts with at least 'title' and 'description'.
    market_volume  Total USDC volume for this market.
    all_volumes    Volumes of every market in the current batch (for percentile rank).

    Returns
    -------
    dict: score (int 0-100), direction (str YES/NO), whale_pts (float),
          sentiment_pts (float), volume_pts (float),
          raw_sentiment (float), sentiment_label (str)
    """
    # ── Smart Money: 50 pts ──────────────────────────────────────────
    yes_wt = sum(p.win_rate for p in positions if p.outcome.upper() == "YES")
    no_wt  = sum(p.win_rate for p in positions if p.outcome.upper() == "NO")
    total_wt = yes_wt + no_wt

    if total_wt == 0:
        direction = "YES"
        dominant_frac = 0.5
    else:
        yes_frac = yes_wt / total_wt
        direction = "YES" if yes_frac >= 0.5 else "NO"
        dominant_frac = max(yes_frac, 1 - yes_frac)

    # [0.5, 0.8] → [0, 50], capped. 0.8 fraction == full 50 pts per spec.
    whale_pts = min(((dominant_frac - 0.5) / 0.3) * 50.0, 50.0)
    whale_pts = round(max(whale_pts, 0.0), 1)

    # ── Sentiment: 30 pts ────────────────────────────────────────────
    raw_sent = keyword_sentiment(articles)          # -1 to 1

    # Align to direction: positive news helps YES, negative helps NO
    aligned = (raw_sent + 1) / 2 if direction == "YES" else (1 - raw_sent) / 2
    aligned = max(0.0, min(1.0, aligned))
    sentiment_pts = round(aligned * 30.0, 1)

    if raw_sent > 0.1:
        sent_label = "Positive 📈"
    elif raw_sent < -0.1:
        sent_label = "Negative 📉"
    else:
        sent_label = "Neutral ➡️"

    # ── Volume Rank: 20 pts ──────────────────────────────────────────
    if not all_volumes or market_volume <= 0:
        volume_pts = 10.0
    else:
        rank = sum(1 for v in all_volumes if v <= market_volume)
        percentile = rank / len(all_volumes)
        volume_pts = round(percentile * 20.0, 1)

    total = whale_pts + sentiment_pts + volume_pts

    return {
        "score": min(round(total), 100),
        "direction": direction,
        "whale_pts": whale_pts,
        "sentiment_pts": sentiment_pts,
        "volume_pts": volume_pts,
        "raw_sentiment": round(raw_sent, 3),
        "sentiment_label": sent_label,
    }
