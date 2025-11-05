"""
API Direct Executor - 기존 CCXT 방식

CCXT를 통한 직접 API 호출로 주문 실행

특징:
- Market/Limit/Stop 등 다양한 주문 타입 지원
- TP/SL 주문 미리 등록 (주문 취소 필요)
- 실시간 가격 조회 및 주문 상태 모니터링
"""

from datetime import datetime
from typing import Dict, Optional

from HYPERRSI.src.api.dependencies import get_user_api_keys
from HYPERRSI.src.trading.executors.base_executor import (
    BaseExecutor,
    OrderResult,
    PositionResult,
)
from HYPERRSI.src.trading.services.order_wrapper import OrderWrapper
from shared.logging import get_logger
from shared.utils import safe_float

logger = get_logger(__name__)


class APIDirectExecutor(BaseExecutor):
    """
    CCXT 기반 직접 API 호출 방식

    기존 로직과 동일:
    - OrderWrapper를 통한 주문 실행
    - Market/Limit/Stop 등 다양한 주문 타입
    - TP/SL 주문 사전 등록
    - 주문 취소/수정 지원
    """

    def __init__(self, user_id: str, api_keys: Dict[str, str]):
        """
        Args:
            user_id: 사용자 ID
            api_keys: OKX API 키 정보 (api_key, api_secret, passphrase)
        """
        super().__init__(user_id)
        self.api_keys = api_keys
        self.exchange: Optional[OrderWrapper] = None

    async def _ensure_exchange(self) -> OrderWrapper:
        """Exchange 인스턴스 확인 및 생성"""
        if self.exchange is None:
            self.exchange = OrderWrapper(self.user_id, self.api_keys)
        return self.exchange

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
        진입 주문 생성

        Args:
            symbol: 거래 심볼 (예: 'BTC/USDT:USDT')
            side: 주문 방향 ('buy' for long, 'sell' for short)
            size: 주문 수량
            leverage: 레버리지 (선택)
            order_type: 주문 타입 ('market', 'limit', 'stop')
            price: Limit 주문 가격
            trigger_price: Stop 주문 트리거 가격
            **kwargs: 추가 파라미터 (posSide, tdMode 등)

        Returns:
            OrderResult: 주문 실행 결과
        """
        exchange = await self._ensure_exchange()

        try:
            logger.info(
                f"[APIDirectExecutor][{self.user_id}] Creating {order_type} order: "
                f"{side} {size} {symbol}"
            )

            # CCXT params 구성
            params = kwargs.copy()

            # Leverage 설정 (필요한 경우)
            if leverage:
                params['leverage'] = leverage

            # Stop order params
            if trigger_price:
                params['stopPrice'] = trigger_price

            # 주문 실행
            result = await exchange.create_order(
                symbol=symbol,
                order_type=order_type,
                side=side,
                amount=size,
                price=price,
                params=params
            )

            logger.info(
                f"[APIDirectExecutor][{self.user_id}] Order created: "
                f"ID={result.get('id')}, Status={result.get('status')}"
            )

            return OrderResult(
                order_id=result.get('id', ''),
                symbol=symbol,
                side=side,
                size=size,
                price=safe_float(result.get('price')),
                status=result.get('status', 'unknown'),
                timestamp=datetime.utcnow().isoformat()
            )

        except Exception as e:
            logger.error(
                f"[APIDirectExecutor][{self.user_id}] Order failed: {str(e)}"
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
        포지션 청산 (Market order)

        Args:
            symbol: 거래 심볼
            side: 포지션 방향 ('long' | 'short')
            size: 청산 수량 (None이면 전체 청산)
            **kwargs: 추가 파라미터

        Returns:
            PositionResult: 청산 결과
        """
        exchange = await self._ensure_exchange()

        try:
            # 포지션 조회 (size가 없는 경우)
            if size is None:
                positions = await exchange.fetch_positions([symbol])
                position = next(
                    (p for p in positions if p['info']['posSide'] == side),
                    None
                )
                if not position:
                    raise ValueError(f"No {side} position found for {symbol}")

                size = abs(safe_float(position.get('contracts', 0)))

            # 반대 방향 주문으로 청산
            close_side = "sell" if side == "long" else "buy"

            logger.info(
                f"[APIDirectExecutor][{self.user_id}] Closing position: "
                f"{side} {size} {symbol}"
            )

            # 청산 주문 (reduce_only)
            params = kwargs.copy()
            params['reduceOnly'] = True

            result = await exchange.create_order(
                symbol=symbol,
                order_type="market",
                side=close_side,
                amount=size,
                params=params
            )

            logger.info(
                f"[APIDirectExecutor][{self.user_id}] Position closed: "
                f"ID={result.get('id')}"
            )

            return PositionResult(
                symbol=symbol,
                side=side,
                size=size,
                close_price=safe_float(result.get('average', 0)),
                realized_pnl=None,  # OKX API에서 조회 필요
                status="closed",
                timestamp=datetime.utcnow().isoformat()
            )

        except Exception as e:
            logger.error(
                f"[APIDirectExecutor][{self.user_id}] Close failed: {str(e)}"
            )
            raise

    async def cancel_order(
        self,
        order_id: str,
        symbol: str,
        **kwargs
    ) -> Dict:
        """
        주문 취소 (API Direct 전용)

        Args:
            order_id: 취소할 주문 ID
            symbol: 거래 심볼
            **kwargs: 추가 파라미터

        Returns:
            Dict: 취소 결과
        """
        exchange = await self._ensure_exchange()

        try:
            logger.info(
                f"[APIDirectExecutor][{self.user_id}] Canceling order: "
                f"ID={order_id} {symbol}"
            )

            result = await exchange.cancel_order(
                order_id=order_id,
                symbol=symbol,
                params=kwargs
            )

            logger.info(
                f"[APIDirectExecutor][{self.user_id}] Order canceled: "
                f"ID={order_id}"
            )

            return result

        except Exception as e:
            logger.error(
                f"[APIDirectExecutor][{self.user_id}] Cancel failed: {str(e)}"
            )
            raise

    async def close(self) -> None:
        """CCXT exchange 연결 종료"""
        if self.exchange:
            await self.exchange.close()
            logger.debug(f"[APIDirectExecutor][{self.user_id}] Exchange closed")
