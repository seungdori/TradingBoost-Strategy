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
    # 심볼별 상태 키 패턴 사용
    async with get_redis_context(user_id=user_id, timeout=RedisTimeout.FAST_OPERATION) as redis:
        key = f"user:{user_id}:symbol:{symbol}:status"
        result = await redis.get(key)
        if isinstance(result, bytes):
            result = result.decode('utf-8')
        return str(result) if result else ""

async def set_symbol_status(user_id: str, symbol: str, status: str) -> None:
    """
    사용자의 특정 심볼에 대한 트레이딩 상태를 설정합니다.
    """
    # 심볼별 상태 키 패턴 사용
    async with get_redis_context(user_id=user_id, timeout=RedisTimeout.NORMAL_OPERATION) as redis:
        key = f"user:{user_id}:symbol:{symbol}:status"
        await redis.set(key, status)


async def get_all_symbol_statuses(user_id: str) -> dict:
    """
    사용자의 모든 심볼에 대한 트레이딩 상태를 반환합니다.
    """
    # 심볼별 상태 키 패턴 사용
    async with get_redis_context(user_id=user_id, timeout=RedisTimeout.PIPELINE) as redis:
        pattern = f"user:{user_id}:symbol:*:status"
        # Use SCAN instead of KEYS to avoid blocking Redis
        keys = await scan_keys_pattern(pattern, redis=redis)
        result = {}
        for k in keys:
            key_str = k.decode('utf-8') if isinstance(k, bytes) else k
            # key 형식: user:{user_id}:symbol:{symbol}:status
            parts = key_str.split(':')
            symbol = parts[3] if len(parts) > 3 else 'unknown'
            status = await redis.get(k)
            if isinstance(status, bytes):
                status = status.decode('utf-8')
            result[symbol] = status
        return result


async def get_universal_status(user_id: str, symbol: str = "BTC-USDT-SWAP") -> str:
    """
    사용자의 특정 심볼에 대한 트레이딩 상태를 반환합니다.
    symbol이 지정되지 않으면 기본 심볼(BTC-USDT-SWAP) 상태를 반환합니다.
    """
    # 심볼별 상태 키 패턴 사용
    async with get_redis_context(user_id=user_id, timeout=RedisTimeout.FAST_OPERATION) as redis:
        key = f"user:{user_id}:symbol:{symbol}:status"
        result = await redis.get(key)
        if isinstance(result, bytes):
            result = result.decode('utf-8')
        return str(result) if result else ""

async def check_is_running(user_id: str, symbol: str = "BTC-USDT-SWAP") -> bool:
    """
    사용자의 특정 심볼에 대한 트레이딩 상태가 running인지 확인합니다.
    """
    status = await get_symbol_status(user_id, symbol)
    return status == "running"


async def check_any_symbol_running(user_id: str) -> bool:
    """
    사용자의 어떤 심볼이라도 running 상태인지 확인합니다.
    """
    statuses = await get_all_symbol_statuses(user_id)
    return any(status == "running" for status in statuses.values())
