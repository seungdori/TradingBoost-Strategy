"""
상태 전환 분석 - 특히 index 83 → 84 → 114 → 115 전환
"""

import pandas as pd
import asyncio
from datetime import datetime, timezone, timedelta
from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._trend import compute_trend_state


async def analyze_state_transition():
    """상태 전환 분석"""

    csv_path = '/Users/seunghyun/Downloads/OKX_BTCUSDT.P, 1_8f411.csv'
    pine_df = pd.read_csv(csv_path)
    pine_df['datetime'] = pd.to_datetime(pine_df['time'], unit='s', utc=True)

    csv_start_time = pine_df['datetime'].min()
    end_time = pine_df['datetime'].max()
    start_time = csv_start_time - timedelta(days=7)

    provider = TimescaleProvider()

    candles_1m_raw = await provider.get_candles('BTC-USDT-SWAP', '1m', start_time, end_time)
    candles_1m = [{'timestamp': c.timestamp, 'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close, 'volume': c.volume} for c in candles_1m_raw]

    candles_15m_raw = await provider.get_candles('BTC-USDT-SWAP', '15m', start_time, end_time)
    candles_15m = [{'timestamp': c.timestamp, 'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close, 'volume': c.volume} for c in candles_15m_raw]

    candles_5m_raw = await provider.get_candles('BTC-USDT-SWAP', '5m', start_time, end_time)
    candles_5m = [{'timestamp': c.timestamp, 'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close, 'volume': c.volume} for c in candles_5m_raw]

    candles_4h_raw = await provider.get_candles('BTC-USDT-SWAP', '4h', start_time, end_time)
    candles_4h = [{'timestamp': c.timestamp, 'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close, 'volume': c.volume} for c in candles_4h_raw]

    result = compute_trend_state(candles=candles_1m, use_longer_trend=False, current_timeframe_minutes=1, candles_higher_tf=candles_15m, candles_bb_mtf=candles_5m, candles_4h=candles_4h, is_confirmed_only=True)

    result_filtered = [c for c in result if c['timestamp'] >= csv_start_time]

    pine_dict = {row['datetime']: row for _, row in pine_df.iterrows()}

    print('\n상태 전환 분석 (Index 83 → 84 → 113 → 114):')
    print('=' * 200)
    print(f"{'Idx':<6} {'Time':<20} {'BB_St':>7} {'BB_MTF':>7} {'CYC_Bull':>9} {'CYC_Bear':>9} {'Bull2':>7} {'Bear2':>7} {'Prev_Py':>8} {'Py_State':>9} {'Pine':>7} {'Match':<6}")
    print('-' * 200)

    for i in range(80, min(120, len(result_filtered))):
        candle = result_filtered[i]
        ts = candle['timestamp']

        if ts not in pine_dict:
            continue

        pine_row = pine_dict[ts]

        python_trend = candle.get('trend_state', 0)
        pine_trend = pine_row['trend_state']

        # 이전 캔들 상태
        prev_py = result_filtered[i-1].get('trend_state', 0) if i > 0 else 0

        bb_st = candle.get('BB_State', 0)
        bb_mtf = candle.get('BB_State_MTF', 0)
        cycle_bull = candle.get('CYCLE_Bull', False)
        cycle_bear = candle.get('CYCLE_Bear', False)
        cycle_bull2 = candle.get('CYCLE_Bull_2nd', False)
        cycle_bear2 = candle.get('CYCLE_Bear_2nd', False)

        match = "✅" if python_trend == pine_trend else "❌"

        print(f"{i:<6} {str(ts)[:19]:<20} {bb_st:>7} {bb_mtf:>7} {str(cycle_bull):>9} {str(cycle_bear):>9} {str(cycle_bull2):>7} {str(cycle_bear2):>7} {prev_py:>8} {python_trend:>9} {pine_trend:>7} {match:<6}")


if __name__ == "__main__":
    asyncio.run(analyze_state_transition())
