"""
WhaleIdentifier: discovers the most active trader addresses across a set of
markets by aggregating trade volume from the Polymarket CLOB.

Strategy
--------
For each market we call /trades (up to 500 records) and accumulate
(maker_address → total_volume_usdc). The top-N addresses by volume are
returned as candidates for win-rate analysis.
"""
import time
from collections import defaultdict

from loguru import logger

from api.polymarket import PolymarketClient


class WhaleIdentifier:
    def __init__(self, client: PolymarketClient) -> None:
        self._client = client

    def discover_traders(
        self,
        markets: list[dict],
        top_n: int = 50,
    ) -> list[str]:
        """
        Scan trades across `markets` and return the top_n maker addresses
        ranked by total USDC volume traded.
        """
        volume: dict[str, float] = defaultdict(float)

        for market in markets:
            condition_id = market.get("condition_id", "")
            if not condition_id:
                continue

            try:
                trades = self._client.get_trades(market=condition_id, limit=500)
            except Exception as exc:
                logger.warning(f"Trade fetch failed for {condition_id[:12]}: {exc}")
                time.sleep(2)
                continue

            for t in trades:
                addr = (t.get("maker_address") or "").lower().strip()
                if not addr or addr == "0x0000000000000000000000000000000000000000":
                    continue
                size = float(t.get("size", 0) or 0)
                price = float(t.get("price", 0) or 0)
                volume[addr] += size * price

            time.sleep(2)

        ranked = sorted(volume.items(), key=lambda kv: kv[1], reverse=True)
        addresses = [addr for addr, _ in ranked[:top_n]]
        logger.info(
            f"Discovered {len(addresses)} candidate traders "
            f"from {len(markets)} markets (top vol: "
            f"${ranked[0][1]:,.0f} if ranked else 0)"
        )
        return addresses
