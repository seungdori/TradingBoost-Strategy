#!/usr/bin/env python3
"""계정 전환을 허용하도록 수정"""

import asyncio
from shared.database.redis_helper import get_redis_client

async def allow_account_switch():
    """텔레그램 사용자가 다른 OKX 계정으로 전환할 수 있도록 설정"""

    redis = await get_redis_client()

    # 텔레그램 ID (스크린샷에서 보이는 사용자)
    telegram_id = "1752607289"  # 또는 실제 telegram user ID

    print("=" * 60)
    print("🔄 계정 전환 허용 설정")
    print("=" * 60)

    # 기존 OKX UID 맵핑 삭제
    old_key = f"user:{telegram_id}:okx_uid"
    old_uid = await redis.get(old_key)

    if old_uid:
        print(f"기존 맵핑 발견:")
        print(f"  Telegram ID: {telegram_id}")
        print(f"  Old OKX UID: {old_uid.decode() if isinstance(old_uid, bytes) else old_uid}")

        # 맵핑 삭제
        await redis.delete(old_key)
        print("✅ 기존 맵핑 삭제 완료")
    else:
        print("기존 맵핑이 없습니다.")

    print("\n이제 텔레그램 봇에서:")
    print("1. /reset 명령 실행")
    print("2. /start 명령 실행")
    print("3. 메인 계정 UID(586156710277369942) 입력")
    print("4. /register 명령으로 메인 계정 API 키 등록")

    print("\n" + "=" * 60)

if __name__ == "__main__":
    asyncio.run(allow_account_switch())