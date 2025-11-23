"""
Stop Loss Service

스탑로스 주문 관리 관련 비즈니스 로직
"""
import asyncio
import json
from typing import Any, Dict, Optional

import ccxt.async_support as ccxt
from fastapi import HTTPException

from HYPERRSI.src.api.exchange.models import OrderResponse
from HYPERRSI.src.api.routes.order.calculators import calculate_stop_loss_distance
from HYPERRSI.src.api.routes.order.error_messages import (
    INVALID_SYMBOL_FORMAT,
    REDIS_DELETE_FAILED,
    REDIS_QUERY_FAILED,
    REDIS_SAVE_FAILED,
    STOP_LOSS_CREATE_FAILED,
    STOP_LOSS_NO_RESPONSE_DATA,
)
from HYPERRSI.src.api.routes.order.parsers import parse_algo_order_to_order_response
from HYPERRSI.src.api.routes.order.services.base_service import BaseService
from HYPERRSI.src.api.routes.order.validators import (
    validate_stop_loss_params,
    validate_symbol_format,
)
from HYPERRSI.src.core.logger import error_logger
from shared.database.redis_patterns import RedisTimeout
from shared.logging import get_logger
from shared.utils.type_converters import safe_float

logger = get_logger(__name__)


class StopLossService(BaseService):
    """스탑로스 관련 서비스"""

    @staticmethod
    @BaseService.handle_exchange_error("스탑로스 주문 생성")
    @BaseService.log_operation("스탑로스 주문 생성", include_args=True)
    async def create_stop_loss_order(
        exchange: ccxt.okx,
        symbol: str,
        side: str,
        amount: float,
        trigger_price: float,
        order_price: Optional[float] = None,
        pos_side: str = "net",
        reduce_only: bool = True,
        ord_type: str = "trigger"
    ) -> OrderResponse:
        """
        스탑로스 주문 생성

        Args:
            exchange: 거래소 클라이언트
            symbol: 심볼
            side: 주문 사이드 (buy/sell)
            amount: 수량
            trigger_price: 트리거 가격
            order_price: 주문 가격 (None이면 시장가)
            pos_side: 포지션 사이드 (long/short/net)
            reduce_only: 감소 전용 주문 여부

        Returns:
            OrderResponse: 생성된 스탑로스 주문 정보

        Raises:
            HTTPException: 주문 생성 실패 시
        """
        BaseService.validate_exchange(exchange)
        BaseService.validate_required_params(symbol=symbol, side=side, amount=amount, trigger_price=trigger_price)

        # 파라미터 검증
        if not validate_symbol_format(symbol):
            raise HTTPException(status_code=400, detail=INVALID_SYMBOL_FORMAT)

        is_valid, error_msg = validate_stop_loss_params(trigger_price, order_price, side)
        if not is_valid:
            raise HTTPException(status_code=400, detail=error_msg)

        # ordType은 OKX 플랜 주문 규격에 맞춰 trigger/conditional만 허용
        ord_type_normalized = (ord_type or "trigger").lower()
        if ord_type_normalized not in {"trigger", "conditional"}:
            ord_type_normalized = "trigger"

        # OKX 스탑로스 주문 파라미터 구성
        params = {
            "instId": symbol,  # 상품 ID (필수)
            "tdMode": "cross",  # 거래 모드
            "side": side.lower(),
            "posSide": pos_side,
            "ordType": ord_type_normalized,
            "sz": str(amount),
            "triggerPx": str(trigger_price),
            "orderPx": str(order_price) if order_price else "-1",  # -1은 시장가
            "triggerPxType": "mark",  # 마크 가격 기준
            "reduceOnly": "true" if reduce_only else "false"  # OKX API는 문자열 요구
        }

        # OKX API를 통해 알고리즘 주문 생성
        # CCXT는 dict 파라미터만 허용하므로 리스트로 감싸지 않는다
        response = await exchange.privatePostTradeOrderAlgo(params)

        code = response.get("code")
        if code != "0":
            msg = response.get("msg", STOP_LOSS_CREATE_FAILED)
            logger.error(f"{STOP_LOSS_CREATE_FAILED}: {msg}")
            raise HTTPException(status_code=400, detail=msg)

        data = response.get("data", [])
        if not data:
            raise HTTPException(status_code=500, detail=STOP_LOSS_NO_RESPONSE_DATA)

        algo_order = data[0]
        algo_id = algo_order.get("algoId")

        logger.info(f"스탑로스 주문 생성 성공: {algo_id} - {symbol} {side} @ {trigger_price}")

        # OrderResponse 형태로 변환
        return parse_algo_order_to_order_response(
            {
                "algoId": algo_id,
                "instId": symbol,
                "side": side,
                "ordType": params["ordType"],
                "sz": str(amount),
                "triggerPx": str(trigger_price),
                "actualPx": str(order_price) if order_price else None,
                "state": "live",
                "posSide": pos_side
            },
            "trigger"
        )

    @staticmethod
    async def update_stop_loss_order(
        exchange: ccxt.okx,
        old_order_id: str,
        symbol: str,
        side: str,
        amount: float,
        new_trigger_price: float,
        new_order_price: Optional[float] = None,
        pos_side: str = "net"
    ) -> OrderResponse:
        """
        스탑로스 주문 업데이트 (기존 주문 취소 후 새 주문 생성)

        Args:
            exchange: 거래소 클라이언트
            old_order_id: 기존 주문 ID
            symbol: 심볼
            side: 주문 사이드
            amount: 수량
            new_trigger_price: 새 트리거 가격
            new_order_price: 새 주문 가격
            pos_side: 포지션 사이드

        Returns:
            OrderResponse: 새로 생성된 스탑로스 주문 정보

        Raises:
            HTTPException: 업데이트 실패 시
        """
        try:
            # 기존 스탑로스 주문 취소
            await StopLossService.cancel_stop_loss_order(
                exchange, old_order_id, symbol
            )

            # 새 스탑로스 주문 생성
            new_order = await StopLossService.create_stop_loss_order(
                exchange=exchange,
                symbol=symbol,
                side=side,
                amount=amount,
                trigger_price=new_trigger_price,
                order_price=new_order_price,
                pos_side=pos_side,
                reduce_only=True
            )

            logger.info(f"스탑로스 주문 업데이트 성공: {old_order_id} → {new_order.order_id}")
            return new_order

        except HTTPException:
            raise
        except Exception as e:
            error_logger.error(f"스탑로스 주문 업데이트 실패: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"스탑로스 주문 업데이트 실패: {str(e)}")

    @staticmethod
    @BaseService.handle_exchange_error("스탑로스 주문 취소")
    @BaseService.log_operation("스탑로스 주문 취소")
    async def cancel_stop_loss_order(
        exchange: ccxt.okx,
        order_id: str,
        symbol: str
    ) -> bool:
        """
        스탑로스 주문 취소

        Args:
            exchange: 거래소 클라이언트
            order_id: 알고리즘 주문 ID
            symbol: 심볼

        Returns:
            bool: 취소 성공 여부

        Raises:
            HTTPException: 취소 실패 시
        """
        BaseService.validate_exchange(exchange)
        BaseService.validate_required_params(order_id=order_id, symbol=symbol)

        if not validate_symbol_format(symbol):
            raise HTTPException(status_code=400, detail=INVALID_SYMBOL_FORMAT)

        # CCXT의 자동 생성 메서드 사용 (올바른 서명 생성)
        # OKX API는 배열을 직접 받음 (data로 감싸지 않음)
        response = await exchange.privatePostTradeCancelAlgos([{
            "algoId": order_id,
            "instId": symbol
        }])

        code = response.get("code")
        if code != "0":
            msg = response.get("msg", "스탑로스 주문 취소 실패")
            logger.warning(f"스탑로스 주문 취소 실패: {msg}")
            return False

        logger.info(f"스탑로스 주문 취소 성공: {order_id}")
        return True

    @staticmethod
    async def update_stop_loss_redis(
        redis_client: Any,
        user_id: str,
        symbol: str,
        side: str,
        trigger_price: float,
        order_id: str,
        entry_price: Optional[float] = None
    ) -> None:
        """
        Redis에 스탑로스 정보 저장

        Args:
            redis_client: Redis 클라이언트
            user_id: 사용자 ID
            symbol: 심볼
            side: 포지션 사이드
            trigger_price: 트리거 가격
            order_id: 주문 ID
            entry_price: 진입 가격 (선택)
        """
        try:
            sl_key = f"user:{user_id}:position:{symbol}:{side}:sl_data"

            sl_data = {
                "trigger_price": str(trigger_price),
                "order_id": order_id,
                "side": side,
                "symbol": symbol
            }

            if entry_price:
                sl_data["entry_price"] = str(entry_price)
                # 스탑로스 거리 계산
                distance = calculate_stop_loss_distance(entry_price, trigger_price, side)
                sl_data["distance_percent"] = str(distance)

            await asyncio.wait_for(
                redis_client.hset(sl_key, mapping=sl_data),
                timeout=RedisTimeout.FAST_OPERATION
            )

            logger.info(f"Redis 스탑로스 데이터 저장 완료: {sl_key}")

        except Exception as e:
            error_logger.error(f"Redis 스탑로스 데이터 저장 실패: {str(e)}", exc_info=True)
            # Redis 저장 실패는 치명적이지 않으므로 예외를 발생시키지 않음

    @staticmethod
    async def get_stop_loss_from_redis(
        redis_client: Any,
        user_id: str,
        symbol: str,
        side: str
    ) -> Optional[Dict[str, Any]]:
        """
        Redis에서 스탑로스 정보 조회

        Args:
            redis_client: Redis 클라이언트
            user_id: 사용자 ID
            symbol: 심볼
            side: 포지션 사이드

        Returns:
            Optional[Dict[str, Any]]: 스탑로스 정보
        """
        try:
            sl_key = f"user:{user_id}:position:{symbol}:{side}:sl_data"
            sl_data = await asyncio.wait_for(
                redis_client.hgetall(sl_key),
                timeout=RedisTimeout.FAST_OPERATION
            )

            if not sl_data:
                return None

            # bytes를 str로 변환
            return {k.decode() if isinstance(k, bytes) else k:
                    v.decode() if isinstance(v, bytes) else v
                    for k, v in sl_data.items()}

        except Exception as e:
            error_logger.error(f"Redis 스탑로스 데이터 조회 실패: {str(e)}", exc_info=True)
            return None

    @staticmethod
    async def delete_stop_loss_from_redis(
        redis_client: Any,
        user_id: str,
        symbol: str,
        side: str
    ) -> None:
        """
        Redis에서 스탑로스 정보 삭제

        Args:
            redis_client: Redis 클라이언트
            user_id: 사용자 ID
            symbol: 심볼
            side: 포지션 사이드
        """
        try:
            sl_key = f"user:{user_id}:position:{symbol}:{side}:sl_data"
            await asyncio.wait_for(
                redis_client.delete(sl_key),
                timeout=RedisTimeout.FAST_OPERATION
            )

            logger.info(f"Redis 스탑로스 데이터 삭제 완료: {sl_key}")

        except Exception as e:
            error_logger.error(f"Redis 스탑로스 데이터 삭제 실패: {str(e)}", exc_info=True)
