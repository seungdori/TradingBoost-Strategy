from pydantic import BaseModel, Field


class TradingDataModel(BaseModel):
    symbol: str = Field(examples=['BTC', 'ETH', 'LTC'])
    long_tp1_price: int = Field(examples=[100])
    long_tp2_price: int = Field(examples=[100])
    long_tp3_price: int = Field(examples=[100])
    long_sl_price: int = Field(examples=[500])  # Todo: select int or float
