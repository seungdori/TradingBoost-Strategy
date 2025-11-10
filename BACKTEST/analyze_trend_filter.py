#!/usr/bin/env python3
"""
Analyze why trend filter blocks all SHORT entry signals.
"""
import asyncio
from datetime import datetime
from BACKTEST.data import TimescaleProvider
from BACKTEST.strategies.signal_generator import SignalGenerator


async def main():
    provider = TimescaleProvider()

    symbol = "BTC/USDT:USDT"
    timeframe = "15m"
    start_date = datetime.fromisoformat("2025-09-06T00:00:00+00:00")
    end_date = datetime.fromisoformat("2025-11-06T23:59:59+00:00")

    # User's strategy params
    strategy_params = {
        "entry_option": "rsi_trend",
        "rsi_entry_option": "돌파",
        "direction": "short",
        "rsi_overbought": 70.0,
        "rsi_oversold": 30.0,
        "rsi_period": 14,
    }

    print("=" * 80)
    print(f"Analyzing trend filter blocking for {symbol} SHORT strategy")
    print(f"Period: {start_date} to {end_date}")
    print(f"Entry option: {strategy_params['entry_option']} (trend filter ENABLED)")
    print(f"RSI entry option: {strategy_params['rsi_entry_option']} (crossover)")
    print("=" * 80)

    try:
        # Initialize signal generator
        signal_gen = SignalGenerator(strategy_params)

        candles = await provider.get_candles(
            symbol, timeframe, start_date, end_date
        )

        print(f"\nTotal candles: {len(candles)}")

        # Track RSI crossovers and their trend_state (PineScript 3-level system)
        crossovers_by_trend = {-2: 0, 0: 0, 2: 0, None: 0}
        blocked_by_trend = 0
        allowed_signals = 0

        print("\n" + "=" * 80)
        print("Analyzing RSI crossovers and trend filter impact:")
        print("=" * 80)

        # We need at least 61 candles for trend calculation
        min_history = 61

        for i in range(1, len(candles)):
            prev_candle = candles[i-1]
            curr_candle = candles[i]

            prev_rsi = prev_candle.rsi
            curr_rsi = curr_candle.rsi

            if prev_rsi and curr_rsi:
                # Check for RSI crossover (SHORT: crossing ABOVE overbought)
                if prev_rsi < 70.0 and curr_rsi >= 70.0:
                    # Calculate trend_state from historical closes
                    trend_state = None
                    if i >= min_history:
                        # Get last 61 candles up to current
                        import pandas as pd
                        historical_closes = pd.Series([c.close for c in candles[i-min_history:i+1]])
                        trend_state = signal_gen.calculate_trend_state(historical_closes)

                    # Count by trend_state
                    crossovers_by_trend[trend_state] += 1

                    # Check signal with trend filter
                    signal_allowed, reason = signal_gen.check_short_signal(
                        rsi=curr_rsi,
                        trend_state=trend_state,
                        previous_rsi=prev_rsi
                    )

                    if signal_allowed:
                        allowed_signals += 1
                        print(f"\n✅ ALLOWED Signal #{allowed_signals}:")
                        print(f"  Time: {curr_candle.timestamp}")
                        print(f"  RSI: {prev_rsi:.2f} → {curr_rsi:.2f}")
                        print(f"  Trend State: {trend_state}")
                        print(f"  Price: {curr_candle.close:.2f}")
                    else:
                        blocked_by_trend += 1
                        if blocked_by_trend <= 10:  # Show first 10 blocked signals
                            print(f"\n❌ BLOCKED Signal #{blocked_by_trend}:")
                            print(f"  Time: {curr_candle.timestamp}")
                            print(f"  RSI: {prev_rsi:.2f} → {curr_rsi:.2f}")
                            print(f"  Trend State: {trend_state}")
                            print(f"  Reason: {reason}")
                            print(f"  Price: {curr_candle.close:.2f}")
                            print(f"  EMA: {curr_candle.ema}, SMA: {curr_candle.sma}")

        print("\n" + "=" * 80)
        print("SUMMARY:")
        print("=" * 80)

        total_crossovers = sum(crossovers_by_trend.values())
        print(f"\nTotal RSI crossovers (70 up): {total_crossovers}")
        print(f"\nCrossovers by trend_state:")
        print(f"  trend_state = -2 (strong downtrend): {crossovers_by_trend[-2]} crossovers")
        print(f"  trend_state = -1 (weak downtrend):   {crossovers_by_trend[-1]} crossovers")
        print(f"  trend_state =  0 (neutral):          {crossovers_by_trend[0]} crossovers")
        print(f"  trend_state =  1 (weak uptrend):     {crossovers_by_trend[1]} crossovers")
        print(f"  trend_state =  2 (strong uptrend):   {crossovers_by_trend[2]} crossovers")
        print(f"  trend_state =  None (no data):       {crossovers_by_trend[None]} crossovers")

        print(f"\n{'='*80}")
        print(f"Signal Filter Results:")
        print(f"{'='*80}")
        print(f"  ✅ Allowed signals:  {allowed_signals}")
        print(f"  ❌ Blocked signals:  {blocked_by_trend}")
        print(f"  Block rate: {blocked_by_trend/total_crossovers*100:.1f}%")

        if crossovers_by_trend[2] > 0:
            print(f"\n⚠️  ROOT CAUSE IDENTIFIED:")
            print(f"  {crossovers_by_trend[2]} out of {total_crossovers} RSI crossovers occurred during STRONG UPTREND (trend_state=2)")
            print(f"  Signal generator blocks SHORT entries when trend_state == 2")
            print(f"  This is why 0 trades were executed in the user's backtest.")
            print(f"\n💡 SOLUTION OPTIONS:")
            print(f"  1. Use 'entry_option: rsi_only' to disable trend filter")
            print(f"  2. Adjust trend filter logic to allow shorts in strong uptrend during extreme RSI")
            print(f"  3. Use different time period (downtrend or neutral market)")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
