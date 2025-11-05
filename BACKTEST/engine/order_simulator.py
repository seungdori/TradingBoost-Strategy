"""
Order simulator for realistic order execution in backtesting.
"""

from typing import Optional, Tuple
from enum import Enum

from BACKTEST.models.candle import Candle
from BACKTEST.models.trade import TradeSide
from shared.logging import get_logger

logger = get_logger(__name__)


class OrderType(str, Enum):
    """Order type enumeration."""
    MARKET = "market"
    LIMIT = "limit"


class SlippageModel(str, Enum):
    """Slippage model enumeration."""
    NONE = "none"
    FIXED = "fixed"
    PERCENTAGE = "percentage"
    REALISTIC = "realistic"


class OrderSimulator:
    """Simulates realistic order execution during backtesting."""

    def __init__(
        self,
        slippage_model: SlippageModel = SlippageModel.PERCENTAGE,
        slippage_percent: float = 0.05,
        use_bid_ask_spread: bool = True
    ):
        """
        Initialize order simulator.

        Args:
            slippage_model: Slippage calculation model
            slippage_percent: Slippage percentage (default 0.05%)
            use_bid_ask_spread: Whether to simulate bid-ask spread
        """
        self.slippage_model = slippage_model
        self.slippage_percent = slippage_percent
        self.use_bid_ask_spread = use_bid_ask_spread

        logger.info(
            f"OrderSimulator initialized: model={slippage_model.value}, "
            f"slippage={slippage_percent}%, bid_ask={use_bid_ask_spread}"
        )

    def simulate_market_order(
        self,
        side: TradeSide,
        candle: Candle,
        order_type: OrderType = OrderType.MARKET
    ) -> float:
        """
        Simulate market order execution and return filled price.

        Args:
            side: Order side (long/short)
            candle: Current candle data
            order_type: Order type

        Returns:
            Filled price after slippage
        """
        base_price = candle.close

        # Apply slippage
        if self.slippage_model == SlippageModel.NONE:
            filled_price = base_price

        elif self.slippage_model == SlippageModel.PERCENTAGE:
            slippage = base_price * (self.slippage_percent / 100)

            if side == TradeSide.LONG:
                # Long entry: buy at higher price
                filled_price = base_price + slippage
            else:
                # Short entry: sell at lower price
                filled_price = base_price - slippage

        elif self.slippage_model == SlippageModel.REALISTIC:
            # Realistic slippage based on candle volatility
            candle_range = candle.high - candle.low
            slippage = candle_range * 0.1  # 10% of candle range

            if side == TradeSide.LONG:
                filled_price = base_price + slippage
            else:
                filled_price = base_price - slippage

        else:  # FIXED
            slippage = self.slippage_percent  # Treat as fixed amount

            if side == TradeSide.LONG:
                filled_price = base_price + slippage
            else:
                filled_price = base_price - slippage

        # Apply bid-ask spread
        if self.use_bid_ask_spread:
            spread = base_price * 0.0001  # 0.01% spread

            if side == TradeSide.LONG:
                filled_price += spread / 2
            else:
                filled_price -= spread / 2

        return filled_price

    def check_stop_hit(
        self,
        candle: Candle,
        stop_price: float,
        side: TradeSide
    ) -> Tuple[bool, Optional[float]]:
        """
        Check if stop loss was hit during candle.

        Args:
            candle: Current candle data
            stop_price: Stop loss price
            side: Position side

        Returns:
            Tuple of (was_hit, filled_price)
        """
        if side == TradeSide.LONG:
            # Long position: stop is below entry
            if candle.low <= stop_price:
                # Stop was hit
                # Filled price is worse than stop due to slippage
                slippage = stop_price * (self.slippage_percent / 100)
                filled_price = stop_price - slippage
                return True, filled_price

        else:  # SHORT
            # Short position: stop is above entry
            if candle.high >= stop_price:
                # Stop was hit
                slippage = stop_price * (self.slippage_percent / 100)
                filled_price = stop_price + slippage
                return True, filled_price

        return False, None

    def check_take_profit_hit(
        self,
        candle: Candle,
        tp_price: float,
        side: TradeSide
    ) -> Tuple[bool, Optional[float]]:
        """
        Check if take profit was hit during candle.

        Args:
            candle: Current candle data
            tp_price: Take profit price
            side: Position side

        Returns:
            Tuple of (was_hit, filled_price)
        """
        if side == TradeSide.LONG:
            # Long position: TP is above entry
            if candle.high >= tp_price:
                # TP was hit - assume filled at TP price
                return True, tp_price

        else:  # SHORT
            # Short position: TP is below entry
            if candle.low <= tp_price:
                # TP was hit
                return True, tp_price

        return False, None

    def check_trailing_stop_hit(
        self,
        candle: Candle,
        trailing_stop_price: float,
        side: TradeSide
    ) -> Tuple[bool, Optional[float]]:
        """
        Check if trailing stop was hit during candle.

        Args:
            candle: Current candle data
            trailing_stop_price: Trailing stop price
            side: Position side

        Returns:
            Tuple of (was_hit, filled_price)
        """
        # Trailing stop behaves like regular stop loss
        return self.check_stop_hit(candle, trailing_stop_price, side)

    def validate_execution_price(
        self,
        price: float,
        candle: Candle
    ) -> bool:
        """
        Validate that execution price is within candle range.

        Args:
            price: Execution price
            candle: Candle data

        Returns:
            True if price is valid
        """
        # Allow some tolerance for slippage beyond candle range
        tolerance = (candle.high - candle.low) * 0.1

        return (candle.low - tolerance) <= price <= (candle.high + tolerance)

    def calculate_realistic_fill_price(
        self,
        side: TradeSide,
        candle: Candle,
        volume_factor: float = 1.0
    ) -> float:
        """
        Calculate realistic fill price considering volume and volatility.

        Args:
            side: Order side
            candle: Current candle data
            volume_factor: Position size relative to candle volume

        Returns:
            Realistic fill price
        """
        base_price = candle.close

        # Higher volume factor means more slippage
        volume_slippage = base_price * (self.slippage_percent / 100) * min(volume_factor, 2.0)

        # Volatility-based slippage
        volatility = (candle.high - candle.low) / candle.open
        volatility_slippage = base_price * volatility * 0.1

        total_slippage = volume_slippage + volatility_slippage

        if side == TradeSide.LONG:
            return base_price + total_slippage
        else:
            return base_price - total_slippage

    @staticmethod
    def validate_order_size(
        quantity: float,
        min_size: float,
        symbol: str
    ) -> tuple[bool, Optional[str]]:
        """
        Validate order quantity against minimum size requirements.

        Args:
            quantity: Order quantity (in contracts)
            min_size: Minimum order size for the symbol
            symbol: Trading symbol for logging

        Returns:
            Tuple of (is_valid, error_message)
        """
        if quantity < min_size:
            error_msg = (
                f"Order quantity {quantity:.6f} is below minimum size {min_size:.6f} for {symbol}. "
                f"Order will be skipped."
            )
            logger.warning(error_msg)
            return False, error_msg

        return True, None

    @staticmethod
    def round_to_precision(
        quantity: float,
        precision: float = 0.001,
        symbol: str = ""
    ) -> float:
        """
        Round quantity to specified precision (for backtesting).

        Args:
            quantity: Original order quantity in coin units (e.g., BTC)
            precision: Minimum quantity increment (e.g., 0.001 for BTC)
            symbol: Trading symbol for logging

        Returns:
            Rounded quantity
        """
        # Round to precision increment
        rounded_quantity = round(quantity / precision) * precision

        # Calculate decimal places from precision
        if precision >= 1:
            decimal_places = 0
        else:
            decimal_places = len(str(precision).split('.')[-1])

        # Fix floating point errors
        rounded_quantity = round(rounded_quantity, decimal_places)

        if abs(rounded_quantity - quantity) > 1e-8 and symbol:
            logger.debug(
                f"Rounded order size for {symbol}: {quantity:.8f} → {rounded_quantity:.8f} "
                f"(precision={precision})"
            )

        return rounded_quantity
