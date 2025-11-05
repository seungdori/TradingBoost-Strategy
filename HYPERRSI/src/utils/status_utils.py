from shared.database.redis_helper import get_redis_client
from shared.database.redis_migration import get_redis_context
from shared.database.redis_patterns import RedisTimeout, scan_keys_pattern

# Module-level attribute for backward compatibility
def __getattr__(name):
    if name == "redis_client":
        return get_redis_client()
    raise AttributeError(f"module has no attribute {name}")

async def get_symbol_status(user_id: str, symbol: str) -> str:
    """
    사용자의 특정 심볼에 대한 트레이딩 상태를 반환합니다.
    """
    # MIGRATED: Using get_redis_context() with FAST_OPERATION for simple GET
    async with get_redis_context(user_id=user_id, timeout=RedisTimeout.FAST_OPERATION) as redis:
        key = f"user:{user_id}:trading:status"
        result = await redis.get(key)
        return str(result) if result else ""

async def set_symbol_status(user_id: str, symbol: str, status: str) -> None:
    """
    사용자의 특정 심볼에 대한 트레이딩 상태를 설정합니다.
    """
    # MIGRATED: Using get_redis_context() with NORMAL_OPERATION for simple SET
    async with get_redis_context(user_id=user_id, timeout=RedisTimeout.NORMAL_OPERATION) as redis:
        key = f"user:{user_id}:{symbol}:status"
        await redis.set(key, status)
    
    
async def get_all_symbol_statuses(user_id: str) -> dict:
    """
    사용자의 모든 심볼에 대한 트레이딩 상태를 반환합니다.
    """
    # MIGRATED: Using get_redis_context() with PIPELINE for SCAN operation
    async with get_redis_context(user_id=user_id, timeout=RedisTimeout.PIPELINE) as redis:
        key = f"user:{user_id}:*:status"
        # Use SCAN instead of KEYS to avoid blocking Redis
        keys = await scan_keys_pattern(key, redis=redis)
        return {k: await redis.get(k) for k in keys} if keys else {}


async def get_universal_status(user_id: str, symbol: str = "BTC-USDT-SWAP") -> str:
    """
    사용자의 기본 심볼에 대한 트레이딩 상태를 반환합니다.
    """
    # MIGRATED: Using get_redis_context() with FAST_OPERATION for simple GET
    async with get_redis_context(user_id=user_id, timeout=RedisTimeout.FAST_OPERATION) as redis:
        key = f"user:{user_id}:trading:status"
        result = await redis.get(key)
        return str(result) if result else ""

async def check_is_running(user_id: str, symbol: str = "BTC-USDT-SWAP") -> bool:
    """
    사용자의 특정 심볼에 대한 트레이딩 상태를 반환합니다.
    """
    status = await get_universal_status(user_id, symbol)
    return status == "running"