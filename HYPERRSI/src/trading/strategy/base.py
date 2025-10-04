from decimal import Decimal
from typing import Optional, Dict, Any
from enum import Enum
from HYPERRSI.src.api.exchange.models import OrderType, OrderSide, Position

class EntryType(str, Enum):
    LONG = "long"
    SHORT = "short"

class Strategy:
    def __init__(self, symbol: str, exchange_client):
        self.symbol = symbol
        self.exchange = exchange_client
        self.positions: Dict[str, Position] = {}
        self.state: Dict[str, Any] = {}  # 전략 상태 저장
        
    async def entry(self, 
                   id: str,
                   direction: EntryType,
                   amount: Decimal,
                   limit: Optional[Decimal] = None,
                   stop: Optional[Decimal] = None,
                   comment: Optional[str] = None) -> bool:
        """
        포지션 진입
        
        Args:
            id: 진입 식별자
            direction: 진입 방향 (LONG/SHORT)
            amount: 주문 수량
            limit: 지정가 주문 가격
            stop: 스탑 주문 가격
            comment: 주문 코멘트
        """
        order_type = OrderType.MARKET if limit is None else OrderType.LIMIT
        side = OrderSide.BUY if direction == EntryType.LONG else OrderSide.SELL
        
        try:
            order = await self.exchange.create_order(
                symbol=self.symbol,
                type=order_type,
                side=side,
                amount=amount,
                price=limit,
                stop_price=stop
            )
            
            if order.status == "filled":
                self.positions[id] = Position(
                    symbol=self.symbol,
                    side=direction,
                    size=amount,
                    entry_price=order.average_price or order.price
                )
                return True
                
            return False
            
        except Exception as e:
            # 로깅 및 에러 처리
            return False
            
    async def exit(self,
                  id: Optional[str] = None,
                  limit: Optional[Decimal] = None,
                  stop: Optional[Decimal] = None,
                  comment: Optional[str] = None) -> bool:
        """
        포지션 종료
        
        Args:
            id: 종료할 포지션 ID (None인 경우 모든 포지션)
            limit: 지정가 청산 가격
            stop: 스탑 청산 가격
            comment: 주문 코멘트
        """
        positions_to_close = [id] if id else list(self.positions.keys())
        
        success = True
        for pos_id in positions_to_close:
            if pos_id not in self.positions:
                continue
                
            position = self.positions[pos_id]
            side = OrderSide.SELL if position.side == EntryType.LONG else OrderSide.BUY
            
            try:
                order = await self.exchange.create_order(
                    symbol=self.symbol,
                    type=OrderType.MARKET if limit is None else OrderType.LIMIT,
                    side=side,
                    amount=position.size,
                    price=limit,
                    stop_price=stop,
                    reduce_only=True
                )
                
                if order.status == "filled":
                    del self.positions[pos_id]
                else:
                    success = False
                    
            except Exception as e:
                success = False
                # 로깅 및 에러 처리
                
        return success
    
    async def close(self,
                   id: Optional[str] = None,
                   comment: Optional[str] = None) -> bool:
        """
        시장가로 포지션 즉시 종료
        """
        return await self.exit(id=id, comment=comment)

    def calc_profit(self, id: str) -> Optional[Decimal]:
        """특정 포지션의 수익 계산"""
        if id not in self.positions:
            return None
            
        position = self.positions[id]
        # 수익 계산 로직
        return None  # 임시
        
    def get_position(self, id: str) -> Optional[Position]:
        """특정 포지션 정보 조회"""
        return self.positions.get(id) 