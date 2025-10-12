#src/trading/executor/order.py
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from HYPERRSI.src.api.exchange.models import (
    OrderRequest,
    OrderResponse,
    OrderSide,
    OrderType,
    TimeInForce,
)
from HYPERRSI.src.trading.executor.order_backend_wrapper import OrderBackendWrapper
from shared.logging import get_logger

logger = get_logger(__name__)

class OrderStatus(str, Enum):
    PENDING = "pending"       # 대기 중
    OPEN = "open"            # 활성화됨
    FILLED = "filled"        # 완전 체결
    PARTIALLY_FILLED = "partially_filled"  # 부분 체결
    CANCELED = "canceled"    # 취소됨
    REJECTED = "rejected"    # 거부됨
    EXPIRED = "expired"      # 만료됨

    def is_final(self) -> bool:
        """주문이 최종 상태인지 확인"""
        return self in [
            OrderStatus.FILLED, 
            OrderStatus.CANCELED, 
            OrderStatus.REJECTED, 
            OrderStatus.EXPIRED
        ]

    def is_active(self) -> bool:
        """주문이 활성 상태인지 확인"""
        return self in [
            OrderStatus.PENDING, 
            OrderStatus.OPEN, 
            OrderStatus.PARTIALLY_FILLED
        ]

@dataclass
class OrderFee:
    """주문 수수료 정보"""
    cost: Decimal
    currency: str
    rate: Decimal

class OrderError(Exception):
    """주문 관련 예외"""
    pass

class Order:
    def __init__(self,
                 order_id: str,
                 client_order_id: Optional[str],
                 symbol: str,
                 side: OrderSide,
                 order_type: OrderType,
                 amount: Decimal,
                 price: Optional[Decimal],
                 stop_price: Optional[Decimal],
                 status: Union[OrderStatus, str]):
        self.order_id = order_id
        self.client_order_id = client_order_id
        self.symbol = symbol
        self.side = side
        self.order_type = order_type
        self.amount = amount
        self.price = price
        self.stop_price = stop_price
        self.status = OrderStatus(status) if isinstance(status, str) else status
        self.created_at = datetime.utcnow()
        self.last_update_time = self.created_at
        self.filled_amount = Decimal('0')
        self.remaining_amount = amount
        self.average_price: Optional[Decimal] = None
        self.trades: List[Dict[str, Any]] = []
        self.fees: List[OrderFee] = []
        self.error: Optional[str] = None
        
    def update_from_exchange(self, exchange_order: OrderResponse) -> None:
        """거래소로부터 받은 주문 정보로 업데이트"""
        try:
            self.status = OrderStatus(exchange_order.status)
            self.filled_amount = exchange_order.filled_amount
            self.remaining_amount = self.amount - self.filled_amount
            self.average_price = exchange_order.average_price
            self.last_update_time = datetime.utcnow()
            
            if exchange_order.trades:
                self.trades.extend(exchange_order.trades)
                
            if exchange_order.fee:
                self.fees.append(OrderFee(
                    cost=Decimal(str(exchange_order.fee.cost)),
                    currency=exchange_order.fee.currency,
                    rate=Decimal(str(exchange_order.fee.rate))
                ))
                
        except Exception as e:
            self.error = str(e)
            logger.error(f"Order update failed: {e}")
        
    def is_active(self) -> bool:
        """주문이 활성 상태인지 확인"""
        return self.status.is_active()
        
    def is_filled(self) -> bool:
        """주문이 완전히 체결되었는지 확인"""
        return self.status == OrderStatus.FILLED
        
    def get_total_fee(self, currency: Optional[str] = None) -> Decimal:
        """총 수수료 계산"""
        if not currency:
            return sum(fee.cost for fee in self.fees)
        return sum(fee.cost for fee in self.fees if fee.currency == currency)

