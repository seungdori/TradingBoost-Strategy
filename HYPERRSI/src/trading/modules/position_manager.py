# HYPERRSI/src/trading/modules/position_manager.py
"""
Position Manager

포지션 오픈/클로즈 및 포지션 조회 관리
"""

import asyncio
import json
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from shared.cache import TradingCache
from HYPERRSI.src.trading.error_message import map_exchange_error
from HYPERRSI.src.trading.models import OrderStatus, Position
from HYPERRSI.src.trading.stats import record_trade_history_entry, update_trade_history_exit
from HYPERRSI.telegram_message import send_telegram_message
from shared.database.redis_helper import get_redis_client
from shared.logging import get_logger
from shared.utils import (
    convert_bool_to_string,
    get_lot_sizes,
    get_minimum_qty,
    get_perpetual_instruments,
    round_to_qty,
    safe_float,
)
from shared.utils.symbol_helpers import normalize_symbol

logger = get_logger(__name__)

# Dynamic redis_client access


class PositionManager:
    """포지션 오픈/클로즈 관리 서비스"""

    def __init__(self, trading_service):
        """
        Args:
            trading_service: TradingService 인스턴스
        """
        self.trading_service = trading_service
        self._position_mode_cache = {}  # 계정별 포지션 모드 캐시

    async def get_position_mode(self, user_id: str) -> str:
        """
        계정의 포지션 모드 조회 (캐싱)

        Returns:
            'long_short_mode': Hedge Mode (양방향)
            'net_mode': Net Mode (단방향)
        """
        if user_id in self._position_mode_cache:
            return self._position_mode_cache[user_id]

        try:
            # OKX API: GET /api/v5/account/config
            account_config = await self.trading_service.client.privateGetAccountConfig()

            # Response structure: {"code":"0","data":[{"posMode":"long_short_mode",...}],"msg":""}
            if account_config and 'data' in account_config and len(account_config['data']) > 0:
                pos_mode = account_config['data'][0].get('posMode', 'net_mode')
                self._position_mode_cache[user_id] = pos_mode
                logger.info(f"계정 포지션 모드: user={user_id}, mode={pos_mode}")
                return pos_mode
            else:
                logger.warning(f"포지션 모드 조회 실패, 기본값 사용: user={user_id}")
                return 'net_mode'  # 기본값
        except Exception as e:
            logger.error(f"포지션 모드 조회 에러: user={user_id}, error={str(e)}")
            return 'net_mode'  # 에러 시 안전한 기본값

    async def contract_size_to_qty(self, user_id: str, symbol: str, contracts_amount: float) -> float:
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
                        positions = await self.trading_service.okx_fetcher.fetch_okx_position(user_id, symbol, side=pos_side, debug_entry_number=1)
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
                    # positions는 {side: {...}} 형식이므로 pos_side를 직접 확인
                    if pos_side in positions:
                        pos_data = positions[pos_side]

                        # symbol 일치 여부 확인 (두 가지 형식 모두 체크)
                        # pos_data["symbol"]은 "ETH/USDT:USDT" 또는 "ETH-USDT-SWAP" 가능
                        pos_symbol = pos_data.get("symbol", "")

                        # 정규화해서 비교 (상단에서 import 완료)
                        try:
                            normalized_input = normalize_symbol(symbol, target_format="ccxt")
                            normalized_pos = normalize_symbol(pos_symbol, target_format="ccxt")
                            symbol_match = (normalized_input == normalized_pos)
                        except Exception:
                            # 정규화 실패 시 직접 비교
                            symbol_match = (pos_symbol == symbol)

                        if symbol_match:
                            position = Position(
                                symbol=pos_data["symbol"],
                                side=pos_data["side"],
                                size=safe_float(pos_data.get("size", 0)),
                                contracts_amount=safe_float(pos_data.get("size", 0)),
                                entry_price=safe_float(pos_data.get("entry_price", 0)),
                                leverage=safe_float(pos_data.get("leverage", 1)),
                                sl_order_id=pos_data.get("sl_order_id"),
                                sl_price=safe_float(pos_data.get("sl_price")) if pos_data.get("sl_price") else None,
                                tp_order_ids=pos_data.get("tp_order_ids", []),
                                tp_prices=pos_data.get("tp_prices", []),
                                order_id=pos_data.get("order_id")
                            )
                            return position
                    # 정확한 symbol + side를 찾지 못했으면 None
                    return None
                # symbol만 주어진 경우
                elif symbol:
                    # positions는 {side: {...}} 형식이므로 직접 side를 확인
                    pos_data = None
                    if "long" in positions:
                        pos_data = positions["long"]
                    elif "short" in positions:
                        pos_data = positions["short"]

                    if not pos_data:
                        return None

                    position = Position(
                        symbol=pos_data["symbol"],
                        side=pos_data["side"],
                        size=safe_float(pos_data.get("size", 0)),
                        contracts_amount=safe_float(pos_data.get("size", 0)),
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
                    # positions는 {side: {...}} 형식이므로 직접 순회
                    for side, pos_data in positions.items():
                        if side in ['long', 'short']:  # 유효한 side인지 확인
                            position = Position(
                                symbol=pos_data["symbol"],
                                side=pos_data["side"],
                                size=safe_float(pos_data.get("size", 0)),
                                contracts_amount=safe_float(pos_data.get("size", 0)),
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

    async def get_contract_size(self, user_id: str, symbol: str) -> float:
        """계약 크기 조회"""
        contract_info = await self.trading_service.market_data.get_contract_info(user_id=user_id, symbol=symbol)
        return safe_float(contract_info.get('contractSize', 1))

    async def open_position(
        self,
        user_id: str,
        symbol: str,
        direction: str,
        size: float,  #contracts_amount로 들어옴.
        leverage: float=10.0,
        settings: Dict[str, Any] = {},
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

        redis = await get_redis_client()
        print(f"direction: {direction}, size: {size}, leverage: {leverage}, size : {size}")
        contracts_amount = size
        position_qty = await self.contract_size_to_qty(user_id, symbol, contracts_amount)

        # 이번 진입 수량 보관 (텔레그램 메시지용)
        entry_size = size
        entry_qty = position_qty

        tp_data: List[Any] = []
        try:
            if direction not in ['long', 'short']:
                raise ValueError("direction must be either 'long' or 'short'")
            settings_key = f"user:{user_id}:settings"
            settings_str = await redis.get(settings_key)
            if not settings_str:
                raise ValueError("설정 정보를 찾을 수 없습니다.")
            settings = json.loads(settings_str)
            # 설정 가져오기
            position_key = f"user:{user_id}:position:{symbol}:{direction}"
            cooldown_key = f"user:{user_id}:cooldown:{symbol}:{direction}"
            if str(user_id) != "1709556958" and not is_hedge:
                if await redis.get(cooldown_key):
                    ttl = await redis.ttl(cooldown_key)
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
                    # direction을 order side로 변환 (long -> sell, short -> buy)
                    # TP/SL은 포지션과 반대 방향으로 걸림
                    cancel_side = "sell" if direction == "long" else "buy"
                    await self.trading_service.order_manager.cancel_all_open_orders(
                        self.trading_service.client, symbol, user_id, side=cancel_side
                    )
                    logger.info(f"✅ DCA 진입 전 기존 TP/SL 주문 취소 완료: user={user_id}, symbol={symbol}, side={cancel_side}")
                except Exception as e:
                    logger.error(f"기존 TP/SL 삭제 실패: {str(e)}")
                    traceback.print_exc()
            # position_qty가 0 이하라면 오류 띄움
            if position_qty <= 0:
                raise ValueError(f"포지션 수량이 0 이하입니다. position_qty : {position_qty}, contracts_amount : {contracts_amount}")
            #최소 주문 수량 조회
            minimum_qty = await get_minimum_qty(symbol)
            print(f" ")
            print(position_qty)
            # position_qty는 이미 contract_size_to_qty()를 통해 수량(qty)으로 변환되었으므로
            # round_to_qty를 호출하면 안 됨 (round_to_qty는 qty -> contracts로 변환하는 함수)
            # 그냥 소수점만 반올림하면 됨
            position_qty = round(position_qty, 8)
            print(f" ")
            print(position_qty)
            #최소 주문 수량보다 작으면 오류 띄움
            if position_qty < minimum_qty:
                raise ValueError(f"포지션 수량이 최소 주문 수량보다 작습니다. position_qty : {position_qty}, minimum_qty : {minimum_qty}")
            # # ========== 레버리지 설정 =============
            # 포지션 모드 확인
            position_mode = await self.get_position_mode(user_id)

            # Net Mode: posSide 제거, Hedge Mode: posSide 필수
            leverage_params = {'mgnMode': 'isolated'}
            if position_mode == 'long_short_mode':
                leverage_params['posSide'] = direction  # 'long' or 'short'

            try:
                await self.trading_service.client.set_leverage(
                    leverage=int(leverage),
                    symbol=symbol,
                    params=leverage_params
                )
                logger.info(f"레버리지 설정 성공: user={user_id}, symbol={symbol}, leverage={leverage}, direction={direction}, mode={position_mode}")
            except Exception as e:
                logger.error(f"레버리지 설정 실패: user={user_id}, symbol={symbol}, leverage={leverage}, direction={direction}, mode={position_mode}, error={str(e)}")
                raise ValueError(f"레버리지 설정 실패. error={str(e)}")

            #=============== 주문 생성 로직 =================
            order_side = "buy" if direction == "long" else "sell"
            posSide = direction  # long or short
            # okx-specific parameter
            okx_params = {
                "tdMode": "isolated",
                "posSide": posSide,
            }

            # 주문 전송 (DCA일 때는 추가 진입 수량만 주문, 아닐 때는 전체 수량)
            order_size = entry_size  # 이번 진입 수량
            order_state = await self.trading_service.order_manager._try_send_order(
                user_id=user_id,
                symbol=symbol,
                side=order_side,  # "buy" or "sell"
                size=order_size,
                order_type="market",
                direction=direction,  # long or short - correct parameter name
                leverage=leverage
            )
            # 실패 상태만 에러로 처리
            if order_state.status in ["canceled", "rejected", "expired"]:
                # OrderStatus has no 'message' attribute - use status and order_id instead
                error_detail = f"status={order_state.status}, order_id={order_state.order_id}"
                raise ValueError(f"주문 생성 실패: {error_detail}")

            # Position 객체 생성
            filled_contracts = safe_float(order_state.filled_size)
            if filled_contracts == 0.0:
                filled_contracts = safe_float(order_state.size) or entry_size
            filled_position_qty = await self.contract_size_to_qty(user_id, symbol, filled_contracts)

            # DCA일 때는 총 포지션 수량을 계산 (기존 + 이번 진입)
            # TP/SL은 총 포지션에 대해 걸어야 함
            if is_DCA and existing:
                total_position_size = safe_float(existing.size) + filled_contracts
            else:
                total_position_size = filled_contracts

            position = Position(
                symbol=symbol,
                side=direction,
                size=total_position_size,  # 총 포지션 수량
                contracts_amount=total_position_size,
                entry_price=safe_float(order_state.avg_fill_price),
                leverage=leverage,
                order_id=order_state.order_id,
                sl_order_id=None,
                sl_price=None,
                tp_order_ids=[],
                tp_prices=[],
                last_filled_price=safe_float(order_state.avg_fill_price),  # 체결 가격 설정
                position_qty=filled_position_qty
            )

            # TP/SL 주문 생성 (총 포지션 수량 사용)
            await self.trading_service.tp_sl_creator._create_tp_sl_orders(
                user_id=user_id,
                symbol=symbol,
                position=position,
                contracts_amount=total_position_size,  # 총 포지션 수량
                side=direction,
                is_DCA=is_DCA,
                atr_value=None,
                current_price=current_price,
                is_hedge=is_hedge,
                hedge_tp_price=hedge_tp_price,
                hedge_sl_price=hedge_sl_price
            )

            # Redis 업데이트
            # TODO: TradingCache.save_position does not exist - need to implement or use set_position
            # await TradingCache.save_position(position)

            # 히스토리 기록 (포지션이 새로 생성된 경우 또는 DCA 시에도 기록 가능)
            await record_trade_history_entry(
                user_id=str(user_id),
                symbol=symbol,
                side=direction,
                size=filled_contracts,
                entry_price=safe_float(order_state.avg_fill_price),
                leverage=leverage,
                order_id=order_state.order_id or "",
                last_filled_price=safe_float(order_state.avg_fill_price)
            )

            # 텔레그램 포지션 오픈 성공 알림 (백그라운드 태스크로 실행)
            async def _send_position_open_notification():
                """포지션 오픈 알림을 전송하는 백그라운드 태스크"""
                try:
                    logger.info(f"📤 [{user_id}] 포지션 오픈 알림 전송 시작...")

                    # Redis에서 최신 TP/SL 정보 조회
                    position_key = f"user:{user_id}:position:{symbol}:{direction}"
                    position_data = await redis.hgetall(position_key)
                    logger.debug(f"📋 [{user_id}] Redis position_data keys: {list(position_data.keys())}")

                    tp_prices_str = position_data.get("tp_prices", "")
                    sl_price = position_data.get("sl_price", "N/A")
                    logger.debug(f"📊 [{user_id}] TP prices string: {tp_prices_str}, SL price: {sl_price}")

                    # TP 가격 포맷팅
                    if tp_prices_str:
                        tp_prices = [float(p) for p in tp_prices_str.split(",") if p]
                        tp_text = "\n".join([f"  TP{i+1}: {price:.2f}" for i, price in enumerate(tp_prices)])
                        logger.debug(f"💰 [{user_id}] TP formatted: {tp_text}")
                    else:
                        tp_text = "  설정 안 됨"
                        logger.warning(f"⚠️ [{user_id}] TP prices not set")

                    # SL 가격 포맷팅
                    sl_text = f"{float(sl_price):.2f}" if sl_price != "N/A" else "설정 안 됨"
                    logger.debug(f"🛡️ [{user_id}] SL formatted: {sl_text}")

                    direction_emoji = "🟢" if direction == "long" else "🔴"
                    telegram_content = (
                        f"{direction_emoji} 포지션 오픈 완료\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"심볼: {symbol}\n"
                        f"방향: {direction.upper()}\n"
                        f"수량: {entry_qty:.6f} ({entry_size:.2f} 계약)\n"
                        f"진입가: {safe_float(order_state.avg_fill_price):.2f}\n"
                        f"레버리지: {leverage}x\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"익절(TP):\n{tp_text}\n"
                        f"손절(SL): {sl_text}\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"주문ID: {order_state.order_id}"
                    )
                    logger.debug(f"📝 [{user_id}] Telegram message prepared (length: {len(telegram_content)})")

                    await send_telegram_message(
                        message=telegram_content,
                        okx_uid=str(user_id)
                    )
                    logger.info(f"✅ 포지션 오픈 알림 전송 완료: user={user_id}, symbol={symbol}, direction={direction}")
                except Exception as e:
                    logger.error(f"❌ [{user_id}] 텔레그램 포지션 오픈 알림 전송 실패: {str(e)}")
                    traceback.print_exc()

            # 백그라운드에서 알림 전송 (메인 로직 블로킹 방지)
            asyncio.create_task(_send_position_open_notification())

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
                size = position.size  # 전체 청산 (contracts)
            else:
                size = min(size, position.size)  # 부분 청산 (contracts)

            # 4) 사용자 알림용 실제 수량 계산 (주문 전송은 contracts 기준)
            close_qty_display = await self.contract_size_to_qty(user_id, symbol, size)
            close_qty_display = round(close_qty_display, 8)

            # 청산 주문(reduceOnly=True)은 최소 주문 수량 제한을 받지 않음
            # 포지션 전체를 청산하는 경우 거래소가 자동으로 처리
            logger.info(f"[{user_id}] 청산 수량: {close_qty_display} (계약: {size})")

            # 5) 청산 주문 생성
            order_side = "sell" if side == "long" else "buy"

            okx_params = {
                "tdMode": "isolated",
                "posSide": side,  # 'long' or 'short'
                "reduceOnly": True  # 청산 주문임을 명시
            }

            logger.info(
                f"[{user_id}] 청산 주문 생성 - symbol={symbol}, side={order_side}, "
                f"contracts={size}, pos_side={side}"
            )

            order_state = await self.trading_service.order_manager._try_send_order(
                user_id=user_id,
                symbol=symbol,
                side=order_side,
                size=size,
                order_type="market",
                direction=side  # long or short - correct parameter name
            )

            if order_state.status not in ["open", "closed"]:
                # OrderStatus has no 'message' attribute - use status and order_id instead
                error_detail = f"status={order_state.status}, order_id={order_state.order_id}"
                raise ValueError(f"청산 주문 실패: {error_detail}")

            # 6) Exit 히스토리 업데이트
            await update_trade_history_exit(
                user_id=str(user_id),
                symbol=symbol,
                order_id=order_state.order_id or "",
                exit_price=safe_float(order_state.avg_fill_price),
                pnl=0.0,  # TODO: 실제 PnL 계산 로직 추가
                close_type="manual",
                comment=reason
            )

            # 7) Redis에서 포지션 제거 (전체 청산 시)
            if size >= position.size:
                await TradingCache.remove_position(str(user_id), symbol, side)
                logger.info(f"[{user_id}] 포지션 제거 완료: {symbol}:{side}")
            else:
                # 부분 청산 시 사이즈 업데이트
                position.size -= size
                # TODO: TradingCache.save_position does not exist - need to implement or use set_position
                # await TradingCache.save_position(position)
                logger.info(f"[{user_id}] 부분 청산 완료. 남은 수량: {position.size}")

            # 8) 텔레그램 알림
            try:
                telegram_content = (
                    f"✅ 포지션 청산 완료\n\n"
                    f"사용자: {user_id}\n"
                    f"심볼: {symbol}\n"
                    f"방향: {side}\n"
                    f"청산 수량: {close_qty_display} ({size:.2f} 계약)\n"
                    f"청산 가격: {order_state.avg_fill_price}\n"
                    f"사유: {reason}"
                )
                await send_telegram_message(
                    message=telegram_content,
                    okx_uid=str(user_id),
                    debug=True
                )
            except Exception as e:
                logger.error(f"텔레그램 전송 실패: {str(e)}")

            return True

        except Exception as e:
            logger.error(f"Position close failed - user={user_id}, symbol={symbol}, error={str(e)}")
            raise
