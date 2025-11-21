#!/usr/bin/env python3
"""
Redis 재계산 결과 정확도 검증 스크립트

TradingView CSV 데이터와 Redis 재계산 결과를 비교하여 정확도를 확인합니다.
"""

import json
import pandas as pd
import redis
from datetime import datetime, timezone
from shared.config import get_settings


settings = get_settings()


def load_csv_data(csv_path):
    """TradingView CSV 데이터 로드"""
    try:
        df = pd.read_csv(csv_path)
        print(f"✅ CSV 로드 성공: {len(df)} 행")

        # 시간대를 UTC로 변환
        df['timestamp'] = pd.to_datetime(df['time'])
        df['timestamp_utc'] = df['timestamp'].dt.tz_convert('UTC')
        df['timestamp_unix'] = df['timestamp_utc'].astype('int64') // 10**9

        print(f"🕐 CSV 기간: {df['timestamp_utc'].iloc[0]} ~ {df['timestamp_utc'].iloc[-1]}")
        return df
    except Exception as e:
        print(f"❌ CSV 로드 실패: {e}")
        return None


def load_redis_data(redis_key):
    """Redis에서 재계산된 데이터 로드"""
    try:
        r = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=0,
            decode_responses=True
        )

        data_list = r.lrange(redis_key, 0, -1)
        candles = [json.loads(item) for item in data_list]

        print(f"✅ Redis 로드 성공: {len(candles)} 캔들")

        # DataFrame으로 변환
        df = pd.DataFrame(candles)
        df['timestamp_dt'] = pd.to_datetime(df['timestamp'], unit='s', utc=True)

        print(f"🕐 Redis 기간: {df['timestamp_dt'].iloc[0]} ~ {df['timestamp_dt'].iloc[-1]}")
        return df
    except Exception as e:
        print(f"❌ Redis 로드 실패: {e}")
        return None


def compare_data(csv_df, redis_df):
    """CSV와 Redis 데이터 비교"""
    print("\n" + "="*80)
    print("📊 정확도 비교 분석")
    print("="*80)

    # 타임스탬프 기준으로 병합
    merged = pd.merge(
        csv_df[['timestamp_unix', 'BB_State', 'trend_state']],
        redis_df[['timestamp', 'BB_State', 'trend_state']],
        left_on='timestamp_unix',
        right_on='timestamp',
        suffixes=('_csv', '_redis')
    )

    print(f"\n📏 비교 가능한 캔들: {len(merged)}개")

    # BB_State 비교
    bb_matches = (merged['BB_State_csv'] == merged['BB_State_redis']).sum()
    bb_accuracy = (bb_matches / len(merged) * 100) if len(merged) > 0 else 0

    print(f"\n🎯 BB_State 정확도: {bb_accuracy:.2f}% ({bb_matches}/{len(merged)})")

    # 불일치 샘플 표시
    bb_mismatches = merged[merged['BB_State_csv'] != merged['BB_State_redis']]
    if not bb_mismatches.empty:
        print(f"⚠️  BB_State 불일치: {len(bb_mismatches)}개")
        print("\n처음 5개 불일치:")
        for idx, row in bb_mismatches.head(5).iterrows():
            ts = datetime.fromtimestamp(row['timestamp_unix'], tz=timezone.utc)
            print(f"  {ts}: CSV={row['BB_State_csv']}, Redis={row['BB_State_redis']}")

    # trend_state 비교
    trend_matches = (merged['trend_state_csv'] == merged['trend_state_redis']).sum()
    trend_accuracy = (trend_matches / len(merged) * 100) if len(merged) > 0 else 0

    print(f"\n🎯 trend_state 정확도: {trend_accuracy:.2f}% ({trend_matches}/{len(merged)})")

    # 불일치 샘플 표시
    trend_mismatches = merged[merged['trend_state_csv'] != merged['trend_state_redis']]
    if not trend_mismatches.empty:
        print(f"⚠️  trend_state 불일치: {len(trend_mismatches)}개")
        print("\n처음 5개 불일치:")
        for idx, row in trend_mismatches.head(5).iterrows():
            ts = datetime.fromtimestamp(row['timestamp_unix'], tz=timezone.utc)
            print(f"  {ts}: CSV={row['trend_state_csv']}, Redis={row['trend_state_redis']}")

    # 최종 결과
    print("\n" + "="*80)
    print("📊 최종 검증 결과")
    print("="*80)

    if bb_accuracy >= 95 and trend_accuracy >= 95:
        print("✅ 검증 성공! Redis 재계산 결과가 TradingView와 95% 이상 일치합니다.")
        return True
    elif bb_accuracy >= 90 and trend_accuracy >= 90:
        print("⚠️  부분 성공: 90% 이상 일치하지만 일부 차이가 있습니다.")
        return False
    else:
        print("❌ 검증 실패: 일치도가 90% 미만입니다. 추가 디버깅 필요.")
        return False


def main():
    csv_path = "/Users/seunghyun/Downloads/OKX_BTCUSDT.P, 15_ba3e6.csv"
    redis_key = "candles_with_indicators:BTC-USDT-SWAP:15m"

    print("🔍 Redis 재계산 결과 정확도 검증")
    print("="*80)

    # 1. CSV 데이터 로드
    csv_df = load_csv_data(csv_path)
    if csv_df is None:
        return

    # 2. Redis 데이터 로드
    redis_df = load_redis_data(redis_key)
    if redis_df is None:
        return

    # 3. 비교 분석
    success = compare_data(csv_df, redis_df)

    if success:
        print("\n🎉 검증 완료! 모든 수정이 정상적으로 적용되었습니다.")
    else:
        print("\n⚠️  일부 차이가 발견되었습니다. 추가 디버깅이 필요할 수 있습니다.")


if __name__ == "__main__":
    main()
