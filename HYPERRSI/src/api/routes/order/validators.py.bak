"""
Order Validation Utilities

주문 데이터 검증 유틸리티 함수들
"""
from typing import Optional, Dict, Any
from decimal import Decimal
from HYPERRSI.src.api.exchange.models import OrderSide, OrderType


def validate_order_amount(amount: float) -> bool:
    """
    주문 수량 유효성 검증

    Args:
        amount: 주문 수량

    Returns:
        bool: 유효하면 True
    """
    if amount is None:
        return False
    return amount > 0


def validate_order_price(price: Optional[float], order_type: str) -> bool:
    """
    주문 가격 유효성 검증

    Args:
        price: 주문 가격
        order_type: 주문 타입 (market, limit)

    Returns:
        bool: 유효하면 True
    """
    if order_type.lower() == "limit":
        if price is None or price <= 0:
            return False
    return True


def validate_close_percent(close_percent: float) -> bool:
    """
    포지션 종료 비율 검증

    Args:
        close_percent: 종료할 포지션 비율 (1-100)

    Returns:
        bool: 유효하면 True
    """
    return 1.0 <= close_percent <= 100.0


def validate_stop_loss_params(
    trigger_price: Optional[float],
    order_price: Optional[float],
    side: str
) -> tuple[bool, Optional[str]]:
    """
    스탑로스 파라미터 검증

    Args:
        trigger_price: 트리거 가격
        order_price: 주문 가격
        side: 포지션 사이드 (long/short)

    Returns:
        tuple[bool, Optional[str]]: (유효성, 에러 메시지)
    """
    if trigger_price is None or trigger_price <= 0:
        return False, "트리거 가격이 유효하지 않습니다"

    if order_price is not None and order_price <= 0:
        return False, "주문 가격이 유효하지 않습니다"

    # Long 포지션의 스탑로스는 현재가보다 낮아야 함
    # Short 포지션의 스탑로스는 현재가보다 높아야 함
    # (이 검증은 실제 현재가와 비교해야 하므로 서비스 레이어에서 수행)

    return True, None


def validate_symbol_format(symbol: str) -> bool:
    """
    심볼 형식 검증

    Args:
        symbol: 거래 심볼 (예: BTC-USDT-SWAP)

    Returns:
        bool: 유효하면 True
    """
    if not symbol or not isinstance(symbol, str):
        return False

    # OKX 스왑 심볼 형식: XXX-USDT-SWAP
    parts = symbol.split("-")
    if len(parts) != 3:
        return False

    if parts[2] not in ["SWAP", "FUTURES"]:
        return False

    return True


def validate_order_side(side: str) -> bool:
    """
    주문 사이드 검증

    Args:
        side: 주문 사이드 (buy/sell)

    Returns:
        bool: 유효하면 True
    """
    return side.lower() in ["buy", "sell"]


def validate_order_type(order_type: str) -> bool:
    """
    주문 타입 검증

    Args:
        order_type: 주문 타입 (market/limit)

    Returns:
        bool: 유효하면 True
    """
    return order_type.lower() in ["market", "limit"]


def validate_leverage(leverage: int) -> bool:
    """
    레버리지 검증

    Args:
        leverage: 레버리지 배수

    Returns:
        bool: 유효하면 True
    """
    return 1 <= leverage <= 125


def validate_position_mode(mode: str) -> bool:
    """
    포지션 모드 검증

    Args:
        mode: 포지션 모드 (long_short_mode, net_mode)

    Returns:
        bool: 유효하면 True
    """
    return mode in ["long_short_mode", "net_mode"]
