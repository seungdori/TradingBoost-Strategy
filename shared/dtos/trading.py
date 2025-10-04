"""트레이딩 공통 DTO/Schema

GRID와 HYPERRSI 프로젝트에서 공통으로 사용하는 트레이딩 관련 데이터 모델
"""
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator
from enum import Enum


class PositionSide(str, Enum):
    """포지션 방향"""
    LONG = "long"
    SHORT = "short"
    BOTH = "both"


class OrderType(str, Enum):
    """주문 타입"""
    MARKET = "market"
    LIMIT = "limit"
    STOP_MARKET = "stop_market"
    STOP_LIMIT = "stop_limit"


# ==================== HYPERRSI용 DTOs ====================

class OpenPositionRequest(BaseModel):
    """포지션 오픈 요청 (HYPERRSI)"""
    user_id: str = Field(1709556958, description="사용자 ID (텔레그램 ID 또는 OKX UID)")
    symbol: str = Field("BTC-USDT-SWAP", description="심볼")
    direction: str = Field("long", description="포지션 방향")
    size: float = Field(0.1, description="포지션 크기")
    leverage: float = Field(10.0, description="레버리지")
    stop_loss: Optional[float] = Field(None, description="손절가")
    take_profit: Optional[List[float]] = Field(None, description="이익실현가")
    is_DCA: bool = Field(False, description="DCA 모드 활성화 여부")
    order_concept: str = Field('', description="주문 개념")
    is_hedge: bool = Field(False, description="헤지 모드 활성화 여부")
    hedge_tp_price: Optional[float] = Field(None, description="헤지 이익실현가")
    hedge_sl_price: Optional[float] = Field(None, description="헤지 손절가")

    @field_validator('direction')
    @classmethod
    def validate_direction(cls, v: str) -> str:
        """방향 검증"""
        if v.lower() not in ['long', 'short']:
            raise ValueError('direction must be "long" or "short"')
        return v.lower()

    @field_validator('take_profit')
    @classmethod
    def validate_take_profit(cls, v: Optional[List[float]]) -> Optional[List[float]]:
        """익절가 검증"""
        if v is not None and len(v) > 0:
            if len(v) > 5:
                raise ValueError('Maximum 5 take profit levels allowed')
            if any(tp <= 0 for tp in v):
                raise ValueError('Take profit prices must be positive')
        return v


class ClosePositionRequest(BaseModel):
    """포지션 청산 요청 (HYPERRSI)"""
    user_id: int = Field(default=1709556958, description="사용자 ID (텔레그램 ID 또는 OKX UID)")
    symbol: str = Field(default="BTC-USDT-SWAP", description="심볼")
    percent: float = Field(default=100.0, description="청산 비율")
    size: Optional[float] = Field(default=None, description="청산 크기")
    comment: str = Field(default="포지션 청산", description="주문 코멘트")
    side: Optional[str] = Field(default=None, description="청산 방향")

    @field_validator('side')
    @classmethod
    def validate_side(cls, v: Optional[str]) -> Optional[str]:
        """포지션 방향 검증"""
        if v is not None and v.lower() not in ['long', 'short']:
            raise ValueError('side must be "long" or "short"')
        return v.lower() if v else None


class PositionResponse(BaseModel):
    """포지션 응답 (HYPERRSI)"""
    symbol: str
    side: str
    size: float
    entry_price: float
    leverage: float
    sl_price: Optional[float] = None
    tp_prices: Optional[List[float]] = None
    order_id: Optional[str] = None
    last_filled_price: Optional[float] = None

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "symbol": "BTC-USDT-SWAP",
                "side": "long",
                "size": 0.01,
                "entry_price": 18765.2,
                "leverage": 10.0,
                "sl_price": 18500.0,
                "tp_prices": [19000.0, 19200.0],
                "order_id": "1234567890"
            }]
        }
    }


# ==================== GRID용 DTOs ====================

class TradingDataDto(BaseModel):
    """그리드 트레이딩 데이터 (GRID)"""
    symbol: str = Field(..., examples=['BTC', 'ETH', 'LTC'], description="심볼")
    long_tp1_price: float = Field(..., examples=[100], description="롱 익절가 1")
    long_tp2_price: float = Field(..., examples=[100], description="롱 익절가 2")
    long_tp3_price: float = Field(..., examples=[100], description="롱 익절가 3")
    long_sl_price: float = Field(..., examples=[500], description="롱 손절가")
    short_tp1_price: Optional[float] = Field(None, description="숏 익절가 1")
    short_tp2_price: Optional[float] = Field(None, description="숏 익절가 2")
    short_tp3_price: Optional[float] = Field(None, description="숏 익절가 3")
    short_sl_price: Optional[float] = Field(None, description="숏 손절가")

    @field_validator('long_tp1_price', 'long_tp2_price', 'long_tp3_price', 'long_sl_price')
    @classmethod
    def validate_positive_prices(cls, v: float) -> float:
        """가격 양수 검증"""
        if v <= 0:
            raise ValueError('Price must be positive')
        return v

    @field_validator('long_tp2_price')
    @classmethod
    def validate_tp2_greater_than_tp1(cls, v: float, info) -> float:
        """TP2가 TP1보다 큰지 검증"""
        if 'long_tp1_price' in info.data and v <= info.data['long_tp1_price']:
            raise ValueError('long_tp2_price must be greater than long_tp1_price')
        return v

    @field_validator('long_tp3_price')
    @classmethod
    def validate_tp3_greater_than_tp2(cls, v: float, info) -> float:
        """TP3가 TP2보다 큰지 검증"""
        if 'long_tp2_price' in info.data and v <= info.data['long_tp2_price']:
            raise ValueError('long_tp3_price must be greater than long_tp2_price')
        return v


class WinrateDto(BaseModel):
    """승률 통계 (GRID)"""
    name: str = Field(..., description="전략 이름")
    long_win_rate: Optional[float] = Field(None, examples=[1], ge=0, le=100, description="롱 승률 (%)")
    short_win_rate: Optional[float] = Field(None, examples=[1], ge=0, le=100, description="숏 승률 (%)")
    total_win_rate: Optional[float] = Field(None, examples=[1], ge=0, le=100, description="전체 승률 (%)")

    @field_validator('long_win_rate', 'short_win_rate', 'total_win_rate')
    @classmethod
    def validate_win_rate_range(cls, v: Optional[float]) -> Optional[float]:
        """승률 범위 검증 (0-100)"""
        if v is not None and (v < 0 or v > 100):
            raise ValueError('Win rate must be between 0 and 100')
        return v


# ==================== 공통 유틸리티 ====================

class GridTradingData(BaseModel):
    """그리드 트레이딩 설정"""
    symbol: str
    long_tp1_price: float
    long_tp2_price: float
    long_tp3_price: float
    long_sl_price: float
    short_tp1_price: Optional[float] = None
    short_tp2_price: Optional[float] = None
    short_tp3_price: Optional[float] = None
    short_sl_price: Optional[float] = None


class TradingSignal(BaseModel):
    """트레이딩 시그널"""
    symbol: str
    side: PositionSide
    signal_type: str  # "entry", "exit", "tp", "sl"
    price: float
    confidence: Optional[float] = Field(None, ge=0, le=1, description="신호 신뢰도 (0-1)")
    timestamp: Optional[str] = None
