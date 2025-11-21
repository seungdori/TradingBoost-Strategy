"""
Forward fill 로직 상세 디버깅
"""

import asyncio
from datetime import datetime, timedelta, timezone
from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._trend import _forward_fill_mtf_to_current_tf


async def test_forward_fill_logic():
    """Forward fill 로직 상세 출력"""

    print("=" * 120)
    print("Forward Fill 로직 디버깅")
    print("=" * 120)

    # 간단한 예제: 1분봉 30개, 15분봉 2개
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=1)

    provider = TimescaleProvider()

    # 1분봉 30개
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
        for c in candles_1m_raw[:30]
    ]

    # 15분봉 2개
    candles_15m_raw = await provider.get_candles(
        symbol="BTC-USDT-SWAP",
        timeframe="15m",
        start_date=start_time,
        end_date=end_time
    )

    candles_15m = [
        {
            'timestamp': c.timestamp,
            'open': c.open,
            'high': c.high,
            'low': c.low,
            'close': c.close,
            'volume': c.volume
        }
        for c in candles_15m_raw[:3]
    ]

    print(f"\n📊 1분봉: {len(candles_1m)}개")
    print(f"📊 15분봉: {len(candles_15m)}개")

    # 가상의 MTF 값 (실제로는 MA 계산 결과)
    mtf_values = [100.0, 200.0, 300.0]

    # Forward fill 실행
    result = _forward_fill_mtf_to_current_tf(
        candles_current=candles_1m,
        candles_mtf=candles_15m,
        mtf_values=mtf_values,
        is_backtest=True
    )

    print("\n" + "=" * 120)
    print("Forward Fill 결과")
    print("=" * 120)

    print(f"\n{'Idx':<5} {'1m Timestamp':<20} {'15m Timestamp':<20} {'MTF Value':>12} {'Result':>10}")
    print("-" * 120)

    for i in range(len(candles_1m)):
        ts_1m = candles_1m[i]['timestamp']

        # 해당 1분봉에 매칭되는 15분봉 찾기
        matched_15m_idx = None
        matched_15m_ts = None
        for j, c15m in enumerate(candles_15m):
            if c15m['timestamp'] <= ts_1m:
                matched_15m_idx = j
                matched_15m_ts = c15m['timestamp']

        matched_15m_str = f"{str(matched_15m_ts)[:19]} (#{matched_15m_idx})" if matched_15m_ts else "N/A"
        mtf_val_str = f"{mtf_values[matched_15m_idx]:.1f}" if matched_15m_idx is not None else "N/A"

        print(f"{i:<5} {str(ts_1m)[:19]:<20} {matched_15m_str:<20} {mtf_val_str:>12} {result[i]:>10.1f}")

    # 15분봉 출력
    print("\n" + "=" * 80)
    print("15분봉 MTF 값")
    print("=" * 80)

    print(f"\n{'Index':<8} {'Timestamp':<20} {'MTF Value':>12}")
    print("-" * 50)

    for i, c15m in enumerate(candles_15m):
        ts = c15m['timestamp']
        mtf_val = mtf_values[i]
        print(f"{i:<8} {str(ts)[:19]:<20} {mtf_val:>12.1f}")


if __name__ == "__main__":
    asyncio.run(test_forward_fill_logic())
