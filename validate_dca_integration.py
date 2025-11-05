"""
Validation script to compare DCA backtest results with expected behavior.

Tests DCA integration against requirements using real TimescaleDB data.
"""

import asyncio
from datetime import datetime
from uuid import uuid4

from BACKTEST.engine.backtest_engine import BacktestEngine
from BACKTEST.strategies.hyperrsi_strategy import HyperrsiStrategy
from BACKTEST.data.timescale_provider import TimescaleProvider


async def validate_dca_integration():
    """Validate DCA integration against requirements."""
    print("\n" + "=" * 80)
    print("🔄 DCA INTEGRATION VALIDATION")
    print("=" * 80)

    # Test configuration with DCA enabled
    params = {
        'entry_option': 'rsi_trend',
        'rsi_oversold': 30,
        'rsi_overbought': 70,
        'rsi_period': 14,
        'leverage': 10,
        'investment': 10,  # 10% of balance per entry
        'tp_sl_option': 'fixed',
        'stop_loss_percent': 5.0,
        'take_profit_percent': 10.0,
        'trailing_stop_enabled': False,
        # DCA parameters
        'pyramiding_enabled': True,
        'pyramiding_limit': 3,
        'entry_multiplier': 0.5,
        'pyramiding_entry_type': '퍼센트 기준',
        'pyramiding_value': 3.0,
        'entry_criterion': '평균 단가',
        'use_check_DCA_with_price': True,
        'use_rsi_with_pyramiding': True,
        'use_trend_logic': True
    }

    strategy = HyperrsiStrategy(params)
    data_provider = TimescaleProvider()

    engine = BacktestEngine(
        data_provider=data_provider,
        initial_balance=10000.0,
        fee_rate=0.0005,
        slippage_percent=0.05
    )

    # Run 1-month backtest
    print("\n🚀 Running 1-month backtest with DCA...")
    print(f"   Period: 2025-10-01 to 2025-10-31")
    print(f"   Symbol: BTCUSDT")
    print(f"   Timeframe: 15m")

    result = await engine.run(
        user_id=uuid4(),
        symbol='BTCUSDT',
        timeframe='15m',
        start_date=datetime(2025, 10, 1),
        end_date=datetime(2025, 10, 31),
        strategy_name='HYPERRSI',
        strategy_params=params,
        strategy_executor=strategy
    )

    print("\n" + "=" * 80)
    print("📊 VALIDATION RESULTS")
    print("=" * 80)

    # Requirement 1: DCA entries present
    print("\n✅ Requirement 1: DCA Entries Present")
    trades_with_dca = [t for t in result.trades if t.dca_count > 0]
    print(f"   Trades with DCA: {len(trades_with_dca)} / {len(result.trades)}")
    print(f"   Status: {'PASS' if len(trades_with_dca) > 0 else 'INFO - No DCA triggers in period'}")

    # Requirement 2: Total entries should be higher than trade count
    print("\n✅ Requirement 2: Total Entry Count")
    total_entries = sum(len(t.entry_history) for t in result.trades)
    print(f"   Total trades: {len(result.trades)}")
    print(f"   Total entries (including DCA): {total_entries}")
    print(f"   Status: {'PASS' if total_entries >= len(result.trades) else 'FAIL'}")

    # Requirement 3: Varying P&L (not all uniform)
    print("\n✅ Requirement 3: Varying P&L")
    if result.trades:
        pnls = [t.pnl for t in result.trades]
        unique_pnls = len(set(round(p, 2) for p in pnls))
        print(f"   Unique P&L values: {unique_pnls} / {len(pnls)}")
        print(f"   Status: {'PASS' if unique_pnls > 1 or len(pnls) == 1 else 'FAIL'}")
    else:
        print(f"   No trades in period")
        print(f"   Status: INFO")

    # Requirement 4: Average price calculation accuracy
    print("\n✅ Requirement 4: Average Price Accuracy")
    avg_price_correct = True
    checked_trades = 0
    for trade in result.trades:
        if trade.dca_count > 0:
            entries = trade.entry_history
            total_cost = sum(e['price'] * e['quantity'] for e in entries)
            total_qty = sum(e['quantity'] for e in entries)
            expected_avg = total_cost / total_qty
            actual_avg = trade.entry_price
            error = abs(actual_avg - expected_avg) / expected_avg

            if error > 0.001:  # 0.1% tolerance
                avg_price_correct = False
                print(f"   ❌ Trade #{trade.trade_number} mismatch: expected={expected_avg:.2f}, actual={actual_avg:.2f}")
            checked_trades += 1

    if checked_trades > 0:
        print(f"   Checked {checked_trades} trades with DCA")
        print(f"   Status: {'PASS' if avg_price_correct else 'FAIL'}")
    else:
        print(f"   No DCA trades to check")
        print(f"   Status: INFO")

    # Requirement 5: DCA limit enforcement
    print("\n✅ Requirement 5: DCA Limit Enforcement")
    max_dca = max((t.dca_count for t in result.trades), default=0)
    limit_enforced = max_dca <= params['pyramiding_limit']
    print(f"   Max DCA count: {max_dca}")
    print(f"   Configured limit: {params['pyramiding_limit']}")
    print(f"   Status: {'PASS' if limit_enforced else 'FAIL'}")

    # Requirement 6: Entry size scaling
    print("\n✅ Requirement 6: Entry Size Scaling")
    scaling_correct = True
    checked_scaling = 0
    for trade in result.trades:
        if trade.dca_count >= 2:
            entries = trade.entry_history
            initial_inv = entries[0]['investment']

            for i in range(1, len(entries)):
                expected = initial_inv * (0.5 ** i)
                actual = entries[i]['investment']
                ratio = actual / expected

                if ratio < 0.95 or ratio > 1.05:
                    scaling_correct = False
                    print(f"   ❌ Trade #{trade.trade_number} entry {i}: expected={expected:.2f}, actual={actual:.2f}")
                checked_scaling += 1

    if checked_scaling > 0:
        print(f"   Checked {checked_scaling} DCA entries")
        print(f"   Status: {'PASS' if scaling_correct else 'FAIL'}")
    else:
        print(f"   No multi-DCA trades to check")
        print(f"   Status: INFO")

    # Requirement 7: Total investment tracking
    print("\n✅ Requirement 7: Total Investment Tracking")
    investment_correct = True
    for trade in result.trades:
        if trade.dca_count > 0:
            entries = trade.entry_history
            expected_total = sum(e['investment'] for e in entries)
            actual_total = trade.total_investment

            if abs(expected_total - actual_total) > 0.01:
                investment_correct = False
                print(f"   ❌ Trade #{trade.trade_number}: expected={expected_total:.2f}, actual={actual_total:.2f}")

    print(f"   Status: {'PASS' if investment_correct else 'FAIL'}")

    # Summary statistics
    print("\n" + "=" * 80)
    print("📈 SUMMARY STATISTICS")
    print("=" * 80)

    print(f"\n💰 Performance:")
    print(f"   Initial Balance: ${result.initial_balance:,.2f}")
    print(f"   Final Balance: ${result.final_balance:,.2f}")
    print(f"   Total Return: {result.total_return_percent:.2f}%")
    print(f"   Max Drawdown: {result.max_drawdown_percent:.2f}%")

    print(f"\n📊 Trade Statistics:")
    print(f"   Total Trades: {len(result.trades)}")
    winning_trades = [t for t in result.trades if t.pnl > 0]
    losing_trades = [t for t in result.trades if t.pnl < 0]
    print(f"   Winning Trades: {len(winning_trades)}")
    print(f"   Losing Trades: {len(losing_trades)}")
    if result.trades:
        win_rate = len(winning_trades) / len(result.trades) * 100
        print(f"   Win Rate: {win_rate:.1f}%")

    print(f"\n🔄 DCA Statistics:")
    print(f"   Trades with DCA: {len(trades_with_dca)}")
    total_dca_entries = sum(t.dca_count for t in result.trades)
    print(f"   Total DCA entries: {total_dca_entries}")
    if trades_with_dca:
        avg_dca = sum(t.dca_count for t in trades_with_dca) / len(trades_with_dca)
        print(f"   Average DCA per trade: {avg_dca:.2f}")
        max_dca_in_trade = max(t.dca_count for t in trades_with_dca)
        print(f"   Max DCA in single trade: {max_dca_in_trade}")

    # Detailed examples
    if result.trades:
        print(f"\n📝 Example Trades (first 3):")
        for i, trade in enumerate(result.trades[:3], 1):
            if trade.entry_timestamp and trade.exit_timestamp:
                duration_hours = (trade.exit_timestamp - trade.entry_timestamp).total_seconds() / 3600
            else:
                duration_hours = 0
            print(f"\n  Trade #{i} ({trade.side.value.upper()}):")
            print(f"    Entry Time: {trade.entry_timestamp}")
            print(f"    Exit Time: {trade.exit_timestamp}")
            print(f"    Duration: {duration_hours:.1f} hours")
            print(f"    DCA Count: {trade.dca_count}")
            print(f"    Entry History:")
            for j, entry in enumerate(trade.entry_history):
                entry_type = "Initial" if j == 0 else f"DCA {j}"
                print(f"      [{entry_type}] Price: ${entry['price']:,.2f}, "
                      f"Qty: {entry['quantity']:.6f}, "
                      f"Investment: ${entry['investment']:.2f}")
            print(f"    Average Entry: ${trade.entry_price:,.2f}")
            print(f"    Exit: ${trade.exit_price:,.2f} ({trade.exit_reason.value})")
            print(f"    P&L: ${trade.pnl:,.2f} ({trade.pnl_percent:.2f}%)")

    print("\n" + "=" * 80)
    print("✅ VALIDATION COMPLETE")
    print("=" * 80)


if __name__ == '__main__':
    asyncio.run(validate_dca_integration())
