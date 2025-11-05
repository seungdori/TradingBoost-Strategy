# src/core/shutdown.py

import asyncio
import logging

from HYPERRSI.src.core.config import settings
from shared.database.redis_helper import get_redis_client
from shared.database.redis_migration import get_redis_context
from shared.database.redis_patterns import RedisTimeout, scan_keys_pattern
from shared.logging import get_logger

logger = logging.getLogger(__name__)

async def deactivate_all_trading():
    """
    모든 사용자의 트레이딩을 중지시킵니다.
    """
    # MIGRATED: Using get_redis_context() with PIPELINE for SCAN + multiple GET/SET operations
    async with get_redis_context(user_id="_system_shutdown", timeout=RedisTimeout.PIPELINE) as redis:
        try:
            # 모든 사용자의 trading:status를 stopped로 설정
            # Use SCAN instead of KEYS to avoid blocking Redis
            user_keys = await scan_keys_pattern("user:*:trading:status", redis=redis)
            stop_count = 0

            for key in user_keys:
                if await redis.get(key) == "running":
                    await redis.set(key, "stopped")
                    print(f"STOPPED: {key}")
                    stop_count += 1

            logger.info(f"{stop_count}개의 트레이딩 세션이 중지되었습니다.")

        except Exception as e:
            logger.error(f"트레이딩 중지 중 오류 발생: {str(e)}")
            raise