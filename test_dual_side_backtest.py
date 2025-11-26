#!/usr/bin/env python3
"""
Dual-side backtest test script
Tests linked_exit behavior with dual-side positions
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from BACKTEST.engine.backtest_engine import BacktestEngine
from BACKTEST.data.timescale_provider import TimescaleProvider
from BACKTEST.strategies.hyperrsi_strategy import HyperrsiStrategy
from shared.logging import get_logger

logger = get_logger(__name__)


async def run_dual_side_test():
    """Run backtest with dual-side configuration"""

    # Strategy parameters from user
    strategy_params = {
        "rsi_period": 14,
        "rsi_os": 30,
        "rsi_ob": 70,
        "direction": "both",
        "use_trend_filter": True,
        "ema_period": 7,
        "sma_period": 20,
        "entry_option": "rsi_only",
        "require_trend_confirm": True,
        "use_trend_close": False,
        "use_tp1": True,
        "tp1_percent": 3,
        "tp1_close_percent": 30,
        "use_tp2": True,
        "tp2_percent": 4,
        "tp2_close_percent": 30,
        "use_tp3": True,
        "tp3_percent": 5,
        "tp3_close_percent": 40,
        "use_trailing_stop": True,
        "trailing_stop_percent": 0.5,
        "trailing_activation_percent": 2,
        "use_break_even": True,
        "use_break_even_tp2": True,
        "use_break_even_tp3": True,
        "use_dca": True,
        "dca_max_orders": 8,
        "dca_price_step_percent": 3,
        "dca_size_multiplier": 1,
        "rsi_entry_option": "돌파",
        "leverage": 10,
        "investment": 35,
        "stop_loss_enabled": False,
        "take_profit_enabled": False,
        "take_profit_percent": None,
        "pyramiding_enabled": True,
        "pyramiding_limit": 8,
        "pyramiding_entry_type": "atr",
        "pyramiding_value": 3,
        "use_rsi_with_pyramiding": True,
        "use_trend_logic": False,
        "tp_option": "atr",
        "tp1_value": 3,
        "tp2_value": 4,
        "tp3_value": 5,
        "tp1_ratio": 30,
        "tp2_ratio": 30,
        "tp3_ratio": 40,
        "trailing_stop_active": True,
        "trailing_start_point": "tp2",
        "trailing_stop_offset_value": 0.5,
        "use_trailing_stop_value_with_tp2_tp3_difference": True,

        # Dual-side configuration
        "use_dual_side_entry": True,
        "dual_side_entry_trigger": 6,
        "dual_side_entry_ratio_type": "percent_of_position",
        "dual_side_entry_ratio_value": 100,
        "dual_side_entry_tp_trigger_type": "existing_position",
        "close_main_on_hedge_tp": True,
        "use_dual_sl": False,
        "dual_side_pyramiding_limit": 2,
        "dual_side_trend_close": False,
        "dual_side_close_on_main_sl": False,  # Default value explicitly set
    }

    logger.info("=" * 80)
    logger.info("🔍 DUAL-SIDE BACKTEST - LINKED_EXIT TEST")
    logger.info("=" * 80)
    logger.info(f"Dual-side enabled: {strategy_params['use_dual_side_entry']}")
    logger.info(f"Dual entry trigger: {strategy_params['dual_side_entry_trigger']} DCA")
    logger.info(f"Dual trend close: {strategy_params['dual_side_trend_close']}")
    logger.info(f"Dual close on main SL: {strategy_params['dual_side_close_on_main_sl']}")
    logger.info("=" * 80)

    # Create strategy
    strategy = HyperrsiStrategy(params=strategy_params)

    # Test period (recent data for quick test)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)  # Last 30 days

    logger.info(f"📅 Test period: {start_date.date()} to {end_date.date()}")
    logger.info(f"💰 Initial balance: $10,000")
    logger.info("")

    # Create data provider
    data_provider = TimescaleProvider()

    # Create backtest engine
    engine = BacktestEngine(
        data_provider=data_provider,
        initial_balance=10000.0,
        fee_rate=0.0005,
        slippage_percent=0.05
    )

    try:
        # Run backtest
        logger.info("🚀 Running backtest...")
        logger.info("")

        from uuid import UUID
        result = await engine.run(
            user_id=UUID("00000000-0000-0000-0000-000000000000"),
            symbol="BTC-USDT-SWAP",
            timeframe="15m",
            start_date=start_date,
            end_date=end_date,
            strategy_name="hyperrsi",
            strategy_params=strategy_params,
            strategy_executor=strategy
        )

        # Print results
        logger.info("=" * 80)
        logger.info("📈 BACKTEST RESULTS")
        logger.info("=" * 80)
        logger.info(f"Total trades: {result.total_trades}")
        logger.info(f"Winning trades: {result.winning_trades}")
        logger.info(f"Losing trades: {result.losing_trades}")
        logger.info(f"Win rate: {result.win_rate:.2f}%")
        logger.info(f"Final balance: ${result.final_balance:.2f}")
        logger.info(f"Total PnL: ${result.total_pnl:.2f}")
        logger.info(f"Total return: {result.total_return:.2f}%")
        logger.info(f"Max drawdown: {result.max_drawdown:.2f}%")
        logger.info("=" * 80)

        # Analyze trades
        logger.info("")
        logger.info("🔍 ANALYZING DUAL-SIDE TRADES...")
        logger.info("=" * 80)

        main_trades = [t for t in result.trades if not t.is_dual_side]
        dual_trades = [t for t in result.trades if t.is_dual_side]

        logger.info(f"📊 Main position trades: {len(main_trades)}")
        logger.info(f"🔄 Dual-side trades: {len(dual_trades)}")
        logger.info("")

        # Check for linked_exit issues
        linked_exit_trades = [t for t in result.trades if t.exit_reason and t.exit_reason.value == "linked_exit"]
        logger.info(f"🔗 Trades closed with LINKED_EXIT: {len(linked_exit_trades)}")

        if linked_exit_trades:
            logger.info("")
            logger.info("📋 LINKED_EXIT Trade Details:")
            for i, trade in enumerate(linked_exit_trades[:5], 1):  # Show first 5
                logger.info(f"\n  Trade #{trade.trade_number}:")
                logger.info(f"    Side: {trade.side.value}")
                logger.info(f"    Is dual: {trade.is_dual_side}")
                logger.info(f"    Parent trade: {trade.parent_trade_id}")
                logger.info(f"    Entry: ${trade.entry_price:.2f} @ {trade.entry_timestamp}")
                logger.info(f"    Exit: ${trade.exit_price:.2f} @ {trade.exit_timestamp}")
                logger.info(f"    PnL: ${trade.pnl:.2f}")

        # Check for unclosed positions
        logger.info("")
        logger.info("=" * 80)
        if result.unrealized_pnl != 0:
            logger.warning(f"⚠️ UNREALIZED P&L REMAINING: ${result.unrealized_pnl:.2f}")
            logger.warning("This indicates positions were not properly closed!")
        else:
            logger.info("✅ All positions closed successfully (unrealized P&L = $0)")
        logger.info("=" * 80)

    except Exception as e:
        logger.error(f"❌ Backtest failed: {e}", exc_info=True)
    finally:
        await data_provider.close()


if __name__ == "__main__":
    asyncio.run(run_dual_side_test())
