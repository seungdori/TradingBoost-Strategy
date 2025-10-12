"""거래소 공통 모델

거래소 API에서 공통으로 사용되는 주문, 포지션 관련 모델들
"""
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class OrderType(str, Enum):
    """주문 타입"""
    MARKET = "market"         # 시장가 주문
    LIMIT = "limit"          # 지정가 주문
    POST_ONLY = "post_only"  # 메이커 주문
    FOK = "fok"             # Fill or Kill
    IOC = "ioc"             # Immediate or Cancel


class OrderSide(str, Enum):
    """주문 방향"""
    BUY = "buy"
    SELL = "sell"


class PositionSide(str, Enum):
    """포지션 방향"""
    LONG = "long"
    SHORT = "short"
    BOTH = "both"  # 양방향


class TimeInForce(str, Enum):
    """주문 유효 기간"""
    GTC = "gtc"  # Good Till Cancel
    IOC = "ioc"  # Immediate or Cancel
    FOK = "fok"  # Fill or Kill


class OrderStatus(str, Enum):
    """주문 상태"""
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"


class OrderRequest(BaseModel):
    """주문 요청 모델"""
    symbol: str = Field(..., description="거래 심볼")
    type: OrderType = Field(..., description="주문 타입")
    side: OrderSide = Field(..., description="주문 방향")
    amount: Decimal = Field(..., description="주문 수량")
    price: Optional[Decimal] = Field(None, description="주문 가격 (지정가 주문의 경우)")
    leverage: Optional[float] = Field(None, description="레버리지")
    time_in_force: TimeInForce = Field(TimeInForce.GTC, description="주문 유효 기간")
    reduce_only: bool = Field(False, description="포지션 축소 전용 여부")
    post_only: bool = Field(False, description="메이커 전용 여부")
    client_order_id: Optional[str] = Field(None, description="클라이언트 주문 ID")
    
    model_config = {
        "arbitrary_types_allowed": True,
        "json_schema_extra": {
            "example": {
                "symbol": "BTC-USDT-SWAP",
                "type": "market",
                "side": "buy",
                "amount": "0.01",
                "leverage": 10
            }
        }
    }


class OrderResponse(BaseModel):
    """주문 응답 모델"""
    order_id: str = Field(..., description="주문 ID")
    client_order_id: Optional[str] = Field(None, description="클라이언트 주문 ID")
    symbol: str = Field(..., description="거래 심볼")
    status: OrderStatus = Field(..., description="주문 상태")
    side: OrderSide = Field(..., description="주문 방향")
    type: OrderType = Field(..., description="주문 타입")
    amount: float = Field(..., description="주문 수량")
    filled_amount: Optional[float] = Field(None, description="체결된 수량")
    remaining_amount: float = Field(0, description="남은 주문량")
    price: Optional[Decimal] = Field(None, description="주문 가격")
    average_price: Optional[Decimal] = Field(None, description="평균 체결 가격")
    created_at: Optional[int] = Field(None, description="주문 생성 시간 (timestamp)")
    updated_at: Optional[int] = Field(None, description="마지막 업데이트 시간 (timestamp)")
    pnl: Optional[float] = Field(None, description="손익")
    order_type: Optional[str] = Field(None, description="주문 타입 (거래소 고유)")
    posSide: Optional[str] = Field(None, description="포지션 방향 (거래소 고유)")
    
    model_config = {
        "arbitrary_types_allowed": True,
        "json_schema_extra": {
            "example": {
                "order_id": "123456789",
                "symbol": "BTC-USDT-SWAP",
                "status": "filled",
                "side": "buy",
                "type": "market",
                "amount": 0.01,
                "filled_amount": 0.01,
                "average_price": "50000.0"
            }
        }
    }


class CancelOrdersResponse(BaseModel):
    """주문 취소 응답 모델"""
    success: bool = Field(..., description="취소 작업의 성공 여부")
    message: str = Field(..., description="작업 결과에 대한 상세 메시지")
    canceled_orders: Optional[List[str]] = Field(None, description="취소된 주문 ID 목록")
    failed_orders: Optional[List[Dict]] = Field(None, description="취소 실패한 주문 정보")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "message": "Successfully cancelled 2 orders",
                "canceled_orders": ["123456", "123457"]
            }
        }
    }
