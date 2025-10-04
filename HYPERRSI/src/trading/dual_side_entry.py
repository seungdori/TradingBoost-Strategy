# src/trading/dual_side_entry.py

import json
import traceback
from typing import Optional
import os
from datetime import datetime
import ccxt
from HYPERRSI.src.helpers.order_helper import contracts_to_qty
from HYPERRSI.src.trading.trading_service import TradingService
from HYPERRSI.src.utils.redis_helper import prepare_for_redis, parse_from_redis, DUAL_SIDE_SETTINGS_SCHEMA
from HYPERRSI.src.api.routes.position import OpenPositionRequest, open_position_endpoint
from HYPERRSI.src.api.routes.order import close_position
from HYPERRSI.src.bot.telegram_message import send_telegram_message
from HYPERRSI.src.trading.error_message import map_exchange_error
from HYPERRSI.src.core.logger import get_logger, log_order, log_dual_side_debug
from HYPERRSI.src.api.routes.order import ClosePositionRequest, cancel_algo_orders
import json
from HYPERRSI.src.core.error_handler import log_error
import asyncio
from HYPERRSI.src.services.redis_service import RedisService, redis_client

logger = get_logger(__name__)
redis_service = RedisService()


async def set_default_dual_side_entry_settings(user_id: str):
    """
    양방향 진입 설정값들을 기본값으로 설정
    """
    try:
        settings = await get_user_dual_side_settings(user_id)
        if not settings:
            from shared.constants.default_settings import DEFAULT_DUAL_SIDE_ENTRY_SETTINGS
            # prepare_for_redis를 사용하여 안전하게 변환
            settings = prepare_for_redis(DEFAULT_DUAL_SIDE_ENTRY_SETTINGS)
            await redis_client.hset(f"user:{user_id}:dual_side", mapping=settings)
    except Exception as e:
        logger.error(f"Failed to set default dual side entry settings: {str(e)}")
        return False
    return True


async def get_last_dca_level(user_id: str, symbol: str, position_side: str) -> float | None:
    try:
        dca_key = f"user:{user_id}:position:{symbol}:{position_side}:dca_levels"
        dca_levels = await redis_client.lrange(dca_key, 0, -1)
        
        if not dca_levels:
            return None
            
        # 문자열 리스트를 float로 변환
        dca_levels = [float(level) for level in dca_levels]
        
        # long 포지션이면 가장 낮은 값이 마지막 DCA
        # short 포지션이면 가장 높은 값이 마지막 DCA
        if position_side == "long":
            return min(dca_levels)
        else:  # short
            return max(dca_levels)
            
    except Exception as e:
        logger.error(f"Error getting last DCA level: {e}")
        return None

def validate_dual_side_settings(settings: dict) -> bool:
    """
    양방향 설정값들의 유효성을 검증
    """
    required_keys = [
        'use_dual_side_entry',
        'dual_side_entry_trigger',
        'dual_side_entry_ratio_type',
        'dual_side_entry_ratio_value',

        'dual_side_entry_tp_trigger_type',  # TP 설정 모드
        'dual_side_entry_tp_value',         # TP 퍼센트값 (percent일 때)
        'dual_side_entry_sl_trigger_type',  # SL 설정 모드
        'dual_side_entry_sl_value',         # SL 퍼센트값 (percent일 때)
        'activate_tp_sl_after_all_dca'      # 모든 DCA 진입 후에 TP/SL 활성화 여부
    ]
    
    for key in required_keys:
        if key not in settings:
            logger.error(f"Missing required setting: {key}")
            return False
            
    return True

async def get_user_dual_side_settings(user_id: str) -> dict:
    """
    사용자의 양방향 설정을 Redis에서 가져옴
    """
    settings_key = f"user:{user_id}:dual_side"
    raw_settings = await redis_client.hgetall(settings_key)
    
    if not raw_settings:
        return {}
    
    # parse_from_redis를 사용하여 타입 변환
    settings = parse_from_redis(raw_settings, DUAL_SIDE_SETTINGS_SCHEMA)
    
    return settings


async def get_pyramiding_limit(user_id: str) -> int:
    """
    user:{user_id}:settings에서 pyramiding_limit 읽어오기
    """
    settings = await redis_service.get_user_settings(user_id)
    pyramiding_limit = settings.get('pyramiding_limit', 1)
    return pyramiding_limit


