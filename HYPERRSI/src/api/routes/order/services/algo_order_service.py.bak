"""
Algo Order Service

알고리즘 주문(트리거, 조건부 주문) 관련 비즈니스 로직
"""
from typing import List, Optional, Dict, Any
import json
import ccxt.async_support as ccxt
from fastapi import HTTPException

from HYPERRSI.src.api.exchange.models import OrderResponse, CancelOrdersResponse
from shared.logging import get_logger
from HYPERRSI.src.core.logger import error_logger
from ..parsers import parse_algo_order_to_order_response
from ..constants import ALGO_ORDERS_CHUNK_SIZE, API_ENDPOINTS, REGULAR_ORDERS_CHUNK_SIZE
from ..validators import validate_symbol_format
from ..error_messages import INVALID_SYMBOL_FORMAT, NO_ALGO_ORDERS_TO_CANCEL
from .base_service import BaseService

logger = get_logger(__name__)


class AlgoOrderService(BaseService):
    """알고리즘 주문 관련 서비스"""

    @staticmethod
    async def get_algo_order_info(
        exchange: ccxt.okx,
        order_id: str,
        algo_type: str = "trigger"
    ) -> Optional[OrderResponse]:
        """
        알고리즘 주문 정보 조회

        Args:
            exchange: 거래소 클라이언트
            order_id: 알고리즘 주문 ID
            algo_type: 알고리즘 타입 (trigger, conditional 등)

        Returns:
            Optional[OrderResponse]: 알고리즘 주문 정보

        Raises:
            HTTPException: 조회 실패 시
        """
        try:
            # OKX API를 통해 알고리즘 주문 조회
            response = await exchange.fetch2(
                path="trade/order-algo",
                api="private",
                method="GET",
                params={"algoId": order_id, "ordType": algo_type}
            )

            code = response.get("code")
            if code != "0":
                msg = response.get("msg", "알고리즘 주문 조회 실패")
                logger.warning(f"알고리즘 주문 조회 실패: {msg}")
                return None

            data = response.get("data", [])
            if not data:
                return None

            algo_order = data[0]
            return parse_algo_order_to_order_response(algo_order, algo_type)

        except ccxt.NetworkError as e:
            error_logger.error(f"네트워크 오류 - 알고리즘 주문 조회 실패: {str(e)}")
            raise HTTPException(status_code=503, detail="거래소 연결 오류")
        except Exception as e:
            error_logger.error(f"알고리즘 주문 조회 실패: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"알고리즘 주문 조회 실패: {str(e)}")

    @staticmethod
    async def fetch_algo_order_by_id(
        exchange: ccxt.okx,
        order_id: str,
        symbol: Optional[str] = None,
        algo_type: str = "trigger"
    ) -> Optional[Dict[str, Any]]:
        """
        알고리즘 주문 원본 데이터 조회

        Args:
            exchange: 거래소 클라이언트
            order_id: 알고리즘 주문 ID
            symbol: 심볼 (선택)
            algo_type: 알고리즘 타입

        Returns:
            Optional[Dict[str, Any]]: 알고리즘 주문 원본 데이터
        """
        try:
            params = {"ordType": algo_type}
            if symbol:
                params["instId"] = symbol

            resp = await exchange.fetch2(
                path="trade/orders-algo-pending",
                api="private",
                method="GET",
                params=params
            )

            code = resp.get("code")
            if code != "0":
                msg = resp.get("msg", "")
                logger.warning(f"알고리즘 주문 조회 실패: {msg}")
                return None

            algo_data = resp.get("data", [])
            for algo in algo_data:
                if algo.get("algoId") == order_id:
                    return algo

            # 미체결 목록에 없으면 완료된 주문 조회
            history_resp = await exchange.fetch2(
                path="trade/orders-algo-history",
                api="private",
                method="GET",
                params=params
            )

            h_code = history_resp.get("code")
            if h_code != "0":
                return None

            h_data = history_resp.get("data", [])
            for algo in h_data:
                if algo.get("algoId") == order_id:
                    return algo

            return None

        except Exception as e:
            logger.error(f"알고리즘 주문 조회 중 오류: {str(e)}")
            return None

    @staticmethod
    @BaseService.handle_exchange_error("알고리즘 주문 취소")
    @BaseService.log_operation("알고리즘 주문 취소")
    async def cancel_algo_orders_for_symbol(
        exchange: ccxt.okx,
        symbol: str,
        pos_side: Optional[str] = None
    ) -> int:
        """
        특정 심볼의 알고리즘 주문 취소

        Args:
            exchange: 거래소 클라이언트
            symbol: 심볼
            pos_side: 포지션 사이드 (Hedge 모드에서만 사용)

        Returns:
            int: 취소된 주문 수

        Raises:
            HTTPException: 취소 실패 시
        """
        BaseService.validate_exchange(exchange)
        BaseService.validate_required_params(symbol=symbol)

        if not validate_symbol_format(symbol):
            raise HTTPException(status_code=400, detail=INVALID_SYMBOL_FORMAT)

        # 미체결 알고리즘 주문 조회
        resp = await exchange.fetch2(
            path=API_ENDPOINTS['ALGO_ORDERS_PENDING'],
            api="private",
            method="GET",
            params={"instId": symbol}
        )

        code = resp.get("code")
        if code != "0":
            msg = resp.get("msg", "")
            logger.warning(f"알고리즘 주문 조회 실패: {msg}")
            return 0

        algo_data = resp.get("data", [])

        # pos_side 필터링 (Hedge 모드)
        if pos_side:
            algo_data = [x for x in algo_data if x.get('posSide') == pos_side]

        if not algo_data:
            return 0

        # 배치 단위로 취소
        canceled_count = 0
        for i in range(0, len(algo_data), ALGO_ORDERS_CHUNK_SIZE):
            chunk = algo_data[i:i + ALGO_ORDERS_CHUNK_SIZE]
            cancel_list = []

            for algo in chunk:
                algo_id = algo.get("algoId")
                inst_id = algo.get("instId", symbol)
                if algo_id and inst_id:
                    cancel_list.append({"algoId": algo_id, "instId": inst_id})

            if cancel_list:
                cancel_resp = await exchange.fetch2(
                    path=API_ENDPOINTS['CANCEL_ALGO_ORDERS'],
                    api="private",
                    method="POST",
                    params={},
                    headers=None,
                    body=json.dumps({"data": cancel_list})
                )

                c_code = cancel_resp.get("code")
                if c_code == "0":
                    canceled_count += len(cancel_list)
                else:
                    c_msg = cancel_resp.get("msg", "")
                    logger.warning(f"알고리즘 주문 취소 실패: {c_msg}")

        logger.info(f"알고리즘 주문 취소 완료: {canceled_count}개 - {symbol}")
        return canceled_count

    @staticmethod
    async def cancel_reduce_only_orders_for_symbol(
        exchange: ccxt.okx,
        symbol: str,
        pos_side: Optional[str] = None
    ) -> int:
        """
        reduceOnly 주문(TP 등) 취소

        Args:
            exchange: 거래소 클라이언트
            symbol: 심볼
            pos_side: 포지션 사이드 (Hedge 모드에서만 사용)

        Returns:
            int: 취소된 주문 수

        Raises:
            HTTPException: 취소 실패 시
        """
        try:
            if not validate_symbol_format(symbol):
                raise HTTPException(status_code=400, detail="잘못된 심볼 형식입니다")

            # 미체결 주문 조회
            open_orders = await exchange.fetch_open_orders(symbol=symbol)

            if not open_orders:
                return 0

            # reduceOnly 주문 필터링
            orders_to_cancel = []
            for order in open_orders:
                info = order.get("info", {})
                ro_flag = str(info.get("reduceOnly", "false")).lower() == "true"
                this_pos_side = info.get("posSide", "net")

                if ro_flag and (not pos_side or this_pos_side == pos_side):
                    orders_to_cancel.append(order)

            if not orders_to_cancel:
                return 0

            # 배치 단위로 취소
            canceled_count = 0
            for i in range(0, len(orders_to_cancel), REGULAR_ORDERS_CHUNK_SIZE):
                chunk = orders_to_cancel[i:i + REGULAR_ORDERS_CHUNK_SIZE]
                cancel_list = []

                for order in chunk:
                    ord_id = order["id"] or order["info"].get("ordId")
                    inst_id = order["info"].get("instId", symbol)
                    if ord_id and inst_id:
                        cancel_list.append({"ordId": ord_id, "instId": inst_id})

                if cancel_list:
                    resp = await exchange.fetch2(
                        path=API_ENDPOINTS['CANCEL_BATCH_ORDERS'],
                        api="private",
                        method="POST",
                        params={},
                        headers=None,
                        body=json.dumps({"data": cancel_list})
                    )

                    code = resp.get("code")
                    if code == "0":
                        canceled_count += len(cancel_list)
                    else:
                        msg = resp.get("msg", "")
                        logger.warning(f"reduceOnly 주문 취소 실패: {msg}")

            logger.info(f"reduceOnly 주문 취소 완료: {canceled_count}개 - {symbol}")
            return canceled_count

        except ccxt.NetworkError as e:
            error_logger.error(f"네트워크 오류 - reduceOnly 주문 취소 실패: {str(e)}")
            raise HTTPException(status_code=503, detail="거래소 연결 오류")
        except Exception as e:
            error_logger.error(f"reduceOnly 주문 취소 실패: {str(e)}", exc_info=True)
            return 0

    @staticmethod
    async def cancel_all_algo_orders(
        exchange: ccxt.okx,
        symbol: Optional[str] = None
    ) -> CancelOrdersResponse:
        """
        모든 알고리즘 주문 취소

        Args:
            exchange: 거래소 클라이언트
            symbol: 심볼 (선택)

        Returns:
            CancelOrdersResponse: 취소 결과

        Raises:
            HTTPException: 취소 실패 시
        """
        try:
            if symbol and not validate_symbol_format(symbol):
                raise HTTPException(status_code=400, detail="잘못된 심볼 형식입니다")

            # 심볼이 지정된 경우
            if symbol:
                canceled = await AlgoOrderService.cancel_algo_orders_for_symbol(exchange, symbol)
                return CancelOrdersResponse(
                    success=True,
                    canceled_count=canceled,
                    failed_count=0,
                    message=f"{canceled}개의 알고리즘 주문이 취소되었습니다"
                )

            # 모든 심볼의 알고리즘 주문 취소
            resp = await exchange.fetch2(
                path=API_ENDPOINTS['ALGO_ORDERS_PENDING'],
                api="private",
                method="GET",
                params={}
            )

            code = resp.get("code")
            if code != "0":
                raise HTTPException(status_code=500, detail="알고리즘 주문 조회 실패")

            algo_data = resp.get("data", [])

            if not algo_data:
                return CancelOrdersResponse(
                    success=True,
                    canceled_count=0,
                    failed_count=0,
                    message="취소할 알고리즘 주문이 없습니다"
                )

            # 배치 단위로 취소
            canceled_count = 0
            failed_count = 0

            for i in range(0, len(algo_data), ALGO_ORDERS_CHUNK_SIZE):
                chunk = algo_data[i:i + ALGO_ORDERS_CHUNK_SIZE]
                cancel_list = []

                for algo in chunk:
                    algo_id = algo.get("algoId")
                    inst_id = algo.get("instId")
                    if algo_id and inst_id:
                        cancel_list.append({"algoId": algo_id, "instId": inst_id})

                if cancel_list:
                    try:
                        cancel_resp = await exchange.fetch2(
                            path=API_ENDPOINTS['CANCEL_ALGO_ORDERS'],
                            api="private",
                            method="POST",
                            params={},
                            headers=None,
                            body=json.dumps({"data": cancel_list})
                        )

                        c_code = cancel_resp.get("code")
                        if c_code == "0":
                            canceled_count += len(cancel_list)
                        else:
                            failed_count += len(cancel_list)
                    except Exception as e:
                        error_logger.error(f"알고리즘 주문 배치 취소 실패: {str(e)}")
                        failed_count += len(cancel_list)

            message = f"총 {canceled_count}개 알고리즘 주문 취소, {failed_count}개 실패"
            logger.info(message)

            return CancelOrdersResponse(
                success=failed_count == 0,
                canceled_count=canceled_count,
                failed_count=failed_count,
                message=message
            )

        except HTTPException:
            raise
        except ccxt.NetworkError as e:
            error_logger.error(f"네트워크 오류 - 전체 알고리즘 주문 취소 실패: {str(e)}")
            raise HTTPException(status_code=503, detail="거래소 연결 오류")
        except Exception as e:
            error_logger.error(f"전체 알고리즘 주문 취소 실패: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"알고리즘 주문 취소 실패: {str(e)}")
