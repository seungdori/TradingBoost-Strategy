#!/usr/bin/env python3
"""모든 계정의 API 키 상태 확인"""

import asyncio
from shared.database.redis_helper import get_redis_client
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def check_all_api_keys():
    """모든 계정의 API 키 상태 확인"""

    redis = await get_redis_client()

    main_uid = "586156710277369942"
    sub_uid = "587662504768345929"

    print("=" * 60)
    print("🔍 API 키 전체 상태 확인")
    print("=" * 60)

    # 1. Redis 확인
    print("\n📊 Redis API 키 상태:")
    print("-" * 40)

    for uid, name in [(main_uid, "메인"), (sub_uid, "서브")]:
        print(f"\n{name} 계정 ({uid}):")

        # api:keys 형식
        api_keys_1 = await redis.hgetall(f"user:{uid}:api:keys")
        if api_keys_1:
            print(f"  ✅ api:keys 존재 ({len(api_keys_1)} 필드)")
            for key, value in api_keys_1.items():
                key_str = key.decode() if isinstance(key, bytes) else key
                value_str = value.decode() if isinstance(value, bytes) else value
                if key_str in ['api_key']:
                    print(f"     - {key_str}: {value_str[:8]}...")
                elif key_str in ['api_secret', 'passphrase']:
                    print(f"     - {key_str}: ***")
        else:
            print(f"  ❌ api:keys 없음")

        # api_keys 형식
        api_keys_2 = await redis.hgetall(f"user:{uid}:api_keys")
        if api_keys_2:
            print(f"  ✅ api_keys 존재 ({len(api_keys_2)} 필드)")
        else:
            print(f"  ❌ api_keys 없음")

    # 2. TimescaleDB 확인
    print("\n📊 TimescaleDB API 키 상태:")
    print("-" * 40)

    try:
        # DB 연결
        db_url = os.getenv("DATABASE_URL", "postgresql://localhost/trading")
        conn = await asyncpg.connect(db_url)

        # 쿼리 실행
        query = """
        SELECT okx_uid, api_key, api_secret IS NOT NULL as has_secret,
               passphrase IS NOT NULL as has_passphrase,
               telegram_linked, telegram_id
        FROM app_users
        WHERE okx_uid IN ($1, $2)
        """

        rows = await conn.fetch(query, main_uid, sub_uid)

        for row in rows:
            name = "메인" if row['okx_uid'] == main_uid else "서브"
            print(f"\n{name} 계정 ({row['okx_uid']}):")
            if row['api_key']:
                print(f"  ✅ API Key: {row['api_key'][:8]}...")
            else:
                print(f"  ❌ API Key 없음")
            print(f"  Secret: {'✅' if row['has_secret'] else '❌'}")
            print(f"  Passphrase: {'✅' if row['has_passphrase'] else '❌'}")
            print(f"  Telegram 연결: {'✅' if row['telegram_linked'] else '❌'}")
            if row['telegram_id']:
                print(f"  Telegram ID: {row['telegram_id']}")

        await conn.close()
    except Exception as e:
        print(f"TimescaleDB 연결 실패: {e}")

    # 3. 활성 트레이더 확인
    print("\n📊 활성 트레이더:")
    print("-" * 40)
    active_traders = await redis.smembers("active_traders")
    for trader in active_traders:
        trader_str = trader.decode() if isinstance(trader, bytes) else trader
        name = "메인" if trader_str == main_uid else "서브" if trader_str == sub_uid else "기타"
        print(f"  - {trader_str} ({name})")

    print("\n" + "=" * 60)

if __name__ == "__main__":
    asyncio.run(check_all_api_keys())