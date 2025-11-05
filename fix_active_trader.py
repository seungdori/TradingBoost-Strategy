#!/usr/bin/env python3
"""활성 트레이더를 메인 계정으로 수정"""

import asyncio
from shared.database.redis_helper import get_redis_client

async def fix_active_trader():
    """활성 트레이더를 메인 계정으로 변경"""

    redis = await get_redis_client()

    main_uid = "586156710277369942"  # 메인
    sub_uid = "587662504768345929"   # 서브

    print("=" * 60)
    print("🔧 활성 트레이더 수정")
    print("=" * 60)

    # 현재 활성 트레이더 확인
    active_traders = await redis.smembers("active_traders")
    print("\n현재 활성 트레이더:")
    for trader in active_traders:
        trader_str = trader.decode() if isinstance(trader, bytes) else trader
        print(f"  - {trader_str}")

    # 서브 계정 제거, 메인 계정 추가
    await redis.srem("active_traders", sub_uid)
    await redis.sadd("active_traders", main_uid)

    # 트레이딩 상태 설정
    await redis.set(f"user:{main_uid}:trading:status", "running")
    await redis.set(f"user:{sub_uid}:trading:status", "stopped")

    # 변경 후 확인
    active_traders = await redis.smembers("active_traders")
    print("\n✅ 변경 후 활성 트레이더:")
    for trader in active_traders:
        trader_str = trader.decode() if isinstance(trader, bytes) else trader
        print(f"  - {trader_str}")

    print(f"\n✅ 메인 계정({main_uid})이 활성화되었습니다!")
    print("\n⚠️  중요: Celery 워커를 재시작하세요:")
    print("   cd HYPERRSI")
    print("   ./stop_celery_worker.sh")
    print("   ./start_celery_worker.sh")

if __name__ == "__main__":
    asyncio.run(fix_active_trader())