async def manage_dual_side_entry(
    user_id: str,
    symbol: str,
    current_price: float,
    dca_order_count: int,
    main_position_side: str,  # 현재 보유중인 메인 포지션 방향
    settings: dict,
    trading_service: TradingService,
    exchange: ccxt.Exchange,  # ccxt 익스체인지 객체 (OKX)
) -> None:
    """
    양방향 엔트리를 관리하는 메인 함수입니다.
    다음과 같은 로직을 분리하여 관리합니다:
    1) 언제 양방향 포지션에 진입할지(몇 번째 진입 시점인지)
    2) 현재 포지션 크기의 몇 배(또는 몇 %)로 진입할지
    3) 양방향 포지션을 언제 익절(TP)할지

    settings 안에 다음과 같은 설정값이 들어있다고 가정합니다:
      - use_dual_side_entry: bool
      - dual_side_entry_trigger: int      (예: 2 => 두 번째 진입에서 양방향 진입)
      - dual_side_entry_ratio_type: str       (예: "percent_of_position", "fixed_amount", etc.)
      - dual_side_entry_ratio_value: float    (포지션 또는 자본의 몇 % / 혹은 고정 금액)
      - dual_side_entry_tp_trigger_type: str  (예: "price", "percent_change", "last_dca_on_position")
      - dual_side_entry_tp_value: float       (TP 기준값. 가격 또는 퍼센트 변화)
    
    매개변수:
        - user_id: 사용자 식별자
        - symbol: 거래 심볼
        - current_price: 현재 가격
        - dca_order_count: 현재까지 진입이 몇 번 일어났는지
        - side: 현재 보유 중인 포지션의 방향("long"|"short") 
        - settings: 사용자 설정(dict)
        - trading_service: 실제 주문/포지션 관리를 담당할 TradingService 인스턴스

    리턴값:
        - None (내부에서 양방향 포지션을 진입하거나, TP를 실행)
    """
    #asyncio.create_task(send_telegram_message(f"[{user_id}] 양방향 진입 관리 함수 시작", okx_uid, debug=True))
    # 함수 시작 로깅
    log_dual_side_debug(
        user_id=user_id,
        symbol=symbol,
        function_name='manage_dual_side_entry',
        message='양방향 진입 관리 함수 시작',
        level='INFO',
        current_price=current_price,
        dca_order_count=dca_order_count,
        main_position_side=main_position_side,
        settings=settings,
    )

    # (A) 양방향 기능이 활성화되어 있는지 확인
    try:
        print("="*30)
        print("position_mode_info 조회 시작")
        print("="*30)
        position_mode_info = await exchange.fetch_position_mode(symbol=symbol)
        #print(f"position_mode_info: {position_mode_info}")
        is_hedge_mode = position_mode_info.get('hedged', False)
        
        log_dual_side_debug(
            user_id=user_id,
            symbol=symbol,
            function_name='manage_dual_side_entry',
            message='포지션 모드 정보 조회 완료',
            level='DEBUG',
            position_mode_info=position_mode_info,
            is_hedge_mode=is_hedge_mode
        )

        if not is_hedge_mode:
            # 헷지모드가 아니라면 안내 메시지 후 종료
            log_dual_side_debug(
                user_id=user_id,
                symbol=symbol,
                function_name='manage_dual_side_entry',
                message='헷지 모드가 활성화되어 있지 않아 양방향 진입 불가',
                level='WARNING'
            )
            
            asyncio.create_task(send_telegram_message(
                f"⚠️ 현재 포지션 모드는 헷지 모드가 아닙니다.\n"
                "⚠️ 현재 포지션 모드는 헷지 모드가 아닙니다.\n"
                "이 기능은 헷지 모드에서만 사용 가능합니다.\n\n"
                "거래소 설정에서 헷지 모드로 변경한 뒤 봇(프로그램)을 재시작해야 적용됩니다.", 
                user_id
            ))
            return
    except Exception as e:
        log_dual_side_debug(
            user_id=user_id,
            symbol=symbol,
            function_name='manage_dual_side_entry',
            message='포지션 모드 조회 실패',
            level='ERROR',
            exception=e
        )
        
        logger.error(f"[{user_id}] 포지션 모드 조회 실패: {str(e)}")
        is_hedge_mode = False
    #print(f"is_hedge_mode: {is_hedge_mode}")
    try:
        dual_side_settings = await get_user_dual_side_settings(user_id)
        #print(f"dual side settings: {dual_side_settings}")
        
        log_dual_side_debug(
            user_id=user_id,
            symbol=symbol,
            function_name='manage_dual_side_entry',
            message='양방향 설정 조회 완료',
            level='DEBUG',
            dual_side_settings=dual_side_settings
        )
        
        dual_side_enabled = dual_side_settings.get('use_dual_side_entry', False)
        #asyncio.create_task(send_telegram_message(f"[{user_id}] dual_side_enabled: {dual_side_enabled}", user_id, debug=True))
        if not dual_side_enabled:
            log_dual_side_debug(
                user_id=user_id,
                symbol=symbol,
                function_name='manage_dual_side_entry',
                message='양방향 진입 기능이 비활성화되어 있음',
                level='INFO'
            )
            print("양방향 진입 기능이 비활성화되어 있음")
            return  # 기능이 꺼져 있다면 아무것도 하지 않음.
        
   
        # (B) 양방향 진입 시점(DCA 트리거) 확인
        trigger_index = dual_side_settings.get('dual_side_entry_trigger', 999)
        dual_side_pyramiding_limit = dual_side_settings.get('dual_side_pyramiding_limit', 1)

        # 현재 dual_side 진입 카운트 확인
        dual_side_count_key = f"user:{user_id}:{symbol}:dual_side_count"
        dual_side_count = await redis_client.get(dual_side_count_key)
        dual_side_count = int(dual_side_count) if dual_side_count else 0
        

            
        # DCA 몇 번째 진입에서 실행할지
        try:
            dca_order_count = await redis_client.get(f"user:{user_id}:position:{symbol}:{main_position_side}:dca_count")
            if not dca_order_count:
                dca_order_count = 1
        except Exception as e:
            logger.error(f"dca_order_count 조회 실패: {str(e)}")
            dca_order_count = 1
        print("여기 분기까지 안들어오는 것 같다.")
        dca_order_count = int(dca_order_count)
        print(f"[{user_id}] dca_order_count: {dca_order_count}, trigger_index: {trigger_index}")
        if (dca_order_count ) < int(trigger_index):
            print(f"아직 양방향 진입 미도달. trigger_index: {trigger_index}, dca_order_count: {dca_order_count}")
            return  # 조건 불충족
        # (C) 현재 보유 중인 (메인) 포지션 정보 확인
        existing_position = await trading_service.get_current_position(user_id, symbol, main_position_side)
        
        print(f"existing_position: {existing_position}")
        if not existing_position:

            await send_telegram_message(f"이상한 부분 발견 : 양방향 조건인데, 메인 포지션이 없음", user_id, debug=True)
            return
        existing_size = existing_position.size  # 메인 포지션 수량
        print(f"existing_size: {existing_size}")
        if existing_size <= 0.02:

            
            await send_telegram_message(f"이상한 부분 발견 : 양방향 조건인데, 메인 포지션이 없음", user_id, debug=True)
            return
    
        # (E) 헷지 포지션 규모 계산
        ratio_type = dual_side_settings.get('dual_side_entry_ratio_type', 'percent_of_position')
        dual_side_entry_ratio_value = dual_side_settings.get('dual_side_entry_ratio_value', 30)
        
        # 헷지 포지션 방향 (반대방향)
        opposite_side = "long" if main_position_side == "short" else "short"
        
        # 현재 헷지 포지션 확인
        existing_hedge_position = await trading_service.get_current_position(user_id, symbol, opposite_side)
        existing_hedge_size = existing_hedge_position.size if existing_hedge_position else 0
        print(f"existing_hedge_size: {existing_hedge_size}")
        
        print(f"dual_side_enabled: {dual_side_enabled}")
        if not validate_dual_side_settings(dual_side_settings):
            log_dual_side_debug(
                user_id=user_id,
                symbol=symbol,
                function_name='manage_dual_side_entry',
                message='양방향 설정이 올바르지 않음',
                level='WARNING',
                invalid_settings=dual_side_settings
            )
            
            print(f"Invalid dual side settings for user {user_id}")
            await send_telegram_message(f"⚠️ 양방향 설정이 올바르지 않습니다.\n""/dual_settings 명령어로 설정을 확인해주세요.",user_id)
            return
        
        
        if ratio_type == 'percent_of_position':
            if dual_side_entry_ratio_value <= 1:
                dual_side_entry_ratio_value = dual_side_entry_ratio_value * 100
            
            # 목표 헷지 포지션 크기 계산
            target_hedge_size = max(float(existing_size) * float(dual_side_entry_ratio_value)*0.01, 0.05)
            
            # 추가로 필요한 헷지 포지션 크기 계산
            new_position_size = max(target_hedge_size - existing_hedge_size, 0.05)
            
            print(f"target_hedge_size: {target_hedge_size}, new_position_size: {new_position_size}")
        else:
            target_hedge_size = max(float(dual_side_entry_ratio_value), 0.05)  # 고정 수량
            new_position_size = max(target_hedge_size - existing_hedge_size, 0.05)  # 필요한 추가 헷지 크기
            
        # 이미 충분한 헷지 포지션이 있는 경우 추가 진입하지 않음
        if existing_hedge_size >= target_hedge_size:
            print(f"이미 충분한 헷지 포지션 있음. 추가 진입 불필요 (기존: {existing_hedge_size}, 목표: {target_hedge_size})")
            return
            
        print(f"new_position_size: {new_position_size}" )
        # (F) 헷지 포지션 방향 (반대방향) - 위로 이동함
        dual_side_entry_tp_trigger_type = dual_side_settings.get('dual_side_entry_tp_trigger_type', 'percent')
        close_on_last_dca = dual_side_entry_tp_trigger_type == 'last_dca_on_position'
        
        log_dual_side_debug(
            user_id=user_id,
            symbol=symbol,
            function_name='manage_dual_side_entry',
            message='헷지 포지션 정보 계산 완료',
            level='DEBUG',
            opposite_side=opposite_side,
            close_on_last_dca=close_on_last_dca,
            tp_trigger_type=dual_side_entry_tp_trigger_type
        )
        
        
        pyramiding_limit = await get_pyramiding_limit(user_id)
        is_last_dca = (dca_order_count) >= pyramiding_limit
        logger.info(f"[❤️‍🔥마지막 DCA여부 : {is_last_dca}] dca_order_count: {dca_order_count}, pyramiding_limit: {pyramiding_limit}")
        if (close_on_last_dca and is_last_dca):
            print("최종 DCA에 헷징포지션을 종료")
            # 헷지 포지션 종료
            request = ClosePositionRequest(
                close_type = 'market',
                user_id=user_id,
                close_percent=100
            )
            try:
                response = await close_position(symbol, request, user_id, opposite_side)
                
                # 종료 포지션 결과
                closed_amount = response.amount
                closed_position_qty = await contracts_to_qty(symbol, closed_amount)
                
                # 양방향 종료 로깅
                try:
                    log_order(
                        user_id=user_id,
                        symbol=symbol,
                    action_type='hedge_exit',
                    position_side=opposite_side,
                    price=current_price,
                    quantity=closed_position_qty,
                    reason='last_dca_close',
                        main_position_side=main_position_side
                    )
                except Exception as e:
                    logger.error(f"헷지 포지션 종료 로깅 실패: {str(e)}")
                               
                message = f"✅양방향 포지션 종료\n"
                message += f"━━━━━━━━━━━━━━━━\n"
                message += f"최종 추가 진입으로 양방향 포지션 종료\n"
                message += f"• 방향: {opposite_side}\n"
                message += f"• 수량: {closed_position_qty:,.3f}\n"
                message += f"━━━━━━━━━━━━━━━━\n"
                
                await send_telegram_message(message, user_id)
                
                dual_side_key = f"user:{user_id}:{symbol}:dual_side_position"
                
                await redis_client.delete(dual_side_key)
                return
            except Exception as e:
                logger.error(f"헷지 포지션 종료 실패: {str(e)}")
                traceback.print_exc()
                await send_telegram_message(f"헷지 포지션 종료 실패: {str(e)}", user_id, debug=True)
            


        # dual_side_pyramiding_limit 체크
        if dual_side_count >= int(dual_side_pyramiding_limit):
            logger.info(f"[{user_id}] 양방향 진입 제한 초과. 현재 카운트: {dual_side_count}, 제한: {dual_side_pyramiding_limit}")
            
                        
            if existing_hedge_size > 0.03 :
                # 메인 포지션 정보 가져오기
                try:
                    main_position = await trading_service.get_current_position(user_id, symbol, main_position_side)
                    if not main_position:
                        logger.warning(f"[{user_id}] DCA 후 메인 포지션 정보를 찾을 수 없음")
                                        
                    # 메인 포지션의 반대 방향
                    opposite_side = "long" if main_position_side == "short" else "short"
                    
                    # 현재 헷지 포지션 확인
                    hedge_position = await trading_service.get_current_position(user_id, symbol, opposite_side)
                    
                    # 헷지 포지션이 있는 경우에만 재계산
                    if hedge_position and hedge_position.size > 0.03:
                        log_dual_side_debug(
                            user_id=user_id,
                            symbol=symbol,
                            function_name='manage_dual_side_entry',
                            message='DCA 후 헷지 포지션 SL/TP 재계산 시작',
                            level='INFO',
                            main_position=main_position.__dict__ if hasattr(main_position, '__dict__') else main_position,
                            hedge_position=hedge_position.__dict__ if hasattr(hedge_position, '__dict__') else hedge_position
                        )
                        
                        # 메인 포지션 정보 변환
                        main_position_dict = {
                            "avg_price": main_position.entry_price if hasattr(main_position, 'entry_price') else current_price,
                            "sl_price": main_position.sl_price if hasattr(main_position, 'sl_price') else None,
                            "tp_prices": main_position.tp_prices if hasattr(main_position, 'tp_prices') else []
                        }
                        
                        # 헷지 포지션 정보 변환
                        hedge_position_dict = {
                            "side": opposite_side,
                            "size": hedge_position.size if hasattr(hedge_position, 'size') else 0,
                            "entry_price": hedge_position.entry_price if hasattr(hedge_position, 'entry_price') else current_price
                        }
                        
                        # SL/TP 재계산 및 업데이트
                        await update_hedge_sl_tp_after_dca(
                            user_id=user_id,
                            symbol=symbol,
                            exchange=exchange,
                            main_position=main_position_dict,
                            hedge_position=hedge_position_dict,
                            settings=settings
                        )
                        
                        # 재계산 후 실행 종료 (헷지 포지션 추가 진입 없이)
                        return
                except Exception as e:
                    logger.error(f"헷지 포지션 재계산 실패: {str(e)}")
                    traceback.print_exc()
                    await send_telegram_message(f"헷지 포지션 재계산 실패. 확인 필수: {str(e)}", user_id, debug=True)
            #asyncio.create_task(send_telegram_message(
            #    f"⚠️ 양방향 진입 제한 초과\n"
            #    f"현재 카운트: {dual_side_count}, 제한: {dual_side_pyramiding_limit}",
            #    user_id, debug=True
            #    ))
            return


        try:
            # (G-1) 헷지 SL/TP 계산
            #   (기존 포지션 SL -> 헷지 TP, firstTP -> 헷지 SL 등)
            hedge_sl_price, hedge_tp_price = await calculate_hedge_sl_tp(
                user_id=user_id,
                symbol=symbol,
                main_position_side=main_position_side,
                dual_side_settings=dual_side_settings,
                trading_service=trading_service
                )
            print(f"hedge_sl_price: {hedge_sl_price}, hedge_tp_price: {hedge_tp_price}")
            print(f"TYPE OF HEDGE TP: {type(hedge_tp_price)}")
            # (G-2) 헷지 포지션 오픈

            try:
                request = OpenPositionRequest(
                    user_id=user_id,
                    symbol=symbol,
                    direction=opposite_side,
                    size=new_position_size,
                    leverage=settings.get('leverage', 1.0),
                    take_profit=None,
                    stop_loss=None,
                    settings=settings,
                    is_DCA = False,
                    is_hedge = True,
                    hedge_tp_price = hedge_tp_price,
                    hedge_sl_price = hedge_sl_price
                )
                
                log_dual_side_debug(
                    user_id=user_id,
                    symbol=symbol,
                    function_name='manage_dual_side_entry',
                    message='헷지 포지션 오픈 요청 준비됨',
                    level='DEBUG',
                    request=request.__dict__
                )
                
                entry_result = await open_position_endpoint(request)
                
                try:
                    log_dual_side_debug(
                        user_id=user_id,
                        symbol=symbol,
                        function_name='manage_dual_side_entry',
                        message='헷지 포지션 오픈 성공',
                        level='INFO',
                        entry_result=entry_result.__dict__ if hasattr(entry_result, '__dict__') else entry_result
                    )
                except Exception as e:
                    logger.error(f"헷지 포지션 오픈 로깅 실패: {str(e)}")   
                
                # 양방향 진입 로깅
                try:
                    log_order(
                    user_id=user_id,
                    symbol=symbol,
                    action_type='hedge_entry',
                    position_side=opposite_side,
                    price=current_price,
                    quantity=new_position_size,
                    level=dca_order_count,
                    is_hedge=True,
                    main_position_side=main_position_side,
                    hedge_sl_price=hedge_sl_price,
                    hedge_tp_price=hedge_tp_price if hedge_tp_price is not None else '',  # None 대신 빈 문자열 사용
                    close_on_last_dca=close_on_last_dca,
                    leverage=settings.get('leverage', 1.0)
                    )
                except Exception as e:
                    logger.error(f"헷지 포지션 진입 로깅 실패: {str(e)}")
                
            except Exception as e:
                log_dual_side_debug(
                    user_id=user_id,
                    symbol=symbol,
                    function_name='manage_dual_side_entry',
                    message='헷지 포지션 오픈 실패',
                    level='ERROR',
                    exception=e,
                    request_data={
                        'symbol': symbol,
                        'direction': opposite_side,
                        'size': new_position_size,
                        'leverage': settings.get('leverage', 1.0),
                        'hedge_tp_price': hedge_tp_price,
                        'hedge_sl_price': hedge_sl_price
                    }
                )
                
                logger.error(f"[manage_dual_side_entry] 헷지 포지션 오픈 실패: {str(e)}")
                return
            logger.info(f"[manage_dual_side_entry] 헷지 포지션 오픈 결과: {entry_result}")
            entry_amount = entry_result.size
            if entry_amount <= 0.02:
                logger.error(f"[manage_dual_side_entry] 헷지 포지션 오픈 실패: {str(e)}")
                return
            contract_size = await trading_service.get_contract_size(symbol)
            new_entering_position = entry_amount * contract_size
            #new_entering_position = await trading_service.round_to_qty(new_entering_position, symbol)
            # (G-3) 알림
            dual_side_emoji = "🟢" if opposite_side == "long" else "🔴"
            msg = (
                f"{dual_side_emoji} 양방향 트레이딩 알림\n"
                f"━━━━━━━━━━━━━━━━\n"
                f" {dual_side_count+1}회차 반대포지션 진입\n\n"
                f"📈 거래 정보\n"
                f"• 방향: {opposite_side}\n"
                f"• 진입가: {current_price:,.2f}\n"
                f"• 수량: {float(new_entering_position):,.4f}\n\n"
        
            )
            
            dual_side_settings = await get_user_dual_side_settings(user_id)
            use_dual_sl = dual_side_settings.get('use_dual_sl', False)
            if hedge_sl_price or hedge_tp_price:
                msg += f"🎯 손익 설정\n"
            if hedge_sl_price and use_dual_sl:
                msg += f"• 손절가: {float(hedge_sl_price):,.2f}\n"
            if hedge_tp_price:
                msg += f"• 목표가: {float(hedge_tp_price):,.2f}\n"
            if close_on_last_dca:
                msg += f"• 최종 추가진입 시 양방향 포지션 익절\n"
                
            await send_telegram_message(msg, user_id)

            # (G-4) Redis 저장 (헷지 포지션 정보)
            dual_side_key = f"user:{user_id}:{symbol}:dual_side_position"
            await redis_client.hset(dual_side_key, 'entry_price', str(current_price))
            await redis_client.hset(dual_side_key, 'size', str(new_position_size))
            await redis_client.hset(dual_side_key, 'side', opposite_side)
            await redis_client.hset(dual_side_key, 'dca_index', str(dca_order_count))
            await redis_client.hset(dual_side_key, 'dual_side_count', str(dual_side_count))
            
            # dual_side 진입 카운트 증가
            await redis_client.incr(dual_side_count_key)
            
            if hedge_sl_price:
                await redis_client.hset(dual_side_key, 'stop_loss', str(hedge_sl_price))
            if hedge_tp_price is not None:  # None이 아닐 때만 저장
                await redis_client.hset(dual_side_key, 'take_profit', str(hedge_tp_price))
            else:
                await redis_client.hset(dual_side_key, 'take_profit', '')  # None 대신 빈 문자열 저장

            # 양방향 진입 로깅
            try:
                log_order(
                    user_id=user_id,
                    symbol=symbol,
                    action_type='hedge_entry',
                    position_side=opposite_side,
                    price=current_price,
                    quantity=new_position_size,
                    level=dca_order_count,
                    is_hedge=True,
                    main_position_side=main_position_side,
                    hedge_sl_price=hedge_sl_price,
                    hedge_tp_price=hedge_tp_price if hedge_tp_price is not None else '',  # None 대신 빈 문자열 사용
                    close_on_last_dca=close_on_last_dca,
                    leverage=settings.get('leverage', 1.0)
                )
            except Exception as e:
                logger.error(f"헷지 포지션 진입 로깅 실패: {str(e)}")

        except Exception as e:
            error_msg = map_exchange_error(e)
            traceback.print_exc()
            logger.error(f"[manage_dual_side_entry] 헷지 진입 실패: {str(e)}")
            
            log_dual_side_debug(
                user_id=user_id,
                symbol=symbol,
                function_name='manage_dual_side_entry',
                message='헷지 진입 처리 중 오류 발생',
                level='ERROR',
                exception=e,
                error_msg=error_msg
            )
            
            #await send_telegram_message(
            #    f"⚠️ 헷지 진입 실패:\n"
            #    f"{error_msg}",
            #    user_id
            #)
            return
    except Exception as e:
        traceback.print_exc()
        
        log_dual_side_debug(
            user_id=user_id,
            symbol=symbol,
            function_name='manage_dual_side_entry',
            message='양방향 진입 처리 중 최상위 오류 발생',
            level='ERROR',
            exception=e,
            main_position_side=main_position_side,
            dca_order_count=dca_order_count,
            current_price=current_price
        )
        
        await send_telegram_message(f"양방향 진입 실패: {str(e)}", user_id, debug=True)
        logger.error(f"[manage_dual_side_entry] 헷지 진입 실패: {str(e)}")
        return


