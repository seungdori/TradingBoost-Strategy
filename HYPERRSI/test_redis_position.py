"""
Redis 포지션 조회 테스트 스크립트
실제 어떤 DB를 사용하고 있는지, 그리고 포지션이 조회되는지 확인
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 Python path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from shared.database.redis_patterns import redis_context, RedisTimeout
from shared.database.redis import get_redis
from shared.logging import get_logger

logger = get_logger(__name__)

async def test_redis_connection():
    """Redis 연결 및 DB 번호 확인"""

    # 테스트 데이터
    user_id = "586156710277369942"
    symbol = "BTC-USDT-SWAP"

    print("\n" + "="*60)
    print("Redis 연결 및 포지션 조회 테스트")
    print("="*60)

    try:
        # 방법 1: redis_context 사용
        print("\n[방법 1] redis_context 사용:")
        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            # 현재 DB 번호 확인
            conn_info = redis.connection_pool.connection_kwargs
            db_num = conn_info.get('db', 'unknown')
            print(f"  연결된 DB 번호: {db_num}")

            # 포지션 키 조회
            for side in ['long', 'short']:
                position_key = f"user:{user_id}:position:{symbol}:{side}"
                print(f"\n  조회 키: {position_key}")

                # EXISTS 확인
                exists = await asyncio.wait_for(
                    redis.exists(position_key),
                    timeout=RedisTimeout.FAST_OPERATION
                )
                print(f"  키 존재 여부: {bool(exists)}")

                # HGETALL 시도
                pos_data = await asyncio.wait_for(
                    redis.hgetall(position_key),
                    timeout=RedisTimeout.FAST_OPERATION
                )
                print(f"  데이터 조회 결과: {bool(pos_data)}")

                if pos_data:
                    print(f"  포지션 데이터:")
                    print(f"    - entry_price: {pos_data.get('entry_price')}")
                    print(f"    - size: {pos_data.get('size')}")
                    print(f"    - leverage: {pos_data.get('leverage')}")
                    print(f"    - dca_count: {pos_data.get('dca_count')}")

        # 방법 2: get_redis() 직접 사용
        print("\n[방법 2] get_redis() 직접 사용:")
        redis = await get_redis()
        try:
            conn_info = redis.connection_pool.connection_kwargs
            db_num = conn_info.get('db', 'unknown')
            print(f"  연결된 DB 번호: {db_num}")

            for side in ['long', 'short']:
                position_key = f"user:{user_id}:position:{symbol}:{side}"
                print(f"\n  조회 키: {position_key}")

                exists = await redis.exists(position_key)
                print(f"  키 존재 여부: {bool(exists)}")

                pos_data = await redis.hgetall(position_key)
                print(f"  데이터 조회 결과: {bool(pos_data)}")

                if pos_data:
                    print(f"  포지션 데이터:")
                    for key, value in list(pos_data.items())[:5]:
                        print(f"    - {key}: {value}")
        finally:
            await redis.aclose()

        print("\n" + "="*60)
        print("테스트 완료")
        print("="*60 + "\n")

    except Exception as e:
        logger.error(f"테스트 실패: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    asyncio.run(test_redis_connection())
