from pydantic import BaseModel, Field


class TelegramTokenDto(BaseModel):
    exchange_name: str = Field(examples=["okx","binance", "upbit", "bitget", "binance_spot", "bitget_spot", "okx_spot"])
    token: str = Field(examples=["sample telegram token"])
