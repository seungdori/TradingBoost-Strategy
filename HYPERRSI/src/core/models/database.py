from sqlalchemy import Boolean, Column, Integer, String, Float, DateTime, ForeignKey, JSON, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from datetime import datetime
from typing import List, Optional
from HYPERRSI.src.core.database_dir.base import Base

class UserModel(Base):
    __tablename__ = "hyperrsi_users"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    okx_uid: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    exchange_keys: Mapped[List["ExchangeKeysModel"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    preferences: Mapped["UserPreferencesModel"] = relationship(back_populates="user", cascade="all, delete-orphan", uselist=False)
    state: Mapped["UserStateModel"] = relationship(back_populates="user", cascade="all, delete-orphan", uselist=False)

class ExchangeKeysModel(Base):
    __tablename__ = "hyperrsi_exchange_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("hyperrsi_users.id", ondelete="CASCADE"))
    api_key: Mapped[str] = mapped_column(String)
    api_secret: Mapped[str] = mapped_column(String)
    passphrase: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    exchange: Mapped[str] = mapped_column(String, default="okx")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    # Relationship
    user: Mapped["UserModel"] = relationship(back_populates="exchange_keys")

class UserPreferencesModel(Base):
    __tablename__ = "hyperrsi_user_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("hyperrsi_users.id", ondelete="CASCADE"), unique=True)
    leverage: Mapped[int] = mapped_column(Integer, default=3)
    risk_per_trade: Mapped[float] = mapped_column(Float, default=1.0)
    max_positions: Mapped[int] = mapped_column(Integer, default=1)
    allowed_symbols: Mapped[List[str]] = mapped_column(JSON, default=["BTC-USDT", "ETH-USDT"])
    auto_trading: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationship
    user: Mapped["UserModel"] = relationship(back_populates="preferences")

class UserStateModel(Base):
    __tablename__ = "hyperrsi_user_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("hyperrsi_users.id", ondelete="CASCADE"), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    last_trade_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    current_position: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    pnl_today: Mapped[float] = mapped_column(Float, default=0.0)
    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    entry_trade: Mapped[int] = mapped_column(Integer, default=0)

    # Relationship
    user: Mapped["UserModel"] = relationship(back_populates="state")

class TickSizeModel(Base):
    __tablename__ = "hyperrsi_tick_sizes"
    __table_args__ = (
        Index('idx_tick_sizes_unique', 'exchange', 'symbol', 'market_type', unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    exchange: Mapped[str] = mapped_column(String, nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    market_type: Mapped[str] = mapped_column(String, nullable=False)  # 'spot' or 'futures'
    tick_size: Mapped[float] = mapped_column(Float, nullable=False)
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)