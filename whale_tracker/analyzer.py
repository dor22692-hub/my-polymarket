"""
WalletAnalyzer: fetches a wallet's last N trades, cross-references resolved
markets to determine win/loss outcomes, and computes win rate + ROI.

Win/Loss logic
--------------
BUY trade in a resolved market → WIN if the purchased token has winner=True.
SELL trade in a resolved market → WIN if the sold token has winner=False
(i.e. the wallet exited the losing side early).
Unresolved markets are skipped.

Polygon RPC (web3.py) is used to verify the wallet's current on-chain token
balance before including open positions in the signal pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from loguru import logger
from web3 import Web3

from api.polymarket import PolymarketClient
from config import settings
from database.db import get_session
from database.models import WhaleTrade, WhaleWallet

# Polymarket Conditional Token Framework on Polygon mainnet (ERC-1155)
_CTF_ADDRESS = Web3.to_checksum_address("0x4D97DCd97eC945f40cF65F87097ACe5EA0476045")
_CTF_ABI = [
    {
        "inputs": [
            {"name": "account", "type": "address"},
            {"name": "id", "type": "uint256"},
        ],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    }
]


@dataclass
class WalletStats:
    address: str
    total_trades: int
    resolved_trades: int
    winning_trades: int
    win_rate: float
    roi: float
    total_volume_usdc: float


class WalletAnalyzer:
    def __init__(self, client: PolymarketClient) -> None:
        self._client = client
        self._market_cache: dict[str, dict] = {}
        self._w3 = Web3(Web3.HTTPProvider(settings.polygon_rpc_url))
        self._ctf = self._w3.eth.contract(address=_CTF_ADDRESS, abi=_CTF_ABI)

    # ── Polygon RPC ──────────────────────────────────────────────────

    def onchain_balance(self, address: str, token_id_hex: str) -> int:
        """Return on-chain ERC-1155 balance for a Polymarket outcome token."""
        try:
            token_int = int(token_id_hex, 16) if token_id_hex.startswith("0x") else int(token_id_hex)
            checksum = Web3.to_checksum_address(address)
            return self._ctf.functions.balanceOf(checksum, token_int).call()
        except Exception as exc:
            logger.debug(f"balanceOf RPC failed for {address[:8]}: {exc}")
            return -1  # -1 = RPC unavailable, don't filter on it

    # ── market resolution ────────────────────────────────────────────

    def _get_market(self, condition_id: str) -> dict | None:
        if condition_id not in self._market_cache:
            try:
                self._market_cache[condition_id] = self._client.get_market(condition_id)
            except Exception:
                self._market_cache[condition_id] = {}
        return self._market_cache[condition_id] or None

    def _trade_outcome(self, trade: dict, market: dict) -> bool | None:
        """True=WIN, False=LOSS, None=unresolved."""
        if not market.get("closed"):
            return None
        tokens = market.get("tokens", [])
        winner = next((t for t in tokens if t.get("winner")), None)
        if not winner:
            return None
        winning_token = winner.get("token_id", "")
        asset_id = trade.get("asset_id", "")
        side = trade.get("side", "")
        if side == "BUY":
            return asset_id == winning_token
        if side == "SELL":
            return asset_id != winning_token
        return None

    # ── analysis ─────────────────────────────────────────────────────

    def analyze(self, address: str, n_trades: int = 50) -> WalletStats | None:
        trades = self._client.get_trades(maker_address=address, limit=n_trades)
        if not trades:
            return None

        resolved: list[bool] = []
        total_cost = 0.0
        total_pnl = 0.0

        for t in trades:
            market_id = t.get("market", "")
            if not market_id:
                continue
            market = self._get_market(market_id)
            if not market:
                continue
            result = self._trade_outcome(t, market)
            if result is None:
                continue

            size = float(t.get("size", 0) or 0)
            price = float(t.get("price", 0) or 0)
            cost = size * price

            resolved.append(result)
            total_cost += cost
            total_pnl += (size - cost) if result else (-cost)

        if not resolved:
            logger.debug(f"{address[:10]}: no resolved trades found")
            return None

        wins = sum(resolved)
        total = len(resolved)
        win_rate = wins / total
        roi = total_pnl / total_cost if total_cost > 0 else 0.0
        total_volume = sum(
            float(t.get("size", 0) or 0) * float(t.get("price", 0) or 0)
            for t in trades
        )

        logger.info(
            f"{address[:10]}… | trades={total} | wins={wins} | "
            f"win_rate={win_rate:.1%} | ROI={roi:+.1%}"
        )
        return WalletStats(
            address=address,
            total_trades=len(trades),
            resolved_trades=total,
            winning_trades=wins,
            win_rate=win_rate,
            roi=roi,
            total_volume_usdc=total_volume,
        )

    def save_expert(self, stats: WalletStats) -> None:
        """Upsert a qualified wallet into the database."""
        with get_session() as session:
            wallet = session.get(WhaleWallet, stats.address)
            if not wallet:
                wallet = WhaleWallet(address=stats.address)
                session.add(wallet)
            wallet.total_trades = stats.total_trades
            wallet.winning_trades = stats.winning_trades
            wallet.win_rate = stats.win_rate
            wallet.roi = stats.roi
            wallet.total_volume_usdc = stats.total_volume_usdc
            wallet.last_seen = datetime.utcnow()
            wallet.is_active = True
