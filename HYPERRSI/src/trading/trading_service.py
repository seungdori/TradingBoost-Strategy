# services/trading_service.py

import json
from datetime import datetime, timedelta
import logging
import pytz
from HYPERRSI.src.trading.cancel_trigger_okx import TriggerCancelClient
from numpy import minimum
from HYPERRSI.src.trading.models import Position, OrderStatus, order_type_mapping, UpdateStopLossRequest
from fastapi import HTTPException
from typing import Any, Dict, Optional, List, Tuple
from HYPERRSI.src.api.routes.order import cancel_algo_orders, update_stop_loss_order
from HYPERRSI.src.trading.stats import record_trade_history_entry, update_trade_history_exit
import pandas as pd
import traceback
import httpx
from HYPERRSI.telegram_message import send_telegram_message
from HYPERRSI.src.trading.error_message import map_exchange_error
from shared.logging import get_logger
import asyncio
import contextlib
import time
import ccxt.async_support as ccxt
# Redis, OKX client 등 (실제 경로/모듈명은 프로젝트에 맞게 조정)
from HYPERRSI.src.core.database import redis_client, TradingCache
from HYPERRSI.src.api.dependencies import get_exchange_client as get_okx_client, get_exchange_context

from shared.utils import round_to_tick_size, safe_float, convert_symbol_to_okx_instrument, get_tick_size_from_redis, get_minimum_qty, round_to_qty, get_contract_size as get_contract_size_from_module, convert_bool_to_string, convert_bool_to_int
from HYPERRSI.src.trading.services.get_current_price import get_current_price
from HYPERRSI.src.trading.services.order_utils import get_order_info as get_order_info_from_module, try_send_order, InsufficientMarginError
from shared.logging import get_logger
from HYPERRSI.src.trading.models import get_timeframe




logger = get_logger(__name__)

API_BASE_URL = "/api"

def get_decimal_places(number: float) -> int:
    """주어진 숫자의 소수점 자리수를 반환"""
    str_num = str(abs(float(number)))
    if '.' not in str_num:
        return 0
    return len(str_num.split('.')[1])


#===============================================
# 포지션 데이터 초기화
#===============================================
async def init_user_position_data(user_id: str, symbol: str, side: str, is_first_init: bool = False):
    position_state_key = f"user:{user_id}:position:{symbol}:position_state"
    tp_data_key = f"user:{user_id}:position:{symbol}:{side}:tp_data"
    dca_count_key = f"user:{user_id}:position:{symbol}:{side}:dca_count"
    dca_levels_key = f"user:{user_id}:position:{symbol}:{side}:dca_levels"
    position_key = f"user:{user_id}:position:{symbol}:{side}"
    if is_first_init:
        min_size_key = f"user:{user_id}:position:{symbol}:min_sustain_contract_size"
        await redis_client.delete(min_size_key)
        main_position_direction_key = f"user:{user_id}:position:{symbol}:main_position_direction"
        await redis_client.delete(main_position_direction_key)
    tp_state = f"user:{user_id}:position:{symbol}:{side}:tp_state"
    hedging_direction_key = f"user:{user_id}:position:{symbol}:hedging_direction"
    entry_fail_count_key = f"user:{user_id}:entry_fail_count"
    initial_size_key = f"user:{user_id}:position:{symbol}:{side}:initial_size"
    await redis_client.delete(position_state_key)
    await redis_client.delete(tp_data_key)
    await redis_client.delete(dca_count_key)
    await redis_client.delete(dca_levels_key)
    await redis_client.delete(position_key)
    await redis_client.delete(initial_size_key)
    await redis_client.delete(tp_state)
    await redis_client.delete(entry_fail_count_key)
    await redis_client.delete(hedging_direction_key)


#===============================================
# 트레이딩 서비스
#===============================================





