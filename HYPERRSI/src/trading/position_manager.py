import asyncio
import json
import logging
import time
import traceback
from datetime import datetime

from redis import WatchError

from HYPERRSI.src.trading.models import Position
from HYPERRSI.src.trading.services.get_current_price import get_current_price
from HYPERRSI.telegram_message import send_telegram_message
from shared.database.redis_helper import get_redis_client
from shared.logging import get_logger

logger = get_logger(__name__)


# Module-level attribute for backward compatibility
def __getattr__(name):
    if name == "redis_client":
        return get_redis_client()
    raise AttributeError(f"module has no attribute {name}")

async def run_with_retry(keys, operation, max_retries=3):
    """Watch-based 트랜잭션 with 재시도"""
    for attempt in range(max_retries):
        try:
            async with get_redis_client().pipeline(transaction=True) as pipe:
                await pipe.watch(*keys)
                return await operation(pipe)
        except WatchError:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(0.1 * (attempt + 1))
# ─────────────────────────────────────────────────────────────────────────
# (B) PositionStateManager: 포지션 상태/Redis 관리 클래스
# ─────────────────────────────────────────────────────────────────────────
class PositionStateManager:
    def __init__(self, trading_service):
        self.trading = trading_service
        self._user_semaphores = {}
        self._semaphore_lock = asyncio.Lock()
        self._last_used = {}  # 추가

    async def get_user_semaphore(self, user_id: str) -> asyncio.Semaphore:
        """사용자별 세마포어 가져오기 (없으면 생성)"""
        async with self._semaphore_lock:
            if user_id not in self._user_semaphores:
                self._user_semaphores[user_id] = asyncio.Semaphore(1)
            # 세마포어를 가져올 때마다 시간 기록
            self._last_used[user_id] = time.time()
            return self._user_semaphores[user_id]
    def get_position_key(self, user_id: str, symbol: str, side: str) -> str:
        """포지션 키 생성"""
        if side == "sell":
            side = "short"
        elif side == "buy":
            side = "long"
        return f"user:{user_id}:position:{symbol}:{side}"


    async def cleanup_old_semaphores(self, max_age: int = 3600):
        """오래된 세마포어 정리"""
        async with self._semaphore_lock:
            current_time = time.time()
            for user_id in list(self._user_semaphores.keys()):
                last_used_time = self._last_used.get(user_id, 0)
                if current_time - last_used_time > max_age:
                    del self._user_semaphores[user_id]
                    del self._last_used[user_id]


    def get_position_keys(self, user_id: str, symbol: str, side: str) -> dict:
        """
        사용자 + 심볼 기준으로 Redis에서 포지션 정보를 구분할 때 사용할 key를 반환
        """
        if side == "sell":
            side = "short"
        elif side == "buy":
            side = "long"
        base = f"user:{user_id}"
        return {
            # position(전체 정보) 따로 관리할 수도 있지만, 여기서는 개별 키만 사용.
            'tp_data':           f"{base}:position:{symbol}:{side}:tp_data",
            'dca_count':         f"{base}:position:{symbol}:{side}:dca_count",
        }

    async def validate_position_state(self, user_id: str, symbol: str, side: str) -> bool:
        """
        거래소 포지션 vs Redis 포지션 정보 동기화 여부 확인 + mismatch 시 cleanup or sync
        """
        try:
            redis = await get_redis_client()
            position_key = self.get_position_key(user_id, symbol, side)

            # Redis에 있는 포지션 정보
            redis_position_data = await redis.hgetall(position_key)
            if not redis_position_data:
                return True

            position_info = json.loads(redis_position_data.get('position_info', '{}'))
            stored_size = float(position_info.get('contracts_amount', 0))

            # 실제 거래소 포지션
            exchange_position = await self.trading.get_current_position(user_id, symbol)
            print("exchange_position: ", exchange_position)
            if exchange_position is None:
                if stored_size > 0:
                    print(f"================\nstored_size: {stored_size} \n================")
                    await self.cleanup_position_data(user_id, symbol, side)
                    logger.warning(f"[{user_id}] [validate_position_state] Redis>0 but no pos => cleanup.")
                    return False
            else:
                position_qty = float(exchange_position.size)
                print(f"================\nposition_qty: {position_qty} \nstored_size2: {stored_size} \n================")
                # Redis의 포지션 정보를 실제 거래소 사이즈로 업데이트
                if abs(stored_size - position_qty) > 1e-6:
                    print("호출")
                    await self.sync_position_state(user_id, symbol, exchange_position)
                    logger.info(f"[{user_id}] [validate_position_state] Syncing size: {stored_size} -> {position_qty}")
                    return True  # 동기화 후 유효한 상태로 처리
            return True
        except Exception as e:
            await send_telegram_message(f"[{user_id}] [validate_position_state] error: {e}", debug=True)
            logger.error(f"[validate_position_state] error: {e}")
            return False


    async def sync_position_state(self, user_id: str, symbol: str, exchange_position: Position | None):
        """거래소 포지션 정보로 Redis 업데이트. 포지션 없으면 전부 삭제."""
        # Lazy import to avoid circular dependency
        from HYPERRSI.src.trading.monitoring.trailing_stop_handler import clear_trailing_stop

        try:
            position_key = self.get_position_key(user_id, symbol, exchange_position.side)

            async def sync_operation(pipe):
                pipe.multi()
                if exchange_position is None:
                    pipe.delete(position_key)
                    # 포지션 청산 시 trailing stop도 비활성화
                    # side를 추출 (position_key에서)
                    side = position_key.split(":")[-1]
                    asyncio.create_task(clear_trailing_stop(user_id, symbol, side))
                    logger.info(f"[포지션 청산] Trailing stop 비활성화 요청: {user_id}, {symbol}, {side}")
                else:
                    new_data = {
                        "position_info": json.dumps({
                            "entry_price": exchange_position.entry_price,
                            "size": float(exchange_position.size),
                            "contracts_amount": float(exchange_position.size),
                            "side": exchange_position.side,
                            "symbol": symbol,
                            "updated_at": str(datetime.now()),
                        })
                    }
                    await pipe.hset(position_key, mapping=new_data)
                return await pipe.execute()
            print("여기까지 실행")
            await run_with_retry([position_key], sync_operation)
        except Exception as e:
            await send_telegram_message(f"[{user_id}] [sync_position_state] error: {e}", debug=True)
            logger.error(f"[sync_position_state] error: {e}")
            raise

    # ─────────────────────────────────────────────────────────────────────────
    # 3) 포지션 관련 데이터(해당 심볼) 전부 삭제 : cleanup_position_data
    # ─────────────────────────────────────────────────────────────────────────
    async def cleanup_position_data(self, user_id: str, symbol: str, side: str):
        """
        user_id + symbol 관련 포지션 및 부가 데이터(TP, DCA 등)를 전부 삭제
        """
        # Lazy import to avoid circular dependency
        from HYPERRSI.src.trading.monitoring.trailing_stop_handler import clear_trailing_stop

        try:
            # 포지션 데이터 삭제 시 trailing stop도 비활성화
            asyncio.create_task(clear_trailing_stop(user_id, symbol, side))
            logger.info(f"[포지션 데이터 삭제] Trailing stop 비활성화 요청: {user_id}, {symbol}, {side}")

            keys_dict = self.get_position_keys(user_id, symbol, side)
            position_key = self.get_position_key(user_id, symbol, side)
            print("position_key: ", position_key)
            all_keys = list(keys_dict.values()) + [position_key]

            async def delete_operation(pipe):
                pipe.multi()
                for k in all_keys:
                    pipe.delete(k)
                return await pipe.execute()
            print("33333")
            try:
                await run_with_retry(all_keys, delete_operation)
                logger.info(f"[cleanup_position_data] done user={user_id}, symbol={symbol}")
            except Exception as e:
                logger.error(f"cleanup_position_data error: {e}")
                raise
        except Exception as e:
            await send_telegram_message(f"[{user_id}] [cleanup_position_data] error: {e}", debug=True)
            logger.error(f"[cleanup_position_data] error: {e}")
            raise
    # ─────────────────────────────────────────────────────────────────────────
    # 6) 핵심: update_position_state (new/add/reduce)
    # ─────────────────────────────────────────────────────────────────────────
    async def update_position_state(
        self,
        user_id: str,
        symbol: str,
        entry_price: float,
        contracts_amount_delta: float,
        side: str = None,
        operation_type: str = None,
        position_qty_delta: float = None,
        new_entry_exact_price: float = None,
        new_exact_contract_size: float = None
    ) -> tuple[float, float]:
        """
        포지션 상태 업데이트 및 (새로운 avg_price, size) 반환
        operation_type: "new_position", "add_position", "reduce_position"
        """
        # Lazy import to avoid circular dependency
        from HYPERRSI.src.trading.monitoring.trailing_stop_handler import clear_trailing_stop
        if side == "sell":
            side = "short"
        elif side == "buy":
            side = "long"
        position_key = f"user:{user_id}:position:{symbol}:{side}"
        if position_qty_delta is None:
            position_qty_delta = contracts_amount_delta / 0.01
            
        async def update_operation(pipe):
            try:
                redis = await get_redis_client()
                # 현재 포지션 정보 조회
                position_data = await pipe.hgetall(position_key)
                position_info = json.loads(position_data.get('position_info', '{}'))
                
                entry_price_raw = position_info.get('entry_price', '0')
                old_avg_price = 0.0
                if entry_price_raw == 'None' or entry_price_raw == None:
                    old_avg_price = 0.0
                else:
                    old_avg_price = float(entry_price_raw)
                
                contracts_amount_raw = position_info.get('contracts_amount', '0')
                old_contracts_amount = 0.0
                if contracts_amount_raw == 'None' or contracts_amount_raw == None:
                    old_contracts_amount = 0.0
                else:
                    old_contracts_amount = float(contracts_amount_raw)
                
                position_qty_raw = position_info.get('position_qty', '0')
                old_position_qty = 0.0
                if position_qty_raw == 'None' or position_qty_raw == None:
                    old_position_qty = 0.0
                else:
                    old_position_qty = float(position_qty_raw)
                
                stored_side = position_info.get('side', None)
                
                print("="*10)
                print(f"old_avg_price: {old_avg_price}, old_contracts_amount: {old_contracts_amount}, old_position_qty: {old_position_qty}, stored_side: {stored_side}")
                print(f"entry_price: {entry_price}, contracts_amount_delta: {contracts_amount_delta}, position_qty_delta: {position_qty_delta}, side: {side}, operation_type: {operation_type}")
                print("="*10)

            except Exception as e:
                logger.error(f"[update_position_state] watch error: {e}")
                raise

            pipe.multi()
            result = None  # 결과값을 저장할 변수
            try:
                if operation_type == "new_position":
                    # 기존 포지션이 다른 방향이면 초기화
                    if stored_side and stored_side != side:
                        await pipe.delete(position_key)
                    new_avg_price = entry_price
                    new_contracts_amount = contracts_amount_delta
                    new_position_qty = position_qty_delta
                    
                    result = (new_avg_price, new_contracts_amount)

                elif operation_type == "add_position":
                    if stored_side and stored_side != side:
                        raise ValueError(f"Cannot add pos on different side: {stored_side} != {side}")
                    new_contracts_amount = old_contracts_amount + contracts_amount_delta
                    new_position_qty = old_position_qty + position_qty_delta
                    print("new_entry_exact_price is None")
                    new_avg_price = old_avg_price
                    if new_contracts_amount <= 0:
                        await pipe.delete(position_key)
                        # 포지션 수량이 0이 되어 청산될 때 trailing stop 비활성화
                        asyncio.create_task(clear_trailing_stop(user_id, symbol, side))
                        logger.info(f"[포지션 수량 0] Trailing stop 비활성화 요청: {user_id}, {symbol}, {side}")
                        result = (0.0, 0.0)
                    else: #직접 가중평균
                        new_avg_price = ((old_avg_price * old_contracts_amount) + (entry_price * contracts_amount_delta)) / new_contracts_amount
                        result = (new_avg_price, new_contracts_amount)
                    if new_entry_exact_price is not None:
                        new_avg_price = new_entry_exact_price
                        print("new_avg_price: ", new_avg_price)
                        result = (new_avg_price, new_contracts_amount)
                    if new_exact_contract_size is not None:
                        result = (new_avg_price, new_exact_contract_size)
                        


                elif operation_type == "reduce_position":
                    if stored_side and stored_side != side:
                        raise ValueError(f"Cannot reduce pos on different side: {stored_side} != {side}")
                    new_contracts_amount = old_contracts_amount - abs(contracts_amount_delta)
                    if new_contracts_amount <= 0:
                        # 완전 청산
                        await pipe.delete(position_key)
                        result = (0.0, 0.0)
                    else:
                        # 부분 청산 -> 평균가 유지
                        new_avg_price = old_avg_price
                        result = (new_avg_price, new_contracts_amount)
                else:
                    raise ValueError(f"Unknown operation_type: {operation_type}")

                if result[1] > 0:  # size가 0보다 큰 경우에만 Redis 업데이트
                    # 새로운 포지션 정보 구성
                    new_position_info = {
                        "entry_price": result[0],
                        "contracts_amount": result[1],
                        "position_qty": new_position_qty,
                        "side": side,
                        "symbol": symbol,
                        "updated_at": str(datetime.now()),
                        "last_entry_size": contracts_amount_delta if operation_type in ["new_position", "add_position"] else old_contracts_amount
                    }

                    # Redis에 업데이트 - JSON과 개별 필드 모두 저장
                    await pipe.hset(
                        position_key,
                        "position_info",
                        json.dumps(new_position_info)
                    )
                    
                    # 개별 필드로도 저장 (position_handler.py와의 호환성을 위해)
                    for key, value in new_position_info.items():
                        await pipe.hset(position_key, key, str(value))

                await pipe.execute()  # transaction 실행
                return result  # 결과값 반환

            except Exception as e:
                logger.error(f"[update_position_state] error: {e}")
                await pipe.delete(position_key)
                raise

        # transaction 실행 및 결과 저장
        try:
            result = await run_with_retry([position_key], update_operation)
            is_valid = await self.validate_position_state(user_id, symbol, side)

            if not result or (isinstance(result, list) and len(result) == 0):
                # 기본값으로 현재 entry_price와 size_delta 사용
                result = (entry_price, contracts_amount_delta)

            if not is_valid:
                logger.warning(f"[update_position_state] after update => invalid => cleanup.")
                await self.cleanup_position_data(user_id, symbol, side)
                return (entry_price, contracts_amount_delta)
            # result가 튜플인지 확인
            if isinstance(result, tuple) and len(result) == 2:
                return result
            else:
                logger.error(f"[update_position_state] Unexpected result format: {result}")
                return (entry_price, contracts_amount_delta)

        except Exception as e:
            logger.error(f"[update_position_state] error: {e}")
            traceback.print_exc()
            return (entry_price, contracts_amount_delta)


    async def get_position_info(self, user_id: str, symbol: str, side: str) -> dict:
        """
        포지션 정보 조회
        """
        try:
            redis = await get_redis_client()
            position_key = self.get_position_key(user_id, symbol, side)
            return await redis.hgetall(position_key)
        except Exception as e:
            await send_telegram_message(f"[{user_id}] [get_position_info] error: {e}", debug=True)
            logger.error(f"[get_position_info] error: {e}")
            return None
