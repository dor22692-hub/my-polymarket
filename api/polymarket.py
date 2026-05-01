"""
Thin wrapper around the Polymarket CLOB REST API.

Docs: https://docs.polymarket.com/#clob-api
"""
import json
from datetime import datetime
from typing import Any

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings


class PolymarketClient:
    BASE_URL = settings.polymarket_clob_url

    def __init__(self) -> None:
        self._http = httpx.Client(
            base_url=self.BASE_URL,
            timeout=30.0,
            headers={"Accept": "application/json"},
        )

    # ── low-level ────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def _get(self, path: str, params: dict | None = None) -> Any:
        resp = self._http.get(path, params=params or {})
        resp.raise_for_status()
        return resp.json()

    # ── markets ──────────────────────────────────────────────────────

    def get_markets(
        self,
        *,
        active: bool = True,
        closed: bool = False,
        limit: int = 100,
    ) -> list[dict]:
        """
        Fetch up to `limit` markets from the CLOB, paginating automatically.
        Returns a flat list of market dicts sorted by volume descending.
        """
        results: list[dict] = []
        next_cursor: str | None = None

        params: dict[str, Any] = {
            "active": str(active).lower(),
            "closed": str(closed).lower(),
        }

        while len(results) < limit:
            if next_cursor:
                params["next_cursor"] = next_cursor

            data = self._get("/markets", params)
            batch: list[dict] = data.get("data", [])
            next_cursor = data.get("next_cursor")

            results.extend(batch)
            logger.debug(f"Fetched {len(batch)} markets (total so far: {len(results)})")

            if not next_cursor or next_cursor == "LTE=":
                break   # no more pages

        # Sort by volume (desc) and trim to requested limit
        results.sort(key=lambda m: float(m.get("volume", 0) or 0), reverse=True)
        return results[:limit]

    def get_market(self, condition_id: str) -> dict:
        return self._get(f"/markets/{condition_id}")

    # ── order book ───────────────────────────────────────────────────

    def get_orderbook(self, token_id: str) -> dict:
        return self._get("/book", {"token_id": token_id})

    # ── trades ───────────────────────────────────────────────────────

    def get_trades(
        self,
        *,
        market: str | None = None,
        maker_address: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        params: dict[str, Any] = {"limit": min(limit, 500)}
        if market:
            params["market"] = market
        if maker_address:
            params["maker_address"] = maker_address
        data = self._get("/trades", params)
        return data if isinstance(data, list) else data.get("data", [])

    # ── helpers ──────────────────────────────────────────────────────

    @staticmethod
    def parse_market(raw: dict) -> dict:
        """Normalise a raw market dict into the shape we store in the DB."""
        tokens = raw.get("tokens", [])
        outcomes = [t.get("outcome", "") for t in tokens]
        prices = [float(t.get("price", 0) or 0) for t in tokens]

        end_date_str = raw.get("end_date_iso") or raw.get("end_date")
        end_date: datetime | None = None
        if end_date_str:
            try:
                end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        return {
            "condition_id": raw.get("condition_id", ""),
            "question_id": raw.get("question_id", ""),
            "question": raw.get("question", ""),
            "description": raw.get("description", ""),
            "category": raw.get("category", ""),
            "end_date": end_date,
            "volume": float(raw.get("volume", 0) or 0),
            "liquidity": float(raw.get("liquidity", 0) or 0),
            "active": raw.get("active", True),
            "closed": raw.get("closed", False),
            "outcomes": json.dumps(outcomes),
            "outcome_prices": json.dumps(prices),
        }

    def close(self) -> None:
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
