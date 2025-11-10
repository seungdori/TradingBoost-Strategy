#!/usr/bin/env python3
"""
Debug trend reversal exit behavior.
Focus on September 30, 2025 timeframe as user requested.
"""
import asyncio
import json
import logging
from datetime import datetime
from BACKTEST.engine.backtest_engine import BacktestEngine
from BACKTEST.strategies.hyperrsi_strategy import HyperrsiStrategy
from BACKTEST.data import TimescaleProvider
from shared.config.logging import configure_root_logger, get_logger

# Enable DEBUG logging for all loggers
configure_root_logger('DEBUG')

logger = get_logger(__name__, log_level='DEBUG')


async def main():
    # Load test config
    with open("test_dca_request.json", "r") as f:
        config = json.load(f)

    print("=" * 80)
    print("TREND REVERSAL EXIT DEBUG")
    print("=" * 80)
    print(f"Period: {config['start_date']} to {config['end_date']}")
    print(f"use_trend_close: {config['strategy_params'].get('use_trend_close')}")
    print(f"use_trend_logic: {config['strategy_params'].get('use_trend_logic')}")
    print(f"Direction: {config['strategy_params']['direction']}")
    print("=" * 80)

    # Create data provider
    provider = TimescaleProvider()

    # Create backtest engine
    engine = BacktestEngine(
        data_provider=provider,
        initial_balance=config["initial_balance"],
        fee_rate=config["fee_rate"],
        slippage_percent=config["slippage_percent"],
        enable_event_logging=config.get("enable_event_logging", True)
    )

    # Create strategy
    strategy = HyperrsiStrategy(config["strategy_params"])
    strategy.set_data_provider(provider, config["symbol"], config["timeframe"])

    print(f"\nStrategy configuration:")
    print(f"  use_trend_close: {strategy.use_trend_close}")
    print(f"  use_trend_logic: {strategy.use_trend_logic}")
    print(f"  use_trend_filter: {strategy.use_trend_filter}")

    # Run backtest
    start_date = datetime.fromisoformat(config["start_date"].replace("Z", "+00:00"))
    end_date = datetime.fromisoformat(config["end_date"].replace("Z", "+00:00"))

    from uuid import uuid4
    result = await engine.run(
        user_id=uuid4(),
        symbol=config["symbol"],
        timeframe=config["timeframe"],
        start_date=start_date,
        end_date=end_date,
        strategy_name=config["strategy_name"],
        strategy_params=config["strategy_params"],
        strategy_executor=strategy
    )

    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)
    print(f"Total trades: {result.total_trades}")
    print(f"Winning trades: {result.winning_trades}")
    print(f"Losing trades: {result.losing_trades}")
    print(f"Win rate: {result.win_rate:.2f}%")

    # Count exit reasons
    from collections import Counter
    exit_reasons = Counter([t.exit_reason.value for t in result.trades])
    print(f"\nExit reasons:")
    for reason, count in exit_reasons.items():
        print(f"  {reason}: {count}")

    # Show trades around Sept 30, 2025
    sept_30 = datetime(2025, 9, 30, tzinfo=start_date.tzinfo)
    print(f"\n" + "=" * 80)
    print(f"Trades around September 30, 2025:")
    print("=" * 80)

    for i, trade in enumerate(result.trades, 1):
        # Show trades that were open during Sept 30 or closed around that time
        if trade.exit_timestamp is None:
            continue  # Skip open trades

        if (trade.entry_timestamp <= sept_30 <= trade.exit_timestamp) or \
           (abs((trade.exit_timestamp - sept_30).days) <= 5):
            print(f"\nTrade {i}:")
            print(f"  Entry: {trade.entry_timestamp} @ ${trade.entry_price:.2f}")
            print(f"  Exit:  {trade.exit_timestamp} @ ${trade.exit_price:.2f}")
            print(f"  Side: {trade.side.value}")
            print(f"  Exit reason: {trade.exit_reason.value}")
            print(f"  PnL: ${trade.pnl:.2f}")
            print(f"  DCA count: {trade.dca_count}")

            # Check if this trade was open during Sept 30
            if trade.entry_timestamp <= sept_30 <= trade.exit_timestamp:
                days_held = (trade.exit_timestamp - trade.entry_timestamp).days
                print(f"  ⚠️  This trade was OPEN during Sept 30 (held for {days_held} days)")

    await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
