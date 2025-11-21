# execute_trading_logic.py

import asyncio
import json
import time
import traceback
from datetime import datetime
from os import error
from typing import Dict

from HYPERRSI.src.api.trading.Calculate_signal import TrendStateCalculator
from HYPERRSI.src.bot.telegram_message import send_telegram_message
from HYPERRSI.src.core.error_handler import ErrorCategory, handle_critical_error
from HYPERRSI.src.core.logger import log_bot_error, log_bot_start, log_bot_stop, setup_error_logger
from HYPERRSI.src.services.redis_service import RedisService
from HYPERRSI.src.trading.models import get_timeframe
from HYPERRSI.src.trading.services.get_current_price import get_current_price
from HYPERRSI.src.trading.trading_service import TradingService
from HYPERRSI.src.trading.utils.position_handler import handle_existing_position, handle_no_position
from HYPERRSI.src.trading.utils.trading_utils import (
    init_user_monitoring_data,
    init_user_position_data,
)
from shared.database.redis_helper import get_redis_client
from shared.database.redis_migration import get_redis_context
from shared.database.redis_patterns import RedisTimeout
from shared.logging import get_logger

logger = get_logger(__name__)
error_logger = setup_error_logger()

# Dynamic redis_client access


async def get_okx_uid_from_telegram_id(telegram_id: str) -> str:
    """
    텔레그램 ID를 OKX UID로 변환하는 함수

    Args:
        telegram_id: 텔레그램 ID

    Returns:
        str: OKX UID
    """
    # MIGRATED: Using get_redis_context() with FAST_OPERATION for single GET
    async with get_redis_context(user_id=telegram_id, timeout=RedisTimeout.FAST_OPERATION) as redis:
        try:
            # 텔레그램 ID로 OKX UID 조회
            key = f"user:{telegram_id}:okx_uid"
            logger.info(f"[DEBUG] Redis에서 OKX UID 조회 시도: {key}")
            okx_uid = await redis.get(key)
            logger.info(f"[DEBUG] Redis 조회 결과: {okx_uid}, type: {type(okx_uid)}")
            if okx_uid:
                result = okx_uid.decode() if isinstance(okx_uid, bytes) else okx_uid
                logger.info(f"[DEBUG] OKX UID 찾음: {telegram_id} -> {result}")
                return result
            logger.info(f"[DEBUG] OKX UID를 찾을 수 없음: {telegram_id}")
            return None
        except Exception as e:
            logger.error(f"텔레그램 ID를 OKX UID로 변환 중 오류: {str(e)}")
            # errordb 로깅
            from HYPERRSI.src.utils.error_logger import log_error_to_db
            log_error_to_db(
                error=e,
                user_id=telegram_id,
                severity="WARNING",
                metadata={"telegram_id": telegram_id}
            )
            return None

async def get_identifier(user_id: str) -> str:
    """
    입력된 식별자가 텔레그램 ID인지 OKX UID인지 확인하고 적절한 OKX UID를 반환
    
    Args:
        user_id: 텔레그램 ID 또는 OKX UID
        
    Returns:
        str: OKX UID
    """
    # 13자리 미만이면 텔레그램 ID로 간주하고 변환
    if len(str(user_id)) < 13:
        okx_uid = await get_okx_uid_from_telegram_id(str(user_id))
        if not okx_uid:
            logger.error(f"텔레그램 ID {user_id}에 대한 OKX UID를 찾을 수 없습니다")
            return str(user_id)  # 변환 실패 시 원래 ID 반환
        logger.info(f"텔레그램 ID {user_id} -> OKX UID {okx_uid} 변환 성공")
        return okx_uid
    # 13자리 이상이면 이미 OKX UID로 간주
    return str(user_id)


