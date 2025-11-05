#!/usr/bin/env python3
"""메인 계정의 API 키를 강제로 Redis에 설정"""

import asyncio
from shared.database.redis_helper import get_redis_client
import os
from dotenv import load_dotenv

load_dotenv()

async def force_set_main_account_api_keys():
    """메인 계정의 API 키를 Redis에 강제 설정"""

    redis = await get_redis_client()
    main_uid = "586156710277369942"

    print("=" * 60)
    print("🔧 메인 계정 API 키 강제 설정")
    print("=" * 60)
    print(f"메인 계정 UID: {main_uid}")
    print("-" * 60)

    # 환경 변수에서 API 키 읽기
    api_key = os.getenv("OKX_API_KEY")
    api_secret = os.getenv("OKX_SECRET_KEY")
    passphrase = os.getenv("OKX_PASSPHRASE")

    if not all([api_key, api_secret, passphrase]):
        print("❌ 환경 변수에 API 키가 설정되지 않았습니다.")
        print("   .env 파일에서 OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE를 확인하세요.")
        return

    print("\n📝 환경 변수에서 API 키 읽기:")
    print(f"  - API Key: {api_key[:8]}...")
    print(f"  - Secret Key: ***")
    print(f"  - Passphrase: ***")

    # Redis에 API 키 저장 (두 형식 모두)
    api_keys_data = {
        "api_key": api_key,
        "api_secret": api_secret,
        "passphrase": passphrase
    }

    # 형식 1: api:keys
    key1 = f"user:{main_uid}:api:keys"
    await redis.delete(key1)  # 기존 키 삭제
    for field, value in api_keys_data.items():
        await redis.hset(key1, field, value)
    print(f"\n✅ {key1} 설정 완료")

    # 형식 2: api_keys (일부 코드에서 이 형식도 사용)
    key2 = f"user:{main_uid}:api_keys"
    await redis.delete(key2)  # 기존 키 삭제
    for field, value in api_keys_data.items():
        await redis.hset(key2, field, value)
    print(f"✅ {key2} 설정 완료")

    # 확인
    print("\n📋 설정 확인:")
    saved_keys1 = await redis.hgetall(key1)
    saved_keys2 = await redis.hgetall(key2)

    if saved_keys1:
        print(f"  - api:keys: {len(saved_keys1)} 필드 저장됨")
    if saved_keys2:
        print(f"  - api_keys: {len(saved_keys2)} 필드 저장됨")

    # 활성 트레이더 확인
    active_traders = await redis.smembers("active_traders")
    print(f"\n활성 트레이더:")
    for trader in active_traders:
        trader_str = trader.decode() if isinstance(trader, bytes) else trader
        print(f"  - {trader_str}")

    print("\n" + "=" * 60)
    print("✅ 메인 계정 API 키 설정 완료!")
    print("=" * 60)
    print("\n⚠️  다음 단계:")
    print("1. Celery 워커 재시작:")
    print("   cd HYPERRSI")
    print("   ./stop_celery_worker.sh")
    print("   ./start_celery_worker.sh")
    print("\n2. 텔레그램 봇에서 /balance 명령으로 확인")

if __name__ == "__main__":
    asyncio.run(force_set_main_account_api_keys())