"""
18:45 시점 forward fill 상세 디버깅
"""

import asyncio
from datetime import datetime, timedelta, timezone
from BACKTEST.data.timescale_provider import TimescaleProvider


async def debug_forward_fill_detail():
    """18:45 시점 forward fill 상세 디버깅"""

    print("=" * 140)
    print("18:45 시점 Forward Fill 상세 디버깅")
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

    # 15분봉
    candles_15m_raw = await provider.get_candles("BTC-USDT-SWAP", "15m", start_time, end_time)
    candles_15m = [
        {'timestamp': c.timestamp, 'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close, 'volume': c.volume}
        for c in candles_15m_raw
    ]

    print(f"\n📊 1분봉: {len(candles_1m)}개")
    print(f"📊 15분봉: {len(candles_15m)}개")

    # 18:30~19:00 범위만 필터링
    target_start = datetime(2025, 11, 16, 18, 30, 0, tzinfo=timezone.utc)
    target_end = datetime(2025, 11, 16, 19, 0, 0, tzinfo=timezone.utc)

    # Forward fill 수동 시뮬레이션 (18:42~18:48만)
    print("\n" + "=" * 140)
    print("Forward Fill 수동 시뮬레이션 (18:42~18:48)")
    print("=" * 140)

    # 가상의 MTF 값 (15분봉)
    mtf_values_example = {}
    for c15m in candles_15m:
        if datetime(2025, 11, 16, 18, 30, 0, tzinfo=timezone.utc) <= c15m['timestamp'] <= target_end:
            # 18:30은 False, 18:45는 True로 가정
            if c15m['timestamp'] == datetime(2025, 11, 16, 18, 30, 0, tzinfo=timezone.utc):
                mtf_values_example[c15m['timestamp']] = False
            elif c15m['timestamp'] == datetime(2025, 11, 16, 18, 45, 0, tzinfo=timezone.utc):
                mtf_values_example[c15m['timestamp']] = True
            else:
                mtf_values_example[c15m['timestamp']] = False

    print(f"\n15분봉 가상 값:")
    for ts, val in sorted(mtf_values_example.items()):
        print(f"  {ts}: {val}")

    print(f"\n{'1m_idx':<8} {'1m_Time':<20} {'15m_idx':<9} {'15m_Time':<20} {'15m_Value':>11} {'Offset_idx':<11} {'Offset_Time':<20} {'Offset_Value':>13} {'Result':>8}")
    print("-" * 140)

    # 15분봉 timestamps
    mtf_timestamps = [c['timestamp'] for c in candles_15m]
    mtf_values_list = [mtf_values_example.get(ts, False) for ts in mtf_timestamps]

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
        current_mtf_value = mtf_values_list[mtf_idx] if mtf_idx < len(mtf_values_list) else None

        # 1-offset 적용 (is_backtest=True)
        if mtf_idx > 0:
            offset_idx = mtf_idx - 1
            offset_time = mtf_timestamps[offset_idx]
            offset_value = mtf_values_list[offset_idx]
            result_value = offset_value
        else:
            offset_idx = None
            offset_time = None
            offset_value = None
            result_value = False

        print(f"{i:<8} {str(ts)[:19]:<20} {mtf_idx:<9} {str(current_mtf_time)[:19] if current_mtf_time else 'N/A':<20} {str(current_mtf_value):>11} {str(offset_idx) if offset_idx is not None else 'N/A':<11} {str(offset_time)[:19] if offset_time else 'N/A':<20} {str(offset_value):>13} {str(result_value):>8}")


if __name__ == "__main__":
    asyncio.run(debug_forward_fill_detail())
