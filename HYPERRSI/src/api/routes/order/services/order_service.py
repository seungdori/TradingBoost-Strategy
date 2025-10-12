"""
Order Service

일반 주문 관련 비즈니스 로직
"""
from decimal import Decimal
from typing import Any, Dict, List, Optional

import ccxt.async_support as ccxt
from fastapi import HTTPException

from HYPERRSI.src.api.exchange.models import (
    CancelOrdersResponse,
    OrderResponse,
    OrderSide,
    OrderStatus,
    OrderType,
)
from HYPERRSI.src.api.routes.order.constants import API_ENDPOINTS, REGULAR_ORDERS_CHUNK_SIZE
from HYPERRSI.src.api.routes.order.error_messages import (
    INVALID_ORDER_AMOUNT,
    INVALID_ORDER_SIDE,
    INVALID_ORDER_TYPE,
    INVALID_SYMBOL_FORMAT,
    LIMIT_ORDER_REQUIRES_PRICE,
    NO_ORDERS_TO_CANCEL,
    ORDER_NOT_FOUND,
)
from HYPERRSI.src.api.routes.order.parsers import parse_order_response
from HYPERRSI.src.api.routes.order.services.base_service import BaseService
from HYPERRSI.src.api.routes.order.validators import (
    validate_order_amount,
    validate_order_price,
    validate_order_side,
    validate_order_type,
    validate_symbol_format,
)
from HYPERRSI.src.core.logger import error_logger
from shared.logging import get_logger
from shared.utils.type_converters import safe_float

logger = get_logger(__name__)


