"""
Trading Executors Package

Strategy Pattern 구현으로 API Direct와 Signal Bot 방식을 추상화

Exports:
    - BaseExecutor: 추상 기본 클래스
    - APIDirectExecutor: CCXT 기반 직접 API 호출
    - SignalBotExecutor: OKX Signal Bot Webhook
    - ExecutorFactory: 유저별 적절한 Executor 선택
"""

from HYPERRSI.src.trading.executors.base_executor import BaseExecutor
from HYPERRSI.src.trading.executors.api_direct_executor import APIDirectExecutor
from HYPERRSI.src.trading.executors.signal_bot_executor import SignalBotExecutor
from HYPERRSI.src.trading.executors.factory import ExecutorFactory

__all__ = [
    "BaseExecutor",
    "APIDirectExecutor",
    "SignalBotExecutor",
    "ExecutorFactory",
]
