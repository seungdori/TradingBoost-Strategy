# src/utils/order_utils.py

import json
import datetime as dt
import traceback
from decimal import Decimal
from typing import Any, Dict, List, Optional

import ccxt.async_support as ccxt
from fastapi import HTTPException
from HYPERRSI.src.core.logger import get_logger
from HYPERRSI.src.core.database import redis_client

# API 모델 (Pydantic) 및 Enum
from HYPERRSI.src.api.exchange.models import (
    OrderResponse,
    OrderStatus,
    OrderType,
    OrderSide,
)

logger = get_logger(__name__)

# ======================================================
# 상수 (Constants)
# ======================================================
ALGO_ORDERS_CHUNK_SIZE = 10
REGULAR_ORDERS_CHUNK_SIZE = 20
API_ENDPOINTS = {
    "ALGO_ORDERS_PENDING": "trade/orders-algo-pending",
    "CANCEL_ALGO_ORDERS": "trade/cancel-algos",
    "CANCEL_BATCH_ORDERS": "trade/cancel-batch-orders",
}


# ======================================================
# 기본 유틸리티 함수들
# ======================================================
def safe_float(value: Any, default: float = 0.0) -> float:
    """
    값이 None이거나 비어있을 경우 default 값을 리턴하며,
    안전하게 float로 변환합니다.
    """
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (ValueError, TypeError):
        return default


async def handle_exchange_error(e: Exception):
    """
    거래소 관련 작업에서 공통으로 사용할 에러 핸들러.
    발생한 예외 유형에 따라 HTTPException을 발생시킵니다.
    """
    logger.error(f"Exchange operation failed: {str(e)}", exc_info=True)

    if isinstance(e, ccxt.NetworkError):
        raise HTTPException(status_code=503, detail="거래소 연결 오류가 발생했습니다")
    elif isinstance(e, ccxt.AuthenticationError):
        raise HTTPException(status_code=401, detail="인증 오류가 발생했습니다")
    elif isinstance(e, ccxt.BadRequest):
        # OKX의 주문 ID 관련 에러 처리
        if "51000" in str(e):
            raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다")
        raise HTTPException(status_code=400, detail=f"잘못된 요청: {str(e)}")
    elif isinstance(e, ccxt.ExchangeError):
        raise HTTPException(status_code=400, detail=f"거래소 오류: {str(e)}")
    else:
        raise HTTPException(status_code=500, detail="작업 중 오류가 발생했습니다")


# ======================================================
# 알고 주문 관련 함수들
# ======================================================
async def fetch_algo_order_by_id(
    exchange: ccxt.okx, order_id: str, symbol: Optional[str] = None, algo_type: Optional[str] = "trigger"
) -> Optional[dict]:
    """
    OKX의 알고리즘 주문(트리거 주문)을 조회합니다.
    
    Args:
        exchange: ccxt.okx 인스턴스
        order_id: 알고리즘 주문 ID (algoId)
        symbol: 선택적 심볼

    Returns:
        주문 정보 dict 또는 None
    """
    params = {"instId": symbol, "ordType": algo_type} if symbol else {"ordType": algo_type}

    try:
        # 활성 주문 조회
        pending_resp = await exchange.privateGetTradeOrdersAlgoPending(params=params)
        if pending_resp.get("code") == "0":
            found = next(
                (x for x in pending_resp.get("data", []) if x.get("algoId") == order_id), None
            )
            if found:
                return found

        # 히스토리 조회
        history_resp = await exchange.privateGetTradeOrdersAlgoHistory(params=params)
        if history_resp.get("code") == "0":
            found = next(
                (x for x in history_resp.get("data", []) if x.get("algoId") == order_id), None
            )
            if found:
                return found
    except Exception as e:
        traceback.print_exc()
        if "Not authenticated" in str(e):
            raise HTTPException(status_code=401, detail="Authentication error")
        elif "Network" in str(e):
            raise HTTPException(status_code=503, detail="Exchange connection error")
        logger.error(f"Error fetching algo order: {str(e)}")
    return None


