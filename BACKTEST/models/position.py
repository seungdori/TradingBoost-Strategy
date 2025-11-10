"""
Position model for backtesting system.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from BACKTEST.models.trade import TradeSide


class Position(BaseModel):
    """
    Current position state during backtesting with DCA and partial exits support.

    Attributes:
        side: Position side (long/short)
        entry_timestamp: Entry time (UTC)
        entry_price: Average entry price (recalculated after each DCA)
        quantity: Total position size (accumulated)
        leverage: Leverage used
        initial_margin: Initial margin required

        # TP/SL management
        take_profit_price: Take profit price (backward compatible, used when partial exits disabled)
        stop_loss_price: Stop loss price
        trailing_stop_price: Trailing stop price
        trailing_stop_activated: Trailing stop activation status

        # Partial exits (TP1/TP2/TP3)
        use_tp1, use_tp2, use_tp3: Enable each TP level
        tp1_price, tp2_price, tp3_price: Target prices for each level
        tp1_ratio, tp2_ratio, tp3_ratio: Exit ratios (0-1) for each level
        tp1_filled, tp2_filled, tp3_filled: Fill status for each level
        remaining_quantity: Remaining quantity after partial exits

        # P&L tracking
        unrealized_pnl: Current unrealized P&L
        unrealized_pnl_percent: Current unrealized P&L %
        highest_pnl: Highest unrealized P&L reached
        lowest_pnl: Lowest unrealized P&L reached

        # Entry context
        entry_reason: Entry signal reason
        entry_rsi: RSI at entry
        entry_atr: ATR at entry

        # DCA tracking
        dca_count: Number of additional entries (0 = no DCA yet)
        entry_history: List of all entries [{price, quantity, investment, timestamp, reason}]
        dca_levels: Remaining DCA price levels to be triggered
        initial_investment: First entry investment amount (USDT)
        total_investment: Accumulated investment across all entries (USDT)
        last_filled_price: Most recent entry price (for DCA calculation)
    """

    # Position identity
    side: TradeSide = Field(..., description="Position side (long/short)")
    entry_timestamp: datetime = Field(..., description="Entry time (UTC)")
    entry_price: float = Field(..., description="Average entry price", gt=0)

    # Position sizing
    quantity: float = Field(..., description="Position size", gt=0)
    leverage: float = Field(..., description="Leverage used", gt=0)
    initial_margin: float = Field(..., description="Initial margin required", gt=0)

    # TP/SL management
    take_profit_price: Optional[float] = Field(None, description="Take profit price (backward compatible)", gt=0)
    stop_loss_price: Optional[float] = Field(None, description="Stop loss price", gt=0)
    trailing_stop_price: Optional[float] = Field(None, description="Trailing stop price", gt=0)
    trailing_stop_activated: bool = Field(default=False, description="Trailing stop activation status")
    trailing_offset: Optional[float] = Field(None, description="Trailing stop offset distance", gt=0)
    trailing_start_point: Optional[int] = Field(None, description="TP level that activated trailing stop (1, 2, or 3)", ge=1, le=3)
    highest_price: Optional[float] = Field(None, description="Highest price reached (for LONG trailing stop)", gt=0)
    lowest_price: Optional[float] = Field(None, description="Lowest price reached (for SHORT trailing stop)", gt=0)

    # Partial exits (TP1/TP2/TP3)
    use_tp1: bool = Field(default=False, description="Use TP1 level")
    use_tp2: bool = Field(default=False, description="Use TP2 level")
    use_tp3: bool = Field(default=False, description="Use TP3 level")
    tp1_price: Optional[float] = Field(None, description="TP1 price", gt=0)
    tp2_price: Optional[float] = Field(None, description="TP2 price", gt=0)
    tp3_price: Optional[float] = Field(None, description="TP3 price", gt=0)
    tp1_ratio: float = Field(default=0.0, description="TP1 exit ratio (0-1)", ge=0, le=1)
    tp2_ratio: float = Field(default=0.0, description="TP2 exit ratio (0-1)", ge=0, le=1)
    tp3_ratio: float = Field(default=0.0, description="TP3 exit ratio (0-1)", ge=0, le=1)
    tp1_filled: bool = Field(default=False, description="TP1 filled status")
    tp2_filled: bool = Field(default=False, description="TP2 filled status")
    tp3_filled: bool = Field(default=False, description="TP3 filled status")
    remaining_quantity: Optional[float] = Field(None, description="Remaining quantity after partial exits", gt=0)

    # P&L tracking
    unrealized_pnl: float = Field(default=0.0, description="Current unrealized P&L")
    unrealized_pnl_percent: float = Field(default=0.0, description="Current unrealized P&L %")
    highest_pnl: float = Field(default=0.0, description="Highest unrealized P&L reached")
    lowest_pnl: float = Field(default=0.0, description="Lowest unrealized P&L reached")

    # Entry context
    entry_reason: Optional[str] = Field(None, description="Entry signal reason")
    entry_rsi: Optional[float] = Field(None, description="RSI at entry", ge=0, le=100)
    entry_atr: Optional[float] = Field(None, description="ATR at entry", ge=0)

    # DCA tracking fields (NEW)
    dca_count: int = Field(default=0, description="Number of additional entries", ge=0)
    entry_history: List[Dict[str, Any]] = Field(default_factory=list, description="Entry history records")
    dca_levels: List[float] = Field(default_factory=list, description="Remaining DCA price levels")
    initial_investment: float = Field(default=0.0, description="First entry investment (USDT)", ge=0)
    total_investment: float = Field(default=0.0, description="Total investment (USDT)", ge=0)
    last_filled_price: float = Field(default=0.0, description="Most recent entry price", ge=0)

    class Config:
        json_schema_extra = {
            "example": {
                "side": "long",
                "entry_timestamp": "2025-01-15T10:30:00Z",
                "entry_price": 42500.0,
                "quantity": 0.1,
                "leverage": 10.0,
                "initial_margin": 425.0,
                "take_profit_price": 43000.0,
                "stop_loss_price": 41800.0,
                "trailing_stop_price": None,
                "trailing_stop_activated": False,
                "unrealized_pnl": 25.0,
                "unrealized_pnl_percent": 5.88,
                "highest_pnl": 30.0,
                "lowest_pnl": -10.0,
                "entry_reason": "RSI oversold + bullish trend",
                "entry_rsi": 28.5,
                "entry_atr": 125.0
            }
        }

    def get_average_entry_price(self) -> float:
        """
        Calculate average entry price from entry history.

        Returns:
            Average entry price weighted by quantity
        """
        if not self.entry_history:
            return self.entry_price

        total_cost = sum(
            entry['price'] * entry['quantity']
            for entry in self.entry_history
        )
        total_quantity = sum(
            entry['quantity']
            for entry in self.entry_history
        )

        if total_quantity == 0:
            return self.entry_price

        return total_cost / total_quantity

    def get_total_quantity(self) -> float:
        """
        Calculate total position quantity from entry history.

        Returns:
            Total quantity across all entries
        """
        if not self.entry_history:
            return self.quantity

        return sum(entry['quantity'] for entry in self.entry_history)

    def get_unrealized_pnl_amount(self, current_price: float) -> float:
        """
        Calculate unrealized P&L based on average entry price.

        Args:
            current_price: Current market price

        Returns:
            Unrealized P&L in USDT
        """
        avg_price = self.get_average_entry_price()
        total_qty = self.get_total_quantity()

        if self.side == TradeSide.LONG:
            price_diff = current_price - avg_price
        else:  # SHORT
            price_diff = avg_price - current_price

        # P&L = price_diff * quantity * leverage
        pnl = price_diff * total_qty * self.leverage

        return pnl

    def update_unrealized_pnl(self, current_price: float) -> None:
        """
        Update unrealized P&L based on current price.

        Uses average entry price for DCA positions.

        Args:
            current_price: Current market price
        """
        # Use DCA-aware P&L calculation
        self.unrealized_pnl = self.get_unrealized_pnl_amount(current_price)

        # Calculate P&L percentage based on total investment
        if self.total_investment > 0:
            self.unrealized_pnl_percent = (self.unrealized_pnl / self.total_investment) * 100
        elif self.initial_margin > 0:
            # Fallback for non-DCA positions
            self.unrealized_pnl_percent = (self.unrealized_pnl / self.initial_margin) * 100

        # Track highest/lowest P&L
        if self.unrealized_pnl > self.highest_pnl:
            self.highest_pnl = self.unrealized_pnl
        if self.unrealized_pnl < self.lowest_pnl:
            self.lowest_pnl = self.unrealized_pnl

    def update_trailing_stop(
        self,
        current_price: float,
        trailing_percent: float,
        atr_multiplier: Optional[float] = None,
        atr_value: Optional[float] = None
    ) -> None:
        """
        Update trailing stop price based on current price and strategy.

        Args:
            current_price: Current market price
            trailing_percent: Trailing stop percentage (e.g., 2.0 for 2%)
            atr_multiplier: Optional ATR multiplier for dynamic trailing
            atr_value: Optional current ATR value
        """
        if not self.trailing_stop_activated:
            return

        if atr_multiplier and atr_value:
            # Dynamic ATR-based trailing stop
            trailing_distance = atr_value * atr_multiplier
        else:
            # Percentage-based trailing stop
            trailing_distance = current_price * (trailing_percent / 100)

        if self.side == TradeSide.LONG:
            new_stop = current_price - trailing_distance
            # Only move stop up, never down
            if self.trailing_stop_price is None or new_stop > self.trailing_stop_price:
                self.trailing_stop_price = new_stop
        else:  # SHORT
            new_stop = current_price + trailing_distance
            # Only move stop down, never up
            if self.trailing_stop_price is None or new_stop < self.trailing_stop_price:
                self.trailing_stop_price = new_stop

    def should_exit_partial(self, current_price: float) -> tuple[bool, Optional[str], Optional[int]]:
        """
        Check if partial exit should be triggered (TP1/TP2/TP3).

        Args:
            current_price: Current market price

        Returns:
            Tuple of (should_exit, exit_reason, tp_level)
            - should_exit: True if any unfilled TP level is reached
            - exit_reason: "tp1", "tp2", or "tp3"
            - tp_level: 1, 2, or 3
        """
        if self.side == TradeSide.LONG:
            # Check TP1
            if self.use_tp1 and not self.tp1_filled and self.tp1_price and current_price >= self.tp1_price:
                return True, "tp1", 1
            # Check TP2
            if self.use_tp2 and not self.tp2_filled and self.tp2_price and current_price >= self.tp2_price:
                return True, "tp2", 2
            # Check TP3 (skip if trailing stop is active - trailing stop replaces TP3)
            if self.use_tp3 and not self.tp3_filled and self.tp3_price and not self.trailing_stop_activated and current_price >= self.tp3_price:
                return True, "tp3", 3

        else:  # SHORT
            # Check TP1
            if self.use_tp1 and not self.tp1_filled and self.tp1_price and current_price <= self.tp1_price:
                return True, "tp1", 1
            # Check TP2
            if self.use_tp2 and not self.tp2_filled and self.tp2_price and current_price <= self.tp2_price:
                return True, "tp2", 2
            # Check TP3 (skip if trailing stop is active - trailing stop replaces TP3)
            if self.use_tp3 and not self.tp3_filled and self.tp3_price and not self.trailing_stop_activated and current_price <= self.tp3_price:
                return True, "tp3", 3

        return False, None, None

    def should_exit(self, current_price: float) -> tuple[bool, Optional[str]]:
        """
        Check if position should be closed (TP, SL, Trailing Stop, or Break-even).

        Priority order:
        1. Take Profit (backward compatibility if partial exits disabled)
        2. Trailing Stop (if activated)
        3. Stop Loss (with break-even detection)

        Break-even detection:
        - LONG: stop_loss_price >= avg_entry_price
        - SHORT: stop_loss_price <= avg_entry_price

        Note: TP is handled by should_exit_partial() for partial exits.
        For backward compatibility, also checks take_profit_price if partial exits are disabled.

        Args:
            current_price: Current market price

        Returns:
            Tuple of (should_exit, exit_reason)
            exit_reason: "take_profit", "trailing_stop", "break_even", or "stop_loss"
        """
        # Check partial exits first
        has_partial_exits = self.use_tp1 or self.use_tp2 or self.use_tp3

        if self.side == TradeSide.LONG:
            # Check take profit (backward compatibility - only if no partial exits)
            if not has_partial_exits and self.take_profit_price and current_price >= self.take_profit_price:
                return True, "take_profit"

            # Check trailing stop first (higher priority than stop loss)
            if self.trailing_stop_price and current_price <= self.trailing_stop_price:
                return True, "trailing_stop"

            # Check stop loss (distinguish break-even from regular stop loss)
            if self.stop_loss_price and current_price <= self.stop_loss_price:
                # Break-even: stop loss at or above entry price
                avg_entry = self.get_average_entry_price()
                if self.stop_loss_price >= avg_entry:
                    return True, "break_even"
                else:
                    return True, "stop_loss"

        else:  # SHORT
            # Check take profit (backward compatibility - only if no partial exits)
            if not has_partial_exits and self.take_profit_price and current_price <= self.take_profit_price:
                return True, "take_profit"

            # Check trailing stop first (higher priority than stop loss)
            if self.trailing_stop_price and current_price >= self.trailing_stop_price:
                return True, "trailing_stop"

            # Check stop loss (distinguish break-even from regular stop loss)
            if self.stop_loss_price and current_price >= self.stop_loss_price:
                # Break-even: stop loss at or below entry price
                avg_entry = self.get_average_entry_price()
                if self.stop_loss_price <= avg_entry:
                    return True, "break_even"
                else:
                    return True, "stop_loss"

        return False, None

    def get_current_quantity(self) -> float:
        """
        Get current position quantity (considering partial exits).

        Returns:
            Current quantity after partial exits, or total quantity if no exits yet
        """
        if self.remaining_quantity is not None:
            return self.remaining_quantity
        return self.get_total_quantity()

    def all_tp_levels_filled(self) -> bool:
        """
        Check if all enabled TP levels have been filled.

        Returns:
            True if all enabled TPs are filled, False otherwise
        """
        if self.use_tp1 and not self.tp1_filled:
            return False
        if self.use_tp2 and not self.tp2_filled:
            return False
        if self.use_tp3 and not self.tp3_filled:
            return False
        return True

    def activate_hyperrsi_trailing_stop(
        self,
        current_price: float,
        trailing_offset: float,
        tp_level: int
    ) -> None:
        """
        Activate trailing stop using HYPERRSI logic.

        Mirrors HYPERRSI's activate_trailing_stop() behavior:
        - Sets initial highest/lowest price
        - Calculates trailing stop price from current price
        - Stores activation metadata

        Args:
            current_price: Current market price at activation
            trailing_offset: Trailing offset distance (absolute price difference)
            tp_level: TP level that triggered activation (1, 2, or 3)
        """
        if self.side == TradeSide.LONG:
            # For LONG: track highest price, stop below it
            self.highest_price = current_price
            self.trailing_stop_price = current_price - trailing_offset
        else:  # SHORT
            # For SHORT: track lowest price, stop above it
            self.lowest_price = current_price
            self.trailing_stop_price = current_price + trailing_offset

        self.trailing_stop_activated = True
        self.trailing_offset = trailing_offset
        self.trailing_start_point = tp_level

    def update_hyperrsi_trailing_stop(self, current_price: float) -> None:
        """
        Update trailing stop price using HYPERRSI logic.

        Mirrors HYPERRSI's check_trailing_stop() behavior:
        - For LONG: Updates highest_price and trailing_stop_price when new high
        - For SHORT: Updates lowest_price and trailing_stop_price when new low
        - Stop price only moves in favorable direction

        Args:
            current_price: Current market price
        """
        if not self.trailing_stop_activated or self.trailing_offset is None:
            return

        if self.side == TradeSide.LONG:
            # Update highest price if new high reached
            if self.highest_price is None or current_price > self.highest_price:
                self.highest_price = current_price
                # Move trailing stop up (never down)
                self.trailing_stop_price = self.highest_price - self.trailing_offset
        else:  # SHORT
            # Update lowest price if new low reached
            if self.lowest_price is None or current_price < self.lowest_price:
                self.lowest_price = current_price
                # Move trailing stop down (never up)
                self.trailing_stop_price = self.lowest_price + self.trailing_offset

    def check_hyperrsi_trailing_stop_hit(self, current_price: float) -> bool:
        """
        Check if HYPERRSI-style trailing stop should trigger.

        Returns:
            True if trailing stop price breached, False otherwise
        """
        if not self.trailing_stop_activated or self.trailing_stop_price is None:
            return False

        if self.side == TradeSide.LONG:
            # LONG: Trigger if price drops below trailing stop
            return current_price <= self.trailing_stop_price
        else:  # SHORT
            # SHORT: Trigger if price rises above trailing stop
            return current_price >= self.trailing_stop_price
