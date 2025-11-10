#!/usr/bin/env python3
"""
Check if trend reversal exit is working correctly.
"""
import asyncio
import json
from datetime import datetime
from BACKTEST.engine.backtest_engine import BacktestEngine
from BACKTEST.strategies.hyperrsi_strategy import HyperrsiStrategy
from BACKTEST.data import TimescaleProvider
from shared.logging import get_logger

logger = get_logger(__name__)


async def main():
    # Load test config
    with open("test_dca_request.json", "r") as f:
        config = json.load(f)

    print("=" * 80)
    print("TREND CLOSE CHECK")
    print("=" * 80)
    print(f"use_trend_close: {config['strategy_params'].get('use_trend_close')}")
    print(f"use_trend_logic: {config['strategy_params'].get('use_trend_logic')}")
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

    print(f"\nStrategy use_trend_close: {strategy.use_trend_close}")
    print(f"Strategy use_trend_logic: {strategy.use_trend_logic}")

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

    # Count exit reasons
    from collections import Counter
    exit_reasons = Counter([t.exit_reason.value for t in result.trades])
    print(f"\nExit reasons:")
    for reason, count in exit_reasons.items():
        print(f"  {reason}: {count}")

    await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
