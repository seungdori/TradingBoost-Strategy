"""Trading Models - Unified Position and Order Models

Production-ready Pydantic models for position and order management.
Supports HYPERRSI and GRID strategies with exchange-agnostic design.
"""
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, computed_field, field_validator

# ==================== Enums ====================

class PositionSide(str, Enum):
    """Position direction"""
    LONG = "long"
    SHORT = "short"


class PositionStatus(str, Enum):
    """Position lifecycle status"""
    OPEN = "open"
    CLOSED = "closed"
    LIQUIDATED = "liquidated"


class OrderSide(str, Enum):
    """Order direction"""
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """Order execution type"""
    MARKET = "market"
    LIMIT = "limit"
    STOP_MARKET = "stop_market"
    STOP_LIMIT = "stop_limit"
    TRIGGER = "trigger"  # OKX algo orders
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"


class OrderStatus(str, Enum):
    """Order lifecycle status"""
    PENDING = "pending"  # Created but not sent to exchange
    OPEN = "open"  # Sent to exchange, awaiting fill
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class Exchange(str, Enum):
    """Supported exchanges"""
    OKX = "okx"
    BINANCE = "binance"
    UPBIT = "upbit"
    BITGET = "bitget"
    BYBIT = "bybit"


# ==================== Value Objects ====================

class PnLInfo(BaseModel):
    """Profit and Loss information"""
    realized_pnl: Decimal = Field(default=Decimal("0"), description="Realized P&L")
    unrealized_pnl: Decimal = Field(default=Decimal("0"), description="Unrealized P&L")
    fees: Decimal = Field(default=Decimal("0"), description="Trading fees")

    @computed_field
    def net_pnl(self) -> Decimal:
        """Net P&L after fees"""
        return self.realized_pnl + self.unrealized_pnl - self.fees

    @computed_field
    def total_pnl(self) -> Decimal:
        """Total P&L before fees"""
        return self.realized_pnl + self.unrealized_pnl


class TradeFee(BaseModel):
    """Trading fee breakdown"""
    maker_fee: Decimal = Field(default=Decimal("0"), description="Maker fee")
    taker_fee: Decimal = Field(default=Decimal("0"), description="Taker fee")
    funding_fee: Decimal = Field(default=Decimal("0"), description="Funding fee (futures)")

    @computed_field
    def total_fee(self) -> Decimal:
        """Total fees"""
        return self.maker_fee + self.taker_fee + self.funding_fee


# ==================== Core Models ====================

