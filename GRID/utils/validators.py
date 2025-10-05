"""검증 및 파싱 유틸리티"""

# shared 모듈에서 공통 유틸리티 import
from shared.utils import parse_bool  # noqa: F401 (re-export for backward compatibility)


def check_order_validity(notional_usd, pos, max_notional_value, order_direction):
    """
    주문 유효성을 검증합니다.

    Args:
        notional_usd: 현재 포지션의 USD 명목 가치
        pos: 현재 포지션 크기 (양수: 롱, 음수: 숏)
        max_notional_value: 최대 허용 명목 가치
        order_direction: 주문 방향 ('long' 또는 'short')

    Returns:
        bool: 주문 가능 여부
    """
    if pos > 0:  # 현재 롱 포지션
        if order_direction == 'long' and notional_usd >= max_notional_value:
            return False  # 주문 불가 (이미 최대 notional 값에 도달)
        elif order_direction == 'short':
            return True  # 주문 가능 (반대 방향으로 주문)
    elif pos < 0:  # 현재 숏 포지션
        if order_direction == 'short' and abs(notional_usd) >= max_notional_value:
            return False  # 주문 불가 (이미 최대 notional 값에 도달)
        elif order_direction == 'long':
            return True  # 주문 가능 (반대 방향으로 주문)
    else:  # pos == 0, 현재 포지션 없음
        return True  # 주문 가능

    return True  # 기본적으로 주문 가능
