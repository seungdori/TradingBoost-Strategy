"""API Request/Response Schemas

Pydantic models for FastAPI endpoints.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class OrderCancelRequest(BaseModel):
    """Request to cancel order"""
    user_id: str
    exchange: str
    symbol: str
    order_id: str
    order_type: Optional[str] = "limit"  # 'limit', 'market', 'stop_loss', 'trigger'
    side: Optional[str] = None  # 'buy' or 'sell'


class OrderCancelResponse(BaseModel):
    """Response for order cancellation"""
    success: bool
    order_id: str
    message: str


class TrailingStopRequest(BaseModel):
    """Request to set trailing stop"""
    user_id: str
    exchange: str
    symbol: str
    side: str  # 'long' or 'short'
    activation_price: Decimal
    callback_rate: Decimal  # e.g., 0.02 for 2%
    size: Decimal
    order_id: Optional[str] = None


class TrailingStopResponse(BaseModel):
    """Response for trailing stop creation"""
    success: bool
    trailing_stop_id: str
    message: str


class ConditionalRuleRequest(BaseModel):
    """Request to create conditional rule"""
    user_id: str
    exchange: str
    trigger_order_id: str
    cancel_order_ids: List[str]
    condition: str = "filled"  # 'filled', 'canceled', 'price_reached'
    condition_params: Optional[Dict[str, Any]] = None


class ConditionalRuleResponse(BaseModel):
    """Response for conditional rule creation"""
    success: bool
    rule_id: str
    message: str


class PositionData(BaseModel):
    """Position data"""
    position_id: str
    user_id: str
    exchange: str
    symbol: str
    side: str
    size: Decimal
    entry_price: Decimal
    current_price: Optional[Decimal] = None
    unrealized_pnl: Optional[Decimal] = None
    leverage: int
    grid_level: Optional[int] = None
    last_updated: datetime


class OrderData(BaseModel):
    """Order data"""
    order_id: str
    user_id: str
    exchange: str
    symbol: str
    side: str
    order_type: str
    quantity: Decimal
    price: Optional[Decimal] = None
    filled_qty: Decimal
    avg_fill_price: Optional[Decimal] = None
    status: str
    last_updated: datetime


class PositionsResponse(BaseModel):
    """Response for positions query"""
    success: bool
    positions: List[Dict[str, Any]]
    count: int


class OrdersResponse(BaseModel):
    """Response for orders query"""
    success: bool
    orders: List[Dict[str, Any]]
    count: int


class TrailingStopsResponse(BaseModel):
    """Response for trailing stops query"""
    success: bool
    trailing_stops: List[Dict[str, Any]]
    count: int


class ConditionalRulesResponse(BaseModel):
    """Response for conditional rules query"""
    success: bool
    rules: List[Dict[str, Any]]
    count: int


class ServiceStatusResponse(BaseModel):
    """Response for service status"""
    status: str
    uptime: float
    active_connections: int
    active_subscriptions: int
    version: str
