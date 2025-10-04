"""
Redis 모델 베이스 클래스
더 나은 Redis 데이터 관리를 위한 추상화
"""
import json
from typing import Dict, Any, Optional, Type, TypeVar
from redis.asyncio import Redis
from pydantic import BaseModel

T = TypeVar('T', bound='RedisModel')


class RedisModel(BaseModel):
    """
    Pydantic 기반 Redis 모델
    자동 직렬화/역직렬화 지원
    """
    
    @classmethod
    def _get_key(cls, identifier: str) -> str:
        """Redis 키 생성"""
        return f"{cls.__name__.lower()}:{identifier}"
    
    async def save(self, redis: Redis, identifier: str, expire: Optional[int] = None) -> None:
        """모델을 Redis에 저장"""
        key = self._get_key(identifier)
        data = self.model_dump_json()
        
        if expire:
            await redis.setex(key, expire, data)
        else:
            await redis.set(key, data)
    
    @classmethod
    async def get(cls: Type[T], redis: Redis, identifier: str) -> Optional[T]:
        """Redis에서 모델 조회"""
        key = cls._get_key(identifier)
        data = await redis.get(key)
        
        if not data:
            return None
            
        return cls.model_validate_json(data)
    
    async def delete(self, redis: Redis, identifier: str) -> None:
        """Redis에서 모델 삭제"""
        key = self._get_key(identifier)
        await redis.delete(key)


# 사용 예시
class UserSettings(RedisModel):
    use_sl: bool = False
    use_break_even: bool = True
    leverage: int = 10
    tp1_value: float = 2.0
    entry_multiplier: float = 1.5
    direction: str = "롱숏"


class Position(RedisModel):
    user_id: str
    symbol: str
    side: str
    entry_price: float
    contracts: float
    leverage: int
    is_hedge: bool = False
    

# 실제 사용
"""
# 저장
settings = UserSettings(use_sl=True, leverage=20)
await settings.save(redis_client, f"user:{user_id}")

# 조회
settings = await UserSettings.get(redis_client, f"user:{user_id}")
if settings:
    print(settings.use_sl)  # True (bool 타입)

# 수정
settings.leverage = 25
await settings.save(redis_client, f"user:{user_id}")
"""