class Position(BaseModel):
    """Unified Position Model

    Represents an active or historical trading position.
    Compatible with HYPERRSI (symbol-based) and GRID (grid-level) strategies.

    Example:
        >>> position = Position(
        ...     user_id="user123",
        ...     exchange=Exchange.OKX,
        ...     symbol="BTC-USDT-SWAP",
        ...     side=PositionSide.LONG,
        ...     size=Decimal("0.1"),
        ...     entry_price=Decimal("45000.50")
        ... )
    """
    # Identity
    id: UUID = Field(default_factory=uuid4, description="Unique position ID")
    user_id: str = Field(..., min_length=1, description="User identifier")
    exchange: Exchange = Field(..., description="Exchange name")

    # Position details
    symbol: str = Field(..., min_length=1, description="Trading pair symbol")
    side: PositionSide = Field(..., description="Position direction")
    size: Decimal = Field(..., gt=0, description="Position size in base currency")

    # Pricing
    entry_price: Decimal = Field(..., gt=0, description="Average entry price")
    current_price: Optional[Decimal] = Field(None, gt=0, description="Current mark price")
    exit_price: Optional[Decimal] = Field(None, gt=0, description="Exit price (closed positions)")

    # Risk management
    leverage: int = Field(default=1, ge=1, le=125, description="Position leverage")
    margin_type: str = Field(default="cross", description="Margin type (cross/isolated)")
    maintenance_margin: Optional[Decimal] = Field(None, description="Maintenance margin")
    margin_ratio: Optional[Decimal] = Field(None, description="Margin ratio")
    liquidation_price: Optional[Decimal] = Field(None, description="Liquidation price")
    stop_loss_price: Optional[Decimal] = Field(None, description="Stop loss trigger price")
    take_profit_price: Optional[Decimal] = Field(None, description="Take profit trigger price")

    # HYPERRSI-specific fields (optional for backward compatibility)
    sl_order_id: Optional[str] = Field(None, description="Stop loss order ID")
    sl_contracts_amount: Optional[Decimal] = Field(None, description="SL contracts amount")
    tp_prices: List[Decimal] = Field(default_factory=list, description="Take profit price levels")
    tp_state: Optional[str] = Field(None, description="TP state tracking")
    get_tp1: Optional[Decimal] = Field(None, description="TP1 level")
    get_tp2: Optional[Decimal] = Field(None, description="TP2 level")
    get_tp3: Optional[Decimal] = Field(None, description="TP3 level")
    sl_data: Optional[Dict[str, Any]] = Field(None, description="Stop loss additional data")
    tp_data: Optional[Dict[str, Any]] = Field(None, description="Take profit additional data")
    tp_contracts_amounts: Optional[Decimal] = Field(None, description="TP contracts amount")
    last_update_time: Optional[int] = Field(None, description="Last update timestamp (epoch)")

    # P&L
    pnl_info: PnLInfo = Field(default_factory=PnLInfo, description="P&L breakdown")

    # Status
    status: PositionStatus = Field(default=PositionStatus.OPEN, description="Position status")

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Exchange-specific data")

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Position open time")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update time")
    closed_at: Optional[datetime] = Field(None, description="Position close time")

    # GRID compatibility
    grid_level: Optional[int] = Field(None, ge=0, le=100, description="Grid level (GRID strategy)")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "user_id": "user123",
                "exchange": "okx",
                "symbol": "BTC-USDT-SWAP",
                "side": "long",
                "size": "0.1",
                "entry_price": "45000.50",
                "current_price": "45500.00",
                "leverage": 10,
                "pnl_info": {
                    "realized_pnl": "0",
                    "unrealized_pnl": "50.00",
                    "fees": "5.00"
                },
                "status": "open",
                "created_at": "2025-01-01T00:00:00Z"
            }
        }

    @field_validator('symbol')
    @classmethod
    def validate_symbol_format(cls, v: str) -> str:
        """Validate symbol format"""
        if not v or len(v.strip()) == 0:
            raise ValueError("Symbol cannot be empty")
        return v.upper()

    @computed_field
    def is_open(self) -> bool:
        """Check if position is open"""
        return self.status == PositionStatus.OPEN

    @computed_field
    def notional_value(self) -> Decimal:
        """Calculate notional value"""
        price = self.current_price or self.entry_price
        return self.size * price

    @computed_field
    def pnl_percentage(self) -> Decimal:
        """Calculate P&L percentage"""
        if self.entry_price == 0:
            return Decimal("0")
        price_diff = (self.current_price or self.entry_price) - self.entry_price
        return (price_diff / self.entry_price) * Decimal("100") * (1 if self.side == PositionSide.LONG else -1)


