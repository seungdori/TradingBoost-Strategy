#!/usr/bin/env python3
"""
손실 거래 분석 - 손절 없는데 왜 손실이 발생했는지 분석
"""
import asyncio
import json
from datetime import datetime
from collections import defaultdict
from BACKTEST.engine.backtest_engine import BacktestEngine
from BACKTEST.strategies.hyperrsi_strategy import HyperrsiStrategy
from BACKTEST.data import TimescaleProvider
from shared.config.logging import configure_root_logger, get_logger

configure_root_logger('WARNING')  # Reduce log noise

logger = get_logger(__name__, log_level='INFO')


async def main():
    # Load test config
    with open("test_1year_trend_exit.json", "r") as f:
        config = json.load(f)

    print("=" * 80)
    print("손실 거래 분석")
    print("=" * 80)

    # Create data provider
    provider = TimescaleProvider()

    # Create backtest engine
    engine = BacktestEngine(
        data_provider=provider,
        initial_balance=config["initial_balance"],
        fee_rate=config["fee_rate"],
        slippage_percent=config["slippage_percent"],
        enable_event_logging=False  # Disable event logging for speed
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

    print(f"\n총 거래: {result.total_trades}")
    print(f"승리: {result.winning_trades}, 손실: {result.losing_trades}")
    print(f"승률: {result.win_rate:.2f}%")

    # Analyze losing trades by exit reason
    losing_trades = [t for t in result.trades if t.pnl < 0]

    print(f"\n" + "=" * 80)
    print(f"손실 거래 상세 분석 (총 {len(losing_trades)}건)")
    print("=" * 80)

    # Group by exit reason
    by_exit_reason = defaultdict(list)
    for trade in losing_trades:
        by_exit_reason[trade.exit_reason.value].append(trade)

    for reason, trades in sorted(by_exit_reason.items()):
        print(f"\n[{reason}] - {len(trades)}건")
        total_loss = sum(t.pnl for t in trades)
        avg_loss = total_loss / len(trades)
        print(f"  총 손실: ${total_loss:.2f}, 평균 손실: ${avg_loss:.2f}")

        # Show first 3 examples
        for i, trade in enumerate(trades[:3], 1):
            print(f"\n  예시 {i} (Trade #{trade.trade_number}):")
            print(f"    Entry: {trade.entry_timestamp} @ ${trade.entry_price:.2f}")
            print(f"    Exit:  {trade.exit_timestamp} @ ${trade.exit_price:.2f}")
            print(f"    PnL: ${trade.pnl:.2f} ({trade.pnl_percent:.2f}%)")
            print(f"    Entry fee: ${trade.entry_fee:.2f}, Exit fee: ${trade.exit_fee:.2f}")
            print(f"    Total fees: ${trade.entry_fee + trade.exit_fee:.2f}")
            print(f"    DCA count: {trade.dca_count}")

            # Calculate price movement
            if trade.side.value == "short":
                price_move_pct = (trade.exit_price - trade.entry_price) / trade.entry_price * 100
            else:
                price_move_pct = (trade.exit_price - trade.entry_price) / trade.entry_price * 100
            print(f"    가격 변동: {price_move_pct:+.2f}%")

    # Analyze break_even specifically
    print(f"\n" + "=" * 80)
    print("break_even 거래 상세 분석")
    print("=" * 80)

    breakeven_trades = [t for t in result.trades if t.exit_reason.value == "break_even"]
    breakeven_winning = [t for t in breakeven_trades if t.pnl >= 0]
    breakeven_losing = [t for t in breakeven_trades if t.pnl < 0]

    print(f"\n총 break_even 거래: {len(breakeven_trades)}건")
    print(f"  이익: {len(breakeven_winning)}건 (평균: ${sum(t.pnl for t in breakeven_winning)/len(breakeven_winning) if breakeven_winning else 0:.2f})")
    print(f"  손실: {len(breakeven_losing)}건 (평균: ${sum(t.pnl for t in breakeven_losing)/len(breakeven_losing) if breakeven_losing else 0:.2f})")

    if breakeven_trades:
        print("\nbreak_even 거래 예시 (첫 5개):")
        for i, trade in enumerate(breakeven_trades[:5], 1):
            pnl_status = "✅" if trade.pnl >= 0 else "❌"
            print(f"\n  {i}. Trade #{trade.trade_number} {pnl_status}")
            print(f"     Entry: ${trade.entry_price:.2f}, Exit: ${trade.exit_price:.2f}")
            print(f"     PnL: ${trade.pnl:.2f} ({trade.pnl_percent:.2f}%)")
            print(f"     Fees: ${trade.entry_fee + trade.exit_fee:.2f}")
            print(f"     DCA: {trade.dca_count}회")

    # Analyze trailing_stop
    print(f"\n" + "=" * 80)
    print("trailing_stop 거래 상세 분석")
    print("=" * 80)

    trailing_trades = [t for t in result.trades if t.exit_reason.value == "trailing_stop"]
    trailing_winning = [t for t in trailing_trades if t.pnl >= 0]
    trailing_losing = [t for t in trailing_trades if t.pnl < 0]

    print(f"\n총 trailing_stop 거래: {len(trailing_trades)}건")
    print(f"  이익: {len(trailing_winning)}건 (평균: ${sum(t.pnl for t in trailing_winning)/len(trailing_winning) if trailing_winning else 0:.2f})")
    print(f"  손실: {len(trailing_losing)}건 (평균: ${sum(t.pnl for t in trailing_losing)/len(trailing_losing) if trailing_losing else 0:.2f})")

    if trailing_losing:
        print("\ntrailing_stop 손실 거래 예시:")
        for i, trade in enumerate(trailing_losing[:3], 1):
            print(f"\n  {i}. Trade #{trade.trade_number}")
            print(f"     Entry: ${trade.entry_price:.2f}, Exit: ${trade.exit_price:.2f}")
            print(f"     PnL: ${trade.pnl:.2f} ({trade.pnl_percent:.2f}%)")
            print(f"     Fees: ${trade.entry_fee + trade.exit_fee:.2f}")
            print(f"     DCA: {trade.dca_count}회")

    await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
