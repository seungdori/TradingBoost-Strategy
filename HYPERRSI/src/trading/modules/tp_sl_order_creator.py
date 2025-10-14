# HYPERRSI/src/trading/modules/tp_sl_order_creator.py
"""
TP/SL Order Creator

TP(익절)와 SL(손절) 주문 생성 및 관리
"""

import json
import logging
import time
import traceback
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

from HYPERRSI.src.trading.error_message import map_exchange_error
from HYPERRSI.src.trading.models import Position
from HYPERRSI.src.trading.modules.trading_utils import get_decimal_places
from HYPERRSI.telegram_message import send_telegram_message
from shared.database.redis_helper import get_redis_client
from shared.logging import get_logger
from shared.utils import get_minimum_qty, safe_float

# Lazy import for circular dependency resolution
if TYPE_CHECKING:
    from HYPERRSI.src.trading.monitoring import check_order_status, update_order_status

logger = get_logger(__name__)


# Module-level attribute for backward compatibility
def __getattr__(name):
    if name == "redis_client":
        return get_redis_client()
    raise AttributeError(f"module has no attribute {name}")


class TPSLOrderCreator:
    """TP/SL 주문 생성 서비스"""

    def __init__(self, trading_service):
        """
        Args:
            trading_service: TradingService 인스턴스
        """
        self.trading_service = trading_service
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

        redis = await get_redis_client()
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

            settings_str = await redis.get(f"user:{user_id}:settings")
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

            existing_data = await redis.hgetall(position_key)
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
                                        # Lazy import to avoid circular dependency
                                        from HYPERRSI.src.trading.monitoring import check_order_status

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
                                    await redis.delete(monitor_key)
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
                                # Lazy import to avoid circular dependency
                                from HYPERRSI.src.trading.monitoring import check_order_status

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
                            await redis.delete(monitor_key)
                            logger.info(f"[DCA] 모니터링 데이터 삭제 완료: {monitor_key}")
                        except Exception as e:
                            logger.error(f"[DCA] SL 주문 취소 실패: {existing_sl_order_id}, {str(e)}")

                    # Redis에서 TP/SL 관련 필드 삭제
                    await redis.hdel(
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
            position_data = await redis.hgetall(position_key)
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
                            
                            await redis.hset(monitor_key, mapping=monitor_data)
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
                await redis.hset(position_key, mapping=tp_data)
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
                    await redis.hset(position_key, mapping=tp_data)
                    dual_side_key = f"user:{user_id}:{symbol}:dual_side_position"
                    await redis.hset(dual_side_key, mapping=tp_data)
                    
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
                    
                    await redis.hset(monitor_key, mapping=monitor_data)
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
                        dca_count = await redis.get(dca_count_key)
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
                        await redis.hset(position_key, mapping=sl_data)
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
                        
                        await redis.hset(monitor_key, mapping=monitor_data)
                        logger.info(f"[SL] 모니터링 데이터 저장 완료: {monitor_key}")

                    except Exception as e:
                        error_msg = map_exchange_error(e)
                        traceback.print_exc()
                        logger.error(f"SL 주문 생성 실패: {str(e)}")
                        await send_telegram_message((f"⚠️ 손절 주문 생성 실패\n"f"━━━━━━━━━━━━━━━\n"f"{error_msg}\n"f"가격: {position.sl_price:.2f}\n"f"수량: {position.position_qty}"),okx_uid=user_id,debug=True)
                        sl_order_id = None
            if is_hedge and (hedge_sl_price is not None):
                dual_side_settings_key = f"user:{user_id}:dual_side"
                dual_side_settings = await redis.hgetall(dual_side_settings_key)
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
                        await redis.hset(position_key, mapping=sl_data)

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

                        await redis.hset(monitor_key, mapping=monitor_data)
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
                    await redis.hdel(position_key, "sl_price", "sl_order_id", "sl_size", "sl_contracts_amount", "sl_position_qty")
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
    
