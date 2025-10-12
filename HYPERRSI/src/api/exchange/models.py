"""HYPERRSI 거래소 모델

이 파일은 하위 호환성을 위해 유지되며, shared.models.exchange를 재export합니다.
"""
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

# 공통 모델 import
from shared.models.exchange import (
    CancelOrdersResponse,
    OrderRequest,
    OrderResponse,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    TimeInForce,
)

# 하위 호환성을 위한 재export
__all__ = [
    'OrderType',
    'OrderSide',
    'PositionSide',
    'TimeInForce',
    'OrderStatus',
    'OrderRequest',
    'OrderResponse',
    'CancelOrdersResponse',
    # HYPERRSI 전용 모델들
    'Balance',
    'Position',
    'Trade',
    'Ticker',
    'OrderBook',
    'BalanceResponse',
    'PositionResponseModel',
    'BalanceResponseModel',
    'TickerResponseModel'
]

# ==================== HYPERRSI 전용 모델들 ====================

class Balance(BaseModel):
   currency: str
   total: Decimal = Field(..., description="전체 잔고")
   free: Decimal = Field(..., description="사용 가능한 잔고")
   used: Decimal = Field(..., description="사용중인 잔고")
   equity: Decimal = Field(default=Decimal("0"), description="순자산")
   floating_pnl: Decimal = Field(default=Decimal("0"), description="미실현 손익")

   class Config:
       arbitrary_types_allowed = True
class Position(BaseModel):
    symbol: str
    side: PositionSide
    size: Decimal = Field(..., description="포지션 크기")
    entry_price: Decimal = Field(..., description="진입 가격")
    mark_price: Decimal = Field(..., description="청산 기준 가격")
    liquidation_price: Optional[Decimal] = Field(None, description="청산 가격")
    unrealized_pnl: Decimal = Field(..., description="미실현 손익")
    realized_pnl: Decimal = Field(default=Decimal("0"), description="실현 손익")
    leverage: float = Field(..., description="레버리지")
    margin_type: str = Field("cross", description="마진 타입 (cross/isolated)")
    maintenance_margin: Optional[Decimal] = Field(None, description="유지 증거금")
    margin_ratio: Optional[Decimal] = Field(None, description="증거금 비율")
    sl_price: Optional[Decimal] = Field(None, description="손절 가격")
    sl_order_id: Optional[str] = Field(None, description="손절 주문 ID")
    sl_contracts_amount: Optional[Decimal] = Field(None, description="손절 주문 수량")
    tp_prices: List[Decimal] = Field([], description="익절 가격 리스트")
    tp_state: Optional[str] = Field(None, description="익절 상태")
    get_tp1: Optional[Decimal] = Field(None, description="TP1 익절 도달")
    get_tp2: Optional[Decimal] = Field(None, description="TP2 익절 도달")
    get_tp3: Optional[Decimal] = Field(None, description="TP3 익절 도달")
    sl_data: Optional[dict] = Field(None, description="손절 데이터")
    tp_data: Optional[dict] = Field(None, description="익절 데이터")
    tp_contracts_amounts: Optional[Decimal] = Field(None, description="TP 주문 수량")
    last_update_time: Optional[int] = Field(None, description="마지막 업데이트 시간 (timestamp)")
    
    class Config:
        arbitrary_types_allowed = True

class Trade(BaseModel):
    trade_id: str
    order_id: str
    symbol: str
    side: OrderSide
    amount: Decimal
    price: Decimal
    fee: Decimal
    fee_currency: str
    timestamp: int
    
    class Config:
        arbitrary_types_allowed = True

class Ticker(BaseModel):
    symbol: str
    last_price: Decimal
    bid: Optional[Decimal]
    ask: Optional[Decimal]
    high: Decimal
    low: Decimal
    volume: Decimal
    timestamp: int
    
    class Config:
        arbitrary_types_allowed = True

class OrderBook(BaseModel):
    symbol: str
    bids: List[Dict[str, Decimal]]  # [price, amount]
    asks: List[Dict[str, Decimal]]  # [price, amount]
    timestamp: int
    
    class Config:
        arbitrary_types_allowed = True 
        
class BalanceResponse(BaseModel):
    currency: str
    total: Decimal
    free: Decimal
    used: Decimal

# class OrderResponse(BaseModel):
#     order_id: str
#     symbol: str
#     side: str
#     order_type: str
#     amount: float
#     filled: float
#     price: Optional[float]
#     average_price: Optional[float]
#     status: str
#     timestamp: datetime

#     class Config:
#         arbitrary_types_allowed = True

class PositionResponseModel(BaseModel):
    symbol: str
    size: Decimal
    entry_price: Decimal
    leverage: Decimal
    unrealized_pnl: Optional[Decimal] = None
    margin: Optional[Decimal] = None
    
    class Config:
        arbitrary_types_allowed = True

class BalanceResponseModel(BaseModel):
    currency: str
    total: Decimal
    free: Decimal
    used: Decimal
    
    class Config:
        arbitrary_types_allowed = True

class TickerResponseModel(BaseModel):
    symbol: str
    last_price: Decimal
    bid: Decimal
    ask: Decimal
    volume_24h: Decimal
    
    class Config:
        arbitrary_types_allowed = True