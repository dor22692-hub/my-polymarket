"""
SignalCorrelator: merges expert-wallet positions with Claude sentiment scores
to produce high-confidence YES/NO recommendations.

Confidence formula
------------------
whale_signal  = fraction of supporting expert wallets weighted by win_rate
sentiment_cmp = |sentiment_score - 0.5| * 2   (0=neutral, 1=max conviction)
combined      = (whale_signal * 0.60) + (sentiment_cmp * 0.40)

A Signal is only emitted when:
  1. Both the whale direction and sentiment direction agree.
  2. combined_confidence >= threshold (default 0.80).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime

from loguru import logger

from config import settings
from database.db import get_session
from database.models import Opportunity
from signal_generator.scanner import Position


@dataclass
class Signal:
    market_id: str
    question: str
    recommendation: str          # "YES" | "NO"
    whale_signal: float          # 0–1: fraction of supporting expert wallets
    sentiment_score: float       # 0–1 from Claude
    combined_confidence: float   # final score
    current_price: float         # YES price at time of signal
    supporting_wallets: list[str] = field(default_factory=list)
    sentiment_reasoning: str = ""
    key_factors: list[str] = field(default_factory=list)

    def display(self) -> str:
        wallets_str = ", ".join(w[:10] + "…" for w in self.supporting_wallets[:3])
        factors = " | ".join(self.key_factors[:3])
        return (
            f"\n{'═' * 80}\n"
            f"  {self.question[:70]}\n"
            f"{'─' * 80}\n"
            f"  Recommendation : {self.recommendation}\n"
            f"  Confidence     : {self.combined_confidence:.1%}\n"
            f"  Current Price  : {self.current_price:.2f} (YES)\n"
            f"  Whale Signal   : {self.whale_signal:.1%}  "
            f"({len(self.supporting_wallets)} expert wallet(s))\n"
            f"  Sentiment Score: {self.sentiment_score:.2f}  ({self.sentiment_reasoning[:80]})\n"
            f"  Key Factors    : {factors}\n"
            f"  Wallets        : {wallets_str}\n"
            f"{'═' * 80}"
        )


class SignalCorrelator:
    def __init__(self, threshold: float | None = None) -> None:
        self._threshold = threshold if threshold is not None else settings.confidence_threshold

    def correlate(
        self,
        positions: list[Position],
        sentiment_by_market: dict[str, dict],
    ) -> list[Signal]:
        """
        `sentiment_by_market`: {condition_id: {score, direction, reasoning, key_factors}}
        Returns signals sorted by combined_confidence descending.
        """
        # Group positions by market
        by_market: dict[str, list[Position]] = defaultdict(list)
        for p in positions:
            by_market[p.market_id].append(p)

        signals: list[Signal] = []

        for market_id, mkt_positions in by_market.items():
            sentiment = sentiment_by_market.get(market_id, {})
            sent_score = float(sentiment.get("score", 0.5))
            sent_dir = sentiment.get("direction", "NEUTRAL")

            if sent_dir == "NEUTRAL":
                continue   # need a clear sentiment signal

            # Separate wallets by the outcome they're backing
            yes_pos = [p for p in mkt_positions if p.outcome.upper() == "YES"]
            no_pos = [p for p in mkt_positions if p.outcome.upper() == "NO"]

            total = len(yes_pos) + len(no_pos)
            if total == 0:
                continue

            # Determine whale direction with win-rate-weighted votes
            yes_weight = sum(p.win_rate for p in yes_pos)
            no_weight = sum(p.win_rate for p in no_pos)

            if yes_weight >= no_weight:
                whale_dir = "YES"
                backing = yes_pos
                whale_signal = yes_weight / (yes_weight + no_weight)
            else:
                whale_dir = "NO"
                backing = no_pos
                whale_signal = no_weight / (yes_weight + no_weight)

            if whale_dir != sent_dir:
                logger.debug(
                    f"Signal mismatch for {market_id[:12]}: "
                    f"whale={whale_dir} sent={sent_dir} — skipped"
                )
                continue

            # Sentiment conviction: how far from 0.5
            sent_conviction = abs(sent_score - 0.5) * 2   # 0→1
            combined = (whale_signal * 0.60) + (sent_conviction * 0.40)

            if combined < self._threshold:
                logger.debug(
                    f"{market_id[:12]}: confidence {combined:.1%} < "
                    f"threshold {self._threshold:.1%} — skipped"
                )
                continue

            current_price = backing[0].current_price if backing else 0.0

            signals.append(Signal(
                market_id=market_id,
                question=mkt_positions[0].question,
                recommendation=whale_dir,
                whale_signal=whale_signal,
                sentiment_score=sent_score,
                combined_confidence=combined,
                current_price=current_price,
                supporting_wallets=[p.wallet for p in backing],
                sentiment_reasoning=sentiment.get("reasoning", ""),
                key_factors=sentiment.get("key_factors", []),
            ))

        signals.sort(key=lambda s: s.combined_confidence, reverse=True)
        return signals

    def save_signals(self, signals: list[Signal]) -> None:
        """Persist signals as Opportunity rows (upsert by market_id + recommendation)."""
        with get_session() as session:
            for s in signals:
                existing = (
                    session.query(Opportunity)
                    .filter_by(market_id=s.market_id, outcome=s.recommendation)
                    .first()
                )
                if existing:
                    existing.whale_signal_score = s.whale_signal
                    existing.sentiment_score = s.sentiment_score
                    existing.combined_confidence = s.combined_confidence
                    existing.current_price = s.current_price
                    existing.rationale = s.sentiment_reasoning
                    existing.is_stale = False
                else:
                    session.add(Opportunity(
                        market_id=s.market_id,
                        outcome=s.recommendation,
                        current_price=s.current_price,
                        whale_signal_score=s.whale_signal,
                        sentiment_score=s.sentiment_score,
                        combined_confidence=s.combined_confidence,
                        rationale=s.sentiment_reasoning,
                        created_at=datetime.utcnow(),
                    ))
        logger.info(f"Saved {len(signals)} signal(s) to opportunities table")
