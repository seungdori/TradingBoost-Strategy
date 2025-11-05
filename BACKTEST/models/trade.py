"""
Trade model for backtesting system.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field


class TradeSide(str, Enum):
    """Trade side enumeration."""
    LONG = "long"
    SHORT = "short"


class ExitReason(str, Enum):
    """Exit reason enumeration."""
    TAKE_PROFIT = "take_profit"
    TP1 = "tp1"
    TP2 = "tp2"
    TP3 = "tp3"
    STOP_LOSS = "stop_loss"
    TRAILING_STOP = "trailing_stop"
    BREAK_EVEN = "break_even"
    SIGNAL = "signal"
    MANUAL = "manual"  # Legacy: kept for backward compatibility
    BACKTEST_END = "backtest_end"  # Position held until backtest end


class Trade(BaseModel):
    """
    Individual trade record with DCA and partial exit support.

    For DCA trades:
    - entry_price: Average entry price across all entries
    - quantity: Total position size across all entries
    - dca_count: Number of additional entries (0 = no DCA)
    - entry_history: Complete record of all entries
    - total_investment: Sum of all entry investments

    For partial exit trades:
    - is_partial_exit: True if this is a partial exit (TP1/TP2/TP3)
    - tp_level: Which TP level triggered (1, 2, or 3)
    - exit_ratio: Proportion of position closed (0-1)
    - remaining_quantity: Position size remaining after this exit
    """

    # Identity
    trade_number: int = Field(..., description="Trade sequence number", ge=0)
    side: TradeSide = Field(..., description="Trade side (long/short)")

    # Entry
    entry_timestamp: datetime = Field(..., description="Entry time (UTC)")
    entry_price: float = Field(..., description="Average entry price", gt=0)
    entry_reason: Optional[str] = Field(None, description="Entry signal reason")

    # Exit
    exit_timestamp: Optional[datetime] = Field(None, description="Exit time (UTC)")
    exit_price: Optional[float] = Field(None, description="Exit price", gt=0)
    exit_reason: Optional[ExitReason] = Field(None, description="Exit reason")

    # Position sizing
    quantity: float = Field(..., description="Total position size", gt=0)
    leverage: float = Field(..., description="Leverage used", gt=0)

    # P&L
    pnl: Optional[float] = Field(None, description="Realized P&L")
    pnl_percent: Optional[float] = Field(None, description="P&L percentage")

    # Fees
    entry_fee: float = Field(default=0.0, description="Entry fee", ge=0)
    exit_fee: float = Field(default=0.0, description="Exit fee", ge=0)

    # TP/SL levels
    take_profit_price: Optional[float] = Field(None, description="Take profit price", gt=0)
    stop_loss_price: Optional[float] = Field(None, description="Stop loss price", gt=0)
    trailing_stop_price: Optional[float] = Field(None, description="Trailing stop price", gt=0)

    # Partial TP levels (TP1/TP2/TP3)
    tp1_price: Optional[float] = Field(None, description="TP1 price for partial exit", gt=0)
    tp2_price: Optional[float] = Field(None, description="TP2 price for partial exit", gt=0)
    tp3_price: Optional[float] = Field(None, description="TP3 price for partial exit", gt=0)

    # DCA levels
    next_dca_levels: List[float] = Field(default_factory=list, description="Next DCA entry levels")

    # Entry indicators
    entry_rsi: Optional[float] = Field(None, description="RSI at entry", ge=0, le=100)
    entry_atr: Optional[float] = Field(None, description="ATR at entry", ge=0)

    # DCA metadata
    dca_count: int = Field(default=0, description="Number of additional entries", ge=0)
    entry_history: List[Dict[str, Any]] = Field(default_factory=list, description="Entry history records")
    total_investment: float = Field(default=0.0, description="Total investment (USDT)", ge=0)

    # Partial exit metadata
    is_partial_exit: bool = Field(default=False, description="Is this a partial exit trade")
    tp_level: Optional[int] = Field(None, description="TP level (1, 2, or 3) for partial exits", ge=1, le=3)
    exit_ratio: Optional[float] = Field(None, description="Exit ratio for partial exits (0-1)", ge=0, le=1)
    remaining_quantity: Optional[float] = Field(None, description="Remaining quantity after partial exit", ge=0)

    class Config:
        json_schema_extra = {
            "example": {
                "trade_number": 1,
                "side": "long",
                "entry_timestamp": "2025-01-15T10:30:00Z",
                "entry_price": 42500.0,
                "entry_reason": "RSI oversold + bullish trend",
                "exit_timestamp": "2025-01-15T11:30:00Z",
                "exit_price": 43000.0,
                "exit_reason": "take_profit",
                "quantity": 0.1,
                "leverage": 10.0,
                "pnl": 50.0,
                "pnl_percent": 5.0,
                "entry_fee": 2.125,
                "exit_fee": 2.15,
                "take_profit_price": 43000.0,
                "stop_loss_price": 41800.0,
                "entry_rsi": 28.5,
                "entry_atr": 125.0
            }
        }

    @property
    def is_open(self) -> bool:
        """Check if trade is still open."""
        return self.exit_timestamp is None

    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate trade duration in seconds."""
        if not self.exit_timestamp:
            return None
        return (self.exit_timestamp - self.entry_timestamp).total_seconds()

    @property
    def total_fees(self) -> float:
        """Calculate total fees paid."""
        return self.entry_fee + self.exit_fee

    def calculate_pnl(self) -> Optional[float]:
        """
        Calculate P&L if trade is closed.

        Returns:
            P&L amount or None if trade is open
        """
        if not self.exit_price:
            return None

        if self.side == TradeSide.LONG:
            price_diff = self.exit_price - self.entry_price
        else:  # SHORT
            price_diff = self.entry_price - self.exit_price

        pnl = price_diff * self.quantity * self.leverage
        pnl -= self.total_fees

        return pnl

    def calculate_pnl_percent(self, initial_investment: float) -> Optional[float]:
        """
        Calculate P&L percentage based on initial investment.

        Args:
            initial_investment: Initial capital invested

        Returns:
            P&L percentage or None if trade is open
        """
        pnl = self.calculate_pnl()
        if pnl is None or initial_investment <= 0:
            return None

        return (pnl / initial_investment) * 100

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert trade to dictionary representation.

        Returns:
            Dictionary with all trade data including DCA metadata
        """
        return {
            'trade_number': self.trade_number,
            'side': self.side.value,
            'entry_timestamp': self.entry_timestamp.isoformat(),
            'entry_price': self.entry_price,
            'entry_reason': self.entry_reason,
            'exit_timestamp': self.exit_timestamp.isoformat() if self.exit_timestamp else None,
            'exit_price': self.exit_price,
            'exit_reason': self.exit_reason.value if self.exit_reason else None,
            'quantity': self.quantity,
            'leverage': self.leverage,
            'pnl': self.pnl,
            'pnl_percent': self.pnl_percent,
            'entry_fee': self.entry_fee,
            'exit_fee': self.exit_fee,
            'take_profit_price': self.take_profit_price,
            'stop_loss_price': self.stop_loss_price,
            'trailing_stop_price': self.trailing_stop_price,
            'tp1_price': self.tp1_price,
            'tp2_price': self.tp2_price,
            'tp3_price': self.tp3_price,
            'next_dca_levels': self.next_dca_levels,
            'entry_rsi': self.entry_rsi,
            'entry_atr': self.entry_atr,
            # DCA metadata
            'dca_count': self.dca_count,
            'entry_history': self.entry_history,
            'total_investment': self.total_investment,
            # Partial exit metadata
            'is_partial_exit': self.is_partial_exit,
            'tp_level': self.tp_level,
            'exit_ratio': self.exit_ratio,
            'remaining_quantity': self.remaining_quantity,
            # Computed fields
            'is_open': self.is_open,
            'duration_seconds': self.duration_seconds,
            'total_fees': self.total_fees
        }
