"""트레이딩 관련 공통 유틸리티 함수"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def get_actual_order_type(order_data: dict) -> str:
    """
    실제 order_type을 결정합니다.
    order_type이 없거나 불명확한 경우 order_name을 확인합니다.

    Args:
        order_data: Redis에서 가져온 주문 데이터

    Returns:
        str: 실제 order_type (tp1, tp2, tp3, sl, break_even 등)

    Examples:
        >>> order_data = {"order_type": "limit", "order_name": "tp1"}
        >>> get_actual_order_type(order_data)
        'tp1'

        >>> order_data = {"order_type": "sl", "order_name": ""}
        >>> get_actual_order_type(order_data)
        'sl'
    """
    if not isinstance(order_data, dict):
        logger.warning(f"get_actual_order_type: order_data가 dict가 아님: {type(order_data)}")
        return "unknown"

    order_type = order_data.get("order_type", "unknown")
    order_name = order_data.get("order_name", "")

    # order_type이 제대로 설정되어 있으면 그대로 사용
    # limit, market은 주문 방식이지 주문 목적이 아니므로 order_name 확인 필요
    if order_type not in ["unknown", "limit", "market", "", None]:
        return order_type

    # order_name이 있고 유효한 경우 사용
    if order_name and isinstance(order_name, str):
        # tp로 시작하는 경우 (tp1, tp2, tp3)
        if order_name.startswith("tp") and len(order_name) >= 3:
            # tp1, tp2, tp3만 허용
            if order_name in ["tp1", "tp2", "tp3"]:
                return order_name
        # sl인 경우
        elif order_name == "sl":
            return "sl"
        # break_even인 경우
        elif order_name == "break_even":
            return "break_even"

    # 둘 다 없으면 unknown 반환
    return "unknown"


def is_valid_order_type(order_type: str) -> bool:
    """
    주문 타입의 유효성을 확인합니다.

    Args:
        order_type: 확인할 주문 타입

    Returns:
        bool: 유효한 주문 타입인지 여부

    Examples:
        >>> is_valid_order_type("tp1")
        True
        >>> is_valid_order_type("invalid")
        False
    """
    valid_types = ["tp1", "tp2", "tp3", "sl", "break_even", "limit", "market"]
    return order_type in valid_types


def normalize_order_type(order_type: str) -> str:
    """
    주문 타입을 정규화합니다.

    Args:
        order_type: 정규화할 주문 타입

    Returns:
        str: 정규화된 주문 타입

    Examples:
        >>> normalize_order_type("TP1")
        'tp1'
        >>> normalize_order_type("BREAK_EVEN")
        'break_even'
    """
    if not order_type:
        return "unknown"

    normalized = order_type.lower().strip()

    # 유효성 검사
    if is_valid_order_type(normalized):
        return normalized

    return "unknown"


def parse_order_info(order_data: dict) -> dict:
    """
    주문 데이터를 파싱하여 필요한 정보를 추출합니다.

    Args:
        order_data: 주문 데이터 딕셔너리

    Returns:
        dict: 파싱된 주문 정보
        {
            'order_type': str,
            'order_name': str,
            'price': float,
            'quantity': float,
            'side': str,
            'status': str
        }

    Examples:
        >>> order_data = {
        ...     "order_type": "limit",
        ...     "order_name": "tp1",
        ...     "price": 50000.0,
        ...     "quantity": 0.01,
        ...     "side": "long"
        ... }
        >>> info = parse_order_info(order_data)
        >>> info['order_type']
        'tp1'
    """
    if not isinstance(order_data, dict):
        logger.warning(f"parse_order_info: order_data가 dict가 아님: {type(order_data)}")
        return {
            'order_type': 'unknown',
            'order_name': '',
            'price': 0.0,
            'quantity': 0.0,
            'side': '',
            'status': ''
        }

    return {
        'order_type': get_actual_order_type(order_data),
        'order_name': order_data.get('order_name', ''),
        'price': float(order_data.get('price', 0.0)),
        'quantity': float(order_data.get('quantity', 0.0)),
        'side': order_data.get('side', ''),
        'status': order_data.get('status', '')
    }


def is_tp_order(order_type: str) -> bool:
    """
    TP(Take Profit) 주문인지 확인합니다.

    Args:
        order_type: 주문 타입

    Returns:
        bool: TP 주문 여부

    Examples:
        >>> is_tp_order("tp1")
        True
        >>> is_tp_order("sl")
        False
    """
    return order_type in ["tp1", "tp2", "tp3"]


def is_sl_order(order_type: str) -> bool:
    """
    SL(Stop Loss) 주문인지 확인합니다.

    Args:
        order_type: 주문 타입

    Returns:
        bool: SL 주문 여부

    Examples:
        >>> is_sl_order("sl")
        True
        >>> is_sl_order("tp1")
        False
    """
    return order_type == "sl"


def is_break_even_order(order_type: str) -> bool:
    """
    Break Even 주문인지 확인합니다.

    Args:
        order_type: 주문 타입

    Returns:
        bool: Break Even 주문 여부

    Examples:
        >>> is_break_even_order("break_even")
        True
        >>> is_break_even_order("tp1")
        False
    """
    return order_type == "break_even"
