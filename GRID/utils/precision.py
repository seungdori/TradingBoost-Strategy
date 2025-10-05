"""정밀도 처리 유틸리티"""

import math


def get_upbit_precision(price):
    """
    Upbit 호가 구조에 맞춰 가격의 정밀도를 반환합니다.

    Args:
        price: 가격

    Returns:
        int: 정밀도 (소수점 자리수)
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


async def get_price_precision(symbol, exchange_instance, redis=None):
    """
    거래소별 가격 정밀도를 조회합니다. (Redis 캐싱)

    Args:
        symbol: 심볼
        exchange_instance: 거래소 인스턴스
        redis: Redis 클라이언트 (None이면 자동 생성)

    Returns:
        int: 가격 정밀도
    """
    from core.redis import get_redis_connection, get_redis_data, set_redis_data

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
            return cached_precision

        # 캐시된 데이터가 없으면 기존 로직 실행
        markets = await exchange_instance.load_markets()
        market = None

        try:
            if str(exchange_instance).lower() == 'upbit':
                symbol_parts = symbol.split('-')
                converted_symbol = f"{symbol_parts[1]}/{symbol_parts[0]}"
                print(converted_symbol)
                market = markets.get(converted_symbol, None)
                precision = market['precision']['price']
                if precision < 1:
                    precision = -int(math.log10(precision))
                else:
                    precision = 0
            else:
                try:
                    market = exchange_instance.market(symbol)
                    if market is not None:
                        if exchange_instance.id == 'bitget':
                            print(market)
                            precision = int(market['info']['pricePrecision'])
                            if precision < 1:
                                precision = -int(math.log10(precision))
                            else:
                                precision = 0
                        else:  # 바이낸스 등 다른 거래소
                            precision = market['precision']['price']
                            if precision is not None and (precision >= 1):
                                precision = int(precision)
                            elif precision is not None and (precision < 1):
                                precision = -int(math.log10(precision))
                            else:
                                print('precision: is none')
                                precision = 0
                    else:
                        precision = 0
                except Exception as e:
                    print(f"An error occurred in get_price_precision (inner): {e}")
                    precision = 0
        except Exception as e:
            print(f"An error occurred in get_price_precision: {e}")
            precision = 0

        # 결과를 Redis에 저장
        await set_redis_data(redis, redis_key, precision)
        return precision
    finally:
        if new_redis_flag:
            await redis.aclose()


def adjust_price_precision(price, precision):
    """
    가격을 지정된 정밀도로 조정합니다.

    Args:
        price: 원본 가격
        precision: 정밀도

    Returns:
        float: 조정된 가격
    """
    precision = int(precision)
    if precision is None:
        return price  # precision이 None이면 원래 가격을 그대로 반환
    try:
        return round(price, int(precision))
    except (ValueError, TypeError):
        print(f"Invalid precision value: {precision}. Using original price.({price})")
        return price
