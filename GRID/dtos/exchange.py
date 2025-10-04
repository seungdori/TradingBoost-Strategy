from typing import Optional

from pydantic import BaseModel, Field


class ApiKeyDto(BaseModel):
    api_key: str = Field(examples=["Exchange api key"])
    secret_key: str = Field(examples=["Exchange secret key"])
    password: Optional[str] = Field(None, examples=["Exchange password"])


class ApiKeys(BaseModel):
    okx: ApiKeyDto
    binance: ApiKeyDto
    upbit: ApiKeyDto
    bitget: ApiKeyDto
    binance_spot: ApiKeyDto
    bitget_spot: ApiKeyDto
    okx_spot: ApiKeyDto
class ExchangeApiKeyDto(BaseModel):
    exchange_name: str = Field(examples=["okx","binance", "upbit", "bitget", "binance_spot", "bitget_spot", "okx_spot"])
    api_key: str = Field(examples=["Exchange api key"])
    secret_key: str = Field(examples=["Exchange secret key"])
    password: Optional[str] = Field(None, examples=["Exchange password"])


class WalletDto(BaseModel):
    exchange_name: str = Field(examples=["okx","binance", "upbit", "bitget", "binance_spot", "bitget_spot", "okx_spot"])
    total_balance: float = Field(example=[0])
    wallet_balance: Optional[float] = Field(None, examples=[0])
    total_unrealized_profit: Optional[float] = Field(None, examples=[0])
