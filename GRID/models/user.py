"""
GRID User Models

Database models for user management, API keys, trading settings,
and related entities.
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from GRID.models.base import Base


class User(Base):
    """
    User model for GRID trading strategy.

    Stores user credentials, trading parameters, and configuration.
    """
    __tablename__ = "grid_users"

    # Primary Key
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    exchange_name: Mapped[str] = mapped_column(String(50), index=True, nullable=False)

    # API Credentials (encrypted in application layer)
    api_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    api_secret: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    password: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Trading Configuration
    initial_capital: Mapped[float] = mapped_column(Float, default=10.0)
    direction: Mapped[str] = mapped_column(String(10), default="long")
    numbers_to_entry: Mapped[int] = mapped_column(Integer, default=5)
    leverage: Mapped[float] = mapped_column(Float, default=10.0)
    stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    grid_num: Mapped[int] = mapped_column(Integer, default=20)

    # Runtime Status
    is_running: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    tasks: Mapped[str] = mapped_column(Text, default="[]")  # JSON array
    running_symbols: Mapped[str] = mapped_column(Text, default="[]")  # JSON array

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Note: Relationships removed to avoid composite key complexity
    # Use repositories to query related data instead

    # Composite unique constraint
    __table_args__ = (
        UniqueConstraint("user_id", "exchange_name", name="uix_user_exchange"),
    )

    def __repr__(self) -> str:
        return f"<User(user_id={self.user_id}, exchange={self.exchange_name}, running={self.is_running})>"


class TelegramID(Base):
    """
    Telegram ID mapping for users.

    Links GRID users to their Telegram accounts for notifications.
    """
    __tablename__ = "grid_telegram_ids"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("grid_users.user_id", ondelete="CASCADE"), primary_key=True
    )
    exchange_name: Mapped[str] = mapped_column(
        String(50), primary_key=True
    )
    telegram_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Note: Relationship removed - use repository to query user

    def __repr__(self) -> str:
        return f"<TelegramID(user_id={self.user_id}, telegram_id={self.telegram_id})>"


class Job(Base):
    """
    Job tracking for GRID trading tasks.

    Tracks Celery job execution and status for each user.
    """
    __tablename__ = "grid_jobs"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("grid_users.user_id", ondelete="CASCADE"), primary_key=True
    )
    exchange_name: Mapped[str] = mapped_column(
        String(50), primary_key=True
    )

    job_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # 'running', 'stopped', 'error'
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Note: Relationship removed - use repository to query user

    def __repr__(self) -> str:
        return f"<Job(user_id={self.user_id}, job_id={self.job_id}, status={self.status})>"


class Blacklist(Base):
    """
    Symbol blacklist for users.

    Prevents trading specific symbols for individual users.
    """
    __tablename__ = "grid_blacklist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("grid_users.user_id", ondelete="CASCADE"), nullable=False, index=True
    )
    exchange_name: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Note: Relationship removed - use repository to query user

    # Unique constraint to prevent duplicate entries
    __table_args__ = (
        UniqueConstraint("user_id", "exchange_name", "symbol", name="uix_blacklist"),
    )

    def __repr__(self) -> str:
        return f"<Blacklist(user_id={self.user_id}, symbol={self.symbol})>"


class Whitelist(Base):
    """
    Symbol whitelist for users.

    Restricts trading to specific symbols for individual users.
    """
    __tablename__ = "grid_whitelist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("grid_users.user_id", ondelete="CASCADE"), nullable=False, index=True
    )
    exchange_name: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Note: Relationship removed - use repository to query user

    # Unique constraint to prevent duplicate entries
    __table_args__ = (
        UniqueConstraint("user_id", "exchange_name", "symbol", name="uix_whitelist"),
    )

    def __repr__(self) -> str:
        return f"<Whitelist(user_id={self.user_id}, symbol={self.symbol})>"
