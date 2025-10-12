"""
GRID Trading Data Models

Database models for trading positions, take profit, stop loss, and win rates.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from GRID.models.base import Base


class Entry(Base):
    """
    Entry position model for GRID trading strategy.

    Stores entry position information including TP and SL levels.
    """
    __tablename__ = "grid_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exchange_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Entry information
    direction: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # 'long' or 'short'
    entry_time: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    entry_order_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Take Profit levels
    tp1_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tp2_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tp3_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tp1_order_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tp2_order_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tp3_order_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Stop Loss
    sl_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Unique constraint
    __table_args__ = (
        UniqueConstraint("exchange_name", "symbol", name="uix_entry_exchange_symbol"),
    )

    def __repr__(self) -> str:
        return f"<Entry(exchange={self.exchange_name}, symbol={self.symbol}, direction={self.direction})>"


class TakeProfit(Base):
    """
    Take Profit model for GRID trading strategy.

    Stores TP order information and status.
    """
    __tablename__ = "grid_take_profits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exchange_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # TP1
    tp1_order_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tp1_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tp1_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # TP2
    tp2_order_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tp2_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tp2_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # TP3
    tp3_order_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tp3_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tp3_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Unique constraint
    __table_args__ = (
        UniqueConstraint("exchange_name", "symbol", name="uix_tp_exchange_symbol"),
    )

    def __repr__(self) -> str:
        return f"<TakeProfit(exchange={self.exchange_name}, symbol={self.symbol})>"


class StopLoss(Base):
    """
    Stop Loss model for GRID trading strategy.

    Stores SL order information and status.
    """
    __tablename__ = "grid_stop_losses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exchange_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    sl_order_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    sl_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sl_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Unique constraint
    __table_args__ = (
        UniqueConstraint("exchange_name", "symbol", name="uix_sl_exchange_symbol"),
    )

    def __repr__(self) -> str:
        return f"<StopLoss(exchange={self.exchange_name}, symbol={self.symbol})>"


class WinRate(Base):
    """
    Win Rate statistics model for GRID trading strategy.

    Stores trading performance metrics per symbol.
    """
    __tablename__ = "grid_win_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exchange_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Win rates
    long_win_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    short_win_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_win_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Entry counts
    long_entry_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    short_entry_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Stop loss counts
    long_stop_loss_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    short_stop_loss_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Take profit counts
    long_take_profit_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    short_take_profit_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Timestamps
    first_timestamp: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    last_timestamp: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    total_win_rate_length: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Unique constraint
    __table_args__ = (
        UniqueConstraint("exchange_name", "symbol", name="uix_winrate_exchange_symbol"),
    )

    def __repr__(self) -> str:
        return f"<WinRate(exchange={self.exchange_name}, symbol={self.symbol}, total={self.total_win_rate})>"
