#!/usr/bin/env python3
"""
1년 기간 백테스트 - 트랜드 반전 종료 테스트
2025-01-01 ~ 2025-11-07 (10개월)
"""
import asyncio
import json
from datetime import datetime
from collections import Counter
from BACKTEST.engine.backtest_engine import BacktestEngine
from BACKTEST.strategies.hyperrsi_strategy import HyperrsiStrategy
from BACKTEST.data import TimescaleProvider
from shared.config.logging import configure_root_logger, get_logger

# Enable INFO logging (DEBUG would be too verbose for 1 year)
configure_root_logger('INFO')

logger = get_logger(__name__, log_level='INFO')


async def main():
    # Load test config
    with open("test_1year_trend_exit.json", "r") as f:
        config = json.load(f)

    print("=" * 80)
    print("1년 기간 백테스트 - 트랜드 반전 종료 테스트")
    print("=" * 80)
    print(f"Period: {config['start_date']} to {config['end_date']}")
    print(f"Direction: {config['strategy_params']['direction']}")
    print(f"use_trend_close: {config['strategy_params'].get('use_trend_close')}")
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
    print("백테스트 결과")
    print("=" * 80)
    print(f"Total trades: {result.total_trades}")
    print(f"Winning trades: {result.winning_trades}")
    print(f"Losing trades: {result.losing_trades}")
    print(f"Win rate: {result.win_rate:.2f}%")
    print(f"Final balance: ${result.final_balance:.2f}")
    print(f"Total return: {result.total_return:.2f}%")
    print(f"Max drawdown: {result.max_drawdown:.2f}%")

    # Count exit reasons
    exit_reasons = Counter([t.exit_reason.value for t in result.trades])
    print(f"\n종료 이유 분포:")
    for reason, count in exit_reasons.most_common():
        print(f"  {reason}: {count} ({count/result.total_trades*100:.1f}%)")

    # Check for trend reversal exits (SIGNAL)
    signal_exits = [t for t in result.trades if t.exit_reason.value == "signal"]

    print(f"\n" + "=" * 80)
    print(f"트랜드 반전 종료 (SIGNAL) 발생 횟수: {len(signal_exits)}")
    print("=" * 80)

    if signal_exits:
        print("\n트랜드 반전으로 종료된 거래들:")
        for i, trade in enumerate(signal_exits[:10], 1):  # Show first 10
            print(f"\nTrade {trade.trade_number}:")
            print(f"  Entry: {trade.entry_timestamp} @ ${trade.entry_price:.2f}")
            print(f"  Exit:  {trade.exit_timestamp} @ ${trade.exit_price:.2f}")
            print(f"  Side: {trade.side.value}")
            print(f"  PnL: ${trade.pnl:.2f} ({trade.pnl_percent:.2f}%)")
            print(f"  DCA count: {trade.dca_count}")
            days_held = (trade.exit_timestamp - trade.entry_timestamp).days
            print(f"  Duration: {days_held} days")
    else:
        print("\n⚠️  1년 기간 동안 트랜드 반전 종료가 발생하지 않았습니다.")
        print("    이는 다음 이유 때문일 수 있습니다:")
        print("    1. 포지션이 trend_state=2로 강화되기 전에 다른 조건으로 청산")
        print("    2. 2025년 시장이 대부분 trend_state=1 (약한 상승추세) 유지")
        print("    3. SHORT 전략 특성상 강한 상승추세 전에 손절/익절")

    # Show DCA statistics
    dca_trades = [t for t in result.trades if t.dca_count > 0]
    print(f"\n" + "=" * 80)
    print(f"DCA 통계:")
    print("=" * 80)
    print(f"DCA 발생한 거래: {len(dca_trades)} ({len(dca_trades)/result.total_trades*100:.1f}%)")
    if dca_trades:
        max_dca = max(t.dca_count for t in dca_trades)
        avg_dca = sum(t.dca_count for t in dca_trades) / len(dca_trades)
        print(f"최대 DCA 횟수: {max_dca}")
        print(f"평균 DCA 횟수: {avg_dca:.2f}")

    await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
