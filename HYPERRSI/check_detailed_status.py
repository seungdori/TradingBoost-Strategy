import asyncio
import redis.asyncio as redis
import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

async def check_detailed_status():
    # 환경 변수에서 Redis 호스트 가져오기
    redis_host = os.getenv('REDIS_HOST', 'localhost')
    client = redis.Redis(host=redis_host, port=6379, db=0, decode_responses=True)
    user_id = 1709556958
    symbol = "BTC-USDT-SWAP"
    sides = ["long", "short"]  # 포지션 방향 변경
    timeframe = "1m"
    
    # 모든 관련 키 확인
    keys_to_check = [
        f"user:{user_id}:trading:status",  # 트레이딩 상태
        f"user:{user_id}:task_running",  # 태스크 실행 상태
        f"user:{user_id}:task_id",  # 태스크 ID
        f"user:{user_id}:symbol:{symbol}:status",  # 심볼 상태
        f"user:{user_id}:last_execution",  # 마지막 실행 정보
        f"user:{user_id}:last_log_time"  # 마지막 로그 시간
    ]
    
    # 각 포지션 방향에 대한 락 키 추가
    for side in sides:
        keys_to_check.append(f"lock:user:{user_id}:{symbol}:{side}:{timeframe}")  # 락 키
    
    print("=== 사용자 상태 상세 정보 ===")
    for key in keys_to_check:
        # 키 타입 확인
        key_type = await client.type(key)
        print(f"\n키: {key}")
        print(f"타입: {key_type}")
        
        if key_type == 'none' or key_type == None:
            print("값: 없음")
        elif key_type == 'string':
            value = await client.get(key)
            print(f"값: {value}")
        elif key_type == 'hash':
            value = await client.hgetall(key)
            print(f"값: {value}")
        else:
            print(f"처리되지 않은 타입: {key_type}")
        
        # 만료 시간 확인
        ttl = await client.ttl(key)
        print(f"TTL: {ttl}초")
    
    # 모든 락 키 스캔
    print("\n=== 모든 락 키 ===")
    cursor = '0'
    lock_pattern = f"lock:user:{user_id}:*"
    while cursor != 0:
        cursor, keys = await client.scan(cursor=cursor, match=lock_pattern, count=100)
        for lock_key in keys:
            lock_value = await client.get(lock_key)
            lock_ttl = await client.ttl(lock_key)
            print(f"락 키: {lock_key}, 값: {lock_value}, TTL: {lock_ttl}초")
    
    await client.close()

if __name__ == "__main__":
    asyncio.run(check_detailed_status()) 