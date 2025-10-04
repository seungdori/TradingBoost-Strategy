# src/core/shutdown.py
from HYPERRSI.src.core.database import redis_client
from HYPERRSI.src.core.config import settings

from HYPERRSI.src.core.logger import get_logger
import asyncio
import logging

logger = logging.getLogger(__name__)

async def deactivate_all_trading():
    """
    모든 사용자의 트레이딩을 중지시킵니다.
    """
    try:
        # 모든 사용자의 trading:status를 stopped로 설정
        user_keys = await redis_client.keys("user:*:trading:status")
        stop_count = 0
        
        for key in user_keys:
            if await redis_client.get(key) == "running":
                await redis_client.set(key, "stopped")
                print(f"STOPPED: {key}")
                stop_count += 1
        
        logger.info(f"{stop_count}개의 트레이딩 세션이 중지되었습니다.")
        
    except Exception as e:
        logger.error(f"트레이딩 중지 중 오류 발생: {str(e)}")
        raise