async def calculate_hedge_sl_tp(
    user_id: str,
    symbol: str,
    main_position_side: str,  # "long" 또는 "short"
    dual_side_settings: dict,
    trading_service: TradingService = None
) -> tuple[float | None, float | None]:
    """
    헷지 포지션의 SL/TP 가격을 계산합니다.
    
    Args:
        user_id: 사용자 ID
        symbol: 거래 심볼
        main_position_side: 메인 포지션 방향
        settings: 사용자 설정
        trading_service: 트레이딩 서비스 인스턴스
        
    Returns:
        tuple: (SL 가격, TP 가격) 쌍
    """
    try:
        log_dual_side_debug(
            user_id=user_id,
            symbol=symbol,
            function_name='calculate_hedge_sl_tp',
            message='헷지 포지션 SL/TP 계산 시작',
            level='DEBUG',
            main_position_side=main_position_side,
            settings=dual_side_settings
        )
        
        # (1) 트레이딩 서비스 인스턴스가 없으면 생성
        if not trading_service:
            from HYPERRSI.src.trading.trading_service import get_trading_service
            trading_service = await get_trading_service()
            
            log_dual_side_debug(
                user_id=user_id,
                symbol=symbol,
                function_name='calculate_hedge_sl_tp',
                message='트레이딩 서비스 인스턴스 생성됨',
                level='DEBUG'
            )

        # (2) 메인 포지션 정보 가져오기
        position_data = await trading_service.get_current_position(user_id, symbol, main_position_side)
        
        if not position_data:
            log_dual_side_debug(
                user_id=user_id,
                symbol=symbol,
                function_name='calculate_hedge_sl_tp',
                message='메인 포지션 정보를 찾을 수 없음',
                level='WARNING'
            )
            return (None, None)
            
        # (3) 현재 SL/TP 설정 가져오기
        sl_price = position_data.sl_price if hasattr(position_data, 'sl_price') else None
        tp_prices = position_data.tp_prices if hasattr(position_data, 'tp_prices') else []
        avg_price = position_data.entry_price if hasattr(position_data, 'entry_price') else 0
        
        log_dual_side_debug(
            user_id=user_id,
            symbol=symbol,
            function_name='calculate_hedge_sl_tp',
            message='메인 포지션 SL/TP 정보 조회 완료',
            level='DEBUG',
            sl_price=sl_price,
            tp_prices=tp_prices,
            avg_price=avg_price
        )
        
        # (4) SL/TP 설정 방식 확인
        sl_trigger_type = dual_side_settings.get('dual_side_entry_sl_trigger_type', 'existing_position')
        tp_trigger_type = dual_side_settings.get('dual_side_entry_tp_trigger_type', 'existing_position')
        use_dual_sl = dual_side_settings.get('use_dual_sl', False)
        sl_value = float(dual_side_settings.get('dual_side_entry_sl_value', 1.0))
        tp_value = float(dual_side_settings.get('dual_side_entry_tp_value', 1.0))
        
        log_dual_side_debug(
            user_id=user_id,
            symbol=symbol,
            function_name='calculate_hedge_sl_tp',
            message='SL/TP 설정 방식 확인',
            level='DEBUG',
            sl_trigger_type=sl_trigger_type,
            tp_trigger_type=tp_trigger_type,
            sl_value=sl_value,
            tp_value=tp_value
        )
        
        # 메인 포지션의 반대 방향
        opposite_side = "short" if main_position_side == "long" else "long"
        hedge_sl_price = None
        hedge_tp_price = None
        
        # (4) SL 계산
        #     "기존 포지션" 모드면 메인 포지션의 첫번째 TP를 헷지 SL로 사용
        #     "퍼센트" 모드면 avg_price ± 퍼센트
        if use_dual_sl:
            print(f"use_dual_sl: {use_dual_sl}")
            if str(user_id) == '1709556958':
                await send_telegram_message(f"use_dual_sl 체크! : {use_dual_sl}", user_id, debug=True)
            if sl_trigger_type == "existing_position":
                # 첫번째 TP 찾기
                hedge_sl_price = tp_prices[0] if tp_prices else None
            else:
                # "percent" 모드
                if opposite_side == "short":
                    # 헷지 숏 => 손절(SL)은 평단보다 올라간 가격
                    hedge_sl_price = avg_price * (1 + sl_value / 100.0)
                else:
                    # opposite_side == "long"
                    # 헷지 롱 => 손절(SL)은 평단보다 내려간 가격
                    hedge_sl_price = avg_price * (1 - sl_value / 100.0)

        # (5) TP 계산
        # 양방향 익절을 사용하지 않는 경우 TP를 None으로 설정
        if tp_trigger_type == "do_not_close":
            hedge_tp_price = None
            log_dual_side_debug(
                user_id=user_id,
                symbol=symbol,
                function_name='calculate_hedge_sl_tp',
                message='양방향 익절 사용 안함 설정으로 TP가 None으로 설정됨',
                level='INFO'
            )
        elif tp_trigger_type == "existing_position":
            hedge_tp_price = sl_price
        elif tp_trigger_type == "last_dca_on_position":
            hedge_tp_price = await get_last_dca_level(user_id, symbol, opposite_side)
        else:
            # "percent" 모드
            if opposite_side == "short":
                # 헷지 숏 => 목표가(익절)는 평단보다 내려간 가격
                hedge_tp_price = avg_price * (1 - tp_value / 100.0)
            else:
                # opposite_side == "long"
                # 헷지 롱 => 목표가(익절)는 평단보다 올라간 가격
                hedge_tp_price = avg_price * (1 + tp_value / 100.0)

        log_dual_side_debug(
            user_id=user_id,
            symbol=symbol,
            function_name='calculate_hedge_sl_tp',
            message='헷지 SL/TP 계산 완료',
            level='INFO',
            hedge_sl_price=hedge_sl_price,
            hedge_tp_price=hedge_tp_price,
            tp_trigger_type=tp_trigger_type
        )

        return (hedge_sl_price, hedge_tp_price)
    except Exception as e:        
        traceback.print_exc()
        logger.error(f"[calculate_hedge_sl_tp] Error: {str(e)}")
        return (None, None)


