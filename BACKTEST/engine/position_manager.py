"""
Position manager for backtest position lifecycle management.
"""

from datetime import datetime
from typing import Optional, Tuple
from decimal import Decimal

from BACKTEST.models.position import Position
from BACKTEST.models.trade import Trade, TradeSide, ExitReason
from shared.logging import get_logger

logger = get_logger(__name__)


class PositionManager:
    """Manages position lifecycle during backtesting."""

    def __init__(self, fee_rate: float = 0.0005):
        """
        Initialize position manager.

        Args:
            fee_rate: Trading fee rate (default 0.05%)
        """
        self.fee_rate = fee_rate
        self.current_position: Optional[Position] = None
        self.trade_counter = 0
        self.trade_history: list[Trade] = []

        logger.info(f"PositionManager initialized with fee_rate={fee_rate*100}%")

    def open_position(
        self,
        side: TradeSide,
        price: float,
        quantity: float,
        leverage: float,
        timestamp: datetime,
        investment: Optional[float] = None,
        take_profit_price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
        entry_reason: Optional[str] = None,
        entry_rsi: Optional[float] = None,
        entry_atr: Optional[float] = None,
        is_dual_side: bool = False,
        main_position_side: Optional[TradeSide] = None,
        dual_side_entry_index: Optional[int] = None,
        parent_trade_id: Optional[int] = None
    ) -> Position:
        """
        Open a new position with DCA support.

        Args:
            side: Position side (long/short)
            price: Entry price
            quantity: Position size
            leverage: Leverage multiplier
            timestamp: Entry timestamp
            investment: Investment amount in USDT (for DCA tracking)
            take_profit_price: Optional TP level
            stop_loss_price: Optional SL level
            entry_reason: Entry signal description
            entry_rsi: RSI at entry
            entry_atr: ATR at entry
            is_dual_side: Flag indicating hedge/dual-side position
            main_position_side: Main position side when hedge is opened
            dual_side_entry_index: Nth dual-side entry trigger
            parent_trade_id: Main position's trade_number if this is a hedge

        Returns:
            Opened Position object

        Raises:
            ValueError: If position already exists
        """
        if self.current_position:
            raise ValueError("Position already exists. Close current position first.")

        # Calculate initial margin
        initial_margin = (price * quantity) / leverage

        # Calculate investment if not provided
        if investment is None:
            investment = initial_margin

        # Create initial entry record
        initial_entry = {
            'price': price,
            'quantity': quantity,
            'investment': investment,
            'timestamp': timestamp,
            'reason': entry_reason or 'initial_entry',
            'dca_count': 0
        }

        position = Position(
            side=side,
            entry_timestamp=timestamp,
            entry_price=price,
            quantity=quantity,
            leverage=leverage,
            initial_margin=initial_margin,
            take_profit_price=take_profit_price,
            stop_loss_price=stop_loss_price,
            entry_reason=entry_reason,
            entry_rsi=entry_rsi,
            entry_atr=entry_atr,
            # DCA initialization
            dca_count=0,
            entry_history=[initial_entry],
            dca_levels=[],  # Will be set by backtest engine
            initial_investment=investment,
            total_investment=investment,
            last_filled_price=price,
            is_dual_side=is_dual_side,
            main_position_side=main_position_side,
            dual_side_entry_index=dual_side_entry_index,
            parent_trade_id=parent_trade_id
        )

        self.current_position = position
        self.trade_counter += 1

        logger.info(
            f"Position opened: {side.value} @ {price:.2f}, "
            f"qty={quantity:.6f}, leverage={leverage}x, investment={investment:.2f} USDT"
        )

        return position

    def close_position(
        self,
        exit_price: float,
        timestamp: datetime,
        exit_reason: ExitReason
    ) -> Optional[Trade]:
        """
        Close current position and create trade record.

        Uses average entry price for DCA positions.

        Args:
            exit_price: Exit price
            timestamp: Exit timestamp
            exit_reason: Reason for exit

        Returns:
            Trade object or None if no position open
        """
        if not self.current_position:
            logger.warning("Attempted to close position when none exists")
            return None

        pos = self.current_position

        # Use average entry price from entry history
        avg_entry_price = pos.get_average_entry_price()

        # Use current quantity (considers partial exits via remaining_quantity)
        close_quantity = pos.get_current_quantity()

        # Calculate fees
        entry_fee = avg_entry_price * close_quantity * self.fee_rate
        exit_fee = exit_price * close_quantity * self.fee_rate

        # Calculate price difference
        if pos.side == TradeSide.LONG:
            price_diff = exit_price - avg_entry_price
            pnl_percent = ((exit_price / avg_entry_price) - 1) * 100
        else:  # SHORT
            price_diff = avg_entry_price - exit_price
            pnl_percent = ((avg_entry_price / exit_price) - 1) * 100

        # Calculate P&L: price_diff * quantity * leverage - fees
        gross_pnl = price_diff * close_quantity * pos.leverage
        net_pnl = gross_pnl - (entry_fee + exit_fee)

        # Create trade record
        trade = Trade(
            trade_number=self.trade_counter,
            side=pos.side,
            entry_timestamp=pos.entry_timestamp,
            entry_price=avg_entry_price,
            entry_reason=pos.entry_reason,
            exit_timestamp=timestamp,
            exit_price=exit_price,
            exit_reason=exit_reason,
            quantity=close_quantity,
            leverage=pos.leverage,
            pnl=net_pnl,
            pnl_percent=pnl_percent,
            entry_fee=entry_fee,
            exit_fee=exit_fee,
            take_profit_price=pos.take_profit_price,
            stop_loss_price=pos.stop_loss_price,
            trailing_stop_price=pos.trailing_stop_price,
            tp1_price=getattr(pos, 'tp1_price', None),
            tp2_price=getattr(pos, 'tp2_price', None),
            tp3_price=getattr(pos, 'tp3_price', None),
            next_dca_levels=getattr(pos, 'dca_levels', []).copy() if hasattr(pos, 'dca_levels') else [],
            entry_rsi=pos.entry_rsi,
            entry_atr=pos.entry_atr,
            # DCA metadata
            dca_count=pos.dca_count,
            entry_history=pos.entry_history.copy(),
            total_investment=pos.total_investment,
            # Dual-side metadata
            is_dual_side=pos.is_dual_side,
            main_position_side=pos.main_position_side,
            dual_side_entry_index=pos.dual_side_entry_index,
            parent_trade_id=pos.parent_trade_id
        )

        logger.info(
            f"Position closed: {pos.side.value} @ {exit_price:.2f}, "
            f"avg_entry={avg_entry_price:.2f}, PNL={net_pnl:.2f} ({pnl_percent:.2f}%), "
            f"DCA_count={pos.dca_count}, reason={exit_reason.value}"
        )

        # Add to trade history
        self.trade_history.append(trade)

        # Clear current position
        self.current_position = None

        return trade

    def add_to_position(
        self,
        price: float,
        quantity: float,
        investment: float,
        timestamp: datetime,
        reason: str = 'dca_entry'
    ) -> Position:
        """
        Add to existing position (DCA entry).

        Updates average entry price, total quantity, and DCA count.

        Args:
            price: DCA entry price
            quantity: Additional quantity
            investment: Additional investment amount (USDT)
            timestamp: Entry timestamp
            reason: Entry reason (for logging)

        Returns:
            Updated position

        Raises:
            ValueError: If no position exists

        Example:
            Initial: entry_price=100, quantity=10, investment=100
            DCA 1: price=95, quantity=5, investment=50
            Result: avg_price=98.33, total_qty=15, total_investment=150
        """
        if not self.current_position:
            raise ValueError("Cannot add to position: no position exists")

        position = self.current_position

        # Create entry record
        dca_entry = {
            'price': price,
            'quantity': quantity,
            'investment': investment,
            'timestamp': timestamp,
            'reason': reason,
            'dca_count': position.dca_count + 1
        }

        # Add to entry history
        position.entry_history.append(dca_entry)

        # Update DCA count
        position.dca_count += 1

        # Update last filled price
        position.last_filled_price = price

        # Update total investment
        position.total_investment += investment

        # Recalculate average entry price and total quantity
        position.entry_price = position.get_average_entry_price()
        position.quantity = position.get_total_quantity()

        # Update initial margin based on new total investment
        position.initial_margin = position.total_investment

        logger.info(
            f"DCA entry #{position.dca_count}: {position.side.value} "
            f"{position.side.value} @ {price:.2f}, qty={quantity:.6f}, "
            f"investment={investment:.2f} USDT"
        )
        logger.info(
            f"Position updated: avg_price={position.entry_price:.2f}, "
            f"total_qty={position.quantity:.6f}, "
            f"total_investment={position.total_investment:.2f} USDT"
        )

        return position

    def update_position(self, current_price: float) -> None:
        """
        Update position with current market price.

        Args:
            current_price: Current market price
        """
        if not self.current_position:
            return

        self.current_position.update_unrealized_pnl(current_price)

    def check_exit_conditions(
        self,
        current_price: float
    ) -> Tuple[bool, Optional[ExitReason]]:
        """
        Check if position should be exited.

        Args:
            current_price: Current market price

        Returns:
            Tuple of (should_exit, exit_reason)
        """
        if not self.current_position:
            return False, None

        should_exit, reason_str = self.current_position.should_exit(current_price)

        if should_exit and reason_str:
            exit_reason = ExitReason(reason_str)
            return True, exit_reason

        return False, None

    def update_trailing_stop(
        self,
        current_price: float,
        trailing_percent: float,
        atr_multiplier: Optional[float] = None,
        atr_value: Optional[float] = None
    ) -> None:
        """
        Update trailing stop for current position.

        Args:
            current_price: Current market price
            trailing_percent: Trailing stop percentage
            atr_multiplier: Optional ATR multiplier
            atr_value: Optional current ATR value
        """
        if not self.current_position:
            return

        self.current_position.update_trailing_stop(
            current_price,
            trailing_percent,
            atr_multiplier,
            atr_value
        )

    def activate_trailing_stop(self) -> None:
        """Activate trailing stop for current position."""
        if self.current_position:
            self.current_position.trailing_stop_activated = True
            logger.info("Trailing stop activated")

    def has_position(self) -> bool:
        """Check if position exists."""
        return self.current_position is not None

    def get_position(self) -> Optional[Position]:
        """Get current position."""
        return self.current_position

    def get_trade_history(self) -> list[Trade]:
        """Get all executed trades."""
        return self.trade_history

    def partial_close_position(
        self,
        exit_price: float,
        timestamp: datetime,
        tp_level: int,
        exit_ratio: float,
        current_stop_loss: Optional[float] = None
    ) -> Optional[Trade]:
        """
        Partially close position (TP1/TP2/TP3).

        Creates a trade record for the partial exit and updates the position's remaining quantity.
        Records the stop loss price that was valid during this period.

        Args:
            exit_price: Exit price for this partial close
            timestamp: Exit timestamp
            tp_level: Which TP level (1, 2, or 3)
            exit_ratio: Ratio of position to close (0-1)
            current_stop_loss: The stop loss price that was valid during this period
                              (before break-even adjustment). If None, uses position's current SL.

        Returns:
            Trade object for the partial exit, or None if no position exists

        Example:
            Initial position: 1.0 BTC, SL=98
            TP1 with exit_ratio=0.3, current_stop_loss=98 → Close 0.3 BTC, keep 0.7 BTC (records SL=98)
            → Break-even applied: SL moves to 100 (entry price)
            TP2 with exit_ratio=0.3, current_stop_loss=100 → Close 0.3 BTC, keep 0.4 BTC (records SL=100)
            → SL moves to TP1 price (102)
            TP3 with exit_ratio=0.4, current_stop_loss=102 → Close remaining 0.4 BTC (records SL=102)
        """
        if not self.current_position:
            logger.warning("Attempted to partially close position when none exists")
            return None

        pos = self.current_position
        avg_entry_price = pos.get_average_entry_price()

        # Get current quantity (considering previous partial exits)
        current_quantity = pos.get_current_quantity()

        # Calculate quantity to close based on ORIGINAL total quantity, not remaining
        original_quantity = pos.get_total_quantity()
        close_quantity = original_quantity * exit_ratio

        # Ensure we don't close more than remaining
        if close_quantity > current_quantity:
            logger.warning(
                f"Calculated close quantity {close_quantity:.6f} exceeds remaining {current_quantity:.6f}, "
                f"adjusting to remaining quantity"
            )
            close_quantity = current_quantity

        # Calculate fees for this partial exit
        entry_fee = avg_entry_price * close_quantity * self.fee_rate
        exit_fee = exit_price * close_quantity * self.fee_rate

        # Calculate P&L for this partial exit
        if pos.side == TradeSide.LONG:
            price_diff = exit_price - avg_entry_price
            pnl_percent = ((exit_price / avg_entry_price) - 1) * 100
        else:  # SHORT
            price_diff = avg_entry_price - exit_price
            pnl_percent = ((avg_entry_price / exit_price) - 1) * 100

        gross_pnl = price_diff * close_quantity * pos.leverage
        net_pnl = gross_pnl - (entry_fee + exit_fee)

        # 🔍 DEBUG: PNL 계산 상세 로그
        logger.info(
            f"[PNL_DEBUG] TP{tp_level} calculation: "
            f"avg_entry={avg_entry_price:.2f}, exit_price={exit_price:.2f}, "
            f"price_diff={price_diff:.4f}, close_qty={close_quantity:.6f}, "
            f"leverage={pos.leverage}x, gross_pnl={gross_pnl:.4f}, "
            f"entry_fee={entry_fee:.4f}, exit_fee={exit_fee:.4f}, "
            f"net_pnl={net_pnl:.4f}"
        )

        # Determine exit reason based on TP level
        exit_reason_map = {1: ExitReason.TP1, 2: ExitReason.TP2, 3: ExitReason.TP3}
        exit_reason = exit_reason_map.get(tp_level, ExitReason.TAKE_PROFIT)

        # Use provided current_stop_loss or fall back to position's current SL
        stop_loss_for_record = current_stop_loss if current_stop_loss is not None else pos.stop_loss_price

        # Create trade record for partial exit
        trade = Trade(
            trade_number=self.trade_counter,
            side=pos.side,
            entry_timestamp=pos.entry_timestamp,
            entry_price=avg_entry_price,
            entry_reason=pos.entry_reason,
            exit_timestamp=timestamp,
            exit_price=exit_price,
            exit_reason=exit_reason,
            quantity=close_quantity,
            leverage=pos.leverage,
            pnl=net_pnl,
            pnl_percent=pnl_percent,
            entry_fee=entry_fee,
            exit_fee=exit_fee,
            take_profit_price=pos.take_profit_price,
            stop_loss_price=stop_loss_for_record,  # Use the SL that was valid during this period
            trailing_stop_price=pos.trailing_stop_price,
            tp1_price=getattr(pos, 'tp1_price', None),
            tp2_price=getattr(pos, 'tp2_price', None),
            tp3_price=getattr(pos, 'tp3_price', None),
            next_dca_levels=getattr(pos, 'dca_levels', []).copy() if hasattr(pos, 'dca_levels') else [],
            entry_rsi=pos.entry_rsi,
            entry_atr=pos.entry_atr,
            # DCA metadata
            dca_count=pos.dca_count,
            entry_history=pos.entry_history.copy(),
            total_investment=pos.total_investment,
            # Partial exit metadata
            is_partial_exit=True,
            tp_level=tp_level,
            exit_ratio=exit_ratio,
            remaining_quantity=current_quantity - close_quantity,
            # Dual-side metadata
            is_dual_side=pos.is_dual_side,
            main_position_side=pos.main_position_side,
            dual_side_entry_index=pos.dual_side_entry_index,
            parent_trade_id=pos.parent_trade_id
        )

        # Update position state
        new_remaining = current_quantity - close_quantity
        pos.remaining_quantity = new_remaining

        # Mark TP level as filled
        if tp_level == 1:
            pos.tp1_filled = True
        elif tp_level == 2:
            pos.tp2_filled = True
        elif tp_level == 3:
            pos.tp3_filled = True

        logger.info(
            f"Partial exit TP{tp_level}: {pos.side.value} @ {exit_price:.2f}, "
            f"closed={close_quantity:.6f} ({exit_ratio*100:.1f}%), "
            f"remaining={new_remaining:.6f}, "
            f"PNL={net_pnl:.2f} ({pnl_percent:.2f}%)"
        )

        # Add to trade history
        self.trade_history.append(trade)

        # If all quantity closed, clear the position
        if new_remaining < 1e-8:  # Use small epsilon for floating point comparison
            logger.info(
                f"✅ All quantity closed via partial exits: "
                f"new_remaining={new_remaining:.12f} < 1e-8, clearing position"
            )
            self.current_position = None
        else:
            logger.info(
                f"⚠️ Position still open after TP{tp_level}: "
                f"new_remaining={new_remaining:.12f} >= 1e-8, keeping position open"
            )

        return trade

    def activate_trailing_stop_after_tp(
        self,
        current_price: float,
        trailing_offset: float,
        tp_level: int
    ) -> bool:
        """
        Activate HYPERRSI-style trailing stop after TP partial exit.

        Called after a TP partial exit to activate trailing stop for remaining position.
        Mirrors HYPERRSI's activate_trailing_stop() behavior.

        Args:
            current_price: Current market price at activation
            trailing_offset: Trailing offset distance (absolute price difference)
            tp_level: TP level that triggered activation (1, 2, or 3)

        Returns:
            True if trailing stop activated, False if no position or already activated
        """
        if not self.current_position:
            logger.warning("Cannot activate trailing stop: no position exists")
            return False

        if self.current_position.trailing_stop_activated:
            logger.info("Trailing stop already activated, skipping")
            return False

        pos = self.current_position
        pos.activate_hyperrsi_trailing_stop(
            current_price=current_price,
            trailing_offset=trailing_offset,
            tp_level=tp_level
        )

        logger.info(
            f"Trailing stop activated after TP{tp_level}: "
            f"side={pos.side.value}, price={current_price:.2f}, "
            f"offset={trailing_offset:.2f}, "
            f"stop={pos.trailing_stop_price:.2f}, "
            f"remaining={pos.get_current_quantity():.6f}"
        )

        return True

    def reset(self) -> None:
        """Reset position manager state."""
        self.current_position = None
        self.trade_counter = 0
        self.trade_history = []
        logger.info("PositionManager reset to initial state")
