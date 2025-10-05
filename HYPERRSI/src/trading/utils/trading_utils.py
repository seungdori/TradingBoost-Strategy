# trading_utils.py

import asyncio
import json
import traceback
from datetime import datetime
from shared.logging import get_logger, setup_error_logger
from HYPERRSI.src.core.database import redis_client

logger = get_logger(__name__)
error_logger = setup_error_logger()

def ensure_async_loop():
    """
    현재 스레드에 사용 가능한 이벤트 루프를 반환하거나 새로 생성합니다.
    닫힌 루프나 다른 스레드의 루프는 사용하지 않습니다.
    """
    try:
        # 현재 실행 중인 루프가 있는지 확인
        loop = asyncio.get_running_loop()
        logger.debug("실행 중인 이벤트 루프를 사용합니다.")
        return loop
    except RuntimeError:
        # 현재 실행 중인 루프가 없는 경우
        pass
    
    try:
        # 기존 루프가 있는지 확인
        loop = asyncio.get_event_loop()
        
        # 루프가 닫혀있는지 확인
        if loop.is_closed():
            logger.info("기존 이벤트 루프가 닫혀 있어 새로 생성합니다")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop
    except RuntimeError as ex:
        # 루프가 아예 없는 경우
        if "There is no current event loop in thread" in str(ex):
            logger.info("이벤트 루프가 없어 새로 생성합니다")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop
        
        # 그 외 예상치 못한 오류
        logger.error(f"이벤트 루프 생성 중 오류 발생: {str(ex)}")
        raise

async def init_user_position_data(user_id: str, symbol: str, side: str):
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
    
    await redis_client.delete(position_state_key)
    await redis_client.delete(dual_side_position_key)
    await redis_client.delete(tp_data_key)
    await redis_client.delete(ts_key)
    await redis_client.delete(dca_count_key)
    await redis_client.delete(dca_levels_key)
    await redis_client.delete(position_key)
    await redis_client.delete(min_size_key)
    #await redis_client.delete(main_position_direction_key)
    await redis_client.delete(tp_state)
    await redis_client.delete(entry_fail_count_key)
    await redis_client.delete(hedging_direction_key)
    await redis_client.delete(dual_side_count_key)
    await redis_client.delete(current_trade_key)
async def init_user_monitoring_data(user_id: str, symbol: str):
    """
    monitor:user:{user_id}:{symbol}:* 패턴에 해당하는 모든 키를 삭제합니다.
    """
    pattern = f"monitor:user:{user_id}:{symbol}:*"
    
    # pattern에 맞는 모든 키 조회
    keys = await redis_client.keys(pattern)
    
    # 조회된 키가 있으면 모두 삭제
    if keys:
        await redis_client.delete(*keys)
        logger.info(f"사용자 {user_id}의 {symbol} 모니터링 데이터를 초기화했습니다. 삭제된 키 개수: {len(keys)}")
    else:
        logger.info(f"사용자 {user_id}의 {symbol} 모니터링 데이터가 없습니다.")

class TPPrice:
    def __init__(self):
        self.prices = {}  # price: ratio

async def store_tp_prices(user_id: str, symbol: str, side: str, tp_prices):
    tp_data_key = f"user:{user_id}:position:{symbol}:{side}:tp_data"
    await redis_client.set(tp_data_key, json.dumps(tp_prices))

async def get_tp_prices(user_id: str, symbol: str, side: str):
    tp_data_key = f"user:{user_id}:position:{symbol}:{side}:tp_data"
    data = await redis_client.get(tp_data_key)
    return json.loads(data) if data else {}

async def is_trading_running(user_id: str) -> bool:
    """trading_status 확인 후 'running'이면 True, 아니면 False."""
    status = await redis_client.get(f"user:{user_id}:trading:status")
    
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
    dca_levels = []
    if pyramiding_entry_type == "퍼센트 기준":
        if side == "long":
            level = entry_price * (1 - (pyramiding_value/100))
        else:
            level = entry_price * (1 + (pyramiding_value/100))
    elif pyramiding_entry_type == "금액 기준":
        if side == "long":
            level = entry_price - (pyramiding_value)
        else:
            level = entry_price + (pyramiding_value)
    else:  # ATR 기준이라 가정
        #print("ATR 기준으로 계산") #<-- 문제 없음. 
        # 실제 ATR 계산 로직은 별도
        if side == "long":
            level = entry_price - (atr_value * (pyramiding_value))
        else:
            level = entry_price + (atr_value * (pyramiding_value))
    dca_levels.append(level)

    return dca_levels

async def update_dca_levels_redis(user_id: str, symbol: str, dca_levels: list, side: str):
    dca_key = f"user:{user_id}:position:{symbol}:{side}:dca_levels"
    await redis_client.delete(dca_key)
    if dca_levels:
        await redis_client.rpush(dca_key, *[str(level) for level in dca_levels])

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