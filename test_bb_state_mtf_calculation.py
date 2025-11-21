"""
BB_State_MTF 계산 로직 검증

목적: TimescaleDB vs OKX API 데이터로 계산한 BB_State 비교
"""

import asyncio
from datetime import datetime, timedelta, timezone
from BACKTEST.data.timescale_provider import TimescaleProvider
from BACKTEST.data.okx_provider import OKXProvider
from shared.indicators._trend import _calc_bb_state


async def test_bb_state_calculation():
    """BB_State 계산 비교 테스트"""

    print("=" * 80)
    print("BB_State 계산 비교: TimescaleDB vs OKX API")
    print("=" * 80)

    # 데이터 수집
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=1)

    # 1. TimescaleDB에서 5분봉 가져오기
    print("\n📊 TimescaleDB에서 5분봉 수집 중...")
    ts_provider = TimescaleProvider()
    ts_candles_raw = await ts_provider.get_candles(
        symbol="BTC-USDT-SWAP",
        timeframe="5m",
        start_date=start_time,
        end_date=end_time
    )

    ts_candles = [
        {
            'timestamp': c.timestamp,
            'open': c.open,
            'high': c.high,
            'low': c.low,
            'close': c.close,
            'volume': c.volume
        }
        for c in ts_candles_raw
    ]

    print(f"✅ TimescaleDB: {len(ts_candles)}개 5분봉")

    # 2. OKX API에서 5분봉 가져오기
    print("\n📊 OKX API에서 5분봉 수집 중...")
    okx_provider = OKXProvider()
    okx_candles_raw = await okx_provider.get_candles(
        symbol="BTC-USDT-SWAP",
        timeframe="5m",
        start_date=start_time,
        end_date=end_time
    )

    okx_candles = [
        {
            'timestamp': c.timestamp,
            'open': c.open,
            'high': c.high,
            'low': c.low,
            'close': c.close,
            'volume': c.volume
        }
        for c in okx_candles_raw
    ]

    print(f"✅ OKX API: {len(okx_candles)}개 5분봉")

    # 3. 각각 BB_State 계산
    print("\n⚙️  BB_State 계산 중...")
    ts_bb_state = _calc_bb_state(ts_candles, length_bb=15, mult_bb=1.5, ma_length=100, is_confirmed_only=True)
    okx_bb_state = _calc_bb_state(okx_candles, length_bb=15, mult_bb=1.5, ma_length=100, is_confirmed_only=True)

    print(f"✅ TimescaleDB BB_State: {len(ts_bb_state)}개")
    print(f"✅ OKX API BB_State: {len(okx_bb_state)}개")

    # 4. 통계 비교
    print("\n" + "=" * 80)
    print("📊 통계 비교")
    print("=" * 80)

    # TimescaleDB 통계
    ts_counts = {-2: 0, -1: 0, 0: 0, 1: 0, 2: 0}
    for state in ts_bb_state:
        ts_counts[state] = ts_counts.get(state, 0) + 1

    # OKX API 통계
    okx_counts = {-2: 0, -1: 0, 0: 0, 1: 0, 2: 0}
    for state in okx_bb_state:
        okx_counts[state] = okx_counts.get(state, 0) + 1

    print("\nTimescaleDB BB_State 분포:")
    total_ts = len(ts_bb_state)
    for state in sorted(ts_counts.keys()):
        count = ts_counts[state]
        pct = count / total_ts * 100 if total_ts > 0 else 0
        print(f"   State {state:>2}: {count:>3}회 ({pct:>5.1f}%)")

    print("\nOKX API BB_State 분포:")
    total_okx = len(okx_bb_state)
    for state in sorted(okx_counts.keys()):
        count = okx_counts[state]
        pct = count / total_okx * 100 if total_okx > 0 else 0
        print(f"   State {state:>2}: {count:>3}회 ({pct:>5.1f}%)")

    # 5. 마지막 20개 값 비교
    print("\n" + "=" * 80)
    print("📊 마지막 20개 값 직접 비교")
    print("=" * 80)

    print(f"\n{'Index':<8} {'TimescaleDB':<15} {'OKX API':<15} {'Match':<10}")
    print("-" * 50)

    compare_count = min(20, len(ts_bb_state), len(okx_bb_state))
    start_idx = len(ts_bb_state) - compare_count

    match_count = 0
    for i in range(compare_count):
        idx = start_idx + i
        ts_val = ts_bb_state[idx]
        okx_val = okx_bb_state[idx]
        match = "✅" if ts_val == okx_val else "❌"
        if ts_val == okx_val:
            match_count += 1

        print(f"{idx:<8} {ts_val:<15} {okx_val:<15} {match:<10}")

    print(f"\n일치율: {match_count}/{compare_count} ({match_count/compare_count*100:.1f}%)")

    await okx_provider.close()


if __name__ == "__main__":
    asyncio.run(test_bb_state_calculation())
