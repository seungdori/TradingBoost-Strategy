"""GRID 봇 상태 DTO

이 파일은 하위 호환성을 위해 유지되며, shared.dtos.bot_state를 재export합니다.
"""
# shared에서 공통 모델 import
from shared.dtos.bot_state import (
    BotStateError,
    BotStateDto,
    BotStateKeyDto,
    BotStatus,
    ErrorSeverity
)

# 하위 호환성을 위한 재export
__all__ = [
    'BotStateError',
    'BotStateDto',
    'BotStateKeyDto',
    'BotStatus',
    'ErrorSeverity'
]