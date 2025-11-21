#!/usr/bin/env python3
"""
수정된 _calc_bb_state 함수 테스트
"""

import pandas as pd
from datetime import datetime
from fixed_calc_bb_state import _calc_bb_state_fixed


def load_csv_data(csv_path):
    """CSV 데이터 로드"""
    df = pd.read_csv(csv_path)
    df['timestamp'] = pd.to_datetime(df['time'])
    df['timestamp_utc'] = df['timestamp'].dt.tz_convert('UTC')
    df['timestamp_unix'] = df['timestamp_utc'].astype('int64') // 10**9
    return df


def prepare_candles(df):
    """캔들 데이터 준비"""
    candles = []
    for _, row in df.iterrows():
        candles.append({
            "timestamp": pd.to_datetime(row["time"]),
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "volume": 0.0
        })
    return candles


def main():
    csv_path = "/Users/seunghyun/Downloads/OKX_BTCUSDT.P, 15_ba3e6.csv"

    print("🔍 수정된 _calc_bb_state 테스트 (전체 히스토리 계산)")
    print("="*80)

    # CSV 로드
    df_csv = load_csv_data(csv_path)

    # Redis에서 전체 데이터 로드 (warm-up 포함)
    import redis
    import json
    from shared.config import get_settings

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

    # Redis 캔들을 Python 계산용으로 변환
    from datetime import datetime
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

    print(f"✅ Redis 전체 {len(all_candles)}개 캔들 로드")

    # CSV 시작점 찾기
    csv_start_ts = df_csv.iloc[0]['timestamp_unix']
    redis_start_idx = None
    for i, candle in enumerate(redis_candles):
        if candle['timestamp'] >= csv_start_ts:
            redis_start_idx = i
            break

    print(f"📊 CSV 시작점 = Redis 인덱스 {redis_start_idx}")
    print(f"   Warm-up: {redis_start_idx}개 캔들")

    # 전체 데이터로 BB_State 계산
    print("\n⚙️  전체 히스토리로 BB_State 재계산 중...")
    bb_state_results = _calc_bb_state_fixed(all_candles, is_confirmed_only=False)

    print(f"✅ 계산 완료: {len(bb_state_results)}개")

    # CSV 범위만 비교
    bb_matches = 0
    mismatches = []

    for i in range(len(df_csv)):
        csv_bb = df_csv.iloc[i]['BB_State']
        redis_idx = redis_start_idx + i

        if redis_idx < len(bb_state_results):
            py_bb = bb_state_results[redis_idx]

            if csv_bb == py_bb:
                bb_matches += 1
            else:
                mismatches.append({
                    'csv_index': i,
                    'redis_index': redis_idx,
                    'time': df_csv.iloc[i]['time'],
                    'csv': csv_bb,
                    'python': py_bb
                })

    accuracy = (bb_matches / len(df_csv) * 100) if len(df_csv) > 0 else 0

    print(f"\n🎯 BB_State 정확도: {accuracy:.2f}% ({bb_matches}/{len(df_csv)})")

    if mismatches:
        print(f"⚠️  불일치: {len(mismatches)}개")
        print("\n처음 10개 불일치:")
        for m in mismatches[:10]:
            print(f"  [CSV:{m['csv_index']}, Redis:{m['redis_index']}] {m['time']}: CSV={m['csv']}, Python={m['python']}")
    else:
        print("🎉 100% 일치!")


if __name__ == "__main__":
    main()
