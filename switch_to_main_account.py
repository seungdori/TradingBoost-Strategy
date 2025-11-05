#!/usr/bin/env python3
"""메인 계정으로 전환하는 스크립트 (자동 실행)"""

import asyncio
from shared.database.redis_helper import get_redis_client

async def switch_to_main_account():
    """서브 계정에서 메인 계정으로 전환합니다."""

    print("=" * 80)
    print("🔄 메인 계정으로 전환")
    print("=" * 80)

    redis = await get_redis_client()

    main_uid = "586156710277369942"  # 메인 계정
    sub_uid = "587662504768345929"   # 서브 계정
    telegram_id = "1709556958"

    print(f"\n📱 텔레그램 ID: {telegram_id}")
    print(f"👤 메인 계정: {main_uid}")
    print(f"👤 서브 계정: {sub_uid}")
    print("-" * 80)

    # 1. API 키 정보 복사
    print("\n1️⃣ API 키 정보 확인 및 복사...")

    # 서브 계정의 API 키 가져오기
    api_keys_data = await redis.hgetall(f"user:{sub_uid}:api_keys")

    if api_keys_data:
        # 메인 계정으로 API 키 복사
        for key, value in api_keys_data.items():
            await redis.hset(f"user:{main_uid}:api_keys", key, value)
        print(f"   ✅ API 키가 메인 계정으로 복사되었습니다.")
    else:
        print(f"   ⚠️  서브 계정에 API 키가 없습니다.")

    # 2. 텔레그램 ID 매핑 설정
    print("\n2️⃣ 텔레그램 ID 매핑 설정...")

    # 메인 계정에 텔레그램 ID 연결
    await redis.set(f"user:{main_uid}:telegram_id", telegram_id)
    await redis.set(f"telegram:{telegram_id}:okx_uid", main_uid)

    # Redis에서 old mapping 제거 (선택적)
    # await redis.delete(f"user:{sub_uid}:telegram_id")

    print(f"   ✅ 텔레그램 ID가 메인 계정에 연결되었습니다.")

    # 3. 트레이딩 설정 복사
    print("\n3️⃣ 트레이딩 설정 복사...")

    # 서브 계정의 설정 가져오기
    settings_keys = [
        "preferences",
        "params",
        "dual_side",
        "trading:status"
    ]

    for key in settings_keys:
        data = await redis.get(f"user:{sub_uid}:{key}")
        if data:
            await redis.set(f"user:{main_uid}:{key}", data)
            print(f"   ✅ {key} 설정이 복사되었습니다.")

    # 4. 마진 차단 상태 확인 및 해제
    print("\n4️⃣ 마진 차단 상태 확인...")

    symbols = ['ETH-USDT-SWAP', 'BTC-USDT-SWAP']
    for symbol in symbols:
        # 서브 계정의 차단 확인
        sub_block_key = f"margin_block:{sub_uid}:{symbol}"
        sub_retry_key = f"margin_retry_count:{sub_uid}:{symbol}"

        if await redis.exists(sub_block_key):
            await redis.delete(sub_block_key)
            print(f"   ✅ {symbol} 차단 해제됨 (서브 계정)")

        if await redis.exists(sub_retry_key):
            await redis.delete(sub_retry_key)
            print(f"   ✅ {symbol} 재시도 카운트 초기화됨 (서브 계정)")

        # 메인 계정의 차단도 확인
        main_block_key = f"margin_block:{main_uid}:{symbol}"
        main_retry_key = f"margin_retry_count:{main_uid}:{symbol}"

        if await redis.exists(main_block_key):
            await redis.delete(main_block_key)
            print(f"   ✅ {symbol} 차단 해제됨 (메인 계정)")

        if await redis.exists(main_retry_key):
            await redis.delete(main_retry_key)
            print(f"   ✅ {symbol} 재시도 카운트 초기화됨 (메인 계정)")

    # 5. 활성 트레이더 목록 업데이트
    print("\n5️⃣ 활성 트레이더 목록 업데이트...")

    # 서브 계정을 활성 목록에서 제거
    await redis.srem("active_traders", sub_uid)

    # 메인 계정을 활성 목록에 추가
    await redis.sadd("active_traders", main_uid)

    print(f"   ✅ 활성 트레이더가 메인 계정으로 변경되었습니다.")

    # 6. 결과 확인
    print("\n" + "=" * 80)
    print("✅ 전환 완료!")
    print("=" * 80)

    print(f"\n📊 변경 사항:")
    print(f"   이전: 서브 계정 ({sub_uid})")
    print(f"   현재: 메인 계정 ({main_uid})")

    print(f"\n⚠️  중요 사항:")
    print(f"1. OKX에서 메인 계정의 자금 확인:")
    print(f"   - Main account ({main_uid})의 Trading 계좌에 USDT가 있는지 확인")
    print(f"   - 없다면 Funding → Trading 이체 필요")

    print(f"\n2. 봇 재시작:")
    print(f"   cd HYPERRSI")
    print(f"   python main.py")

    print(f"\n3. 환경 변수 확인:")
    print(f"   .env 파일에서 OWNER_ID={main_uid}로 변경")

    # 7. 현재 상태 표시
    print("\n" + "=" * 80)
    print("📋 현재 상태")
    print("-" * 80)

    # 메인 계정 정보 확인
    main_telegram = await redis.get(f"user:{main_uid}:telegram_id")
    main_api_keys = await redis.hgetall(f"user:{main_uid}:api_keys")
    main_status = await redis.get(f"user:{main_uid}:trading:status")

    print(f"\n메인 계정 ({main_uid}):")
    print(f"   텔레그램 ID: {main_telegram.decode() if main_telegram else 'None'}")
    print(f"   API 키: {'설정됨' if main_api_keys else '없음'}")
    print(f"   트레이딩 상태: {main_status.decode() if main_status else 'stopped'}")

    # 활성 트레이더 확인
    active_traders = await redis.smembers("active_traders")
    print(f"\n활성 트레이더:")
    for trader_bytes in active_traders:
        trader = trader_bytes.decode() if isinstance(trader_bytes, bytes) else trader_bytes
        print(f"   - {trader} {'(메인)' if trader == main_uid else ''}")

if __name__ == "__main__":
    asyncio.run(switch_to_main_account())