def parse_algo_order_to_order_response(algo_order: dict, algo_type: str) -> OrderResponse:
    """
    OKX 알고 주문(Trigger) 데이터를 OrderResponse 형태로 변환합니다.
    
    Args:
        algo_order: 알고리즘 주문 데이터 dict.

    Returns:
        OrderResponse 모델 인스턴스
    """
    def safe_decimal(val, default="0"):
        if val is None or val == "":
            return Decimal(default)
        try:
            return Decimal(str(val))
        except Exception:
            return Decimal(default)

    order_id = algo_order.get("algoId", "N/A")
    client_order_id = algo_order.get("clOrdId")
    symbol = algo_order.get("instId", "N/A")

    # side 매핑
    side_str = algo_order.get("side", "").lower()
    side = OrderSide.BUY if side_str == "buy" else OrderSide.SELL

    # type 매핑
    o_type_str = algo_order.get("ordType", algo_type)
    o_type = OrderType.MARKET if o_type_str == "market" else OrderType.LIMIT

    # 수량 관련
    amount = safe_decimal(algo_order.get("sz", 0.0))
    filled_amount = safe_decimal(algo_order.get("fillSz", 0.0))
    remaining_amount = amount - filled_amount

    # 가격 관련
    price = safe_decimal(algo_order.get("triggerPx"))
    average_price = safe_decimal(algo_order.get("actualPx")) if algo_order.get("actualPx") else None

    # 상태 매핑
    status_map = {
        "live": OrderStatus.OPEN,
        "canceled": OrderStatus.CANCELED,
        "partially_filled": OrderStatus.PARTIALLY_FILLED,
        "filled": OrderStatus.FILLED,
        "failed": OrderStatus.REJECTED,
    }
    status = status_map.get(algo_order.get("state", "").lower(), OrderStatus.PENDING)

    created_at = int(algo_order.get("cTime")) if str(algo_order.get("cTime", "")).isdigit() else None
    updated_at = int(algo_order.get("uTime")) if str(algo_order.get("uTime", "")).isdigit() else None

    pnl = safe_decimal(algo_order.get("pnl", "0"))

    return OrderResponse(
        order_id=order_id,
        client_order_id=client_order_id,
        symbol=symbol,
        status=status,
        side=side,
        type=o_type,
        amount=amount,
        filled_amount=filled_amount,
        remaining_amount=remaining_amount,
        price=price,
        average_price=average_price,
        created_at=created_at,
        updated_at=updated_at,
        pnl=pnl,
        order_type=o_type_str,
        posSide=algo_order.get("posSide", "unknown"),
    )


def parse_order_response(order_data: dict) -> OrderResponse:
    """
    거래소에서 받아온 원시 주문 데이터를 OrderResponse 모델로 변환합니다.
    
    Args:
        order_data: 원시 주문 데이터 dict.
    
    Returns:
        OrderResponse 모델 인스턴스
    """
    return OrderResponse(
        order_id=order_data["id"],
        symbol=order_data["symbol"],
        side=order_data["side"],
        type=order_data["type"],
        amount=safe_float(order_data["amount"]),
        filled_amount=safe_float(order_data.get("filled", 0.0)),
        price=safe_float(order_data["price"]) if order_data.get("price") else None,
        average_price=safe_float(order_data["average"]) if order_data.get("average") else None,
        status=order_data["status"],
        timestamp=dt.datetime.fromtimestamp(order_data["timestamp"] / 1000)
        if order_data.get("timestamp")
        else dt.datetime.now(),
        pnl=safe_float(order_data.get("info", {}).get("pnl")),
    )


# ======================================================
# 주문 취소 관련 함수들
# ======================================================
async def cancel_algo_orders_for_symbol_and_side(
    exchange, symbol: str, pos_side: str
):
    """
    Hedge 모드에서 특정 심볼 및 posSide에 해당하는 알고 주문들을 취소합니다.
    """
    try:
        resp = await exchange.privateGetTradeOrdersAlgoPending(params={"instId": symbol})
        if resp.get("code") != "0":
            msg = resp.get("msg", "")
            logger.warning(f"[cancel_algo_orders_for_symbol_and_side] 알고주문 조회 실패: {msg}")
            return

        algo_data = resp.get("data", [])
        filtered = [x for x in algo_data if x.get("posSide") == pos_side]

        for i in range(0, len(filtered), ALGO_ORDERS_CHUNK_SIZE):
            chunk = filtered[i : i + ALGO_ORDERS_CHUNK_SIZE]
            cancel_list = []
            for algo in chunk:
                algo_id = algo.get("algoId")
                inst_id = algo.get("instId", symbol)
                if algo_id and inst_id:
                    cancel_list.append({"algoId": algo_id, "instId": inst_id})

            if cancel_list:
                cancel_resp = await exchange.fetch2(
                    path=API_ENDPOINTS["CANCEL_ALGO_ORDERS"],
                    api="private",
                    method="POST",
                    params={},
                    headers=None,
                    body=json.dumps({"data": cancel_list}),
                )
                if cancel_resp.get("code") != "0":
                    logger.warning(
                        f"[cancel_algo_orders_for_symbol_and_side] 취소 실패: {cancel_resp.get('msg', '')}"
                    )
    except Exception as e:
        logger.error(
            f"[cancel_algo_orders_for_symbol_and_side] 오류: {str(e)}", exc_info=True
        )


