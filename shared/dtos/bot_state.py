"""봇 상태 관리 DTO

트레이딩 봇의 실행 상태, 에러 정보 등을 관리
"""
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

# 공통 에러 모듈에서 ErrorSeverity, ErrorInfo import
from shared.errors import ErrorSeverity
from shared.errors.models import ErrorInfo


class BotStatus(str, Enum):
    """봇 상태"""
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    STARTING = "starting"
    STOPPING = "stopping"


# BotStateError는 ErrorInfo와 동일하므로 alias 생성
BotStateError = ErrorInfo


class BotStateDto(BaseModel):
    """
    트레이딩 봇 상태 정보

    봇의 실행 상태, 에러 정보 등을 포함합니다.
    Redis에 저장되며 실시간으로 업데이트됩니다.
    """

    key: str = Field(
        ...,
        description="봇 고유 식별자. 형식: {exchange_name}_{enter_strategy}_{user_id}",
        examples=["okx_momentum_12345", "binance_reversal_67890", "upbit_long_11111"]
    )

    exchange_name: str = Field(
        ...,
        description="거래소 이름",
        examples=["okx", "binance", "upbit", "bitget", "binance_spot", "bitget_spot", "okx_spot", "bybit", "bybit_spot"]
    )

    user_id: str = Field(
        ...,
        description="사용자 ID",
        examples=["12345", "67890"]
    )

    enter_strategy: Optional[str] = Field(
        default='long',
        description="진입 전략. momentum(모멘텀), reversal(반전), breakout(돌파) 등",
        examples=["momentum", "reversal", "breakout", "long", "short", "long-short"]
    )

    is_running: bool = Field(
        ...,
        description="봇 실행 상태. True: 실행 중, False: 중지됨",
        examples=[True, False]
    )

    error: Optional[BotStateError] = Field(
        None,
        description="에러 정보. 에러 발생 시 에러 이름, 메시지, 상세 정보를 포함. 정상 시 None",
        examples=[
            None,
            {
                'code': 'EXCHANGE_API_ERROR',
                'message': 'Failed to place order: Insufficient balance',
                'severity': 'ERROR',
                'timestamp': '2025-01-12T10:30:00Z',
                'details': {'order_id': '123456', 'symbol': 'BTC/USDT'}
            },
            {
                'code': 'CONNECTION_ERROR',
                'message': 'WebSocket connection lost',
                'severity': 'WARNING',
                'timestamp': '2025-01-12T10:35:00Z',
                'details': {'retry_count': 3}
            }
        ]
    )


class BotStateKeyDto(BaseModel):
    """
    봇 상태 조회 키

    특정 봇의 상태를 조회하기 위한 키 정보입니다.
    """

    exchange_name: str = Field(
        ...,
        description="거래소 이름",
        examples=["okx", "binance", "upbit", "bitget"]
    )

    enter_strategy: Optional[str] = Field(
        default='long',
        description="진입 전략",
        examples=["momentum", "reversal", "long", "short"]
    )

    user_id: str = Field(
        ...,
        description="사용자 ID",
        examples=["12345", "67890"]
    )
