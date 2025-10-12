"""거래소 공통 DTO

거래소 API 키, 지갑 정보 등 공통 데이터 모델
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


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
    """
    거래소 API 키 정보

    거래소에 접근하기 위한 인증 정보입니다.
    조회 시 보안을 위해 마스킹되어 반환됩니다.
    """

    api_key: str = Field(
        ...,
        description="거래소 API 키. 조회 시 일부 마스킹됨 (예: xxxxx***xxxxx)",
        examples=["89d5cdd8-192b-4b7e-a4ce-d5666b7cdb42", "xxxxx***xxxxx"],
        min_length=8
    )

    secret_key: str = Field(
        ...,
        description="거래소 Secret 키. 조회 시 일부 마스킹됨 (예: xxxxx***xxxxx)",
        examples=["135CF39F458BC20E0FA9FB3A9EA32B90", "xxxxx***xxxxx"],
        min_length=8
    )

    password: Optional[str] = Field(
        None,
        description="거래소 API Passphrase (OKX 등에서 필요). 조회 시 마스킹됨",
        examples=["MyPassphrase123", "xxxxx***xxxxx", None]
    )


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
    """
    거래소별 API 키 (업데이트용)

    특정 거래소의 API 키를 업데이트할 때 사용하는 DTO입니다.
    """

    exchange_name: str = Field(
        ...,
        description="거래소 이름",
        examples=["okx", "binance", "upbit", "bitget", "binance_spot", "bitget_spot", "okx_spot"]
    )

    api_key: str = Field(
        ...,
        description="새로운 API 키 (평문)",
        examples=["89d5cdd8-192b-4b7e-a4ce-d5666b7cdb42"],
        min_length=8
    )

    secret_key: str = Field(
        ...,
        description="새로운 Secret 키 (평문)",
        examples=["135CF39F458BC20E0FA9FB3A9EA32B90"],
        min_length=8
    )

    password: Optional[str] = Field(
        None,
        description="API Passphrase (OKX 등에서 필요)",
        examples=["MyPassphrase123", None]
    )


class WalletDto(BaseModel):
    """
    거래소 지갑 정보

    거래소 계정의 잔고, 증거금, 미실현 손익 등을 포함하는 지갑 정보입니다.
    """

    exchange_name: str = Field(
        ...,
        description="거래소 이름 (okx, binance, upbit, bitget, bybit 등)",
        examples=["okx", "binance", "upbit", "bitget", "binance_spot", "bitget_spot", "okx_spot"]
    )

    total_balance: float = Field(
        ...,
        description="총 잔고 (USDT 기준). 가용 잔고 + 사용 중인 증거금 + 미실현 손익",
        examples=[10000.50, 5432.10],
        ge=0.0
    )

    wallet_balance: Optional[float] = Field(
        None,
        description="지갑 잔고 (USDT). 거래소에 실제로 있는 금액",
        examples=[8500.25, 4000.00],
        ge=0.0
    )

    total_unrealized_profit: Optional[float] = Field(
        None,
        description="총 미실현 손익 (USDT). 현재 오픈 포지션의 평가 손익",
        examples=[50.75, -120.50, 0.0]
    )