async def set_position_mode(exchange, hedged: bool = True):
    """
    포지션 모드 설정
    
    Args:
        exchange: CCXT exchange 인스턴스
        hedged (bool): True면 헷지모드, False면 단방향 모드
    """
    try:
        return await exchange.set_position_mode(hedged)
    except Exception as e:
        logger.error(f"포지션 모드 설정 실패: {str(e)}")
        raise


async def cancel_algo_orders_for_symbol(
    exchange, symbol: str, pos_side: Optional[str] = None
):
    """
    특정 심볼에 대한 알고 주문 취소 함수.
    pos_side가 주어지면 해당 pos_side의 주문만 취소합니다.
    """
    try:
        resp = await exchange.fetch2(
            path=API_ENDPOINTS["ALGO_ORDERS_PENDING"],
            api="private",
            method="GET",
            params={"instId": symbol},
        )
        if resp.get("code") != "0":
            logger.warning(f"알고주문 조회 실패: {resp.get('msg', '')}")
            return

        algo_data = resp.get("data", [])
        if pos_side:
            algo_data = [x for x in algo_data if x.get("posSide") == pos_side]

        for i in range(0, len(algo_data), ALGO_ORDERS_CHUNK_SIZE):
            chunk = algo_data[i : i + ALGO_ORDERS_CHUNK_SIZE]
            cancel_list = []
            for algo in chunk:
                algo_id = algo.get("algoId")
                inst_id = algo.get("instId", symbol)
                if algo_id and inst_id:
                    cancel_list.append({"algoId": algo_id, "instId": inst_id})
            if cancel_list:
                cancel_resp = await exchange.fetch2(
                    path=API_ENDPOINTS["CANCEL_ALGO_ORDERS"],
                    api="private",
                    method="POST",
                    params={},
                    headers=None,
                    body=json.dumps({"data": cancel_list}),
                )
                if cancel_resp.get("code") != "0":
                    logger.warning(
                        f"알고주문 취소 실패: {cancel_resp.get('msg', '')}"
                    )
    except Exception as e:
        logger.error(f"알고주문 취소 중 오류: {str(e)}", exc_info=True)


async def cancel_reduce_only_orders_for_symbol(
    exchange, symbol: str, pos_side: Optional[str] = None
):
    """
    특정 심볼에 대한 reduceOnly 주문 취소 함수.
    pos_side가 주어지면 해당 pos_side의 주문만 취소합니다.
    """
    try:
        open_orders = await exchange.fetch_open_orders(symbol=symbol)
        if not open_orders:
            return

        orders_to_cancel = []
        for o in open_orders:
            info = o.get("info", {})
            ro_flag = str(info.get("reduceOnly", "false")).lower() == "true"
            this_pos_side = info.get("posSide", "net")
            if ro_flag and (not pos_side or this_pos_side == pos_side):
                orders_to_cancel.append(o)

        for i in range(0, len(orders_to_cancel), REGULAR_ORDERS_CHUNK_SIZE):
            chunk = orders_to_cancel[i : i + REGULAR_ORDERS_CHUNK_SIZE]
            cancel_list = []
            for od in chunk:
                ord_id = od["id"] or od["info"].get("ordId")
                inst_id = od["info"].get("instId", symbol)
                if ord_id and inst_id:
                    cancel_list.append({"ordId": ord_id, "instId": inst_id})
            if cancel_list:
                resp = await exchange.fetch2(
                    path=API_ENDPOINTS["CANCEL_BATCH_ORDERS"],
                    api="private",
                    method="POST",
                    params={},
                    headers=None,
                    body=json.dumps({"data": cancel_list}),
                )
                if resp.get("code") != "0":
                    logger.warning(
                        f"reduceOnly 주문 취소 실패: {resp.get('msg', '')}"
                    )
    except Exception as e:
        logger.error(f"reduceOnly 주문 취소 중 오류: {str(e)}", exc_info=True)


