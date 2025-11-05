#!/usr/bin/env python3
"""Redis margin_block 키 확인 스크립트"""

import asyncio
import sys
from shared.database.redis_helper import get_redis_client

async def check_margin_blocks():
    """모든 margin_block 키와 관련 정보를 확인합니다."""
    redis = await get_redis_client()

    # 모든 margin_block 키 찾기
    pattern = "margin_block:*"
    cursor = 0
    found_keys = []

    print(f"\n🔍 Redis에서 '{pattern}' 패턴의 키를 검색합니다...\n")

    while True:
        cursor, keys = await redis.scan(cursor, match=pattern, count=100)
        found_keys.extend([k.decode() if isinstance(k, bytes) else k for k in keys])
        if cursor == 0:
            break

    if not found_keys:
        print("✅ margin_block 키가 없습니다. 차단된 심볼이 없습니다.\n")
        return

    print(f"⚠️  총 {len(found_keys)}개의 차단 키를 발견했습니다:\n")

    for key in found_keys:
        value = await redis.get(key)
        ttl = await redis.ttl(key)

        # 키 파싱: margin_block:{user_id}:{symbol}
        parts = key.split(":")
        user_id = parts[1] if len(parts) > 1 else "unknown"
        symbol = parts[2] if len(parts) > 2 else "unknown"

        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"🔒 키: {key}")
        print(f"   사용자 ID: {user_id}")
        print(f"   심볼: {symbol}")
        print(f"   값: {value.decode() if isinstance(value, bytes) else value}")
        print(f"   남은 시간: {ttl}초 ({ttl // 60}분 {ttl % 60}초)")

        # margin_retry_count도 확인
        retry_key = f"margin_retry_count:{user_id}:{symbol}"
        retry_count = await redis.get(retry_key)
        if retry_count:
            retry_count_int = int(retry_count)
            print(f"   재시도 횟수: {retry_count_int}/15")

    print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    # 사용자 입력으로 차단 해제 여부 확인
    if len(sys.argv) > 1 and sys.argv[1] == "--clear":
        print("🧹 모든 margin_block 키를 삭제합니다...")
        for key in found_keys:
            parts = key.split(":")
            user_id = parts[1] if len(parts) > 1 else ""
            symbol = parts[2] if len(parts) > 2 else ""

            await redis.delete(key)
            # retry_count도 함께 삭제
            retry_key = f"margin_retry_count:{user_id}:{symbol}"
            await redis.delete(retry_key)
            print(f"✅ 삭제됨: {key}")

        print(f"\n✅ 총 {len(found_keys)}개의 차단이 해제되었습니다.\n")
    else:
        print("💡 차단을 해제하려면 다음 명령어를 실행하세요:")
        print(f"   python {sys.argv[0]} --clear\n")

if __name__ == "__main__":
    asyncio.run(check_margin_blocks())
