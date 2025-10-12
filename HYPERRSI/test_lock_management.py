import asyncio
import time
from datetime import datetime

import redis.asyncio as redis

from HYPERRSI.src.core.config import settings


async def test_lock_management():
    """
    락 관리 메커니즘의 작동을 테스트하는 스크립트
    """
    client = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB, 
                         decode_responses=True, password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None)
    user_id = 1709556958
    symbol = "BTC-USDT-SWAP"
    
    # side 값을 "long"과 "short"으로 변경하여 테스트
    sides = ["long", "short"]
    timeframe = "1m"
    
    print("=== 락 관리 메커니즘 테스트 ===")
    
    # 각 포지션 방향에 대해 테스트 수행
    for side in sides:
        # 락 키 형식
        lock_key = f"lock:user:{user_id}:{symbol}:{side}:{timeframe}"
        
        print(f"\n=== {side.upper()} 포지션 락 테스트 ===")
        
        # 1. 현재 락 상태 확인
        current_lock = await client.get(lock_key)
        if current_lock:
            print(f"기존 락 발견: {lock_key} = {current_lock}")
            print("→ 락 삭제 중...")
            await client.delete(lock_key)
            print("→ 락 삭제 완료")
        else:
            print("기존 락 없음")
        
        # 2. 락 획득 테스트
        print("\n락 획득 테스트 시작...")
        lock_value = f"{datetime.now().timestamp()}:{id(asyncio.current_task())}"
        acquired = await client.set(lock_key, lock_value, nx=True, ex=30)
        
        if acquired:
            print(f"락 획득 성공: {lock_key} = {lock_value}")
            
            # 3. 획득한 락 정보 확인
            ttl = await client.ttl(lock_key)
            print(f"락 만료 시간: {ttl}초")
            
            # 4. 동일한 락 재획득 시도 (실패해야 함)
            second_value = f"{datetime.now().timestamp()}:{id(asyncio.current_task())}_second"
            second_acquired = await client.set(lock_key, second_value, nx=True, ex=30)
            
            if second_acquired:
                print("오류: 이미 획득한 락을 다시 획득할 수 있었습니다.")
            else:
                print("정상: 이미 획득한 락을 다시 획득할 수 없습니다.")
            
            # 5. 잠시 대기 후 락 해제
            print("\n5초 대기 후 락 해제...")
            await asyncio.sleep(5)
            
            # 락 해제 전 현재 값 확인
            current_value = await client.get(lock_key)
            if current_value == lock_value:
                await client.delete(lock_key)
                print(f"락 해제 완료: {lock_key}")
            else:
                print(f"오류: 락 값이 변경됨. 예상: {lock_value}, 실제: {current_value}")
        else:
            print(f"락 획득 실패: {lock_key}")
    
    # 6. 모든 락 키 스캔
    print("\n=== 모든 락 키 스캔 ===")
    cursor = '0'
    lock_pattern = f"lock:user:{user_id}:*"
    lock_count = 0
    
    while cursor != 0:
        cursor, keys = await client.scan(cursor=cursor, match=lock_pattern, count=100)
        for found_key in keys:
            lock_count += 1
            lock_value = await client.get(found_key)
            lock_ttl = await client.ttl(found_key)
            print(f"락 키: {found_key}, 값: {lock_value}, TTL: {lock_ttl}초")
    
    if lock_count == 0:
        print("발견된 락 없음")
    
    await client.close()
    print("\n테스트 완료")

if __name__ == "__main__":
    asyncio.run(test_lock_management()) 