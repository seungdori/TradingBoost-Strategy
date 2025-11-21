"""
Forward fill 로직 테스트

목적: _forward_fill_mtf_to_current_tf() 함수가 제대로 작동하는지 확인
"""

import asyncio
from datetime import datetime, timedelta, timezone
from shared.indicators._trend import _calc_bb_state, _forward_fill_mtf_to_current_tf
from BACKTEST.data.okx_provider import OKXProvider


async def test_forward_fill():
    """Forward fill 로직 테스트"""

    print("=" * 80)
    print("Forward Fill 로직 테스트")
    print("=" * 80)

    # 1. 데이터 수집
    print("\n📊 데이터 수집 중...")

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=6)  # 6시간만 (짧게)

    okx_provider = OKXProvider()

    # 1분봉
    candles_1m_raw = await okx_provider.get_candles(
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

    # 5분봉
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

    print(f"✅ 1분봉: {len(candles_1m)}개")
    print(f"✅ 5분봉: {len(candles_5m)}개")

    # 2. 5분봉 BB_State 계산
    print("\n⚙️  5분봉 BB_State 계산 중...")

    bb_state_5m = _calc_bb_state(
        candles_5m,
        length_bb=15,
        mult_bb=1.5,
        ma_length=100,
        is_confirmed_only=True
    )

    print(f"✅ BB_State 계산 완료: {len(bb_state_5m)}개")

    # 5분봉 마지막 10개 출력
    print("\n📊 5분봉 마지막 10개 BB_State:")
    for i in range(max(0, len(candles_5m) - 10), len(candles_5m)):
        ts = candles_5m[i]['timestamp']
        bb = bb_state_5m[i]
        print(f"  [{i}] {ts} → BB_State = {bb}")

    # 3. Forward fill 적용
    print("\n⚙️  Forward fill 적용 중...")

    bb_state_1m = _forward_fill_mtf_to_current_tf(
        candles_current=candles_1m,
        candles_mtf=candles_5m,
        mtf_values=bb_state_5m,
        is_backtest=True
    )

    print(f"✅ Forward fill 완료: {len(bb_state_1m)}개")

    # 4. 1분봉 마지막 50개 출력 (5분 단위로 그룹핑해서 확인)
    print("\n" + "=" * 80)
    print("1분봉 마지막 50개 BB_State_MTF (forward filled)")
    print("=" * 80)

    start_idx = max(0, len(candles_1m) - 50)

    print(f"\n{'Index':<8} {'Timestamp':<20} {'BB_MTF':>10} {'Note':<30}")
    print("-" * 80)

    for i in range(start_idx, len(candles_1m)):
        ts = candles_1m[i]['timestamp']
        bb_mtf = bb_state_1m[i]

        # 5분 경계 확인
        minute = ts.minute if isinstance(ts, datetime) else datetime.fromtimestamp(ts).minute
        is_5m_boundary = (minute % 5 == 0)

        note = "★ 5분 경계" if is_5m_boundary else ""

        print(f"{i:<8} {str(ts)[:19]:<20} {bb_mtf:>10} {note:<30}")

    # 5. 통계
    print("\n" + "=" * 80)
    print("BB_State_MTF 통계 (1분봉 전체)")
    print("=" * 80)

    bb_state_counts = {-2: 0, -1: 0, 0: 0, 1: 0, 2: 0}
    for state in bb_state_1m:
        bb_state_counts[state] = bb_state_counts.get(state, 0) + 1

    total = len(bb_state_1m)
    for state in sorted(bb_state_counts.keys()):
        count = bb_state_counts[state]
        pct = count / total * 100 if total > 0 else 0
        print(f"   State {state:>2}: {count:>3}회 ({pct:>5.1f}%)")

    await okx_provider.close()


if __name__ == "__main__":
    asyncio.run(test_forward_fill())
