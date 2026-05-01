"""
News API client — supports NewsAPI and Tavily Search.
Configure via NEWSAPI_KEY / TAVILY_API_KEY in .env.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings


@dataclass
class Article:
    title: str
    description: str
    url: str
    source: str
    published_at: datetime | None
    raw_text: str = ""


class NewsClient:
    _NEWSAPI_URL = "https://newsapi.org/v2/everything"
    _TAVILY_URL = "https://api.tavily.com/search"

    def __init__(self) -> None:
        self._http = httpx.Client(timeout=20.0)

    # ── NewsAPI ──────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def search_newsapi(self, query: str, days_back: int = 3, page_size: int = 20) -> list[Article]:
        if not settings.newsapi_key:
            logger.warning("NEWSAPI_KEY not set — skipping NewsAPI")
            return []

        from_date = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        params = {
            "q": query,
            "from": from_date,
            "sortBy": "publishedAt",
            "pageSize": page_size,
            "apiKey": settings.newsapi_key,
            "language": "en",
        }
        resp = self._http.get(self._NEWSAPI_URL, params=params)
        resp.raise_for_status()
        raw = resp.json()

        articles = []
        for a in raw.get("articles", []):
            published = None
            if a.get("publishedAt"):
                try:
                    published = datetime.fromisoformat(a["publishedAt"].replace("Z", "+00:00"))
                except ValueError:
                    pass
            articles.append(Article(
                title=a.get("title", ""),
                description=a.get("description", "") or "",
                url=a.get("url", ""),
                source=a.get("source", {}).get("name", ""),
                published_at=published,
                raw_text=f"{a.get('title', '')} {a.get('description', '')} {a.get('content', '')}",
            ))
        logger.debug(f"NewsAPI returned {len(articles)} articles for '{query}'")
        return articles

    # ── Tavily ───────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def search_tavily(self, query: str, max_results: int = 10) -> list[Article]:
        if not settings.tavily_api_key:
            logger.warning("TAVILY_API_KEY not set — skipping Tavily")
            return []

        payload = {
            "api_key": settings.tavily_api_key,
            "query": query,
            "search_depth": "advanced",
            "max_results": max_results,
            "include_answer": False,
        }
        resp = self._http.post(self._TAVILY_URL, json=payload)
        resp.raise_for_status()
        raw = resp.json()

        articles = []
        for r in raw.get("results", []):
            articles.append(Article(
                title=r.get("title", ""),
                description=r.get("content", "")[:400],
                url=r.get("url", ""),
                source="Tavily",
                published_at=None,
                raw_text=r.get("content", ""),
            ))
        logger.debug(f"Tavily returned {len(articles)} results for '{query}'")
        return articles

    # ── combined ─────────────────────────────────────────────────────

    def search(self, query: str, *, days_back: int = 3) -> list[Article]:
        """Fetch from all configured providers and deduplicate by URL."""
        all_articles = (
            self.search_newsapi(query, days_back=days_back)
            + self.search_tavily(query)
        )
        seen: set[str] = set()
        unique: list[Article] = []
        for a in all_articles:
            if a.url not in seen:
                seen.add(a.url)
                unique.append(a)
        return unique

    def close(self) -> None:
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
