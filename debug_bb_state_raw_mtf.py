"""
5분봉으로 직접 계산한 BB_State 값 확인

목적: bb_state_mtf_raw가 왜 0인지 확인
"""

import asyncio
from datetime import datetime, timedelta, timezone
from shared.indicators._trend import _calc_bb_state
from BACKTEST.data.okx_provider import OKXProvider


async def debug_bb_state_raw():
    """5분봉 원본으로 BB_State 계산 테스트"""

    print("=" * 80)
    print("5분봉 BB_State 직접 계산 테스트")
    print("=" * 80)

    # 1. 5분봉 데이터 수집
    print("\n📊 5분봉 데이터 수집 중...")

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=1)

    okx_provider = OKXProvider()

    candles_5m_raw = await okx_provider.get_candles(
        symbol="BTC-USDT-SWAP",
        timeframe="5m",
        start_date=start_time,
        end_date=end_time
    )

    candles_5m = [
        {
            'timestamp': c.timestamp,
            'open': c.open,
            'high': c.high,
            'low': c.low,
            'close': c.close,
            'volume': c.volume
        }
        for c in candles_5m_raw
    ]

    print(f"✅ 총 {len(candles_5m)}개 5분봉 수집 완료")

    # 2. BB_State 계산
    print("\n⚙️  BB_State 계산 중...")

    bb_state_5m = _calc_bb_state(
        candles_5m,
        length_bb=15,
        mult_bb=1.5,
        ma_length=100,
        is_confirmed_only=True
    )

    print(f"✅ 총 {len(bb_state_5m)}개 BB_State 계산 완료")

    # 3. 마지막 50개 값 출력
    print("\n" + "=" * 80)
    print("마지막 50개 5분봉 BB_State 값")
    print("=" * 80)

    start_idx = max(0, len(candles_5m) - 50)

    print(f"\n{'Index':<8} {'Timestamp':<20} {'Close':>10} {'BB_State':>10}")
    print("-" * 60)

    for i in range(start_idx, len(candles_5m)):
        timestamp = candles_5m[i]['timestamp']
        close = candles_5m[i]['close']
        bb_state = bb_state_5m[i]

        print(f"{i:<8} {str(timestamp)[:19]:<20} {close:>10.2f} {bb_state:>10}")

    # 4. 통계
    print("\n" + "=" * 80)
    print("BB_State 통계 (전체)")
    print("=" * 80)

    bb_state_counts = {-2: 0, -1: 0, 0: 0, 1: 0, 2: 0}
    for state in bb_state_5m:
        bb_state_counts[state] = bb_state_counts.get(state, 0) + 1

    total = len(bb_state_5m)
    for state in sorted(bb_state_counts.keys()):
        count = bb_state_counts[state]
        pct = count / total * 100 if total > 0 else 0
        print(f"   State {state:>2}: {count:>3}회 ({pct:>5.1f}%)")

    await okx_provider.close()


if __name__ == "__main__":
    asyncio.run(debug_bb_state_raw())
