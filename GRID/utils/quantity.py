"""수량 계산 유틸리티"""

from GRID.trading.get_minimum_qty import get_lot_sizes, get_perpetual_instruments


async def calculate_order_quantity(symbol, initial_capital_list, current_price, redis=None):
    """
    초기 자본과 현재 가격을 기반으로 주문 수량을 계산합니다.

    Args:
        symbol: 심볼
        initial_capital_list: 초기 자본 리스트
        current_price: 현재 가격
        redis: Redis 클라이언트 (미사용, 호환성 유지)

    Returns:
        list: 주문 수량 리스트
    """
    try:
        perpetual_instruments = await get_perpetual_instruments()
        lot_sizes = get_lot_sizes(perpetual_instruments)

        order_quantities = []
        if symbol in lot_sizes:
            lot_size, contract_value, base_currency = lot_sizes[symbol]
            for initial_capital in initial_capital_list:
                # 계약 수 계산
                order_quantity = initial_capital / (current_price * contract_value)
                order_quantities.append(order_quantity)
        else:
            print(f"Symbol {symbol} not found in lot_sizes. Cannot calculate order quantity.")

        return order_quantities

    except Exception as e:
        print(f"An error occurred in calculate_order_quantity: {e}")
        return []
