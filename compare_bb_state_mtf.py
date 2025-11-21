"""
BB_State_MTF 값 비교: Python vs Pine Script CSV
"""

import asyncio
import pandas as pd
from datetime import datetime, timedelta, timezone
from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._trend import compute_trend_state


async def compare_bb_state_mtf():
    """Python 계산과 Pine Script CSV의 BB_state_MTF 비교"""

    print("=" * 140)
    print("BB_State_MTF 비교: Python vs Pine Script")
    print("=" * 140)

    # Pine Script CSV 로드
    csv_path = "/Users/seunghyun/Downloads/OKX_BTCUSDT.P, 1_8f411.csv"
    df_pine = pd.read_csv(csv_path)
    df_pine['time'] = pd.to_datetime(df_pine['time'], unit='s', utc=True)

    print(f"\n📊 Pine Script CSV: {len(df_pine)}개 캔들")

    # CSV 시작 시점
    csv_start = df_pine['time'].min()
    print(f"CSV 시작: {csv_start}")

    # 7일 전부터 데이터 로드 (indicator 계산에 필요)
    start_time = csv_start - timedelta(days=7)
    end_time = df_pine['time'].max() + timedelta(hours=1)

    provider = TimescaleProvider()

    # 1분봉
    candles_1m_raw = await provider.get_candles("BTC-USDT-SWAP", "1m", start_time, end_time)
    candles_1m = [
        {'timestamp': c.timestamp, 'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close, 'volume': c.volume}
        for c in candles_1m_raw
    ]

    # 15분봉
    candles_15m_raw = await provider.get_candles("BTC-USDT-SWAP", "15m", start_time, end_time)
    candles_15m = [
        {'timestamp': c.timestamp, 'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close, 'volume': c.volume}
        for c in candles_15m_raw
    ]

    # 5분봉
    candles_5m_raw = await provider.get_candles("BTC-USDT-SWAP", "5m", start_time, end_time)
    candles_5m = [
        {'timestamp': c.timestamp, 'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close, 'volume': c.volume}
        for c in candles_5m_raw
    ]

    # 4시간봉
    candles_4h_raw = await provider.get_candles("BTC-USDT-SWAP", "4h", start_time, end_time)
    candles_4h = [
        {'timestamp': c.timestamp, 'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close, 'volume': c.volume}
        for c in candles_4h_raw
    ]

    print(f"📊 1분봉: {len(candles_1m)}개")
    print(f"📊 5분봉: {len(candles_5m)}개")
    print(f"📊 15분봉: {len(candles_15m)}개")
    print(f"📊 4시간봉: {len(candles_4h)}개")

    # Python compute_trend_state 호출
    result = compute_trend_state(
        candles=candles_1m,
        use_longer_trend=False,
        current_timeframe_minutes=1,
        candles_higher_tf=candles_15m,
        candles_bb_mtf=candles_5m,
        candles_4h=candles_4h,
        is_confirmed_only=True
    )

    # CSV 시작 시점부터 비교
    print("\n" + "=" * 140)
    print("BB_State_MTF 비교 결과")
    print("=" * 140)

    print(f"\n{'Index':<8} {'Timestamp':<20} {'Pine_BB_MTF':>11} {'Python_BB_MTF':>13} {'Match':>8}")
    print("-" * 140)

    matches = 0
    mismatches = 0
    mismatch_examples = []

    for i, candle in enumerate(result):
        ts = candle['timestamp']

        # CSV 범위 내에서만 비교
        if ts < csv_start:
            continue

        # Pine Script CSV에서 해당 timestamp 찾기
        pine_row = df_pine[df_pine['time'] == ts]

        if pine_row.empty:
            continue

        pine_bb_mtf = int(pine_row['BB_state_MTF'].values[0])
        python_bb_mtf = candle.get('BB_State_MTF', 0)

        match = "✅" if pine_bb_mtf == python_bb_mtf else "❌"

        if pine_bb_mtf == python_bb_mtf:
            matches += 1
        else:
            mismatches += 1
            if len(mismatch_examples) < 20:
                mismatch_examples.append({
                    'index': i,
                    'timestamp': ts,
                    'pine': pine_bb_mtf,
                    'python': python_bb_mtf,
                    'close': candle.get('close', 0)
                })

        # 처음 10개와 mismatch만 출력
        if matches + mismatches <= 10 or pine_bb_mtf != python_bb_mtf:
            print(f"{i:<8} {str(ts)[:19]:<20} {pine_bb_mtf:>11} {python_bb_mtf:>13} {match:>8}")

    # 통계
    total = matches + mismatches
    match_rate = (matches / total * 100) if total > 0 else 0

    print("\n" + "=" * 140)
    print("📊 통계")
    print("=" * 140)
    print(f"총 캔들: {total}개")
    print(f"일치: {matches}개 ({match_rate:.1f}%)")
    print(f"불일치: {mismatches}개 ({100-match_rate:.1f}%)")

    # Mismatch 예시
    if mismatch_examples:
        print("\n" + "=" * 140)
        print("❌ 불일치 예시 (최대 20개)")
        print("=" * 140)
        print(f"\n{'Index':<8} {'Timestamp':<20} {'Close':>10} {'Pine':>6} {'Python':>8}")
        print("-" * 140)

        for ex in mismatch_examples:
            print(f"{ex['index']:<8} {str(ex['timestamp'])[:19]:<20} {ex['close']:>10.2f} {ex['pine']:>6} {ex['python']:>8}")


if __name__ == "__main__":
    asyncio.run(compare_bb_state_mtf())
