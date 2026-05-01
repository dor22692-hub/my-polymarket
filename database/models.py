from datetime import datetime
from sqlalchemy import (
    Column, String, Float, Integer, Boolean, DateTime,
    ForeignKey, Text, Index
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class WhaleWallet(Base):
    """Polygon wallet addresses identified as high-win-rate traders."""
    __tablename__ = "whale_wallets"

    address = Column(String(42), primary_key=True)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)
    total_volume_usdc = Column(Float, default=0.0)
    roi = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)

    trades = relationship("WhaleTrade", back_populates="wallet")

    __table_args__ = (
        Index("ix_whale_win_rate", "win_rate"),
        Index("ix_whale_active", "is_active"),
    )


class WhaleTrade(Base):
    """Individual trades made by tracked whale wallets."""
    __tablename__ = "whale_trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    wallet_address = Column(String(42), ForeignKey("whale_wallets.address"), nullable=False)
    tx_hash = Column(String(66), unique=True, nullable=False)
    market_id = Column(String(66), ForeignKey("markets.condition_id"), nullable=True)
    token_id = Column(String(80), nullable=True)   # outcome token
    side = Column(String(4))                        # "BUY" | "SELL"
    size = Column(Float)                            # shares
    price = Column(Float)                           # entry price (0–1)
    outcome = Column(String(8), nullable=True)      # "WIN" | "LOSS" | "OPEN"
    pnl_usdc = Column(Float, nullable=True)
    timestamp = Column(DateTime, nullable=False)

    wallet = relationship("WhaleWallet", back_populates="trades")
    market = relationship("Market", back_populates="whale_trades")

    __table_args__ = (
        Index("ix_trade_wallet", "wallet_address"),
        Index("ix_trade_market", "market_id"),
        Index("ix_trade_ts", "timestamp"),
    )


class Market(Base):
    """Polymarket prediction markets."""
    __tablename__ = "markets"

    condition_id = Column(String(66), primary_key=True)
    question_id = Column(String(66))
    question = Column(Text, nullable=False)
    description = Column(Text)
    category = Column(String(100))
    end_date = Column(DateTime)
    volume = Column(Float, default=0.0)
    liquidity = Column(Float, default=0.0)
    active = Column(Boolean, default=True)
    closed = Column(Boolean, default=False)
    outcomes = Column(Text)     # JSON-encoded list of outcome labels
    outcome_prices = Column(Text)  # JSON-encoded list of current prices
    fetched_at = Column(DateTime, default=datetime.utcnow)

    whale_trades = relationship("WhaleTrade", back_populates="market")
    opportunities = relationship("Opportunity", back_populates="market")

    __table_args__ = (
        Index("ix_market_active", "active"),
        Index("ix_market_volume", "volume"),
    )


class Opportunity(Base):
    """High-confidence betting opportunities flagged by the system."""
    __tablename__ = "opportunities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market_id = Column(String(66), ForeignKey("markets.condition_id"), nullable=False)
    outcome = Column(String(200))
    current_price = Column(Float)
    whale_signal_score = Column(Float, default=0.0)   # 0–1
    sentiment_score = Column(Float, default=0.0)      # -1 to 1
    combined_confidence = Column(Float, default=0.0)  # 0–1
    rationale = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_stale = Column(Boolean, default=False)

    market = relationship("Market", back_populates="opportunities")

    __table_args__ = (
        Index("ix_opp_confidence", "combined_confidence"),
        Index("ix_opp_created", "created_at"),
    )
