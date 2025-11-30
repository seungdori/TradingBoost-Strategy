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
from HYPERRSI.src.trading.utils.position_handler.constants import (
    DCA_COUNT_KEY,
    DCA_LEVELS_KEY,
    PENDING_DELETION_KEY,
    POSITION_KEY,
    TP_DATA_KEY,
)
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
                # 지수 백오프: 2초, 4초, 8초 (네트워크 안정화 대기)
                wait_time = 2 * (2 ** attempt)
                logger.warning(f"Attempt {attempt + 1}/{max_retries} failed for {symbol}. "
                               f"Retrying in {wait_time}s... Error: {str(e)}")

                if attempt == max_retries - 1:  # 마지막 시도였다면
                    logger.error(f"All retry attempts failed for {symbol}: {str(e)}")
                    raise  # 마지막 에러를 그대로 전파

                await asyncio.sleep(wait_time)
        return None

    @staticmethod
    def get_redis_keys(user_id: str, symbol: str, side: str) -> dict:
        """사용자별 Redis 키 생성 (심볼별 상태 관리)"""
        return {
            'api_keys': f"user:{user_id}:api:keys",
            'symbol_status': f"user:{user_id}:symbol:{symbol}:status",  # 심볼별 상태
            'positions': POSITION_KEY.format(user_id=user_id, symbol=symbol, side=side),
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
            symbol (str): 심볼 (예: 'BTC/USDT:USDT' 또는 'BTC-USDT-SWAP')

        Returns:
            dict: 포지션 정보. 포지션이 없으면 빈 딕셔너리 반환
        """

        redis = await get_redis_client()
        exchange = None
        fail_to_fetch_position = False
        fetched_redis_position = False

        # 심볼 형식 정규화 (공용 함수 사용)
        from shared.utils.symbol_helpers import normalize_symbol as norm_sym
        try:
            normalized_symbol = norm_sym(symbol, target_format="ccxt")
        except Exception as e:
            logger.warning(f"심볼 정규화 실패, 원본 사용: {symbol}, 에러: {e}")
            normalized_symbol = symbol

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
                positions = await self.fetch_with_retry(exchange, normalized_symbol)
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
                await redis.set(f"user:{user_id}:symbol:{symbol}:status", "stopped")
                if exchange is not None:
                    await exchange.close()
                return {}
            except Exception as e:
                logger.error(f"Error in fetch_okx_position for {symbol}: {str(e)}")
                traceback.print_exc()
                # errordb 로깅
                from HYPERRSI.src.utils.error_logger import log_error_to_db
                log_error_to_db(
                    error=e,
                    error_type="PositionFetchError",
                    user_id=user_id,
                    severity="ERROR",
                    symbol=symbol,
                    metadata={"side": side, "component": "OKXPositionFetcher.fetch_okx_position"}
                )
                try:
                    if side is None:
                        positions_long = await redis.hgetall(POSITION_KEY.format(user_id=user_id, symbol=symbol, side="long"))
                        positions_short = await redis.hgetall(POSITION_KEY.format(user_id=user_id, symbol=symbol, side="short"))
                        positions = {**positions_long, **positions_short}
                        return positions
                    else:
                        positions = await redis.hgetall(POSITION_KEY.format(user_id=user_id, symbol=symbol, side=side))
                        return positions
                except Exception as e2:
                    logger.error(f"Error in fetch_okx_position fallback for {symbol}: {str(e2)}")
                    traceback.print_exc()
                    fail_to_fetch_position = True
                    fetched_redis_position = True
                fail_to_fetch_position = True

            # 2) 포지션이 없는 경우 - 안전한 삭제 로직 (2회 연속 확인 필요)
            if not positions:
                has_redis_position = False
                for side in ['long', 'short']:
                    position_key = POSITION_KEY.format(user_id=user_id, symbol=symbol, side=side)
                    pending_deletion_key = PENDING_DELETION_KEY.format(user_id=user_id, symbol=symbol, side=side)

                    # Redis에 실제로 키가 존재하는지 확인
                    exists = await redis.exists(position_key)
                    if exists:
                        has_redis_position = True

                        # 삭제 대기 상태 확인 (2회 연속 확인 로직)
                        pending_deletion = await redis.get(pending_deletion_key)

                        if not pending_deletion:
                            # 첫 번째 "포지션 없음" - 삭제 대기 상태로 설정 (60초 TTL)
                            await redis.set(pending_deletion_key, "1", ex=60)
                            logger.warning(f"[{user_id}][{symbol}][{side}] OKX에서 포지션 없음 (1차 확인) - 삭제 대기 상태로 설정. 다음 확인 시 삭제 예정.")
                            await send_telegram_message(f"[{user_id}][{symbol}][{side}] ⚠️ OKX 포지션 없음 (1차). 60초 내 재확인 후 삭제 여부 결정.", debug=True)
                        else:
                            # 두 번째 "포지션 없음" - 실제 삭제 진행
                            logger.warning(f"[{user_id}][{symbol}][{side}] OKX에서 포지션 없음 (2차 확인) - 실제 삭제 진행")

                            dca_count_key = DCA_COUNT_KEY.format(user_id=user_id, symbol=symbol, side=side)
                            tp_data_key = TP_DATA_KEY.format(user_id=user_id, symbol=symbol, side=side)
                            dca_levels_key = DCA_LEVELS_KEY.format(user_id=user_id, symbol=symbol, side=side)

                            # 삭제 전 백업 생성 (24시간 보관)
                            position_data = await redis.hgetall(position_key)
                            if position_data:
                                backup_key = f"user:{user_id}:position_deleted_backup:{symbol}:{side}"
                                await redis.set(backup_key, json.dumps(position_data), ex=86400)
                                logger.info(f"[{user_id}][{symbol}][{side}] 삭제 전 백업 생성: {backup_key}")

                            # 삭제 전 데이터 존재 여부 로깅
                            tp_exists = await redis.exists(tp_data_key)
                            dca_exists = await redis.exists(dca_levels_key)
                            logger.warning(f"[{user_id}][{symbol}][{side}] 포지션 없음 - Redis 삭제 시작: position_key 존재, tp_data_key 존재={tp_exists}, dca_levels_key 존재={dca_exists}")

                            # 통합 삭제 함수 사용 - 모든 관련 키를 일괄 삭제 (고아 키 방지)
                            deleted_count = await init_user_position_data(
                                user_id=user_id,
                                symbol=symbol,
                                side=side,
                                cleanup_symbol_keys=False  # 반대 포지션 존재 가능성
                            )
                            logger.warning(f"[{user_id}][{symbol}][{side}] 포지션 관련 데이터 삭제 완료: {deleted_count}개 키 삭제")
                            await send_telegram_message(f"[{user_id}][{symbol}][{side}] ✅ 포지션 삭제 완료 (2차 확인 후)", debug=True)

                # 실제로 Redis 키가 있어서 처리한 경우만 로깅
                if has_redis_position:
                    logger.info(f"[{user_id}] OKX 포지션 없음 감지. 안전 삭제 로직 실행됨.")

            # 3) 각 포지션 처리
            if fail_to_fetch_position:
                if fetched_redis_position:
                    return positions
                else:
                    return {}
            result = {}
            active_positions = [pos for pos in positions if float(pos.get('info', {}).get('pos', 0)) > 0]
            for pos in active_positions:
                # 심볼 매칭 시 정규화된 심볼 사용
                pos_symbol = pos['info']['instId']
                if pos_symbol != normalized_symbol and pos_symbol != symbol:
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
                dca_count_key = DCA_COUNT_KEY.format(user_id=user_id, symbol=symbol, side=side)
                dca_count = await redis.get(dca_count_key)

                try:
                    if contracts > 0:
                        position_key = POSITION_KEY.format(user_id=user_id, symbol=symbol, side=side)
                        existing_data = await redis.hgetall(position_key)
                        previous_contracts = safe_float(existing_data.get('contracts_amount')) if existing_data.get('contracts_amount') else None
                        previous_last_entry = safe_float(existing_data.get('last_entry_size')) if existing_data.get('last_entry_size') else None

                        dca_count_int = int(dca_count) if dca_count else 0
                        if dca_count_int <= 1:
                            last_entry_size = contracts_amount
                        else:
                            delta = 0.0
                            if previous_contracts is not None:
                                delta = contracts_amount - previous_contracts
                            if delta > 0:
                                last_entry_size = delta
                            elif previous_last_entry and previous_last_entry > 0:
                                # 이전 스냅샷이라도 유효하면 그대로 유지
                                last_entry_size = previous_last_entry
                            else:
                                # 이전 정보가 없으면 entry_multiplier 기반 추정
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
                                arithmetic_sum = 1 + entry_multiplier * (dca_count_int - 1) * dca_count_int / 2
                                initial_entry = contracts_amount / arithmetic_sum if arithmetic_sum else contracts_amount
                                if dca_count_int == 1:
                                    last_entry_size = initial_entry
                                else:
                                    last_entry_size = initial_entry * entry_multiplier * (dca_count_int - 1)

                        leverage = safe_float(pos['leverage'])
                        # 기존 tp_data와 sl_data 보존
                        existing_tp_data = existing_data.get('tp_data')
                        existing_sl_data = existing_data.get('sl_data')

                        # 기존 last_entry_size가 있고 새로 계산된 값이 0 이하라면 기존 값을 유지
                        if (last_entry_size is None or last_entry_size <= 0) and existing_data.get('last_entry_size'):
                            try:
                                last_entry_size = safe_float(existing_data.get('last_entry_size'))
                            except Exception:
                                last_entry_size = 0.0

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

                        # 포지션이 확인되면 삭제 대기 플래그 제거
                        pending_deletion_key = PENDING_DELETION_KEY.format(user_id=user_id, symbol=symbol, side=side)
                        await redis.delete(pending_deletion_key)

                    else:
                        # contracts가 0인 경우 해당 side의 포지션 삭제
                        # 통합 삭제 함수 사용 - 모든 관련 키 일괄 삭제 (고아 키 방지)
                        logger.warning(f"[{user_id}][{symbol}][{side}] contracts=0 감지 - 포지션 데이터 삭제")
                        deleted_count = await init_user_position_data(
                            user_id=user_id,
                            symbol=symbol,
                            side=side,
                            cleanup_symbol_keys=False  # 반대 포지션 존재 가능성
                        )
                        logger.warning(f"[{user_id}][{symbol}][{side}] contracts=0 처리 완료 - {deleted_count}개 키 삭제")
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
                position_key = POSITION_KEY.format(user_id=user_id, symbol=symbol, side=side)
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
                position_key = POSITION_KEY.format(user_id=user_id, symbol=symbol, side=side)
                await redis.hset(position_key, 'entry_price', str(entry_price))
                return entry_price

        # ccxt에서 찾지 못한 경우 redis 확인
        position_key = POSITION_KEY.format(user_id=user_id, symbol=symbol, side=side)
        position_data = await redis.hgetall(position_key)
        if not position_data:
            return None

        return float(position_data.get('entry_price', 0))
