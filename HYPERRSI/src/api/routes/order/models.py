"""
Order API Pydantic Models

주문 관련 요청/응답 모델 정의
"""
from typing import Optional

from pydantic import BaseModel


class ClosePositionRequest(BaseModel):
    """포지션 종료 요청 모델"""
    close_type: str = "market"  # market 또는 limit
    price: Optional[float] = None  # limit 주문일 경우 가격
    close_percent: float = 100.0  # 종료할 포지션의 퍼센트 (1-100)

    model_config = {
        "json_schema_extra": {
            "example": {
                "close_type": "market",
                "price": None,
                "close_percent": 50.0  # 50% 종료 예시
            }
        }
    }


# 주문 상태 매핑
STATUS_MAPPING = {
    'closed': 'filled',
    'canceled': 'canceled',
    'rejected': 'rejected',
    'expired': 'expired',
    'open': 'open',
    'partial': 'partially_filled',
    'unknown': 'pending'
}

# API 응답 예시
EXAMPLE_RESPONSE = {
    "order_example": {
        "summary": "주문 조회 응답 예시",
        "value": {
            "order_id": "2205764866869846016",
            "client_order_id": "e847386590ce4dBCe66cc0a9f0cbbbd5",
            "symbol": "SOL-USDT-SWAP",
            "status": "filled",
            "side": "sell",
            "type": "market",
            "amount": "0.01",
            "filled_amount": "0.01",
            "remaining_amount": "0.0",
            "price": "240.7",
            "average_price": "240.7",
            "created_at": 1738239315673,
            "updated_at": 1738239315674,
            "pnl": "0.0343",
            "order_type": "market",
            "posSide": "net"
        }
    }
}
