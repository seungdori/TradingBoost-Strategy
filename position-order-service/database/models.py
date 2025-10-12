"""SQLAlchemy Models for Position/Order Service

PostgreSQL models for permanent storage of positions, orders, and events.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Column, String, DateTime, Numeric, Integer, Boolean, Text, Index
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class PositionHistory(Base):
    """Historical position records"""

    __tablename__ = 'position_history'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Identifiers
    user_id = Column(String(50), nullable=False, index=True)
    exchange = Column(String(20), nullable=False, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    position_id = Column(String(100), nullable=False, unique=True, index=True)

    # Position details
    side = Column(String(10), nullable=False)  # long/short
    size = Column(Numeric(20, 8), nullable=False)
    entry_price = Column(Numeric(20, 8), nullable=False)
    exit_price = Column(Numeric(20, 8))
    leverage = Column(Numeric(10, 2))

    # P&L
    realized_pnl = Column(Numeric(20, 8))
    unrealized_pnl = Column(Numeric(20, 8))
    fee = Column(Numeric(20, 8))

    # Strategy info
    strategy_type = Column(String(50))  # HYPERRSI, GRID, etc.
    grid_level = Column(Integer)  # For GRID strategy
    is_dca = Column(Boolean, default=False)
    is_hedge = Column(Boolean, default=False)

    # Status
    status = Column(String(20), nullable=False)  # open, closed

    # Timestamps
    opened_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    closed_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Additional metadata
    metadata_json = Column(Text)  # JSON string for additional data

    # Indexes for common queries
    __table_args__ = (
        Index('idx_user_exchange_symbol', 'user_id', 'exchange', 'symbol'),
        Index('idx_user_opened_at', 'user_id', 'opened_at'),
        Index('idx_status_opened_at', 'status', 'opened_at'),
    )


class OrderHistory(Base):
    """Historical order records"""

    __tablename__ = 'order_history'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Identifiers
    user_id = Column(String(50), nullable=False, index=True)
    exchange = Column(String(20), nullable=False, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    order_id = Column(String(100), nullable=False, unique=True, index=True)
    client_order_id = Column(String(100), index=True)

    # Order details
    side = Column(String(10), nullable=False)  # buy/sell
    order_type = Column(String(20), nullable=False)  # limit, market, stop, etc.
    quantity = Column(Numeric(20, 8), nullable=False)
    price = Column(Numeric(20, 8))
    stop_price = Column(Numeric(20, 8))

    # Execution
    filled_qty = Column(Numeric(20, 8), default=0)
    average_price = Column(Numeric(20, 8))
    fee = Column(Numeric(20, 8))
    fee_currency = Column(String(10))

    # Status
    status = Column(String(20), nullable=False)  # open, filled, cancelled, etc.

    # Strategy info
    strategy_type = Column(String(50))
    grid_level = Column(Integer)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    filled_at = Column(DateTime)
    cancelled_at = Column(DateTime)

    # Additional metadata
    metadata_json = Column(Text)

    # Indexes
    __table_args__ = (
        Index('idx_user_exchange_symbol', 'user_id', 'exchange', 'symbol'),
        Index('idx_user_created_at', 'user_id', 'created_at'),
        Index('idx_status_created_at', 'status', 'created_at'),
    )


class TrailingStopHistory(Base):
    """Historical trailing stop records"""

    __tablename__ = 'trailing_stop_history'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Identifiers
    user_id = Column(String(50), nullable=False, index=True)
    exchange = Column(String(20), nullable=False)
    symbol = Column(String(50), nullable=False)
    trailing_stop_id = Column(String(100), nullable=False, unique=True, index=True)

    # Trailing stop config
    side = Column(String(10), nullable=False)
    activation_price = Column(Numeric(20, 8), nullable=False)
    callback_rate = Column(Numeric(10, 4), nullable=False)  # e.g., 0.02 for 2%

    # State
    highest_price = Column(Numeric(20, 8))
    lowest_price = Column(Numeric(20, 8))
    current_stop_price = Column(Numeric(20, 8))
    activated = Column(Boolean, default=False)
    triggered = Column(Boolean, default=False)

    # Associated order
    order_id = Column(String(100))

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    activated_at = Column(DateTime)
    triggered_at = Column(DateTime)

    # Indexes
    __table_args__ = (
        Index('idx_user_symbol', 'user_id', 'symbol'),
        Index('idx_triggered', 'triggered'),
    )


class ConditionalRuleHistory(Base):
    """Historical conditional rule executions"""

    __tablename__ = 'conditional_rule_history'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Identifiers
    user_id = Column(String(50), nullable=False, index=True)
    exchange = Column(String(20), nullable=False)
    rule_id = Column(String(100), nullable=False, index=True)

    # Rule config
    trigger_order_id = Column(String(100), nullable=False)
    cancel_order_ids = Column(Text, nullable=False)  # JSON array
    condition = Column(String(50), nullable=False)  # filled, cancelled, etc.

    # Execution
    executed = Column(Boolean, default=False)
    execution_result = Column(Text)  # JSON with results

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    executed_at = Column(DateTime)

    # Indexes
    __table_args__ = (
        Index('idx_user_executed', 'user_id', 'executed'),
        Index('idx_trigger_order', 'trigger_order_id'),
    )
