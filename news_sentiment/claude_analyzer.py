"""
Claude-powered sentiment analysis for Polymarket questions.

Calls the Anthropic Messages API with prompt caching on the system prompt.
Returns a structured dict: {score, direction, reasoning, key_factors}.
"""
from __future__ import annotations

import json
import re

import anthropic
from loguru import logger

from api.news import Article, NewsClient

_SYSTEM_PROMPT = """\
You are a quantitative analyst for prediction markets. Given a market question and \
recent news, assess the probability the market resolves YES.

Rules:
- Output ONLY valid JSON — no prose, no markdown fences.
- score: float 0.0–1.0 (0 = certain NO, 0.5 = uncertain, 1 = certain YES).
- direction: "YES" if score > 0.55, "NO" if score < 0.45, else "NEUTRAL".
- reasoning: 2–3 sentences of evidence-based explanation.
- key_factors: list of 3 concise strings (most influential factors).\
"""

_RESPONSE_SCHEMA = {
    "score": 0.5,
    "direction": "NEUTRAL",
    "reasoning": "",
    "key_factors": [],
}


class ClaudeSentimentAnalyzer:
    def __init__(self, model: str = "claude-sonnet-4-6") -> None:
        self._anthropic = anthropic.Anthropic()
        self._model = model
        self._news = NewsClient()

    def analyze_market(self, market_id: str, question: str) -> dict:
        """
        Fetch recent news for `question` and return a sentiment dict.
        Falls back to a neutral result if news is unavailable or Claude errors.
        """
        articles: list[Article] = self._news.search(question, days_back=3)

        if not articles:
            logger.debug(f"No articles for '{question[:60]}' — returning neutral")
            return {**_RESPONSE_SCHEMA, "reasoning": "No relevant news found."}

        articles_block = "\n\n---\n".join(
            f"[{a.source}] {a.title}\n{a.description[:350]}"
            for a in articles[:10]
        )
        user_content = (
            f"Market Question: {question}\n\n"
            f"Recent News:\n{articles_block}\n\n"
            "Respond with JSON only."
        )

        try:
            response = self._anthropic.messages.create(
                model=self._model,
                max_tokens=512,
                system=[
                    {
                        "type": "text",
                        "text": _SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_content}],
            )
            raw = response.content[0].text.strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            result: dict = json.loads(raw)
            logger.info(
                f"Sentiment '{question[:50]}': "
                f"score={result.get('score', '?')} dir={result.get('direction', '?')}"
            )
            return {**_RESPONSE_SCHEMA, **result}
        except Exception as exc:
            logger.warning(f"Claude analysis failed: {exc}")
            return {**_RESPONSE_SCHEMA, "reasoning": f"Analysis error: {exc}"}

    def close(self) -> None:
        self._news.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