# ======== 메인 트레이딩 로직 ========
async def execute_trading_logic(user_id: str, symbol: str, timeframe: str, restart = False):

    # MIGRATED: Using get_redis_context() with NORMAL_OPERATION
    async with get_redis_context(user_id=user_id, timeout=RedisTimeout.NORMAL_OPERATION) as redis:
        start_time_loop = datetime.now()
        """
        - 주기적으로:
          1) monitor_orders()를 통해 주문 체결 여부를 업데이트
          2) RSI/트랜드 체크 -> 포지션 분기처리
        """
        trading_service = None
        #print("execute_trading_logic 호출")
    
        # 원본 user_id를 telegram_id로 저장 (텔레그램 메시지 전송용)
        original_user_id = user_id
        telegram_id = user_id if len(str(user_id)) < 13 else None
        try: 
            user_id = await get_identifier(user_id)
        except Exception as e:
            traceback.print_exc()
            user_id = None
        if not user_id:
            logger.error(f"유효하지 않은 사용자 ID: {original_user_id}")
            return

        # get_identifier가 원래 ID를 그대로 반환한 경우 (변환 실패)
        # 이는 텔레그램 ID인데 OKX UID를 찾지 못한 경우
        # OKX UID에서 텔레그램 ID 조회 (telegram_id가 없는 경우)
        if not telegram_id:
            try:
                telegram_id_bytes = await redis.get(f"okx_uid_to_telegram:{user_id}")
                if telegram_id_bytes:
                    telegram_id = telegram_id_bytes.decode() if isinstance(telegram_id_bytes, bytes) else telegram_id_bytes
            except Exception as e:
                logger.debug(f"텔레그램 ID 조회 실패: {e}")
    
        logger.debug(f"execute_trading_logic 호출 - user_id: {user_id}, telegram_id: {telegram_id}, symbol: {symbol}, timeframe: {timeframe}, restart: {restart}")
    
        try:
            # 트레이딩 서비스 초기화
            #logger.warning("트레이딩 서비스 초기화 시작")
            trading_service = await TradingService.create_for_user(user_id)
           # logger.warning("트레이딩 서비스 초기화 완료")
            okx_instance = trading_service.client
            calculator = TrendStateCalculator()
            redis_service = RedisService()

            # Redis 연결 확인
            #logger.warning("Redis 연결 확인 중")
            await redis.ping()
            await redis.set(f"user:{user_id}:trading:status", "running")
            #logger.warning(f"Redis 상태 업데이트 완료: user:{user_id}:trading:status = running")

        except Exception as e:
            error_msg = f"트레이딩 초기화 실패: {str(e)}"
            error_logger.error(error_msg)
            logger.error(f"트레이딩 초기화 실패: {str(e)}", exc_info=True)

            # errordb 로깅
            from HYPERRSI.src.utils.error_logger import async_log_error_to_db
            await async_log_error_to_db(
                error=e,
                user_id=user_id,
                telegram_id=int(telegram_id) if telegram_id else None,
                severity="CRITICAL",
                symbol=symbol,
                metadata={
                    "timeframe": timeframe,
                    "restart": restart,
                    "component": "trading_initialization"
                }
            )

            await handle_critical_error(
                error=e,
                category=ErrorCategory.TRADING_INIT,
                context={"user_id": user_id, "symbol": symbol, "timeframe": timeframe, "restart": restart},
                okx_uid=user_id
            )

            try:
                # 에러 로그 기록
                log_bot_error(
                    user_id=int(user_id),
                    symbol=symbol,
                    error_message=error_msg,
                    exception=e,
                    component="trading_initialization"
                )

                await send_telegram_message(f"⚠️ {error_msg}\n User의 상태를 Stopped로 강제 변경.", user_id, debug=True)
                await send_telegram_message(f"에러가 발생했습니다. 잠시 후에 다시 시도해주세요.", user_id)
                await redis.set(f"user:{user_id}:trading:status", "stopped")
            except Exception as telegram_error:
                logger.error(f"텔레그램 메시지 전송 실패: {str(telegram_error)}", exc_info=True)
                # errordb 로깅 (텔레그램 전송 실패)
                await async_log_error_to_db(
                    error=telegram_error,
                    user_id=user_id,
                    telegram_id=int(telegram_id) if telegram_id else None,
                    severity="WARNING",
                    metadata={"component": "telegram_notification", "original_error": error_msg}
                )
        
            if trading_service:
                try:
                    await trading_service.cleanup()
                    #await trading_service.close()
                except Exception as close_error:
                    logger.error(f"트레이딩 서비스 종료 실패: {str(close_error)}", exc_info=True)
                
            return

        try:
            # 사용자 설정 가져오기
            user_settings = await redis_service.get_user_settings(user_id)
            if not user_settings:
                await send_telegram_message("⚠️ 트레이딩 설정 오류\n""─────────────────────\n""사용자 설정을 찾을 수 없습니다.\n""/settings 명령어로 설정을 확인해주세요.",user_id)
                await redis.set(f"user:{user_id}:trading:status", "stopped")
                return
            entry_fail_count_key = f"user:{user_id}:entry_fail_count"
            await redis.delete(entry_fail_count_key)
            active_key = f"user:{user_id}:preferences"
        
            # 매개변수로 전달된 symbol이 없는 경우에만 Redis에서 가져옴
            if symbol is None:
                symbol = await redis.hget(active_key, "symbol")
                if not symbol:
                    symbol = 'BTC-USDT-SWAP'
                
            if timeframe is None:   
                timeframe = await redis.hget(active_key, "timeframe")
                if not timeframe:
                    timeframe = '1m'
            if not symbol or not timeframe:
                await send_telegram_message("⚠️ 트레이딩 설정 오류\n""─────────────────────\n""심볼 또는 타임프레임이 설정되지 않았습니다.\n""설정을 확인하고 다시 시작해주세요.",user_id)
                await redis.set(f"user:{user_id}:trading:status", "stopped")
                await send_telegram_message(f"⚠️[{user_id}] User의 상태를 Stopped로 강제 변경1.", user_id, debug=True)
                return
        
            #print(f"Active Symbol: {symbol}, Active Timeframe: {timeframe}")
        
            # 최소 주문 금액 검증
            investment = None
            min_notional = 200  # 최소 명목 가치 (USDT)
            if symbol == "BTC-USDT-SWAP":
                investment = float(user_settings.get('btc_investment', 20))
            elif symbol == "ETH-USDT-SWAP":
                investment = float(user_settings.get('eth_investment', 10))
            elif symbol == "SOL-USDT-SWAP":
                investment = float(user_settings.get('sol_investment', 10))
            else:
                investment = float(user_settings.get('investment', 0))  # 기본값
            leverage = float(user_settings.get('leverage', 10))
            actual_notional = investment * leverage
            tf_str = get_timeframe(timeframe)
            logger.info(f"[{user_id}] : symbol: {symbol}, investment: {investment}, leverage: {leverage}, actual_notional: {actual_notional}")
            await asyncio.sleep(0.05)

            if restart:
                pass    
            else:
            
                if actual_notional < min_notional:
                    insufficient_balance_error = Exception(f"최소 주문 금액 미달: 현재 {actual_notional:.2f} USDT < 필요 {min_notional:.2f} USDT")
                    await handle_critical_error(
                        error=insufficient_balance_error,
                        category=ErrorCategory.INSUFFICIENT_BALANCE,
                        context={
                            "user_id": user_id,
                            "symbol": symbol,
                            "actual_notional": actual_notional,
                            "min_notional": min_notional,
                            "investment": investment,
                            "leverage": leverage
                        },
                        okx_uid=user_id
                    )
                
                    await send_telegram_message(
                        f"⚠️ 최소 주문 금액 오류\n"
                        f"─────────────────────\n"
                        f"현재 설정된 금액이 최소 주문 금액보다 작습니다.\n"
                        f"• 현재: {actual_notional:.2f} USDT\n"
                        f"• 필요: {min_notional:.2f} USDT\n"
                        f"• 최소 투자금: {min_notional:.2f} USDT\n"
                        f"• 현재 레버리지: {leverage}x\n\n"
                        f"설정을 수정하고 다시 시작해주세요.",
                        user_id
                    )
                    await redis.set(f"user:{user_id}:trading:status", "stopped")
                    await send_telegram_message(f"⚠️[{user_id}] User의 상태를 Stopped로 강제 변경2.", user_id, debug=True)
                    return
            
            
                print(f"[{user_id}] RESTART 여부 : {restart}")
                # 트레이딩 시작 메시지
                trading_start_msg = f"🚀 트레이딩을 시작합니다\n"
                trading_start_msg += f"─────────────────────\n"
                trading_start_msg += f"📊 트레이딩 설정 정보\n"
                trading_start_msg += f"─────────────────────\n"
                trading_start_msg += f"심볼: {symbol}\n"
                trading_start_msg += f"타임프레임: {timeframe}\n"
                trading_start_msg += f"투자금: {investment} USDT\n"
                trading_start_msg += f"레버리지: {leverage}x\n"
                trading_start_msg += f"명목 가치: {actual_notional:.2f} USDT"
                timeframe_long_lock_key = f"user:{user_id}:position_lock:{symbol}:long:{tf_str}"
                timeframe_short_lock_key = f"user:{user_id}:position_lock:{symbol}:short:{tf_str}"
                print(f"[{user_id}] 타임프레임 잠금 키: {timeframe_long_lock_key}, {timeframe_short_lock_key}")
                await redis.delete(timeframe_long_lock_key)
                await redis.delete(timeframe_short_lock_key)
                logger.info(f"[{user_id}] 트레이딩 시작 메시지 전송 시도. OKX UID: {user_id}, telegram_id: {telegram_id}")
                try:
                    result = await send_telegram_message(trading_start_msg, user_id)
                    logger.info(f"[{user_id}] 메시지 전송 결과: {result}")
                except Exception as e:
                    logger.error(f"[{user_id}] 메시지 전송 실패: {str(e)}")
                    import traceback
                    traceback.print_exc()
            
                # 트레이딩 시작 로그 기록
                config_data = {
                    'timeframe': timeframe,
                    'investment': investment,
                    'leverage': leverage,
                    'actual_notional': actual_notional
                }
                log_bot_start(user_id=user_id, symbol=symbol, config=config_data)
            
                await init_user_position_data(user_id, symbol, "long")
                await init_user_position_data(user_id, symbol, "short")
                await init_user_monitoring_data(user_id, symbol)
                # 기존 main_position_direction 키가 있으면 삭제
                main_position_key = f"user:{user_id}:position:{symbol}:main_position_direction"
                hedging_position_key = f"user:{user_id}:position:{symbol}:hedging_position_direction"
                if await redis.exists(main_position_key):
                    await redis.delete(main_position_key)
                if await redis.exists(hedging_position_key):
                    await redis.delete(hedging_position_key)



            position_info = await trading_service.fetch_okx_position(user_id, symbol, user_settings, debug_entry_number=5)
            leverage = float(user_settings.get('leverage', 1.0))

            # position_info가 이제 {'long': {...}, 'short': {...}} 형태이므로
            # 현재 레버리지는 존재하는 포지션에서 가져옴
            current_leverage = None
            if position_info:
                # long 포지션이 있으면 우선 사용
                if 'long' in position_info:
                    current_leverage = float(position_info['long'].get('leverage', leverage))
                # 없으면 short 포지션에서 가져옴
                elif 'short' in position_info:
                    current_leverage = float(position_info['short'].get('leverage', leverage))
                else:
                    current_leverage = leverage

            #print(f"레버리지: {leverage}, 현재 레버리지: {current_leverage}")
            is_hedge_mode, tdMode = await trading_service.get_position_mode(user_id, symbol)
            is_running = await redis.get(f"user:{user_id}:trading:status")
            if not restart:
                try:
                    if leverage > 1.0 and current_leverage != leverage:
                        # 열린 주문이 있는지 확인
                        try:
                            cancel_response = await trading_service.cancel_all_open_orders(exchange= okx_instance, symbol = symbol, user_id  = user_id)
                            if cancel_response:
                                print("레버리지 변경 전 주문 취소 성공")
                        except Exception as e:
                            traceback.print_exc()
                            logger.error(f"레버리지 변경 전 주문 취소 실패: {str(e)}")
                            await send_telegram_message(f"⚠️ 레버리지 변경 전 주문 취소 실패: {str(e)}", user_id, debug=True)
                
                    # 레버리지 설정 시도
                    try:
                        if is_hedge_mode:
                            for pos_side in ['long', 'short']:
                                await okx_instance.set_leverage(leverage, symbol, {
                                'marginMode': 'cross',
                                'posSide': pos_side
                            })
                                print("레버리지 설정 성공")
                                await asyncio.sleep(0.5)
                        else:
                            await okx_instance.set_leverage(leverage, symbol, {
                                'marginMode': 'cross'
                            })
                            print("레버리지 설정 성공")
                            await asyncio.sleep(0.5)  # API 레이트 리밋 고려
                    except Exception as e:
                        symbol_name = symbol.split("-")[0]
                        if "59000" in str(e):  # 열린 주문이나 포지션이 있는 경우
                            logger.warning("포지션이 있어 레버리지 변경이 불가능합니다.")
                            #traceback.print_exc()
                            await send_telegram_message(
                                f"⚠️{symbol_name}"
                                f"━━━━━━━━━━━━━━━\n"
                                f"⚠️ 포지션 혹은 열린 주문이 있어 레버리지 변경이 불가능합니다.\n"
                                "레버리지 변경을 원하시면 직접 변경해주세요.\n"
                                f"━━━━━━━━━━━━━━━\n",
                                f"(참고 : 자동 트레이딩의 시작은 {symbol_name} 포지션이 없는 상태에서 시작됩니다.)\n",
                                user_id
                            )
                        else:
                            raise e
                except Exception as e:
                    logger.error(f"레버리지 설정 오류: {str(e)}")
                    #await send_telegram_message(
                    #    f"⚠️ 레버리지 설정 실패\n"
                    #    f"에러: {str(e)}\n"
                    #    f"필요한 경우 직접 변경해주세요.",
                    #    user_id
                    #)
            if is_running:
                # 설정 업데이트
                #print("설정 업데이트 호출")
                tf_str = get_timeframe(timeframe)
                current_price = await get_current_price(symbol, tf_str)
                settings_str = await redis.get(f"user:{user_id}:settings")
                candle_key = f"candles_with_indicators:{symbol}:{tf_str}"
                raw_data = await redis.lindex(candle_key, -1)
                if not raw_data:
                    # 15분에 한 번만 알림을 보내도록 제한
                    alert_key = f"candle_data_alert_sent:{user_id}:{symbol}:{tf_str}"
                    already_sent = await redis.get(alert_key)
                    if not already_sent:
                        await send_telegram_message("⚠️ 캔들 데이터를 찾을 수 없습니다.\n관리자에게 문의해주세요.", user_id, debug=True )
                        # 15분(900초) 동안 알림 재전송 방지
                        await redis.setex(alert_key, 3600, "1")
                    return
                candle_data = json.loads(raw_data)
                #print("atr_value: ", atr_value)
                if settings_str:
                    try:
                        user_settings = json.loads(settings_str)
                    except json.JSONDecodeError:
                        logger.error(f"설정 데이터 파싱 실패: user_id={user_id}")
                        return
                else:
                    logger.error(f"설정을 찾을 수 없음: user_id={user_id}")
                    return
                #print("설정 업데이트 완료")
                trading_status = await redis.get(f"user:{user_id}:trading:status")
                # 바이트 문자열을 디코딩
                if isinstance(trading_status, bytes):
                    trading_status = trading_status.decode('utf-8')
                if trading_status != "running":
                    logger.info(f"[{user_id}] 트레이딩 중지 감지. telegram_id: {telegram_id}")
                    # 메시지 전송 (OKX UID 사용)
                    await send_telegram_message(
                        "🛑 트레이딩 중지\n"
                        "─────────────────────\n"
                        "트레이딩이 중지되었습니다.",
                        user_id  # 여기서 user_id는 이미 OKX UID로 변환됨
                    )
                    return
                #=======================================
                trading_status = await redis.get(f"user:{user_id}:trading:status")
                if isinstance(trading_status, bytes):
                    trading_status = trading_status.decode('utf-8')
                if trading_status != "running":
                    logger.info(f"[{user_id}] 트레이딩 중지 상태 감지: {trading_status}")
                    return
                #=======================================
                # --- (1) 주문 상태 모니터링(폴링) ---
                try:
                    start_time = datetime.now()
                    #print("=====================================")
                    #print("주문 상태 모니터링 호출")
                    await trading_service.monitor_orders(user_id)
                    end_time = datetime.now()
                    #print("주문 상태 모니터링 완료 시간 : ", end_time.strftime('%Y-%m-%d %H:%M:%S'))
                    #print("주문 상태 모니터링 소요 시간 : ", end_time - start_time)
                    #print("=====================================")
                except Exception as e:
                    error_logger.error(f"[{user_id}]:monitor_orders 에러", exc_info=True)
                    await handle_critical_error(
                        error=e,
                        category=ErrorCategory.ORDER_EXECUTION,
                        context={"user_id": user_id, "symbol": symbol, "operation": "monitor_orders"},
                        okx_uid=user_id
                    )

                # --- (2) RSI / 트랜드 분석 ---
                tf_str = get_timeframe(timeframe)
                redis_key = f"candles_with_indicators:{symbol}:{tf_str}"
                #print(f"[{user_id}] redis_key: {redis_key}")
                # 여러 캔들 데이터를 가져옵니다 (최소 마지막 14개)
                raw_data_list = await redis.lrange(redis_key, -14, -1)
                #print(f"[{user_id}] raw_data_list: {raw_data_list}") #<-- 1h 정상 작동
                if not raw_data_list or len(raw_data_list) < 2:  # 최소 2개 이상의 데이터가 필요
                    raw_data = await redis.lindex(redis_key, -1)
                    if not raw_data:
                        # 15분에 한 번만 알림을 보내도록 제한
                        alert_key = f"candle_data_alert_sent:{user_id}:{symbol}:{tf_str}"
                        already_sent = await redis.get(alert_key)
                        if not already_sent:
                            await send_telegram_message("⚠️ 캔들 데이터를 찾을 수 없습니다.\n관리자에게 문의해주세요.", user_id, debug=True)
                            # 15분(900초) 동안 알림 재전송 방지
                            await redis.setex(alert_key, 3600, "1")
                        return

                #=======================================
                trading_status = await redis.get(f"user:{user_id}:trading:status")
                if isinstance(trading_status, bytes):
                    trading_status = trading_status.decode('utf-8')
                if trading_status != "running":
                    logger.info(f"[{user_id}] 트레이딩 중지 상태 감지: {trading_status}")
                    return
                #=======================================
                # 모든 캔들에서 RSI 값 추출
                rsi_values = []
                for raw_data in raw_data_list:
                    candle_data = json.loads(raw_data)
                    if 'rsi' in candle_data and candle_data['rsi'] is not None:
                        rsi_values.append(candle_data['rsi'])
                            # RSI 값이 충분하지 않은 경우 처리
                if len(rsi_values) < 2:
                    await send_telegram_message("⚠️ 충분한 RSI 데이터가 없습니다.\n관리자에게 문의해주세요.", user_id, debug=True)
                    return
                candle_data = json.loads(raw_data)
                current_rsi = candle_data['rsi']
                #print("current_rsi: ", current_rsi)
                trend_timeframe = user_settings['trend_timeframe']
                if trend_timeframe is None:
                    trend_timeframe = str(timeframe)
                trend_timeframe_str = get_timeframe(trend_timeframe)
                rsi_signals = await trading_service.check_rsi_signals(
                    rsi_values,
                    {
                        'entry_option': user_settings['entry_option'],
                        'rsi_oversold': user_settings['rsi_oversold'],
                        'rsi_overbought': user_settings['rsi_overbought']
                    }
                )
                #print("rsi_signals: ", rsi_signals)
                analysis = await calculator.analyze_market_state_from_redis(symbol, str(timeframe), trend_timeframe_str)
                current_state = analysis['trend_state']
                # --- (3) 포지션 분기 ---
                current_position = await trading_service.get_current_position(user_id, symbol)
            
                if current_position:  # 포지션이 있는 경우
                    try:
                        min_size_key = f"user:{user_id}:position:{symbol}:min_sustain_contract_size"
                        min_sustain_contract_size = await redis.get(min_size_key)
                        if min_sustain_contract_size is None:
                            min_sustain_contract_size = 0.01
            
                        if min_sustain_contract_size:  # min_size가 Redis에 저장되어 있는 경우만 체크
                            min_sustain_contract_size = float(min_sustain_contract_size) if isinstance(min_sustain_contract_size, (str, bytes)) else min_sustain_contract_size
                            min_sustain_contract_size = max(float(min_sustain_contract_size), 0.01)
                            current_contracts_amount = float(current_position.contracts_amount)

                            if current_contracts_amount <= min_sustain_contract_size:
                                logger.info(f"포지션 크기({current_contracts_amount})가 최소 크기({min_sustain_contract_size})보다 작아 청산 진행")
                                position_info_str = str(current_position).replace('<', '&lt;').replace('>', '&gt;')
                                await send_telegram_message(f"⚠️ 포지션 크기({current_contracts_amount})가 최소 크기({min_sustain_contract_size})보다 작아 청산 진행\n"
                                                            f"━━━━━━━━━━━━━━━\n"
                                                            f"포지션 정보 : {position_info_str}\n"
                                                            f"━━━━━━━━━━━━━━━\n"
                                                            f"최소 크기: {min_sustain_contract_size}\n"
                                                            f"━━━━━━━━━━━━━━━\n", user_id, debug=True)
                                await trading_service.close_position(
                                    user_id=user_id,
                                    symbol=symbol,
                                    percent=100,
                                    comment="최소 수량 미만 포지션 청산",
                                    side=current_position.side
                                )
                                current_position = None
                    except Exception as e:  
                        traceback.print_exc()
                        logger.error(f"[{user_id}]:포지션 청산 오류", exc_info=True)
                        await handle_critical_error(
                            error=e,
                            category=ErrorCategory.POSITION_MANAGEMENT,
                            context={
                                "user_id": user_id,
                                "symbol": symbol,
                                "operation": "close_min_position",
                                "position_size": current_contracts_amount if 'current_contracts_amount' in locals() else None,
                                "min_size": min_sustain_contract_size if 'min_sustain_contract_size' in locals() else None
                            },
                            okx_uid=user_id
                        )
                        await send_telegram_message(f"⚠️ 포지션 청산 오류: {str(e)}", user_id, debug=True)
                # 마지막 포지션 출력 시간 체크
                last_print_key = f"user:{user_id}:last_position_print_time"
                last_print_time = await redis.get(last_print_key)
                current_time = int(time.time())
            
                if not last_print_time or (current_time - int(last_print_time)) >= 300:  # 300초 = 5분
                    logger.debug(f"Current Position : {current_position}")
                    await redis.set(last_print_key, str(current_time))
            
                trading_status = await redis.get(f"user:{user_id}:trading:status")
                if isinstance(trading_status, bytes):
                    trading_status = trading_status.decode('utf-8')
                if trading_status != "running":
                    logger.info(f"[{user_id}] 트레이딩 중지 상태 감지: {trading_status}")
                    return
                if not current_position:
                    logger.info(f"[{user_id}]포지션이 없다고 출력 됨.")
                    await handle_no_position(
                        user_id, user_settings, trading_service, calculator,
                        symbol, timeframe,
                        current_rsi, rsi_signals, current_state
                    )
                    trading_status = await redis.get(f"user:{user_id}:trading:status")
                    if isinstance(trading_status, bytes):
                        trading_status = trading_status.decode('utf-8')
                    if trading_status is None:
                        logger.info(f"⚠️Not FOUND [{user_id}] Trading Status!!. Trading Status :  {trading_status}")
                        await send_telegram_message(f"⚠️Not FOUND [{user_id}] Trading Status!!. Trading Status :  {trading_status}", user_id, debug=True)
                        return
                    if trading_status != "running":
                        logger.info(f"[{user_id}] 트레이딩 중지 상태 감지: {trading_status}")
                        return
                else:
                    try:
                        #print("포지션이 있다고 출력 됨.")
                        main_position_direction_key = f"user:{user_id}:position:{symbol}:main_position_direction"
                        direction = await redis.get(main_position_direction_key)
                        if direction is None:
                            direction = "any"
                        await handle_existing_position(
                            user_id, user_settings, trading_service,
                            symbol, timeframe,
                            current_position, current_rsi, rsi_signals, current_state, side = direction
                        )
                        trading_status = await redis.get(f"user:{user_id}:trading:status")
                        if isinstance(trading_status, bytes):
                            trading_status = trading_status.decode('utf-8')
                        if trading_status != "running":
                            logger.info(f"[{user_id}] 트레이딩 중지 상태 감지: {trading_status}")
                            return
                    except Exception as e:
                        error_logger.error(f"[{user_id}]:포지션 처리 오류", exc_info=True)
                        error_logger.error(f"[{user_id}] Calling handle_critical_error for position error")
                        try:
                            await handle_critical_error(
                                error=e,
                                category=ErrorCategory.POSITION_MANAGEMENT,
                                context={
                                    "user_id": user_id,
                                    "symbol": symbol,
                                    "operation": "handle_existing_position",
                                    "position_side": current_position.side if current_position else None
                                },
                                okx_uid=user_id
                            )
                            error_logger.error(f"[{user_id}] handle_critical_error completed successfully")
                        except Exception as critical_error:
                            error_logger.error(f"[{user_id}] handle_critical_error failed: {str(critical_error)}", exc_info=True)
                    
                        await send_telegram_message(f"⚠️ 포지션 처리 오류: {str(e)}", user_id, debug=True)
                logger.debug(f"[{user_id}] 트레이딩 로직 루프 완료. 현재 RSI: {current_rsi}, 현재 상태: {current_state}") # 디버깅용

                #=======================================
                trading_status = await redis.get(f"user:{user_id}:trading:status")
                if isinstance(trading_status, bytes):
                    trading_status = trading_status.decode('utf-8')
                if trading_status != "running":
                    logger.info(f"[{user_id}] 트레이딩 중지 상태 감지: {trading_status}")
                    return
                #=======================================
            end_time_loop = datetime.now()
            #print(f"[{user_id}] 루프 끝. 시간 : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            #print(f"[{user_id}] 루프 소요 시간 : {end_time_loop - start_time_loop}")
            return
        except Exception as e:
            error_logger.error(f"[{user_id}]:execute_trading_logic 오류", exc_info=True)
            #await send_telegram_message(f"[{user_id}]종료되었습니다. 잠시 후 다시 실행해주세요", user_id)
            #await send_telegram_message(f"[{user_id}]종료되었습니다. 잠시 후 다시 실행해주세요: {str(e)}", user_id, debug=True)
            traceback.print_exc()

        finally:
            if trading_service:
                await trading_service.close()
                #print("trading_service 종료")
        
            # 트레이딩 종료 여부 확인 및 로그 기록
            trading_status = await redis.get(f"user:{user_id}:trading:status")
            if trading_status == "stopped":
                # 가장 먼저 로그를 기록
                log_bot_stop(user_id=user_id, symbol=symbol, reason="사용자 요청 또는 시스템에 의한 종료")
                #await send_telegram_message("트레이딩이 종료되었습니다.", user_id)


        # ======== 실제 실행 예시 ========
async def main():
    """테스트용 함수: 단일 사용자에 대해 트레이딩 로직을 실행합니다."""
    test_user_id = 1709556958
    
    await execute_trading_logic(test_user_id, "BTC-USDT-SWAP", "1m", restart=True)

if __name__ == "__main__":
    # 직접 실행 시 테스트 함수 호출
    asyncio.run(main())
    
    # Celery 태스크로 실행하려면 아래 코드를 사용하세요:
    # from HYPERRSI.src.trading.tasks import start_trading
    # start_trading.delay("1709556958", "BTC-USDT-SWAP", "1m")