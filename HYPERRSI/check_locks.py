import asyncio
import redis.asyncio as redis
from HYPERRSI.src.core.config import settings

async def check_lock():
    client = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB, 
                         password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None)
    pattern = 'lock:user:1709556958:*'
    cursor, keys = await client.scan(cursor=0, match=pattern)
    print(f'현재 락 키 목록: {keys}')
    
    # 트레이딩 상태도 확인
    trading_status_key = 'user:1709556958:trading:status'
    status = await client.get(trading_status_key)
    print(f'현재 트레이딩 상태: {status}')
    
    # 태스크 실행 상태 확인
    task_running_key = 'user:1709556958:task_running'
    task_status = await client.hgetall(task_running_key)
    print(f'태스크 실행 상태: {task_status}')
    
    await client.close()

if __name__ == "__main__":
    asyncio.run(check_lock()) 