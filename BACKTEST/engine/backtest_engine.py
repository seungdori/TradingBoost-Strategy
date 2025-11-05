"""
Main backtest engine for running strategy simulations.
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID
import asyncio
import pandas as pd

from BACKTEST.data.data_provider import DataProvider
from BACKTEST.engine.balance_tracker import BalanceTracker
from BACKTEST.engine.position_manager import PositionManager
from BACKTEST.engine.order_simulator import OrderSimulator, SlippageModel
from BACKTEST.engine.event_logger import EventLogger, EventType
from BACKTEST.engine.dca_calculator import (
    calculate_dca_levels,
    check_dca_condition,
    calculate_dca_entry_size,
    check_rsi_condition_for_dca,
    check_trend_condition_for_dca
)
from BACKTEST.models.candle import Candle
from BACKTEST.models.result import BacktestResult
from BACKTEST.models.trade import TradeSide, ExitReason
from BACKTEST.models.position import Position
from shared.logging import get_logger

logger = get_logger(__name__)


class BacktestEngine:
    """Main backtesting engine."""

    def __init__(
        self,
        data_provider: DataProvider,
        initial_balance: float = 10000.0,
        fee_rate: float = 0.0005,
        slippage_percent: float = 0.05,
        enable_event_logging: bool = True
    ):
        """
        Initialize backtest engine.

        Args:
            data_provider: Data source provider
            initial_balance: Starting capital
            fee_rate: Trading fee rate (default 0.05%)
            slippage_percent: Slippage percentage (default 0.05%)
            enable_event_logging: Enable detailed event logging
        """
        self.data_provider = data_provider
        self.initial_balance = initial_balance
        self.fee_rate = fee_rate

        # Core components
        self.balance_tracker = BalanceTracker(initial_balance)
        self.position_manager = PositionManager(fee_rate)
        self.order_simulator = OrderSimulator(
            slippage_model=SlippageModel.PERCENTAGE,
            slippage_percent=slippage_percent
        )
        self.event_logger = EventLogger() if enable_event_logging else None

        # State
        self.is_running = False
        self.current_candle: Optional[Candle] = None
        self.strategy_params: Dict[str, Any] = {}
        self.strategy_executor = None  # Will be set in run()
        self.symbol_info: Optional[Dict[str, Any]] = None  # Symbol specifications (min_size, etc.)

        logger.info(
            f"BacktestEngine initialized: balance={initial_balance}, "
            f"fee={fee_rate*100}%, slippage={slippage_percent}%"
        )

    async def run(
        self,
        user_id: UUID,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        strategy_name: str,
        strategy_params: Dict[str, Any],
        strategy_executor  # Will be Strategy interface
    ) -> BacktestResult:
        """
        Run backtest simulation.

        Args:
            user_id: User ID
            symbol: Trading symbol
            timeframe: Timeframe
            start_date: Start date
            end_date: End date
            strategy_name: Strategy name
            strategy_params: Strategy parameters
            strategy_executor: Strategy execution instance

        Returns:
            BacktestResult with complete results
        """
        self.is_running = True
        started_at = datetime.utcnow()

        # Store symbol and strategy params for access in methods
        self.symbol = symbol
        # Use strategy executor's params (already mapped Korean → English)
        self.strategy_params = strategy_executor.params
        self.strategy_executor = strategy_executor

        logger.info(
            f"Starting backtest: {symbol} {timeframe} "
            f"from {start_date} to {end_date}"
        )

        # Fetch symbol specifications (min_size, contract_size, etc.)
        self.symbol_info = await self.data_provider.get_symbol_info(symbol)
        if self.symbol_info:
            logger.info(
                f"Symbol specifications loaded: "
                f"min_size={self.symbol_info.get('min_size')}, "
                f"contract_size={self.symbol_info.get('contract_size')}, "
                f"tick_size={self.symbol_info.get('tick_size')}"
            )
        else:
            logger.warning(
                f"Failed to load symbol specifications for {symbol}, "
                f"using defaults (min_size=1)"
            )
            self.symbol_info = {
                'symbol': symbol,
                'min_size': 1.0,
                'contract_size': 0.01,
                'tick_size': 0.01,
                'base_currency': symbol.split('-')[0]
            }

        # Set data provider on strategy for on-demand historical data loading
        if hasattr(strategy_executor, 'set_data_provider'):
            strategy_executor.set_data_provider(self.data_provider, symbol, timeframe)

        try:
            # Validate data availability
            validation = await self.data_provider.validate_data_availability(
                symbol, timeframe, start_date, end_date
            )

            if not validation["available"]:
                raise ValueError("No data available for specified period")

            if validation["coverage"] < 0.9:
                logger.warning(
                    f"Low data coverage: {validation['coverage']*100:.1f}%"
                )

            # Fetch candle data
            candles = await self.data_provider.get_candles(
                symbol, timeframe, start_date, end_date
            )

            if not candles:
                raise ValueError("No candles returned from data provider")

            logger.info(f"Processing {len(candles)} candles...")

            # Process each candle
            total_candles = len(candles)
            for idx, candle in enumerate(candles):
                self.current_candle = candle

                # Process candle
                await self._process_candle(candle, strategy_executor)

                # Progress update every 100 candles
                #if (idx + 1) % 100 == 0:
                #    progress = ((idx + 1) / total_candles) * 100
                #    logger.info(f"Progress: {progress:.1f}% ({idx + 1}/{total_candles})")

            # Check for remaining position (keep as unrealized P&L)
            unrealized_pnl = 0.0
            if self.position_manager.has_position():
                last_candle = candles[-1]
                position = self.position_manager.get_position()
                position.update_unrealized_pnl(last_candle.close)
                unrealized_pnl = position.unrealized_pnl
                logger.info(
                    f"Backtest ended with open position: {position.side.value} @ {position.entry_price:.2f}, "
                    f"current_price={last_candle.close:.2f}, unrealized_pnl={unrealized_pnl:.2f}"
                )

            # Build result
            completed_at = datetime.utcnow()
            execution_time = (completed_at - started_at).total_seconds()

            result = BacktestResult(
                user_id=user_id,
                symbol=symbol,
                timeframe=timeframe,
                start_date=start_date,
                end_date=end_date,
                strategy_name=strategy_name,
                strategy_params=strategy_params,
                started_at=started_at,
                completed_at=completed_at,
                execution_time_seconds=execution_time,
                initial_balance=self.initial_balance,
                final_balance=self.balance_tracker.current_balance,
                unrealized_pnl=unrealized_pnl,
                trades=self._get_all_trades(),
                equity_curve=self.balance_tracker.get_equity_curve()
            )

            # Calculate metrics
            result.calculate_metrics()
            result.sharpe_ratio = result.calculate_sharpe_ratio()

            # Add balance tracker stats
            balance_stats = self.balance_tracker.get_statistics()
            result.max_drawdown = balance_stats.get("max_drawdown", 0.0)
            result.max_drawdown_percent = balance_stats.get("max_drawdown_percent", 0.0)

            # Add event summary if logging enabled
            if self.event_logger:
                result.detailed_metrics = {
                    "event_summary": self.event_logger.get_event_summary(),
                    "balance_stats": balance_stats
                }

            logger.info(
                f"Backtest completed: {result.total_trades} trades, "
                f"Return: {result.total_return_percent:.2f}%, "
                f"Win rate: {result.win_rate:.2f}%"
            )

            return result

        except Exception as e:
            logger.error(f"Backtest failed: {e}")
            if self.event_logger:
                self.event_logger.log_error("Backtest execution failed", e)
            raise

        finally:
            self.is_running = False

    async def _process_candle(
        self,
        candle: Candle,
        strategy_executor
    ) -> None:
        """
        Process single candle.

        Args:
            candle: Current candle
            strategy_executor: Strategy instance
        """
        # Check if position should be closed first (TP/SL/Trailing)
        if self.position_manager.has_position():
            await self._check_exit_conditions(candle)

        # Check DCA conditions (if position still open after exit checks)
        if self.position_manager.has_position():
            await self._check_dca_conditions(candle)

        # Update position P&L if still open
        if self.position_manager.has_position():
            self.position_manager.update_position(candle.close)
            position = self.position_manager.get_position()

            # Add balance snapshot with unrealized P&L
            self.balance_tracker.add_snapshot(
                timestamp=candle.timestamp,
                position_side=position.side.value,
                position_size=position.quantity,
                unrealized_pnl=position.unrealized_pnl
            )

            # Update trailing stop if activated using strategy parameters
            if position.trailing_stop_activated:
                old_stop = position.trailing_stop_price

                # Get trailing stop parameters from strategy
                trailing_percent, atr_multiplier, atr_value = strategy_executor.get_trailing_stop_params(candle)

                self.position_manager.update_trailing_stop(
                    current_price=candle.close,
                    trailing_percent=trailing_percent,
                    atr_multiplier=atr_multiplier,
                    atr_value=atr_value
                )
                if old_stop != position.trailing_stop_price and self.event_logger:
                    self.event_logger.log_trailing_stop_update(
                        candle.timestamp,
                        old_stop,
                        position.trailing_stop_price,
                        candle.close
                    )

            # Check if trailing stop should be activated
            elif strategy_executor.should_activate_trailing_stop(position.unrealized_pnl_percent):
                self.position_manager.activate_trailing_stop()
                if self.event_logger:
                    self.event_logger.log_event(
                        event_type=EventType.TRAILING_STOP_ACTIVATED,
                        message=f"Trailing stop activated @ {candle.close:.2f}",
                        data={"unrealized_pnl_percent": position.unrealized_pnl_percent}
                    )

        else:
            # No position - check for entry signal from strategy
            signal = await strategy_executor.generate_signal(candle)

            if signal.side:  # Has entry signal (long or short)
                # Calculate position size
                quantity, leverage = strategy_executor.calculate_position_size(
                    signal,
                    self.balance_tracker.current_balance,
                    candle.close
                )

                # ✅ Round quantity to 0.001 precision (BTC unit)
                quantity = self.order_simulator.round_to_precision(
                    quantity, precision=0.001, symbol=self.symbol
                )

                # Calculate TP/SL levels
                take_profit, stop_loss = strategy_executor.calculate_tp_sl(
                    signal.side,
                    candle.close,
                    candle
                )

                # Simulate market order
                filled_price = self.order_simulator.simulate_market_order(
                    signal.side,
                    candle
                )

                # Calculate investment amount
                investment = self.balance_tracker.initial_balance * (
                    self.strategy_params.get('investment', 100) / 100
                )

                # Open position
                position = self.position_manager.open_position(
                    side=signal.side,
                    price=filled_price,
                    quantity=quantity,
                    leverage=leverage,
                    timestamp=candle.timestamp,
                    investment=investment,
                    take_profit_price=take_profit,
                    stop_loss_price=stop_loss,
                    entry_reason=signal.reason,
                    entry_rsi=signal.indicators.get("rsi"),
                    entry_atr=signal.indicators.get("atr")
                )

                # Log initial position open
                logger.info(
                    f"Position opened: {signal.side.value} @ {filled_price:.2f}, "
                    f"qty={quantity:.4f}, investment={investment:.2f} USDT"
                )

                # Calculate partial exit levels (TP1/TP2/TP3) if enabled
                has_calculate_method = hasattr(strategy_executor, 'calculate_tp_levels')
                logger.info(f"Checking TP calculation: has_calculate_tp_levels={has_calculate_method}")

                if has_calculate_method:
                    # Get ATR value from signal indicators if available
                    atr_value = signal.indicators.get("atr") if signal.indicators else None
                    logger.info(
                        f"Calculating TP levels with: side={signal.side.value}, "
                        f"entry_price={filled_price:.2f}, atr={atr_value}"
                    )

                    tp1, tp2, tp3 = strategy_executor.calculate_tp_levels(
                        signal.side,
                        filled_price,
                        atr_value=atr_value
                    )

                    logger.info(f"TP levels calculated: TP1={tp1}, TP2={tp2}, TP3={tp3}")

                    # Set TP levels on position
                    position.use_tp1 = strategy_executor.use_tp1
                    position.use_tp2 = strategy_executor.use_tp2
                    position.use_tp3 = strategy_executor.use_tp3
                    position.tp1_price = tp1
                    position.tp2_price = tp2
                    position.tp3_price = tp3
                    position.tp1_ratio = strategy_executor.tp1_ratio
                    position.tp2_ratio = strategy_executor.tp2_ratio
                    position.tp3_ratio = strategy_executor.tp3_ratio

                    logger.info(
                        f"TP flags on position: use_tp1={position.use_tp1}, "
                        f"use_tp2={position.use_tp2}, use_tp3={position.use_tp3}"
                    )

                    if any([position.use_tp1, position.use_tp2, position.use_tp3]):
                        logger.info(
                            f"Partial exits configured: "
                            f"TP1={tp1 if position.use_tp1 else 'disabled'} ({position.tp1_ratio*100:.0f}%), "
                            f"TP2={tp2 if position.use_tp2 else 'disabled'} ({position.tp2_ratio*100:.0f}%), "
                            f"TP3={tp3 if position.use_tp3 else 'disabled'} ({position.tp3_ratio*100:.0f}%)"
                        )
                    else:
                        logger.warning("TP calculation completed but all TP levels are disabled!")
                else:
                    logger.error("strategy_executor does not have 'calculate_tp_levels' method!")

                # Calculate initial DCA levels if pyramiding enabled
                if self.strategy_params.get('pyramiding_enabled', True):
                    dca_levels = calculate_dca_levels(
                        entry_price=filled_price,
                        last_filled_price=filled_price,
                        settings=self.strategy_params,
                        side=position.side.value,
                        atr_value=candle.atr if hasattr(candle, 'atr') else None,
                        current_price=candle.close
                    )
                    position.dca_levels = dca_levels

                    logger.info(
                        f"Initial DCA levels calculated: {dca_levels}, "
                        f"pyramiding_limit={self.strategy_params.get('pyramiding_limit', 3)}"
                    )

                # Log position open event
                if self.event_logger:
                    self.event_logger.log_position_open(
                        candle.timestamp,
                        signal.side.value,
                        filled_price,
                        quantity,
                        leverage,
                        signal.reason,
                        signal.indicators
                    )

                # Check if trailing stop should be activated
                if strategy_executor.should_activate_trailing_stop(0.0):
                    self.position_manager.activate_trailing_stop()

            # Add balance snapshot (with or without position)
            self.balance_tracker.add_snapshot(
                timestamp=candle.timestamp,
                position_side=None,
                position_size=0.0,
                unrealized_pnl=0.0
            )

    async def _check_exit_conditions(self, candle: Candle) -> None:
        """
        Check if position should be exited due to TP/SL/Trailing or partial exits.

        Args:
            candle: Current candle
        """
        if not self.position_manager.has_position():
            return

        position = self.position_manager.get_position()

        # Check trend reversal exit first (highest priority)
        if self.strategy_executor and hasattr(self.strategy_executor, 'use_trend_close'):
            if self.strategy_executor.use_trend_close:
                should_exit_trend = await self._check_trend_reversal_exit(candle, position)
                if should_exit_trend:
                    return  # Position already closed by trend reversal

        # Check partial exits first (TP1/TP2/TP3)
        should_exit_partial, exit_reason, tp_level = position.should_exit_partial(candle.close)

        if should_exit_partial and tp_level:
            # Get TP price and ratio for this level
            if tp_level == 1:
                tp_price = position.tp1_price
                exit_ratio = position.tp1_ratio
            elif tp_level == 2:
                tp_price = position.tp2_price
                exit_ratio = position.tp2_ratio
            elif tp_level == 3:
                tp_price = position.tp3_price
                exit_ratio = position.tp3_ratio
            else:
                logger.error(f"Invalid TP level: {tp_level}")
                return

            # Check if TP level hit using order simulator
            hit, filled_price = self.order_simulator.check_take_profit_hit(
                candle, tp_price, position.side
            )

            if hit and filled_price:
                # Calculate partial exit quantity
                partial_quantity = position.quantity * exit_ratio

                # ✅ Round partial exit quantity to 0.001 precision (BTC unit)
                rounded_quantity = self.order_simulator.round_to_precision(
                    partial_quantity, precision=0.001, symbol=self.symbol
                )

                # Skip partial exit if rounded quantity is 0 or negative
                if rounded_quantity <= 0:
                    logger.warning(
                        f"TP{tp_level} partial exit skipped: rounded quantity {rounded_quantity:.6f} "
                        f"is too small (original: {partial_quantity:.6f})"
                    )
                    return

                # Cap at position quantity (don't exceed total position)
                if rounded_quantity > position.quantity:
                    rounded_quantity = position.quantity
                    logger.info(
                        f"TP{tp_level} rounded quantity ({rounded_quantity:.6f}) exceeds position size, "
                        f"capping at full position quantity ({position.quantity:.6f})"
                    )

                # Update exit_ratio based on rounded quantity
                exit_ratio = rounded_quantity / position.quantity

                # Snapshot current stop loss BEFORE partial close (for record keeping)
                current_sl_snapshot = position.stop_loss_price

                # Partial close with the SL that was valid during this period
                trade = self.position_manager.partial_close_position(
                    exit_price=filled_price,
                    timestamp=candle.timestamp,
                    tp_level=tp_level,
                    exit_ratio=exit_ratio,
                    current_stop_loss=current_sl_snapshot
                )

                if trade:
                    self.balance_tracker.update_balance(trade.pnl, trade.total_fees)
                    if self.event_logger:
                        self.event_logger.log_event(
                            event_type=EventType.TAKE_PROFIT_HIT,
                            message=f"TP{tp_level} hit @ {filled_price:.2f} ({exit_ratio*100:.0f}% closed)",
                            data={"pnl": trade.pnl, "tp_level": tp_level, "exit_ratio": exit_ratio}
                        )
                    logger.info(
                        f"Partial exit TP{tp_level}: closed {exit_ratio*100:.0f}% @ {filled_price:.2f}, "
                        f"PNL={trade.pnl:.2f}, remaining={trade.remaining_quantity:.6f}"
                    )

                # Check if all TP levels filled - if so, position is fully closed
                if not self.position_manager.has_position():
                    logger.info("All partial exits completed, position fully closed")
                    return

                # Apply break even logic if enabled
                # 초기 SL이 None이어도 break-even은 정상 작동함
                if self.strategy_executor:
                    break_even_price = None

                    # TP1 hit → move SL to entry price
                    if tp_level == 1 and hasattr(self.strategy_executor, 'use_break_even') and self.strategy_executor.use_break_even:
                        break_even_price = position.get_average_entry_price()
                        logger.info(f"TP1 hit: Moving SL to break-even (entry price) @ {break_even_price:.2f}")

                    # TP2 hit → move SL to TP1 price
                    elif tp_level == 2 and hasattr(self.strategy_executor, 'use_break_even_tp2') and self.strategy_executor.use_break_even_tp2:
                        if position.tp1_price:
                            break_even_price = position.tp1_price
                            logger.info(f"TP2 hit: Moving SL to TP1 price @ {break_even_price:.2f}")

                    # TP3 hit → move SL to TP2 price (only if TP sum < 100%)
                    elif tp_level == 3 and hasattr(self.strategy_executor, 'use_break_even_tp3') and self.strategy_executor.use_break_even_tp3:
                        # Check if total TP ratio is less than 100%
                        total_tp_ratio = position.tp1_ratio + position.tp2_ratio + position.tp3_ratio
                        if total_tp_ratio < 0.99 and position.tp2_price:  # Allow 1% tolerance
                            break_even_price = position.tp2_price
                            logger.info(f"TP3 hit: Moving SL to TP2 price @ {break_even_price:.2f}")
                        else:
                            logger.info(f"TP3 hit: Total TP ratio ({total_tp_ratio*100:.0f}%) >= 100%, skipping break-even")

                    # Update stop loss price if break even price was set
                    # 중요: 초기 SL이 None이어도 여기서 entry_price로 설정됨
                    if break_even_price:
                        position.stop_loss_price = break_even_price
                        if self.event_logger:
                            self.event_logger.log_event(
                                event_type=EventType.STOP_LOSS_HIT,  # Reuse event type
                                message=f"Break-even activated: SL moved to {break_even_price:.2f} after TP{tp_level}",
                                data={
                                    "tp_level": tp_level,
                                    "new_sl_price": break_even_price,
                                    "reason": "break_even"
                                }
                            )

                # Check if trailing stop should be activated after this TP level
                if self.strategy_executor and hasattr(self.strategy_executor, 'trailing_stop_active') and self.strategy_executor.trailing_stop_active:
                    trailing_start_point = self.strategy_executor.trailing_start_point.lower()
                    current_tp = f"tp{tp_level}"

                    if current_tp == trailing_start_point and not position.trailing_stop_activated:
                        # Calculate trailing offset using strategy logic
                        trailing_offset = self.strategy_executor.calculate_trailing_offset(
                            side=position.side,
                            current_price=filled_price,
                            tp2_price=position.tp2_price,
                            tp3_price=position.tp3_price
                        )

                        # Activate trailing stop
                        activated = self.position_manager.activate_trailing_stop_after_tp(
                            current_price=filled_price,
                            trailing_offset=trailing_offset,
                            tp_level=tp_level
                        )

                        if activated and self.event_logger:
                            self.event_logger.log_event(
                                event_type=EventType.TRAILING_STOP_ACTIVATED,
                                message=f"Trailing stop activated after TP{tp_level}",
                                data={
                                    "tp_level": tp_level,
                                    "trailing_offset": trailing_offset,
                                    "trailing_stop_price": position.trailing_stop_price
                                }
                            )

                # Continue checking other TPs and SL (don't return here)

        # Check full take profit (backward compatibility - only if no partial exits configured)
        has_partial_exits = position.use_tp1 or position.use_tp2 or position.use_tp3
        if not has_partial_exits and position.take_profit_price:
            hit, filled_price = self.order_simulator.check_take_profit_hit(
                candle, position.take_profit_price, position.side
            )
            if hit and filled_price:
                trade = self.position_manager.close_position(
                    exit_price=filled_price,
                    timestamp=candle.timestamp,
                    exit_reason=ExitReason.TAKE_PROFIT
                )
                if trade:
                    self.balance_tracker.update_balance(trade.pnl, trade.total_fees)
                    if self.event_logger:
                        self.event_logger.log_take_profit(
                            candle.timestamp,
                            position.take_profit_price,
                            trade.pnl
                        )
                return

        # Check stop loss
        if position.stop_loss_price:
            hit, filled_price = self.order_simulator.check_stop_hit(
                candle, position.stop_loss_price, position.side
            )
            if hit and filled_price:
                trade = self.position_manager.close_position(
                    exit_price=filled_price,
                    timestamp=candle.timestamp,
                    exit_reason=ExitReason.STOP_LOSS
                )
                if trade:
                    self.balance_tracker.update_balance(trade.pnl, trade.total_fees)
                    if self.event_logger:
                        self.event_logger.log_stop_loss(
                            candle.timestamp,
                            position.stop_loss_price,
                            filled_price,
                            trade.pnl
                        )
                return

        # Check HYPERRSI-style trailing stop
        if position.trailing_stop_activated:
            # Update trailing stop price using HYPERRSI logic
            position.update_hyperrsi_trailing_stop(candle.close)

            # Check if trailing stop hit
            if position.check_hyperrsi_trailing_stop_hit(candle.close):
                # Verify with order simulator for realistic fill
                if position.trailing_stop_price:
                    hit, filled_price = self.order_simulator.check_trailing_stop_hit(
                        candle, position.trailing_stop_price, position.side
                    )
                    if hit and filled_price:
                        trade = self.position_manager.close_position(
                            exit_price=filled_price,
                            timestamp=candle.timestamp,
                            exit_reason=ExitReason.TRAILING_STOP
                        )
                        if trade:
                            self.balance_tracker.update_balance(trade.pnl, trade.total_fees)
                            if self.event_logger:
                                self.event_logger.log_event(
                                    event_type=EventType.TRAILING_STOP_HIT,
                                    message=f"Trailing stop hit @ {filled_price:.2f}",
                                    data={"pnl": trade.pnl}
                                )
                        return

    async def _check_dca_conditions(self, candle: Candle) -> None:
        """
        Check if DCA entry should be triggered.

        Args:
            candle: Current candle
        """
        if not self.position_manager.has_position():
            return

        position = self.position_manager.get_position()

        # Check if pyramiding enabled
        if not self.strategy_params.get('pyramiding_enabled', True):
            return

        # Check if DCA limit reached
        pyramiding_limit = self.strategy_params.get('pyramiding_limit', 3)
        if position.dca_count >= pyramiding_limit:
            return

        # Check if DCA levels exist
        if not position.dca_levels:
            logger.warning(
                f"No DCA levels set for position, skipping DCA check"
            )
            return

        # Check price condition
        if not check_dca_condition(
            current_price=candle.close,
            dca_levels=position.dca_levels,
            side=position.side.value,
            use_check_DCA_with_price=self.strategy_params.get('use_check_DCA_with_price', True)
        ):
            return  # Price hasn't reached DCA level

        # Check RSI condition (if enabled)
        rsi = candle.rsi if hasattr(candle, 'rsi') else None

        # If RSI is None, try to calculate it from strategy
        if rsi is None and self.strategy_executor:
            if hasattr(self.strategy_executor, 'calculate_rsi_from_history'):
                rsi = await self.strategy_executor.calculate_rsi_from_history(candle)
                if rsi is not None:
                    logger.info(f"Calculated RSI={rsi:.2f} from historical data for DCA check")
                else:
                    logger.debug(f"Failed to calculate RSI for DCA check")

        if not check_rsi_condition_for_dca(
            rsi=rsi,
            side=position.side.value,
            rsi_oversold=self.strategy_params.get('rsi_oversold', 30),
            rsi_overbought=self.strategy_params.get('rsi_overbought', 70),
            use_rsi_with_pyramiding=self.strategy_params.get('use_rsi_with_pyramiding', True)
        ):
            logger.debug(
                f"DCA blocked by RSI condition: RSI={rsi}, "
                f"side={position.side.value}"
            )
            return

        # Check trend condition (if enabled)
        # Note: Using sma and ema fields from Candle model
        ema_value = candle.ema if hasattr(candle, 'ema') and candle.ema else None
        sma_value = candle.sma if hasattr(candle, 'sma') and candle.sma else None

        # If EMA/SMA is None, try to calculate from strategy
        if (ema_value is None or sma_value is None) and self.strategy_executor:
            if hasattr(self.strategy_executor, 'calculate_trend_indicators'):
                ema_value, sma_value = await self.strategy_executor.calculate_trend_indicators(candle)
                if ema_value and sma_value:
                    logger.info(f"Calculated EMA={ema_value:.2f}, SMA={sma_value:.2f} for DCA check")

        if not check_trend_condition_for_dca(
            ema=ema_value,
            sma=sma_value,
            side=position.side.value,
            use_trend_logic=self.strategy_params.get('use_trend_logic', True)
        ):
            logger.debug(
                f"DCA blocked by trend condition: SMA={sma_value}, "
                f"EMA={ema_value}, side={position.side.value}"
            )
            return

        # All conditions met - execute DCA entry
        await self._execute_dca_entry(candle, position)

    async def _execute_dca_entry(self, candle: Candle, position: Position) -> None:
        """
        Execute DCA entry.

        Args:
            candle: Current candle
            position: Current position
        """
        # Calculate DCA entry size
        initial_contracts = position.entry_history[0]['quantity'] if position.entry_history else position.quantity
        investment, contracts = calculate_dca_entry_size(
            initial_investment=position.initial_investment,
            initial_contracts=initial_contracts,
            dca_count=position.dca_count + 1,  # Next DCA count (1-indexed)
            entry_multiplier=self.strategy_params.get('entry_multiplier', 0.5),
            current_price=candle.close,
            leverage=position.leverage
        )

        # ✅ Round DCA quantity to 0.001 precision (BTC unit)
        contracts = self.order_simulator.round_to_precision(
            contracts, precision=0.001, symbol=self.symbol
        )

        # Skip DCA entry if rounded quantity is 0 or negative
        if contracts <= 0:
            logger.warning(
                f"DCA entry #{position.dca_count + 1} skipped: rounded quantity {contracts:.6f} "
                f"is too small (calculated investment: {investment:.2f} USDT)"
            )
            return

        # Simulate order execution
        filled_price = self.order_simulator.simulate_market_order(
            position.side,
            candle
        )

        # Calculate fees
        entry_fee = investment * self.fee_rate

        # Add to position
        self.position_manager.add_to_position(
            price=filled_price,
            quantity=contracts,
            investment=investment,
            timestamp=candle.timestamp,
            reason=f'dca_{position.dca_count + 1}'
        )

        # Deduct fees from balance (use update_balance with 0 PNL and fee)
        self.balance_tracker.update_balance(pnl=0.0, fee=entry_fee)

        # Log DCA entry event
        if self.event_logger:
            self.event_logger.log_position_open(
                timestamp=candle.timestamp,
                side=position.side.value,
                entry_price=filled_price,
                quantity=contracts,
                leverage=position.leverage,
                reason=f'DCA Entry #{position.dca_count}',
                indicators={
                    'rsi': candle.rsi if hasattr(candle, 'rsi') and candle.rsi else None,
                    'sma': candle.sma if hasattr(candle, 'sma') and candle.sma else None,
                    'ema': candle.ema if hasattr(candle, 'ema') and candle.ema else None,
                    'atr': candle.atr if hasattr(candle, 'atr') and candle.atr else None
                }
            )

        # Recalculate DCA levels from new average price
        updated_position = self.position_manager.get_position()
        new_dca_levels = calculate_dca_levels(
            entry_price=updated_position.entry_price,  # Average price
            last_filled_price=updated_position.last_filled_price,
            settings=self.strategy_params,
            side=updated_position.side.value,
            atr_value=candle.atr if hasattr(candle, 'atr') else None,
            current_price=candle.close
        )
        updated_position.dca_levels = new_dca_levels

        # Recalculate TP levels from new average price
        if self.strategy_executor and hasattr(self.strategy_executor, 'calculate_tp_levels'):
            atr_value = candle.atr if hasattr(candle, 'atr') else None

            logger.info(
                f"Recalculating TP levels after DCA: new_avg={updated_position.entry_price:.2f}, "
                f"side={updated_position.side.value}"
            )

            tp1, tp2, tp3 = self.strategy_executor.calculate_tp_levels(
                updated_position.side,
                updated_position.entry_price,  # Use new average price
                atr_value=atr_value
            )

            # Update TP prices on position
            updated_position.tp1_price = tp1
            updated_position.tp2_price = tp2
            updated_position.tp3_price = tp3

            logger.info(
                f"TP levels updated after DCA: "
                f"TP1={tp1 if updated_position.use_tp1 else 'disabled'}, "
                f"TP2={tp2 if updated_position.use_tp2 else 'disabled'}, "
                f"TP3={tp3 if updated_position.use_tp3 else 'disabled'}"
            )

        logger.info(
            f"DCA entry #{updated_position.dca_count} executed: "
            f"price={filled_price:.2f}, qty={contracts:.4f}, "
            f"investment={investment:.2f} USDT, fee={entry_fee:.2f}, "
            f"new_avg_price={updated_position.entry_price:.2f}, "
            f"new_total_qty={updated_position.quantity:.4f}, "
            f"next_dca_levels={new_dca_levels}"
        )

    async def _check_trend_reversal_exit(self, candle: Candle, position: Position) -> bool:
        """
        Check if position should be closed due to strong trend reversal.

        Mirrors HYPERRSI's handle_trend_reversal_exit() logic:
        - Long position: Close when trend state == -2 (strong downtrend)
        - Short position: Close when trend state == +2 (strong uptrend)

        Args:
            candle: Current candle
            position: Current position

        Returns:
            True if position was closed due to trend reversal, False otherwise
        """
        # Calculate current trend state
        if hasattr(self.strategy_executor, 'signal_generator'):
            # Get price history from strategy
            closes = pd.Series([c.close for c in self.strategy_executor.price_history])

            if len(closes) < 20:  # Need at least 20 candles for SMA20
                return False

            trend_state = self.strategy_executor.signal_generator.calculate_trend_state(closes)

            if trend_state is None:
                return False

            # Check if strong trend reversal against position
            should_exit = False
            if position.side == TradeSide.LONG and trend_state == -2:
                # Long position in strong downtrend
                should_exit = True
                reason = "Strong downtrend reversal (state=-2)"
            elif position.side == TradeSide.SHORT and trend_state == 2:
                # Short position in strong uptrend
                should_exit = True
                reason = "Strong uptrend reversal (state=+2)"

            if should_exit:
                logger.info(
                    f"Trend reversal detected: {position.side.value} position, "
                    f"trend_state={trend_state} - Closing position"
                )

                # Close position
                trade = self.position_manager.close_position(
                    exit_price=candle.close,
                    timestamp=candle.timestamp,
                    exit_reason=ExitReason.SIGNAL  # Trend reversal signal
                )

                if trade:
                    self.balance_tracker.update_balance(trade.pnl, trade.total_fees)

                    if self.event_logger:
                        self.event_logger.log_event(
                            event_type=EventType.STOP_LOSS_HIT,  # Reuse STOP_LOSS event type
                            message=f"Trend reversal exit: {reason}",
                            data={
                                "trend_state": trend_state,
                                "pnl": trade.pnl,
                                "exit_price": candle.close
                            }
                        )

                    logger.info(
                        f"Position closed due to trend reversal: "
                        f"PNL={trade.pnl:.2f}, reason={reason}"
                    )

                return True

        return False

    def _get_all_trades(self) -> List:
        """Get all executed trades."""
        return self.position_manager.get_trade_history()

    def reset(self) -> None:
        """Reset engine to initial state."""
        self.balance_tracker.reset()
        self.position_manager.reset()
        if self.event_logger:
            self.event_logger.clear()
        self.is_running = False
        self.current_candle = None
        self.strategy_executor = None
        logger.info("BacktestEngine reset to initial state")
