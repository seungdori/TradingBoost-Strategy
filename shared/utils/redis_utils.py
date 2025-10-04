"""Redis 유틸리티 함수

공통적으로 사용되는 Redis 관련 유틸리티 함수들
"""
import json
from typing import Any, Optional


async def set_redis_data(redis_client, key: str, data: Any, expiry: int = 144000) -> None:
    """
    Redis에 데이터를 저장합니다.
    
    Args:
        redis_client: Redis 클라이언트 인스턴스
        key: Redis 키
        data: 저장할 데이터 (JSON 직렬화 가능한 객체)
        expiry: 만료 시간 (초 단위, 기본값: 144000초 = 40시간)
    """
    await redis_client.set(key, json.dumps(data), ex=expiry)


async def get_redis_data(redis_client, key: str) -> Optional[Any]:
    """
    Redis에서 데이터를 가져옵니다.
    
    Args:
        redis_client: Redis 클라이언트 인스턴스
        key: Redis 키
        
    Returns:
        저장된 데이터 또는 None (데이터가 없는 경우)
    """
    data = await redis_client.get(key)
    return json.loads(data) if data else None


async def delete_redis_data(redis_client, key: str) -> bool:
    """
    Redis에서 데이터를 삭제합니다.
    
    Args:
        redis_client: Redis 클라이언트 인스턴스
        key: Redis 키
        
    Returns:
        삭제 성공 여부
    """
    result = await redis_client.delete(key)
    return result > 0


async def exists_redis_key(redis_client, key: str) -> bool:
    """
    Redis 키가 존재하는지 확인합니다.
    
    Args:
        redis_client: Redis 클라이언트 인스턴스
        key: Redis 키
        
    Returns:
        키 존재 여부
    """
    return await redis_client.exists(key) > 0