async def update_hedge_sl_tp_after_dca(
    user_id: str,
    symbol: str,
    exchange: ccxt.Exchange,          # ccxt 익스체인지 객체    
    main_position: dict,
    hedge_position: dict,
    settings: dict,
):
    """
    - 메인 포지션에 추가 DCA가 체결된 뒤(평단 or SL/TP 변경),
      헷지 포지션의 SL/TP를 다시 계산해서 취소 후 재생성하는 예시 함수
    - `main_position` : { "avg_price":..., "sl_price":..., "tp_prices":[...], ... }
    - `hedge_position`: { "side":"long"/"short", "size":..., ... }
    """
    # 헷지 포지션이 없거나, 사이즈가 0이면 패스
    if not hedge_position or hedge_position.get("size", 0) <= 0:
        logger.info("헷지 포지션이 없어서 SL/TP 갱신 불필요.")
        return


    hedge_side = hedge_position["side"]  # "long" or "short"
    
    hedge_cancel_side = "buy" if hedge_side == "short" else "sell"
    # (1) 기존 알고주문/감시주문/리듀스온리주문 모두 취소
    #     pos_side는 "long"/"short" 그대로 전달
    try:
        
        await cancel_algo_orders(symbol = symbol, user_id = user_id, side = hedge_cancel_side, algo_type="trigger")
    except Exception as e:  
        log_dual_side_debug(
            user_id=user_id,
            symbol=symbol,
            function_name='update_hedge_sl_tp_after_dca',
            message='알고주문 취소 실패',
            level='ERROR',
            exception=e,
            hedge_side=hedge_side,
            hedge_cancel_side=hedge_cancel_side
        )
        
        log_error(
        error=e,
        user_id=user_id,
        additional_info={
            'action': 'cancel_algo_orders',
            'symbol': symbol,
            'side': hedge_cancel_side,
            'position_type': 'hedge'
        }
    )
        logger.warning(f"[{user_id}] 알고주문 취소 실패: {e}")

    tdMode = await redis_client.get(f"user:{user_id}:position:{symbol}:tdMode")
    if tdMode is None:
        tdMode = "cross"  # 기본값 설정
    # (2) 새 SL/TP 가격 계산
    #     프로젝트에서 원하는 로직(기존 포지션 SL -> 헷지 TP, 1차 TP -> 헷지 SL, 등등)
    hedge_sl_price, hedge_tp_price = await recalc_hedge_sl_tp(
        user_id,
        symbol,
        main_position,
        hedge_position,
        settings
    )
    
    if not hedge_sl_price and not hedge_tp_price:
        log_dual_side_debug(
            user_id=user_id,
            symbol=symbol,
            function_name='update_hedge_sl_tp_after_dca',
            message='새 SL/TP 계산결과가 없어 주문 생성 안 함',
            level='WARNING'
        )
        
        logger.info("새 SL/TP 계산결과가 없어, 주문 생성 안 함.")
        return

    # (3) 새 SL/TP 주문 생성
    sl_order_id = None
    tp_order_id = None

    # 헷지 포지션이 숏 => 청산 주문은 'buy' / 롱 => 청산 주문은 'sell'
    exit_side = "buy" if hedge_side == "short" else "sell"
    size = hedge_position.get("size", 0)

    # 예시: CCXT create_order(type="stop") + OKX 파라미터
    # 실제론 OKX "algo주문" API를 직접 호출할 수도 있음
    if hedge_sl_price:
        try:
            algo_type = "conditional"  # 알고 주문 타입
            resp_sl = await exchange.create_order(
                symbol=symbol,
                type=algo_type,
                side=exit_side,
                amount=size,
                price=hedge_sl_price,  # 실제 체결 가격
                params={
                    'stopPrice': hedge_sl_price,  # 트리거 가격
                    'reduceOnly': True,  # 포지션 종료용 주문임을 명시
                    'posSide': hedge_side,
                    'slTriggerPxType': 'last',
                    'slOrdPxType': 'last',
                    'tdMode': tdMode,
                }
            )
            sl_order_id = resp_sl.get("id")

            
            logger.info(f"새 SL 주문 생성 완료: {sl_order_id} (triggerPx={hedge_sl_price})")
        except Exception as e:

            
            log_error(
            error=e,
            user_id=user_id,
            additional_info={
                'action': 'create_order',
                'symbol': symbol,
                    'side': exit_side
                }
            )
            logger.warning(f"[{user_id}] SL 주문 생성 실패: {e}")

    if hedge_tp_price:
        try:
            resp_tp = await exchange.create_order(
                symbol=symbol,
                type="limit",
                side=exit_side,
                amount=size,
                price=hedge_tp_price,  # 리밋 주문가
                params={
                    "reduceOnly": True,
                    "posSide": hedge_side,
                    "tdMode": tdMode,
                }
            )
            tp_order_id = resp_tp.get("id")

            
            logger.info(f"새 TP 주문 생성 완료: {tp_order_id} (price={hedge_tp_price})")
        except Exception as e:

            
            log_error(
            error=e,
            user_id=user_id,
            additional_info={
                'action': 'create_order',
                'symbol': symbol,
                'side': exit_side
            }
            )   
            logger.warning(f"[{user_id}] TP 주문 생성 실패: {e}")

    # (4) Redis 등에 새로운 SL/TP 주문 정보 저장
    hedge_order_key = f"user:{user_id}:{symbol}:hedge_sl_tp"
    new_info = {
        "sl_order_id": sl_order_id,
        "tp_order_id": tp_order_id,
        "sl_price": hedge_sl_price or None,
        "tp_price": hedge_tp_price or None,
    }
    await redis_client.set(hedge_order_key, json.dumps(new_info))
    

    
    logger.info(f"헷지 SL/TP 주문 재생성 완료. sl={hedge_sl_price}, tp={hedge_tp_price}")
    
    # 헷지 SL/TP 업데이트 로깅


