"""거래소 공통 DTO

거래소 API 키, 지갑 정보 등 공통 데이터 모델
"""
from typing import Optional
from pydantic import BaseModel, Field
from enum import Enum


class ExchangeName(str, Enum):
    """지원 거래소 목록"""
    OKX = "okx"
    BINANCE = "binance"
    UPBIT = "upbit"
    BITGET = "bitget"
    OKX_SPOT = "okx_spot"
    BINANCE_SPOT = "binance_spot"
    BITGET_SPOT = "bitget_spot"


class ApiKeyDto(BaseModel):
    """API 키 정보"""
    api_key: str = Field(examples=["Exchange api key"])
    secret_key: str = Field(examples=["Exchange secret key"])
    password: Optional[str] = Field(None, examples=["Exchange password"])


class ApiKeys(BaseModel):
    """모든 거래소 API 키"""
    okx: ApiKeyDto
    binance: ApiKeyDto
    upbit: ApiKeyDto
    bitget: ApiKeyDto
    binance_spot: ApiKeyDto
    bitget_spot: ApiKeyDto
    okx_spot: ApiKeyDto


class ExchangeApiKeyDto(BaseModel):
    """거래소별 API 키"""
    exchange_name: str = Field(examples=["okx","binance", "upbit", "bitget", "binance_spot", "bitget_spot", "okx_spot"])
    api_key: str = Field(examples=["Exchange api key"])
    secret_key: str = Field(examples=["Exchange secret key"])
    password: Optional[str] = Field(None, examples=["Exchange password"])


class WalletDto(BaseModel):
    """지갑 정보"""
    exchange_name: str = Field(examples=["okx","binance", "upbit", "bitget", "binance_spot", "bitget_spot", "okx_spot"])
    total_balance: float = Field(example=[0])
    wallet_balance: Optional[float] = Field(None, examples=[0])
    total_unrealized_profit: Optional[float] = Field(None, examples=[0])