class TradingService:
    """
    - OKX 주문/청산/포지션 조회 로직
    - Redis 포지션 저장/조회
    - 주문 상태 모니터링 (폴링 기반) 예시
    """
    _instances = {}

    def __new__(cls, user_id: str = None):
        if user_id not in cls._instances:
            cls._instances[user_id] = super().__new__(cls)
        return cls._instances[user_id]

    def __init__(self, user_id: str = None):
        if hasattr(self, 'initialized'):
            return
        self.user_id = user_id
        self.client = None
        self.initialized = True
        self._locks = {}  # 락 딕셔너리 초기화 추가

    @classmethod
    async def create_for_user(cls, user_id: str):
        """해당 user_id에 대한 TradingService 인스턴스 생성(OKX 클라이언트 연결)"""
        try:
            #print("create_for_user 호출")
            instance = cls(user_id)
            #print("instance: ", instance)
            
            # 컨텍스트 매니저 사용하여 클라이언트 자동 반환 보장
            async with get_exchange_context(str(user_id)) as client:
                instance.client = client
                #print("instance.client: ", instance.client)
                if instance.client is None:
                    raise Exception("OKX client initialization failed")
                #logger.info(f"Successfully created trading service for user {user_id}")
                return instance
        except Exception as e:
            logger.error(f"Failed to create trading service for user {user_id}: {str(e)}")
            raise Exception(f"트레이딩 서비스 생성 실패: {str(e)}")
        
    @contextlib.asynccontextmanager
    async def position_lock(self, user_id: str, symbol: str):
        """asyncio를 이용한 로컬 락"""
        lock_key = f"position:{user_id}:{symbol}"
        
        if lock_key not in self._locks:
            self._locks[lock_key] = asyncio.Lock()
            
        lock = self._locks[lock_key]
        
        try:
            await lock.acquire()
            yield
        finally:
            lock.release()
            

    async def contract_size_to_qty(self, user_id, symbol: str, contracts_amount: float) -> float:
        """
        계약 수를 주문 수량으로 변환
        """
        try:
            contract_info = await self.get_contract_info( user_id=user_id, symbol = symbol)
            #print("contract_size: ", contract_info['contractSize']) #<-- 비트 기준 0.01로 나오는 것 확인. 
            qty = safe_float(contracts_amount) * safe_float(contract_info['contractSize']) #<-- contract에 contract size를 곱하는 게 맞지.
            qty = round(qty, 8)
            print("qty:1 ", qty) #<-- 비트 기준, 0.01 * 12 = 0.12 로 나오는 것 확인. 
            
            return qty
        except Exception as e:
            logger.error(f"계약 수를 주문 수량으로 변환 실패: {str(e)}")
            return contracts_amount

    async def update_stop_loss(
        self,
        user_id: str,
        symbol: str,
        side: str,
        new_sl_price: float,
        old_order_id: Optional[str] = None
    ) -> bool:
        """
        스탑로스 가격 업데이트
        
        Args:
            user_id: 사용자 ID
            symbol: 거래 심볼
            side: 포지션의 사이드. "long" or "short"
            new_sl_price: 새로운 SL 가격
            
        Returns:
            bool: 업데이트 성공 여부
            
        Raises:
            ValueError: 유효하지 않은 SL 가격
        """
        print("update_stop_loss 호출")
        async with self.position_lock(user_id, symbol):  # 포지션별 락 사용
            try:
                # 1. 현재 포지션 확인
                position = await self.get_current_position(user_id, symbol, side)
                if not position or position.side != side or position.symbol != symbol:
                    logger.warning(f"[{user_id}] 업데이트할 {side} 포지션이 없습니다.")
                    await TradingCache.remove_position(str(user_id), symbol, side)
                    return False

                # 2. SL 가격 유효성 검사
                current_price = await self._get_current_price(symbol)

                if side == "long":
                    if new_sl_price >= current_price:
                        raise ValueError("롱 포지션의 SL은 현재가보다 낮아야 합니다")
  
                else:  # short
                    if new_sl_price <= current_price:
                        raise ValueError("숏 포지션의 SL은 현재가보다 높아야 합니다")


                # 3. 거래소 API로 SL 주문 업데이트
                old_order_id = position.sl_order_id
                try:
                    new_order = await update_stop_loss_order(
                        sl_request=UpdateStopLossRequest(
                            new_sl_price=new_sl_price,
                            symbol=symbol,
                            side=side,
                            order_side="sell" if side == "long" else "buy",
                            size=position.size
                        ),
                        user_id=str(user_id)
                    )
                except Exception as e:
                    logger.error(f"SL 업데이트 실패: {str(e)}")
                    traceback.print_exc()
                    return False
                if not new_order.get('success', True):  # success가 False면
                    logger.info(f"SL update skipped: {new_order.get('message')}")
                    return False


                # 4. Redis 포지션 정보 업데이트
                position.sl_price = new_sl_price
                position.sl_order_id = new_order['id']
                
                position_key = f"user:{user_id}:position:{symbol}:{side}"
                async with redis_client.pipeline() as pipe:
                    pipe.hset(
                        position_key,
                        mapping={
                            "symbol": position.symbol,
                            "side": position.side,
                            "size": str(position.size),
                            "entry_price": str(position.entry_price),
                            "leverage": str(position.leverage),
                            "sl_order_id": str(new_order['id']),
                            "sl_price": str(new_sl_price),
                            "order_id": str(new_order['id'])
                        }
                    )
                    await pipe.execute()

                logger.info(
                    f"SL 업데이트 성공: user={user_id}, symbol={symbol}, id={new_order['id']}, "
                    f"side={side}, new_sl={new_sl_price}"
                )
                return True

            except Exception as e:
                traceback.print_exc()
                logger.error(f"SL 업데이트 실패: {str(e)}")
                # 실패 시 롤백 시도
                if 'new_order' in locals():
                    try:
                        await self.exchange.cancel_order(new_order['id'], symbol)
                    except Exception as cancel_error:
                        logger.error(f"롤백 실패: {str(cancel_error)}")
                raise Exception(f"스탑로스 업데이트 실패: {str(e)}")
        
    async def calculate_tp_prices(
        self,
        user_id: str,
        current_price: float,
        settings: dict,
        side: str,  # 'long' 또는 'short'
        atr_value: Optional[float] = None,
        symbol: Optional[str] = None,
        order_concept: str = None
    ) -> List[float]:
        """
        TP 가격들을 계산합니다.
        Args:
            current_price: 현재 가격
            settings: Redis에서 가져온 설정값
            direction: 포지션 방향 ('long' 또는 'short')
            atr_value: ATR 값 (ATR 기준일 경우 필요)
            symbol: 거래 심볼 (옵션)
        Returns:
            List[float]: 계산된 TP 가격들의 리스트
        """
        if not settings:
            logger.error("Settings dictionary is empty")
            return []
        position_avg_price = None
        try:
            position_avg_price = await self.get_position_avg_price(user_id, symbol, side)
        except Exception as e:
            position_avg_price = current_price
        if not current_price or current_price <= 0:
            logger.error(f"Invalid current price: {current_price}")
            return []
        if position_avg_price is None or position_avg_price <= 0:
            position_avg_price = current_price
        try:
            tp_prices = []
            if not any([settings.get(f'use_tp{i}') for i in range(1, 4)]):
                return tp_prices

            tp_option = settings.get('tp_option')
            # tp_option 유효성 검사
            if tp_option not in ['ATR 기준', '퍼센트 기준', '가격 기준']:
                logger.error(f"Invalid TP option: {tp_option}")
                return []
            #print("ATR VALUE: ", atr_value)
            multiplier = 1 if side == 'long' else -1  # 방향에 따른 승수
            logger.info(f"[TP 계산] side: {side}, multiplier: {multiplier}, position_avg_price: {position_avg_price}, current_price: {current_price}")
            #print("="*20)
            for i in range(1, 4):
                # 아래 조건 주석 처리 - 사용 여부와 상관없이 모든 TP 가격 계산
                #if not settings.get(f'use_tp{i}'): #<-- 생략. 왜냐면, tp prices에 들어가는 것 자체는, 다 들어가야한다. 그래야 리스팅하기가 쉬움.
                #    continue

                tp_value = safe_float(settings.get(f'tp{i}_value', 0))
                if tp_value <= 0:
                    continue

                #logger.info(f"[TP{i} 계산] tp_option: {tp_option}, tp_value: {tp_value}")

                if tp_option == 'ATR 기준':
                    if not atr_value or atr_value <= current_price * 0.001:
                        atr_value = current_price*0.01*0.1
                        #ogger.info(f"[TP{i} 계산] ATR 값 재설정: {atr_value}")
                    
                    raw_tp_price = position_avg_price + (multiplier * atr_value * tp_value)
                    #logger.info(f"[TP{i} 계산] ATR 기준 raw_tp_price = {position_avg_price} + ({multiplier} * {atr_value} * {tp_value}) = {raw_tp_price}")
                    
                    if side == "long":
                        tp_price = max(raw_tp_price, position_avg_price * 1.0001, current_price * 1.0001)
                        #logger.info(f"[TP{i} 계산] Long TP: max({raw_tp_price}, {position_avg_price * 1.0001}, {current_price * 1.0001}) = {tp_price}")
                    else:
                        # short 포지션인 경우 TP는 진입 가격보다 낮아야 함
                        tp_price = min(raw_tp_price, position_avg_price * 0.9999, current_price * 0.9999)
                        #logger.info(f"[TP{i} 계산] Short TP: min({raw_tp_price}, {position_avg_price * 0.9999}, {current_price * 0.9999}) = {tp_price}")
                    
                    original_tp_price = tp_price
                    tp_price = await round_to_tick_size(tp_price, position_avg_price, symbol)
                    #logger.info(f"[TP{i} 계산] Tick size 적용 후: {original_tp_price} -> {tp_price}")
                    
                elif tp_option == '퍼센트 기준':
                    tp_percent = tp_value / 100
                    #logger.info(f"[TP{i} 계산] 퍼센트 기준 tp_percent: {tp_percent}")
                    
                    raw_tp_price = position_avg_price * (1 + (multiplier * tp_percent))
                    #logger.info(f"[TP{i} 계산] 퍼센트 기준 raw_tp_price = {position_avg_price} * (1 + ({multiplier} * {tp_percent})) = {raw_tp_price}")
                    
                    if side == "long":
                        tp_price = max(raw_tp_price, position_avg_price * 1.0001, current_price * 1.0001)
                        #logger.info(f"[TP{i} 계산] Long TP: max({raw_tp_price}, {position_avg_price * 1.0001}, {current_price * 1.0001}) = {tp_price}")
                    else:
                        # short 포지션인 경우 TP는 진입 가격보다 낮아야 함
                        tp_price = min(raw_tp_price, position_avg_price * 0.9999, current_price * 0.9999)
                        logger.info(f"[TP{i} 계산] Short TP: min({raw_tp_price}, {position_avg_price * 0.9999}, {current_price * 0.9999}) = {tp_price}")
                    
                    original_tp_price = tp_price
                    tp_price = await round_to_tick_size(tp_price, position_avg_price, symbol)
                    #logger.info(f"[TP{i} 계산] Tick size 적용 후: {original_tp_price} -> {tp_price}")
                    
                elif tp_option == '가격 기준':
                    raw_tp_price = position_avg_price + (multiplier * tp_value)
                    #logger.info(f"[TP{i} 계산] 가격 기준 raw_tp_price = {position_avg_price} + ({multiplier} * {tp_value}) = {raw_tp_price}")
                    
                    if side == "long":
                        tp_price = max(raw_tp_price, position_avg_price * 1.0001, current_price * 1.0001)
                        #logger.info(f"[TP{i} 계산] Long TP: max({raw_tp_price}, {position_avg_price * 1.0001}, {current_price * 1.0001}) = {tp_price}")
                    else:
                        # short 포지션인 경우 TP는 진입 가격보다 낮아야 함
                        tp_price = min(raw_tp_price, position_avg_price * 0.9999, current_price * 0.9999)
                        #logger.info(f"[TP{i} 계산] Short TP: min({raw_tp_price}, {position_avg_price * 0.9999}, {current_price * 0.9999}) = {tp_price}")
                    
                    original_tp_price = tp_price
                    tp_price = await round_to_tick_size(tp_price, position_avg_price, symbol)
                    #logger.info(f"[TP{i} 계산] Tick size 적용 후: {original_tp_price} -> {tp_price}")
                else:
                    continue

                tp_prices.append(tp_price)
                #logger.info(f"[TP{i} 계산] 최종 TP 가격: {tp_price}")
            
            logger.debug(f"=========\ntp_prices: {tp_prices}\n=========")
            # 롱은 오름차순, 숏은 내림차순으로 정렬
            return sorted(tp_prices, reverse=(side == 'short'))
        except Exception as e:
            logger.error(f"TP 가격 계산 실패: {str(e)}")
            traceback.print_exc()
            return []
        
    async def get_position_mode(self, user_id: str, symbol: str) -> Tuple[str, str]:
        """
        거래소 API를 통해 포지션 모드를 조회합니다.
        
        Args:
            user_id (int): 사용자 ID
            symbol (str): 심볼 (예: "BTC-USDT-SWAP")
            
        Returns:
            str: 포지션 모드 ("hedge" 또는 "one-way"). 설정이 없으면 기본값으로 "hedge" 반환
        """
        try:
            # 거래소 API를 통해 포지션 모드 조회
            try:
                position_mode = await self.client.fetch_position_mode(symbol=symbol)
            except Exception as e:
                traceback.print_exc()
                logger.error(f"2포지션 모드 조회 실패: {str(e)}")
                return "hedge", "cross"
            
            is_hedge_mode = position_mode.get('hedged', True)
            td_mode = position_mode.get('tdMode', 'cross')

            # Redis에 캐시 (bool을 문자열로 변환)
            await redis_client.set(f"user:{user_id}:position:{symbol}:hedge_mode", str(is_hedge_mode).lower())
            await redis_client.set(f"user:{user_id}:position:{symbol}:tdMode", td_mode)
            
            return str(is_hedge_mode).lower(), td_mode
            
        except Exception as e:
            logger.error(f"포지션 모드 조회 실패: {str(e)}")
            traceback.print_exc()
            # Redis에 캐시된 값이 있으면 사용
            cached_mode = await redis_client.get(f"user:{user_id}:position:{symbol}:hedge_mode")
            cached_tdMode = await redis_client.get(f"user:{user_id}:position:{symbol}:tdMode")
            return cached_mode if cached_mode else "true", cached_tdMode if cached_tdMode else "cross"
        
    async def calculate_sl_price(
        self,
        current_price: float,
        side: str,
        settings: dict,
        symbol: Optional[str] = None,
        atr_value: Optional[float] = None
    ) -> Optional[float]:
        """
        설정에 따른 SL 가격 계산
        
        Args:
            current_price: 현재 가격
            side: 포지션 방향 ("long" or "short")
            settings: SL 설정 딕셔너리
            symbol: 거래 심볼 (옵션)
        Returns:
            Optional[float]: 계산된 SL 가격 또는 None
        """
        if not settings.get('use_sl'):
            return None
        try:
            tick_size = await get_tick_size_from_redis(symbol)
        except Exception as e:
            logger.error(f"틱 사이즈 조회 실패: {str(e)}")
            return None
        
        sl_option = settings.get('sl_option')
        sl_value = safe_float(settings.get('sl_value', 0))
        if not sl_value or sl_value <= 0:
            return None

        if sl_option == '퍼센트 기준':
            sl_percent = sl_value / 100
            sl_price = (current_price * (1 - sl_percent) if side == "long" 
                    else current_price * (1 + sl_percent))
            sl_price = await round_to_tick_size(sl_price, current_price, symbol)
            return sl_price
        elif sl_option == '가격 기준':
            sl_price = (current_price - sl_value if side == "long" 
                    else current_price + sl_value)
            sl_price = await round_to_tick_size(sl_price, current_price, symbol)
            return sl_price
        elif sl_option == 'ATR 기준':
            if atr_value is None or atr_value <= current_price * 0.001:
                atr_value = current_price * 0.001  # ATR이 없을 경우 현재가의 0.1%를 사용
            sl_price = current_price - (atr_value * sl_value) if side == "long" else current_price + (atr_value * sl_value)
            sl_price = await round_to_tick_size(sl_price, current_price, symbol)
            return sl_price
        
        return None

    async def get_current_position(
        self,
        user_id: str,
        symbol: Optional[str] = None,
        pos_side: Optional[str] = None
    ) -> Optional[Position]:
        """
        Hedge 모드 대응 포지션 조회:
        1) symbol과 pos_side가 모두 주어진 경우: 해당 특정 포지션만 반환
        2) symbol만 주어진 경우: 해당 심볼의 포지션들 중 하나 반환 (long 우선)
        3) 모두 None인 경우: 모든 활성 포지션 중 첫 번째 것 반환
        """
        max_retries = 3
        retry_delay = 2
        logger.debug(f"[USER ID] : {user_id}, [SYMBOL] : {symbol}, [POS SIDE] : {pos_side}")
        for attempt in range(max_retries):
            try:
                async with asyncio.timeout(20) as _:  # 타임아웃을 20초로 증가
                    try:
                        positions = await self.fetch_okx_position(user_id, symbol, debug_entry_number=1)
                        print(f"[{user_id}] positions: {str(positions)[:50]}...")
                    except Exception as e:
                        logger.error(f"거래소 포지션 조회 실패: {str(e)}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                            continue
                        return None

                if not positions or positions == {}:
                    return None
                #print("="*20)
                #print("positions: ", positions)
                #print("="*20)
                # pos_side가 지정된 경우 해당 방향만 필터링
                possible_short_side = ['short', 'sell']
                possible_long_side = ['long', 'buy']
                if pos_side:
                    if pos_side in possible_short_side:
                        position_info = positions.get('short')
                    elif pos_side in possible_long_side:
                        position_info = positions.get('long')
                    else:
                        print(f"pos_side: {pos_side}")
                        if pos_side not in positions:
                            print("POS SIDE NOT IN POSITIONS")
                        return None
                else:
                    #print("POS SIDE IS NONE")
                    # pos_side가 None이면 long 우선, 없으면 short
                    position_info = positions.get('long') or positions.get('short')
                    if not position_info:
                        print("POSITION INFO IS NONE")
                        return None

                # position_info가 여전히 None인지 확인
                if position_info is None:
                    logger.error(f"position_info이 None입니다. positions: {positions}")
                    return None
                    
                # Redis에서 추가 정보 조회
                side = position_info['side']
                position_key = f"user:{user_id}:position:{symbol}:{side}"
                position_data = await redis_client.hgetall(position_key)

                # TP 데이터 파싱
                tp_data = json.loads(position_data.get('tp_data', '[]'))
                logger.debug(f"❤️‍🔥tp_data: {tp_data}")
                
                # tp_data가 단순 가격 리스트인지 딕셔너리 리스트인지 확인
                if tp_data and isinstance(tp_data[0], (int, float)):
                    # 단순 가격 리스트인 경우
                    tp_prices = [float(price) for price in tp_data]
                    tp_order_ids = []
                else:
                    # 딕셔너리 리스트인 경우 (기존 로직)
                    tp_prices = [float(tp['price']) for tp in tp_data if tp['status'] == 'active']
                    tp_order_ids = [tp.get('order_id') for tp in tp_data if tp['status'] == 'active' and tp.get('order_id')]
                    
                if tp_prices == []:
                    logger.error(f"[{user_id}] {symbol} tp_prices is empty")
                    #return None
                
                #logger.debug(f"tp_prices: {tp_prices}")
                #logger.debug(f"tp_order_ids: {tp_order_ids}")
                # SL 데이터 파싱
                
                sl_data = json.loads(position_data.get('sl_data', '{}'))
                sl_price_str = sl_data.get('price')
                sl_price = float(sl_price_str) if sl_price_str else None
                sl_order_id = sl_data.get('order_id')
                position_qty = safe_float(position_info["position_qty"])
                contracts_amount = safe_float(position_info["contracts_amount"])
                logger.debug(f"sl_price: {sl_price}")
                logger.debug(f"tp_prices: {tp_prices}")
                logger.debug(f"tp_order_ids: {tp_order_ids}")
                return Position(
                    symbol=position_info["symbol"],
                    side=position_info["side"],
                    size=contracts_amount,
                    position_qty=position_qty,
                    contracts_amount=contracts_amount,
                    entry_price=safe_float(position_info["entry_price"]),
                    leverage=safe_float(position_info.get("leverage", 10)),
                    sl_price=sl_price,
                    tp_prices=tp_prices,
                    sl_order_id=sl_order_id,
                    tp_order_ids=tp_order_ids
                )

            except Exception as e:
                logger.error(f"포지션 조회 실패1: {str(e)}")
                traceback.print_exc()
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                return None

        return None
    
    async def get_contract_size(self, symbol: str) -> float:
        try:
            return await get_contract_size_from_module(symbol)
        except Exception as e:
            logger.error(f"Error in get_contract_size for {symbol}: {str(e)}")
            return 0.01
        

    async def open_position(
        self, 
        user_id: str, 
        symbol: str, 
        direction: str, 
        size: float,  #contracts_amount로 들어옴. 
        leverage: float=10.0, 
        settings: dict = {}, 
        stop_loss: Optional[float] = None, 
        take_profit: Optional[float] = None, 
        is_DCA: bool = False,
        order_concept: str = 'new_position',
        is_hedge: bool = False,
        hedge_tp_price: Optional[float] = None,
        hedge_sl_price: Optional[float] = None
    ) -> Position:
        """포지션 오픈 + TP/SL 설정
        Args:
            user_id: 사용자 ID
            symbol: 심볼
            direction: 'long' 또는 'short'
            leverage: 레버리지 (기본값: 10.0)
            settings: 설정 정보
        """
        print(f"direction: {direction}, size: {size}, leverage: {leverage}, size : {size}")
        contracts_amount = size
        position_qty = await self.contract_size_to_qty(user_id, symbol, contracts_amount)
        tp_data = []
        try:
            if direction not in ['long', 'short']:
                raise ValueError("direction must be either 'long' or 'short'")
            settings_key = f"user:{user_id}:settings"
            settings_str = await redis_client.get(settings_key)
            if not settings_str:
                raise ValueError("설정 정보를 찾을 수 없습니다.")
            settings = json.loads(settings_str)
            # 설정 가져오기
            position_key = f"user:{user_id}:position:{symbol}:{direction}"
            cooldown_key = f"user:{user_id}:cooldown:{symbol}:{direction}"
            if user_id != 1709556958 and not is_hedge:
                if await redis_client.get(cooldown_key):
                    ttl = await redis_client.ttl(cooldown_key)
                    raise ValueError(f"[{user_id}] {direction} 진입 중지. 직전 주문 종료 후 쿨다운 시간이 지나지 않았습니다. 쿨다운 시간: " + str(ttl) + "초")
                # 현재가 조회
            current_price = await self._get_current_price(symbol)
            try:
                position_avg_price = await self.get_position_avg_price(user_id, symbol, direction)
                if position_avg_price:
                    position_avg_price = float(position_avg_price)
                else:
                    position_avg_price = current_price
            except Exception as e:
                logger.error(f"포지션 평균가격 조회 실패: {str(e)}")
                traceback.print_exc()
                current_price = await self._get_current_price(symbol)
        
            user_preference_key = f"user:{user_id}:preferences"
            selected_timeframe = await redis_client.hget(user_preference_key, "timeframe")
            if selected_timeframe:
                timeframe = selected_timeframe
            else:
                timeframe = "1m"
            atr_value = await self.get_atr_value(symbol = symbol, timeframe = timeframe, current_price = current_price)
            if atr_value is None or atr_value <= current_price * 0.001:
                atr_value = current_price * 0.001
            # TP 가격 계산
            
            if take_profit:
                try:
                    tp_prices = [take_profit]
                except Exception as e:
                    logger.error(f"TP 가격 계산 실패: {str(e)}")
                    traceback.print_exc()
                    tp_prices = []
            else:
                if order_concept == 'new_position':
                    tp_prices = await self.calculate_tp_prices(user_id = user_id, current_price = current_price,settings= settings, side= direction, symbol=symbol, atr_value=atr_value)
                else:
                    print("DCA 추가진입이므로, 기존 포지션의 평균가격 조회")
                    tp_prices = await self.calculate_tp_prices(user_id = user_id, current_price = position_avg_price,settings= settings, side= direction, symbol=symbol, atr_value=atr_value)
            logger.debug(f"Calculated TP prices: {tp_prices}")
            if not tp_prices:
                logger.error("TP prices list is empty")
                #raise ValueError("Failed to calculate TP prices")

            # TP 데이터 구성

            contracts_amount = size  # 이미 계약 수량임
            total_allocated = 0
            total_allocated_qty = 0


            contracts_amount = await round_to_qty(contracts_amount, symbol)
            position_qty = await self.contract_size_to_qty(user_id, symbol, contracts_amount)
            trailing_start_point = settings.get('trailing_start_point', None)
            use_trailing_stop = settings.get('trailing_stop_active', False)
            if use_trailing_stop == False or trailing_start_point == None or use_trailing_stop == "false":
                use_trailing_stop = False
                trailing_start_point = None
            else:
                use_trailing_stop = True
            
            # TP 단계 결정 (트레일링 스탑 시작점에 따라)
            active_tp_levels = 3  # 기본값: 모든 TP 사용
            use_tp1 = True
            use_tp2 = True
            use_tp3 = True
            if trailing_start_point == 'tp1' and use_trailing_stop:
                active_tp_levels = 1  # TP1만 사용
                use_tp2 = False
                use_tp3 = False
            elif trailing_start_point == 'tp2' and use_trailing_stop == True:
                active_tp_levels = 2  # TP1, TP2 사용
                use_tp3 = False
            if not is_hedge:
                if settings.get('use_tp1', False):
                    tp1_size = round(contracts_amount * (safe_float(settings.get('tp1_ratio', 0)) / 100), 2)
                    total_allocated += tp1_size
                    tp1_qty = round(position_qty * (safe_float(settings.get('tp1_ratio', 0)) / 100), 2)
                    total_allocated_qty += tp1_qty
                    tp_data.append({
                        'price': tp_prices[0],
                        'size': tp1_size,
                        'order_id': None,
                        'position_qty': tp1_qty,
                        'ratio': safe_float(settings.get('tp1_ratio', 0)) / 100,
                        'level': 1,
                        'status': 'active'
                    })
                
                if (settings.get('use_tp2', False) and len(tp_prices) > 1) and use_tp2:
                    tp2_size = round(contracts_amount * (safe_float(settings.get('tp2_ratio', 0)) / 100), 2)
                    total_allocated += tp2_size
                    tp2_qty = round(position_qty * (safe_float(settings.get('tp2_ratio', 0)) / 100), 2)
                    total_allocated_qty += tp2_qty
                    tp_data.append({
                        'price': tp_prices[1],
                        'size': tp2_size,
                        'position_qty': tp2_qty,
                        'ratio': safe_float(settings.get('tp2_ratio', 0)) / 100,
                        'level': 2,
                        'status': 'active'
                    })
                
                if settings.get('use_tp3', False) and len(tp_prices) > 2 and use_tp3:
                    tp3_size = contracts_amount - total_allocated
                    total_allocated += tp3_size
                    tp3_qty = round(position_qty - total_allocated_qty, 2)
                    tp_data.append({
                        'price': tp_prices[2],
                        'size': tp3_size,
                        'position_qty': tp3_qty,
                        'ratio': safe_float(settings.get('tp3_ratio', 0)) / 100,
                        'level': 3,
                        'status': 'active'
                    })
            #==기존 트리거 주문 취소==#
            await self._cancel_order(user_id=user_id, symbol=symbol, side=direction, order_type="trigger")
            # SL 가격 계산
            if not is_hedge:
                if stop_loss:
                    sl_price = stop_loss
                else:
                    sl_price = await self.calculate_sl_price(current_price, direction, settings, symbol=symbol, atr_value=atr_value)
            else:
                sl_price = hedge_sl_price

            # 포지션 오픈
            try:
                print("1번 호출!!!!")
                order_result = await self._try_send_order(
                    user_id=user_id,
                    symbol=symbol,
                    side="buy" if direction == "long" else "sell",
                    size=contracts_amount,  # 계약 수량으로 보냄. 따라서, 아래 텔레그램에서는 변환과정 거침
                    leverage=leverage,
                    order_type="market",
                    price=current_price,
                    direction=direction
                )
                print("주문 결과:", order_result)  # 디버깅용 로그 추가
                
                # order_result가 OrderStatus 객체인지 확인
                if not isinstance(order_result, OrderStatus):
                    logger.error(f"주문 결과가 OrderStatus 객체가 아닙니다: {type(order_result)}")
                    raise ValueError(f"주문 결과가 올바른 형식이 아닙니다: {type(order_result)}")
                
                # 주문 상태가 rejected인 경우 즉시 종료
                if order_result.status == 'rejected' or order_result.order_id == 'margin_blocked' or order_result.order_id == 'max_retries_exceeded':
                    logger.warning(f"[{user_id}] 주문이 거부되었습니다. 후속 작업이 취소됩니다. 상태: {order_result.status}, 주문 ID: {order_result.order_id}")
                    # 주문 실패 정보 기록 후 반환
                    failed_position = Position(
                        symbol=symbol,
                        side=direction,
                        size=contracts_amount,
                        entry_price=current_price,
                        leverage=leverage,
                        sl_price=None,
                        tp_prices=None,
                        order_id=order_result.order_id,
                        status="rejected",
                        contracts_amount=contracts_amount,
                        message=f"주문이 거부되었습니다: {order_result.order_id}"
                    )
                    return failed_position
                    
            except InsufficientMarginError as e:
                # 자금 부족 오류는 이미 처리되었으므로 그대로 상위로 전파
                logger.warning(f"[{user_id}] 자금 부족 오류 발생: {str(e)}")
                raise ValueError(f"자금 부족: {str(e)}")
            except Exception as e:
                error_msg = str(e)
                logger.error(f"포지션 오픈 실패: {str(error_msg)}")
                traceback.print_exc()
                
                if "Service temporarily unavailable" in error_msg:
                    alert_msg = (
                        f"⚠️OKX 거래소 일시 점검\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"현재 OKX 거래소 이슈로 진입이 중지되었습니다\n"
                        f"일정 시간 후에 다시 시도해주세요.\n\n"
                        f"요청 정보:\n"
                        f"심볼: {symbol}\n"
                        #f"방향: {'롱' if direction == 'long' else '숏'}\n"
                        #f"수량: {position_qty}"
                    )
                    cooldown_key = f"user:{user_id}:cooldown:{symbol}:{direction}"
                    await redis_client.set(cooldown_key, "true", ex=300)
                    await send_telegram_message(
                        alert_msg,
                        okx_uid=user_id
                    )
                    await send_telegram_message(
                        alert_msg,
                        okx_uid=user_id,
                        debug=True
                    )
                else:
                    await send_telegram_message(
                        f"⚠️ 포지션 오픈 실패\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"에러: {str(e)}\n"
                        f"심볼: {symbol}\n"
                        f"방향: {'롱' if direction == 'long' else '숏'}\n"
                        f"수량: {position_qty}",
                        okx_uid=user_id,
                        debug=True
                       )
                    return False
            try:
                
                # order_result가 None이거나 avg_fill_price에 접근할 수 없는 경우를 처리
                entry_price = current_price  # 기본값으로 current_price 설정
                initial_size_value = None
                if not is_DCA:
                    initial_size_value = contracts_amount # position_qty가 float이라고 가정

                try:
                    if order_result and hasattr(order_result, 'avg_fill_price'):
                        if order_result.avg_fill_price and order_result.avg_fill_price > 0:
                            entry_price = safe_float(order_result.avg_fill_price)
                    elif isinstance(order_result, dict) and 'avg_fill_price' in order_result:
                        if order_result['avg_fill_price'] and order_result['avg_fill_price'] > 0:
                            entry_price = safe_float(order_result['avg_fill_price'])

                    # 텔레그램 메시지 구성
                    entry_msg = (
                        f"{'📈 롱' if direction == 'long' else '📉 숏'} 포지션 진입\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"심볼: {symbol}\n"
                        f"진입가: {entry_price:.2f}\n"
                        f"수량: {position_qty}\n"
                        f"레버리지: {leverage}x\n"
                        f"주문금액: {position_qty * entry_price:.2f} USDT"
                    )
                except Exception as e:
                    logger.error(f"메세지 전송 실패: {str(e)}")
                    traceback.print_exc()
                #print("entry_msg: ", entry_msg)


                try:
                    await redis_client.hset(position_key, "tp_state", "0")
                    
                except Exception as e:
                    logger.error(f"tp_state 설정 실패: {str(e)}")
                    traceback.print_exc()
                position_state = await redis_client.get(f"user:{user_id}:position:{symbol}:position_state")
                position_state = int(position_state) if position_state else 0
                if not is_hedge:
                    if position_state is None or position_state == 0:
                        position_state = 0
                    if direction == "long" and not is_DCA:
                        position_state = 1
                    elif direction == "short" and not is_DCA:
                        position_state = -1
                    elif direction == "long" and is_DCA and position_state < 3:
                        position_state = 2
                    elif direction == "short" and is_DCA and position_state > -3:
                        position_state = -2
                if is_hedge:
                    if not is_DCA:
                        if position_state > 0:
                            position_state = 3  #<-- 양방향 포지션에 진입한 경우, 롱은 3
                        if position_state < 0:
                            position_state = -3 #<-- 양방향 포지션에 진입한 경우, 숏은 -3
                    else:
                        if position_state > 0:
                            position_state = 4  #<-- 양방향 포지션에 진입하고 DCA 진입한 경우, 롱은 4
                        if position_state < 0:
                            position_state = -4 #<-- 양방향 포지션에 진입하고 DCA 진입한 경우, 숏은 -4
                    
                await redis_client.hset(position_key, "position_state", str(position_state))
                
                await redis_client.set(f"user:{user_id}:position:{symbol}:position_state", str(position_state))
                # stats 처리 로직 수정
                entry_trades = await redis_client.hget(f"user:{user_id}:stats", "entry_trade")
                if entry_trades:
                    await redis_client.hset(f"user:{user_id}:stats", "entry_trade", str(int(entry_trades) + 1))
                else:
                    await redis_client.hset(f"user:{user_id}:stats", "entry_trade", "1")
            except Exception as e:
                logger.error(f"포지션 오픈 실패: {str(e)}")
                traceback.print_exc()   

                # order_id 처리 로직 추가
                order_id = None
                if order_result:
                    if hasattr(order_result, 'order_id'):
                        order_id = order_result.order_id
                    elif isinstance(order_result, dict):
                        order_id = order_result.get('order_id') or order_result.get('id')
                
                if not order_id:
                    # 주문 ID가 없는 경우 타임스탬프로 임시 ID 생성
                    order_id = f"temp_{int(time.time())}_{user_id}_{symbol}"

                # tp_prices와 sl_price는 이미 계산되어 있으니 그걸 직접 사용
                if tp_prices:
                    if not isinstance(tp_prices, (list, tuple)):
                        logger.warning(f"tp_prices is not a list or tuple: {type(tp_prices)}")
                        if isinstance(tp_prices, str):
                            try:
                                tp_prices = json.loads(tp_prices)
                            except json.JSONDecodeError:
                                logger.error(f"Failed to parse tp_prices string: {tp_prices}")
                                tp_prices = []
                        else:
                            tp_prices = []
                    
                    entry_msg += "\n\n🎯 익절 목표가:"
                    for i, price in enumerate(tp_prices, 1):
                        if isinstance(price, (int, float)):
                            entry_msg += f"\nTP{i}: {float(price):.2f}"
                        else:
                            try:
                                price_float = float(price)
                                entry_msg += f"\nTP{i}: {price_float:.2f}"
                            except (ValueError, TypeError):
                                logger.warning(f"Invalid TP price format: {price}")

                # SL 정보가 있으면 추가  
                if sl_price:
                    entry_msg += f"\n\n🛑 손절가: {sl_price:.2f}"

            except Exception as e:
                logger.error(f"{direction} 포지션 오픈 실패: {str(e)}")
                traceback.print_exc()

            try:
                order_id = order_result.order_id
            except Exception as e:
                logger.error(f"주문 ID 처리 실패: {str(e)}")
                traceback.print_exc()
                order_id = None
            # Redis에 저장할 포지션 데이터 구성
            
            
            position_data = {
                "position_info": json.dumps({
                    "symbol": symbol,
                    "side": direction,
                    "size": str(size),
                    "position_qty": str(position_qty),
                    "contracts_amount": str(contracts_amount),
                    "entry_price": str(entry_price),
                    "leverage": str(leverage),
                    "order_id": order_id,
                    "created_at": str(datetime.now()),
                    "status": "open"
                }),
                "settings": json.dumps({
                    "tp_option": settings.get('tp_option', ''),
                    "sl_option": settings.get('sl_option', ''),
                    "use_break_even": settings.get('use_break_even', "false"),
                    "use_break_even_tp2": settings.get('use_break_even_tp2', "false"),
                    "use_break_even_tp3": settings.get('use_break_even_tp3', "false"),
                    "use_sl": settings.get('use_sl', "false"),
                    "use_check_DCA_with_price": settings.get('use_check_DCA_with_price', "true"),
                    "use_rsi_with_pyramiding": settings.get('use_rsi_with_pyramiding', "true"),
                    "trailing_stop_active": settings.get('trailing_stop_active', "false"),
                    "use_sl_on_last": settings.get('use_sl_on_last', "false"),
                }),
                "tp_data": json.dumps(tp_data),
                "sl_data": json.dumps({
                    "price": str(sl_price) if sl_price is not None else None, # None 처리 및 문자열 변환
                    "size": size,
                    "status": "active" if settings.get('use_sl', "false") == "true" else "inactive" # bool 대신 문자열 비교
                }),
                # TP 상태 추적을 위한 필드들 추가
                "get_tp1": "false",  # 문자열로 저장
                "get_tp2": "false",
                "get_tp3": "false",
                "tp_state": "0",  # TP 상태 초기화
                "is_hedge": str(is_hedge).lower(),
                "last_filled_price": str(current_price),
                "last_entry_size": str(contracts_amount)
            }
            
            position_key = f"user:{user_id}:position:{symbol}:{direction}"
            initial_size_key = f"user:{user_id}:position:{symbol}:{direction}:initial_size"
            if initial_size_value is not None:
                position_data["initial_size"] = str(initial_size_value) # 문자열로 저장
                await redis_client.set(initial_size_key, str(initial_size_value))

            # Redis에 모든 데이터 저장
            # Redis에 데이터 저장
            await redis_client.hset(position_key, mapping=position_data)
            if not is_hedge:
                main_position_direction_key = f"user:{user_id}:position:{symbol}:main_position_direction"
                await redis_client.set(main_position_direction_key, direction)
            else:
                hedging_position_direction_key = f"user:{user_id}:position:{symbol}:hedging_position_direction"
                await redis_client.set(hedging_position_direction_key, direction)
            existing_data = await redis_client.hgetall(position_key)
            await redis_client.set(f"user:{user_id}:position:{symbol}:{direction}:tp_data", json.dumps(tp_data))
            #print("existing_data: ", existing_data)
            try:
                current_price =  await get_current_price(symbol)
            except Exception as e:
                logger.error(f"현재 가격 조회 실패: {str(e)}")
                traceback.print_exc()
                current_price = entry_price
            position = Position(
                symbol=symbol,
                side=direction,
                size=size,
                position_qty=position_qty,
                contracts_amount=contracts_amount,
                entry_price=entry_price,
                leverage=leverage,
                tp_prices=tp_prices,
                sl_price=sl_price,
                order_id=order_id,  # order_result.order_id 대신 위에서 처리한 order_id 사용
                status="open",
                message=None
            )
            await record_trade_history_entry(
                user_id=user_id,
                symbol=symbol,
                side=direction,
                size=size,
                entry_price=entry_price,
                leverage=leverage,
                order_id=order_id,
                last_filled_price=current_price  # order_result.order_id 대신 위에서 처리한 order_id 사용
            )


            #===============================================
            # TP/SL 주문 생성 로직
            #===============================================
            able_to_create_tp_sl_orders = True
            if is_hedge and (hedge_tp_price is None and hedge_sl_price is None):
                able_to_create_tp_sl_orders = False
            # TP/SL 주문 생성 (이 함수 내에서 추가 Redis 업데이트 수행)
            try:
                print("IS DCA ? : ", is_DCA)
                if able_to_create_tp_sl_orders:
                    await self._create_tp_sl_orders(
                        user_id=user_id,
                        symbol=symbol,
                        position=position,
                        contracts_amount = size,
                        side=direction,
                        is_DCA=is_DCA,
                        atr_value=atr_value,
                        current_price=current_price,
                        is_hedge=is_hedge,
                        hedge_tp_price=hedge_tp_price,
                        hedge_sl_price=hedge_sl_price,
                    )
            except Exception as e:
                logger.error(f"TP/SL 주문 생성 실패: {str(e)}")
                
            settings_str = await redis_client.get(settings_key)
            settings = json.loads(settings_str) if settings_str else {}

            use_cooldown = settings.get("use_cooldown")
            cooldown_time = settings.get("cooldown_time")
            if use_cooldown == 'true' or cooldown_time > 0 or cooldown_time is None:
                cooldown_key = f"user:{user_id}:cooldown:{symbol}:{direction}"
                await redis_client.set(cooldown_key, "true", ex=cooldown_time)
            return position
        

        except Exception as e:
            traceback.print_exc()
            logger.error(f"{direction} 포지션 오픈 실패: {str(e)}")
            raise

    async def _create_tp_sl_orders(
        self,
        user_id: str,
        symbol: str,
        position: Position,
        contracts_amount: float,
        side: str,
        is_DCA: bool = False,
        atr_value: float = None,
        current_price: float = None,
        is_hedge: bool = False,
        hedge_tp_price: Optional[float] = None,
        hedge_sl_price: Optional[float] = None,
    ) -> None:
        """
        TP와 SL 주문을 생성하고 Redis에 저장합니다.
        DCA가 True면 기존 TP/SL 주문을 제거 후 새로 생성합니다.
        """
        original_side = side
        opposite_side = "sell" if side == "long" else "buy"
        fetched_contracts_amount = contracts_amount
        position_not_exist = False
       # print("중요!!!!!!!!!!! [position_size]가 계약 수량인지 position_qty인지 확인해야 함!!!!!!!!!!!!!!!!!!1")
        #print("일단 amount인걸로 추측됨. ")
        try:
            min_qty = await get_minimum_qty(symbol)
            decimal_places = get_decimal_places(min_qty) 
            position_qty = await self.contract_size_to_qty(user_id, symbol, contracts_amount)
            # 처음 전달받은 position_size를 로그로 남김
            #print(f"[DEBUG] _create_tp_sl_orders 호출됨 | user_id: {user_id}, symbol: {symbol}, side: {side}")
            #print(f"[DEBUG] 초기 입력 position_size: {position_size}")

            settings_str = await redis_client.get(f"user:{user_id}:settings")
            if not settings_str:
                logger.error(f"Settings not found for user {user_id}")
                await send_telegram_message(message=(    "⚠️ TP/SL 주문 생성 실패\n"    "━━━━━━━━━━━━━━━\n"    "사용자 설정을 찾을 수 없습니다."),okx_uid=user_id)
                return

            try:
                settings = json.loads(settings_str)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse settings for user {user_id}")
                await send_telegram_message(
                    message=(
                        "⚠️ TP/SL 주문 생성 실패\n"
                        "━━━━━━━━━━━━━━━\n"
                        "설정 데이터 형식이 올바르지 않습니다."
                    ),
                    okx_uid=user_id
                )
                return

            # 1) 먼저 Redis에 저장된 기존 포지션/주문 정보를 가져옵니다.
            position_key = f"user:{user_id}:position:{symbol}:{side}"

            existing_data = await redis_client.hgetall(position_key)
            # 자세한 내용 확인용 디버그 출력
            #print(f"[DEBUG] 기존 Redis 포지션 데이터: {existing_data}")

            # 2) DCA 모드인 경우 기존 TP/SL 주문 취소 및 Redis 정리
            try:
                if is_DCA:
                    print("[DEBUG] DCA 모드 진입: 기존 TP/SL 주문 취소 및 Redis 정보 삭제")

                    existing_tp_order_ids = existing_data.get("tp_order_ids", "")
                    print(f"[DEBUG] 기존 TP 주문 목록: {existing_tp_order_ids}")

                    if existing_tp_order_ids:
                        for tp_order_id in existing_tp_order_ids.split(","):
                            if tp_order_id:
                                print(f"[DEBUG] 기존 TP 주문 취소 시도 -> {tp_order_id}")
                                try:
                                    await self._cancel_order(
                                        user_id=user_id,
                                        symbol=symbol,
                                        order_id=tp_order_id,
                                        order_type="take_profit",
                                        side=side
                                    )
                                    logger.debug(f"[DCA] 기존 TP 주문 {tp_order_id} 취소 완료")
                                    
                                    # 모니터링 데이터 삭제 전 최종 상태 확인
                                    monitor_key = f"monitor:user:{user_id}:{symbol}:order:{tp_order_id}"
                                    logger.debug(f"[DCA] TP 주문 삭제 전 최종 확인: {tp_order_id}")
                                    
                                    try:
                                        from HYPERRSI.src.trading.monitoring import check_order_status, update_order_status
                                        
                                        # 삭제 직전 실제 상태 확인
                                        final_status = await check_order_status(
                                            user_id=user_id,
                                            symbol=symbol,
                                            order_id=tp_order_id,
                                            order_type="tp"
                                        )
                                        
                                        if isinstance(final_status, dict) and 'status' in final_status:
                                            status_value = str(final_status['status'].value) if hasattr(final_status['status'], 'value') else str(final_status['status'])
                                            
                                            if status_value.lower() in ['filled', 'closed']:
                                                logger.warning(f"[DCA] 삭제 직전 TP 체결 발견: {tp_order_id}")
                                                
                                                # 체결 알림 직접 처리 (재귀 호출 방지)
                                                filled_amount = final_status.get('filled_amount', final_status.get('amount', '0'))
                                                
                                                # 15분 체크
                                                current_time_ms = int(time.time() * 1000)
                                                should_send = True
                                                
                                                for time_field in ['updated_at', 'lastUpdateTimestamp', 'lastTradeTimestamp', 'fillTime']:
                                                    if time_field in final_status:
                                                        order_fill_time = final_status[time_field]
                                                        if order_fill_time < 1000000000000:
                                                            order_fill_time *= 1000
                                                        time_diff_minutes = (current_time_ms - order_fill_time) / 1000 / 60
                                                        if time_diff_minutes > 15:
                                                            logger.warning(f"[DCA] TP 체결이 {time_diff_minutes:.1f}분 전이므로 알림 스킵")
                                                            should_send = False
                                                        break
                                                
                                                if should_send:
                                                    # 직접 알림 메시지 구성 및 전송
                                                    title = f"🟢 익절(TP) 체결 완료"
                                                    message = (
                                                        f"{title}\n"
                                                        f"━━━━━━━━━━━━━━━\n"
                                                        f"심볼: {symbol}\n"
                                                        f"방향: {side.upper()}\n"
                                                        f"주문ID: {tp_order_id}\n"
                                                    )
                                                    
                                                    await send_telegram_message(message, user_id)
                                                    logger.info(f"[DCA] 삭제 직전 TP 체결 알림 직접 전송 완료: {tp_order_id}")
                                            elif status_value.lower() in ['canceled']:
                                                logger.debug(f"[DCA] 삭제 직전 확인 - TP 취소됨: {tp_order_id}")
                                                
                                    except Exception as final_check_error:
                                        logger.error(f"[DCA] TP 삭제 직전 확인 오류: {tp_order_id}, {str(final_check_error)}")
                                    
                                    # 모니터링 데이터 삭제
                                    await redis_client.delete(monitor_key)
                                    logger.debug(f"[DCA] 모니터링 데이터 삭제 완료: {monitor_key}")
                                except Exception as e:
                                    logger.error(f"[DCA] TP 주문 취소 실패: {tp_order_id}, {str(e)}")

                    existing_sl_order_id = existing_data.get("sl_order_id")
                    print(f"[DEBUG] 기존 SL 주문 ID: {existing_sl_order_id}")

                    if existing_sl_order_id:
                        try:
                            await self._cancel_order(
                                user_id=user_id,
                                symbol=symbol,
                                order_id=existing_sl_order_id,
                                side=side,
                                order_type="trigger"
                            )
                            #logger.info(f"[DCA] 기존 SL 주문 {existing_sl_order_id} 취소 완료")
                            
                            # 모니터링 데이터 삭제 전 최종 상태 확인
                            monitor_key = f"monitor:user:{user_id}:{symbol}:order:{existing_sl_order_id}"
                            logger.debug(f"[DCA] SL 주문 삭제 전 최종 확인: {existing_sl_order_id}")
                            
                            try:
                                from HYPERRSI.src.trading.monitoring import check_order_status, update_order_status
                                
                                # 삭제 직전 실제 상태 확인
                                final_status = await check_order_status(
                                    user_id=user_id,
                                    symbol=symbol,
                                    order_id=existing_sl_order_id,
                                    order_type="sl"
                                )
                                
                                if isinstance(final_status, dict) and 'state' in final_status:
                                    state_value = final_status.get('state')
                                    
                                    if state_value == 'filled':
                                        logger.warning(f"[DCA] 삭제 직전 SL 체결 발견: {existing_sl_order_id}")
                                        
                                        # 체결 알림 직접 처리 (재귀 호출 방지)
                                        filled_amount = final_status.get('filled_amount', final_status.get('sz', '0'))
                                        
                                        # 직접 알림 메시지 구성 및 전송
                                        title = f"🔴 손절(SL) 체결 완료"
                                        message = (
                                            f"{title}\n"
                                            f"━━━━━━━━━━━━━━━\n"
                                            f"심볼: {symbol}\n"
                                            f"방향: {side.upper()}\n"
                                            f"주문ID: {existing_sl_order_id}\n"
                                        )
                                        
                                        await send_telegram_message(message, user_id)
                                        logger.info(f"[DCA] 삭제 직전 SL 체결 알림 직접 전송 완료: {existing_sl_order_id}")
                                    elif state_value == 'canceled':
                                        logger.debug(f"[DCA] 삭제 직전 확인 - SL 취소됨: {existing_sl_order_id}")
                                        
                            except Exception as final_check_error:
                                logger.error(f"[DCA] SL 삭제 직전 확인 오류: {existing_sl_order_id}, {str(final_check_error)}")
                            
                            # 모니터링 데이터 삭제
                            await redis_client.delete(monitor_key)
                            logger.info(f"[DCA] 모니터링 데이터 삭제 완료: {monitor_key}")
                        except Exception as e:
                            logger.error(f"[DCA] SL 주문 취소 실패: {existing_sl_order_id}, {str(e)}")

                    # Redis에서 TP/SL 관련 필드 삭제
                    await redis_client.hdel(
                        position_key,
                        "tp_order_ids", "tp_prices", "tp_sizes", "tp_contracts_amounts", "tp_sizes", "sl_contracts_amount",
                        "sl_order_id", "sl_price", "sl_size"
                    )
                    logger.info(f"[DCA] Redis에 저장된 기존 TP/SL 정보 삭제 완료")

                    # 최신 포지션 사이즈/평단가 확인
                    pos_dict = await self.fetch_okx_position(user_id, symbol, side, debug_entry_number=3)
                    #print(f"[DEBUG] fetch_okx_position 결과: {pos_dict}")

                    if pos_dict:
                        # DCA에서는 포지션 값이 다시 업데이트되므로 position_size 재설정
                        position_qty = float(pos_dict.get(side, {}).get('position_qty', 0.0)) or 0.0
                        contracts_amount = float(pos_dict.get(side, {}).get('contracts_amount', 0.0)) or 0.0
                        position_avg_price = float(pos_dict.get(side, {}).get('avgPrice', 0.0)) or 0.0

                    print(f"[DEBUG] DCA 후 재설정된 position_size: {contracts_amount}, contracts_amount: {contracts_amount}")

            except Exception as e:
                logger.error(f"포지션 정보 불러오기 실패: {str(e)}")
                traceback.print_exc()
            # DCA가 아닐 때, 현 시점 포지션 사이즈 다시 불러오기
            if not is_DCA:
                pos_dict = await self.fetch_okx_position(user_id, symbol, side, debug_entry_number=2)
                if pos_dict:
                    # 만약 fetch_okx_position()이 'long'/'short' 키없이 반환한다면 수정 필요
                    # 현재 로직에 맞춰 size 필드가 바로 있는 경우 fallback
                    fetched_size = float(pos_dict.get("size", contracts_amount)) or contracts_amount
                    print(f"[DEBUG] fetch_okx_position()에서 불러온 size: {fetched_size}")
                    #position_size = fetched_size #< --- 이렇게 하면 뒤에 contract amount를 따로 구할 필요 없지만 이미 해놔서 주석처리
                    try:
                        fetched_contracts_amount = float(pos_dict.get("contracts_amount", 0.0)) or 0.0
                        print(f"[DEBUG] fetch_okx_position()에서 불러온 contracts: {fetched_contracts_amount}")
                    except Exception as e:
                        logger.error(f"contracts_amount 파싱 실패: {str(e)}")
                        fetched_contracts_amount = contracts_amount
            # DCA일 때, TP 계산 로직
            if is_DCA and not is_hedge:
                position_avg_price = float(pos_dict.get(side, {}).get('avgPrice', 0.0)) or current_price
                if position_avg_price == 0.0:
                    current_price = await self._get_current_price(symbol)
                else:
                    current_price = position_avg_price

                print(f"[DEBUG] DCA - TP 계산용 current_price: {current_price}")

                tp_prices = await self.calculate_tp_prices(user_id = user_id, current_price = current_price,settings= settings, side= side, symbol=symbol, atr_value=atr_value)
                print(f"[DEBUG] calculate_tp_prices 결과: {tp_prices}")

                if tp_prices:
                    position.tp_prices = tp_prices

            # 최종 position_size 확인 로깅
            print(f"[DEBUG] 최종 position_size (TP 주문 직전): {contracts_amount}")

            # --------------------
            # TP 주문 생성 로직
            # --------------------
            position_data = await redis_client.hgetall(position_key)
            tp_data_list = []
            
            tp_data_str = position_data.get("tp_data")
            #print("!!!!tp_data_str@@@: ", tp_data_str)
            if tp_data_str:
                tp_data_list = json.loads(tp_data_str)
                #print("!!!!tp2323_data_list@@@: ", tp_data_list)
            
            if position.tp_prices and not is_hedge:
                last_tp = False
                logger.info(f"Creating TP orders for user {user_id}")
                # (이전 코드) min_qty 가져오기
                min_qty = await get_minimum_qty(symbol)
                #logger.info(f"[DEBUG] {symbol}의 minimum_qty: {min_qty}")

                tp_order_ids = []
                total_size = float(contracts_amount)
                remaining_size = total_size

                #logger.info(f"[DEBUG] TP 생성 시작 | total_size: {total_size}")

                # 트레일링 스탑 설정 가져오기
                trailing_start_point = settings.get('trailing_start_point', None)
                use_trailing_stop = settings.get('trailing_stop_active', False)
                # TP 단계 결정 (트레일링 스탑 시작점에 따라)
                active_tp_levels = 3  # 기본값: 모든 TP 사용
                if trailing_start_point == 'tp1' and use_trailing_stop == True:
                    active_tp_levels = 1  # TP1만 사용
                    use_tp2 = False
                    use_tp3 = False
                elif trailing_start_point == 'tp2' and use_trailing_stop == True:
                    active_tp_levels = 2  # TP1, TP2 사용
                    use_tp3 = False
                elif trailing_start_point == 'tp3' and use_trailing_stop == True:
                    active_tp_levels = 3  # TP1, TP2, TP3 사용
                # TP 비율 계산
                tp_ratios = []
                tp_accumulator = 0.0  # 누적 수량

                for i in range(1, 4):  # 활성화된 TP 레벨만 처리
                    if settings.get(f'use_tp{i}'):
                        ratio = safe_float(settings.get(f'tp{i}_ratio', 0)) / 100
                        tp_ratios.append(ratio)

                # 비율 합이 정확히 1이 되도록 정규화
                if tp_ratios:
                    ratio_sum = sum(tp_ratios)
                    if ratio_sum > 0:
                        tp_ratios = [r / ratio_sum for r in tp_ratios]
                        
                        # 마지막 TP에 나머지 비율을 할당하여 정확히 1이 되도록 조정
                        adjusted_ratios = tp_ratios.copy()
                        adjusted_sum = sum(adjusted_ratios[:-1])  # 마지막 항목 제외한 합
                        adjusted_ratios[-1] = 1.0 - adjusted_sum  # 마지막 항목은 나머지 비율로 설정
                        tp_ratios = adjusted_ratios

                #logger.info(f"[DEBUG] TP 비율들 (정규화 후): {tp_ratios}")
                #logger.info(f"[DEBUG] 설정된 TP 가격들: {position.tp_prices}")  # 활성화된 TP 가격만 표시
                
                tp_sizes = []
                tp_contracts_amounts = []
                successful_tps = []
                contract_size = await self.get_contract_size(symbol)
                print(f"[DEBUG] TP 생성 시작 | contract_size: {contract_size}")
                
                # 활성화된 TP 레벨만큼만 처리
                active_tp_prices = position.tp_prices[:active_tp_levels]

                # 모든 TP 가격을 tp_data_list에 추가 (사용하지 않는 TP 포함)
                for i, tp_price in enumerate(position.tp_prices):
                    # tp_data_list에 해당 레벨의 TP가 없으면 추가
                    found = False
                    for tp in tp_data_list:
                        if tp.get("level") == i+1:
                            # 이미 존재하면 가격 업데이트
                            tp["price"] = tp_price
                            tp["status"] = "active" if i < active_tp_levels else "inactive"
                            found = True
                            break
                    
                    if not found:
                        # 새로운 TP 데이터 추가
                        tp_data_list.append({
                            "level": i+1,
                            "price": tp_price,
                            "status": "active" if i < active_tp_levels else "inactive"
                        })

                for i, (tp_price, ratio) in enumerate(zip(active_tp_prices, tp_ratios)):
                    # 비율에 따른 주문 크기 계산
                    if i == len(tp_ratios) - 1:  # 마지막 TP인 경우
                        # 정확히 남은 수량 모두 사용
                        tp_size = remaining_size
                    
                    else:
                        # 비율에 따른 계산
                        raw_size = round(total_size * ratio,2)
                        tp_size = raw_size
                    
                    # min_qty보다 작은 경우 처리
                    if tp_size < min_qty:
                        print(f"[DEBUG] TP{i+1} -> tp_size < min_qty, tp_size를 min_qty로 강제 조정")
                        tp_size = min_qty
                        last_tp = True
                    if position_not_exist:
                        print("포지션이 없어서 TP 주문 생성 건너뜀")
                        continue
                    # 소수점 처리
                    contracts_amount_value = round(float(tp_size), decimal_places)
                    contracts_amount_str = f"{{:.{decimal_places}f}}".format(contracts_amount_value)
                    
                    # 남은 사이즈 감소
                    remaining_size -= tp_size
                    print(f"[DEBUG] TP{i+1} -> [contracts_amount: {contracts_amount_str}] 최종 결정 tp_size: {tp_size}, remaining_size: {remaining_size}")
                    
                    tp_sizes.append(str(tp_size))
                    tp_contracts_amounts.append(contracts_amount_str)

                    try:
                        tp_order = await self._try_send_order(
                            user_id=user_id,
                            symbol=symbol,
                            side="sell" if position.side == "long" else "buy",
                            size=float(contracts_amount_str),
                            price=tp_price,
                            leverage=position.leverage,
                            order_type="take_profit",
                            trigger_price=tp_price,
                            direction=position.side
                        )
                        # 주문 성공
                        if tp_order:
                            order_id = tp_order.order_id
                            print(f"[DEBUG] TP{i+1} 주문 성공 -> order_id: {order_id}, price: {tp_price}, size: {contracts_amount_str}")
                            tp_order_ids.append(order_id)
                            tp_data_str = position_data.get("tp_data")
                            for tp in tp_data_list:
                                if tp["level"] == i+1:
                                    tp["order_id"] = order_id
                                    break
                                    
                            # 모니터링 데이터 저장
                            monitor_key = f"monitor:user:{user_id}:{symbol}:order:{order_id}"
                            now = datetime.now()
                            kr_time = now + timedelta(hours=9)
                            
                            monitor_data = {
                                "status": "open",
                                "price": str(tp_price),
                                "position_side": position.side,
                                "contracts_amount": contracts_amount_str,
                                "order_type": f"tp{i+1}",
                                "order_name": f"tp{i+1}",  # order_name 추가
                                "position_qty": str(position_qty),
                                "ordertime": str(int(now.timestamp())),
                                "filled_contracts_amount": "0",
                                "remain_contracts_amount": contracts_amount_str,
                                "last_updated_time": str(int(now.timestamp())),
                                "last_updated_time_kr": kr_time.strftime("%Y-%m-%d %H:%M:%S"),
                                "is_hedge": "false"
                            }
                            
                            await redis_client.hset(monitor_key, mapping=monitor_data)
                            logger.info(f"[TP{i+1}] 모니터링 데이터 저장 완료: {monitor_key}")
                            
                        if remaining_size <= 0 or tp_size == 0.0:
                            #print(f"[DEBUG] 더 이상 남은 사이즈가 없으므로 TP{i+1}에서 반복문 탈출")
                            break

                    except Exception as e:
                        error_msg = map_exchange_error(e)
                        logger.error(f"TP{i+1} 주문 생성 실패: {str(e)}")
                        await send_telegram_message(message=(f"⚠️ TP{i+1} 주문 생성 실패\n"f"━━━━━━━━━━━━━━━\n"f"{error_msg}\n"f"가격: {tp_price:.2f}\n"f"수량: {round(tp_size, decimal_places)}"),okx_uid=user_id)
                        if "You don't have any positions" in str(e):
                            position_not_exist = True

                # TP 주문 결과를 Redis에 업데이트
                tp_data = {
                    "tp_prices": ",".join(str(p) for p in position.tp_prices),  # 모든 TP 가격 저장
                    "tp_order_ids": ",".join(tp_order_ids),
                    "tp_sizes": ",".join(tp_sizes),
                    "tp_contracts_amounts": ",".join(tp_contracts_amounts),
                    "tp_data": json.dumps(tp_data_list)
                }
                print(f"[DEBUG] 최종 TP Redis 저장 데이터: {tp_data}")
                await redis_client.hset(position_key, mapping=tp_data)
            if is_hedge and (hedge_tp_price is not None):
                try:
                    tp_order = await self._try_send_order(
                        user_id=user_id,
                        symbol=symbol,
                        side="sell" if (position.side == "long" or position.side == "buy") else "buy",
                        size=contracts_amount,
                        price=hedge_tp_price,
                        order_type="take_profit",
                        trigger_price=hedge_tp_price,
                        direction=position.side
                    )
                    try:
                        tp_price_into_data = float(position.tp_prices[0]) if position.tp_prices else None
                    except Exception as e:
                        tp_price_into_data = hedge_tp_price
                    tp_data = {
                        "tp_prices": str(tp_price_into_data),
                        "tp_order_ids": str(tp_order.order_id),
                        "tp_sizes": str(contracts_amount),
                        "tp_contracts_amounts": str(contracts_amount),
                        "tp_data": json.dumps(tp_data_list)
                    }
                    await redis_client.hset(position_key, mapping=tp_data)
                    dual_side_key = f"user:{user_id}:{symbol}:dual_side_position"
                    await redis_client.hset(dual_side_key, mapping=tp_data)
                    
                    # 모니터링 데이터 저장 (헷지 TP)
                    monitor_key = f"monitor:user:{user_id}:{symbol}:order:{tp_order.order_id}"
                    now = datetime.now()
                    kr_time = now + timedelta(hours=9)
                    
                    monitor_data = {
                        "status": "open",
                        "price": str(hedge_tp_price),
                        "position_side": position.side,
                        "contracts_amount": str(contracts_amount),
                        "order_type": "tp1",  # 헷지는 단일 TP만 사용
                        "order_name": "tp1",  # order_name 추가
                        "position_qty": str(position_qty),
                        "ordertime": str(int(now.timestamp())),
                        "filled_contracts_amount": "0",
                        "remain_contracts_amount": str(contracts_amount),
                        "last_updated_time": str(int(now.timestamp())),
                        "last_updated_time_kr": kr_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "is_hedge": "true"
                    }
                    
                    await redis_client.hset(monitor_key, mapping=monitor_data)
                    logger.info(f"[헷지 TP] 모니터링 데이터 저장 완료: {monitor_key}")
                except Exception as e:
                    logger.error(f"헷지 TP 주문 생성 실패: {str(e)}")
                    traceback.print_exc()
                    await send_telegram_message(f"⚠️ 헷지 TP 주문 생성 실패: {str(e)}",okx_uid=user_id, debug=True)
                
                
            # --------------------
            # SL 주문 생성 로직
            # --------------------
            if position.sl_price and settings.get('use_sl') and not is_hedge and not position_not_exist:
                okay_to_order_sl = True
                try:
                    use_sl_only_on_last_dca = settings.get('use_sl_on_last', False)
                    if use_sl_only_on_last_dca:
                        dca_count_key = f"user:{user_id}:position:{symbol}:{position.side}:dca_count"
                        dca_count = await redis_client.get(dca_count_key)
                        if dca_count is None:
                            dca_count = 0
                        else:
                            dca_count = int(dca_count)
                        pyramding_limit = settings.get('pyramiding_limit', 8)
                        if use_sl_only_on_last_dca and dca_count+1 <= int(pyramding_limit):
                            okay_to_order_sl = False
                        else:
                            okay_to_order_sl = True
                    else:
                        okay_to_order_sl = True
                            
                        
                        
                except Exception as e:
                    logging.error(f"close on Last dca 오류 : {str(e)}")
                    okay_to_order_sl = True
                    
                contracts_amount = position.contracts_amount
                sl_contracts_amount = round(float(contracts_amount), decimal_places)
                

                #print(f"[SL AMOUNT with FETCHED_CONTRACTS_AMOUNT: {sl_contracts_amount}]")
                #print(f"[SL AMOUNT : {sl_contracts_amount}] SL 주문 생성 시작 -> SL 가격: {position.sl_price}, SL 수량: {position_size}")
                if okay_to_order_sl == True:
                    try:
                        sl_order = await self._try_send_order(
                            user_id=user_id,
                            symbol=symbol,
                            side="sell" if position.side == "long" else "buy",
                            size = sl_contracts_amount, #<-- fetched_contracts_amount 사용
                            #size=position.size,  # 여기서 position.size 확인
                            price=position.sl_price,
                            order_type="stop_loss",
                            leverage=position.leverage,
                            trigger_price=position.sl_price,
                            direction=position.side
                        )
                        #print(f"[DEBUG] SL ORDER 반환: {sl_order}")

                        sl_order_id = (
                            sl_order['algoId'] 
                            if isinstance(sl_order, dict) else sl_order.order_id
                        )
                        # Redis에 SL 정보 업데이트
                        sl_data = {
                            "sl_price": str(position.sl_price),
                            "sl_order_id": sl_order_id,
                            "sl_size": str(fetched_contracts_amount),
                            "sl_position_qty": str(position_qty),
                            "sl_contracts_amount": str(sl_contracts_amount)
                        }
                        #print(f"[DEBUG] SL Redis 저장 데이터: {sl_data}")
                        await redis_client.hset(position_key, mapping=sl_data)
                        position.sl_order_id = sl_order_id
                        
                        # 모니터링 데이터 저장 (SL)
                        monitor_key = f"monitor:user:{user_id}:{symbol}:order:{sl_order_id}"
                        now = datetime.now()
                        kr_time = now + timedelta(hours=9)
                        
                        monitor_data = {
                            "status": "open",
                            "price": str(position.sl_price),
                            "position_side": position.side,
                            "contracts_amount": str(sl_contracts_amount),
                            "order_type": "sl",
                            "order_name": "sl",  # order_name 추가
                            "position_qty": str(position_qty),
                            "ordertime": str(int(now.timestamp())),
                            "filled_contracts_amount": "0",
                            "remain_contracts_amount": str(sl_contracts_amount),
                            "last_updated_time": str(int(now.timestamp())),
                            "last_updated_time_kr": kr_time.strftime("%Y-%m-%d %H:%M:%S"),
                            "is_hedge": "false"
                        }
                        
                        await redis_client.hset(monitor_key, mapping=monitor_data)
                        logger.info(f"[SL] 모니터링 데이터 저장 완료: {monitor_key}")

                    except Exception as e:
                        error_msg = map_exchange_error(e)
                        traceback.print_exc()
                        logger.error(f"SL 주문 생성 실패: {str(e)}")
                        await send_telegram_message((f"⚠️ 손절 주문 생성 실패\n"f"━━━━━━━━━━━━━━━\n"f"{error_msg}\n"f"가격: {position.sl_price:.2f}\n"f"수량: {position.position_qty}"),okx_uid=user_id,debug=True)
                        sl_order_id = None
            if is_hedge and (hedge_sl_price is not None):
                dual_side_settings_key = f"user:{user_id}:dual_side"
                dual_side_settings = await redis_client.hgetall(dual_side_settings_key)
                use_dual_sl = dual_side_settings.get('use_dual_sl', False)
                if use_dual_sl:
                    try:
                        sl_order = await self._try_send_order(
                            user_id=user_id,
                            symbol=symbol,
                            side="sell" if position.side == "long" else "buy",
                            size=contracts_amount,
                            price=hedge_sl_price,
                            order_type="stop_loss",
                            trigger_price=hedge_sl_price,
                            direction=position.side
                        )

                        sl_data = {
                            "sl_price": str(position.sl_price),
                            "sl_order_id": sl_order.order_id,
                            "sl_size": str(contracts_amount),
                            "sl_contracts_amount": str(contracts_amount),
                            "sl_position_qty": str(position_qty)
                        }
                        await redis_client.hset(position_key, mapping=sl_data)

                        # 모니터링 데이터 저장 (헷지 SL)
                        monitor_key = f"monitor:user:{user_id}:{symbol}:order:{sl_order.order_id}"
                        now = datetime.now()
                        kr_time = now + timedelta(hours=9)

                        monitor_data = {
                            "status": "open",
                            "price": str(hedge_sl_price),
                            "position_side": position.side,
                            "contracts_amount": str(contracts_amount),
                            "order_type": "sl",
                            "order_name": "sl",  # order_name 추가
                            "position_qty": str(position_qty),
                            "ordertime": str(int(now.timestamp())),
                            "filled_contracts_amount": "0",
                            "remain_contracts_amount": str(contracts_amount),
                            "last_updated_time": str(int(now.timestamp())),
                            "last_updated_time_kr": kr_time.strftime("%Y-%m-%d %H:%M:%S"),
                            "is_hedge": "true"
                        }

                        await redis_client.hset(monitor_key, mapping=monitor_data)
                        logger.info(f"[헷지 SL] 모니터링 데이터 저장 완료: {monitor_key}")
                    except Exception as e:  
                        logger.error(f"헷지 SL 주문 생성 실패: {str(e)}")
                        traceback.print_exc()
                        await send_telegram_message(
                            f"⚠️ 헷지 SL 주문 생성 실패: {str(e)}",
                            okx_uid=user_id, debug=True
                        )
                        sl_order_id = None

                    
            elif position.sl_price is None or position.sl_price == 0.0 or settings.get('use_sl') == False:
                try:
                    await redis_client.hdel(position_key, "sl_price", "sl_order_id", "sl_size", "sl_contracts_amount", "sl_position_qty")
                    logger.info(f"SL 관련 필드 삭제 완료: {position_key}")
                            # 로컬 객체 상태 업데이트
                    position.sl_price = None
                    position.sl_order_id = None
                except Exception as e:
                    logger.error(f"Redis SL 필드 삭제 실패: {str(e)}")
        # 에러 처리 로직
        except Exception as e:
            logger.error(f"TP/SL 주문 생성 실패: {str(e)}")
            error_msg = map_exchange_error(e)
            await send_telegram_message(message=(f"⚠️ TP/SL 주문 생성 중 오류 발생\n"f"━━━━━━━━━━━━━━━\n"f"{error_msg}"),okx_uid=user_id,debug=True)
            traceback.print_exc()
            raise
    
    
    #--------------------------------
    # 포지션 청산
    #--------------------------------
    
    async def close_position(
        self,
        user_id: str,
        symbol: str,
        percent: Optional[float] = 100.0,
        size: Optional[float] = 0.0,
        qty: Optional[float] = 0.0,
        comment: str = "포지션 청산",
        side: Optional[str] = None
    ) -> bool:
        """
        포지션 청산 (전체 또는 부분)
        Args:
            user_id: 사용자 ID
            symbol: 거래 심볼
            percent: 청산할 비율 (1-100 사이의 값, 기본값 100)
            size: 계약 수량으로 입력
            qty: 수량으로 입력
            comment: 청산 코멘트
        """
        try:
            # 1. 현재 포지션 확인
            print("Close 1Position 호출됨")
            try:
                position = await self.get_current_position(user_id, symbol, side)
                print("position: ", position)
            except Exception as e:
                logger.error(f"포지션 조회 실패2: {str(e)}")
                return False
            current_price = None
            print("position: ", position)
            if position is None or position.contracts_amount == 0:
                logger.warning(f"[{user_id}]2 활성화된 포지션이 없습니다.")
                return False

            # 2. percent 유효성 검사 및 정규화
            if not percent:
                logger.info(f"[{user_id}] 청산 비율이 주어지지 않아 100%로 설정합니다")
                percent = 100.0
            if not 0 < percent <= 100:
                raise ValueError("청산 비율은 0보다 크고 100 이하여야 합니다")
            

            # 3. 청산할 수량 계산 (소수점 처리)
            close_contracts_amount = float(position.contracts_amount)
            close_position_qty = float(position.position_qty)   
            close_amount = round(close_contracts_amount * (percent / 100.0), 8)
            close_qty = round(close_position_qty * (percent / 100.0), 8)
            print(f"Position Size: {position.contracts_amount}, closing size: {close_amount}, closing qty: {close_qty}")
            if close_amount <= 0:
                logger.error(f"Invalid close size calculated: {close_amount}")
                return False

            # 4. 청산 주문 방향 결정
            side_to_close = "sell" if position.side == "long" else "buy"

            # 5. 현재가 및 손익 계산
            current_price = await self._get_current_price(symbol)
            pnl = position.position_qty * (current_price - position.entry_price) if position.side == "long" else \
                position.position_qty * (position.entry_price - current_price)

            # 6. 청산 실행
            try:
                # ccxt를 통한 직접 청산
                close_params = {
                    'reduceOnly': True,  # 포지션 감소만 허용
                    'tdMode': 'cross'    # 교차 마진 모드
                }
                
                # 헷지 모드 확인 및 설정
                position_mode = await self.client.fetch_position_mode(symbol=symbol)
                if position_mode.get('hedged', False):
                    close_params['posSide'] = 'long' if position.side == 'long' else 'short'
                contract_size = await self.get_contract_size(symbol)
                #close_size = round(close_size * contract_size, 8)
                # 거래소에 청산 주문 전송 (ccxt의 create_market_order 사용)
                
                try:
                    # 100% 청산을 위한 파라미터 추가
                    if percent >= 99:  # 전체 청산인 경우
                        close_params.update({
                            'tpTriggerPxType': 'last',
                            'sz': '100'  # 100%
                        })
                    
                    print(f"[symbol] : {symbol}, [side] : {side_to_close}, [amount] : {contract_size}, [params] : {close_params}")
                    close_order = await self.client.create_market_order(
                        symbol=symbol,
                        side=side_to_close,
                        amount=contract_size,
                        params=close_params
                    )
                    print(f"[close_order] : {close_order}")
                    await init_user_position_data(user_id, symbol, side_to_close)
                except Exception as e:
                    logger.error(f"청산 주문 실패: {str(e)}")
                    traceback.print_exc()
                    return False
                # 주문 상태 확인
                if not close_order:
                    logger.error(f"Order execution failed for user {user_id} on {symbol}")
                    return False

                # 주문 체결 확인을 위해 잠시 대기
                await asyncio.sleep(1)
                
                # 주문 상태 확인
                order_status = await self.client.fetch_order(close_order['id'], symbol)
                print(f"[order_status] : {order_status}")
                if order_status['status'] not in ['closed', 'filled']:
                    logger.error(f"Order not filled: {order_status['status']}")
                    return False

                # 7. Redis 데이터 업데이트
                position_key = f"user:{user_id}:position:{symbol}:{side_to_close}"
                if percent >= 99.5:  # 전체 청산
                    try:
                        keys_to_delete = [
                            position_key,
                            f"user:{user_id}:position:{symbol}:long:entry_price",
                            f"user:{user_id}:position:{symbol}:short:entry_price",
                            f"user:{user_id}:position:{symbol}:long:tp_data",
                            f"user:{user_id}:position:{symbol}:short:tp_data",
                            f"user:{user_id}:position:{symbol}:long:dca_levels",
                            f"user:{user_id}:position:{symbol}:short:dca_levels",
                            f"user:{user_id}:position:{symbol}:long:dca_count",
                            f"user:{user_id}:position:{symbol}:short:dca_count",
                            f"user:{user_id}:position:{symbol}:main_position_direction"
                        ]
                        await redis_client.delete(*keys_to_delete)
                    except Exception as e:
                        logger.error(f"Redis 데이터 삭제 실패: {str(e)}")
                        await send_telegram_message(f"[{user_id}]⚠️ Redis 데이터 삭제 실패\n"f"━━━━━━━━━━━━━━━\n"f"{str(e)}", okx_uid=user_id, debug=True)
                else:  # 부분 청산
                    remaining_contracts_amount = round(float(position.contracts_amount) - float(close_amount), 8)
                    remaining_position_qty = round(float(position.position_qty) - float(close_qty), 8)
                    if remaining_contracts_amount > 0:
                        await redis_client.hset(
                            position_key,
                            mapping={
                                "side": position.side,
                                "size": str(remaining_contracts_amount),
                                "contracts_amount": str(remaining_contracts_amount),
                                "position_qty": str(remaining_position_qty),
                                "entry_price": str(position.entry_price),
                                "leverage": str(position.leverage)
                            }
                        )
                    else:
                        await redis_client.delete(position_key)
                        await send_telegram_message(
                            f"[{user_id}]⚠️ 특이 경과 확인\n"
                            f"━━━━━━━━━━━━━━━\n"
                            f"특이 경과 확인", okx_uid=user_id, debug=True
                        )
                        
                await cancel_algo_orders(user_id = user_id, symbol = symbol, side = side, algo_type="trigger")
                # 실제 체결가 업데이트
                executed_price = float(order_status.get('average', current_price))
                await update_trade_history_exit(
                    user_id=user_id,
                    symbol=symbol,
                    order_id=position.order_id,
                    exit_price=executed_price,
                    pnl=pnl,
                    close_type="TP" if "TP" in comment else "SL" if "SL" in comment else "시장가",
                    comment=comment,
                    percent_closed=percent
                    )
                # 8. 성공 메시지 전송
                close_type = "🎯 익절 체결" if "TP" in comment else "🛑 손절 체결" if "SL" in comment else "📊 포지션 종료"
                if "트랜드" in comment:
                    close_type = "트랜드 반전 포지션 종료"
                success_msg = (
                    f"{close_type} \n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"심볼: {symbol}\n"
                    f"방향: {'롱' if position.side == 'long' else '숏'}\n"
                    f"종료 가격: {executed_price:.2f}\n"
                    f"수량: {close_qty}\n"
                    f"손익: {'🟢' if pnl > 0 else '🔴' if pnl < 0 else ''} {abs(pnl):.2f} USDT"
                )
                if comment != "최소 수량 미만 포지션 청산":
                    await send_telegram_message(success_msg, user_id)
                
                main_direction_key = f"user:{user_id}:position:{symbol}:main_position_direction"
                main_direction = side_to_close
                if await redis_client.exists(main_direction_key):
                    main_direction = await redis_client.get(main_direction_key)
                if side_to_close == main_direction:
                    await redis_client.delete(f"user:{user_id}:position:{symbol}:main_position_direction")
                    await redis_client.set(f"user:{user_id}:position:{symbol}:position_state", 0)
                else:
                    await redis_client.delete(f"user:{user_id}:position:{symbol}:hedging_position_direction")
                    #await redis_client.set(f"user:{user_id}:position:{symbol}:position_state", 0)
                    
                #monitor key
                    
                settings_key = f"user:{user_id}:settings"
                settings_str = await redis_client.get(settings_key)
                settings = json.loads(settings_str) if settings_str else {}

                use_cooldown = settings.get("use_cooldown")
                cooldown_time = settings.get("cooldown_time")
                if use_cooldown == 'true' or cooldown_time > 0 or cooldown_time is None:
                    cooldown_key = f"user:{user_id}:cooldown:{symbol}:{side_to_close}"
                    await redis_client.set(cooldown_key, "true", ex=cooldown_time)
                # 9. 로깅
                logger.info(
                    f"Position close successful - "
                    f"user={user_id}, symbol={symbol}, "
                    f"percent={percent}%, size={close_amount}, "
                    f"comment={comment}, order_result={close_order}"
                )
                return True

            except Exception as e:
                error_msg = map_exchange_error(e)
                logger.error(f"청산 주문 실패: {str(e)}")
                await send_telegram_message(
                    message=
                    f"⚠️ 청산 주문 실패\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"{error_msg}\n"
                    f"시도 정보:\n"
                    f"심볼: {symbol}\n"
                    f"방향: {'롱' if position.side == 'long' else '숏'}\n"
                    f"수량: {close_qty}\n"
                    f"현재가: {current_price:.2f}",
                    okx_uid=user_id,
                    debug=True
                )
                return False

        except Exception as e:
            logger.error(f"Position close failed - user={user_id}, symbol={symbol}, error={str(e)}")
            raise
    
    
    async def get_user_api_keys(self, user_id: str) -> Dict[str, str]:
        """
        사용자 ID를 기반으로 Redis에서 OKX API 키를 가져오는 함수
        """
        try:
            api_key_format = f"user:{user_id}:api:keys"
            #print(api_key_format)
            api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
            #print(api_keys)
            if not api_keys:
                raise HTTPException(status_code=404, detail="API keys not found in Redis")
            return api_keys
        except Exception as e:
            
            logger.error(f"3API 키 조회 실패: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error fetching API keys: {str(e)}")


    async def fetch_with_retry(self, exchange, symbol: str, max_retries: int = 3) -> Optional[list]:
        for attempt in range(max_retries):
            try:
                positions = await exchange.fetch_positions([symbol], params={
                    'instType': 'SWAP'
                })
                return positions
            except Exception as e:
                wait_time = (2 ** attempt)  # 1초, 2초, 4초
                logger.warning(f"Attempt {attempt + 1}/{max_retries} failed for {symbol}. "
                            f"Retrying in {wait_time}s... Error: {str(e)}")
                
                if attempt == max_retries - 1:  # 마지막 시도였다면
                    logger.error(f"All retry attempts failed for {symbol}: {str(e)}")
                    raise  # 마지막 에러를 그대로 전파
                
                await asyncio.sleep(wait_time)
        return None

    def get_redis_keys(user_id: str, symbol:str, side:str) -> dict:
        """사용자별 Redis 키 생성"""
        return {
            'api_keys': f"user:{user_id}:api:keys",
            'trading_status': f"user:{user_id}:trading:status",
            'positions': f"user:{user_id}:position:{symbol}:{side}",
            'settings': f"user:{user_id}:settings"
        }
        
        #TODO : 면밀히 로직 체크해야함. 
    async def fetch_okx_position(self, user_id: str, symbol: str, side: str=None, user_settings: dict=None, debug_entry_number: int=9) -> dict:
        """
        - user_id에 대응하는 ccxt.okx 클라이언트(캐시) 획득
        - 해당 심볼의 포지션을 ccxt 'fetch_positions()'로 조회
        - symbol과 정확히 매칭되는 포지션을 찾아 dict 형태로 반환
        (포지션이 없으면 Redis에서 삭제 후, 빈 dict 반환)
        Args:
            user_id (str): 사용자 ID
            symbol (str): 심볼 (예: 'BTC/USDT:USDT')

        Returns:
            dict: 포지션 정보. 포지션이 없으면 빈 딕셔너리 반환
        """
        #print("request : ", user_id, symbol, side)
        exchange = None
        fail_to_fetch_position = False
        fetched_redis_position = False
        try:
            api_keys = await self.get_user_api_keys(user_id)
            # ✅ OrderWrapper 사용 (ORDER_BACKEND 자동 감지)
            from HYPERRSI.src.trading.services.order_wrapper import OrderWrapper
            exchange = OrderWrapper(user_id, api_keys)

            position_state_key = f"user:{user_id}:position:{symbol}:position_state"
            current_state = await redis_client.get(position_state_key)
            
            try:
                position_state = int(current_state) if current_state is not None else 0
            except (TypeError, ValueError):
                position_state = 0  # 변환 실패시 기본값 0

            # 1) 실제 포지션 가져오기
            try:
                positions = await self.fetch_with_retry(exchange, symbol)
                #print("positions!!!!!!: ", positions)
                #여기서 들어오는 positioin은, ccxt를 통한 객체 응답.
                if exchange is not None:
                    await exchange.close()
            except ccxt.OnMaintenance as e:
                raise HTTPException(
                        status_code=503,
                        detail="거래소가 현재 유지보수 중입니다. 잠시 후 다시 시도해주세요."
                    )
            except ccxt.AuthenticationError as e:
                logger.error(f"[{user_id}] Authentication error for {symbol}: {str(e)}")
                # Call stop() for authentication errors
                
                is_running = False
                await redis_client.set(f"user:{user_id}:trading:status", str(is_running))
                # Close the exchange connection if it's open
                if exchange is not None:
                    await exchange.close()
                return {}
            except Exception as e:
                logger.error(f"Error in fetch_okx_position for {symbol}: {str(e)}")
                traceback.print_exc()
                try:
                    if side is None:
                        positions_long = await redis_client.hgetall(f"user:{user_id}:position:{symbol}:long")
                        positions_short = await redis_client.hgetall(f"user:{user_id}:position:{symbol}:short")
                        positions = {**positions_long, **positions_short}
                        return positions
                    else:
                        positions = await redis_client.hgetall(f"user:{user_id}:position:{symbol}:{side}")
                        return positions
                except Exception as e:
                    logger.error(f"Error in fetch_okx_position for {symbol}: {str(e)}")
                    traceback.print_exc()
                    fail_to_fetch_position = True
                    fetched_redis_position = True
                fail_to_fetch_position = True
            #print("positions: ", positions)
            # 2) 포지션이 없는 경우 모든 side의 포지션 키 삭제
            
            if not positions:
                for side in ['long', 'short']:
                    position_key = f"user:{user_id}:position:{symbol}:{side}"
                    dca_count_key = f"user:{user_id}:position:{symbol}:{side}:dca_count"
                    await redis_client.set(dca_count_key, "0")
                    await redis_client.set(position_state_key, "0")
                    await redis_client.delete(position_key)
                logger.error(f"[{user_id}] 포지션 없음. Redis 데이터 삭제.")
                await send_telegram_message(f"[{user_id}] [{debug_entry_number}] 포지션 없음. Redis 데이터 삭제. 여기서 아마 경합 일어날 가능성 있으니, 실제로 어떻게 된건지 체크.", debug = True)
                #return {}

            #for pos in positions:
            #    print("개별 position 데이터:", pos)
            #    print("side 값:", pos.get('side')) #<--이렇게 side값 제대로 나오는 것 확인. 
            # 3) 각 포지션 처리
            if fail_to_fetch_position:
                if fetched_redis_position:
                    return positions
                else:
                    return {}
            result = {}
            active_positions = [pos for pos in positions if float(pos.get('info', {}).get('pos', 0)) > 0]
            #print(f"[{user_id}]sActive Position 갯수 : {len(active_positions)}")
            for pos in active_positions:
                if pos['info']['instId'] != symbol:
                    continue
                side = (pos.get('info', {}).get('posSide') or '').lower()
                if side == 'net':
                    side = (pos.get('side') or '').lower()
                if side not in ['long', 'short']:
                    continue
                # 계약 수량과 계약 크기를 곱해 실제 포지션 크기를 계산
                contracts = abs(safe_float(pos.get('contracts', 0) or 0))

                contract_size = safe_float(pos.get('contractSize', 1.0) or 1.0)
                if contracts == 0:
                    contracts = abs(safe_float(pos.get('contracts_amount', 0) or 0))
                    if contracts == 0:
                        contracts = abs(safe_float(pos.get('size', 0) or 0))
                #02 05 15:16 수정 -> 이미 contracts가 , 바로 계약수량으로 들어옴. 그래서 이걸로 바로 size를 씀. 
                position_qty = contracts * contract_size
                contracts_amount = contracts
                #print(f"contracts: {contracts}, contract_size: {contract_size}, position_qty: {position_qty}") #<-- 문제 없음. 
                #print(f"position_qty: {position_qty}, contracts: {contracts}") #<-- 제대로 들어옴. 실제 물량 그대로 
                #print(f"position_qty: {position_qty}") #<-- 제대로 들어옴. 실제 물량 그대로 
                dca_count_key = f"user:{user_id}:position:{symbol}:{side}:dca_count"
                dca_count = await redis_client.get(dca_count_key)
                
                try:
                    if contracts > 0:
                        position_key = f"user:{user_id}:position:{symbol}:{side}"
                        if dca_count == "1":
                            last_entry_size = contracts_amount
                        else:
                            # DCA 진입이 2회 이상인 경우, 가장 최근 진입 크기 계산
                            # 1) Redis에서 이전 포지션 크기 가져오기
                            previous_contracts = await redis_client.hget(position_key, 'contracts_amount')
                            if previous_contracts:
                                previous_contracts = safe_float(previous_contracts)
                                # 현재 포지션에서 이전 포지션을 빼서 최근 추가된 물량 계산
                                last_entry_size = contracts_amount - previous_contracts
                                if last_entry_size <= 0:
                                    # 음수이거나 0인 경우, DCA 배수로 추정 계산
                                    previous_last_entry = await redis_client.hget(position_key, 'last_entry_size')
                                    if previous_last_entry:
                                        scale = 0.5  # 기본 DCA 배수
                                        last_entry_size = safe_float(previous_last_entry) * scale
                                    else:
                                        # 데이터가 없으면 현재 포지션을 DCA 횟수로 나눈 평균값 사용
                                        last_entry_size = contracts_amount / max(safe_float(dca_count or 1), 1)
                            else:
                                # 이전 데이터가 없으면 entry_multiplier를 사용해서 역산으로 계산
                                if user_settings is None:
                                    settings_str = await redis_client.get(f"user:{user_id}:settings")
                                    if settings_str:
                                        try:
                                            user_settings = json.loads(settings_str)
                                        except json.JSONDecodeError:
                                            user_settings = {}
                                    else:
                                        user_settings = {}
                                entry_multiplier = safe_float(user_settings.get('entry_multiplier', 0.5))
                                dca_count_int = int(dca_count) if dca_count else 1
                                
                                # n회차의 last_entry_size = 초기진입 * entry_multiplier * (n-1)
                                # 1회차: 초기진입
                                # 2회차: 초기진입 * entry_multiplier  
                                # 3회차: 초기진입 * entry_multiplier * 2
                                # n회차: 초기진입 * entry_multiplier * (n-1)
                                
                                # 총 포지션 = 초기진입 + 초기진입*entry_multiplier + 초기진입*entry_multiplier*2 + ... + 초기진입*entry_multiplier*(n-1)
                                # 총 포지션 = 초기진입 * (1 + entry_multiplier + entry_multiplier*2 + ... + entry_multiplier*(n-1))
                                # 총 포지션 = 초기진입 * (1 + entry_multiplier * (1 + 2 + ... + (n-1)))
                                # 총 포지션 = 초기진입 * (1 + entry_multiplier * (n-1)*n/2)
                                
                                arithmetic_sum = 1 + entry_multiplier * (dca_count_int - 1) * dca_count_int / 2
                                initial_entry = contracts_amount / arithmetic_sum
                                
                                # n회차의 진입 크기 = 초기진입 * entry_multiplier * (n-1)
                                if dca_count_int == 1:
                                    last_entry_size = initial_entry
                                elif dca_count_int > 1:
                                    last_entry_size = initial_entry * entry_multiplier * (dca_count_int - 1)
                                else:
                                    last_entry_size = 0
                        
                        leverage = safe_float(pos['leverage'])
                        #print(f"leverage: {leverage}")
                        # 기존 tp_data와 sl_data 보존
                        existing_data = await redis_client.hgetall(position_key)
                        existing_tp_data = existing_data.get('tp_data')
                        existing_sl_data = existing_data.get('sl_data')
                        
                        mapping = {
                            'symbol': pos['symbol'],
                            'side': side,
                            'size': str(contracts_amount),  # 이미 절댓값 처리된 contracts 사용
                            'contracts': str(contracts_amount),
                            'contract_size': str(contract_size),
                            'contracts_amount': str(contracts_amount),
                            'position_qty': str(position_qty),
                            'entry_price': str(pos.get('entryPrice') or pos.get('average') or 0.0),
                            'leverage': str(leverage),
                            'unrealized_pnl': str(pos.get('unrealizedPnl', 0.0)),
                            'liquidation_price': str(pos.get('liquidationPrice') or '0.0'),
                            'margin_mode': pos.get('marginMode', 'cross'),
                            'mark_price': str(pos.get('markPrice', 0.0)),
                            'dca_count': str(dca_count),
                            'last_entry_size': str(last_entry_size),
                            'last_update_time': str(int(time.time())),
                            'last_update_time_kr': str(datetime.now(pytz.timezone('Asia/Seoul')).strftime('%Y-%m-%d %H:%M:%S'))
                        }
                        
                        # 기존 tp_data와 sl_data가 있으면 보존
                        if existing_tp_data and existing_tp_data != '[]':
                            mapping['tp_data'] = existing_tp_data
                        if existing_sl_data and existing_sl_data != '{}':
                            mapping['sl_data'] = existing_sl_data

                        await redis_client.hset(position_key, mapping=mapping)
                        result[side] = mapping

                        #logger.debug(f"포지션 업데이트 - {side}: {mapping}")
                    else:
                        # contracts가 0인 경우 해당 side의 포지션 삭제
                        await init_user_position_data(user_id, symbol, side)
                        position_key = f"user:{user_id}:position:{symbol}:{side}"
                        await redis_client.delete(position_key)
                        dca_count_key = f"user:{user_id}:position:{symbol}:{side}:dca_count"
                        await redis_client.set(dca_count_key, "0")
                        await send_telegram_message(f"[{user_id}] contracts가 0인 경우여서, 해당 Side의 포지션을 삭제하는데, 정상적이지 않은 로직. 체크 필요", debug=True)
                except Exception as e:
                    logger.error(f"포지션 업데이트 실패 ({symbol}): {str(e)}")
                    await send_telegram_message(f"[{user_id}] Fetching Position에서 에러 발생.\n에러 내용 : {e}", debug = True)

            # result 딕셔너리에는 side별 mapping이 있음.
            long_exists = 'long' in result and float(result['long'].get('position_qty', 0)) > 0
            short_exists = 'short' in result and float(result['short'].get('position_qty', 0)) > 0

            # position_state 업데이트 로직
            if position_state > 1 and (not long_exists) and short_exists:
                position_state = -1
            elif position_state < -1 and (not short_exists) and long_exists:
                position_state = 1
            elif position_state != 0 and (not long_exists and not short_exists):
                position_state = 0

            # Redis에 업데이트된 position_state 저장
            await redis_client.set(position_state_key, str(position_state))
     
            # ==============================

            return result

        except Exception as e:
            logger.error(f"포지션 조회 실패3 ({symbol}): {str(e)}")
            traceback.print_exc()   
            # 에러 발생시 양쪽 포지션 모두 조회
            result = {}
            for side in ['long', 'short']:
                position_key = f"user:{user_id}:position:{symbol}:{side}"
                position_data = await redis_client.hgetall(position_key)
                if position_data:
                    result[side] = position_data
            return result
        finally:
            # 이 인스턴스에 대해서만 리소스 해제
            if exchange is not None:
                await exchange.close()
    
    async def get_atr_value(self, symbol: str, timeframe: str = "1m", current_price: float = None) -> float:
        """
        - 주어진 심볼에 대한 ATR 값을 조회
        - 캐시된 ATR 값이 있는 경우 캐시에서 가져오고, 없는 경우 OKX API로 조회
        - 조회된 ATR 값을 반환
        """
        try:
            tf_str = get_timeframe(timeframe)
            candle_key = f"candles_with_indicators:{symbol}:{tf_str}"
            candle_data = await redis_client.lindex(candle_key, -1)
            if candle_data:
                candle_json = json.loads(candle_data)
                atr_value = float(candle_json.get('atr14', 0.0))
                if atr_value is None or atr_value <= current_price * 0.001:
                    atr_value = current_price * 0.001
                return atr_value if atr_value > 0 else 0.0
            else:
                return 0.0
        except Exception as e:
            logger.error(f"Failed to get ATR value for {symbol}: {str(e)}")
            return 0.0
    
    async def get_historical_prices(self, symbol: str, timeframe: str, limit: int=200) -> pd.DataFrame:
        """Redis에서 과거 데이터(캔들+인디케이터) 가져오기 (샘플)"""
        try:
            tf_str = get_timeframe(timeframe)
            candles_key = f"candles_with_indicators:{symbol}:{tf_str}"
            cached_data = await redis_client.lrange(candles_key, -limit, -1)
            if cached_data:
                df = pd.DataFrame([
                    {
                        'timestamp': pd.to_datetime(json.loads(item)['timestamp'], unit='s'),
                        'open': float(json.loads(item)['open']),
                        'high': float(json.loads(item)['high']),
                        'low': float(json.loads(item)['low']),
                        'close': float(json.loads(item)['close']),
                        'volume': float(json.loads(item)['volume'])
                    }
                    for item in cached_data
                ])
                if not df.empty:
                    df.set_index('timestamp', inplace=True)
                    df.sort_index(inplace=True)
                return df
            else:
                # 없으면 OKX API로 추가 조회 (생략)
                return pd.DataFrame()
        except Exception as e:
            logger.error(f"과거 가격 데이터 조회 실패: {str(e)}")
            print(traceback.format_exc())
            return pd.DataFrame()

    async def get_order_status(self, *, user_id: str, order_id: str, symbol: str) -> dict:
        """
        주어진 주문 ID에 대해 주문 상태를 조회합니다.
        OKX API (ccxt의 fetch_order)를 활용하여 주문 상태를 가져오며,
        주문 상태 딕셔너리 예시:
          {
              "order_id": order_id,
              "status": "filled" or "open" or "error",
              "filled_size": <float>,
              "avg_fill_price": <float>
          }
        """
        try:
            # OKX API를 통해 주문 상태 조회
            order_status = await self.client.fetch_order(order_id, symbol)
            # 주문 상태 값은 상황에 따라 다를 수 있으므로, 필요한 필드를 추출합니다.
            status = order_status.get("status", "unknown")
            filled_size = safe_float(order_status.get("filled_size", order_status.get("filled", 0.0)))
            avg_fill_price = safe_float(order_status.get("avg_fill_price", order_status.get("average", 0.0)))
            return {
                "order_id": order_id,
                "status": status,
                "filled_size": filled_size,
                "avg_fill_price": avg_fill_price,
            }
        except Exception as e:
            logger.error(f"get_order_status() error for order {order_id}: {str(e)}")
            # 필요 시 traceback.print_exc()도 추가할 수 있습니다.
            return {
                "order_id": order_id,
                "status": "error",
                "error": str(e)
            }


    async def check_rsi_signals(self, rsi_values: list, rsi_settings: dict) -> dict:
        """RSI 신호 확인 로직"""
        try:
            # RSI 값 유효성 검사
            if not rsi_values or len(rsi_values) < 2:
                logger.warning("충분한 RSI 데이터가 없습니다.")
                return {
                    'rsi': None,
                    'is_oversold': False,
                    'is_overbought': False
                }
            
            # 현재 RSI와 이전 RSI 값
            current_rsi = rsi_values[-1]
            previous_rsi = rsi_values[-2]
            
            print(f"current_rsi: {current_rsi}, previous_rsi: {previous_rsi}, rsi settings: {rsi_settings}")
            
            # 진입 옵션에 따른 처리
            entry_option = rsi_settings.get('entry_option', '')
            rsi_oversold = rsi_settings['rsi_oversold']
            rsi_overbought = rsi_settings['rsi_overbought']
            
            is_oversold = False
            is_overbought = False
            
            if entry_option == '돌파':
                # 롱: crossunder the rsi_oversold
                is_oversold = previous_rsi > rsi_oversold and current_rsi <= rsi_oversold
                
                # 숏: crossunder the rsi_overbought
                is_overbought = previous_rsi < rsi_overbought and current_rsi >= rsi_overbought
                
            elif entry_option == '변곡돌파':
                # 롱: crossover the rsi_oversold
                is_oversold = current_rsi < rsi_oversold and previous_rsi >= rsi_oversold
                
                # 숏: crossover the rsi_overbought
                is_overbought = current_rsi > rsi_overbought and previous_rsi <= rsi_overbought
                
            elif entry_option == '초과':
                # 롱: current_rsi > rsi_oversold
                is_oversold = current_rsi < rsi_oversold
                # 숏: current_rsi < rsi_overbought
                is_overbought = current_rsi > rsi_overbought
                
            else:
                # 기본 동작 (기존 코드와 동일)
                is_oversold = current_rsi < rsi_oversold
                is_overbought = current_rsi > rsi_overbought
            
            return {
                'rsi': current_rsi,
                'is_oversold': is_oversold,
                'is_overbought': is_overbought
            }
        except Exception as e:
            logger.error(f"RSI 신호 확인 중 오류 발생: {str(e)}", exc_info=True)
            return {
                'rsi': None,
                'is_oversold': False,
                'is_overbought': False
            }

    async def cleanup(self):
        """인스턴스 정리 및 클라이언트 반환"""
        if hasattr(self, 'client') and self.client:
            # 클라이언트가 존재하면 닫기
            try:
                # ccxt 클라이언트의 경우 close 메소드 호출
                if hasattr(self.client, 'close'):
                    await self.client.close()
                # 그렇지 않은 경우 - 이미 컨텍스트 매니저로 관리되었으므로 추가 작업 필요 없음
                self.client = None
                logger.info(f"Client cleanup completed for user {self.user_id}")
            except Exception as e:
                logger.error(f"Error during client cleanup: {e}")

    # ─────────────────────────────────────────────────────────
    # 주문/체결 관련 보조 메서드
    # ─────────────────────────────────────────────────────────




    async def _cancel_order(
        self,
        user_id: str,
        symbol: str,
        order_id: str = None,
        side: str = None,
        order_type: str = None  # 'limit' | 'market' | 'stop_loss' | 'take_profit' 등
    ) -> None:
        """
        OKX에서 지정된 order_id의 주문을 취소합니다.
        order_type 등을 통해 일반 주문 / Algo 주문 취소를 분기 처리합니다.
        """
        try:
            print("호출 1")
            print(f"[취소주문 {user_id}] : side : {side}, order_id : {order_id}, order_type : {order_type}")
        
            exchange = None
            api_keys = await self.get_user_api_keys(user_id)
            # ✅ OKX 클라이언트 생성
            exchange = ccxt.okx({
                'apiKey': api_keys.get('api_key'),
                'secret': api_keys.get('api_secret'),
                'password': api_keys.get('passphrase'),
                'enableRateLimit': True,
                'options': {'defaultType': 'swap'}
            })

            # 1) OKX 심볼(InstID) 변환 로직
            #    예: 'BTC/USDT:USDT' -> 'BTC-USDT-SWAP'
            #inst_id = convert_symbol_to_okx_instrument(symbol)
            
            # 2) Algo 주문인지 여부를 order_type이나 order_id 저장방식으로 판단
            #    예: order_type이 'stop_loss'나 'take_profit'이면 algo 취소로 분기
            is_algo_order = order_type in ('stop_loss', 'trigger', 'conditional', 'stopLoss')
            
            if is_algo_order:
                # ---- Algo 주문 취소 ----
                # 1) CCXT의 cancelOrder()로 시도 (가능한 버전도 있음)
                #    안 될 경우 private_post_trade_cancel_algos() 직접 호출

                # (1) cancelOrder() 시도
                try:
                    api_keys = await self.get_user_api_keys(user_id)
                    trigger_cancel_client = TriggerCancelClient(
                        api_key=api_keys.get('api_key'),
                        secret_key=api_keys.get('api_secret'),
                        passphrase=api_keys.get('passphrase')
                    )
                    # OKX에서는 cancelOrder() 파라미터가 독특하여 algoId로 전달
                    await trigger_cancel_client.cancel_all_trigger_orders(inst_id = symbol, side = side, algo_type = "trigger", user_id = user_id)
                    logger.info(f"Canceled algo order {order_id} for {symbol}")
                except Exception as e:
                    # (2) cancelOrder()가 안 된다면 private_post_trade_cancel_algos() 직접 호출
                    logger.warning(f"[{user_id}] cancelOrder() failed for algo; trying private_post_trade_cancel_algos. Err={str(e)}")
                    try:
                        await exchange.private_post_trade_cancel_algos({
                            "algoId": [order_id],  # 배열로 multiple IDs 가능
                            "instId": symbol
                        })
                        logger.info(f"Canceled algo order via private_post_trade_cancel_algos: {order_id}")
                    except Exception as e2:
                        logger.error(f"Failed to cancel algo order {order_id} via both ways. {str(e2)}")
                        raise

            else:
                # ---- 일반 주문 취소 ----
                await exchange.cancelOrder(order_id, symbol)
                logger.info(f"Canceled normal order {order_id} for {symbol}")

        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {str(e)}")
            raise
        finally:
            if exchange is not None:
                await exchange.close()

    async def cancel_all_open_orders(self, exchange, symbol, user_id, side: str = None):
        try:
            # 먼저 미체결 주문들을 가져옵니다
            print(f"취소할 주문 조회: {symbol}, side: {side}")
            open_orders = await exchange.fetch_open_orders(symbol)
                    # side로 필터링
            if side:
                open_orders = [order for order in open_orders if order['side'].lower() == side.lower()]
            
            len_open_orders = len(open_orders)
            print(f"미체결 주문 수: {len_open_orders}")
            try:
                api_keys = await self.get_user_api_keys(user_id)
                trigger_cancel_client = TriggerCancelClient(
                    api_key=api_keys.get('api_key'),
                    secret_key=api_keys.get('api_secret'),
                    passphrase=api_keys.get('passphrase')
                )
                await trigger_cancel_client.cancel_all_trigger_orders(inst_id = symbol, side = side, algo_type = "trigger", user_id = user_id)
            except Exception as e:
                logger.error(f"Failed to cancel trigger orders: {str(e)}")

                # 취소 요청 리스트를 만듭니다
            if len(open_orders) > 0:
                cancellation_requests = [
                    {
                        "id": order['id'],
                        "symbol": order['symbol'],
                        "clientOrderId": order.get('clientOrderId')  # clientOrderId가 있는 경우 포함
                    }
                    for order in open_orders
                ]

                if len(cancellation_requests) > 0:
                    # 한번에 모든 주문을 취소합니다
                # 일반 주문 취소
                    response = await exchange.cancel_orders_for_symbols(cancellation_requests)
                    #print(f"취소 응답: {response}")



                # 취소된 주문들을 Redis에 저장
                closed_orders_key = f"user:{user_id}:closed_orders"
                
                # 리스트로 저장
                for order in open_orders:
                    await redis_client.rpush(closed_orders_key, json.dumps(order))

                # 열린 주문 목록 삭제
                await redis_client.delete(f"user:{user_id}:open_orders")
                
                return True
            else:
                print("미체결 주문이 없습니다.")
                return True
        except Exception as e:
            logger.error(f"Failed to cancel all open orders: {str(e)}")
            return False


    async def _try_send_order(
        self, 
        user_id: str, 
        symbol: str, 
        side: str, 
        size: float, 
        leverage: float = None, 
        order_type: str = 'market',
        price: float = None,
        trigger_price: float = None,
        direction: Optional[str] = None
    ) -> OrderStatus:
        debug_order_params = { 
            'symbol': symbol,
            'side': side,
            'size': size,
            'leverage': leverage,
            'order_type': order_type,
            'price': price,
            'trigger_price': trigger_price,
            'direction': direction
        }
        #print("try_send_order 파라미터: ", debug_order_params)
        try:
            exchange = self.client
            order_status = await try_send_order(user_id = user_id, symbol = symbol, side = side, size = size, leverage = leverage, order_type = order_type, price = price, trigger_price = trigger_price, direction = direction, exchange = exchange)
            return order_status
        except Exception as e:
            logger.error(f"Failed to send order: {str(e)}")
            raise

    async def _store_order_in_redis(self, user_id: str, order_state: OrderStatus):
        """
        open_orders 리스트/해시 등으로 관리 (여기서는 리스트 예시)
        - key: user:{user_id}:open_orders
        - value: JSON (OrderStatus)
        """
        redis_key = f"user:{user_id}:open_orders"
        existing = await redis_client.get(f"open_orders:{user_id}:{order_state.order_id}")
        if existing:
            return
        order_data = {
            "order_id": order_state.order_id,
            "symbol": order_state.symbol,
            "side": order_state.side,
            "size": order_state.size,
            "filled_size": order_state.filled_size,
            "status": order_state.status,
            "avg_fill_price": order_state.avg_fill_price,
            "create_time": order_state.create_time.isoformat(),
            "update_time": order_state.update_time.isoformat(),
            "order_type": order_state.order_type,
            "posSide": order_state.posSide
        }
        # 간단히 lpush
        await redis_client.lpush(redis_key, json.dumps(order_data))
        # 실제 운영 시 "open_orders"에서 상태가 확정된 주문(= filled or canceled 등)은 제거하거나 별도 리스트에 옮기는 식으로 관리

    async def monitor_orders(self, user_id: str):
        """
        - 폴링 기반으로 'open_orders' 목록을 조회
        - 각 주문의 최신 상태(체결량, 가격, 상태)를 API로 확인
        - Redis 업데이트: open 주문과 closed 주문을 별도의 키로 관리
        """
        open_key = f"user:{user_id}:open_orders"
        closed_key = f"user:{user_id}:closed_orders"  # 종료된 주문을 저장할 새로운 Redis 키

        open_orders = await redis_client.lrange(open_key, 0, -1)
        #if not open_orders:
        #    print(f"DEBUG: open_orders -> {open_orders}")
        #    return  # 열려있는 주문이 없음

        new_open_list = []   # 계속 open 상태인 주문들
        closed_list = []     # 종료(closed)된 주문들

        #print("len(open_orders1): ", len(open_orders))
        for data in open_orders:
            try:
                order_json = json.loads(data)
                order_id = order_json['order_id']
                symbol = order_json['symbol']
                order_type = order_json.get('order_type', '')
                is_algo = order_type in ['stop_loss']
                try:
                    if is_algo:
                        # 알고리즘 주문 조회
                        try:
                            latest = await self.client.fetch_order(order_id, symbol, params={'stop': True, 'ordType': 'trigger'})
                            #print("order_data: ", latest)
                            # 응답 구조가 다르므로 데이터 매핑
                            if latest.get('data') and len(latest['data']) > 0:
                                algo_order = latest['data'][0]
                                latest = {
                                    'status': algo_order.get('state', 'open'),
                                    'filled_size': float(algo_order.get('sz', 0)),
                                    'avg_fill_price': float(algo_order.get('avgPx', 0))
                                }
                                if latest.get('status') in ["closed", "canceled", "error", "rejected"]:
                                    closed_list.append(json.dumps(order_json))

                        except Exception as e:
                            logger.error(f"알고주문 조회 실패: {str(e)}")
                            new_open_list.append(data)  # 조회 실패 시 기존 데이터 유지
                            continue  # 다음 주문으로 넘어감
                    else:
                        try:
                            # 일반 주문 조회
                            latest = await self.client.fetch_order(order_id, symbol)
                        except Exception as e:
                            logger.error(f"일반 주문 조회 실패: {str(e)}")
                            new_open_list.append(data)  # 조회 실패 시 기존 데이터 유지
                            continue  # 다음 주문으로 넘어감
                except Exception as e:
                    logger.error(f"주문 조회 실패: {str(e)}")
                    new_open_list.append(data)  # 조회 실패 시 기존 데이터 유지
                    continue  # 다음 주문으로 넘어감

                # 최신 주문 정보 예시: {'status': 'partially_filled', 'filled_size': '0.02', 'avg_fill_price': '19000.0', ...}
                filled_size = float(latest.get('filled_size', 0.0))
                avg_fill_price = float(latest.get('avg_fill_price', 0.0))
                status = latest.get('status', 'open')

                order_json['filled_size'] = filled_size
                order_json['avg_fill_price'] = avg_fill_price
                order_json['status'] = status
                order_json['update_time'] = datetime.now().isoformat()

                if status in ("filled", "canceled", "error", "closed", "rejected"):
                    # 종료된 주문은 open_orders 목록에서 제거하고 closed_orders로 옮김
                    logger.info(f"[monitor_orders] Order {order_id} -> {status}. Moving to closed_orders.")
                    closed_list.append(json.dumps(order_json))
                else:
                    # 여전히 open 또는 partially_filled 인 경우, open 주문 목록에 유지
                    new_open_list.append(json.dumps(order_json))
            except Exception as ex:
                logger.error(f"[monitor_orders] 주문 상태 업데이트 오류: {str(ex)}")
                traceback.print_exc()
                # 문제 발생 시 원본 데이터를 유지
                new_open_list.append(data)

        #print(f"new_open_list: {new_open_list}")

        # open_orders 키 업데이트: 기존 데이터를 삭제하고 새로 open 상태인 주문들만 추가
        await redis_client.delete(open_key)
        for item in new_open_list:
            await redis_client.rpush(open_key, item)
        #print(f"open_orders updated in key: {open_key}")

        # closed_orders 키에 종료된 주문 추가 (기존 데이터와 합칠지, 새로 저장할지는 비즈니스 로직에 맞게 결정)
        if closed_list:
            for item in closed_list:
                await redis_client.rpush(closed_key, item)
            logger.info(f"[{user_id}] Closed orders moved to key: {closed_key}")
            
    async def close(self):
        """클라이언트 리소스 정리"""
        try:
            if self.client is not None:
                # ccxt exchange 인스턴스 정리
                await self.client.close()
                self.client = None
                
            logger.debug(f"Trading service closed for user {self.user_id}")
        except Exception as e:
            logger.error(f"Error closing trading service: {e}")

    


    async def get_contract_info(
        self,
        symbol: str,
        user_id: str = None,
        size_usdt: float = None,
        leverage: float = None,
        current_price: Optional[float] = None
    ) -> dict:
        """
        주어진 심볼의 계약 정보를 조회하고 계약 수량을 계산합니다.
        
        Args:
            user_id: 사용자 ID
            symbol: 거래 심볼 (예: "BTC-USDT-SWAP")
            size: 주문 금액
            leverage: 레버리지
            current_price: 현재가 (None이면 자동으로 조회)
            
        Returns:
            dict: {
                "symbol": str,
                "contractSize": float,  # 계약 단위
                "contracts_amount": float,      # 계산된 계약 수량
                "minSize": float,       # 최소 주문 수량
                "tickSize": float,      # 틱 크기
                "current_price": float   # 사용된 현재가
            }
        """
        try:
            # 1. 계약 사양 정보 조회
            specs_json = await redis_client.get("symbol_info:contract_specifications")
            if not specs_json:
                if not user_id:
                    print("user_id가 없어서 계약사항 새로운 정보를 조회하지 않습니다.")
                    return None
                logger.info(f"계약 사양 정보가 없어 새로 조회합니다: {symbol}")
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"{API_BASE_URL}/account/contract-specs",
                        params={
                            "user_id": str(user_id),
                            "force_update": True
                        }
                    )
                    if response.status_code != 200:
                        raise ValueError("계약 사양 정보 조회 실패")
                        
                    specs_json = await redis_client.get(f"symbol_info:contract_specifications")
                    if not specs_json:
                        raise ValueError(f"계약 사양 정보를 찾을 수 없습니다: {symbol}")
            
            # 2. 계약 정보 파싱
            specs_dict = json.loads(specs_json)
            contract_info = specs_dict.get(symbol)
            if not contract_info:
                raise ValueError(f"해당 심볼의 계약 정보가 없습니다: {symbol}")
            
            # 3. 현재가 조회 (필요시)
            if current_price is None:
                current_price = await self._get_current_price(symbol)
            
            # 4. 계약 수량 계산
            
            contract_size = contract_info.get('contractSize', 0)
            if contract_size <= 0:
                raise ValueError(f"유효하지 않은 계약 크기: {contract_size}")
            
            if leverage is None or leverage <= 0:
                leverage = 1
            contracts_amount = 0.0
            tick_size = contract_info.get('tickSize', 0.001)
            min_size = contract_info.get('minSize', 1)
            if size_usdt is None or size_usdt <= 0:
                contracts_amount = 0   
            else:
                contract_size = float(contract_size)
                size_usdt = float(size_usdt)
                
                contracts_amount = (size_usdt * leverage) / (contract_size * current_price)
                contracts_amount = max(min_size, safe_float(contracts_amount))
                contracts_amount = round(contracts_amount / min_size) * min_size
                contracts_amount = float("{:.8f}".format(contracts_amount))  # 소수점 8자리로 형식화
                #print(f"contracts1: {contracts_amount}")
            return {
                "symbol": symbol,
                "contractSize": contract_size,
                "contracts_amount": contracts_amount,
                "minSize": min_size,
                "tickSize": tick_size,
                "current_price": current_price,
            }
            
        except Exception as e:
            logger.error(f"계약 정보 조회 실패: {str(e)}")
            raise ValueError(f"계약 정보 조회 실패: {str(e)}")
        
    async def get_order_info(self, user_id: str, symbol: str, order_id: str, is_algo=False, exchange: ccxt.Exchange = None) -> dict:
        """
        ccxt 기반으로 해당 order_id의 주문 정보를 반환한다.
        OKX 기준:
          - 일반 주문: fetch_order(order_id, symbol)
          - 알고(ALGO) 주문: OKX 전용 Private API 호출
        :param is_algo: SL같은 ALGO 주문이면 True
        :return: {
            "status": "filled" / "canceled" / "open" ...
            "id": "...",
            ...
        }
        """
        exchange = self.client if not exchange else exchange
        try:
            return await get_order_info_from_module(user_id = user_id, symbol = symbol, order_id = order_id, is_algo= is_algo, exchange= exchange)
        except Exception as e:
            logger.error(f"get_order_info() 오류: {str(e)}")
            raise

    async def _get_current_price(self, symbol: str, timeframe: str = "1m") -> float:
        exchange = self.client
        return await get_current_price(symbol, timeframe, exchange)


    async def get_position_avg_price(self, user_id: str, symbol: str, side: str) -> float:
        """
        포지션의 평균 가격을 조회합니다.
        먼저 ccxt로 실시간 포지션을 확인하고, 없으면 redis에서 확인합니다.
        """
        # ccxt로 실시간 포지션 확인
        positions = await self.client.fetch_positions([symbol])
        for position in positions:
            if position['symbol'] == symbol and position['side'] == side:
                entry_price = position['entryPrice']
                # redis 업데이트
                position_key = f"user:{user_id}:position:{symbol}:{side}"
                await redis_client.hset(position_key, 'entry_price', str(entry_price))
                return entry_price

        # ccxt에서 찾지 못한 경우 redis 확인
        position_key = f"user:{user_id}:position:{symbol}:{side}"
        position_data = await redis_client.hgetall(position_key)
        if not position_data:
            return None
        
        return float(position_data.get('entry_price', 0))
    
    
    

