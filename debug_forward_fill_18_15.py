"""
18:15 시점의 forward fill 디버깅
"""

import asyncio
from datetime import datetime, timedelta, timezone
from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._trend import _calc_bb_state, _forward_fill_mtf_to_current_tf


async def debug_forward_fill_18_15():
    """18:15 시점 forward fill 디버깅"""

    print("=" * 140)
    print("18:15 시점 Forward Fill 디버깅")
    print("=" * 140)

    provider = TimescaleProvider()

    # CSV 시작 7일 전부터 로드
    csv_start = datetime(2025, 11, 16, 16, 51, 0, tzinfo=timezone.utc)
    start_time = csv_start - timedelta(days=7)
    end_time = datetime(2025, 11, 17, 7, 1, 0, tzinfo=timezone.utc)

    # 1분봉
    candles_1m_raw = await provider.get_candles("BTC-USDT-SWAP", "1m", start_time, end_time)
    candles_1m = [
        {'timestamp': c.timestamp, 'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close, 'volume': c.volume}
        for c in candles_1m_raw
    ]

    # 5분봉
    candles_5m_raw = await provider.get_candles("BTC-USDT-SWAP", "5m", start_time, end_time)
    candles_5m = [
        {'timestamp': c.timestamp, 'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close, 'volume': c.volume}
        for c in candles_5m_raw
    ]

    print(f"\n📊 1분봉: {len(candles_1m)}개")
    print(f"📊 5분봉: {len(candles_5m)}개")

    # 18:00~18:30 범위만 필터링
    target_start = datetime(2025, 11, 16, 18, 0, 0, tzinfo=timezone.utc)
    target_end = datetime(2025, 11, 16, 18, 30, 0, tzinfo=timezone.utc)

    candles_1m_filtered = [c for c in candles_1m if target_start <= c['timestamp'] <= target_end]
    candles_5m_filtered = [c for c in candles_5m if target_start <= c['timestamp'] <= target_end]

    print(f"\n📊 1분봉 (18:00~18:30): {len(candles_1m_filtered)}개")
    print(f"📊 5분봉 (18:00~18:30): {len(candles_5m_filtered)}개")

    # 5분봉 BB_State 계산
    bb_state_5m = _calc_bb_state(candles_5m, length_bb=15, mult_bb=1.5, ma_length=100, is_confirmed_only=True)

    # 5분봉 BB_State 출력 (18:00~18:30)
    print("\n" + "=" * 100)
    print("5분봉 BB_State (18:00~18:30)")
    print("=" * 100)

    print(f"\n{'Index':<8} {'Timestamp':<20} {'Close':>10} {'BB_State':>10}")
    print("-" * 100)

    for i, c in enumerate(candles_5m):
        if target_start <= c['timestamp'] <= target_end:
            print(f"{i:<8} {str(c['timestamp'])[:19]:<20} {c['close']:>10.2f} {bb_state_5m[i]:>10}")

    # Forward fill 실행
    print("\n⚙️  Forward Fill 실행 중...")

    bb_state_mtf_filled = _forward_fill_mtf_to_current_tf(
        candles_current=candles_1m,
        candles_mtf=candles_5m,
        mtf_values=bb_state_5m,
        is_backtest=True
    )

    # Forward fill 결과 출력 (18:00~18:30)
    print("\n" + "=" * 140)
    print("1분봉 BB_State_MTF (Forward Fill 결과, 18:00~18:30)")
    print("=" * 140)

    print(f"\n{'Index':<8} {'Timestamp':<20} {'Close':>10} {'BB_MTF':>10} {'Expected':>10}")
    print("-" * 140)

    # 18:00~18:30 구간의 1분봉 index 찾기
    for i, c in enumerate(candles_1m):
        if target_start <= c['timestamp'] <= target_end:
            ts = c['timestamp']
            close = c['close']
            bb_mtf = bb_state_mtf_filled[i]

            # 예상값: 1-offset 적용
            # 18:00~18:04 → 17:55 5분봉 (index 찾아야 함)
            # 18:05~18:09 → 18:00 5분봉
            # 18:10~18:14 → 18:05 5분봉
            # 18:15~18:19 → 18:10 5분봉
            # 18:20~18:24 → 18:15 5분봉

            # 해당 1분봉에 대응하는 5분봉 찾기
            mtf_idx = None
            for j, c5m in enumerate(candles_5m):
                if c5m['timestamp'] <= ts:
                    mtf_idx = j

            # 1-offset 적용 (backtest mode)
            if mtf_idx is not None and mtf_idx > 0:
                expected_bb = bb_state_5m[mtf_idx - 1]
            else:
                expected_bb = 0

            print(f"{i:<8} {str(ts)[:19]:<20} {close:>10.2f} {bb_mtf:>10} {expected_bb:>10}")


if __name__ == "__main__":
    asyncio.run(debug_forward_fill_18_15())
