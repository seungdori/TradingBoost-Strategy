"""
거래소별 가격 정밀도 처리 유틸리티

각 거래소의 호가 구조에 맞춰 가격 정밀도를 조회하고 조정하는 기능 제공
"""

import math
from typing import Optional


def get_upbit_precision(price: float) -> int:
    """
    Upbit 호가 구조에 맞춰 가격의 정밀도를 반환합니다.

    Args:
        price: 가격

    Returns:
        int: 정밀도 (소수점 자리수, 음수는 10의 거듭제곱 단위)

    Examples:
        >>> get_upbit_precision(5.5)      # 5 < price < 10
        2
        >>> get_upbit_precision(50)       # 10 < price < 100
        1
        >>> get_upbit_precision(500)      # 100 < price < 1000
        0
        >>> get_upbit_precision(5000)     # 1000 < price < 10000
        -1
    """
    if price < 10:
        precision = 2  # 소수점 아래 2자리까지
    elif price < 100:
        precision = 1  # 소수점 아래 1자리까지
    elif price < 1000:
        precision = 0  # 소수점 없음
    elif price < 10000:
        precision = -1  # 10의 단위 (10^1)
    elif price < 100000:
        precision = -1  # 10의 단위 (10^1)
    elif price < 500000:
        precision = -2  # 100의 단위 (10^2)
    elif price < 1000000:
        precision = -2  # 100의 단위 (10^2)
    elif price < 2000000:
        precision = -3  # 1000의 단위 (10^3)
    else:
        precision = -3  # 1000의 단위 (10^3)

    return precision


async def get_price_precision(
    symbol: str,
    exchange_instance,
    redis=None
) -> int:
    """
    거래소별 가격 정밀도를 조회합니다. (Redis 캐싱)

    Args:
        symbol: 심볼 (예: 'BTC-USDT-SWAP', 'KRW-BTC')
        exchange_instance: CCXT 거래소 인스턴스
        redis: Redis 클라이언트 (None이면 자동 생성)

    Returns:
        int: 가격 정밀도

    Examples:
        >>> precision = await get_price_precision('BTC-USDT-SWAP', exchange, redis_client)
    """
    from shared.database.redis import get_redis_connection
    from shared.utils.redis_utils import get_redis_data, set_redis_data

    new_redis_flag = False
    if redis is None:
        redis = await get_redis_connection()
        new_redis_flag = True

    try:
        # Redis 키 생성
        redis_key = f"price_precision:{exchange_instance.id}:{symbol}"

        # Redis에서 데이터 확인
        cached_precision = await get_redis_data(redis, redis_key)
        if cached_precision is not None:
            return int(cached_precision)

        # 캐시된 데이터가 없으면 거래소 API 호출
        markets = await exchange_instance.load_markets()
        market = None
        precision = 0

        try:
            if str(exchange_instance).lower() == 'upbit':
                # Upbit: 'KRW-BTC' -> 'BTC/KRW'
                symbol_parts = symbol.split('-')
                converted_symbol = f"{symbol_parts[1]}/{symbol_parts[0]}"
                print(f"Upbit symbol conversion: {symbol} -> {converted_symbol}")
                market = markets.get(converted_symbol, None)
                if market:
                    precision = market['precision']['price']
                    if precision < 1:
                        precision = -int(math.log10(precision))
                    else:
                        precision = 0
            else:
                # 다른 거래소 (Binance, Bitget, OKX 등)
                try:
                    market = exchange_instance.market(symbol)
                    if market is not None:
                        if exchange_instance.id == 'bitget':
                            print(f"Bitget market info: {market}")
                            precision = int(market['info']['pricePrecision'])
                            if precision < 1:
                                precision = -int(math.log10(precision))
                            else:
                                precision = 0
                        else:  # Binance, OKX 등
                            precision = market['precision']['price']
                            if precision is not None and (precision >= 1):
                                precision = int(precision)
                            elif precision is not None and (precision < 1):
                                precision = -int(math.log10(precision))
                            else:
                                print('precision is None, using 0')
                                precision = 0
                    else:
                        precision = 0
                except Exception as e:
                    print(f"Error in get_price_precision (market lookup): {e}")
                    precision = 0
        except Exception as e:
            print(f"Error in get_price_precision (outer): {e}")
            precision = 0

        # 결과를 Redis에 저장 (1일 = 86400초)
        await set_redis_data(redis, redis_key, precision, expiry=86400)
        return precision
    finally:
        if new_redis_flag and hasattr(redis, 'aclose'):
            await redis.aclose()


def adjust_price_precision(price: float, precision: Optional[int]) -> float:
    """
    가격을 지정된 정밀도로 조정합니다.

    Args:
        price: 원본 가격
        precision: 정밀도 (None이면 원본 반환)

    Returns:
        float: 조정된 가격

    Examples:
        >>> adjust_price_precision(1234.5678, 2)
        1234.57
        >>> adjust_price_precision(1234.5678, 0)
        1235.0
        >>> adjust_price_precision(1234.5678, -1)  # 10의 단위
        1230.0
        >>> adjust_price_precision(1234.5678, None)
        1234.5678
    """
    if precision is None:
        return price  # precision이 None이면 원래 가격을 그대로 반환

    try:
        precision = int(precision)
        return round(price, precision)
    except (ValueError, TypeError):
        print(f"Invalid precision value: {precision}. Using original price ({price})")
        return price
