#!/usr/bin/env python3
"""기존 설정을 메인 계정으로 변경"""

import asyncio
from shared.database.redis_helper import get_redis_client

async def change_to_main():
    """서브에서 메인으로 변경"""

    redis = await get_redis_client()

    main_uid = "586156710277369942"  # 메인
    sub_uid = "587662504768345929"   # 서브
    telegram_id = "1709556958"

    print("=" * 60)
    print("텔레그램 ID 매핑 변경")
    print("=" * 60)
    print(f"\n변경 전: {telegram_id} → {sub_uid} (서브)")
    print(f"변경 후: {telegram_id} → {main_uid} (메인)")

    # Redis에서 변경
    await redis.set(f"telegram:{telegram_id}:okx_uid", main_uid)
    await redis.set(f"user:{main_uid}:telegram_id", telegram_id)

    # 활성 트레이더 변경
    await redis.srem("active_traders", sub_uid)
    await redis.sadd("active_traders", main_uid)

    # 트레이딩 상태 설정
    await redis.set(f"user:{main_uid}:trading:status", "running")

    print("\n✅ 완료!")
    print(f"\n이제 봇이 메인 계정({main_uid})을 사용합니다.")

if __name__ == "__main__":
    asyncio.run(change_to_main())