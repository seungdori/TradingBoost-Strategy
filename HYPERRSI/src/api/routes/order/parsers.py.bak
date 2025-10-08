"""
Order Response Parsers

주문 데이터를 OrderResponse 모델로 변환하는 파서 함수들
"""
from decimal import Decimal
from typing import Optional
import datetime as dt

from HYPERRSI.src.api.exchange.models import OrderResponse, OrderStatus, OrderSide, OrderType
from shared.utils.type_converters import safe_float, safe_decimal
from .models import STATUS_MAPPING


def parse_order_response(order_data: dict) -> OrderResponse:
    """
    거래소 주문 데이터를 OrderResponse 모델로 변환

    Args:
        order_data: CCXT 주문 데이터 딕셔너리

    Returns:
        OrderResponse: 파싱된 주문 응답
    """
    return OrderResponse(
        order_id=order_data["id"],
        symbol=order_data["symbol"],
        side=order_data["side"],
        type=order_data["type"],
        amount=safe_float(order_data["amount"]),
        filled=safe_float(order_data["filled"]),
        price=safe_float(order_data["price"]) if order_data.get("price") else None,
        average_price=safe_float(order_data["average"]) if order_data.get("average") else None,
        status=order_data["status"],
        timestamp=dt.datetime.fromtimestamp(order_data["timestamp"] / 1000) if order_data.get("timestamp") else dt.datetime.now(),
        pnl=safe_float(order_data["info"].get("pnl"))
    )


def parse_algo_order_to_order_response(algo_order: dict, algo_type: str) -> OrderResponse:
    """
    OKX 알고주문(Trigger) 데이터를 OrderResponse 형태로 변환

    Args:
        algo_order: OKX 알고리즘 주문 데이터
        algo_type: 알고리즘 주문 타입 (trigger, conditional)

    Returns:
        OrderResponse: 파싱된 주문 응답
    """
    # 기본 정보 매핑
    order_id = algo_order.get("algoId", "N/A")
    client_order_id = algo_order.get("clOrdId")
    symbol = algo_order.get("instId", "N/A")

    # side 매핑
    side_str = algo_order.get("side", "").lower()
    side = OrderSide.BUY if side_str == "buy" else OrderSide.SELL

    # type 매핑
    o_type_str = algo_order.get("ordType", algo_type)
    o_type = OrderType.MARKET if o_type_str == "market" else OrderType.LIMIT

    # 수량 관련
    amount = safe_decimal(algo_order.get("sz", 0.0))
    filled_amount = safe_decimal(algo_order.get("fillSz", 0.0))
    remaining_amount = Decimal(amount - filled_amount)

    # 가격 관련
    price = safe_decimal(algo_order.get("triggerPx"))
    average_price = safe_decimal(algo_order.get("actualPx")) or None

    # 상태 매핑 (OrderStatus enum에 맞게)
    status_map = {
        "live": OrderStatus.OPEN,
        "canceled": OrderStatus.CANCELED,
        "partially_filled": OrderStatus.PARTIALLY_FILLED,
        "filled": OrderStatus.FILLED,
        "failed": OrderStatus.REJECTED
    }
    status = status_map.get(algo_order.get("state", "").lower(), OrderStatus.PENDING)

    # 시간 처리
    created_at = int(algo_order.get("cTime")) if algo_order.get("cTime", "").isdigit() else None
    updated_at = int(algo_order.get("uTime")) if algo_order.get("uTime", "").isdigit() else None

    # PNL 처리
    pnl = safe_decimal(algo_order.get("pnl", "0"))

    return OrderResponse(
        order_id=order_id,
        client_order_id=client_order_id,
        symbol=symbol,
        status=status,
        side=side,
        type=o_type,
        amount=amount,
        filled_amount=filled_amount,
        remaining_amount=remaining_amount,
        price=price,
        average_price=average_price,
        created_at=created_at,
        updated_at=updated_at,
        pnl=pnl,
        order_type=o_type_str,
        posSide=algo_order.get("posSide", "unknown")
    )
