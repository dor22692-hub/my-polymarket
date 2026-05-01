"""
News sentiment analyzer.

Uses a HuggingFace zero-shot classification pipeline by default.
Falls back to a simple positive/negative keyword heuristic if the
model is not yet downloaded (speeds up cold-start in Phase 1).
"""
from __future__ import annotations

from loguru import logger

from api.news import Article, NewsClient


_POSITIVE_WORDS = {"win", "yes", "pass", "approve", "confirm", "rise", "surge", "gains"}
_NEGATIVE_WORDS = {"lose", "no", "fail", "reject", "decline", "fall", "crash", "drop"}


def _keyword_sentiment(text: str) -> float:
    """Returns a score in [-1, 1] based on keyword overlap."""
    tokens = set(text.lower().split())
    pos = len(tokens & _POSITIVE_WORDS)
    neg = len(tokens & _NEGATIVE_WORDS)
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total


class SentimentAnalyzer:
    def __init__(self, use_transformer: bool = False) -> None:
        self._pipeline = None
        if use_transformer:
            try:
                from transformers import pipeline  # type: ignore
                self._pipeline = pipeline(
                    "zero-shot-classification",
                    model="facebook/bart-large-mnli",
                )
                logger.info("Loaded BART zero-shot classification pipeline")
            except Exception as e:
                logger.warning(f"Could not load transformer pipeline: {e} — using keyword fallback")

        self._news = NewsClient()

    def _score_article(self, article: Article, labels: list[str]) -> float:
        """Returns a probability that the article supports the YES outcome."""
        text = article.raw_text or f"{article.title} {article.description}"
        if not text.strip():
            return 0.0

        if self._pipeline:
            result = self._pipeline(text[:512], candidate_labels=labels)
            yes_idx = labels.index("yes") if "yes" in labels else 0
            return float(result["scores"][yes_idx])

        return (_keyword_sentiment(text) + 1) / 2   # map [-1,1] → [0,1]

    def analyze_market(self, question: str) -> float:
        """
        Fetch recent news for the market question and return an
        aggregate sentiment score in [0, 1] where >0.5 favours YES.
        """
        articles = self._news.search(question, days_back=3)
        if not articles:
            logger.debug(f"No articles found for: {question!r}")
            return 0.5   # neutral

        labels = ["yes", "no"]
        scores = [self._score_article(a, labels) for a in articles]
        avg = sum(scores) / len(scores)
        logger.debug(f"Sentiment for '{question[:60]}': {avg:.3f} ({len(articles)} articles)")
        return avg

    def close(self) -> None:
        self._news.close()
