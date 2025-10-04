"""봇 상태 관리 DTO

트레이딩 봇의 실행 상태, 에러 정보 등을 관리
"""
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
from datetime import datetime

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
    """봇 상태 정보"""
    # {exchange_name}_{enter_strategy}}
    # e.g. 'binance_short_전략1', 'upbit_long-short_전략1', 'okx_long_전략3'
    key: str
    exchange_name: str  # 'binance', 'upbit',  'bitget', 'okx', 'binance_spot', 'bitget_spot', 'okx_spot'
    user_id: str
    enter_strategy: Optional[str] = 'long'  # 선택적으로 만듦  # 'long', 'short', 'long-short'
    is_running: bool
    error: Optional[BotStateError] = Field(None, examples=[
        {'name': 'error', 'message': 'trading error.', 'meta': { 'error_detail': 'raw logs'}}
    ])


class BotStateKeyDto(BaseModel):
    """봇 상태 키"""
    exchange_name: str  # 'binance', 'upbit', 'bitget', 'okx', 'binance_spot', 'bitget_spot', 'okx_spot'
    enter_strategy: Optional[str] = 'long'  # 'long', 'short', 'long-short'
    user_id: str  # 1234
