#!/usr/bin/env python3
"""마진 관련 문제 종합 진단 스크립트"""

import asyncio
import sys
import json
from datetime import datetime
from shared.database.redis_helper import get_redis_client
from shared.config import get_settings
from HYPERRSI.src.api.dependencies import get_user_api_keys
from HYPERRSI.src.trading.services.order_wrapper import OrderWrapper
from shared.utils import safe_float

async def diagnose_margin_issues(user_id: str = None, symbol: str = "ETH-USDT-SWAP"):
    """마진 관련 모든 문제를 종합적으로 진단합니다."""

    print("=" * 60)
    print("🔍 마진 문제 종합 진단 시작")
    print("=" * 60)

    redis = await get_redis_client()
    settings = get_settings()

    # 1. 사용자 ID 확인
    if not user_id:
        # Redis에서 모든 사용자 찾기
        pattern = "user:*:trading:status"
        cursor = 0
        users = set()

        while True:
            cursor, keys = await redis.scan(cursor, match=pattern, count=100)
            for key in keys:
                key_str = key.decode() if isinstance(key, bytes) else key
                # user:ID:trading:status 형태에서 ID 추출
                parts = key_str.split(":")
                if len(parts) >= 2:
                    users.add(parts[1])
            if cursor == 0:
                break

        if users:
            print(f"\n📋 발견된 사용자 ID: {list(users)}")
            if len(users) == 1:
                user_id = list(users)[0]
                print(f"✅ 단일 사용자 선택: {user_id}")
            else:
                user_id = input("진단할 사용자 ID를 입력하세요: ")
        else:
            print("⚠️  활성 사용자를 찾을 수 없습니다.")
            user_id = input("사용자 ID를 직접 입력하세요: ")

    print(f"\n👤 사용자 ID: {user_id}")
    print(f"📊 심볼: {symbol}")

    # 2. margin_block 키 확인
    print("\n" + "=" * 60)
    print("🔒 Margin Block 상태 확인")
    print("-" * 60)

    block_key = f"margin_block:{user_id}:{symbol}"
    block_status = await redis.get(block_key)

    if block_status:
        ttl = await redis.ttl(block_key)
        print(f"❌ 차단 상태: 활성")
        print(f"   남은 시간: {ttl}초 ({ttl // 60}분 {ttl % 60}초)")
    else:
        print("✅ 차단 상태: 없음")

    # 3. margin_retry_count 확인
    retry_key = f"margin_retry_count:{user_id}:{symbol}"
    retry_count = await redis.get(retry_key)

    print(f"\n🔄 재시도 횟수: {int(retry_count) if retry_count else 0}/15")
    if retry_count:
        ttl = await redis.ttl(retry_key)
        print(f"   TTL: {ttl}초 ({ttl // 3600}시간)")

    # 4. 실제 계좌 잔고 확인
    print("\n" + "=" * 60)
    print("💰 실제 계좌 잔고 확인")
    print("-" * 60)

    try:
        api_keys = await get_user_api_keys(user_id)
        exchange = OrderWrapper(str(user_id), api_keys)

        # 잔고 조회
        balance = await exchange.fetch_balance()
        usdt_balance = balance.get('USDT', {})

        total_usdt = safe_float(usdt_balance.get('total', 0))
        free_usdt = safe_float(usdt_balance.get('free', 0))
        used_usdt = safe_float(usdt_balance.get('used', 0))

        print(f"💵 총 USDT: {total_usdt:,.2f}")
        print(f"✅ 사용 가능: {free_usdt:,.2f}")
        print(f"🔒 사용 중: {used_usdt:,.2f}")

        # 현재 포지션 확인
        positions = await exchange.fetch_positions([symbol])
        if positions:
            print(f"\n📈 현재 포지션:")
            for pos in positions:
                if pos.get('contracts', 0) > 0:
                    print(f"   {pos.get('symbol')}: {pos.get('contracts')} 계약")
                    print(f"   진입가: ${pos.get('markPrice', 0):,.2f}")
                    print(f"   미실현 손익: ${pos.get('unrealizedPnl', 0):,.2f}")

        await exchange.close()

    except Exception as e:
        print(f"❌ 계좌 정보 조회 실패: {str(e)}")

    # 5. 트레이딩 상태 확인
    print("\n" + "=" * 60)
    print("⚙️  트레이딩 상태 확인")
    print("-" * 60)

    trading_status = await redis.get(f"user:{user_id}:trading:status")
    if isinstance(trading_status, bytes):
        trading_status = trading_status.decode('utf-8')

    print(f"상태: {trading_status or '없음'}")

    # 6. 최근 에러 로그 확인
    print("\n" + "=" * 60)
    print("📝 최근 주문 에러 로그")
    print("-" * 60)

    # Redis에서 최근 로그 패턴 찾기
    error_pattern = f"error_log:{user_id}:*"
    cursor = 0
    error_keys = []

    while True:
        cursor, keys = await redis.scan(cursor, match=error_pattern, count=10)
        error_keys.extend([k.decode() if isinstance(k, bytes) else k for k in keys])
        if cursor == 0:
            break

    if error_keys:
        print(f"발견된 에러 로그: {len(error_keys)}개")
        # 최근 5개만 표시
        for key in error_keys[:5]:
            value = await redis.get(key)
            if value:
                print(f"  - {key}: {value.decode() if isinstance(value, bytes) else value}")
    else:
        print("최근 에러 로그 없음")

    # 7. 해결 방법 제안
    print("\n" + "=" * 60)
    print("💡 해결 방법")
    print("=" * 60)

    if block_status or (retry_count and int(retry_count) >= 15):
        print("\n🔧 차단 해제 방법:")
        print("1. 자동 해제 (10분 대기)")
        print("2. 수동 해제 명령어:")
        print(f"   python check_margin_block.py --clear")
        print("\n3. 특정 키만 삭제:")
        print(f"   redis-cli DEL margin_block:{user_id}:{symbol}")
        print(f"   redis-cli DEL margin_retry_count:{user_id}:{symbol}")

    if retry_count and int(retry_count) > 0:
        print("\n⚠️  재시도 카운트 초기화 권장")
        print("재시도 카운트가 누적되어 있으면 정상적인 주문도 차단될 수 있습니다.")

        if input("\n재시도 카운트를 초기화하시겠습니까? (y/n): ").lower() == 'y':
            await redis.delete(retry_key)
            print("✅ 재시도 카운트가 초기화되었습니다.")

            if block_status:
                if input("차단 상태도 해제하시겠습니까? (y/n): ").lower() == 'y':
                    await redis.delete(block_key)
                    print("✅ 차단 상태가 해제되었습니다.")

    print("\n" + "=" * 60)
    print("✅ 진단 완료")
    print("=" * 60)

if __name__ == "__main__":
    user_id = sys.argv[1] if len(sys.argv) > 1 else None
    symbol = sys.argv[2] if len(sys.argv) > 2 else "ETH-USDT-SWAP"

    asyncio.run(diagnose_margin_issues(user_id, symbol))