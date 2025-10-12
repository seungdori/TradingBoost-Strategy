from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from HYPERRSI.src.api.exchange.models import OrderSide
from HYPERRSI.src.api.exchange.models import Position as ExchangePosition
from HYPERRSI.src.api.exchange.models import PositionSide


class PositionManager:
    def __init__(self):
        self.positions: Dict[str, 'Position'] = {}
        
    def add_position(self, position_id: str, position: 'Position') -> None:
        self.positions[position_id] = position
        
    def remove_position(self, position_id: str) -> None:
        if position_id in self.positions:
            del self.positions[position_id]
            
    def get_position(self, position_id: str) -> Optional['Position']:
        return self.positions.get(position_id)
        
    def get_all_positions(self) -> List['Position']:
        return list(self.positions.values())
        
    def update_position(self, position_id: str, 
                       exchange_position: ExchangePosition) -> None:
        if position_id in self.positions:
            self.positions[position_id].update_from_exchange(exchange_position)

class Position:
    def __init__(self,
                 symbol: str,
                 side: PositionSide,
                 size: Decimal,
                 entry_price: Decimal,
                 leverage: float = 1.0,
                 position_id: Optional[str] = None,
                 stop_loss: Optional[Decimal] = None,
                 take_profit: Optional[Decimal] = None):
        self.symbol = symbol
        self.side = side
        self.size = size
        self.entry_price = entry_price
        self.leverage = leverage
        self.position_id = position_id
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.entry_time = datetime.utcnow()
        self.last_update_time = self.entry_time
        self.realized_pnl = Decimal('0')
        self.unrealized_pnl = Decimal('0')
        
    def update_from_exchange(self, exchange_position: ExchangePosition) -> None:
        """거래소로부터 받은 포지션 정보로 업데이트"""
        self.size = exchange_position.size
        self.entry_price = exchange_position.entry_price
        self.unrealized_pnl = exchange_position.unrealized_pnl
        self.realized_pnl = exchange_position.realized_pnl
        self.last_update_time = datetime.utcnow()
        
    def calculate_pnl(self, current_price: Decimal) -> Decimal:
        """손익 계산"""
        if self.side == PositionSide.LONG:
            return (current_price - self.entry_price) * self.size
        else:
            return (self.entry_price - current_price) * self.size
            
    def should_close(self, current_price: Decimal) -> bool:
        """청산 조건 확인"""
        if self.stop_loss and self.side == PositionSide.LONG:
            if current_price <= self.stop_loss:
                return True
        elif self.stop_loss and self.side == PositionSide.SHORT:
            if current_price >= self.stop_loss:
                return True
                
        if self.take_profit and self.side == PositionSide.LONG:
            if current_price >= self.take_profit:
                return True
        elif self.take_profit and self.side == PositionSide.SHORT:
            if current_price <= self.take_profit:
                return True
                
        return False 