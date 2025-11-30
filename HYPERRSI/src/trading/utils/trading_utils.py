# trading_utils.py

import asyncio
import json
import traceback
from datetime import datetime

from HYPERRSI.src.core.logger import setup_error_logger
from HYPERRSI.src.trading.utils.position_handler.constants import (
    POSITION_SIDE_KEYS,
    POSITION_SYMBOL_KEYS,
)
from shared.database.redis_helper import get_redis_client
from shared.database.redis_patterns import scan_keys_pattern
from shared.logging import get_logger
from shared.utils.async_helpers import ensure_async_loop

logger = get_logger(__name__)
error_logger = setup_error_logger()

# redis_client는 사용 시점에 동적으로 import


async def init_user_position_data(
    user_id: str,
    symbol: str,
    side: str,
    cleanup_symbol_keys: bool = True
):
    """
    포지션 관련 Redis 데이터를 초기화(삭제)합니다.

    Args:
        user_id: 사용자 ID
        symbol: 거래 심볼 (e.g., "BTC-USDT-SWAP")
        side: 포지션 방향 ("long" 또는 "short")
        cleanup_symbol_keys: True면 심볼 전체 키도 삭제, False면 side별 키만 삭제
                            (반대쪽 포지션이 있을 수 있는 경우 False 사용)

    Returns:
        int: 삭제된 키 개수
    """
    redis = await get_redis_client()

    keys_to_delete = []

    # 1. Side별 키 수집 (POSITION_SIDE_KEYS 사용)
    for key_pattern in POSITION_SIDE_KEYS:
        key = key_pattern.format(user_id=user_id, symbol=symbol, side=side)
        keys_to_delete.append(key)

    # 2. 심볼 전체 키 수집 (cleanup_symbol_keys가 True일 때만)
    if cleanup_symbol_keys:
        for key_pattern in POSITION_SYMBOL_KEYS:
            key = key_pattern.format(user_id=user_id, symbol=symbol)
            keys_to_delete.append(key)

    # 3. 일괄 삭제 (pipeline 사용으로 성능 최적화)
    deleted_count = 0
    if keys_to_delete:
        try:
            deleted_count = await redis.delete(*keys_to_delete)
            logger.debug(
                f"[{user_id}] Position init: {deleted_count}/{len(keys_to_delete)} keys deleted "
                f"for {symbol} {side} (symbol_keys={cleanup_symbol_keys})"
            )
        except Exception as e:
            logger.error(f"[{user_id}] Position init failed: {e}")
            raise

    return deleted_count


async def init_user_monitoring_data(user_id: str, symbol: str):
    """
    monitor:user:{user_id}:{symbol}:* 패턴에 해당하는 모든 키를 삭제합니다.
    """

    redis = await get_redis_client()

    pattern = f"monitor:user:{user_id}:{symbol}:*"

    # pattern에 맞는 모든 키 조회
    # Use SCAN instead of KEYS to avoid blocking Redis
    keys = await scan_keys_pattern(pattern, redis=redis)
    
    # 조회된 키가 있으면 모두 삭제
    if keys:
        await redis.delete(*keys)
        logger.info(f"사용자 {user_id}의 {symbol} 모니터링 데이터를 초기화했습니다. 삭제된 키 개수: {len(keys)}")
    else:
        logger.info(f"사용자 {user_id}의 {symbol} 모니터링 데이터가 없습니다.")

class TPPrice:
    def __init__(self):
        self.prices = {}  # price: ratio

async def store_tp_prices(user_id: str, symbol: str, side: str, tp_prices):

    redis = await get_redis_client()
    tp_data_key = f"user:{user_id}:position:{symbol}:{side}:tp_data"
    await redis.set(tp_data_key, json.dumps(tp_prices))

async def get_tp_prices(user_id: str, symbol: str, side: str):

    redis = await get_redis_client()
    tp_data_key = f"user:{user_id}:position:{symbol}:{side}:tp_data"
    data = await redis.get(tp_data_key)
    return json.loads(data) if data else {}

async def is_trading_running(user_id: str, symbol: str = None) -> bool:
    """trading_status 확인 후 'running'이면 True, 아니면 False.

    Args:
        user_id: 사용자 ID (OKX UID)
        symbol: 심볼 (옵션). None이면 모든 활성 심볼 중 하나라도 running이면 True
    """
    redis = await get_redis_client()

    if symbol:
        # 특정 심볼의 상태 확인
        status = await redis.get(f"user:{user_id}:symbol:{symbol}:status")
        if isinstance(status, bytes):
            status = status.decode('utf-8')
        return (status == "running")
    else:
        # 모든 심볼 중 하나라도 running이면 True
        pattern = f"user:{user_id}:symbol:*:status"
        keys = await redis.keys(pattern)
        for key in keys:
            status = await redis.get(key)
            if isinstance(status, bytes):
                status = status.decode('utf-8')
            if status == "running":
                return True
        return False

async def calculate_dca_levels(entry_price: float, last_filled_price:float ,settings: dict, side: str, atr_value: float, current_price: float, user_id: str) -> list:
    pyramiding_entry_type = settings.get('pyramiding_entry_type', '퍼센트 기준')
    pyramiding_value = settings.get('pyramiding_value', 3.0)
    pyramiding_limit = settings.get('pyramiding_limit', 3)
    entry_criterion = settings.get('entry_criterion', '평균 단가')

    if entry_criterion == "평균 단가":
        entry_price = entry_price
    else:
        entry_price = last_filled_price
        

    #print(f"[{user_id}] entry_criterion : {entry_criterion}\n last_filled_price : {last_filled_price}\n current_price : {current_price}")

    # pyramiding_limit 만큼 DCA 레벨 생성 (마지막 체결가 기준으로 순차 계산)
    dca_levels = []
    base_price = entry_price

    for i in range(1, pyramiding_limit + 1):
        if pyramiding_entry_type == "퍼센트 기준":
            if side == "long":
                level = base_price * (1 - (pyramiding_value / 100))
            else:
                level = base_price * (1 + (pyramiding_value / 100))
        elif pyramiding_entry_type == "금액 기준":
            if side == "long":
                level = base_price - pyramiding_value
            else:
                level = base_price + pyramiding_value
        else:  # ATR 기준
            if side == "long":
                level = base_price - (atr_value * pyramiding_value)
            else:
                level = base_price + (atr_value * pyramiding_value)

        dca_levels.append(level)
        base_price = level  # 다음 레벨은 이전 레벨 기준으로 계산

    return dca_levels

async def update_dca_levels_redis(user_id: str, symbol: str, dca_levels: list, side: str):

    redis = await get_redis_client()
    dca_key = f"user:{user_id}:position:{symbol}:{side}:dca_levels"
    await redis.delete(dca_key)
    if dca_levels:
        await redis.rpush(dca_key, *[str(level) for level in dca_levels])

async def check_dca_condition(current_price: float, dca_levels: list, side: str, use_check_DCA_with_price: bool) -> bool:
    if use_check_DCA_with_price:
        if not dca_levels:
            return False
        next_dca_level = float(dca_levels[0])
        if side == "long":
            return current_price <= next_dca_level
        else:
            return current_price >= next_dca_level
    else:
        return True 