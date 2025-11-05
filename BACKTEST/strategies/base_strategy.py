"""
Base strategy interface for backtesting.
"""

from abc import ABC, abstractmethod
from typing import Optional, Tuple, Dict, Any
from datetime import datetime

from BACKTEST.models.candle import Candle
from BACKTEST.models.trade import TradeSide
from shared.logging import get_logger

logger = get_logger(__name__)


class TradingSignal:
    """Trading signal representation."""

    def __init__(
        self,
        side: Optional[TradeSide],
        reason: str,
        confidence: float = 1.0,
        indicators: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize trading signal.

        Args:
            side: Trade side (long/short) or None for no signal
            reason: Signal generation reason
            confidence: Signal confidence (0.0 to 1.0)
            indicators: Indicator values at signal time
        """
        self.side = side
        self.reason = reason
        self.confidence = confidence
        self.indicators = indicators or {}
        self.timestamp = datetime.utcnow()

    @property
    def is_long(self) -> bool:
        """Check if signal is long."""
        return self.side == TradeSide.LONG

    @property
    def is_short(self) -> bool:
        """Check if signal is short."""
        return self.side == TradeSide.SHORT

    @property
    def is_neutral(self) -> bool:
        """Check if signal is neutral (no trade)."""
        return self.side is None


class BaseStrategy(ABC):
    """
    Abstract base class for trading strategies.

    Strategies can optionally support DCA (Dollar Cost Averaging) / pyramiding
    by implementing validate_dca_params() and handling additional entry logic.
    """

    def __init__(self, params: Dict[str, Any]):
        """
        Initialize strategy.

        Args:
            params: Strategy parameters
        """
        self.params = params
        self.name = self.__class__.__name__
        logger.info(f"Strategy {self.name} initialized with params: {params}")

    @abstractmethod
    def generate_signal(self, candle: Candle) -> TradingSignal:
        """
        Generate trading signal for current candle.

        Args:
            candle: Current candle data with indicators

        Returns:
            TradingSignal object
        """
        pass

    @abstractmethod
    def calculate_position_size(
        self,
        signal: TradingSignal,
        current_balance: float,
        current_price: float
    ) -> Tuple[float, float]:
        """
        Calculate position size and leverage.

        Args:
            signal: Trading signal
            current_balance: Current account balance
            current_price: Current market price

        Returns:
            Tuple of (quantity, leverage)
        """
        pass

    @abstractmethod
    def calculate_tp_sl(
        self,
        side: TradeSide,
        entry_price: float,
        candle: Candle
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Calculate take profit and stop loss levels.

        Args:
            side: Position side
            entry_price: Entry price
            candle: Current candle with indicators

        Returns:
            Tuple of (take_profit_price, stop_loss_price)
        """
        pass

    def should_close_position(
        self,
        candle: Candle,
        current_side: TradeSide,
        unrealized_pnl_percent: float
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if position should be closed based on strategy logic.

        Args:
            candle: Current candle
            current_side: Current position side
            unrealized_pnl_percent: Current unrealized P&L percentage

        Returns:
            Tuple of (should_close, reason)
        """
        # Default implementation: no signal-based exit
        # Override in subclass for strategy-specific logic
        return False, None

    def should_activate_trailing_stop(
        self,
        unrealized_pnl_percent: float
    ) -> bool:
        """
        Check if trailing stop should be activated.

        Args:
            unrealized_pnl_percent: Current unrealized P&L percentage

        Returns:
            True if trailing stop should be activated
        """
        # Default: activate at break-even or profit
        return unrealized_pnl_percent >= 0

    def get_trailing_stop_params(
        self,
        candle: Candle
    ) -> Tuple[float, Optional[float], Optional[float]]:
        """
        Get trailing stop parameters.

        Args:
            candle: Current candle with indicators

        Returns:
            Tuple of (trailing_percent, atr_multiplier, atr_value)
        """
        # Default: 2% trailing stop
        trailing_percent = self.params.get("trailing_stop_percent", 2.0)

        # ATR-based trailing if available
        atr_multiplier = None
        atr_value = None

        if candle.atr and self.params.get("use_atr_trailing", False):
            atr_multiplier = self.params.get("atr_trailing_multiplier", 2.0)
            atr_value = candle.atr

        return trailing_percent, atr_multiplier, atr_value

    def validate_params(self) -> bool:
        """
        Validate strategy parameters.

        Returns:
            True if parameters are valid

        Raises:
            ValueError: If parameters are invalid
        """
        # Override in subclass for specific validation
        return True

    def validate_dca_params(self, params: Dict[str, Any]) -> bool:
        """
        Validate DCA/pyramiding parameters if strategy supports them.

        Override in subclass to implement DCA-specific validation.
        Default implementation performs no validation.

        Args:
            params: Strategy parameters dictionary

        Returns:
            True if parameters are valid

        Raises:
            ValueError: If parameters are invalid
        """
        return True

    def get_required_indicators(self) -> list[str]:
        """
        Get list of required indicators for this strategy.

        Returns:
            List of indicator names
        """
        # Override in subclass
        return []

    def __repr__(self) -> str:
        """String representation."""
        return f"{self.name}(params={self.params})"
