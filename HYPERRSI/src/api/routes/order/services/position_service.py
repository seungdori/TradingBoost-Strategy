"""
Position Service

포지션 관리 관련 비즈니스 로직
"""
from decimal import Decimal
from typing import Any, Dict, Optional

import ccxt.async_support as ccxt
from fastapi import HTTPException

from HYPERRSI.src.api.exchange.models import OrderResponse
from HYPERRSI.src.api.routes.order.calculators import calculate_close_amount
from HYPERRSI.src.api.routes.order.error_messages import (
    INVALID_CLOSE_AMOUNT,
    INVALID_CLOSE_PERCENT,
    INVALID_SYMBOL_FORMAT,
    NO_POSITION_TO_CLOSE,
    POSITION_NOT_FOUND,
    REDIS_UPDATE_FAILED,
)
from HYPERRSI.src.api.routes.order.services.algo_order_service import AlgoOrderService
from HYPERRSI.src.api.routes.order.services.base_service import BaseService
from HYPERRSI.src.api.routes.order.services.order_service import OrderService
from HYPERRSI.src.api.routes.order.validators import validate_close_percent, validate_symbol_format
from HYPERRSI.src.core.logger import error_logger
from shared.logging import get_logger

logger = get_logger(__name__)


class PositionService(BaseService):
    """포지션 관련 서비스"""

    @staticmethod
    @BaseService.handle_exchange_error("포지션 종료")
    @BaseService.log_operation("포지션 종료", include_args=True)
    async def close_position(
        exchange: ccxt.okx,
        user_id: str,
        symbol: str,
        close_type: str = "market",
        price: Optional[float] = None,
        close_percent: float = 100.0,
        redis_client: Optional[Any] = None
    ) -> OrderResponse:
        """
        포지션 종료

        Args:
            exchange: 거래소 클라이언트
            user_id: 사용자 ID
            symbol: 심볼
            close_type: 종료 타입 (market/limit)
            price: 가격 (limit 타입인 경우 필수)
            close_percent: 종료할 포지션 비율 (1-100)
            redis_client: Redis 클라이언트 (포지션 데이터 조회용)

        Returns:
            OrderResponse: 종료 주문 정보

        Raises:
            HTTPException: 종료 실패 시
        """
        BaseService.validate_exchange(exchange)
        BaseService.validate_required_params(symbol=symbol, user_id=user_id)

        # 파라미터 검증
        if not validate_symbol_format(symbol):
            raise HTTPException(status_code=400, detail=INVALID_SYMBOL_FORMAT)

        if not validate_close_percent(close_percent):
            raise HTTPException(status_code=400, detail=INVALID_CLOSE_PERCENT)

        # 현재 포지션 조회
        positions = await exchange.fetch_positions([symbol])

        if not positions:
            raise HTTPException(status_code=404, detail=POSITION_NOT_FOUND)

        position = positions[0]
        contracts = float(position.get('contracts', 0))

        if contracts == 0:
            raise HTTPException(status_code=400, detail=NO_POSITION_TO_CLOSE)

        # 종료할 수량 계산
        close_amount = calculate_close_amount(contracts, close_percent)

        if close_amount <= 0:
            raise HTTPException(status_code=400, detail=INVALID_CLOSE_AMOUNT)

        # 포지션 사이드 확인
        side = position.get('side', 'long')
        pos_side = position.get('info', {}).get('posSide', 'net')

        # 종료 주문 사이드 결정 (포지션과 반대)
        close_side = "sell" if side == "long" else "buy"

        # 종료 주문 생성
        logger.info(f"포지션 종료 시작: {symbol} {side} {close_amount} ({close_percent}%)")

        # 기존 알고리즘 주문 및 reduceOnly 주문 취소
        await AlgoOrderService.cancel_algo_orders_for_symbol(
            exchange, symbol, pos_side if pos_side != 'net' else None
        )
        await AlgoOrderService.cancel_reduce_only_orders_for_symbol(
            exchange, symbol, pos_side if pos_side != 'net' else None
        )

        # 종료 주문 파라미터
        params = {
            "reduceOnly": True
        }
        if pos_side != 'net':
            params['posSide'] = pos_side

        # 종료 주문 생성
        order = await OrderService.create_order(
            exchange=exchange,
            symbol=symbol,
            side=close_side,
            order_type=close_type,
            amount=close_amount,
            price=price,
            reduce_only=True,
            params=params
        )

        logger.info(f"포지션 종료 주문 생성 성공: {order.order_id}")

        # Redis에 포지션 상태 업데이트 (선택적)
        if redis_client:
            try:
                position_key = f"user:{user_id}:position:{symbol}:closing"
                await redis_client.setex(position_key, 300, "true")  # 5분 TTL
            except Exception as e:
                logger.warning(f"{REDIS_UPDATE_FAILED}: {str(e)}")

        return order

    @staticmethod
    @BaseService.handle_exchange_error("포지션 정보 조회")
    @BaseService.log_operation("포지션 정보 조회")
    async def get_position_info(
        exchange: ccxt.okx,
        symbol: str
    ) -> Optional[Dict[str, Any]]:
        """
        포지션 정보 조회

        Args:
            exchange: 거래소 클라이언트
            symbol: 심볼

        Returns:
            Optional[Dict[str, Any]]: 포지션 정보

        Raises:
            HTTPException: 조회 실패 시
        """
        BaseService.validate_exchange(exchange)
        BaseService.validate_required_params(symbol=symbol)

        if not validate_symbol_format(symbol):
            raise HTTPException(status_code=400, detail=INVALID_SYMBOL_FORMAT)

        positions = await exchange.fetch_positions([symbol])

        if not positions:
            return None

        position = positions[0]
        contracts = float(position.get('contracts', 0))

        if contracts == 0:
            return None

        # 포지션 정보 가공
        info = position.get('info', {})
        return {
            "symbol": symbol,
            "side": position.get('side', 'long'),
            "contracts": contracts,
            "entry_price": float(position.get('entryPrice', 0)),
            "mark_price": float(position.get('markPrice', 0)),
            "liquidation_price": float(position.get('liquidationPrice', 0)),
            "unrealized_pnl": float(position.get('unrealizedPnl', 0)),
            "leverage": int(info.get('lever', 1)),
            "position_side": info.get('posSide', 'net'),
            "margin_mode": info.get('mgnMode', 'cross'),
            "notional_value": float(position.get('notional', 0)),
            "percentage": float(position.get('percentage', 0))
        }

    @staticmethod
    async def init_position_data(
        user_id: str,
        symbol: str,
        side: str,
        redis_client: Any
    ) -> None:
        """
        포지션 데이터 초기화 (Redis)

        Args:
            user_id: 사용자 ID
            symbol: 심볼
            side: 포지션 사이드
            redis_client: Redis 클라이언트
        """
        try:
            # Redis 키 생성
            dual_side_position_key = f"user:{user_id}:{symbol}:dual_side_position"
            position_state_key = f"user:{user_id}:position:{symbol}:position_state"
            tp_data_key = f"user:{user_id}:position:{symbol}:{side}:tp_data"
            ts_key = f"trailing:user:{user_id}:{symbol}:{side}"
            dca_count_key = f"user:{user_id}:position:{symbol}:{side}:dca_count"
            dca_levels_key = f"user:{user_id}:position:{symbol}:{side}:dca_levels"

            # 기존 데이터 삭제
            await redis_client.delete(
                dual_side_position_key,
                position_state_key,
                tp_data_key,
                ts_key,
                dca_count_key,
                dca_levels_key
            )

            logger.info(f"포지션 데이터 초기화 완료: {user_id} - {symbol} {side}")

        except Exception as e:
            error_logger.error(f"포지션 데이터 초기화 실패: {str(e)}", exc_info=True)
            # Redis 초기화 실패는 치명적이지 않으므로 예외를 발생시키지 않음

    @staticmethod
    @BaseService.handle_exchange_error("전체 포지션 조회")
    @BaseService.log_operation("전체 포지션 조회")
    async def get_all_positions(
        exchange: ccxt.okx
    ) -> list[Dict[str, Any]]:
        """
        모든 포지션 조회

        Args:
            exchange: 거래소 클라이언트

        Returns:
            list[Dict[str, Any]]: 포지션 리스트

        Raises:
            HTTPException: 조회 실패 시
        """
        BaseService.validate_exchange(exchange)

        positions = await exchange.fetch_positions()

        # 포지션이 있는 것만 필터링
        active_positions = []
        for position in positions:
            contracts = float(position.get('contracts', 0))
            if contracts > 0:
                info = position.get('info', {})
                active_positions.append({
                    "symbol": position.get('symbol'),
                    "side": position.get('side', 'long'),
                    "contracts": contracts,
                    "entry_price": float(position.get('entryPrice', 0)),
                    "mark_price": float(position.get('markPrice', 0)),
                    "unrealized_pnl": float(position.get('unrealizedPnl', 0)),
                    "leverage": int(info.get('lever', 1)),
                    "position_side": info.get('posSide', 'net')
                })

        return active_positions
