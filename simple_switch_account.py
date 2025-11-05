#!/usr/bin/env python3
"""간단한 메인 계정 전환 스크립트"""

import asyncio
from shared.database.redis_helper import get_redis_client

async def simple_switch_to_main():
    """간단하게 메인 계정으로 전환합니다."""

    print("=" * 80)
    print("🔄 간단한 메인 계정 전환")
    print("=" * 80)

    redis = await get_redis_client()

    main_uid = "586156710277369942"  # 메인 계정
    sub_uid = "587662504768345929"   # 서브 계정

    print(f"\n👤 서브 계정: {sub_uid}")
    print(f"👤 메인 계정: {main_uid}")
    print("-" * 80)

    # 1. 활성 트레이더 변경
    print("\n✅ 활성 트레이더를 메인 계정으로 변경...")
    await redis.srem("active_traders", sub_uid)
    await redis.sadd("active_traders", main_uid)

    # 2. 트레이딩 상태 설정
    print("✅ 메인 계정 트레이딩 상태 설정...")
    await redis.set(f"user:{main_uid}:trading:status", "running")

    # 3. 마진 차단 해제
    print("✅ 모든 마진 차단 해제...")

    # 모든 margin_block 키 삭제
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match="margin_block:*", count=100)
        if keys:
            await redis.delete(*keys)
            print(f"   삭제된 차단 키: {len(keys)}개")
        if cursor == 0:
            break

    # 모든 margin_retry_count 키 삭제
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match="margin_retry_count:*", count=100)
        if keys:
            await redis.delete(*keys)
            print(f"   삭제된 재시도 키: {len(keys)}개")
        if cursor == 0:
            break

    # 4. 결과 확인
    active_traders = await redis.smembers("active_traders")

    print("\n" + "=" * 80)
    print("✅ 전환 완료!")
    print("=" * 80)

    print("\n현재 활성 트레이더:")
    for trader in active_traders:
        trader_str = trader.decode() if isinstance(trader, bytes) else trader
        if trader_str == main_uid:
            print(f"   ✅ {trader_str} (메인 계정)")
        else:
            print(f"   - {trader_str}")

    print("\n💡 다음 단계:")
    print("\n1. 환경 변수 업데이트 (.env 파일):")
    print(f"   OWNER_ID={main_uid}")

    print("\n2. OKX에서 자금 확인:")
    print(f"   메인 계정({main_uid})의 Trading 계좌에 USDT가 있는지 확인")
    print(f"   없다면 Funding → Trading 이체")

    print("\n3. 봇 재시작:")
    print("   cd HYPERRSI")
    print("   python main.py")

if __name__ == "__main__":
    asyncio.run(simple_switch_to_main())