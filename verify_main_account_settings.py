#!/usr/bin/env python3
"""메인 계정 설정 확인 및 기본값 설정"""

import asyncio
from shared.database.redis_helper import get_redis_client
import json

async def verify_and_setup_main_account():
    """메인 계정의 설정을 확인하고 필요한 기본값을 설정"""

    redis = await get_redis_client()

    main_uid = "586156710277369942"  # 메인 계정

    print("=" * 60)
    print("📊 메인 계정 설정 확인")
    print("=" * 60)
    print(f"UID: {main_uid}")
    print("-" * 60)

    # 1. preferences 확인 및 설정
    preferences = await redis.hgetall(f"user:{main_uid}:preferences")
    if not preferences:
        print("⚠️  preferences 없음 - 기본값 설정 중...")
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
        for key, value in preferences.items():
            print(f"   - {key}: {value.decode() if isinstance(value, bytes) else value}")

    # 2. params 확인 및 설정
    params = await redis.hgetall(f"user:{main_uid}:params")
    if not params:
        print("\n⚠️  params 없음 - 기본값 설정 중...")
        default_params = {
            "rsi_period": "14",
            "rsi_overbought": "70",
            "rsi_oversold": "30",
            "volume_threshold": "1000000",
            "trend_ema_period": "50",
            "entry_cooldown": "60",
            "max_positions": "3"
        }
        for k, v in default_params.items():
            await redis.hset(f"user:{main_uid}:params", k, v)
        print("✅ 기본 params 설정 완료")
    else:
        print(f"\n✅ params 존재 ({len(params)} 항목)")

    # 3. dual_side 설정 확인
    dual_side = await redis.hgetall(f"user:{main_uid}:dual_side")
    if not dual_side:
        print("\n⚠️  dual_side 없음 - 기본값 설정 중...")
        default_dual = {
            "enabled": "false",
            "long_enabled": "true",
            "short_enabled": "true"
        }
        for k, v in default_dual.items():
            await redis.hset(f"user:{main_uid}:dual_side", k, v)
        print("✅ 기본 dual_side 설정 완료")
    else:
        print(f"\n✅ dual_side 존재 ({len(dual_side)} 항목)")

    # 4. API 키 확인 (설정하지 않음, 사용자가 직접 설정해야 함)
    api_keys = await redis.hgetall(f"user:{main_uid}:api_keys")
    if not api_keys:
        print("\n⚠️  API 키 없음")
        print("   텔레그램 봇에서 /register 명령으로 API 키를 설정하세요")
    else:
        print(f"\n✅ API 키 설정됨")

    # 5. trading:status 설정
    await redis.set(f"user:{main_uid}:trading:status", "running")
    print("\n✅ trading:status = running 설정 완료")

    # 6. active_traders 확인
    await redis.sadd("active_traders", main_uid)
    active_traders = await redis.smembers("active_traders")
    print(f"\n활성 트레이더:")
    for trader in active_traders:
        trader_str = trader.decode() if isinstance(trader, bytes) else trader
        print(f"  - {trader_str}")

    print("\n" + "=" * 60)
    print("✅ 메인 계정 설정 확인 완료!")
    print("=" * 60)

    # API 키가 없는 경우 안내
    if not api_keys:
        print("\n⚠️  다음 단계:")
        print("1. 텔레그램 봇에서 /register 명령으로 API 키 설정")
        print("2. Celery 워커 재시작:")
        print("   cd HYPERRSI")
        print("   ./stop_celery_worker.sh")
        print("   ./start_celery_worker.sh")
    else:
        print("\n⚠️  Celery 워커를 재시작하세요:")
        print("   cd HYPERRSI")
        print("   ./stop_celery_worker.sh")
        print("   ./start_celery_worker.sh")

if __name__ == "__main__":
    asyncio.run(verify_and_setup_main_account())