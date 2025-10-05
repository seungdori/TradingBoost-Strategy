"""가격 계산 유틸리티"""

from decimal import Decimal, ROUND_HALF_UP
from GRID.trading.get_minimum_qty import get_lot_sizes, get_perpetual_instruments


def round_to_upbit_tick_size(amount):
    """
    Upbit 호가 단위에 맞춰 금액을 반올림합니다.

    Args:
        amount: 반올림할 금액 (str 또는 float)

    Returns:
        float: 반올림된 금액 (None if invalid)
    """
    # 입력된 값이 문자열이고, 비어 있지 않은 경우 float로 변환
    if isinstance(amount, str) and amount.strip():
        try:
            amount = float(amount)
        except ValueError:
            return None
    elif isinstance(amount, str):
        # 빈 문자열이거나 공백만 있는 경우
        return None

    # 금액에 따라 tick_size 결정
    if amount >= 1000:
        tick_size = Decimal('0.1')
    elif amount >= 100:
        tick_size = Decimal('0.01')
    elif amount >= 1:
        tick_size = Decimal('0.01')
    elif amount >= 0.01:
        tick_size = Decimal('0.0001')
    elif amount >= 0.0001:
        tick_size = Decimal('0.0001')
    else:
        tick_size = Decimal('0.0001')

    # Decimal을 사용하여 반올림
    amount_decimal = Decimal(str(amount))
    rounded_amount = amount_decimal.quantize(tick_size, rounding=ROUND_HALF_UP)

    return float(rounded_amount)


def get_order_price_unit_upbit(price):
    """
    Upbit 호가 구조에 따라 주문 가격 단위를 반환합니다.

    Args:
        price: 가격

    Returns:
        float: 주문 가격 단위
    """
    if price >= 2000000:
        return 2000
    elif 1000000 <= price < 2000000:
        return 1000
    elif 500000 <= price < 1000000:
        return 500
    elif 100000 <= price < 500000:
        return 100
    elif 10000 <= price < 100000:
        return 50
    elif 1000 <= price < 10000:
        return 10
    elif 100 <= price < 1000:
        return 1
    elif 10 <= price < 100:
        return 0.1
    elif 1 <= price < 10:
        return 0.01
    elif 0.1 <= price < 1:
        return 0.001
    elif 0.01 <= price < 0.1:
        return 0.0001
    elif 0.001 <= price < 0.01:
        return 0.00001
    elif 0.0001 <= price < 0.001:
        return 0.000001
    else:
        return 0.1


def get_corrected_rounded_price(price):
    """
    호가 구조에 맞춰 가격을 내림 처리합니다.

    Args:
        price: 원본 가격

    Returns:
        float: 조정된 가격
    """
    if price < 1:
        unit = Decimal('0.001')
    elif price < 10:
        unit = Decimal('0.01')
    elif price < 100:
        unit = Decimal('0.1')
    elif price < 1000:
        unit = Decimal('1')
    elif price < 10000:
        unit = Decimal('5')
    elif price < 50000:
        unit = Decimal('10')
    elif price < 100000:
        unit = Decimal('50')
    elif price < 500000:
        unit = Decimal('100')
    elif price < 1000000:
        unit = Decimal('500')
    else:
        unit = Decimal('1000')

    # Decimal을 사용하여 내림 처리된 가격을 반환
    price = Decimal(str(round(price, 5)))
    adjusted_price = price // unit * unit
    return float(adjusted_price)


async def get_min_notional(symbol, exchange_instance, redis=None, default_value=10):
    """
    거래소별 최소 주문 금액을 조회합니다. (Redis 캐싱)

    Args:
        symbol: 심볼
        exchange_instance: 거래소 인스턴스
        redis: Redis 클라이언트 (None이면 자동 생성)
        default_value: 기본값

    Returns:
        float: 최소 주문 금액
    """
    from core.redis import get_redis_connection, get_redis_data, set_redis_data

    new_redis_flag = False
    if redis is None:
        redis = await get_redis_connection()
        new_redis_flag = True

    try:
        # Redis 키 생성
        redis_key = f"min_notional:{exchange_instance.id}:{symbol}"

        # Redis에서 데이터 확인
        cached_min_notional = await get_redis_data(redis, redis_key)
        if cached_min_notional is not None:
            return cached_min_notional

        # 캐시된 데이터가 없으면 기존 로직 실행
        try:
            markets = await exchange_instance.load_markets()
            market = None

            if exchange_instance.name.lower() == 'upbit':
                symbol_parts = symbol.split('-')
                converted_symbol = f"{symbol_parts[1]}/{symbol_parts[0]}"
                market = markets.get(converted_symbol, None)
            else:
                market = markets.get(symbol.replace("/", ""))

            if market is not None:
                if str(exchange_instance).lower() == 'upbit':
                    print(market['precision']['amount'])
                    min_notional = float(market['precision']['amount'])
                elif exchange_instance.id == 'bitget':
                    min_notional = float(market['limits']['amount']['min'] * market['limits']['price']['min'])
                elif exchange_instance.id == 'okx':
                    print(market)
                    min_notional = float(market['limits']['amount']['min'])
                else:  # 바이낸스 등 다른 거래소
                    min_notional = float(market['limits']['cost']['min'])
            else:
                min_notional = default_value
        except Exception as e:
            print(f"An error occurred in get_min_notional: {e}")
            min_notional = default_value

        # 결과를 Redis에 저장
        await set_redis_data(redis, redis_key, min_notional)
        return min_notional
    finally:
        if new_redis_flag:
            await redis.aclose()
