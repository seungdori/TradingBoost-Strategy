"""
18:45 시점의 BB_State_MTF forward fill 디버깅
"""

import asyncio
from datetime import datetime, timedelta, timezone
from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._trend import _calc_bb_state, _forward_fill_mtf_to_current_tf


async def debug_bb_mtf_18_45():
    """18:45 시점 BB_State_MTF forward fill 디버깅"""

    print("=" * 140)
    print("18:45 시점 BB_State_MTF Forward Fill 디버깅")
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

    # 5분봉 (BB_State_MTF 계산용)
    candles_5m_raw = await provider.get_candles("BTC-USDT-SWAP", "5m", start_time, end_time)
    candles_5m = [
        {'timestamp': c.timestamp, 'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close, 'volume': c.volume}
        for c in candles_5m_raw
    ]

    print(f"\n📊 1분봉: {len(candles_1m)}개")
    print(f"📊 5분봉: {len(candles_5m)}개")

    # 5분봉 BB_State 계산
    bb_state_5m = _calc_bb_state(candles_5m, length_bb=15, mult_bb=1.5, ma_length=100, is_confirmed_only=True)

    # 18:30~19:00 범위의 5분봉 BB_State 출력
    print("\n" + "=" * 100)
    print("5분봉 BB_State (18:30~19:00)")
    print("=" * 100)

    print(f"\n{'Index':<8} {'Timestamp':<20} {'Close':>10} {'BB_State':>10}")
    print("-" * 100)

    target_start = datetime(2025, 11, 16, 18, 30, 0, tzinfo=timezone.utc)
    target_end = datetime(2025, 11, 16, 19, 0, 0, tzinfo=timezone.utc)

    for i, c in enumerate(candles_5m):
        if target_start <= c['timestamp'] <= target_end:
            print(f"{i:<8} {str(c['timestamp'])[:19]:<20} {c['close']:>10.2f} {bb_state_5m[i]:>10}")

    # Forward fill 실행
    print("\n⚙️  Forward Fill 실행 중 (is_backtest=True, 1-offset 적용)...")

    bb_state_mtf_filled = _forward_fill_mtf_to_current_tf(
        candles_current=candles_1m,
        candles_mtf=candles_5m,
        mtf_values=bb_state_5m,
        is_backtest=True  # 1-offset 적용
    )

    # Forward fill 결과 출력 (18:42~18:48)
    print("\n" + "=" * 140)
    print("1분봉 BB_State_MTF (Forward Fill 결과, 18:42~18:48)")
    print("=" * 140)

    print(f"\n{'1m_idx':<8} {'1m_Time':<20} {'5m_idx':<9} {'5m_Time':<20} {'5m_BB':>8} {'Offset_idx':<11} {'Offset_BB':>10} {'Result_BB':>10}")
    print("-" * 140)

    # 5분봉 timestamps
    mtf_timestamps = [c['timestamp'] for c in candles_5m]

    mtf_idx = 0
    for i, c in enumerate(candles_1m):
        ts = c['timestamp']

        if not (datetime(2025, 11, 16, 18, 42, 0, tzinfo=timezone.utc) <= ts <= datetime(2025, 11, 16, 18, 48, 0, tzinfo=timezone.utc)):
            continue

        # 현재 캔들 timestamp보다 작거나 같은 가장 최근 MTF 인덱스 찾기
        while mtf_idx + 1 < len(mtf_timestamps) and mtf_timestamps[mtf_idx + 1] <= ts:
            mtf_idx += 1

        # 현재 MTF 값
        current_mtf_time = mtf_timestamps[mtf_idx] if mtf_idx < len(mtf_timestamps) else None
        current_mtf_bb = bb_state_5m[mtf_idx] if mtf_idx < len(bb_state_5m) else 0

        # 1-offset 적용 (is_backtest=True)
        if mtf_idx > 0:
            offset_idx = mtf_idx - 1
            offset_bb = bb_state_5m[offset_idx]
        else:
            offset_idx = None
            offset_bb = 0

        result_bb = bb_state_mtf_filled[i]

        print(f"{i:<8} {str(ts)[:19]:<20} {mtf_idx:<9} {str(current_mtf_time)[:19] if current_mtf_time else 'N/A':<20} {current_mtf_bb:>8} {str(offset_idx) if offset_idx is not None else 'N/A':<11} {offset_bb:>10} {result_bb:>10}")


if __name__ == "__main__":
    asyncio.run(debug_bb_mtf_18_45())
