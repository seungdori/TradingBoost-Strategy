"""
1분봉 리샘플링 vs 5분봉 직접 데이터 비교
"""

import asyncio
import pandas as pd
from datetime import datetime, timedelta, timezone
from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._trend import _calc_bb_state


def resample_1m_to_5m(candles_1m):
    """1분봉을 5분봉으로 리샘플링"""
    df = pd.DataFrame(candles_1m)
    df.set_index('timestamp', inplace=True)

    # 5분봉으로 리샘플링
    df_5m = df.resample('5min', label='left', closed='left').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()

    # 다시 딕셔너리 리스트로 변환
    candles_5m_resampled = []
    for ts, row in df_5m.iterrows():
        candles_5m_resampled.append({
            'timestamp': ts,
            'open': row['open'],
            'high': row['high'],
            'low': row['low'],
            'close': row['close'],
            'volume': row['volume']
        })

    return candles_5m_resampled


async def compare_resampled_vs_direct():
    """리샘플링 vs 직접 5분봉 비교"""

    print("=" * 140)
    print("1분봉 리샘플링 vs 5분봉 직접 데이터 비교")
    print("=" * 140)

    csv_start = datetime(2025, 11, 16, 16, 51, 0, tzinfo=timezone.utc)
    start_time = csv_start - timedelta(days=7)
    end_time = datetime(2025, 11, 17, 7, 1, 0, tzinfo=timezone.utc)

    provider = TimescaleProvider()

    # 1분봉
    candles_1m_raw = await provider.get_candles("BTC-USDT-SWAP", "1m", start_time, end_time)
    candles_1m = [
        {'timestamp': c.timestamp, 'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close, 'volume': c.volume}
        for c in candles_1m_raw
    ]

    # 5분봉 (직접)
    candles_5m_raw = await provider.get_candles("BTC-USDT-SWAP", "5m", start_time, end_time)
    candles_5m_direct = [
        {'timestamp': c.timestamp, 'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close, 'volume': c.volume}
        for c in candles_5m_raw
    ]

    # 1분봉 리샘플링
    candles_5m_resampled = resample_1m_to_5m(candles_1m)

    print(f"\n📊 1분봉: {len(candles_1m)}개")
    print(f"📊 5분봉 (직접): {len(candles_5m_direct)}개")
    print(f"📊 5분봉 (리샘플링): {len(candles_5m_resampled)}개")

    # BB_State 계산
    bb_state_direct = _calc_bb_state(candles_5m_direct, length_bb=15, mult_bb=1.5, ma_length=100, is_confirmed_only=True)
    bb_state_resampled = _calc_bb_state(candles_5m_resampled, length_bb=15, mult_bb=1.5, ma_length=100, is_confirmed_only=True)

    # 20:45~21:00 구간 비교
    print("\n" + "=" * 140)
    print("BB_State 비교 (20:45~21:00)")
    print("=" * 140)

    print(f"\n{'Timestamp':<20} {'Direct_Close':>12} {'Resamp_Close':>12} {'Direct_BB':>10} {'Resamp_BB':>10} {'Match':>8}")
    print("-" * 140)

    target_start = datetime(2025, 11, 16, 20, 45, 0, tzinfo=timezone.utc)
    target_end = datetime(2025, 11, 16, 21, 0, 0, tzinfo=timezone.utc)

    # 직접 5분봉 기준으로 비교
    for i, c_direct in enumerate(candles_5m_direct):
        ts = c_direct['timestamp']

        if not (target_start <= ts <= target_end):
            continue

        # 리샘플링 데이터에서 같은 timestamp 찾기
        c_resamp = next((c for c in candles_5m_resampled if c['timestamp'] == ts), None)

        if c_resamp is None:
            print(f"{str(ts)[:19]:<20} {c_direct['close']:>12.2f} {'N/A':>12} {bb_state_direct[i]:>10} {'N/A':>10} {'❌':>8}")
            continue

        # 리샘플링 데이터의 인덱스 찾기
        j = next((idx for idx, c in enumerate(candles_5m_resampled) if c['timestamp'] == ts), None)

        if j is None:
            continue

        direct_bb = bb_state_direct[i]
        resamp_bb = bb_state_resampled[j]
        match = "✅" if direct_bb == resamp_bb else "❌"

        print(f"{str(ts)[:19]:<20} {c_direct['close']:>12.2f} {c_resamp['close']:>12.2f} {direct_bb:>10} {resamp_bb:>10} {match:>8}")


if __name__ == "__main__":
    asyncio.run(compare_resampled_vs_direct())
