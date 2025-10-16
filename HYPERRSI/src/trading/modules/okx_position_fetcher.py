# HYPERRSI/src/trading/modules/okx_position_fetcher.py
"""
OKX Position Fetcher

OKX 거래소 포지션 조회 및 관리
"""

import asyncio
import json
import time
import traceback
from datetime import datetime
from typing import Dict, Optional

import ccxt.async_support as ccxt
import pytz
from fastapi import HTTPException

from HYPERRSI.src.trading.modules.trading_utils import init_user_position_data
from HYPERRSI.telegram_message import send_telegram_message
from shared.database.redis_helper import get_redis_client
from shared.logging import get_logger
from shared.utils import safe_float

logger = get_logger(__name__)


# Module-level attribute for backward compatibility
def __getattr__(name):
    if name == "redis_client":
        return get_redis_client()
    raise AttributeError(f"module has no attribute {name}")


class OKXPositionFetcher:
    """OKX 거래소 포지션 조회 서비스"""

    def __init__(self, trading_service):
        """
        Args:
            trading_service: TradingService 인스턴스
        """
        self.trading_service = trading_service

    async def get_user_api_keys(self, user_id: str) -> Dict[str, str]:
        """
        사용자 ID를 기반으로 Redis에서 OKX API 키를 가져오는 함수
        """
        try:
            redis = await get_redis_client()
            api_key_format = f"user:{user_id}:api:keys"
            api_keys = await redis.hgetall(f"user:{user_id}:api:keys")
            if not api_keys:
                raise HTTPException(status_code=404, detail="API keys not found in Redis")
            return api_keys
        except Exception as e:
            logger.error(f"3API 키 조회 실패: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error fetching API keys: {str(e)}")

    async def fetch_with_retry(self, exchange, symbol: str, max_retries: int = 3) -> Optional[list]:
        """재시도 로직이 포함된 포지션 조회"""
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

    @staticmethod
    def get_redis_keys(user_id: str, symbol: str, side: str) -> dict:
        """사용자별 Redis 키 생성"""
        return {
            'api_keys': f"user:{user_id}:api:keys",
            'trading_status': f"user:{user_id}:trading:status",
            'positions': f"user:{user_id}:position:{symbol}:{side}",
            'settings': f"user:{user_id}:settings"
        }

    async def fetch_okx_position(self, user_id: str, symbol: str, side: str = None, user_settings: dict = None, debug_entry_number: int = 9) -> dict:
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

        redis = await get_redis_client()
        exchange = None
        fail_to_fetch_position = False
        fetched_redis_position = False
        try:
            api_keys = await self.get_user_api_keys(user_id)
            # ✅ OrderWrapper 사용 (ORDER_BACKEND 자동 감지)
            from HYPERRSI.src.trading.services.order_wrapper import OrderWrapper
            exchange = OrderWrapper(user_id, api_keys)

            position_state_key = f"user:{user_id}:position:{symbol}:position_state"
            current_state = await redis.get(position_state_key)

            try:
                position_state = int(current_state) if current_state is not None else 0
            except (TypeError, ValueError):
                position_state = 0  # 변환 실패시 기본값 0

            # 1) 실제 포지션 가져오기
            try:
                positions = await self.fetch_with_retry(exchange, symbol)
                if exchange is not None:
                    await exchange.close()
            except ccxt.OnMaintenance as e:
                raise HTTPException(
                    status_code=503,
                    detail="거래소가 현재 유지보수 중입니다. 잠시 후 다시 시도해주세요."
                )
            except ccxt.AuthenticationError as e:
                logger.error(f"[{user_id}] Authentication error for {symbol}: {str(e)}")

                is_running = False
                await redis.set(f"user:{user_id}:trading:status", str(is_running))
                if exchange is not None:
                    await exchange.close()
                return {}
            except Exception as e:
                logger.error(f"Error in fetch_okx_position for {symbol}: {str(e)}")
                traceback.print_exc()
                try:
                    if side is None:
                        positions_long = await redis.hgetall(f"user:{user_id}:position:{symbol}:long")
                        positions_short = await redis.hgetall(f"user:{user_id}:position:{symbol}:short")
                        positions = {**positions_long, **positions_short}
                        return positions
                    else:
                        positions = await redis.hgetall(f"user:{user_id}:position:{symbol}:{side}")
                        return positions
                except Exception as e:
                    logger.error(f"Error in fetch_okx_position for {symbol}: {str(e)}")
                    traceback.print_exc()
                    fail_to_fetch_position = True
                    fetched_redis_position = True
                fail_to_fetch_position = True

            # 2) 포지션이 없는 경우, Redis에 실제 키가 있는 경우만 삭제
            if not positions:
                has_redis_position = False
                for side in ['long', 'short']:
                    position_key = f"user:{user_id}:position:{symbol}:{side}"
                    # Redis에 실제로 키가 존재하는지 확인
                    exists = await redis.exists(position_key)
                    if exists:
                        has_redis_position = True
                        dca_count_key = f"user:{user_id}:position:{symbol}:{side}:dca_count"
                        await redis.set(dca_count_key, "0")
                        await redis.set(position_state_key, "0")
                        await redis.delete(position_key)

                # 실제로 Redis 키가 있어서 삭제한 경우만 로깅
                if has_redis_position:
                    logger.error(f"[{user_id}] 포지션 없음. Redis 데이터 삭제.")
                    await send_telegram_message(f"[{user_id}] [{debug_entry_number}] 포지션 없음. Redis 데이터 삭제. 여기서 아마 경합 일어날 가능성 있으니, 실제로 어떻게 된건지 체크.", debug=True)

            # 3) 각 포지션 처리
            if fail_to_fetch_position:
                if fetched_redis_position:
                    return positions
                else:
                    return {}
            result = {}
            active_positions = [pos for pos in positions if float(pos.get('info', {}).get('pos', 0)) > 0]
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
                # 02 05 15:16 수정 -> 이미 contracts가 , 바로 계약수량으로 들어옴. 그래서 이걸로 바로 size를 씀.
                position_qty = contracts * contract_size
                contracts_amount = contracts
                dca_count_key = f"user:{user_id}:position:{symbol}:{side}:dca_count"
                dca_count = await redis.get(dca_count_key)

                try:
                    if contracts > 0:
                        position_key = f"user:{user_id}:position:{symbol}:{side}"
                        if dca_count == "1":
                            last_entry_size = contracts_amount
                        else:
                            # DCA 진입이 2회 이상인 경우, 가장 최근 진입 크기 계산
                            # 1) Redis에서 이전 포지션 크기 가져오기
                            previous_contracts = await redis.hget(position_key, 'contracts_amount')
                            if previous_contracts:
                                previous_contracts = safe_float(previous_contracts)
                                # 현재 포지션에서 이전 포지션을 빼서 최근 추가된 물량 계산
                                last_entry_size = contracts_amount - previous_contracts
                                if last_entry_size <= 0:
                                    # 음수이거나 0인 경우, DCA 배수로 추정 계산
                                    previous_last_entry = await redis.hget(position_key, 'last_entry_size')
                                    if previous_last_entry:
                                        scale = 0.5  # 기본 DCA 배수
                                        last_entry_size = safe_float(previous_last_entry) * scale
                                    else:
                                        # 데이터가 없으면 현재 포지션을 DCA 횟수로 나눈 평균값 사용
                                        last_entry_size = contracts_amount / max(safe_float(dca_count or 1), 1)
                            else:
                                # 이전 데이터가 없으면 entry_multiplier를 사용해서 역산으로 계산
                                if user_settings is None:
                                    settings_str = await redis.get(f"user:{user_id}:settings")
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
                        # 기존 tp_data와 sl_data 보존
                        existing_data = await redis.hgetall(position_key)
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

                        await redis.hset(position_key, mapping=mapping)
                        result[side] = mapping

                    else:
                        # contracts가 0인 경우 해당 side의 포지션 삭제
                        await init_user_position_data(user_id, symbol, side)
                        position_key = f"user:{user_id}:position:{symbol}:{side}"
                        await redis.delete(position_key)
                        dca_count_key = f"user:{user_id}:position:{symbol}:{side}:dca_count"
                        await redis.set(dca_count_key, "0")
                        await send_telegram_message(f"[{user_id}] contracts가 0인 경우여서, 해당 Side의 포지션을 삭제하는데, 정상적이지 않은 로직. 체크 필요", debug=True)
                except Exception as e:
                    logger.error(f"포지션 업데이트 실패 ({symbol}): {str(e)}")
                    await send_telegram_message(f"[{user_id}] Fetching Position에서 에러 발생.\n에러 내용 : {e}", debug=True)

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
            await redis.set(position_state_key, str(position_state))

            return result

        except Exception as e:
            logger.error(f"포지션 조회 실패3 ({symbol}): {str(e)}")
            traceback.print_exc()
            # 에러 발생시 양쪽 포지션 모두 조회
            result = {}
            for side in ['long', 'short']:
                position_key = f"user:{user_id}:position:{symbol}:{side}"
                position_data = await redis.hgetall(position_key)
                if position_data:
                    result[side] = position_data
            return result
        finally:
            # 이 인스턴스에 대해서만 리소스 해제
            if exchange is not None:
                await exchange.close()

    async def get_position_avg_price(self, user_id: str, symbol: str, side: str) -> float:
        """
        포지션의 평균 가격을 조회합니다.
        먼저 ccxt로 실시간 포지션을 확인하고, 없으면 redis에서 확인합니다.
        """
        # ccxt로 실시간 포지션 확인

        redis = await get_redis_client()
        positions = await self.trading_service.client.fetch_positions([symbol])
        for position in positions:
            if position['symbol'] == symbol and position['side'] == side:
                entry_price = position['entryPrice']
                # redis 업데이트
                position_key = f"user:{user_id}:position:{symbol}:{side}"
                await redis.hset(position_key, 'entry_price', str(entry_price))
                return entry_price

        # ccxt에서 찾지 못한 경우 redis 확인
        position_key = f"user:{user_id}:position:{symbol}:{side}"
        position_data = await redis.hgetall(position_key)
        if not position_data:
            return None

        return float(position_data.get('entry_price', 0))
