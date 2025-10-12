"""Event Types for Pub/Sub System

Defines all event types used in the position/order management microservice.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Event type enumeration"""
    # Position events
    POSITION_OPENED = "position.opened"
    POSITION_UPDATED = "position.updated"
    POSITION_CLOSED = "position.closed"

    # Order events
    ORDER_CREATED = "order.created"
    ORDER_FILLED = "order.filled"
    ORDER_PARTIALLY_FILLED = "order.partially_filled"
    ORDER_CANCELED = "order.canceled"
    ORDER_FAILED = "order.failed"

    # Price events
    PRICE_UPDATED = "price.updated"

    # Trailing stop events
    TRAILING_STOP_ACTIVATED = "trailing_stop.activated"
    TRAILING_STOP_TRIGGERED = "trailing_stop.triggered"

    # Conditional cancellation events
    CONDITIONAL_RULE_TRIGGERED = "conditional.triggered"


class BaseEvent(BaseModel):
    """Base event model"""
    event_type: EventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    user_id: str
    exchange: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PositionEvent(BaseEvent):
    """Position event"""
    position_id: str
    symbol: str
    side: str  # 'long' or 'short'
    size: Decimal
    entry_price: Decimal
    current_price: Optional[Decimal] = None
    unrealized_pnl: Optional[Decimal] = None
    leverage: int
    grid_level: Optional[int] = None


class OrderEvent(BaseEvent):
    """Order event"""
    order_id: str
    symbol: str
    side: str  # 'buy' or 'sell'
    order_type: str  # 'market', 'limit', 'stop_loss', 'trigger'
    quantity: Decimal
    price: Optional[Decimal] = None
    filled_qty: Decimal = Decimal("0")
    avg_fill_price: Optional[Decimal] = None
    status: str  # 'open', 'filled', 'partially_filled', 'canceled', 'failed'


class PriceEvent(BaseEvent):
    """Price update event"""
    symbol: str
    price: Decimal
    volume_24h: Optional[Decimal] = None
    source: str = "websocket"  # 'websocket' or 'api'


class TrailingStopEvent(BaseEvent):
    """Trailing stop event"""
    symbol: str
    activation_price: Decimal
    callback_rate: Decimal
    current_highest: Decimal
    stop_price: Decimal
    triggered: bool = False


class ConditionalRuleEvent(BaseEvent):
    """Conditional rule event"""
    rule_id: str
    trigger_order_id: str
    cancel_order_ids: List[str]
    condition: str  # 'filled', 'canceled', 'price_reached'
    triggered: bool = False