class OrderService(BaseService):
    """일반 주문 관련 서비스"""

    @staticmethod
    @BaseService.handle_exchange_error("미체결 주문 조회")
    @BaseService.log_operation("미체결 주문 조회")
    async def get_open_orders(
        exchange: ccxt.okx,
        user_id: str,
        symbol: Optional[str] = None,
        limit: int = 100
    ) -> List[OrderResponse]:
        """
        미체결 주문 조회

        Args:
            exchange: 거래소 클라이언트
            user_id: 사용자 ID
            symbol: 심볼 (선택)
            limit: 조회 제한

        Returns:
            List[OrderResponse]: 미체결 주문 리스트

        Raises:
            HTTPException: 조회 실패 시
        """
        BaseService.validate_exchange(exchange)

        # symbol 검증
        if symbol and not validate_symbol_format(symbol):
            raise HTTPException(status_code=400, detail=INVALID_SYMBOL_FORMAT)

        orders = await exchange.fetch_open_orders(symbol=symbol, limit=limit)

        if not orders:
            return []

        return [parse_order_response(order) for order in orders]

    @staticmethod
    @BaseService.handle_exchange_error("주문 상세 조회")
    @BaseService.log_operation("주문 상세 조회")
    async def get_order_detail(
        exchange: ccxt.okx,
        order_id: str,
        symbol: str
    ) -> OrderResponse:
        """
        주문 상세 조회

        Args:
            exchange: 거래소 클라이언트
            order_id: 주문 ID
            symbol: 심볼

        Returns:
            OrderResponse: 주문 상세 정보

        Raises:
            HTTPException: 조회 실패 시
        """
        BaseService.validate_exchange(exchange)
        BaseService.validate_required_params(order_id=order_id, symbol=symbol)

        # symbol 검증
        if not validate_symbol_format(symbol):
            raise HTTPException(status_code=400, detail=INVALID_SYMBOL_FORMAT)

        order = await exchange.fetch_order(order_id, symbol)

        if not order:
            raise HTTPException(status_code=404, detail=ORDER_NOT_FOUND)

        return parse_order_response(order)

    @staticmethod
    @BaseService.handle_exchange_error("주문 생성")
    @BaseService.log_operation("주문 생성", include_args=True)
    async def create_order(
        exchange: ccxt.okx,
        symbol: str,
        side: str,
        order_type: str,
        amount: float,
        price: Optional[float] = None,
        reduce_only: bool = False,
        params: Optional[Dict[str, Any]] = None
    ) -> OrderResponse:
        """
        주문 생성

        Args:
            exchange: 거래소 클라이언트
            symbol: 심볼
            side: 주문 사이드 (buy/sell)
            order_type: 주문 타입 (market/limit)
            amount: 수량
            price: 가격 (limit 주문인 경우 필수)
            reduce_only: 감소 전용 주문 여부
            params: 추가 파라미터

        Returns:
            OrderResponse: 생성된 주문 정보

        Raises:
            HTTPException: 주문 생성 실패 시
        """
        BaseService.validate_exchange(exchange)
        BaseService.validate_required_params(symbol=symbol, side=side, amount=amount)

        # 파라미터 검증
        if not validate_symbol_format(symbol):
            raise HTTPException(status_code=400, detail=INVALID_SYMBOL_FORMAT)

        if not validate_order_side(side):
            raise HTTPException(status_code=400, detail=INVALID_ORDER_SIDE)

        if not validate_order_type(order_type):
            raise HTTPException(status_code=400, detail=INVALID_ORDER_TYPE)

        if not validate_order_amount(amount):
            raise HTTPException(status_code=400, detail=INVALID_ORDER_AMOUNT)

        if not validate_order_price(price, order_type):
            raise HTTPException(status_code=400, detail=LIMIT_ORDER_REQUIRES_PRICE)

        # 주문 파라미터 설정
        order_params = params or {}
        if reduce_only:
            order_params["reduceOnly"] = True

        # 주문 생성
        order = await exchange.create_order(
            symbol=symbol,
            type=order_type.lower(),
            side=side.lower(),
            amount=amount,
            price=price,
            params=order_params
        )

        logger.info(f"주문 생성 성공: {order.get('id')} - {symbol} {side} {amount}")
        return parse_order_response(order)

    @staticmethod
    @BaseService.handle_exchange_error("주문 취소")
    @BaseService.log_operation("주문 취소")
    async def cancel_order(
        exchange: ccxt.okx,
        order_id: str,
        symbol: str
    ) -> Dict[str, Any]:
        """
        주문 취소

        Args:
            exchange: 거래소 클라이언트
            order_id: 주문 ID
            symbol: 심볼

        Returns:
            Dict[str, Any]: 취소 결과

        Raises:
            HTTPException: 취소 실패 시
        """
        BaseService.validate_exchange(exchange)
        BaseService.validate_required_params(order_id=order_id, symbol=symbol)

        if not validate_symbol_format(symbol):
            raise HTTPException(status_code=400, detail=INVALID_SYMBOL_FORMAT)

        result = await exchange.cancel_order(order_id, symbol)

        logger.info(f"주문 취소 성공: {order_id} - {symbol}")
        return result

    @staticmethod
    @BaseService.handle_exchange_error("전체 주문 취소")
    @BaseService.log_operation("전체 주문 취소")
    async def cancel_all_orders(
        exchange: ccxt.okx,
        symbol: Optional[str] = None
    ) -> CancelOrdersResponse:
        """
        모든 주문 취소

        Args:
            exchange: 거래소 클라이언트
            symbol: 심볼 (선택)

        Returns:
            CancelOrdersResponse: 취소 결과

        Raises:
            HTTPException: 취소 실패 시
        """
        BaseService.validate_exchange(exchange)

        if symbol and not validate_symbol_format(symbol):
            raise HTTPException(status_code=400, detail=INVALID_SYMBOL_FORMAT)

        # 미체결 주문 조회
        open_orders = await exchange.fetch_open_orders(symbol=symbol)

        if not open_orders:
            return CancelOrdersResponse(
                success=True,
                canceled_count=0,
                failed_count=0,
                message=NO_ORDERS_TO_CANCEL
            )

        # 배치 단위로 주문 취소
        canceled_count = 0
        failed_count = 0

        for i in range(0, len(open_orders), REGULAR_ORDERS_CHUNK_SIZE):
            chunk = open_orders[i:i + REGULAR_ORDERS_CHUNK_SIZE]

            for order in chunk:
                try:
                    await exchange.cancel_order(order['id'], order['symbol'])
                    canceled_count += 1
                except Exception as e:
                    error_logger.error(f"주문 취소 실패 - ID: {order['id']}, 오류: {str(e)}")
                    failed_count += 1

        message = f"총 {canceled_count}개 주문 취소, {failed_count}개 실패"
        logger.info(message)

        return CancelOrdersResponse(
            success=failed_count == 0,
            canceled_count=canceled_count,
            failed_count=failed_count,
            message=message
        )
