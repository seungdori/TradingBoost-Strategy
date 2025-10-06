"""GRID Trading Orders Module

주문 생성 관련 함수들:
- create_long_order: 롱 주문 생성

Note: create_short_orders는 GRID.services.order_service에 위치
"""

import logging

logger = logging.getLogger(__name__)


async def create_long_order(exchange_instance, symbol, symbol_name, long_level, adjusted_quantity,
                           exchange_name, user_id, min_quantity=None):
    """롱 주문 생성

    Args:
        exchange_instance: 거래소 인스턴스
        symbol: 심볼
        symbol_name: 심볼 이름
        long_level: 롱 진입 가격
        adjusted_quantity: 조정된 수량
        exchange_name: 거래소 이름
        user_id: 사용자 ID
        min_quantity: 최소 수량

    Returns:
        생성된 주문 정보
    """
    try:
        if exchange_name == 'bitget':
            long_order = await exchange_instance.create_order(
                symbol=symbol_name,
                type='limit',
                side='buy',
                amount=adjusted_quantity,
                price=long_level,
                params={
                    'contract_type': 'swap',
                    'position_mode': 'single',
                    'marginCoin': 'USDT',
                }
            )
        elif exchange_name == 'upbit':
            long_order = await exchange_instance.create_order(
                symbol=symbol,
                type='limit',
                side='buy',
                amount=adjusted_quantity,
                price=long_level
            )
        else:  # okx, binance 등
            long_order = await exchange_instance.create_order(
                symbol=symbol,
                type='limit',
                side='buy',
                amount=adjusted_quantity,
                price=long_level
            )

        print(f"{user_id} : {symbol} long order created at {long_level}")
        return long_order

    except Exception as e:
        print(f"{user_id} : An error occurred in create_long_order: {e}")
        raise e
