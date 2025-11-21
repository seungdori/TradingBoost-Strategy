import datetime
import json
from dataclasses import dataclass
from token import OP
from typing import List, Optional

from pydantic import BaseModel


#TODO : BASEMODEL로 변경
@dataclass
class Position:

    symbol: str
    side: str  # "long" or "short"
    size: float #<-- 포지션크기. 이게 당연히, contracts_amount와 같은 값으로 만들어져야하는데, 어디에선가 가끔 잘못나올 떄가 있음.
    contracts_amount: float
    entry_price: float
    leverage: float
    position_qty: Optional[float] = None
    initial_size: Optional[float] = None
    contract_size: Optional[float] = None # 심볼 별로 contractSize로 나오는 것.
    mark_price: Optional[float] = None  # 현재 마크 가격
    tp_prices: Optional[List[float]] = None
    sl_price: Optional[float] = None
    order_id: Optional[str] = None  # 진입 주문 ID
    sl_order_id: Optional[str] = None  # SL 주문 ID
    tp_order_ids: Optional[List[str]] = None  # TP 주문 ID 리스트
    last_filled_price: Optional[float] = None  # 체결된 가격
    status: str = "open"  # 'open', 'closed', 'rejected' 등의 상태
    message: Optional[str] = None  # 오류 또는 상태 메시지

    def __post_init__(self):
        self.tp_prices = self.tp_prices or []
        self.tp_order_ids = self.tp_order_ids or []

@dataclass
class PositionState:
    symbol: str
    side: str
    tp_executed_count: int = 0  # 체결된 TP 주문 건수
    sl_filled: bool = False     # SL 주문 체결 여부

    def __str__(self):
        return json.dumps(self.__dict__)

@dataclass
class OrderStatus:
    order_id: str
    symbol: str
    side: str              # "buy"/"sell"
    size: float
    filled_size: float
    status: str            # "open"/"partially_filled"/"filled"/"canceled"/"error"
    avg_fill_price: float
    create_time: datetime.datetime
    update_time: datetime.datetime
    order_type: str
    posSide: str


class UpdateStopLossRequest(BaseModel):
    new_sl_price: float
    symbol: str
    side: str  # "long" or "short"
    size: float

    model_config = {
        "json_schema_extra": {
            "example": {
                "new_sl_price": 1.95,
                "symbol": "XRP-USDT-SWAP",
                "side": "long",
                "size": 100.0
            }
        }
    }

order_type_mapping = {
    'market': 'market',
    'limit': 'limit',
    'take_profit': 'limit',  # TP는 reduceOnly limit order로 처리
    'stop_loss': 'trigger'   # SL은 trigger order로 처리
}

def get_order_type(order_type):
    """
    주문 타입을 맵핑에 따라 변환합니다.
    맵핑에 없는 타입은 원래 값을 그대로 반환합니다.
    """
    return order_type_mapping.get(order_type, order_type)


tf_mapping = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1H": "1h",
    "4H": "4h",
    "1D": "1d",
    "1M": "1m",
    "15M": "15m",
    "30M": "30m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
    "30m": "30m"
}

def get_timeframe(timeframe):
    """
    시간 프레임을 맵핑에 따라 변환합니다.
    맵핑에 없는 시간 프레임은 원래 값을 그대로 반환합니다.
    """
    if timeframe is None:
        return "1m"
    # 입력값을 소문자로 변환하여 매핑
    return tf_mapping.get(timeframe.lower(), timeframe)