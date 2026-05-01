"""
WhaleTracker: identifies and monitors high-win-rate wallets on Polygon.

Data sources:
  - Polymarket CLOB trade history (via PolymarketClient)
  - Polygon on-chain events (via Web3.py) — Phase 2
"""
from datetime import datetime

from loguru import logger
from web3 import Web3

from api.polymarket import PolymarketClient
from config import settings
from database.db import get_session
from database.models import WhaleTrade, WhaleWallet


class WhaleTracker:
    def __init__(self, client: PolymarketClient) -> None:
        self._client = client
        self._w3 = Web3(Web3.HTTPProvider(settings.polygon_rpc_url))

    @property
    def polygon_connected(self) -> bool:
        try:
            return self._w3.is_connected()
        except Exception:
            return False

    # ── wallet analysis ──────────────────────────────────────────────

    def analyze_wallet(self, address: str) -> WhaleWallet | None:
        """Pull trade history for an address and compute win rate."""
        trades = self._client.get_trades(maker_address=address)
        if not trades:
            return None

        resolved = [t for t in trades if t.get("status") in ("MATCHED",)]
        wins = [
            t for t in resolved
            if float(t.get("price", 0) or 0) > 0.5 and t.get("side") == "BUY"
        ]

        total = len(resolved)
        win_count = len(wins)
        win_rate = win_count / total if total else 0.0
        volume = sum(
            float(t.get("size", 0) or 0) * float(t.get("price", 0) or 0)
            for t in resolved
        )

        logger.info(f"Wallet {address}: {total} trades, win_rate={win_rate:.2%}")

        with get_session() as session:
            wallet = session.get(WhaleWallet, address)
            if not wallet:
                wallet = WhaleWallet(address=address)
                session.add(wallet)

            wallet.total_trades = total
            wallet.winning_trades = win_count
            wallet.win_rate = win_rate
            wallet.total_volume_usdc = volume
            wallet.last_seen = datetime.utcnow()
            wallet.is_active = True

            # Persist individual trades
            for t in resolved:
                tx = t.get("transaction_hash", "")
                if not tx or session.get(WhaleTrade, tx):
                    continue
                session.add(WhaleTrade(
                    wallet_address=address,
                    tx_hash=tx,
                    market_id=t.get("market"),
                    token_id=t.get("asset_id"),
                    side=t.get("side", ""),
                    size=float(t.get("size", 0) or 0),
                    price=float(t.get("price", 0) or 0),
                    outcome="OPEN",
                    timestamp=datetime.utcnow(),
                ))

        return wallet

    # ── active whales ────────────────────────────────────────────────

    def get_active_whales(self) -> list[WhaleWallet]:
        """Return all tracked wallets that meet the win-rate threshold."""
        with get_session() as session:
            return (
                session.query(WhaleWallet)
                .filter(
                    WhaleWallet.win_rate >= settings.whale_win_rate_threshold,
                    WhaleWallet.total_trades >= settings.whale_min_trades,
                    WhaleWallet.is_active == True,  # noqa: E712
                )
                .order_by(WhaleWallet.win_rate.desc())
                .all()
            )

    def get_whale_signal(self, market_id: str) -> float:
        """
        Returns a 0–1 signal: fraction of active whales that have
        recently bought YES on this market.
        Phase 1 stub — returns 0 if no whale trade data for the market.
        """
        whales = self.get_active_whales()
        if not whales:
            return 0.0

        addresses = {w.address for w in whales}
        with get_session() as session:
            recent_buys = (
                session.query(WhaleTrade)
                .filter(
                    WhaleTrade.market_id == market_id,
                    WhaleTrade.side == "BUY",
                    WhaleTrade.wallet_address.in_(addresses),
                )
                .count()
            )
        return min(recent_buys / max(len(addresses), 1), 1.0)
