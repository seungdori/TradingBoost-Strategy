#!/usr/bin/env python3
"""
Run backtest with detailed logging to debug why 0 trades occur.
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
    print("BACKTEST DEBUG RUN")
    print("=" * 80)
    print(f"Symbol: {config['symbol']}")
    print(f"Period: {config['start_date']} to {config['end_date']}")
    print(f"Strategy: {config['strategy_name']}")
    print(f"Entry option: {config['strategy_params']['entry_option']}")
    print(f"RSI entry option: {config['strategy_params']['rsi_entry_option']}")
    print(f"Direction: {config['strategy_params']['direction']}")
    print("=" * 80)

    # Create data provider
    provider = TimescaleProvider()

    # Validate data availability
    start_date = datetime.fromisoformat(config["start_date"].replace("Z", "+00:00"))
    end_date = datetime.fromisoformat(config["end_date"].replace("Z", "+00:00"))

    validation = await provider.validate_data_availability(
        config["symbol"],
        config["timeframe"],
        start_date,
        end_date
    )

    print(f"\nData validation:")
    print(f"  Available: {validation['available']}")
    print(f"  Coverage: {validation['coverage']*100:.1f}%")
    print(f"  Candles: {validation.get('total_candles_found', 0)}")

    if not validation["available"]:
        print("\n❌ Data not available!")
        await provider.close()
        return

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

    # Run backtest
    print("\n" + "=" * 80)
    print("RUNNING BACKTEST...")
    print("=" * 80)

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

    # Print results
    print("\n" + "=" * 80)
    print("BACKTEST RESULTS")
    print("=" * 80)
    print(f"Total trades: {result.total_trades}")
    print(f"Winning trades: {result.winning_trades}")
    print(f"Losing trades: {result.losing_trades}")
    print(f"Win rate: {result.win_rate:.2f}%")
    print(f"Final balance: ${result.final_balance:.2f}")
    print(f"Total return: {result.total_return:.2f}%")
    print(f"Max drawdown: {result.max_drawdown:.2f}%")

    if result.total_trades > 0:
        print(f"\nFirst 5 trades:")
        for i, trade in enumerate(result.trades[:5], 1):
            print(f"\n  Trade {i}:")
            print(f"    Entry: {trade.entry_time} @ ${trade.entry_price:.2f}")
            print(f"    Exit: {trade.exit_time} @ ${trade.exit_price:.2f}")
            print(f"    Side: {trade.side.value}")
            print(f"    PnL: ${trade.pnl:.2f}")
            print(f"    DCA count: {trade.dca_count}")
    else:
        print("\n❌ NO TRADES EXECUTED!")
        print("\nChecking event log for details...")
        if hasattr(engine, 'event_log') and engine.event_log:
            print(f"\nTotal events: {len(engine.event_log)}")
            # Show signal events
            signal_events = [e for e in engine.event_log if e.get('type') in ['signal_generated', 'signal_filtered']]
            print(f"Signal events: {len(signal_events)}")
            if signal_events:
                print("\nFirst 10 signal events:")
                for i, event in enumerate(signal_events[:10], 1):
                    print(f"\n  Event {i}:")
                    print(f"    Type: {event['type']}")
                    print(f"    Time: {event['timestamp']}")
                    if 'reason' in event:
                        print(f"    Reason: {event['reason']}")
                    if 'indicators' in event:
                        print(f"    Indicators: {event['indicators']}")

    await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
