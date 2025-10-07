# Dynamic redis_client access
def _get_redis_client():
    """Get redis_client dynamically to avoid import-time errors"""
    from HYPERRSI.src.core import database as db_module
    return db_module.redis_client

redis_client = _get_redis_client()

# Module-level attribute for backward compatibility
def __getattr__(name):
    if name == "redis_client":
        return _get_redis_client()
    raise AttributeError(f"module has no attribute {name}")

async def get_symbol_status(user_id: str, symbol: str) -> str:
    """
    사용자의 특정 심볼에 대한 트레이딩 상태를 반환합니다.
    """
    key = f"user:{user_id}:trading:status"
    return await redis_client.get(key)

async def set_symbol_status(user_id: str, symbol: str, status: str):
    """
    사용자의 특정 심볼에 대한 트레이딩 상태를 설정합니다.
    """
    key = f"user:{user_id}:{symbol}:status"
    await redis_client.set(key, status)
    
    
async def get_all_symbol_statuses(user_id: str) -> dict:
    """
    사용자의 모든 심볼에 대한 트레이딩 상태를 반환합니다.
    """
    key = f"user:{user_id}:*:status"
    return await redis_client.keys(key)


async def get_universal_status(user_id: str, symbol: str = "BTC-USDT-SWAP") -> str:
    """
    사용자의 기본 심볼에 대한 트레이딩 상태를 반환합니다.
    """
    key = f"user:{user_id}:trading:status"
    return await redis_client.get(key)

async def check_is_running(user_id: str, symbol: str = "BTC-USDT-SWAP"):
    """
    사용자의 특정 심볼에 대한 트레이딩 상태를 반환합니다.
    """
    status = await get_universal_status(user_id, symbol)
    return status == "running"