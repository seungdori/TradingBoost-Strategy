#!/usr/bin/env python3
"""
원본 CSV 파일로 Python vs PineScript BB_State 정확도 테스트
"""

import pandas as pd
import redis
import json
from datetime import datetime
from shared.config import get_settings
from shared.indicators._trend import _calc_bb_state

def main():
    # CSV 파일 로드
    csv_path = "/Users/seunghyun/Downloads/OKX_BTCUSDT.P, 15_ba3e6.csv"
    df = pd.read_csv(csv_path)

    print("=" * 100)
    print(f"CSV 파일: {csv_path}")
    print(f"총 캔들 개수: {len(df)}")
    print("=" * 100)
    print()

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

    # Redis 시작 인덱스 (CSV는 Redis:1358부터 시작)
    csv_start_redis_idx = 1358

    # Redis에서 필요한 데이터 추출
    all_candles = []
    for c in redis_candles:
        all_candles.append({
            "timestamp": datetime.fromtimestamp(c["timestamp"]),
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
            "volume": float(c["volume"])
        })

    # Python BB_State 계산 (전체)
    print("Python BB_State 계산 중...")
    bb_state_list = _calc_bb_state(all_candles)
    print(f"✅ 계산 완료: {len(bb_state_list)}개")
    print()

    # CSV 범위만 추출 (Redis:1358~)
    csv_bb_states = bb_state_list[csv_start_redis_idx:]

    # CSV에서 Pine BB_State 추출
    pine_bb_states = df['BB_State'].tolist()

    # 비교
    min_len = min(len(csv_bb_states), len(pine_bb_states))
    matches = 0
    mismatches = []

    for i in range(min_len):
        python_state = csv_bb_states[i]
        pine_state = pine_bb_states[i]

        if python_state == pine_state:
            matches += 1
        else:
            redis_idx = csv_start_redis_idx + i
            mismatches.append({
                'csv_idx': i,
                'redis_idx': redis_idx,
                'timestamp': df.iloc[i]['time'],
                'close': df.iloc[i]['close'],
                'python': python_state,
                'pine': pine_state
            })

    accuracy = (matches / min_len * 100) if min_len > 0 else 0

    print("=" * 100)
    print("비교 결과")
    print("=" * 100)
    print()
    print(f"총 비교: {min_len}개")
    print(f"✅ 일치: {matches}개 ({accuracy:.2f}%)")
    print(f"❌ 불일치: {len(mismatches)}개 ({100 - accuracy:.2f}%)")
    print()

    if mismatches:
        print("=" * 100)
        print(f"불일치 상세 (처음 30개)")
        print("=" * 100)
        print()
        print(f"{'CSV Idx':<10} {'Redis Idx':<12} {'Timestamp':<25} {'Close':>10} {'Python':>8} {'Pine':>8}")
        print("-" * 100)

        for mm in mismatches[:30]:
            print(f"{mm['csv_idx']:<10} {mm['redis_idx']:<12} {mm['timestamp']:<25} {mm['close']:>10.2f} "
                  f"{mm['python']:>8} {mm['pine']:>8.0f}")

        if len(mismatches) > 30:
            print()
            print(f"... 그 외 {len(mismatches) - 30}개 불일치")

        print()
        print("=" * 100)
        print(f"불일치 상세 (마지막 30개)")
        print("=" * 100)
        print()
        print(f"{'CSV Idx':<10} {'Redis Idx':<12} {'Timestamp':<25} {'Close':>10} {'Python':>8} {'Pine':>8}")
        print("-" * 100)

        for mm in mismatches[-30:]:
            print(f"{mm['csv_idx']:<10} {mm['redis_idx']:<12} {mm['timestamp']:<25} {mm['close']:>10.2f} "
                  f"{mm['python']:>8} {mm['pine']:>8.0f}")
    else:
        print("🎉 100% 일치!")

    print()
    print("=" * 100)
    print("결론")
    print("=" * 100)
    print()

    if accuracy >= 99.9:
        print("✅ 거의 완벽한 일치! (99.9% 이상)")
    elif accuracy >= 95:
        print("✅ 매우 높은 정확도 (95% 이상)")
    elif accuracy >= 90:
        print("⚠️ 좋은 정확도지만 개선 필요 (90-95%)")
    elif accuracy >= 80:
        print("⚠️ 보통 정확도, 추가 검증 필요 (80-90%)")
    else:
        print("❌ 낮은 정확도, 근본적인 문제 존재 (<80%)")

    print()
    print(f"최종 정확도: {accuracy:.2f}%")


if __name__ == "__main__":
    main()
