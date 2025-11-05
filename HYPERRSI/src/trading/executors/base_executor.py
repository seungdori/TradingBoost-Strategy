"""
Base Executor - Abstract Base Class for Order Execution

Strategy Pattern 기반 주문 실행 추상화

Signal Bot 모드에서는:
- 주문 취소 불필요 (Market order만 사용)
- TP/SL은 Python에서 모니터링
- 조건 충족 시 EXIT 시그널 전송
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional, TypedDict


class OrderResult(TypedDict):
    """주문 실행 결과"""
    order_id: str
    symbol: str
    side: str
    size: float
    price: Optional[float]
    status: str
    timestamp: str


class PositionResult(TypedDict):
    """포지션 청산 결과"""
    symbol: str
    side: str
    size: float
    close_price: float
    realized_pnl: Optional[float]
    status: str
    timestamp: str


class BaseExecutor(ABC):
    """
    주문 실행 전략 기본 클래스

    Signal Bot 철학:
    - 진입: ENTER_LONG/SHORT (Market)
    - 청산: EXIT_LONG/SHORT (Market)
    - TP/SL: Python 모니터링 → 조건 시 EXIT
    - 주문 취소: 불필요
    """

    def __init__(self, user_id: str):
        self.user_id = user_id

    @abstractmethod
    async def create_order(
        self,
        symbol: str,
        side: str,  # 'buy' | 'sell'
        size: float,
        leverage: Optional[float] = None,
        order_type: str = "market",
        price: Optional[float] = None,
        trigger_price: Optional[float] = None,
        **kwargs
    ) -> OrderResult:
        """
        진입 주문 생성

        Args:
            symbol: 거래 심볼 (예: 'BTC/USDT:USDT')
            side: 주문 방향 ('buy' for long, 'sell' for short)
            size: 주문 수량
            leverage: 레버리지 (Signal Bot에서는 사전 설정)
            order_type: 주문 타입 ('market' only for Signal Bot)
            price: Limit 주문 가격 (Signal Bot에서는 사용 안 함)
            trigger_price: Trigger 가격 (Signal Bot에서는 사용 안 함)
            **kwargs: 추가 파라미터

        Returns:
            OrderResult: 주문 실행 결과

        Raises:
            Exception: 주문 실패 시
        """
        pass

    @abstractmethod
    async def close_position(
        self,
        symbol: str,
        side: str,  # 'long' | 'short'
        size: Optional[float] = None,
        **kwargs
    ) -> PositionResult:
        """
        포지션 청산

        Args:
            symbol: 거래 심볼
            side: 포지션 방향 ('long' | 'short')
            size: 청산 수량 (None이면 전체 청산)
            **kwargs: 추가 파라미터

        Returns:
            PositionResult: 청산 결과

        Raises:
            Exception: 청산 실패 시
        """
        pass

    async def close(self) -> None:
        """
        리소스 정리 (선택적 구현)

        API Direct: CCXT exchange 연결 종료
        Signal Bot: HTTP client 종료
        """
        pass
