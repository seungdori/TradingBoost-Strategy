from typing import Optional, List, Union
from pydantic import BaseModel, Field


class AiSearchStartFeatureDto(BaseModel):
    exchange_name: str = Field(examples=["binance","upbit", "bitget",  "okx", "binance_spot", "bitget_spot", "okx_spot"])
    enter_strategy: str = Field(examples=["long-short", "short", "long"])


class StartFeatureDto(BaseModel):
    exchange_name: str = Field(examples=["okx","upbit", "binance",  "bitget", "binance_spot", "bitget_spot", "okx_spot"])
    enter_strategy: str = Field(examples=["long-short", "short", "long"])
    enter_symbol_count: int = Field(examples=[8])
    enter_symbol_amount_list: Optional[List[float]] = Field(examples=[[5]])  # 각 그리드별 금액 리스트
    grid_num: int = Field(20, ge=1, le=40, examples=[20])
    leverage: Optional[int] = Field(None, examples=[20])
    stop_loss: Optional[float] = Field(None, examples=[5])
    custom_stop: Optional[int] = Field(None, examples=[2880])
    telegram_id : Optional[int] = Field(None, examples=[1709556958])
    user_id: Optional[Union[int, str]] = Field(None, examples=[1234])
    api_key: Optional[str] = Field(None, examples=["89d5cdd8-192b-4b7e-a4ce-d5666b7cdb42"])
    api_secret: Optional[str] = Field(None, examples=["135CF39F458BC20E0FA9FB3A9EA32B90"])
    password: Optional[str] = Field(None, examples=["Tmdehfl2014"])
    #api_key: str = Field(None, examples=["your_api_key"])
    #api_secret: str = Field(None, examples=["your_api_secret"])
    #password: Optional[str] = Field(None, examples=["your_password"])

class StopFeatureDto(BaseModel):
    exchange_name: str = Field(examples=["okx","bitget", "upbit", "binance", "binance_spot", "bitget_spot", "okx_spot"])
    enter_strategy: str = Field(examples=["long-short", "short", "long-short"])
    user_id: int = Field(examples=[1234])


class TestFeatureDto(BaseModel):
    exchange_name: str = Field(examples=["upbit","binance", "okx", "bitget", "binance_spot", "bitget_spot", "okx_spot"])
    leverage: Optional[int] = Field(None, examples=[1])


class CoinSellAllFeatureDto(BaseModel):
    exchange_name: str = Field(examples=["okx","binance", "upbit",  "bitget", "binance_spot", "bitget_spot", "okx_spot"])
    user_id:int = Field(examples=[1234])


class CoinDto(BaseModel):
    symbol: str = Field(examples=["BTCUSDT","ETC-USDT-SWAP","BTCUSDT", "BTC-KRW"])
    # amount: float = Field(examples=[0]) # Todo: 클라이언트에서 코인 갯수 필요한지 확인


class CoinSellFeatureDto(BaseModel):
    exchange_name: str = Field(examples=["okx","binance", "upbit", "bitget", "binance_spot", "bitget_spot", "okx_spot"])
    user_id: int = Field(examples=[1234])
    qty_percent: Optional[int] = Field(None, examples=[50])
    coins: List[CoinDto]
    # symbol: List[str] = Field(examples=["BTCUSDT", "BTC-KRW"])
    # coin amount? # Todo: 클라이언트에서 코인 갯수 필요한지 확인
