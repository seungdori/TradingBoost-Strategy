#!/usr/bin/env python3
"""
Pine Script CSV의 BB_State와 Python 계산 결과 비교

CSV 파일: /Users/seunghyun/Downloads/OKX_BTCUSDT.P, 15_ba3e6.csv
- 1641개 15분봉 캔들
- 2025-11-01 ~ 2025-11-18
- Redis index: 1358부터 시작
"""

import redis
import json
import pandas as pd
from datetime import datetime
from shared.config import get_settings
from shared.indicators._trend import _calc_bb_state


def main():
    print("=" * 120)
    print("Pine Script BB_State vs Python 계산 결과 비교")
    print("=" * 120)

    # 1. Pine Script CSV 로드
    csv_path = "/Users/seunghyun/Downloads/OKX_BTCUSDT.P, 15_ba3e6.csv"
    pine_df = pd.read_csv(csv_path)

    print(f"\n📊 Pine Script CSV 데이터: {len(pine_df)}개")
    print(f"   시간 범위: {pine_df['time'].min()} ~ {pine_df['time'].max()}")

    # ISO 형식 문자열을 datetime으로 변환
    pine_df['datetime'] = pd.to_datetime(pine_df['time'], utc=True)
    print(f"   날짜 범위: {pine_df['datetime'].min()} ~ {pine_df['datetime'].max()}")

    # 2. Redis에서 데이터 가져오기
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

    print(f"\n🔍 Redis 데이터: {len(redis_candles)}개")

    # 캔들 변환
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

    # 3. Python으로 BB_State 계산
    print(f"\n⚙️  Python BB_State 계산 중...")
    bb_state_results = _calc_bb_state(all_candles, is_confirmed_only=False)
    print(f"✅ 계산 완료: {len(bb_state_results)}개")

    # CSV 시작 시간 (Redis index 1358)
    csv_start_idx = 1358
    csv_start_time = all_candles[csv_start_idx]["timestamp"]
    print(f"\n📍 CSV 시작: Redis index {csv_start_idx}, timestamp {csv_start_time}")

    # 4. 매칭 및 비교
    print(f"\n🔗 타임스탬프 기준 매칭 중...")

    matches = 0
    mismatches = 0
    mismatch_details = []

    for csv_idx, (_, row) in enumerate(pine_df.iterrows()):
        redis_idx = csv_start_idx + csv_idx

        if redis_idx >= len(all_candles):
            break

        # Skip NaN values in CSV
        if pd.isna(row['BB_State']):
            continue

        pine_bb_state = int(row['BB_State'])
        python_bb_state = bb_state_results[redis_idx]

        if pine_bb_state == python_bb_state:
            matches += 1
        else:
            mismatches += 1
            if len(mismatch_details) < 20:
                mismatch_details.append({
                    'csv_idx': csv_idx,
                    'redis_idx': redis_idx,
                    'timestamp': all_candles[redis_idx]['timestamp'],
                    'close': all_candles[redis_idx]['close'],
                    'pine': pine_bb_state,
                    'python': python_bb_state
                })

    total = matches + mismatches

    # 5. 결과 출력
    print("\n" + "=" * 120)
    print("비교 결과")
    print("=" * 120)

    print(f"\n📊 전체 통계:")
    print(f"   총 비교: {total}개")
    print(f"   ✅ 일치: {matches}개 ({matches/total*100:.2f}%)")
    print(f"   ❌ 불일치: {mismatches}개 ({mismatches/total*100:.2f}%)")

    # 불일치 상세 출력
    if mismatch_details:
        print("\n" + "=" * 120)
        print("불일치 상세 (처음 20개)")
        print("=" * 120)

        print(f"\n{'CSV':<5} {'Redis':<7} {'Timestamp':<20} {'Close':>10} {'Pine':>7} {'Python':>7}")
        print("-" * 70)

        for detail in mismatch_details:
            print(f"{detail['csv_idx']:<5} {detail['redis_idx']:<7} "
                  f"{str(detail['timestamp'])[:19]:<20} {detail['close']:>10.2f} "
                  f"{detail['pine']:>7} {detail['python']:>7}")

    # 불일치 패턴 분석
    if mismatch_details:
        print("\n" + "=" * 120)
        print("불일치 패턴 분석")
        print("=" * 120)

        pattern_counts = {}
        for detail in mismatch_details:
            pattern = f"Pine={detail['pine']}, Python={detail['python']}"
            pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1

        print("\n패턴별 빈도:")
        for pattern, count in sorted(pattern_counts.items(), key=lambda x: -x[1]):
            print(f"  {pattern}: {count}회")

    # 6. 처음 150개 캔들 상세 비교
    print("\n" + "=" * 120)
    print("처음 150개 캔들 상세 비교")
    print("=" * 120)

    print(f"\n{'CSV':<5} {'Redis':<7} {'Timestamp':<20} {'Close':>10} {'Pine':>7} {'Python':>7} {'Match':<6}")
    print("-" * 70)

    for csv_idx in range(min(150, len(pine_df))):
        redis_idx = csv_start_idx + csv_idx

        if redis_idx >= len(all_candles):
            break

        row = pine_df.iloc[csv_idx]
        pine_bb_state = int(row['BB_State'])
        python_bb_state = bb_state_results[redis_idx]

        match = "✅" if pine_bb_state == python_bb_state else "❌"

        print(f"{csv_idx:<5} {redis_idx:<7} "
              f"{str(all_candles[redis_idx]['timestamp'])[:19]:<20} "
              f"{all_candles[redis_idx]['close']:>10.2f} "
              f"{pine_bb_state:>7} {python_bb_state:>7} {match:<6}")


if __name__ == "__main__":
    main()