# ======================================================
# 클라이언트 생성 및 API 키 조회 함수
# ======================================================
async def get_user_api_keys(user_id: str) -> Dict[str, str]:
    """
    사용자 ID를 기반으로 Redis에서 OKX API 키를 조회합니다.
    """
    try:
        api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
        if not api_keys:
            raise HTTPException(status_code=404, detail="API keys not found in Redis")
        return api_keys
    except Exception as e:
        logger.error(f"4API 키 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching API keys: {str(e)}")


async def create_exchange_client(user_id: str) -> ccxt.okx:
    """
    사용자 API 키를 기반으로 새로운 OKX ccxt 클라이언트 인스턴스를 생성합니다.
    """
    api_keys = await get_user_api_keys(user_id)
    return ccxt.okx(
        {
            "apiKey": api_keys.get("api_key"),
            "secret": api_keys.get("api_secret"),
            "password": api_keys.get("passphrase"),
            "enableRateLimit": True,
            "options": {
                "defaultType": "swap",
                "adjustForTimeDifference": True,
            },
        }
    )


async def cancel_all_orders(
    client: Optional[ccxt.okx] = None, user_id: Optional[str] = None, symbol: Optional[str] = None, algo_type: Optional[str] = "trigger"
):
    """
    모든 주문(일반 주문 + 알고 주문)을 취소하는 유틸리티 함수입니다.
    
    Args:
        client: 기존 ccxt.okx 인스턴스 (없으면 user_id로 새 인스턴스 생성)
        user_id: 사용자 ID (client가 None인 경우 필수)
        symbol: 특정 심볼의 주문만 취소하려면 지정 (예: "BTC-USDT-SWAP")
    """
    created_local_client = False
    try:
        if client is None:
            if not user_id:
                raise ValueError("client 또는 user_id 중 하나는 필수입니다")
            client = await create_exchange_client(user_id)
            created_local_client = True

        # 1. 일반 주문 취소
        open_orders = await client.fetch_open_orders(symbol=symbol)
        if open_orders:
            for i in range(0, len(open_orders), REGULAR_ORDERS_CHUNK_SIZE):
                chunk = open_orders[i : i + REGULAR_ORDERS_CHUNK_SIZE]
                cancel_list = []
                for o in chunk:
                    ord_id = o["id"] or o["info"].get("ordId")
                    inst_id = o["info"].get("instId", symbol)
                    if ord_id and inst_id:
                        cancel_list.append({"ordId": ord_id, "instId": inst_id})
                if cancel_list:
                    params = {"instId": symbol, "instType": "SWAP", "ordType": algo_type}
                    # NOTE: 실제 일반 주문 취소 방식은 거래소 API에 따라 달라질 수 있습니다.
                    for _ in cancel_list:
                        resp = await client.privatePostTradeCancelAlgos(params=params)
                    if resp.get("code") != "0":
                        raise ValueError(f"일반 주문 일괄 취소 실패: {resp.get('msg', '')}")

        # 2. 알고 주문 취소
        open_algo_resp = await client.privateGetTradeOrdersAlgoPending(
            params={"instId": symbol} if symbol else {}
        )
        if open_algo_resp.get("code") != "0":
            raise ValueError(f"알고주문 조회 실패: {open_algo_resp.get('msg', '')}")

        algo_data = open_algo_resp.get("data", [])
        if algo_data:
            for i in range(0, len(algo_data), ALGO_ORDERS_CHUNK_SIZE):
                chunk = algo_data[i : i + ALGO_ORDERS_CHUNK_SIZE]
                cancel_list = []
                for algo_order in chunk:
                    algo_id = algo_order.get("algoId")
                    inst_id = algo_order.get("instId", symbol)
                    if algo_id and inst_id:
                        cancel_list.append({"algoId": algo_id, "instId": inst_id})
                if cancel_list:
                    cancel_resp = await client.privatePostTradeCancelAlgos(
                        params={},
                        body=json.dumps({"data": cancel_list}),
                    )
                    if cancel_resp.get("code") != "0":
                        raise ValueError(f"알고주문 취소 실패: {cancel_resp.get('msg', '')}")
    finally:
        if created_local_client and client is not None:
            await client.close()