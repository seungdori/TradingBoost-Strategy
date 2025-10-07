# HYPERRSI/src/trading/modules/position_manager.py
"""
Position Manager

포지션 오픈/클로즈 및 포지션 조회 관리
"""

import json
import asyncio
import traceback
from datetime import datetime, timedelta
from typing import Optional, Dict, List

from HYPERRSI.src.core.database import TradingCache
from HYPERRSI.src.trading.models import Position, OrderStatus
from HYPERRSI.src.trading.stats import record_trade_history_entry, update_trade_history_exit
from HYPERRSI.telegram_message import send_telegram_message
from HYPERRSI.src.trading.error_message import map_exchange_error
from shared.utils import safe_float, round_to_qty, get_minimum_qty, convert_bool_to_string
from shared.logging import get_logger

logger = get_logger(__name__)

# Dynamic redis_client access
def _get_redis_client():
    """Get redis_client dynamically to avoid import-time errors"""
    from HYPERRSI.src.core import database as db_module
    return db_module.redis_client


class PositionManager:
    """포지션 오픈/클로즈 관리 서비스"""

    def __init__(self, trading_service):
        """
        Args:
            trading_service: TradingService 인스턴스
        """
        self.trading_service = trading_service

    async def contract_size_to_qty(self, user_id, symbol: str, contracts_amount: float) -> float:
        """
        계약 수를 주문 수량으로 변환
        """
        try:
            contract_info = await self.trading_service.market_data.get_contract_info( user_id=user_id, symbol = symbol)
            #print("contract_size: ", contract_info['contractSize']) #<-- 비트 기준 0.01로 나오는 것 확인.
            qty = safe_float(contracts_amount) * safe_float(contract_info['contractSize']) #<-- contract에 contract size를 곱하는 게 맞지.
            qty = round(qty, 8)
            print("qty:1 ", qty) #<-- 비트 기준, 0.01 * 12 = 0.12 로 나오는 것 확인.

            return qty
        except Exception as e:
            logger.error(f"계약 수를 주문 수량으로 변환 실패: {str(e)}")
            return contracts_amount

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
                        positions = await self.trading_service.okx_fetcher.fetch_okx_position(user_id, symbol, debug_entry_number=1)
                        print(f"[{user_id}] positions: {str(positions)[:50]}...")
                    except Exception as e:
                        logger.error(f"거래소 포지션 조회 실패: {str(e)}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                            continue
                        return None

                if not positions or positions == {}:
                    return None
                # symbol과 pos_side가 모두 주어진 경우
                if symbol and pos_side:
                    # 정확히 해당하는 포지션이 있으면 반환
                    if symbol in positions and pos_side in positions[symbol]:
                        pos_data = positions[symbol][pos_side]
                        position = Position(
                            user_id=user_id,
                            symbol=pos_data["symbol"],
                            side=pos_data["side"],
                            size=safe_float(pos_data.get("size", 0)),
                            entry_price=safe_float(pos_data.get("entry_price", 0)),
                            leverage=safe_float(pos_data.get("leverage", 1)),
                            sl_order_id=pos_data.get("sl_order_id"),
                            sl_price=safe_float(pos_data.get("sl_price")) if pos_data.get("sl_price") else None,
                            tp_order_ids=pos_data.get("tp_order_ids", []),
                            tp_prices=pos_data.get("tp_prices", []),
                            order_id=pos_data.get("order_id")
                        )
                        return position
                    else:
                        # 정확한 symbol + side를 찾지 못했으면 None
                        return None
                # symbol만 주어진 경우
                elif symbol:
                    if symbol not in positions:
                        return None
                    # 해당 심볼에 대해 long, short 중 하나 반환 (long 우선)
                    pos_data = None
                    if "long" in positions[symbol]:
                        pos_data = positions[symbol]["long"]
                    elif "short" in positions[symbol]:
                        pos_data = positions[symbol]["short"]
                    if not pos_data:
                        return None
                    position = Position(
                        user_id=user_id,
                        symbol=pos_data["symbol"],
                        side=pos_data["side"],
                        size=safe_float(pos_data.get("size", 0)),
                        entry_price=safe_float(pos_data.get("entry_price", 0)),
                        leverage=safe_float(pos_data.get("leverage", 1)),
                        sl_order_id=pos_data.get("sl_order_id"),
                        sl_price=safe_float(pos_data.get("sl_price")) if pos_data.get("sl_price") else None,
                        tp_order_ids=pos_data.get("tp_order_ids", []),
                        tp_prices=pos_data.get("tp_prices", []),
                        order_id=pos_data.get("order_id")
                    )
                    return position
                else:
                    # symbol도 pos_side도 없으면 첫 번째 포지션 반환
                    for sym, side_dict in positions.items():
                        for s, pos_data in side_dict.items():
                            position = Position(
                                user_id=user_id,
                                symbol=pos_data["symbol"],
                                side=pos_data["side"],
                                size=safe_float(pos_data.get("size", 0)),
                                entry_price=safe_float(pos_data.get("entry_price", 0)),
                                leverage=safe_float(pos_data.get("leverage", 1)),
                                sl_order_id=pos_data.get("sl_order_id"),
                                sl_price=safe_float(pos_data.get("sl_price")) if pos_data.get("sl_price") else None,
                                tp_order_ids=pos_data.get("tp_order_ids", []),
                                tp_prices=pos_data.get("tp_prices", []),
                                order_id=pos_data.get("order_id")
                            )
                            return position
                    return None
            except asyncio.TimeoutError:
                logger.warning(f"포지션 조회 타임아웃 (시도 {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                return None
            except Exception as e:
                logger.error(f"포지션 조회 실패: {str(e)}")
                traceback.print_exc()
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                return None
        return None

    async def get_contract_size(self, symbol: str) -> float:
        """계약 크기 조회"""
        contract_info = await self.trading_service.market_data.get_contract_info(symbol=symbol)
        return safe_float(contract_info.get('contractSize', 1))

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
        redis_client = _get_redis_client()
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
            current_price = await self.trading_service.market_data.get_current_price(symbol)
            try:
                position_avg_price = await self.trading_service.okx_fetcher.get_position_avg_price(user_id, symbol, direction)
                if position_avg_price:
                    position_avg_price = float(position_avg_price)
                else:
                    position_avg_price = current_price
            except Exception as e:
                logger.error(f"포지션 평균가 조회 실패: {str(e)}")
                position_avg_price = current_price

            if not is_DCA:
                #비헷지 모드일 떄, 포지션 조회. 있으면 오류 반환
                existing = await self.get_current_position(user_id, symbol, direction)
                print("[USER ID] : {}, [DIRECTION] : {}, [EXSITING] : {}".format(user_id, direction, existing))
                if existing:
                    raise ValueError(f"이미 {direction} 포지션이 존재합니다. 기존 포지션을 먼저 종료하세요.")
            #======================== DCA 이면서 HEDGE MODE일 때, 기존 포지션을 조회하지 않음.
            elif is_DCA and is_hedge:
                pass
            #======================== DCA일 때, 기존 포지션 조회
            else:
                existing = await self.get_current_position(user_id, symbol, direction)
                #======================== DCA일 때, 기존 포지션 조회 했는데 있으면, contracts_amount를 기존 포지션 사이즈에 더해서 업데이트
                #======================== DCA일 때, 기존 포지션 조회 했는데 없으면 contract_size를 그대로 사용 >> 아래 로직이 다 실행되니까, 새로운 포지션 생성임.
                if existing:
                    contracts_amount = safe_float(existing.size) + size #<-- 기존 포지션 사이즈에 더해서 업데이트
                    position_qty = await self.contract_size_to_qty(user_id, symbol, contracts_amount)
            # DCA시 기존 tp/sl주문 삭제
            if is_DCA:
                try:
                    await self.trading_service.order_manager.cancel_all_open_orders(self.trading_service.client, symbol, user_id, side=direction)
                except Exception as e:
                    logger.error(f"기존 TP/SL 삭제 실패: {str(e)}")
                    traceback.print_exc()
            # position_qty가 0 이하라면 오류 띄움
            if position_qty <= 0:
                raise ValueError(f"포지션 수량이 0 이하입니다. position_qty : {position_qty}, contracts_amount : {contracts_amount}")
            #최소 주문 수량 조회 및 반올림
            minimum_qty = await get_minimum_qty(symbol)
            position_qty = await round_to_qty(position_qty, symbol, minimum_qty)
            #최소 주문 수량보다 작으면 오류 띄움
            if position_qty < minimum_qty:
                raise ValueError(f"포지션 수량이 최소 주문 수량보다 작습니다. position_qty : {position_qty}, minimum_qty : {minimum_qty}")
            # # ========== 레버리지 설정 =============
            leverage_body = {
                "instId": symbol,
                "lever": str(int(leverage)),
                "mgnMode": "isolated"
            }
            try:
                await self.trading_service.client.set_leverage(
                    leverage=int(leverage),
                    symbol=symbol,
                    params={'mgnMode': 'isolated'}
                )
                logger.info(f"레버리지 설정 성공: user={user_id}, symbol={symbol}, leverage={leverage}")
            except Exception as e:
                logger.error(f"레버리지 설정 실패: user={user_id}, symbol={symbol}, leverage={leverage}, error={str(e)}")
                raise ValueError(f"레버리지 설정 실패. error={str(e)}")

            #=============== 주문 생성 로직 =================
            order_side = "buy" if direction == "long" else "sell"
            posSide = direction  # long or short
            # okx-specific parameter
            okx_params = {
                "tdMode": "isolated",
                "posSide": posSide,
            }

            # 주문 전송
            order_state = await self.trading_service.order_manager._try_send_order(
                user_id=user_id,
                symbol=symbol,
                side=order_side,  # "buy" or "sell"
                size=position_qty,
                order_type="market",
                pos_side=direction,  # long or short
                params=okx_params,
                max_retry=3,
                leverage=leverage,
                is_DCA=is_DCA
            )
            if order_state.status not in ["open", "closed"]:
                raise ValueError(f"주문 생성 실패: {order_state.message}")

            # Position 객체 생성
            position = Position(
                user_id=user_id,
                symbol=symbol,
                side=direction,
                size=contracts_amount,
                entry_price=safe_float(order_state.price),
                leverage=leverage,
                order_id=order_state.order_id,
                sl_order_id=None,
                sl_price=None,
                tp_order_ids=[],
                tp_prices=[]
            )

            # TP/SL 주문 생성
            await self.trading_service.tp_sl_creator._create_tp_sl_orders(
                user_id=user_id,
                symbol=symbol,
                position=position,
                contracts_amount=contracts_amount,
                side=direction,
                is_DCA=is_DCA,
                atr_value=None,
                current_price=current_price,
                is_hedge=is_hedge,
                hedge_tp_price=hedge_tp_price,
                hedge_sl_price=hedge_sl_price
            )

            # Redis 업데이트
            await TradingCache.save_position(position)

            # 히스토리 기록 (포지션이 새로 생성된 경우 또는 DCA 시에도 기록 가능)
            await record_trade_history_entry(
                user_id=str(user_id),
                symbol=symbol,
                side=direction,
                size=contracts_amount,
                entry_price=safe_float(order_state.price),
                sl_price=position.sl_price,
                leverage=leverage,
                timestamp=datetime.now().isoformat()
            )

            return position

        except Exception as e:
            logger.error(f"Position open failed - user={user_id}, symbol={symbol}, error={str(e)}")
            traceback.print_exc()
            raise

    async def close_position(
        self,
        user_id: str,
        symbol: str,
        side: str,
        order_id: Optional[str] = None,
        size: Optional[float] = None,
        reason: str = "manual",
        max_retry: int = 3,
        delay_sec: float = 1.0,
        debug: bool = False
    ) -> bool:
        """
        포지션 청산 (TP/SL 주문 취소 포함)

        Args:
            user_id: 사용자 ID
            symbol: 거래 심볼
            side: 포지션 방향 ('long' or 'short')
            order_id: 청산할 주문 ID (옵션)
            size: 청산할 수량 (None이면 전체)
            reason: 청산 사유 (기본값: "manual")
            max_retry: 최대 재시도 횟수
            delay_sec: 재시도 간 대기 시간
            debug: 디버그 모드 활성화 여부

        Returns:
            bool: 청산 성공 여부
        """
        try:
            # 1) 포지션 조회
            position = await self.get_current_position(user_id, symbol, side)
            logger.info(f"포지션 조회 결과: {position}")
            if not position:
                logger.warning(f"[{user_id}] 청산할 포지션이 없습니다. symbol={symbol}, side={side}")
                await TradingCache.remove_position(str(user_id), symbol, side)
                return False

            # 2) 기존 TP/SL 주문 취소
            try:
                logger.info(f"기존 TP/SL 주문 취소 시작")
                await self.trading_service.order_manager.cancel_all_open_orders(self.trading_service.client, symbol, user_id, side=side)
                logger.info(f"기존 TP/SL 주문 취소 완료")
            except Exception as e:
                logger.warning(f"[{user_id}] 기존 TP/SL 주문 취소 실패: {e}")

            # 3) 청산할 수량 결정
            if size is None:
                size = position.size  # 전체 청산
            else:
                size = min(size, position.size)  # 부분 청산

            # 4) 계약 수량을 실제 거래 수량으로 변환
            close_qty = await self.contract_size_to_qty(user_id, symbol, size)

            # 최소 주문 수량 반올림
            minimum_qty = await get_minimum_qty(symbol)
            close_qty = await round_to_qty(close_qty, symbol, minimum_qty)

            if close_qty < minimum_qty:
                logger.error(f"[{user_id}] 청산 수량이 최소 주문 수량보다 작습니다: {close_qty} < {minimum_qty}")
                return False

            # 5) 청산 주문 생성
            order_side = "sell" if side == "long" else "buy"

            okx_params = {
                "tdMode": "isolated",
                "posSide": side,  # 'long' or 'short'
                "reduceOnly": True  # 청산 주문임을 명시
            }

            logger.info(
                f"[{user_id}] 청산 주문 생성 - symbol={symbol}, side={order_side}, "
                f"qty={close_qty}, pos_side={side}"
            )

            order_state = await self.trading_service.order_manager._try_send_order(
                user_id=user_id,
                symbol=symbol,
                side=order_side,
                size=close_qty,
                order_type="market",
                pos_side=side,
                params=okx_params,
                max_retry=max_retry,
            )

            if order_state.status not in ["open", "closed"]:
                raise ValueError(f"청산 주문 실패: {order_state.message}")

            # 6) Exit 히스토리 업데이트
            await update_trade_history_exit(
                user_id=str(user_id),
                symbol=symbol,
                side=side,
                exit_price=safe_float(order_state.price),
                pnl=0.0,  # TODO: 실제 PnL 계산 로직 추가
                exit_timestamp=datetime.now().isoformat()
            )

            # 7) Redis에서 포지션 제거 (전체 청산 시)
            if size >= position.size:
                await TradingCache.remove_position(str(user_id), symbol, side)
                logger.info(f"[{user_id}] 포지션 제거 완료: {symbol}:{side}")
            else:
                # 부분 청산 시 사이즈 업데이트
                position.size -= size
                await TradingCache.save_position(position)
                logger.info(f"[{user_id}] 부분 청산 완료. 남은 수량: {position.size}")

            # 8) 텔레그램 알림
            try:
                telegram_content = (
                    f"✅ 포지션 청산 완료\n\n"
                    f"사용자: {user_id}\n"
                    f"심볼: {symbol}\n"
                    f"방향: {side}\n"
                    f"청산 수량: {size}\n"
                    f"청산 가격: {order_state.price}\n"
                    f"사유: {reason}"
                )
                await send_telegram_message(
                    message=telegram_content,
                    user_id=user_id,
                    symbol=symbol,
                    direction=side,
                    debug=True
                )
            except Exception as e:
                logger.error(f"텔레그램 전송 실패: {str(e)}")

            return True

        except Exception as e:
            logger.error(f"Position close failed - user={user_id}, symbol={symbol}, error={str(e)}")
            raise


