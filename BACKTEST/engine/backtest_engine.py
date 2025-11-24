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
from BACKTEST.engine.dual_side_utils import (
    merge_dual_side_params,
    should_create_dual_side_position,
    calculate_dual_side_quantity,
    calculate_dual_side_tp_price,
    calculate_dual_side_sl_price,
    can_add_dual_side_position,
    should_close_main_on_hedge_tp,
    should_close_dual_on_trend,
    should_close_dual_on_main_sl
)

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
        self.dual_position_manager = PositionManager(fee_rate)
        self.order_simulator = OrderSimulator(
            slippage_model=SlippageModel.PERCENTAGE,
            slippage_percent=slippage_percent
        )
        self.event_logger = EventLogger() if enable_event_logging else None

        # State
        self.is_running = False
        self.current_candle: Optional[Candle] = None
        self.strategy_params: Dict[str, Any] = {}
        self.dual_side_params: Dict[str, Any] = {}
        self.dual_entry_count: int = 0
        self.strategy_executor = None  # Will be set in run()
        self.symbol_info: Optional[Dict[str, Any]] = None  # Symbol specifications (min_size, etc.)

        logger.info(
            f"BacktestEngine initialized: balance={initial_balance}, "
            f"fee={fee_rate*100}%, slippage={slippage_percent}%"
        )

    def _get_fallback_symbol_specs(self, base_currency: str) -> dict:
        """
        Get fallback symbol specifications based on base currency.

        These are approximate values used when API fails to load symbol info.
        Real values from OKX API should be used whenever possible.

        Args:
            base_currency: Base currency symbol (e.g., "BTC", "ETH", "SOL")

        Returns:
            dict with min_size, contract_size, tick_size
        """
        # Symbol-specific fallback mapping (OKX USDT-SWAP typical values)
        # Source: https://www.okx.com/trade-market/info/swap
        fallback_map = {
            # Tier 1: High-value coins
            'BTC': {'min_size': 1, 'contract_size': 0.001, 'tick_size': 0.1},
            'ETH': {'min_size': 1, 'contract_size': 0.01, 'tick_size': 0.01},

            # Tier 2: Mid-value coins
            'SOL': {'min_size': 1, 'contract_size': 1, 'tick_size': 0.001},
            'BNB': {'min_size': 1, 'contract_size': 0.1, 'tick_size': 0.01},
            'ADA': {'min_size': 1, 'contract_size': 10, 'tick_size': 0.0001},
            'AVAX': {'min_size': 1, 'contract_size': 1, 'tick_size': 0.001},
            'MATIC': {'min_size': 1, 'contract_size': 10, 'tick_size': 0.0001},
            'DOT': {'min_size': 1, 'contract_size': 1, 'tick_size': 0.001},
            'LINK': {'min_size': 1, 'contract_size': 1, 'tick_size': 0.001},

            # Tier 3: Lower-value coins
            'DOGE': {'min_size': 1, 'contract_size': 100, 'tick_size': 0.00001},
            'SHIB': {'min_size': 1, 'contract_size': 1000000, 'tick_size': 0.0000001},
            'XRP': {'min_size': 1, 'contract_size': 10, 'tick_size': 0.0001},
        }

        # Return mapped value or generic default
        if base_currency in fallback_map:
            return fallback_map[base_currency]
        else:
            # Generic fallback for unknown symbols
            logger.warning(
                f"No fallback specs for {base_currency}, using generic default"
            )
            return {
                'min_size': 1,
                'contract_size': 1,  # Generic: 1 coin per contract
                'tick_size': 0.001
            }

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
        self.timeframe = timeframe
        # Use strategy executor's params (already mapped Korean → English)
        self.strategy_params = strategy_executor.params
        self.strategy_executor = strategy_executor
        self.dual_side_params = merge_dual_side_params(self.strategy_params)
        self.dual_entry_count = 0

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
            # Use symbol-specific fallback values
            base_currency = symbol.split('-')[0] if '-' in symbol else 'BTC'
            fallback_specs = self._get_fallback_symbol_specs(base_currency)

            logger.warning(
                f"Failed to load symbol specifications for {symbol}, "
                f"using fallback: min_size={fallback_specs['min_size']} contract, "
                f"contract_size={fallback_specs['contract_size']} {base_currency}"
            )
            self.symbol_info = {
                'symbol': symbol,
                'min_size': fallback_specs['min_size'],
                'contract_size': fallback_specs['contract_size'],
                'tick_size': fallback_specs['tick_size'],
                'base_currency': base_currency
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
            last_candle = candles[-1]
            if self.position_manager.has_position():
                position = self.position_manager.get_position()
                position.update_unrealized_pnl(last_candle.close)
                unrealized_pnl += position.unrealized_pnl
                logger.warning(
                    f"🚨 [MAIN POSITION NOT CLOSED] Backtest ended with open position: "
                    f"side={position.side.value}, entry_price={position.entry_price:.2f}, "
                    f"current_price={last_candle.close:.2f}, "
                    f"total_qty={position.get_total_quantity():.6f}, "
                    f"remaining_qty={position.get_current_quantity():.6f}, "
                    f"unrealized_pnl={position.unrealized_pnl:.2f}, "
                    f"dca_count={position.dca_count}, "
                    f"tp1_filled={position.tp1_filled}, tp2_filled={position.tp2_filled}, tp3_filled={position.tp3_filled}"
                )

            if self.dual_position_manager.has_position():
                dual_position = self.dual_position_manager.get_position()
                dual_position.update_unrealized_pnl(last_candle.close)
                unrealized_pnl += dual_position.unrealized_pnl
                logger.warning(
                    f"🚨 [DUAL POSITION NOT CLOSED] Backtest ended with open dual position: "
                    f"side={dual_position.side.value}, entry_price={dual_position.entry_price:.2f}, "
                    f"current_price={last_candle.close:.2f}, "
                    f"total_qty={dual_position.get_total_quantity():.6f}, "
                    f"remaining_qty={dual_position.get_current_quantity():.6f}, "
                    f"unrealized_pnl={dual_position.unrealized_pnl:.2f}, "
                    f"dca_count={dual_position.dca_count}"
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

        # Check dual-side exits (hedge TP/SL)
        if self.dual_position_manager.has_position():
            await self._check_dual_exit_conditions(candle)

        # Check DCA conditions (if position still open after exit checks)
        if self.position_manager.has_position():
            await self._check_dca_conditions(candle)

        # Update position P&L and trailing stop if still open
        if self.position_manager.has_position():
            position = self.position_manager.get_position()
            self.position_manager.update_position(candle.close)

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
                logger.info(f"✅ Entry signal detected: {signal.side.value}, reason: {signal.reason}")

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

                # Check minimum order size (following project pattern: min_size * contract_size)
                min_size_contracts = self.symbol_info.get('min_size', 1) if self.symbol_info else 1
                contract_size = self.symbol_info.get('contract_size', 0.001) if self.symbol_info else 0.001
                base_currency = self.symbol_info.get('base_currency', 'BTC') if self.symbol_info else 'BTC'
                minimum_qty = min_size_contracts * contract_size  # e.g., 1 * 0.001 = 0.001 BTC

                if quantity <= 0 or quantity < minimum_qty:
                    logger.warning(
                        f"Entry signal skipped: {quantity:.6f} {base_currency} < minimum {minimum_qty:.6f} {base_currency} "
                        f"(min_size={min_size_contracts} contracts, contract_size={contract_size})"
                    )
                    # Skip this entry and continue to next candle
                    self._record_snapshot(candle)
                    return

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
                self.dual_entry_count = 0  # Reset hedge counter for new trade

                # Calculate partial exit levels (TP1/TP2/TP3) if enabled
                has_calculate_method = hasattr(strategy_executor, 'calculate_tp_levels')

                if has_calculate_method:
                    # Get ATR value from signal indicators if available
                    atr_value = signal.indicators.get("atr") if signal.indicators else None

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
        self._record_snapshot(candle)

    async def _check_exit_conditions(self, candle: Candle) -> None:
        """
        Check if position should be exited due to TP/SL/Trailing or partial exits.

        Args:
            candle: Current candle
        """
        if not self.position_manager.has_position():
            return

        position = self.position_manager.get_position()

        # Update trailing stop FIRST (before any exit checks)
        # This ensures trailing stop tracks price even if TP/SL hit on same candle
        if position.trailing_stop_activated:
            position.update_hyperrsi_trailing_stop(candle.close)

        # Check trend reversal exit first (highest priority)
        if self.strategy_executor and hasattr(self.strategy_executor, 'use_trend_close'):
            if self.strategy_executor.use_trend_close:
                #logger.info(f"[TREND_EXIT] use_trend_close=True, calling _check_trend_reversal_exit")
                should_exit_trend = await self._check_trend_reversal_exit(candle, position)
                if should_exit_trend:
                    logger.info(f"[TREND_EXIT] Position closed by trend reversal at {candle.timestamp}")
                    return  # Position already closed by trend reversal

        # Check HYPERRSI-style trailing stop BEFORE TP3 (when active)
        # Trailing stop is a protective exit that takes priority over aggressive TP3
        # Always check with order simulator (uses candle low/high) instead of just close
        if position.trailing_stop_activated and position.trailing_stop_price:
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
                    self._handle_dual_after_main_close(trade.exit_reason, candle, filled_price)
                return

        # Check partial exits (TP1/TP2/TP3)
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

                # Check minimum order size (following project pattern: min_size * contract_size)
                min_size_contracts = self.symbol_info.get('min_size', 1) if self.symbol_info else 1
                contract_size = self.symbol_info.get('contract_size', 0.001) if self.symbol_info else 0.001
                base_currency = self.symbol_info.get('base_currency', 'BTC') if self.symbol_info else 'BTC'
                minimum_qty = min_size_contracts * contract_size  # e.g., 1 * 0.001 = 0.001 BTC

                # Skip partial exit if below minimum
                if rounded_quantity <= 0 or rounded_quantity < minimum_qty:
                    logger.warning(
                        f"TP{tp_level} partial exit skipped: {rounded_quantity:.6f} {base_currency} < minimum {minimum_qty:.6f} {base_currency} "
                        f"(original: {partial_quantity:.6f} {base_currency}, min_size={min_size_contracts} contracts, contract_size={contract_size})"
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
                    self._handle_dual_after_main_close(trade.exit_reason, candle, filled_price)
                    return

                # Apply break even logic if enabled
                # 초기 SL이 None이어도 break-even은 정상 작동함
                if self.strategy_executor:
                    break_even_price = None

                    # TP1 hit → move SL to entry price
                    if tp_level == 1 and hasattr(self.strategy_executor, 'use_break_even') and self.strategy_executor.use_break_even:
                        break_even_price = position.get_average_entry_price()
                        #logger.info(f"TP1 hit: Moving SL to break-even (entry price) @ {break_even_price:.2f}")

                    # TP2 hit → move SL to TP1 price
                    elif tp_level == 2 and hasattr(self.strategy_executor, 'use_break_even_tp2') and self.strategy_executor.use_break_even_tp2:
                        if position.tp1_price:
                            break_even_price = position.tp1_price
                            #logger.info(f"TP2 hit: Moving SL to TP1 price @ {break_even_price:.2f}")

                    # TP3 hit → move SL to TP2 price (only if TP sum < 100%)
                    elif tp_level == 3 and hasattr(self.strategy_executor, 'use_break_even_tp3') and self.strategy_executor.use_break_even_tp3:
                        # Check if total TP ratio is less than 100%
                        total_tp_ratio = position.tp1_ratio + position.tp2_ratio + position.tp3_ratio
                        if total_tp_ratio < 0.99 and position.tp2_price:  # Allow 1% tolerance
                            break_even_price = position.tp2_price
                            #logger.info(f"TP3 hit: Moving SL to TP2 price @ {break_even_price:.2f}")
                        #else:
                        #    logger.info(f"TP3 hit: Total TP ratio ({total_tp_ratio*100:.0f}%) >= 100%, skipping break-even")

                    # Update stop loss price if break even price was set
                    # 중요: 초기 SL이 None이어도 여기서 entry_price로 설정됨
                    if break_even_price:
                        position.stop_loss_price = break_even_price
                        #if self.event_logger:
                        #    self.event_logger.log_event(
                        #        event_type=EventType.STOP_LOSS_HIT,  # Reuse event type
                        #        message=f"Break-even activated: SL moved to {break_even_price:.2f} after TP{tp_level}",
                        #        data={
                        #            "tp_level": tp_level,
                        #            "new_sl_price": break_even_price,
                        #            "reason": "break_even"
                        #        }
                        #    )

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
                    self._handle_dual_after_main_close(trade.exit_reason, candle, filled_price)
                return

        # Check stop loss (distinguish break-even from regular stop loss)
        if position.stop_loss_price:
            # Determine if this is break-even or regular stop loss
            avg_entry = position.get_average_entry_price()
            is_break_even = False

            if position.side == TradeSide.LONG:
                # LONG: break-even if SL >= entry price
                is_break_even = position.stop_loss_price >= avg_entry
            else:
                # SHORT: break-even if SL <= entry price
                is_break_even = position.stop_loss_price <= avg_entry

            # Skip regular stop loss check if use_sl=False
            # But always check break-even (independent of use_sl setting)
            if not is_break_even:
                # Regular stop loss - only check if enabled
                if not (self.strategy_executor and hasattr(self.strategy_executor, 'use_sl') and self.strategy_executor.use_sl):
                    return  # Skip regular stop loss check

            # Check if stop loss hit
            hit, filled_price = self.order_simulator.check_stop_hit(
                candle, position.stop_loss_price, position.side
            )

            if hit and filled_price:
                # For break-even, use exact stop_loss_price (no slippage)
                if is_break_even:
                    filled_price = position.stop_loss_price

                exit_reason = ExitReason.BREAK_EVEN if is_break_even else ExitReason.STOP_LOSS

                trade = self.position_manager.close_position(
                    exit_price=filled_price,
                    timestamp=candle.timestamp,
                    exit_reason=exit_reason
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
                    self._handle_dual_after_main_close(trade.exit_reason, candle, filled_price)
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
        pyramiding_enabled = self.strategy_params.get('pyramiding_enabled', True)
        if not pyramiding_enabled:
            return

        # Check if DCA limit reached
        pyramiding_limit = self.strategy_params.get('pyramiding_limit', 3)
        if position.dca_count >= pyramiding_limit:
            logger.debug(
                f"[DCA] DCA limit reached: "
                f"count={position.dca_count}, limit={pyramiding_limit}"
            )
            return

        # Check if DCA levels exist
        if not position.dca_levels:
            logger.warning(
                f"[DCA] No DCA levels set for position, skipping DCA check"
            )
            return



        # Check price condition
        price_check_result = check_dca_condition(
            current_price=candle.close,
            dca_levels=position.dca_levels,
            side=position.side.value,
            use_check_DCA_with_price=self.strategy_params.get('use_check_DCA_with_price', True)
        )

        if not price_check_result:
            logger.debug(
                f"[DCA] Price condition NOT met: "
                f"current={candle.close:.2f}, "
                f"next_dca_level={position.dca_levels[0]:.2f}, "
                f"side={position.side.value}, "
                f"use_check_DCA_with_price={self.strategy_params.get('use_check_DCA_with_price', True)}"
            )
            return  # Price hasn't reached DCA level



        # Check RSI condition (if enabled)
        rsi = candle.rsi if hasattr(candle, 'rsi') else None

        # If RSI is None, try to calculate it from strategy
        if rsi is None and self.strategy_executor:
            if hasattr(self.strategy_executor, 'calculate_rsi_from_history'):
                rsi = await self.strategy_executor.calculate_rsi_from_history(candle)

        use_rsi_with_pyramiding = self.strategy_params.get('use_rsi_with_pyramiding', True)
        rsi_check_result = check_rsi_condition_for_dca(
            rsi=rsi,
            side=position.side.value,
            rsi_oversold=self.strategy_params.get('rsi_oversold', 30),
            rsi_overbought=self.strategy_params.get('rsi_overbought', 70),
            use_rsi_with_pyramiding=use_rsi_with_pyramiding
        )

        if not rsi_check_result:

            return


        # Check trend condition (if enabled)
        # Note: Using sma and ema fields from Candle model
        ema_value = candle.ema if hasattr(candle, 'ema') and candle.ema else None
        sma_value = candle.sma if hasattr(candle, 'sma') and candle.sma else None

        # If EMA/SMA is None, try to calculate from strategy
        if (ema_value is None or sma_value is None) and self.strategy_executor:
            if hasattr(self.strategy_executor, 'calculate_trend_indicators'):
                ema_value, sma_value = await self.strategy_executor.calculate_trend_indicators(candle)
                #if ema_value and sma_value:
                #    logger.info(f"[DCA] Calculated EMA={ema_value:.2f}, SMA={sma_value:.2f} for DCA check")

        # Get trend_state from candle (PineScript indicator)
        trend_state = candle.trend_state if hasattr(candle, 'trend_state') else None

        use_trend_logic = self.strategy_params.get('use_trend_logic', True)
        trend_check_result = check_trend_condition_for_dca(
            ema=ema_value,
            sma=sma_value,
            side=position.side.value,
            use_trend_logic=use_trend_logic,
            trend_state=trend_state
        )

        if not trend_check_result:

            return
        else:
            logger.debug(
                f"[DCA] ✅ Trend condition MET: "
                f"trend_state={trend_state}, EMA={ema_value}, SMA={sma_value}, use_trend_logic={use_trend_logic}"
            )

        # All conditions met - execute DCA entry
        logger.info(
            f"[DCA] 🎯 ALL CONDITIONS MET - Executing DCA entry at price {candle.close:.2f}"
        )
        await self._execute_dca_entry(candle, position)

    async def _execute_dca_entry(self, candle: Candle, position: Position) -> None:
        """
        Execute DCA entry.

        Args:
            candle: Current candle
            position: Current position
        """
        logger.info(
            f"[DCA] 📍 Starting DCA execution: "
            f"current_price={candle.close:.2f}, "
            f"avg_entry={position.get_average_entry_price():.2f}, "
            f"current_dca_count={position.dca_count}"
        )

        # Calculate DCA entry size
        initial_contracts = position.entry_history[0]['quantity'] if position.entry_history else position.quantity
        investment, contracts = calculate_dca_entry_size(
            initial_investment=position.initial_investment,
            initial_contracts=initial_contracts,
            dca_count=position.dca_count + 1,  # Next DCA count (1-indexed)
            entry_multiplier=self.strategy_params.get('entry_multiplier', 1.6),
            current_price=candle.close,
            leverage=position.leverage
        )


        # ✅ Round DCA quantity to 0.001 precision (BTC unit)
        contracts = self.order_simulator.round_to_precision(
            contracts, precision=0.001, symbol=self.symbol
        )

        # Get minimum order size (following project pattern: min_size * contract_size)
        min_size_contracts = self.symbol_info.get('min_size', 1) if self.symbol_info else 1
        contract_size = self.symbol_info.get('contract_size', 0.001) if self.symbol_info else 0.001
        base_currency = self.symbol_info.get('base_currency', 'BTC') if self.symbol_info else 'BTC'
        minimum_qty = min_size_contracts * contract_size  # e.g., 1 * 0.001 = 0.001 BTC

        # Skip DCA entry if below minimum
        if contracts <= 0 or contracts < minimum_qty:
            logger.warning(
                f"[DCA] ❌ DCA entry #{position.dca_count + 1} SKIPPED: {contracts:.6f} {base_currency} < minimum {minimum_qty:.6f} {base_currency} "
                f"(min_size={min_size_contracts} contracts, contract_size={contract_size}, calculated investment: {investment:.2f} USDT)"
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
                f"[DCA] Recalculating TP levels after DCA: new_avg={updated_position.entry_price:.2f}, "
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
                f"[DCA] TP levels updated after DCA: "
                f"TP1={tp1 if updated_position.use_tp1 else 'disabled'}, "
                f"TP2={tp2 if updated_position.use_tp2 else 'disabled'}, "
                f"TP3={tp3 if updated_position.use_tp3 else 'disabled'}"
            )

        await self._handle_dual_side_after_main_dca(candle, updated_position)

        logger.info(
            f"[DCA] ✅ DCA entry #{updated_position.dca_count} EXECUTED: "
            f"price={filled_price:.2f}, qty={contracts:.4f}, "
            f"investment={investment:.2f} USDT, fee={entry_fee:.2f}, "
            f"new_avg_price={updated_position.entry_price:.2f}, "
            f"new_total_qty={updated_position.quantity:.4f}, "
            f"next_dca_levels={[f'{level:.2f}' for level in new_dca_levels]}"
        )

    async def _handle_dual_side_after_main_dca(self, candle: Candle, main_position: Position) -> None:
        """
        Trigger or update dual-side entries after a main DCA fill.
        """
        if not self.dual_side_params.get('use_dual_side_entry'):
            return

        # Always keep hedge TP/SL aligned with the latest main state
        self._update_dual_targets_from_main(main_position)

        current_dca_count = main_position.dca_count
        is_last_dca = self._is_last_main_dca(main_position)
        if not should_create_dual_side_position(current_dca_count, self.dual_side_params):
            return

        if not can_add_dual_side_position(self.dual_entry_count, self.dual_side_params):
            logger.info(
                f"[DUAL] Entry limit reached: "
                f"count={self.dual_entry_count}, "
                f"limit={self.dual_side_params.get('dual_side_pyramiding_limit')}"
            )
            return

        opposite_side = TradeSide.SHORT if main_position.side == TradeSide.LONG else TradeSide.LONG

        quantity = calculate_dual_side_quantity(main_position.get_current_quantity(), self.dual_side_params)
        quantity = self.order_simulator.round_to_precision(quantity, precision=0.001, symbol=self.symbol)

        min_size_contracts = self.symbol_info.get('min_size', 1) if self.symbol_info else 1
        contract_size = self.symbol_info.get('contract_size', 0.001) if self.symbol_info else 0.001
        base_currency = self.symbol_info.get('base_currency', 'BTC') if self.symbol_info else 'BTC'
        minimum_qty = min_size_contracts * contract_size

        if quantity <= 0 or quantity < minimum_qty:
            logger.warning(
                f"[DUAL] Hedge entry skipped: {quantity:.6f} {base_currency} < "
                f"minimum {minimum_qty:.6f} {base_currency} "
                f"(min_size={min_size_contracts} contracts, contract_size={contract_size})"
            )
            return

        filled_price = self.order_simulator.simulate_market_order(opposite_side, candle)
        tp_price = calculate_dual_side_tp_price(
            entry_price=filled_price,
            side=opposite_side,
            params=self.dual_side_params,
            main_position_sl_price=self._get_main_stop_reference(main_position),
            last_main_dca_price=main_position.last_filled_price,
            is_last_main_dca=is_last_dca
        )
        main_tp_prices = {
            'tp1': main_position.tp1_price,
            'tp2': main_position.tp2_price,
            'tp3': main_position.tp3_price
        }
        sl_price = calculate_dual_side_sl_price(
            entry_price=filled_price,
            side=opposite_side,
            params=self.dual_side_params,
            main_tp_prices=main_tp_prices,
            is_last_main_dca=is_last_dca
        )

        leverage = main_position.leverage
        investment = (filled_price * quantity) / leverage
        entry_fee = investment * self.fee_rate

        if not self.dual_position_manager.has_position():
            self.dual_position_manager.open_position(
                side=opposite_side,
                price=filled_price,
                quantity=quantity,
                leverage=leverage,
                timestamp=candle.timestamp,
                investment=investment,
                take_profit_price=tp_price,
                stop_loss_price=sl_price,
                entry_reason="dual_side_entry",
                is_dual_side=True,
                main_position_side=main_position.side,
                dual_side_entry_index=self.dual_entry_count + 1,
                parent_trade_id=self.position_manager.trade_counter
            )
        else:
            self.dual_position_manager.add_to_position(
                price=filled_price,
                quantity=quantity,
                investment=investment,
                timestamp=candle.timestamp,
                reason=f'dual_side_{self.dual_entry_count + 1}'
            )
            dual_position = self.dual_position_manager.get_position()
            dual_position.take_profit_price = tp_price
            dual_position.stop_loss_price = sl_price

        self.dual_entry_count += 1
        self.balance_tracker.update_balance(pnl=0.0, fee=entry_fee)

        if self.event_logger:
            self.event_logger.log_event(
                event_type=EventType.POSITION_OPENED,
                message=f"Dual-side {'open' if self.dual_entry_count == 1 else 'add'} @ {filled_price:.2f}",
                data={
                    "side": opposite_side.value,
                    "qty": quantity,
                    "tp": tp_price,
                    "sl": sl_price,
                    "dca_index": current_dca_count
                }
            )

    def _update_dual_targets_from_main(self, main_position: Position) -> None:
        """
        Refresh hedge TP/SL after main TP/SL or DCA changes.
        """
        if not self.dual_position_manager.has_position():
            return

        dual_position = self.dual_position_manager.get_position()
        main_tp_prices = {
            'tp1': main_position.tp1_price,
            'tp2': main_position.tp2_price,
            'tp3': main_position.tp3_price
        }

        dual_position.take_profit_price = calculate_dual_side_tp_price(
            entry_price=dual_position.entry_price,
            side=dual_position.side,
            params=self.dual_side_params,
            main_position_sl_price=self._get_main_stop_reference(main_position),
            last_main_dca_price=main_position.last_filled_price,
            is_last_main_dca=self._is_last_main_dca(main_position)
        )
        dual_position.stop_loss_price = calculate_dual_side_sl_price(
            entry_price=dual_position.entry_price,
            side=dual_position.side,
            params=self.dual_side_params,
            main_tp_prices=main_tp_prices,
            is_last_main_dca=self._is_last_main_dca(main_position)
        )

    async def _check_dual_exit_conditions(self, candle: Candle) -> None:
        """
        Check TP/SL for dual-side hedge position.
        """
        if not self.dual_position_manager.has_position():
            return

        position = self.dual_position_manager.get_position()

        # Check take profit
        if position.take_profit_price:
            hit, filled_price = self.order_simulator.check_take_profit_hit(
                candle, position.take_profit_price, position.side
            )
            if hit and filled_price:
                trade = self.dual_position_manager.close_position(
                    exit_price=filled_price,
                    timestamp=candle.timestamp,
                    exit_reason=ExitReason.HEDGE_TP
                )
                if trade:
                    self.balance_tracker.update_balance(trade.pnl, trade.total_fees)
                    if self.event_logger:
                        self.event_logger.log_event(
                            event_type=EventType.TAKE_PROFIT_HIT,
                            message=f"Dual-side TP hit @ {filled_price:.2f}",
                            data={"pnl": trade.pnl}
                        )

                    if should_close_main_on_hedge_tp(self.dual_side_params) and self.position_manager.has_position():
                        main_trade = self.position_manager.close_position(
                            exit_price=filled_price,
                            timestamp=candle.timestamp,
                            exit_reason=ExitReason.HEDGE_TP
                        )
                        if main_trade:
                            self.balance_tracker.update_balance(main_trade.pnl, main_trade.total_fees)
                            self._handle_dual_after_main_close(
                                main_trade.exit_reason,
                                candle,
                                filled_price,
                                close_dual_position=False
                            )
                return

        # Check stop loss
        if position.stop_loss_price:
            hit, filled_price = self.order_simulator.check_stop_hit(
                candle, position.stop_loss_price, position.side
            )
            if hit and filled_price:
                trade = self.dual_position_manager.close_position(
                    exit_price=filled_price,
                    timestamp=candle.timestamp,
                    exit_reason=ExitReason.HEDGE_SL
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

    def _close_dual_position(
        self,
        exit_price: float,
        timestamp: datetime,
        reason: ExitReason
    ):
        """
        Close dual-side position and update balance/event log.
        """
        if not self.dual_position_manager.has_position():
            return None

        trade = self.dual_position_manager.close_position(
            exit_price=exit_price,
            timestamp=timestamp,
            exit_reason=reason
        )

        if trade:
            self.balance_tracker.update_balance(trade.pnl, trade.total_fees)
            if self.event_logger:
                self.event_logger.log_event(
                    event_type=EventType.POSITION_CLOSED,
                    message=f"Dual-side position closed ({reason.value}) @ {exit_price:.2f}",
                    data={"pnl": trade.pnl, "side": trade.side.value}
                )
        return trade

    def _handle_dual_after_main_close(
        self,
        exit_reason: ExitReason,
        candle: Candle,
        exit_price: float,
        close_dual_position: bool = True
    ) -> None:
        """
        Close or reset dual-side state when the main position closes.

        FIX: Close dual position based on configuration when main position closes.
        - BREAK_EVEN/STOP_LOSS: Close dual if dual_side_close_on_main_sl=True
        - SIGNAL (trend reversal): Close dual if dual_side_trend_close=True
        - Other exits: Always close dual
        """
        if close_dual_position and self.dual_position_manager.has_position():
            # Close dual position when main hits SL (including break-even SL) - only if configured
            if exit_reason in (ExitReason.BREAK_EVEN, ExitReason.STOP_LOSS):
                if should_close_dual_on_main_sl(self.dual_side_params):
                    logger.info(f"🔄 Closing dual position due to main position {exit_reason.value} (dual_side_close_on_main_sl=True)")
                    self._close_dual_position(exit_price, candle.timestamp, ExitReason.LINKED_EXIT)
                else:
                    logger.info(f"⏳ Keeping dual position open after main {exit_reason.value} (dual_side_close_on_main_sl=False)")
            elif exit_reason == ExitReason.SIGNAL:
                if should_close_dual_on_trend(self.dual_side_params):
                    logger.info("🔄 Closing dual position due to trend reversal (dual_side_trend_close=True)")
                    self._close_dual_position(exit_price, candle.timestamp, ExitReason.LINKED_EXIT)
                else:
                    logger.info("⏳ Keeping dual position open after trend reversal (dual_side_trend_close=False)")
            else:
                # For other exit reasons (TP, etc.), always close dual position
                self._close_dual_position(exit_price, candle.timestamp, ExitReason.LINKED_EXIT)

        # Reset counter for the next trade cycle
        if not self.position_manager.has_position():
            self.dual_entry_count = 0

    def _record_snapshot(self, candle: Candle) -> None:
        """
        Capture combined unrealized P&L for main and dual-side positions.
        """
        total_unrealized = 0.0
        position_side = None
        position_size = 0.0

        if self.position_manager.has_position() and self.dual_position_manager.has_position():
            self._update_dual_targets_from_main(self.position_manager.get_position())

        if self.position_manager.has_position():
            position = self.position_manager.get_position()
            position.update_unrealized_pnl(candle.close)
            total_unrealized += position.unrealized_pnl
            position_side = position.side.value
            position_size += position.get_current_quantity()

        if self.dual_position_manager.has_position():
            dual_position = self.dual_position_manager.get_position()
            dual_position.update_unrealized_pnl(candle.close)
            total_unrealized += dual_position.unrealized_pnl
            position_size += dual_position.get_current_quantity()
            if position_side and dual_position.side.value != position_side:
                position_side = "hedged"
            elif not position_side:
                position_side = dual_position.side.value

        self.balance_tracker.add_snapshot(
            timestamp=candle.timestamp,
            position_side=position_side,
            position_size=position_size,
            unrealized_pnl=total_unrealized
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
            # Use cached trend_state from candle if available (from TimescaleDB)
            trend_state = getattr(candle, 'trend_state', None)

            if trend_state is None:
                # Fallback: Calculate trend_state if not in DB
                logger.info("[TREND_EXIT] trend_state not found in candle, calculating...")

                # Get price history from strategy and convert to DataFrame
                price_history = self.strategy_executor.price_history

                if len(price_history) < 20:  # Need at least 20 candles for SMA20
                    logger.info(f"[TREND_EXIT] Insufficient price history: {len(price_history)} < 20")
                    return False

                # Build DataFrame with OHLCV columns
                candles_df = pd.DataFrame([{
                    'timestamp': c.timestamp,
                    'open': c.open,
                    'high': c.high,
                    'low': c.low,
                    'close': c.close,
                    'volume': c.volume
                } for c in price_history])
                candles_df = candles_df.set_index('timestamp')

                # Convert timeframe string to minutes
                from shared.utils.time_helpers import parse_timeframe
                timeframe_unit, timeframe_value = parse_timeframe(self.timeframe)
                if timeframe_unit == 'hours':
                    current_timeframe_minutes = timeframe_value * 60
                elif timeframe_unit == 'days':
                    current_timeframe_minutes = timeframe_value * 1440
                else:  # minutes
                    current_timeframe_minutes = timeframe_value

                logger.info(
                    f"[TREND_EXIT] Checking trend reversal: time={candle.timestamp}, "
                    f"side={position.side.value}, price={candle.close:.2f}, "
                    f"history_len={len(candles_df)}, timeframe={self.timeframe} ({current_timeframe_minutes}m)"
                )

                trend_state = self.strategy_executor.signal_generator.calculate_trend_state(
                    candles_df,
                    current_timeframe_minutes=current_timeframe_minutes
                )
            else:
                logger.info(
                    f"[TREND_EXIT] Using cached trend_state from DB: time={candle.timestamp}, "
                    f"side={position.side.value}, price={candle.close:.2f}, "
                    f"trend_state={trend_state}"
                )

            logger.info(
                f"[TREND_EXIT] trend_state={trend_state}, side={position.side.value}, "
                f"entry_price={position.entry_price:.2f}, current_price={candle.close:.2f}, "
                f"unrealized_pnl={((candle.close - position.entry_price) / position.entry_price * 100 * (1 if position.side == TradeSide.LONG else -1)):.2f}%"
            )

            if trend_state is None:
                logger.info("[TREND_EXIT] trend_state is None, skipping")
                return False

            # Check if strong trend reversal against position
            should_exit = False
            if position.side == TradeSide.LONG and trend_state == -2:
                # Long position in strong downtrend
                should_exit = True
                reason = "Strong downtrend reversal (state=-2)"
                logger.info(f"[TREND_EXIT] ✅ LONG exit condition met: trend_state={trend_state}")
            elif position.side == TradeSide.SHORT and trend_state == 2:
                # Short position in strong uptrend
                should_exit = True
                reason = "Strong uptrend reversal (state=+2)"
                logger.info(f"[TREND_EXIT] ✅ SHORT exit condition met: trend_state={trend_state}")
            else:
                logger.info(
                    f"[TREND_EXIT] No exit condition met: side={position.side.value}, "
                    f"trend_state={trend_state}"
                )

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
                    self._handle_dual_after_main_close(trade.exit_reason, candle, trade.exit_price)

                return True

        return False

    def _get_all_trades(self) -> List:
        """Get all executed trades."""
        trades = self.position_manager.get_trade_history() + self.dual_position_manager.get_trade_history()
        trades.sort(key=lambda t: (t.exit_timestamp or t.entry_timestamp))

        # Re-sequence trade numbers for combined history
        for idx, trade in enumerate(trades, start=1):
            try:
                trade.trade_number = idx
            except Exception:
                logger.debug("Failed to resequence trade_number for trade", exc_info=True)
        return trades

    def reset(self) -> None:
        """Reset engine to initial state."""
        self.balance_tracker.reset()
        self.position_manager.reset()
        self.dual_position_manager.reset()
        if self.event_logger:
            self.event_logger.clear()
        self.is_running = False
        self.current_candle = None
        self.strategy_executor = None
        self.dual_side_params = {}
        self.dual_entry_count = 0
        logger.info("BacktestEngine reset to initial state")

    def _is_last_main_dca(self, position: Position) -> bool:
        """
        Determine if the latest DCA is the final allowed entry for the main position.
        """
        pyramiding_limit = int(
            self.strategy_params.get(
                'pyramiding_limit',
                self.strategy_params.get('dca_max_orders', 0)
            ) or 0
        )
        if pyramiding_limit <= 0:
            return False
        return position.dca_count >= pyramiding_limit

    def _get_main_stop_reference(self, position: Position) -> Optional[float]:
        """
        Return the current protective stop level of the main position.

        Preference order:
        1) Trailing stop price if activated
        2) Static stop loss price
        """
        if position.trailing_stop_activated and position.trailing_stop_price:
            return position.trailing_stop_price
        return position.stop_loss_price
