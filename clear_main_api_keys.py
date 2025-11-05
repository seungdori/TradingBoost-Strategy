#!/usr/bin/env python3
"""메인 계정의 잘못된 API 키 삭제"""

import asyncio
from shared.database.redis_helper import get_redis_client

async def clear_main_api_keys():
    """메인 계정의 잘못된 API 키를 삭제"""

    redis = await get_redis_client()
    main_uid = "586156710277369942"

    print("=" * 60)
    print("🧹 메인 계정의 잘못된 API 키 삭제")
    print("=" * 60)
    print(f"메인 계정 UID: {main_uid}")
    print("-" * 60)

    # 현재 API 키 확인
    api_keys = await redis.hgetall(f"user:{main_uid}:api:keys")
    if api_keys:
        api_key = api_keys.get(b'api_key', b'').decode() if isinstance(api_keys.get(b'api_key', b''), bytes) else api_keys.get(b'api_key', '')
        print(f"\n현재 API Key: {api_key[:8]}...")
        print("이 API 키는 서브 계정의 것입니다!")

    # API 키 삭제
    deleted1 = await redis.delete(f"user:{main_uid}:api:keys")
    deleted2 = await redis.delete(f"user:{main_uid}:api_keys")

    print(f"\n✅ 삭제 완료:")
    print(f"  - api:keys 삭제: {deleted1}")
    print(f"  - api_keys 삭제: {deleted2}")

    # 확인
    check1 = await redis.hgetall(f"user:{main_uid}:api:keys")
    check2 = await redis.hgetall(f"user:{main_uid}:api_keys")

    print(f"\n확인:")
    print(f"  - api:keys: {'삭제됨' if not check1 else '여전히 존재'}")
    print(f"  - api_keys: {'삭제됨' if not check2 else '여전히 존재'}")

    print("\n" + "=" * 60)
    print("✅ 메인 계정의 API 키가 삭제되었습니다!")
    print("=" * 60)
    print("\n다음 단계:")
    print("1. 텔레그램 봇에서 /register 명령 실행")
    print("2. 메인 계정(586156710277369942)의 실제 API 키 입력:")
    print("   - 메인 계정 전용 API Key")
    print("   - 메인 계정 전용 Secret Key")
    print("   - 메인 계정 전용 Passphrase")
    print("\n⚠️  중요: 서브 계정의 API 키가 아닌, 메인 계정의 실제 API 키를 사용하세요!")

if __name__ == "__main__":
    asyncio.run(clear_main_api_keys())