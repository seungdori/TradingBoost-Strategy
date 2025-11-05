#!/usr/bin/env python3
"""강제로 메인 계정으로 전환하는 스크립트"""

import asyncio
from shared.database.redis_helper import get_redis_client
import json

async def force_switch_to_main():
    """강제로 메인 계정으로 전환합니다."""

    print("=" * 80)
    print("🔄 강제 메인 계정 전환")
    print("=" * 80)

    redis = await get_redis_client()

    main_uid = "586156710277369942"  # 메인 계정
    sub_uid = "587662504768345929"   # 서브 계정
    telegram_id = "1709556958"

    print(f"\n메인 계정: {main_uid}")
    print(f"서브 계정: {sub_uid}")
    print(f"텔레그램 ID: {telegram_id}")
    print("-" * 80)

    # 1. 모든 서브 계정 관련 키 삭제
    print("\n1️⃣ 서브 계정 데이터 정리...")
    patterns_to_delete = [
        f"user:{sub_uid}:*",
        f"telegram:{telegram_id}:*",
        f"margin_block:*",
        f"margin_retry_count:*"
    ]

    for pattern in patterns_to_delete:
        cursor = 0
        deleted_count = 0
        while True:
            cursor, keys = await redis.scan(cursor, match=pattern, count=100)
            if keys:
                await redis.delete(*keys)
                deleted_count += len(keys)
            if cursor == 0:
                break
        if deleted_count > 0:
            print(f"   삭제됨: {pattern} ({deleted_count}개)")

    # 2. 메인 계정 설정
    print("\n2️⃣ 메인 계정 설정...")

    # 활성 트레이더 설정
    await redis.delete("active_traders")
    await redis.sadd("active_traders", main_uid)
    print(f"   ✅ 활성 트레이더: {main_uid}")

    # 텔레그램 매핑
    await redis.set(f"user:{main_uid}:telegram_id", telegram_id)
    await redis.set(f"telegram:{telegram_id}:okx_uid", main_uid)
    print(f"   ✅ 텔레그램 ID 연결됨")

    # 트레이딩 상태
    await redis.set(f"user:{main_uid}:trading:status", "running")
    print(f"   ✅ 트레이딩 상태: running")

    # 3. API 키 설정 (서브 계정과 동일한 키 사용)
    print("\n3️⃣ API 키 설정...")

    # 여기에 실제 API 키 정보를 입력하세요
    api_keys = {
        "api_key": "ee71a3a8-a89e-4e79-b53f-0077a6c0a506",  # 실제 API 키
        "api_secret": "YOUR_API_SECRET",  # 실제 API Secret
        "passphrase": "YOUR_PASSPHRASE"   # 실제 Passphrase
    }

    # API 키 저장
    for key, value in api_keys.items():
        await redis.hset(f"user:{main_uid}:api_keys", key, value)

    print(f"   ✅ API 키 설정됨")

    # 4. 기본 설정 추가
    print("\n4️⃣ 기본 트레이딩 설정...")

    # preferences 설정
    preferences = {
        "leverage": 50.0,
        "margin_mode": "cross",
        "order_amount": 5.0,
        "max_positions": 3,
        "take_profit": 2.0,
        "stop_loss": 1.5
    }
    await redis.set(f"user:{main_uid}:preferences", json.dumps(preferences))
    print(f"   ✅ Preferences 설정됨")

    # 5. 확인
    print("\n" + "=" * 80)
    print("✅ 전환 완료!")
    print("=" * 80)

    # 현재 상태 확인
    active_traders = await redis.smembers("active_traders")
    print("\n현재 활성 트레이더:")
    for trader in active_traders:
        trader_str = trader.decode() if isinstance(trader, bytes) else trader
        print(f"   ✅ {trader_str}")

    telegram_mapping = await redis.get(f"telegram:{telegram_id}:okx_uid")
    if telegram_mapping:
        print(f"\n텔레그램 ID {telegram_id} → {telegram_mapping.decode() if isinstance(telegram_mapping, bytes) else telegram_mapping}")

    print("\n" + "=" * 80)
    print("⚠️  중요: 다음 단계를 수행하세요")
    print("=" * 80)

    print("\n1. .env 파일 수정:")
    print(f"   OWNER_ID={main_uid}")
    print(f"   # API 키는 동일하게 유지")

    print("\n2. 봇 재시작:")
    print("   cd HYPERRSI")
    print("   ./stop_celery_worker.sh  # Celery 중지")
    print("   python main.py            # 봇 시작")
    print("   ./start_celery_worker.sh  # 새 터미널에서")

if __name__ == "__main__":
    asyncio.run(force_switch_to_main())