class Order(BaseModel):
    """Unified Order Model

    Represents a trading order lifecycle from creation to execution.
    Supports all order types across exchanges.

    Example:
        >>> order = Order(
        ...     user_id="user123",
        ...     exchange=Exchange.OKX,
        ...     symbol="BTC-USDT-SWAP",
        ...     side=OrderSide.BUY,
        ...     order_type=OrderType.LIMIT,
        ...     price=Decimal("45000"),
        ...     quantity=Decimal("0.1")
        ... )
    """
    # Identity
    id: UUID = Field(default_factory=uuid4, description="Internal order ID")
    user_id: str = Field(..., min_length=1, description="User identifier")
    exchange: Exchange = Field(..., description="Exchange name")
    exchange_order_id: Optional[str] = Field(None, description="Exchange-assigned order ID")

    # Order details
    symbol: str = Field(..., min_length=1, description="Trading pair symbol")
    side: OrderSide = Field(..., description="Order direction")
    order_type: OrderType = Field(..., description="Order type")

    # Quantity and pricing
    quantity: Decimal = Field(..., gt=0, description="Order quantity")
    price: Optional[Decimal] = Field(None, gt=0, description="Limit price (for limit orders)")
    trigger_price: Optional[Decimal] = Field(None, gt=0, description="Trigger price (for stop orders)")

    # Execution
    filled_qty: Decimal = Field(default=Decimal("0"), ge=0, description="Filled quantity")
    avg_fill_price: Optional[Decimal] = Field(None, description="Average fill price")

    # Status
    status: OrderStatus = Field(default=OrderStatus.PENDING, description="Order status")

    # Risk parameters
    reduce_only: bool = Field(default=False, description="Reduce-only flag")
    post_only: bool = Field(default=False, description="Post-only flag (maker-only)")
    time_in_force: str = Field(default="GTC", description="Time in force (GTC, IOC, FOK)")

    # Fees
    fee: TradeFee = Field(default_factory=TradeFee, description="Fee breakdown")

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Exchange-specific params")

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Order creation time")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update time")
    filled_at: Optional[datetime] = Field(None, description="Fill completion time")

    # GRID compatibility
    grid_level: Optional[int] = Field(None, ge=0, le=100, description="Grid level (GRID strategy)")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440001",
                "user_id": "user123",
                "exchange": "okx",
                "symbol": "BTC-USDT-SWAP",
                "side": "buy",
                "order_type": "limit",
                "quantity": "0.1",
                "price": "45000.00",
                "filled_qty": "0.05",
                "avg_fill_price": "45000.50",
                "status": "partially_filled",
                "created_at": "2025-01-01T00:00:00Z"
            }
        }

    @field_validator('symbol')
    @classmethod
    def validate_symbol_format(cls, v: str) -> str:
        """Validate symbol format"""
        if not v or len(v.strip()) == 0:
            raise ValueError("Symbol cannot be empty")
        return v.upper()

    @computed_field
    def is_filled(self) -> bool:
        """Check if order is fully filled"""
        return self.status == OrderStatus.FILLED or self.filled_qty >= self.quantity

    @computed_field
    def is_active(self) -> bool:
        """Check if order is active (open or partially filled)"""
        return self.status in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED)

    @computed_field
    def remaining_qty(self) -> Decimal:
        """Calculate remaining quantity"""
        return max(Decimal("0"), self.quantity - self.filled_qty)

    @computed_field
    def fill_percentage(self) -> Decimal:
        """Calculate fill percentage"""
        if self.quantity == 0:
            return Decimal("0")
        return (self.filled_qty / self.quantity) * Decimal("100")


# ==================== Helper Models ====================

class PositionSummary(BaseModel):
    """Aggregated position statistics for a user"""
    user_id: str
    exchange: Exchange
    total_positions: int = 0
    open_positions: int = 0
    total_pnl: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")
    total_volume: Decimal = Decimal("0")
    win_rate: Optional[Decimal] = None

    @computed_field
    def net_pnl(self) -> Decimal:
        """Net P&L after fees"""
        return self.total_pnl - self.total_fees


class OrderBook(BaseModel):
    """Order book snapshot for a symbol"""
    exchange: Exchange
    symbol: str
    bids: List[tuple[Decimal, Decimal]] = Field(default_factory=list, description="[price, size]")
    asks: List[tuple[Decimal, Decimal]] = Field(default_factory=list, description="[price, size]")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    @computed_field
    def best_bid(self) -> Optional[Decimal]:
        """Best bid price"""
        return self.bids[0][0] if self.bids else None

    @computed_field
    def best_ask(self) -> Optional[Decimal]:
        """Best ask price"""
        return self.asks[0][0] if self.asks else None

    @computed_field
    def spread(self) -> Optional[Decimal]:
        """Bid-ask spread"""
        if self.bids and self.asks:
            return self.asks[0][0] - self.bids[0][0]
        return None
