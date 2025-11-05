"""
Signal Bot Executor - OKX Signal Bot Webhook 방식

OKX 공식 문서: https://www.okx.com/help/signal-bot-alert-message-specifications

핵심 특징:
- Market order만 사용 (항상 즉시 체결)
- 주문 취소 불필요 (미체결 주문 없음)
- TP/SL은 Python 모니터링으로 처리
"""

import httpx
from datetime import datetime
from typing import Dict, Optional

from HYPERRSI.src.trading.executors.base_executor import (
    BaseExecutor,
    OrderResult,
    PositionResult,
)
from shared.logging import get_logger

logger = get_logger(__name__)


class SignalBotExecutor(BaseExecutor):
    """
    OKX Signal Bot Webhook 방식 주문 실행

    Webhook Payload Format (OKX 공식):
    {
        "action": "ENTER_LONG" | "ENTER_SHORT" | "EXIT_LONG" | "EXIT_SHORT",
        "instrument": "BTCUSDT.P",  # Perpetual은 .P suffix 필수
        "signalToken": "your_token",
        "timestamp": "2025-01-15T12:00:00.000Z",
        "maxLag": "60",  # 60초 이내만 유효
        "orderType": "market",
        "investmentType": "base",
        "amount": "0.1"
    }
    """

    def __init__(
        self,
        user_id: str,
        signal_token: str,
        webhook_url: str,
        max_lag: int = 60,
    ):
        """
        Args:
            user_id: 사용자 ID
            signal_token: OKX Signal Bot Token
            webhook_url: OKX 제공 Webhook URL
            max_lag: 시그널 유효 시간 (초, 기본 60초)
        """
        super().__init__(user_id)
        self.signal_token = signal_token
        self.webhook_url = webhook_url
        self.max_lag = max_lag
        self.client = httpx.AsyncClient(timeout=30.0)

    async def create_order(
        self,
        symbol: str,
        side: str,
        size: float,
        leverage: Optional[float] = None,
        order_type: str = "market",
        price: Optional[float] = None,
        trigger_price: Optional[float] = None,
        **kwargs
    ) -> OrderResult:
        """
        진입 주문 생성 (ENTER_LONG/SHORT)

        Args:
            symbol: 거래 심볼 (예: 'BTC/USDT:USDT')
            side: 주문 방향 ('buy' for long, 'sell' for short)
            size: 주문 수량
            leverage: 무시됨 (Signal Bot에서 사전 설정)
            order_type: 항상 'market'
            price: 무시됨 (Market order만 지원)
            trigger_price: 무시됨

        Returns:
            OrderResult: 주문 실행 결과
        """
        # 1. Symbol 변환
        instrument = self._convert_to_okx_format(symbol)

        # 2. Action 결정
        action = "ENTER_LONG" if side == "buy" else "ENTER_SHORT"

        # 3. Payload 구성
        payload = {
            "action": action,
            "instrument": instrument,
            "signalToken": self.signal_token,
            "timestamp": datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')[:-3] + 'Z',
            "maxLag": str(self.max_lag),
            "orderType": "market",
            "investmentType": "base",  # 수량 직접 지정
            "amount": str(size),
        }

        # 4. Webhook 전송
        try:
            logger.info(
                f"[SignalBot][{self.user_id}] Sending {action}: "
                f"{size} {instrument}"
            )

            response = await self.client.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()

            # 5. 응답 파싱 (OKX 응답 형식에 따라 조정 필요)
            result = response.json()

            logger.info(
                f"[SignalBot][{self.user_id}] Order success: {action} {size} {symbol}"
            )

            return OrderResult(
                order_id=result.get("data", {}).get("ordId", "signal_bot_order"),
                symbol=symbol,
                side=side,
                size=size,
                price=None,  # Market order
                status="filled",
                timestamp=datetime.utcnow().isoformat()
            )

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
            logger.error(
                f"[SignalBot][{self.user_id}] Order failed: {error_msg}"
            )
            raise Exception(f"Signal Bot order failed: {error_msg}")

        except Exception as e:
            logger.error(
                f"[SignalBot][{self.user_id}] Unexpected error: {str(e)}"
            )
            raise

    async def close_position(
        self,
        symbol: str,
        side: str,
        size: Optional[float] = None,
        **kwargs
    ) -> PositionResult:
        """
        포지션 청산 (EXIT_LONG/SHORT)

        Args:
            symbol: 거래 심볼
            side: 포지션 방향 ('long' | 'short')
            size: 무시됨 (Signal Bot은 전체 청산)

        Returns:
            PositionResult: 청산 결과
        """
        # 1. Symbol 변환
        instrument = self._convert_to_okx_format(symbol)

        # 2. Action 결정
        action = "EXIT_LONG" if side == "long" else "EXIT_SHORT"

        # 3. Payload 구성 (EXIT는 수량 지정 안 함)
        payload = {
            "action": action,
            "instrument": instrument,
            "signalToken": self.signal_token,
            "timestamp": datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')[:-3] + 'Z',
            "maxLag": str(self.max_lag),
        }

        # 4. Webhook 전송
        try:
            logger.info(
                f"[SignalBot][{self.user_id}] Sending {action}: {instrument}"
            )

            response = await self.client.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()

            result = response.json()

            logger.info(
                f"[SignalBot][{self.user_id}] Position closed: {action} {symbol}"
            )

            return PositionResult(
                symbol=symbol,
                side=side,
                size=size or 0.0,
                close_price=0.0,  # Signal Bot은 가격 정보 없음
                realized_pnl=None,
                status="closed",
                timestamp=datetime.utcnow().isoformat()
            )

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
            logger.error(
                f"[SignalBot][{self.user_id}] Close failed: {error_msg}"
            )
            raise Exception(f"Signal Bot close failed: {error_msg}")

        except Exception as e:
            logger.error(
                f"[SignalBot][{self.user_id}] Unexpected error: {str(e)}"
            )
            raise

    async def close(self) -> None:
        """HTTP client 종료"""
        await self.client.aclose()
        logger.debug(f"[SignalBot][{self.user_id}] Client closed")

    def _convert_to_okx_format(self, symbol: str) -> str:
        """
        심볼 변환: BTC/USDT:USDT -> BTCUSDT.P

        ⚠️ 중요: Perpetual contract는 반드시 .P suffix 필요

        Examples:
            'BTC/USDT:USDT' -> 'BTCUSDT.P'
            'ETH/USDT:USDT' -> 'ETHUSDT.P'
        """
        # BTC/USDT:USDT -> BTCUSDT
        base = symbol.replace("/", "").replace(":USDT", "")

        # Perpetual suffix 추가
        return f"{base}.P"
