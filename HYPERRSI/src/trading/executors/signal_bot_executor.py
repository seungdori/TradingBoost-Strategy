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

    OKX Signal Bot 공식 규격:
    https://www.okx.com/help/signal-bot-alert-message-specifications

    Webhook Payload Format (Universally Compatible Format):
    {
        "action": "ENTER_LONG" | "ENTER_SHORT" | "EXIT_LONG" | "EXIT_SHORT",
        "instrument": "BTC-USDT-SWAP",  # OKX instId 형식
        "signalToken": "your_token",
        "timestamp": "2025-01-15T12:00:00.000Z",  # ISO 8601 형식
        "maxLag": "60",  # 1-3600초, 기본 60초
        "orderType": "market",  # "market" 또는 "limit"
        "investmentType": "base" | "margin" | "contract" | "percentage_balance",
        "amount": "0.1"  # investmentType에 맞는 수량
    }

    Exit 시 추가 옵션:
    - investmentType: "percentage_position" + amount: "100" → 전체 청산
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
        close_percentage: Optional[float] = None,
        **kwargs
    ) -> PositionResult:
        """
        포지션 청산 (EXIT_LONG/SHORT)

        Args:
            symbol: 거래 심볼
            side: 포지션 방향 ('long' | 'short')
            size: 청산할 계약 수량 (contracts). 지정 시 해당 수량만 청산
            close_percentage: 청산 비율 (1-100). size가 없을 때 사용, 기본값 100

        Returns:
            PositionResult: 청산 결과

        OKX Signal Bot Exit 규격:
        - size 지정 시: investmentType="contract", amount=size
        - size 미지정 시: investmentType="percentage_position", amount=100 (전체)

        Examples:
            # 전체 청산 (100%)
            await executor.close_position(symbol, side="long")

            # 50% 청산
            await executor.close_position(symbol, side="long", close_percentage=50)

            # 특정 수량 청산 (10 contracts)
            await executor.close_position(symbol, side="long", size=10)
        """
        # 1. Symbol 변환
        instrument = self._convert_to_okx_format(symbol)

        # 2. Action 결정
        action = "EXIT_LONG" if side == "long" else "EXIT_SHORT"

        # 3. Payload 구성 - size 또는 percentage 기반으로 분기
        payload = {
            "action": action,
            "instrument": instrument,
            "signalToken": self.signal_token,
            "timestamp": datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')[:-3] + 'Z',
            "maxLag": str(self.max_lag),
        }

        # 청산 방식 결정
        if size is not None and size > 0:
            # 특정 수량(contracts) 청산
            payload["investmentType"] = "contract"
            payload["amount"] = str(size)
            close_info = f"{size} contracts"
        else:
            # 비율 기반 청산 (기본값: 100% 전체 청산)
            pct = close_percentage if close_percentage is not None else 100.0
            payload["investmentType"] = "percentage_position"
            payload["amount"] = str(pct)
            close_info = f"{pct}%"

        # 4. Webhook 전송
        try:
            logger.info(
                f"[SignalBot][{self.user_id}] Sending {action}: {instrument} ({close_info})"
            )

            response = await self.client.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()

            result = response.json()

            logger.info(
                f"[SignalBot][{self.user_id}] Position closed: {action} {symbol} ({close_info})"
            )

            return PositionResult(
                symbol=symbol,
                side=side,
                size=size if size is not None else 0.0,
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
        심볼 변환: 다양한 형식 → OKX instId 형식 (BTC-USDT-SWAP)

        OKX Signal Bot은 instId 형식을 사용함:
        - Perpetual: BTC-USDT-SWAP
        - Spot: BTC-USDT (지원하지 않음)

        Examples:
            'BTC/USDT:USDT' -> 'BTC-USDT-SWAP'  (CCXT 형식)
            'BTC-USDT-SWAP' -> 'BTC-USDT-SWAP'  (이미 OKX 형식)
            'BTCUSDT' -> 'BTC-USDT-SWAP'        (Binance 형식)
        """
        # 이미 OKX 형식인 경우
        if "-SWAP" in symbol:
            return symbol

        # CCXT 형식: BTC/USDT:USDT -> BTC-USDT-SWAP
        if "/" in symbol:
            # BTC/USDT:USDT -> BTC-USDT
            base = symbol.split("/")[0]
            quote = symbol.split("/")[1].split(":")[0]
            return f"{base}-{quote}-SWAP"

        # Binance 형식: BTCUSDT -> BTC-USDT-SWAP
        # 일반적인 quote currencies
        for quote in ["USDT", "USDC", "BUSD", "USD"]:
            if symbol.endswith(quote):
                base = symbol[:-len(quote)]
                return f"{base}-{quote}-SWAP"

        # 알 수 없는 형식 - 그대로 반환하고 경고
        logger.warning(
            f"[SignalBot] Unknown symbol format: {symbol}. "
            f"Returning as-is. Expected OKX instId format like 'BTC-USDT-SWAP'"
        )
        return symbol