async def recalc_hedge_sl_tp(
    user_id: str,
    symbol: str,
    main_position: dict,
    hedge_position: dict,
    settings: dict
) -> tuple[float | None, float | None]:
    """
    DCA(추가 진입) 이후 헷지 포지션의 SL/TP를 재계산합니다.
    메인 포지션의 변경된 SL/TP를 기반으로 헷지 포지션의 SL/TP를 업데이트합니다.
    
    Args:
        user_id: 사용자 ID
        symbol: 거래 심볼
        main_position: 메인 포지션 정보 (dict)
            {"sl_price": float, "tp_prices": [float, ...], "avg_price": float}
        hedge_position: 헷지 포지션 정보 (dict)
            {"side": "long" or "short", "size": float, "entry_price": float}
        settings: 사용자 설정
            
    Returns:
        tuple: (hedge_sl_price, hedge_tp_price) - 헷지 포지션의 새 SL/TP 가격
    """
    try:
        # 로깅
        log_dual_side_debug(
            user_id=user_id,
            symbol=symbol,
            function_name='recalc_hedge_sl_tp',
            message='헷지 포지션 SL/TP 재계산 시작',
            level='DEBUG',
            main_position=main_position,
            hedge_position=hedge_position
        )
        
        # 사용자의 양방향 설정 가져오기
        dual_side_settings = await get_user_dual_side_settings(user_id)
        
        # SL/TP 설정 방식 확인
        sl_trigger_type = dual_side_settings.get('dual_side_entry_sl_trigger_type', 'existing_position')
        tp_trigger_type = dual_side_settings.get('dual_side_entry_tp_trigger_type', 'existing_position')
        use_dual_sl = dual_side_settings.get('use_dual_sl', False)
        sl_value = float(dual_side_settings.get('dual_side_entry_sl_value', 1.0))
        tp_value = float(dual_side_settings.get('dual_side_entry_tp_value', 1.0))
        
        # 메인 포지션 정보 추출
        main_sl_price = main_position.get("sl_price")
        tp_prices = main_position.get("tp_prices", [])
        main_first_tp = tp_prices[0] if tp_prices else None
        main_avg_price = main_position.get("avg_price", main_position.get("entry_price"))
        
        # 헷지 포지션 정보
        hedge_side = hedge_position.get("side")
        
        # 기본값 설정
        hedge_sl_price = None
        hedge_tp_price = None
        
        # SL 계산 (사용자 설정에 따라 계산)
        if use_dual_sl:
            if sl_trigger_type == "existing_position":
                # 메인 포지션의 첫번째 TP를 헷지 SL로 사용
                hedge_sl_price = main_first_tp
            else:
                # "percent" 모드 - 평단가에서 일정 비율 떨어진 가격
                if hedge_side == "short":
                    # 헷지 숏 => 손절(SL)은 평단보다 올라간 가격
                    hedge_sl_price = main_avg_price * (1 + sl_value / 100.0)
                else:
                    # hedge_side == "long"
                    # 헷지 롱 => 손절(SL)은 평단보다 내려간 가격
                    hedge_sl_price = main_avg_price * (1 - sl_value / 100.0)
        
        # TP 계산 (사용자 설정에 따라 계산)
        if tp_trigger_type == "do_not_close":
            hedge_tp_price = None
        elif tp_trigger_type == "existing_position":
            # 메인 포지션의 SL을 헷지 TP로 사용
            hedge_tp_price = main_sl_price
        elif tp_trigger_type == "last_dca_on_position":
            # 마지막 DCA 레벨에 도달하면 종료 (TP 가격 계산 안함)
            hedge_tp_price = await get_last_dca_level(user_id, symbol, hedge_side)
        else:
            # "percent" 모드 - 평단가에서 일정 비율 떨어진 가격
            if hedge_side == "short":
                # 헷지 숏 => 목표가(익절)는 평단보다 내려간 가격
                hedge_tp_price = main_avg_price * (1 - tp_value / 100.0)
            else:
                # hedge_side == "long"
                # 헷지 롱 => 목표가(익절)는 평단보다 올라간 가격
                hedge_tp_price = main_avg_price * (1 + tp_value / 100.0)
        
        # 로깅
        log_dual_side_debug(
            user_id=user_id,
            symbol=symbol,
            function_name='recalc_hedge_sl_tp',
            message='헷지 SL/TP 재계산 완료',
            level='INFO',
            hedge_sl_price=hedge_sl_price,
            hedge_tp_price=hedge_tp_price,
            tp_trigger_type=tp_trigger_type,
            sl_trigger_type=sl_trigger_type
        )
        
        return (hedge_sl_price, hedge_tp_price)
    
    except Exception as e:
        logger.error(f"[recalc_hedge_sl_tp] 오류: {str(e)}")
        traceback.print_exc()
        return (None, None)


