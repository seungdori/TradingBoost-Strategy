from typing import Optional, List
from pydantic import BaseModel

class OpenPositionRequest(BaseModel):
    """
    포지션 오픈 요청 값
    """
    user_id: str
    symbol: str
    direction: str   # "long" or "short"
    size: float
    leverage: float = 10.0
    stop_loss: Optional[float] = None
    take_profit: Optional[List[float]] = None
    is_DCA: bool = False

class ClosePositionRequest(BaseModel):
    """
    포지션 청산 요청 값
    """
    user_id: str
    symbol: str
    percent: Optional[float] = 100.0
    size: Optional[float] = 0.0
    comment: str = "포지션 청산"
    side: Optional[str] = None   # "long" or "short"

class PositionResponse(BaseModel):
    """
    포지션 열렸을 때 반환 정보
    """
    symbol: str
    side: str
    size: float
    entry_price: float
    leverage: float
    sl_price: Optional[float]
    tp_prices: Optional[List[float]] = None
    order_id: Optional[str] = None

    model_config = {
        
        "json_schema_extra": {
            "example": {
                "symbol": "BTC-USDT-SWAP",
                "side": "long",
                "size": 0.05,
                "entry_price": 18765.2,
                "leverage": 10.0,
                "sl_price": 18500.0,
                "tp_prices": [19000.0, 19200.0],
                "order_id": "1234567890"
            }
        }
    }