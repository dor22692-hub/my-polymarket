"""
ExpertScanner: for each known expert wallet, compute its current net long
positions across active Polymarket markets.

Net position logic
------------------
For each (market, outcome_token) pair, sum BUY shares and subtract SELL shares.
A positive net means the wallet currently holds that outcome.

Polygon RPC verification
------------------------
When web3 is available, on-chain ERC-1155 balanceOf() is called to confirm
the CLOB-derived position. If the RPC is unavailable, CLOB data alone is used.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict

from loguru import logger

from api.polymarket import PolymarketClient
from database.db import get_session
from database.models import WhaleWallet
from whale_tracker.analyzer import WalletAnalyzer


@dataclass
class Position:
    wallet: str
    win_rate: float
    roi: float
    market_id: str
    question: str
    outcome: str          # "YES" | "NO" | label
    token_id: str
    net_shares: float
    avg_entry_price: float
    current_price: float
    onchain_verified: bool = False


class ExpertScanner:
    def __init__(self, client: PolymarketClient) -> None:
        self._client = client
        self._analyzer = WalletAnalyzer(client)

    def load_expert_wallets(self) -> list[WhaleWallet]:
        from config import settings
        with get_session() as session:
            wallets = (
                session.query(WhaleWallet)
                .filter(
                    WhaleWallet.win_rate >= settings.whale_win_rate_threshold,
                    WhaleWallet.total_trades >= settings.whale_min_trades,
                    WhaleWallet.is_active == True,  # noqa: E712
                )
                .order_by(WhaleWallet.win_rate.desc())
                .all()
            )
            # detach from session so we can use them outside
            return list(wallets)

    def scan_positions(
        self,
        wallets: list[WhaleWallet],
        verify_onchain: bool = True,
    ) -> list[Position]:
        """Return all current net-long positions held by expert wallets."""
        positions: list[Position] = []

        for wallet in wallets:
            logger.info(f"Scanning {wallet.address[:10]}… (win_rate={wallet.win_rate:.1%})")
            trades = self._client.get_trades(maker_address=wallet.address, limit=50)

            # Aggregate net shares and total cost per (market, token)
            net: dict[tuple, dict] = defaultdict(lambda: {"shares": 0.0, "cost": 0.0})
            market_cache: dict[str, dict] = {}

            for t in trades:
                mid = t.get("market", "")
                tid = t.get("asset_id", "")
                if not mid or not tid:
                    continue
                size = float(t.get("size", 0) or 0)
                price = float(t.get("price", 0) or 0)
                key = (mid, tid)
                if t.get("side") == "BUY":
                    net[key]["shares"] += size
                    net[key]["cost"] += size * price
                else:
                    net[key]["shares"] -= size

            for (mid, tid), pos in net.items():
                if pos["shares"] <= 0.01:   # dust threshold
                    continue

                # Fetch + cache market detail
                if mid not in market_cache:
                    try:
                        market_cache[mid] = self._client.get_market(mid)
                    except Exception:
                        market_cache[mid] = {}
                market = market_cache[mid]

                if not market or market.get("closed") or not market.get("active"):
                    continue

                tokens = market.get("tokens", [])
                token_info = next((t for t in tokens if t.get("token_id") == tid), None)
                outcome = token_info.get("outcome", "UNKNOWN") if token_info else "UNKNOWN"
                current_price = float(token_info.get("price", 0) or 0) if token_info else 0.0
                avg_price = pos["cost"] / pos["shares"] if pos["shares"] > 0 else 0.0

                # Polygon RPC verification
                onchain_verified = False
                if verify_onchain:
                    balance = self._analyzer.onchain_balance(wallet.address, tid)
                    if balance == 0:
                        logger.debug(
                            f"On-chain balance=0 for {wallet.address[:10]} "
                            f"on token {tid[:12]}… — skipping"
                        )
                        continue
                    onchain_verified = balance > 0

                positions.append(Position(
                    wallet=wallet.address,
                    win_rate=wallet.win_rate,
                    roi=wallet.roi,
                    market_id=mid,
                    question=market.get("question", ""),
                    outcome=outcome,
                    token_id=tid,
                    net_shares=pos["shares"],
                    avg_entry_price=avg_price,
                    current_price=current_price,
                    onchain_verified=onchain_verified,
                ))

        logger.info(f"Scanner found {len(positions)} active expert positions")
        return positions