#===========================================
# 헷지 TP/SL 주문 관리
#===========================================


# --------------------------------------------------
# 예시: 헷지 SL/TP 재계산 함수 (업데이트용)
# --------------------------------------------------
async def calculate_hedge_sl_tp_for_update(
    side: str,                # 메인 포지션 방향("long"/"short")
    main_position_data: dict, # {"sl_price":..., "tp_prices":[...], "avg_price":...}
    hedge_side: str,          # "long" or "short"
    hedge_entry_price: float, # 헷지 포지션 진입가
    settings: dict
) -> tuple[float | None, float | None]:
    """
    DCA 후에 메인 포지션이 변동됨에 따라, 헷지 포지션의 SL/TP를 새로 계산하는 로직.
    실제 정책: "기존 롱의 SL => 헷지 숏의 TP", "기존 롱의 1차TP => 헷지 숏의 SL" 등.
    """
    main_sl_price = main_position_data.get("sl_price")
    main_tp_prices = main_position_data.get("tp_prices", [])
    main_first_tp = main_tp_prices[0] if main_tp_prices else None

    # 간단 예: side="long" => 헷지side="short"
    # => 헷지SL=메인1차TP, 헷지TP=메인SL
    # (프로젝트 상황에 맞게 변경)
    if hedge_side == "short":
        hedge_sl = main_first_tp
        hedge_tp = main_sl_price
    else:
        # hedge_side="long"
        hedge_sl = main_first_tp
        hedge_tp = main_sl_price

    return (hedge_sl, hedge_tp)