class OrderExecutor:
    def __init__(self, exchange_client):
        # OrderBackendWrapper를 사용하여 주문 처리
        self.order_wrapper = OrderBackendWrapper(exchange_client)
        self.exchange = exchange_client  # 다른 메서드를 위해 보존
        self.active_orders: Dict[str, Order] = {}
        self._order_updates: Dict[str, datetime] = {}
        
    async def create_order(self,
                          symbol: str,
                          side: OrderSide,
                          order_type: OrderType,
                          amount: Decimal,
                          price: Optional[Decimal] = None,
                          stop_price: Optional[Decimal] = None,
                          time_in_force: TimeInForce = TimeInForce.GTC,
                          reduce_only: bool = False,
                          post_only: bool = False,
                          client_order_id: Optional[str] = None,
                          **kwargs) -> OrderResponse:
        """주문 생성 및 실행"""
        try:
            order_request = OrderRequest(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=amount,
                price=price,
                time_in_force=time_in_force,
                reduce_only=reduce_only,
                post_only=post_only,
                client_order_id=client_order_id,
                **kwargs
            )
            
            # OrderBackendWrapper를 통해 주문 생성
            response = await self.order_wrapper.create_order(order_request)
            
            order = Order(
                order_id=response.order_id,
                client_order_id=response.client_order_id,
                symbol=symbol,
                side=side,
                order_type=order_type,
                amount=amount,
                price=price,
                stop_price=stop_price,
                status=response.status
            )
            
            if not OrderStatus(response.status).is_final():
                self.active_orders[response.order_id] = order
                self._order_updates[response.order_id] = datetime.utcnow()
                
            return response
            
        except Exception as e:
            logger.error(f"Order creation failed: {e}")
            raise OrderError(f"Failed to create order: {str(e)}")
        
    async def cancel_order(self, order_id: str) -> bool:
        """주문 취소"""
        try:
            # OrderBackendWrapper를 통해 주문 취소
            result = await self.order_wrapper.cancel_order(order_id)
            if result and order_id in self.active_orders:
                del self.active_orders[order_id]
                del self._order_updates[order_id]
            return bool(result)
        except Exception as e:
            logger.error(f"Order cancellation failed: {e}")
            return False
            
    async def cancel_all_orders(self, symbol: Optional[str] = None) -> bool:
        """모든 주문 취소"""
        # OrderBackendWrapper의 cancel_all_orders 시도
        wrapper_result = await self.order_wrapper.cancel_all_orders(symbol)
        if wrapper_result:
            # 성공하면 로컬 추적 정보 초기화
            if symbol:
                for order_id in list(self.active_orders.keys()):
                    if self.active_orders[order_id].symbol == symbol:
                        del self.active_orders[order_id]
                        del self._order_updates[order_id]
            else:
                self.active_orders.clear()
                self._order_updates.clear()
            return True
        
        # 실패하면 개별 취소로 폴백
        success = True
        for order_id in list(self.active_orders.keys()):
            order = self.active_orders[order_id]
            if symbol and order.symbol != symbol:
                continue
            if not await self.cancel_order(order_id):
                success = False
        return success

    async def get_order_status(self, order_id: str) -> Optional[Order]:
        """주문 상태 조회"""
        try:
            if order_id in self.active_orders:
                # OrderBackendWrapper를 통해 주문 정보 조회
                response = await self.order_wrapper.get_order(order_id)
                self.active_orders[order_id].update_from_exchange(response)
                self._order_updates[order_id] = datetime.utcnow()
                return self.active_orders[order_id]
            return None
        except Exception as e:
            logger.error(f"Failed to get order status: {e}")
            return None
            
    async def check_order(self, order_id: str) -> Dict[str, Any]:
        """주문 상세 정보 조회"""
        order = await self.get_order_status(order_id)
        if not order:
            return {
                "exists": False,
                "status": None,
                "filled_amount": Decimal('0'),
                "remaining_amount": Decimal('0')
            }
            
        return {
            "exists": True,
            "status": order.status,
            "filled_amount": order.filled_amount,
            "remaining_amount": order.remaining_amount,
            "average_price": order.average_price,
            "is_active": order.is_active(),
            "is_filled": order.is_filled(),
            "last_update": order.last_update_time,
            "trades": order.trades,
            "fees": [{"cost": fee.cost, "currency": fee.currency} for fee in order.fees],
            "error": order.error
        }

    def cleanup_inactive_orders(self, max_age_hours: int = 24) -> None:
        """오래된 비활성 주문 정리"""
        current_time = datetime.utcnow()
        for order_id in list(self.active_orders.keys()):
            last_update = self._order_updates.get(order_id)
            if last_update and (current_time - last_update).total_seconds() > max_age_hours * 3600:
                del self.active_orders[order_id]
                del self._order_updates[order_id]
