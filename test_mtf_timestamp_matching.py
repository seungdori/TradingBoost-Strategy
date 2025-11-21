"""
MTF Timestamp 매칭 로직 검증

목적: 1분봉과 5분봉의 timestamp 매칭이 제대로 되는지 확인
"""

import asyncio
from datetime import datetime, timedelta, timezone
from BACKTEST.data.okx_provider import OKXProvider
from shared.indicators._trend import _forward_fill_mtf_to_current_tf, _calc_bb_state


async def test_mtf_timestamp_matching():
    """MTF timestamp 매칭 테스트"""

    print("=" * 80)
    print("MTF Timestamp 매칭 테스트")
    print("=" * 80)

    # 데이터 수집 (짧은 기간)
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=2)  # 2시간만

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

    print(f"\n📊 1분봉: {len(candles_1m)}개")
    print(f"📊 5분봉: {len(candles_5m)}개")

    # BB_State 계산
    print("\n⚙️  5분봉 BB_State 계산 중...")
    bb_state_5m = _calc_bb_state(candles_5m, length_bb=15, mult_bb=1.5, ma_length=100, is_confirmed_only=True)

    print(f"✅ BB_State 계산 완료: {len(bb_state_5m)}개")

    # Forward fill 적용
    print("\n⚙️  Forward fill 적용 중...")
    bb_state_1m = _forward_fill_mtf_to_current_tf(
        candles_current=candles_1m,
        candles_mtf=candles_5m,
        mtf_values=bb_state_5m,
        is_backtest=True
    )

    print(f"✅ Forward fill 완료: {len(bb_state_1m)}개")

    # 마지막 30개 1분봉 출력 (5분 단위로 그룹핑)
    print("\n" + "=" * 80)
    print("마지막 30개 1분봉 BB_State_MTF (forward filled)")
    print("=" * 80)

    start_idx = max(0, len(candles_1m) - 30)

    print(f"\n{'Index':<8} {'Timestamp':<20} {'Minute':<8} {'BB_MTF':>10} {'Note':<30}")
    print("-" * 80)

    for i in range(start_idx, len(candles_1m)):
        ts = candles_1m[i]['timestamp']
        bb_mtf = bb_state_1m[i]

        # 분 단위 추출
        minute = ts.minute

        # 5분 경계 확인
        is_5m_boundary = (minute % 5 == 0)
        note = "★ 5분 경계" if is_5m_boundary else ""

        # 5분봉에서 해당하는 인덱스 찾기
        mtf_idx = None
        for j, c5m in enumerate(candles_5m):
            if c5m['timestamp'] <= ts:
                mtf_idx = j

        mtf_note = f"(5m#{mtf_idx}: {bb_state_5m[mtf_idx]})" if mtf_idx is not None and mtf_idx < len(bb_state_5m) else ""

        print(f"{i:<8} {str(ts)[:19]:<20} {minute:<8} {bb_mtf:>10} {note:<15} {mtf_note}")

    # 5분봉 마지막 10개 출력
    print("\n" + "=" * 80)
    print("5분봉 마지막 10개 BB_State")
    print("=" * 80)

    start_idx_5m = max(0, len(candles_5m) - 10)

    print(f"\n{'Index':<8} {'Timestamp':<20} {'BB_State':>10}")
    print("-" * 50)

    for i in range(start_idx_5m, len(candles_5m)):
        ts = candles_5m[i]['timestamp']
        bb = bb_state_5m[i]
        print(f"{i:<8} {str(ts)[:19]:<20} {bb:>10}")

    await okx_provider.close()


if __name__ == "__main__":
    asyncio.run(test_mtf_timestamp_matching())
