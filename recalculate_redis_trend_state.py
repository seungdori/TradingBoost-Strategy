#!/usr/bin/env python3
"""
Redis candles_with_indicators 데이터 재계산 스크립트

수정된 compute_trend_state 함수를 사용하여 Redis의 캔들 데이터를 재계산하고 업데이트합니다.
"""

import asyncio
import json
import redis
from datetime import datetime
from typing import List, Dict

from shared.indicators._trend import compute_trend_state
from shared.config import get_settings


settings = get_settings()


def get_redis_client():
    """Redis 클라이언트 생성"""
    return redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=0,
        decode_responses=True
    )


def load_candles_from_redis(redis_client, key: str) -> List[Dict]:
    """Redis에서 캔들 데이터 로드 (List 타입)"""
    try:
        # Redis List 타입이므로 lrange 사용
        data_list = redis_client.lrange(key, 0, -1)
        if not data_list:
            print(f"❌ Redis 키 없음: {key}")
            return []

        # 각 요소를 JSON 파싱
        candles = [json.loads(item) for item in data_list]
        print(f"✅ Redis 데이터 로드: {len(candles)}개 캔들")
        return candles

    except Exception as e:
        print(f"❌ Redis 로드 실패: {e}")
        return []


def save_candles_to_redis(redis_client, key: str, candles: List[Dict]) -> bool:
    """Redis에 캔들 데이터 저장 (List 타입)"""
    try:
        # 백업 키 생성 (재계산 전 데이터 백업)
        backup_key = f"{key}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        existing_data = redis_client.lrange(key, 0, -1)
        if existing_data:
            # 백업 List 생성
            redis_client.delete(backup_key)
            for item in existing_data:
                redis_client.rpush(backup_key, item)
            # 백업 만료 시간 설정 (7일)
            redis_client.expire(backup_key, 7 * 24 * 3600)
            print(f"✅ 백업 생성: {backup_key}")

        # 새 데이터 저장 (기존 List 삭제 후 새로 생성)
        redis_client.delete(key)
        json_strings = [json.dumps(candle) for candle in candles]
        if json_strings:
            redis_client.rpush(key, *json_strings)
        print(f"✅ Redis 저장 완료: {len(candles)}개 캔들")
        return True

    except Exception as e:
        print(f"❌ Redis 저장 실패: {e}")
        return False


def prepare_candles_for_calculation(candles: List[Dict]) -> List[Dict]:
    """compute_trend_state에 필요한 형식으로 캔들 변환"""
    prepared = []
    for c in candles:
        # timestamp를 datetime 객체로 변환
        if isinstance(c.get("timestamp"), str):
            ts = datetime.fromisoformat(c["timestamp"].replace('Z', '+00:00'))
        elif isinstance(c.get("timestamp"), (int, float)):
            # Redis 데이터는 초 단위 timestamp 사용
            ts = datetime.fromtimestamp(c["timestamp"])
        else:
            ts = c.get("timestamp")

        prepared.append({
            "timestamp": ts,
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
            "volume": float(c.get("volume", 0))
        })
    return prepared


def merge_calculated_indicators(original_candles: List[Dict], calculated_candles: List[Dict]) -> List[Dict]:
    """
    계산된 지표를 원본 캔들에 병합

    원본 캔들의 모든 필드를 유지하고, BB_State와 trend_state만 업데이트
    """
    merged = []
    for i, orig in enumerate(original_candles):
        if i < len(calculated_candles):
            calc = calculated_candles[i]
            # 원본 캔들 복사
            merged_candle = orig.copy()

            # 계산된 지표 업데이트
            merged_candle["BB_State"] = calc.get("BB_State", 0)
            merged_candle["BB_State_MTF"] = calc.get("BB_State_MTF", 0)
            merged_candle["trend_state"] = calc.get("trend_state", 0)
            merged_candle["CYCLE_Bull"] = calc.get("CYCLE_Bull", False)
            merged_candle["CYCLE_Bear"] = calc.get("CYCLE_Bear", False)
            merged_candle["CYCLE_Bull_2nd"] = calc.get("CYCLE_Bull_2nd", False)
            merged_candle["CYCLE_Bear_2nd"] = calc.get("CYCLE_Bear_2nd", False)

            merged.append(merged_candle)
        else:
            merged.append(orig)

    return merged


