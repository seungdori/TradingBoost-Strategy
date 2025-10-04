import asyncio
import redis.asyncio as redis
from HYPERRSI.src.core.config import settings

async def reset_all_status():
    client = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB,
                         password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None)
    user_id = 1709556958
    symbol = "BTC-USDT-SWAP"
    sides = ["long", "short"]  # 포지션 방향 변경
    timeframe = "1m"
    
    # 삭제할 키 목록
    keys_to_delete = [
        f"user:{user_id}:task_running",  # 태스크 실행 상태
        f"user:{user_id}:task_id"  # 태스크 ID
    ]
    
    # 각 포지션 방향에 대한 락 키 추가
    for side in sides:
        keys_to_delete.append(f"lock:user:{user_id}:{symbol}:{side}:{timeframe}")  # 락 키
    
    for key in keys_to_delete:
        deleted = await client.delete(key)
        print(f"키 삭제: {key} - {'성공' if deleted else '실패 (키가 없음)'}")
    
    # 모든 락 키 스캔 및 삭제
    print("\n=== 모든 락 키 삭제 ===")
    cursor = '0'
    lock_pattern = f"lock:user:{user_id}:*"
    while cursor != 0:
        cursor, keys = await client.scan(cursor=cursor, match=lock_pattern, count=100)
        for lock_key in keys:
            deleted = await client.delete(lock_key)
            print(f"락 키 삭제: {lock_key} - {'성공' if deleted else '실패'}")
    
    # 트레이딩 상태 유지 (running으로 유지)
    print("\n트레이딩 상태는 'running'으로 유지됩니다.")
    
    await client.close()

if __name__ == "__main__":
    asyncio.run(reset_all_status()) 