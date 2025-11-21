"""
Pine Script CSV 데이터와 Python 계산 결과 비교

목적: 진짜 Pine Script로 계산된 trend_state와 Python 계산 결과 비교
"""

import asyncio
import pandas as pd
from datetime import datetime, timezone
from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._trend import compute_trend_state


async def compare_with_pinescript():
    """Pine Script CSV vs Python 계산 결과 비교"""

    print("=" * 120)
    print("Pine Script vs Python trend_state 비교")
    print("=" * 120)

    # 1. Pine Script CSV 로드
    csv_path = "/Users/seunghyun/Downloads/OKX_BTCUSDT.P, 1_8f411.csv"
    pine_df = pd.read_csv(csv_path)

    print(f"\n📊 Pine Script CSV 데이터: {len(pine_df)}개")
    print(f"   시간 범위: {pine_df['time'].min()} ~ {pine_df['time'].max()}")

    # UNIX timestamp를 datetime으로 변환
    pine_df['datetime'] = pd.to_datetime(pine_df['time'], unit='s', utc=True)

    print(f"   날짜 범위: {pine_df['datetime'].min()} ~ {pine_df['datetime'].max()}")

    # 2. TimescaleDB에서 데이터 가져오기
    # MA 계산을 위해 CSV 시작 시간보다 훨씬 이전부터 로드 (7일 전)
    csv_start_time = pine_df['datetime'].min()
    end_time = pine_df['datetime'].max()

    from datetime import timedelta
    start_time = csv_start_time - timedelta(days=7)

    print(f"   데이터 로드 기간: {start_time} ~ {end_time}")

    provider = TimescaleProvider()

    print(f"\n🔍 TimescaleDB 데이터 로드 중...")
    print(f"   기간: {start_time} ~ {end_time}")

    # 1분봉
    candles_1m_raw = await provider.get_candles(
        symbol="BTC-USDT-SWAP",
        timeframe="1m",
        start_date=start_time,
        end_date=end_time
    )

    candles_1m = [
        {
            'timestamp': c.timestamp,
            'open': c.open,
            'high': c.high,
            'low': c.low,
            'close': c.close,
            'volume': c.volume
        }
        for c in candles_1m_raw
    ]

    # MTF 데이터
    candles_15m_raw = await provider.get_candles("BTC-USDT-SWAP", "15m", start_time, end_time)
    candles_15m = [
        {'timestamp': c.timestamp, 'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close, 'volume': c.volume}
        for c in candles_15m_raw
    ]

    candles_5m_raw = await provider.get_candles("BTC-USDT-SWAP", "5m", start_time, end_time)
    candles_5m = [
        {'timestamp': c.timestamp, 'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close, 'volume': c.volume}
        for c in candles_5m_raw
    ]

    candles_4h_raw = await provider.get_candles("BTC-USDT-SWAP", "4h", start_time, end_time)
    candles_4h = [
        {'timestamp': c.timestamp, 'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close, 'volume': c.volume}
        for c in candles_4h_raw
    ]

    print(f"✅ 1m: {len(candles_1m)}개")
    print(f"✅ 15m: {len(candles_15m)}개")
    print(f"✅ 5m: {len(candles_5m)}개")
    print(f"✅ 4h: {len(candles_4h)}개")

    # 3. Python으로 trend_state 계산
    print(f"\n⚙️  Python trend_state 계산 중...")
    result = compute_trend_state(
        candles=candles_1m,
        use_longer_trend=False,
        current_timeframe_minutes=1,
        candles_higher_tf=candles_15m,
        candles_bb_mtf=candles_5m,
        candles_4h=candles_4h,
        is_confirmed_only=True
    )

    print(f"✅ 계산 완료: {len(result)}개")

    # CSV 시간대만 필터링
    result_filtered = [c for c in result if c['timestamp'] >= csv_start_time]
    print(f"✅ CSV 시간대 필터링: {len(result_filtered)}개")

    # 4. 타임스탬프 기준으로 매칭
    print(f"\n🔗 타임스탬프 기준 매칭 중...")

    # Pine Script 데이터를 dict로 변환 (timestamp -> trend_state)
    pine_dict = {}
    for _, row in pine_df.iterrows():
        ts = row['datetime']
        pine_dict[ts] = row['trend_state']

    # 매칭 및 비교
    matches = 0
    mismatches = 0
    not_found = 0

    mismatch_details = []

    for i, candle in enumerate(result_filtered):
        ts = candle['timestamp']
        python_trend = candle.get('trend_state', 0)

        if ts in pine_dict:
            pine_trend = pine_dict[ts]

            if python_trend == pine_trend:
                matches += 1
            else:
                mismatches += 1
                if len(mismatch_details) < 20:  # 처음 20개만 저장
                    mismatch_details.append({
                        'index': i,
                        'timestamp': ts,
                        'close': candle.get('close', 0),
                        'python': python_trend,
                        'pine': pine_trend,
                        'bb_state': candle.get('BB_State', 0),
                        'bb_state_mtf': candle.get('BB_State_MTF', 0),
                        'bb_state_mtf_pine': pine_df[pine_df['datetime'] == ts]['BB_state_MTF'].values[0] if ts in pine_dict else 'N/A',
                        'cycle_bull': candle.get('CYCLE_Bull', False),
                        'cycle_bear': candle.get('CYCLE_Bear', False)
                    })
        else:
            not_found += 1

    total = matches + mismatches

    # 5. 결과 출력
    print("\n" + "=" * 120)
    print("비교 결과")
    print("=" * 120)

    print(f"\n📊 전체 통계:")
    print(f"   총 비교: {total}개")
    print(f"   ✅ 일치: {matches}개 ({matches/total*100:.1f}%)")
    print(f"   ❌ 불일치: {mismatches}개 ({mismatches/total*100:.1f}%)")
    print(f"   🔍 매칭 안됨: {not_found}개")

    # 불일치 상세 출력
    if mismatch_details:
        print("\n" + "=" * 120)
        print("불일치 상세 (처음 20개)")
        print("=" * 120)

        print(f"\n{'Idx':<5} {'Timestamp':<20} {'Close':>10} {'BB_St':>7} {'BB_MTF_Py':>10} {'BB_MTF_Pin':>11} "
              f"{'CYC_B':>7} {'CYC_b':>7} {'Python':>7} {'Pine':>7}")
        print("-" * 140)

        for detail in mismatch_details:
            cycle_bull_str = "Bull" if detail['cycle_bull'] else "----"
            cycle_bear_str = "Bear" if detail['cycle_bear'] else "----"

            print(f"{detail['index']:<5} {str(detail['timestamp'])[:19]:<20} {detail['close']:>10.2f} "
                  f"{detail['bb_state']:>7} {detail['bb_state_mtf']:>10} {detail['bb_state_mtf_pine']:>11} "
                  f"{cycle_bull_str:>7} {cycle_bear_str:>7} "
                  f"{detail['python']:>7} {detail['pine']:>7}")

    # 6. 처음 50개 캔들 상세 비교
    print("\n" + "=" * 120)
    print("처음 50개 캔들 상세 비교")
    print("=" * 120)

    print(f"\n{'Idx':<5} {'Timestamp':<20} {'Close':>10} {'Python':>7} {'Pine':>7} {'Match':<6}")
    print("-" * 120)

    for i in range(min(150, len(result_filtered))):
        candle = result_filtered[i]
        ts = candle['timestamp']
        python_trend = candle.get('trend_state', 0)

        pine_trend = pine_dict.get(ts, 'N/A')

        if pine_trend != 'N/A':
            match = "✅" if python_trend == pine_trend else "❌"
        else:
            match = "🔍"

        print(f"{i:<5} {str(ts)[:19]:<20} {candle.get('close', 0):>10.2f} "
              f"{python_trend:>7} {pine_trend:>7} {match:<6}")


if __name__ == "__main__":
    asyncio.run(compare_with_pinescript())
