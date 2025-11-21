"""
CYCLE MTF 값 확인 - 15분봉 CYCLE_Bear가 18:45에 True인지 확인
"""

import pandas as pd
import asyncio
from datetime import datetime, timezone, timedelta
from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._trend import compute_trend_state


async def check_cycle_mtf():
    """CYCLE MTF 값 확인"""

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

    # 18:45 전후 1분봉 확인
    target_time = datetime(2025, 11, 16, 18, 45, 0, tzinfo=timezone.utc)

    print('\n18:30~19:00 구간의 1분봉 CYCLE 값:')
    print('=' * 180)
    print(f"{'Idx':<6} {'Time':<20} {'15m_Time':<20} {'CYCLE_Bull':>11} {'CYCLE_Bear':>11} {'Prev_State':>11} {'Py_State':>9}")
    print('-' * 180)

    for i, candle in enumerate(result_filtered):
        ts = candle['timestamp']

        if datetime(2025, 11, 16, 18, 30, 0, tzinfo=timezone.utc) <= ts <= datetime(2025, 11, 16, 19, 0, 0, tzinfo=timezone.utc):
            cycle_bull = candle.get('CYCLE_Bull', False)
            cycle_bear = candle.get('CYCLE_Bear', False)
            py_state = candle.get('trend_state', 0)
            prev_state = result_filtered[i-1].get('trend_state', 0) if i > 0 else 0

            # 해당 1분봉에 대응하는 15분봉 찾기
            mtf_ts = None
            for c15m in candles_15m:
                if c15m['timestamp'] <= ts:
                    mtf_ts = c15m['timestamp']

            print(f"{i:<6} {str(ts)[:19]:<20} {str(mtf_ts)[:19] if mtf_ts else 'N/A':<20} {str(cycle_bull):>11} {str(cycle_bear):>11} {prev_state:>11} {py_state:>9}")


if __name__ == "__main__":
    asyncio.run(check_cycle_mtf())
