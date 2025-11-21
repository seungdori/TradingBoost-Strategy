#!/usr/bin/env python3
"""
Redis:1368-1372의 BB_State 계산 흐름 추적
"""

import redis
import json
from datetime import datetime
from shared.config import get_settings
from shared.indicators._trend import _calc_bb_state


def main():
    # Redis 데이터 로드
    settings = get_settings()
    r = redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=0,
        decode_responses=True
    )

    redis_key = "candles_with_indicators:BTC-USDT-SWAP:15m"
    data_list = r.lrange(redis_key, 0, -1)
    redis_candles = [json.loads(item) for item in data_list]

    all_candles = []
    for c in redis_candles:
        all_candles.append({
            "timestamp": datetime.fromtimestamp(c["timestamp"]),
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
            "volume": float(c.get("volume", 0))
        })

    # BB_State 계산
    bb_state_results = _calc_bb_state(all_candles, is_confirmed_only=False)

    # 결과 출력
    print("=" * 100)
    print("Redis:1368-1372 BB_State 계산 흐름")
    print("=" * 100)
    print()

    print(f"{'Index':<7} {'Timestamp':<20} {'Close':>10} {'Python BB_State':>17}")
    print("-" * 100)

    for idx in range(1368, 1373):
        print(f"{idx:<7} {str(all_candles[idx]['timestamp'])[:19]:<20} {all_candles[idx]['close']:>10.2f} {bb_state_results[idx]:>17}")

    print()
    print("=" * 100)
    print("Pine vs Python 비교")
    print("=" * 100)
    print()

    # Pine 값 (CSV에서)
    import pandas as pd
    csv_path = "/Users/seunghyun/Downloads/OKX_BTCUSDT.P, 15_ba3e6.csv"
    pine_df = pd.read_csv(csv_path)

    print(f"{'CSV':<5} {'Redis':<7} {'Pine BB_State':>15} {'Python BB_State':>17} {'Match':<6}")
    print("-" * 70)

    csv_start = 1358
    for csv_idx in range(10, 16):  # CSV 10-15 = Redis 1368-1373
        redis_idx = csv_start + csv_idx
        pine_state = int(pine_df.iloc[csv_idx]['BB_State'])
        python_state = bb_state_results[redis_idx]
        match = "✅" if pine_state == python_state else "❌"

        print(f"{csv_idx:<5} {redis_idx:<7} {pine_state:>15} {python_state:>17} {match:<6}")


if __name__ == "__main__":
    main()
