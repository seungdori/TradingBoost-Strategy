#!/usr/bin/env python3
"""마진 차단 상태 초기화 스크립트"""

import asyncio
import sys
from shared.database.redis_helper import get_redis_client
from datetime import datetime

async def reset_margin_blocks(user_id: str = None, symbol: str = None):
    """마진 차단 상태와 재시도 카운트를 초기화합니다."""

    print("=" * 80)
    print("🔧 마진 차단 초기화 스크립트")
    print("=" * 80)

    redis = await get_redis_client()

    # 1. 사용자 ID 확인
    if not user_id:
        pattern = "margin_block:*"
        cursor = 0
        blocked_users = set()

        while True:
            cursor, keys = await redis.scan(cursor, match=pattern, count=100)
            for key in keys:
                key_str = key.decode() if isinstance(key, bytes) else key
                parts = key_str.split(":")
                if len(parts) >= 2:
                    blocked_users.add(parts[1])
            if cursor == 0:
                break

        if blocked_users:
            print(f"\n차단된 사용자 ID: {list(blocked_users)}")
            if len(blocked_users) == 1:
                user_id = list(blocked_users)[0]
                print(f"✅ 단일 사용자 선택: {user_id}")
            else:
                user_id = input("초기화할 사용자 ID를 입력하세요 (all=전체): ")
        else:
            print("차단된 사용자가 없습니다.")
            user_id = input("사용자 ID를 직접 입력하세요: ")

    print(f"\n👤 대상 사용자: {user_id}")

    # 2. 심볼 확인
    if not symbol:
        if user_id != "all":
            pattern = f"margin_block:{user_id}:*"
        else:
            pattern = "margin_block:*"

        cursor = 0
        blocked_symbols = set()

        while True:
            cursor, keys = await redis.scan(cursor, match=pattern, count=100)
            for key in keys:
                key_str = key.decode() if isinstance(key, bytes) else key
                parts = key_str.split(":")
                if len(parts) >= 3:
                    blocked_symbols.add(parts[2])
            if cursor == 0:
                break

        if blocked_symbols:
            print(f"차단된 심볼: {list(blocked_symbols)}")
            symbol = input("초기화할 심볼을 입력하세요 (all=전체, Enter=전체): ")
            if not symbol:
                symbol = "all"
        else:
            symbol = "all"

    print(f"📊 대상 심볼: {symbol}")

    # 3. 현재 상태 확인
    print("\n" + "=" * 80)
    print("📊 현재 차단 상태")
    print("-" * 80)

    if user_id == "all":
        pattern = "margin_block:*"
    elif symbol == "all":
        pattern = f"margin_block:{user_id}:*"
    else:
        pattern = f"margin_block:{user_id}:{symbol}"

    cursor = 0
    block_keys = []
    retry_keys = []

    while True:
        cursor, keys = await redis.scan(cursor, match=pattern, count=100)
        block_keys.extend([k.decode() if isinstance(k, bytes) else k for k in keys])
        if cursor == 0:
            break

    # retry_count 키도 찾기
    if user_id == "all":
        retry_pattern = "margin_retry_count:*"
    elif symbol == "all":
        retry_pattern = f"margin_retry_count:{user_id}:*"
    else:
        retry_pattern = f"margin_retry_count:{user_id}:{symbol}"

    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match=retry_pattern, count=100)
        retry_keys.extend([k.decode() if isinstance(k, bytes) else k for k in keys])
        if cursor == 0:
            break

    print(f"\n발견된 차단 키: {len(block_keys)}개")
    print(f"발견된 재시도 카운트 키: {len(retry_keys)}개")

    if block_keys:
        print("\n🔒 차단된 항목:")
        for key in block_keys[:10]:  # 처음 10개만 표시
            ttl = await redis.ttl(key)
            parts = key.split(":")
            user = parts[1] if len(parts) > 1 else "unknown"
            sym = parts[2] if len(parts) > 2 else "unknown"
            print(f"   {user} / {sym}: {ttl}초 남음")

    if retry_keys:
        print("\n🔄 재시도 카운트:")
        for key in retry_keys[:10]:  # 처음 10개만 표시
            count = await redis.get(key)
            count = int(count) if count else 0
            parts = key.split(":")
            user = parts[1] if len(parts) > 1 else "unknown"
            sym = parts[2] if len(parts) > 2 else "unknown"
            print(f"   {user} / {sym}: {count}/15회")

    # 4. 초기화 확인
    if not block_keys and not retry_keys:
        print("\n✅ 초기화할 항목이 없습니다.")
        return

    print("\n" + "=" * 80)
    print("⚠️  경고")
    print("-" * 80)
    print("초기화하면 다음이 수행됩니다:")
    print("1. 모든 margin_block 차단이 해제됩니다")
    print("2. 모든 재시도 카운트가 0으로 초기화됩니다")
    print("3. 즉시 거래 재시도가 가능해집니다")

    confirm = input("\n정말로 초기화하시겠습니까? (yes/no): ")
    if confirm.lower() != "yes":
        print("취소되었습니다.")
        return

    # 5. 초기화 실행
    print("\n" + "=" * 80)
    print("🔧 초기화 실행 중...")
    print("-" * 80)

    deleted_blocks = 0
    deleted_retries = 0

    # margin_block 키 삭제
    for key in block_keys:
        await redis.delete(key)
        deleted_blocks += 1
        print(f"✅ 차단 해제: {key}")

    # margin_retry_count 키 삭제
    for key in retry_keys:
        await redis.delete(key)
        deleted_retries += 1
        print(f"✅ 카운트 초기화: {key}")

    # 6. 결과 확인
    print("\n" + "=" * 80)
    print("✅ 초기화 완료")
    print("=" * 80)
    print(f"\n📊 결과:")
    print(f"   차단 해제: {deleted_blocks}개")
    print(f"   카운트 초기화: {deleted_retries}개")

    print("\n💡 다음 단계:")
    print("1. OKX 계좌에 충분한 USDT가 있는지 확인")
    print("2. Trading 계좌로 자금 이체 (필요시)")
    print("3. 트레이딩 봇 재시작:")
    print(f"   cd HYPERRSI && python main.py")

    # 7. 트레이딩 상태 확인
    if user_id != "all":
        trading_status = await redis.get(f"user:{user_id}:trading:status")
        if isinstance(trading_status, bytes):
            trading_status = trading_status.decode('utf-8')

        print(f"\n⚙️  현재 트레이딩 상태: {trading_status or '없음'}")
        if trading_status == "stopped":
            print("   ⚠️  트레이딩이 중지된 상태입니다. 재시작이 필요합니다.")

if __name__ == "__main__":
    user_id = sys.argv[1] if len(sys.argv) > 1 else None
    symbol = sys.argv[2] if len(sys.argv) > 2 else None

    asyncio.run(reset_margin_blocks(user_id, symbol))