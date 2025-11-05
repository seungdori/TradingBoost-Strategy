#!/usr/bin/env python3
"""서브 계정의 모든 설정을 메인 계정으로 복사"""

import asyncio
from shared.database.redis_helper import get_redis_client
import json

async def copy_all_settings():
    """서브 계정의 모든 설정을 메인 계정으로 복사"""

    redis = await get_redis_client()

    main_uid = "586156710277369942"  # 메인
    sub_uid = "587662504768345929"   # 서브

    print("=" * 60)
    print("📋 설정 복사 시작")
    print("=" * 60)
    print(f"From: {sub_uid} (서브)")
    print(f"To:   {main_uid} (메인)")
    print("-" * 60)

    # 복사할 키 패턴들
    key_patterns = [
        "preferences",
        "params",
        "settings",
        "dual_side",
        "api:keys",
        "api_keys",
        "trading:status",
        "entry_trade",
        "position:*",
        "stats",
    ]

    copied_count = 0

    for pattern in key_patterns:
        try:
            # 1. Hash 타입 시도
            sub_key = f"user:{sub_uid}:{pattern}"
            data = await redis.hgetall(sub_key)

            if data:
                main_key = f"user:{main_uid}:{pattern}"
                # 기존 데이터 삭제
                await redis.delete(main_key)
                # 새 데이터 복사
                for field, value in data.items():
                    await redis.hset(main_key, field, value)
                print(f"✅ Hash 복사: {pattern} ({len(data)} fields)")
                copied_count += 1
                continue

            # 2. String 타입 시도
            data = await redis.get(sub_key)
            if data:
                main_key = f"user:{main_uid}:{pattern}"
                await redis.set(main_key, data)
                print(f"✅ String 복사: {pattern}")
                copied_count += 1

        except Exception as e:
            # 와일드카드 패턴 처리
            if "*" in pattern:
                cursor = 0
                sub_pattern = f"user:{sub_uid}:{pattern}"
                while True:
                    cursor, keys = await redis.scan(cursor, match=sub_pattern, count=100)
                    for key in keys:
                        key_str = key.decode() if isinstance(key, bytes) else key
                        # 새 키 이름 생성
                        new_key = key_str.replace(f"user:{sub_uid}:", f"user:{main_uid}:")

                        # 데이터 복사
                        data = await redis.get(key_str)
                        if data:
                            await redis.set(new_key, data)
                            print(f"✅ Pattern 복사: {key_str} → {new_key}")
                            copied_count += 1

                    if cursor == 0:
                        break

    # API 키 특별 처리 (중요!)
    print("\n" + "=" * 60)
    print("🔑 API 키 설정")
    print("-" * 60)

    # 서브 계정의 API 키 확인
    api_patterns = [
        f"user:{sub_uid}:api_keys",
        f"user:{sub_uid}:api:keys",
    ]

    api_found = False
    for pattern in api_patterns:
        api_data = await redis.hgetall(pattern)
        if api_data:
            # 메인 계정에 복사
            main_api_key = f"user:{main_uid}:api_keys"
            await redis.delete(main_api_key)
            for field, value in api_data.items():
                await redis.hset(main_api_key, field, value)

            # 추가로 api:keys에도 복사
            main_api_key2 = f"user:{main_uid}:api:keys"
            await redis.delete(main_api_key2)
            for field, value in api_data.items():
                await redis.hset(main_api_key2, field, value)

            print(f"✅ API 키 복사 완료")
            api_found = True
            break

    if not api_found:
        print("⚠️  서브 계정에 API 키가 없습니다. 수동 설정 필요!")

    # 기본 설정 보장
    print("\n" + "=" * 60)
    print("⚙️  기본 설정 확인")
    print("-" * 60)

    # preferences가 없으면 기본값 설정
    preferences = await redis.hgetall(f"user:{main_uid}:preferences")
    if not preferences:
        default_preferences = {
            "leverage": "50",
            "margin_mode": "cross",
            "order_amount": "5",
            "max_positions": "3",
            "take_profit": "2.0",
            "stop_loss": "1.5",
            "entry_option": "초과",
            "rsi_oversold": "30",
            "rsi_overbought": "70"
        }
        for k, v in default_preferences.items():
            await redis.hset(f"user:{main_uid}:preferences", k, v)
        print("✅ 기본 preferences 설정 완료")
    else:
        print(f"✅ preferences 존재 ({len(preferences)} 항목)")

    # 활성 트레이더 확인 및 설정
    await redis.sadd("active_traders", main_uid)
    await redis.set(f"user:{main_uid}:trading:status", "running")
    print("✅ 활성 트레이더 설정 완료")

    # 최종 확인
    print("\n" + "=" * 60)
    print("📊 최종 상태")
    print("-" * 60)

    # 메인 계정 상태 확인
    main_prefs = await redis.hgetall(f"user:{main_uid}:preferences")
    main_api = await redis.hgetall(f"user:{main_uid}:api_keys")
    main_status = await redis.get(f"user:{main_uid}:trading:status")

    print(f"메인 계정 ({main_uid}):")
    print(f"  - Preferences: {len(main_prefs)} 항목")
    print(f"  - API Keys: {'✅ 있음' if main_api else '❌ 없음'}")
    print(f"  - Trading Status: {main_status.decode() if main_status else 'None'}")

    active_traders = await redis.smembers("active_traders")
    print(f"\n활성 트레이더:")
    for trader in active_traders:
        trader_str = trader.decode() if isinstance(trader, bytes) else trader
        print(f"  - {trader_str}")

    print("\n" + "=" * 60)
    print("✅ 설정 복사 완료!")
    print("=" * 60)
    print("\n⚠️  Celery 워커를 다시 재시작하세요:")
    print("   cd HYPERRSI")
    print("   ./stop_celery_worker.sh")
    print("   ./start_celery_worker.sh")

if __name__ == "__main__":
    asyncio.run(copy_all_settings())