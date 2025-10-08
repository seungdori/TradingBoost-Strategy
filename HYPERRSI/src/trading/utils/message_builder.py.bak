# message_builder.py

import json
import traceback
from datetime import datetime
from shared.logging import get_logger
from shared.utils import contracts_to_qty
from HYPERRSI.src.trading.utils.trading_utils import calculate_dca_levels, update_dca_levels_redis
from HYPERRSI.src.trading.services.get_current_price import get_current_price
logger = get_logger(__name__)

async def create_position_message(
    user_id: str,
    symbol: str,
    position_type: str,  # "long" or "short"
    position,
    settings: dict,
    tp_levels=None,
    stop_loss=None,
    contracts_amount=None, #contract size로 들어옴. 
    trading_service=None,
    atr_value=None
):
    try:
        
        #여기로 들어오는 size가, contract size로 들어옴. 따라서 qty로 변환 필요.
        position_qty = await trading_service.contract_size_to_qty(user_id=user_id, symbol=symbol, contracts_amount=contracts_amount)
        current_price = await get_current_price(symbol)
        # 기본 메시지 구성
        print(f"[{user_id}] position 정보 확인 : \n", position)
        emoji = "📈" if position_type == "long" else "📉"
        entry_price = position.entry_price
        symbol_investment = 0
        if symbol == "BTC-USDT-SWAP":
            symbol_investment = f"{float(settings.get('btc_investment', 20)):.2f}"
        elif symbol == "ETH-USDT-SWAP":
            symbol_investment = f"{float(settings.get('eth_investment', 10)):.2f}"
        elif symbol == "SOL-USDT-SWAP":
            symbol_investment = f"{float(settings.get('sol_investment', 10)):.2f}"
        else:
            symbol_investment = f"{float(settings.get('investment', 0)):.2f}"

        if entry_price is None:
            entry_price = current_price
        message_parts = [
            f"{emoji} {'롱' if position_type == 'long' else '숏'} 포지션 진입",
            "━━━━━━━━━━━━━━━",
            f"💎 심볼: {symbol}",
            f"💰 주문금액: {symbol_investment} USDT",
            f"🪜 레버리지: {settings['leverage']}x",
            f"💲 진입가격: {entry_price:.2f}",
            f"📊 포지션 크기: {position_qty:.4g}"
            f"(USDT 기준 : {float(position_qty)*float(entry_price):.2f} USDT)"
        ]

        # TP 정보가 있는 경우에만 추가
        if tp_levels:
            message_parts.extend([
                "",
                "🎯 목표가격"
            ])
            
            # 트레일링 스탑 설정 확인
            trailing_start_point = settings.get('trailing_start_point', None)
            use_trailing_stop = settings.get('trailing_stop_active', False)
            trailing_tp_level = None
            
            if trailing_start_point and trailing_start_point.startswith('tp') and use_trailing_stop:
                try:
                    # tp2, tp3 등에서 숫자 부분 추출
                    trailing_tp_level = int(trailing_start_point[2:])
                except ValueError:
                    trailing_tp_level = None
            
            # tp_levels 형식에 따른 처리
            if isinstance(tp_levels, list):
                # 리스트인 경우 (가격만 있는 경우)
                for i, price in enumerate(tp_levels, 1):
                    # 트레일링 스탑 레벨 이전까지만 표시
                    if trailing_tp_level is None or i < trailing_tp_level:
                        message_parts.append(f"TP{i}: {float(price):,.2f} $")
                    elif i == trailing_tp_level and use_trailing_stop:
                        message_parts.append(f"TP{i}: {float(price):,.2f} $")
                        message_parts.append(f"TP{i} 도달 후부터는 트레일링 스탑이 활성화됩니다.")
                        break
            elif isinstance(tp_levels, dict):
                # 딕셔너리인 경우 (가격과 비율이 있는 경우)
                for i, (price, ratio) in enumerate(tp_levels.items(), 1):
                    if trailing_tp_level is None or i < trailing_tp_level:
                        message_parts.append(f"TP{i}: {float(price):.2f} ({float(ratio)*100:.0f}%)")
                    elif i == trailing_tp_level and use_trailing_stop:
                        message_parts.append(f"TP{i}: {float(price):.2f} ({float(ratio)*100:.0f}%)")
                        message_parts.append(f"TP{i} 도달 후부터는 트레일링 스탑이 활성화됩니다.")
                        break
            else:
                # 기타 형식의 경우
                for i, tp_info in enumerate(tp_levels, 1):
                    if trailing_tp_level is None or i < trailing_tp_level:
                        if isinstance(tp_info, (list, tuple)):
                            price, ratio = tp_info
                            message_parts.append(f"TP{i}: {float(price):,.2f} $ ({float(ratio)*100:.0f}%)")
                        else:
                            message_parts.append(f"TP{i}: {float(tp_info):,.2f} $")
                    elif i == trailing_tp_level and use_trailing_stop:
                        if isinstance(tp_info, (list, tuple)):
                            price, ratio = tp_info
                            message_parts.append(f"TP{i}: {float(price):,.2f} $ ({float(ratio)*100:.0f}%)")
                        else:
                            message_parts.append(f"TP{i}: {float(tp_info):,.2f} $")
                        message_parts.append(f"TP{i} 도달 후부터는 트레일링 스탑이 활성화됩니다.")
                        break

        # SL 정보가 있는 경우에만 추가
        if stop_loss:
            message_parts.extend([
                "",
                "🛑 손절가격",
                f"{float(stop_loss):,.2f} $"
            ])

        from HYPERRSI.src.core.database import redis_client
        dca_key = f"user:{user_id}:position:{symbol}:{position_type}:dca_levels"

        try:
            entry_price = position.entry_price  
        except Exception as e:
            entry_price = current_price

        try:
            last_filled_price = position.last_filled_price if position.last_filled_price is not None else current_price
        except Exception as e:
            last_filled_price = current_price

        dca_levels = await redis_client.lrange(dca_key, 0, -1)
        if not dca_levels:
            dca_levels = await calculate_dca_levels(entry_price, last_filled_price, settings, position_type, atr_value, current_price, user_id)
            await update_dca_levels_redis(user_id, symbol, dca_levels, position_type)

        print(f"[{user_id}] 🖤dca_levels: {dca_levels}")
        
        if dca_levels and len(dca_levels) > 0:
            dca_levels = [float(level) for level in dca_levels]  # 문자열을 float로 변환
            next_level = max(dca_levels) if position_type == 'long' else min(dca_levels)
            message_parts.extend([
                "",
                f"📍 다음 진입가능 가격\n {next_level:,.2f}$"
            ])

        return "\n".join(message_parts)
    except Exception as e:
        logger.error(f"포지션 메시지 생성 오류: {str(e)}")
        traceback.print_exc()
        return ""