def compare_before_after(original_candles: List[Dict], updated_candles: List[Dict], num_samples=20):
    """재계산 전후 비교"""
    print("\n" + "="*80)
    print("📊 재계산 전후 비교 (최근 20개 캔들)")
    print("="*80)

    start_idx = max(0, len(original_candles) - num_samples)

    print(f"\n{'Index':<6} {'Timestamp':<20} {'Old BB':<8} {'New BB':<8} {'Old trend':<10} {'New trend':<10}")
    print("-" * 80)

    changes_bb = 0
    changes_trend = 0

    for i in range(start_idx, len(original_candles)):
        orig = original_candles[i]
        updated = updated_candles[i]

        old_bb = orig.get("BB_State", 0)
        new_bb = updated.get("BB_State", 0)
        old_trend = orig.get("trend_state", 0)
        new_trend = updated.get("trend_state", 0)

        if old_bb != new_bb:
            changes_bb += 1
        if old_trend != new_trend:
            changes_trend += 1

        # 변경된 경우 ★ 표시
        bb_marker = "★" if old_bb != new_bb else ""
        trend_marker = "★" if old_trend != new_trend else ""

        timestamp = orig.get("timestamp", "")
        if isinstance(timestamp, str):
            timestamp = timestamp[:19]  # YYYY-MM-DD HH:MM:SS

        print(f"{i:<6} {timestamp:<20} {old_bb:<8} {new_bb:<8}{bb_marker:<2} {old_trend:<10} {new_trend:<10}{trend_marker}")

    print("\n" + "="*80)
    print(f"📈 변경 통계:")
    print(f"  - BB_State 변경: {changes_bb}개")
    print(f"  - trend_state 변경: {changes_trend}개")
    print("="*80)


async def main():
    redis_key = "candles_with_indicators:BTC-USDT-SWAP:15m"

    print("🔄 Redis Trend State 재계산 시작")
    print("="*80)
    print(f"대상 키: {redis_key}")
    print("="*80)

    # 1. Redis 클라이언트 생성
    redis_client = get_redis_client()

    # 2. 기존 데이터 로드
    print("\n📥 Step 1: Redis 데이터 로드...")
    original_candles = load_candles_from_redis(redis_client, redis_key)

    if not original_candles:
        print("❌ 데이터가 없습니다. 종료합니다.")
        return

    print(f"✅ {len(original_candles)}개 캔들 로드 완료")

    # 3. 계산용 형식으로 변환
    print("\n🔧 Step 2: 캔들 데이터 변환...")
    prepared_candles = prepare_candles_for_calculation(original_candles)
    print(f"✅ {len(prepared_candles)}개 캔들 준비 완료")

    # 4. Trend State 재계산
    print("\n⚙️  Step 3: Trend State 재계산 중...")
    print("   - is_confirmed_only=False (백테스트 모드)")
    print("   - 15분 타임프레임")

    try:
        calculated_candles = compute_trend_state(
            prepared_candles,
            use_longer_trend=False,
            current_timeframe_minutes=15,
            is_confirmed_only=False  # 수정된 기본값 사용
        )
        print(f"✅ 재계산 완료: {len(calculated_candles)}개")
    except Exception as e:
        print(f"❌ 재계산 실패: {e}")
        import traceback
        traceback.print_exc()
        return

    # 5. 원본 데이터에 병합
    print("\n🔀 Step 4: 지표 병합...")
    updated_candles = merge_calculated_indicators(original_candles, calculated_candles)
    print(f"✅ 병합 완료: {len(updated_candles)}개")

    # 6. 재계산 전후 비교
    compare_before_after(original_candles, updated_candles)

    # 7. Redis에 저장
    print("\n💾 Step 5: Redis 저장...")
    success = save_candles_to_redis(redis_client, redis_key, updated_candles)

    if success:
        print("\n" + "="*80)
        print("✅ Redis Trend State 재계산 완료!")
        print("="*80)
        print(f"📍 키: {redis_key}")
        print(f"📊 총 캔들: {len(updated_candles)}개")
        print("\n💡 백업 키가 자동으로 생성되었습니다 (7일 보관).")
        print("   필요 시 백업 키로 복원 가능합니다.")
    else:
        print("\n❌ Redis 저장 실패. 재시도하거나 로그를 확인하세요.")


if __name__ == "__main__":
    asyncio.run(main())
