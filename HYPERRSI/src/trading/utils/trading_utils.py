# trading_utils.py

import asyncio
import json
import traceback
from datetime import datetime

from HYPERRSI.src.core.logger import setup_error_logger
from shared.database.redis_helper import get_redis_client
from shared.database.redis_patterns import scan_keys_pattern
from shared.logging import get_logger
from shared.utils.async_helpers import ensure_async_loop

logger = get_logger(__name__)
error_logger = setup_error_logger()

# redis_client는 사용 시점에 동적으로 import

async def init_user_position_data(user_id: str, symbol: str, side: str):

    redis = await get_redis_client()

    dual_side_position_key = f"user:{user_id}:{symbol}:dual_side_position"
    position_state_key = f"user:{user_id}:position:{symbol}:position_state"
    tp_data_key = f"user:{user_id}:position:{symbol}:{side}:tp_data"
    ts_key = f"trailing:user:{user_id}:{symbol}:{side}"
    dual_side_position_key = f"user:{user_id}:{symbol}:dual_side_position"
    dca_count_key = f"user:{user_id}:position:{symbol}:{side}:dca_count"
    dca_levels_key = f"user:{user_id}:position:{symbol}:{side}:dca_levels"
    position_key = f"user:{user_id}:position:{symbol}:{side}"
    min_size_key = f"user:{user_id}:position:{symbol}:min_sustain_contract_size"
    #main_position_direction_key = f"user:{user_id}:position:{symbol}:main_position_direction"
    tp_state = f"user:{user_id}:position:{symbol}:{side}:tp_state"
    hedging_direction_key = f"user:{user_id}:position:{symbol}:hedging_direction"
    entry_fail_count_key = f"user:{user_id}:entry_fail_count"
    dual_side_count_key = f"user:{user_id}:{symbol}:dual_side_count"
    current_trade_key = f"user:{user_id}:current_trade:{symbol}:{side}"

    await redis.delete(position_state_key)
    await redis.delete(dual_side_position_key)
    await redis.delete(tp_data_key)
    await redis.delete(ts_key)
    await redis.delete(dca_count_key)
    await redis.delete(dca_levels_key)
    await redis.delete(position_key)
    await redis.delete(min_size_key)
    #await redis_client.delete(main_position_direction_key)
    await redis.delete(tp_state)
    await redis.delete(entry_fail_count_key)
    await redis.delete(hedging_direction_key)
    await redis.delete(dual_side_count_key)
    await redis.delete(current_trade_key)
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

async def is_trading_running(user_id: str) -> bool:
    """trading_status 확인 후 'running'이면 True, 아니면 False."""
    redis = await get_redis_client()
    status = await redis.get(f"user:{user_id}:trading:status")
    
    # 바이트 문자열을 디코딩
    if isinstance(status, bytes):
        status = status.decode('utf-8')
        
    return (status == "running")

async def calculate_dca_levels(entry_price: float, last_filled_price:float ,settings: dict, side: str, atr_value: float, current_price: float, user_id: str) -> list:
    pyramiding_entry_type = settings.get('pyramiding_entry_type', '퍼센트 기준')
    pyramiding_value = settings.get('pyramiding_value', 3.0)
    pyramiding_limit = settings.get('pyramiding_limit', 3)
    entry_criterion = settings.get('entry_criterion', '평균 단가')

    if entry_criterion == "평균 단가":
        entry_price = entry_price
    else:
        entry_price = last_filled_price
        
    print(f"[{user_id}] 🖤entry_price: {entry_price}")
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

    print(f"[{user_id}] 계산된 DCA 레벨: {dca_levels}")
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