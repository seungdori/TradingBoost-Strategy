#src/api/routes/order.py
from fastapi import APIRouter, HTTPException, Body, Path, Query
from typing import List, Optional, Dict, Any
from decimal import Decimal
from HYPERRSI.src.core.database import TradingCache
from HYPERRSI.src.api.exchange.models import (
    OrderRequest,
    OrderResponse,
    OrderStatus,
    OrderType,
    CancelOrdersResponse,
    OrderSide
)
from HYPERRSI.src.trading.cancel_trigger_okx import TriggerCancelClient
import asyncio
from shared.logging import get_logger
from HYPERRSI.src.core.logger import error_logger
from HYPERRSI.src.api.dependencies import get_exchange_context
from pydantic import BaseModel
import ccxt.async_support as ccxt
import traceback
import datetime as dt

import json
from HYPERRSI.telegram_message import send_telegram_message
from HYPERRSI.src.config import settings
import aiohttp

# shared 모듈에서 공통 함수 import
from shared.utils.type_converters import safe_float, safe_decimal
from shared.helpers.user_id_converter import get_identifier as get_okx_uid_identifier
from shared.errors.exceptions import (
    OrderNotFoundException,
    ValidationException,
    ExchangeUnavailableException,
    TradingException,
    ErrorCode
)

# order 모듈 내부 import
from .models import ClosePositionRequest, STATUS_MAPPING, EXAMPLE_RESPONSE
from .constants import ALGO_ORDERS_CHUNK_SIZE, REGULAR_ORDERS_CHUNK_SIZE, API_ENDPOINTS
from .parsers import parse_order_response, parse_algo_order_to_order_response
from .services import OrderService, AlgoOrderService, PositionService, StopLossService

# ORDER_BACKEND는 항상 자기 자신을 가리키므로 사용하지 않음
order_backend_client = None

async def init_user_position_data(user_id: str, symbol: str, side: str) -> None:
    dual_side_position_key = f"user:{user_id}:{symbol}:dual_side_position"
    position_state_key = f"user:{user_id}:position:{symbol}:position_state"
    tp_data_key = f"user:{user_id}:position:{symbol}:{side}:tp_data"
    ts_key = f"trailing:user:{user_id}:{symbol}:{side}"
    dual_side_position_key = f"user:{user_id}:{symbol}:dual_side_position"
    dca_count_key = f"user:{user_id}:position:{symbol}:{side}:dca_count"
    dca_levels_key = f"user:{user_id}:position:{symbol}:{side}:dca_levels"
    position_key = f"user:{user_id}:position:{symbol}:{side}"
    min_size_key = f"user:{user_id}:position:{symbol}:min_sustain_contract_size"
    #main_position_direction_key = f"user:{user_id}:position:{symbol}:main_position_direction"
    tp_state = f"user:{user_id}:position:{symbol}:{side}:tp_state"
    hedging_direction_key = f"user:{user_id}:position:{symbol}:hedging_direction"
    entry_fail_count_key = f"user:{user_id}:entry_fail_count"
    dual_side_count_key = f"user:{user_id}:{symbol}:dual_side_count"
    initial_size_key = f"user:{user_id}:position:{symbol}:{side}:initial_size"
    current_trade_key = f"user:{user_id}:current_trade:{symbol}:{side}"
    await redis_client.delete(position_state_key)
    await redis_client.delete(dual_side_position_key)
    await redis_client.delete(tp_data_key)
    await redis_client.delete(ts_key)
    await redis_client.delete(dca_count_key)
    await redis_client.delete(dca_levels_key)
    await redis_client.delete(position_key)
    await redis_client.delete(min_size_key)
    #await redis_client.delete(main_position_direction_key)
    await redis_client.delete(tp_state)
    await redis_client.delete(entry_fail_count_key)
    await redis_client.delete(hedging_direction_key)
    await redis_client.delete(dual_side_count_key)
    await redis_client.delete(current_trade_key)
    await redis_client.delete(initial_size_key)
    

status_mapping = {
    'closed': 'filled',
    'canceled': 'canceled',
    'rejected': 'rejected',
    'expired': 'expired',
    'open': 'open',
    'partial': 'partially_filled',
    'unknown': 'pending'
}
example_response = {
    "order_example": {
        "summary": "주문 조회 응답 예시",
        "value": {
            "order_id": "2205764866869846016",
            "client_order_id": "e847386590ce4dBCe66cc0a9f0cbbbd5",
            "symbol": "SOL-USDT-SWAP",
            "status": "filled",
            "side": "sell",
            "type": "market",
            "amount": "0.01",
            "filled_amount": "0.01",
            "remaining_amount": "0.0",
            "price": "240.7",
            "average_price": "240.7",
            "created_at": 1738239315673,
            "updated_at": 1738239315674,
            "pnl": "0.0343",
            "order_type": "market",
            "posSide": "net"
        }
    }
}


# Constants
ALGO_ORDERS_CHUNK_SIZE = 10
REGULAR_ORDERS_CHUNK_SIZE = 20
API_ENDPOINTS = {
    'ALGO_ORDERS_PENDING': 'trade/orders-algo-pending',
    'CANCEL_ALGO_ORDERS': 'trade/cancel-algos',
    'CANCEL_BATCH_ORDERS': 'trade/cancel-batch-orders',
}

logger = get_logger(__name__)

# Dynamic redis_client access
def _get_redis_client():
    """Get redis_client dynamically to avoid import-time errors"""
    from HYPERRSI.src.core import database as db_module
    return db_module.redis_client

redis_client = _get_redis_client()
router = APIRouter(prefix="/order", tags=["order"])

# get_identifier는 shared.helpers.user_id_converter에서 import했으므로 래퍼 함수 생성
async def get_identifier(user_id: str) -> str:
    """
    입력된 식별자가 텔레그램 ID인지 OKX UID인지 확인하고 적절한 OKX UID를 반환
    shared.helpers.user_id_converter를 사용하여 변환

    Args:
        user_id: 텔레그램 ID 또는 OKX UID

    Returns:
        str: OKX UID
    """
    okx_uid = await get_okx_uid_identifier(redis_client, user_id)
    if not okx_uid:
        raise HTTPException(status_code=404, detail=f"사용자 ID {user_id}에 대한 OKX UID를 찾을 수 없습니다")
    return okx_uid

async def get_user_api_keys(user_id: str) -> Dict[str, str]:
    """
    사용자 ID를 기반으로 Redis에서 OKX API 키를 가져오는 함수
    """
    try:
        # 텔레그램 ID인지 OKX UID인지 확인하고 변환
        okx_uid = await get_identifier(user_id)

        api_key_format = f"user:{okx_uid}:api:keys"
        result: Dict[str, Any] = await redis_client.hgetall(api_key_format)
        api_keys = {k: str(v) for k, v in result.items()}

        if not api_keys:
            raise HTTPException(status_code=404, detail="API keys not found in Redis")
        return api_keys
    except HTTPException:
        raise
    except Exception as e:
        error_logger.error(f"API 키 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching API keys: {str(e)}")

# safe_float는 shared.utils.type_converters에서 import하여 사용

async def handle_exchange_error(e: Exception) -> None:
    """Common error handling for exchange operations"""
    error_logger.error(f"Exchange operation failed: {str(e)}", exc_info=True)

    if isinstance(e, ccxt.NetworkError):
        raise HTTPException(status_code=503, detail="거래소 연결 오류가 발생했습니다")
    elif isinstance(e, ccxt.AuthenticationError):
        raise HTTPException(status_code=401, detail="인증 오류가 발생했습니다")
    elif isinstance(e, ccxt.BadRequest):
        # OKX의 주문 ID 관련 에러 처리
        if "51000" in str(e):
            raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다")
        # posSide 관련 에러 처리 추가
        elif "Parameter posSide error" in str(e):
            raise HTTPException(status_code=400, detail="포지션 방향(posSide) 파라미터 오류가 발생했습니다")
        raise HTTPException(status_code=400, detail=f"잘못된 요청: {str(e)}")
    elif isinstance(e, ccxt.ExchangeError):
        # 포지션이 없는 경우에 대한 처리
        if "You don't have any positions in this contract that can be closed" in str(e) or "51169" in str(e):
            raise HTTPException(status_code=404, detail="종료할 포지션이 없습니다")
        raise HTTPException(status_code=400, detail=f"거래소 오류: {str(e)}")
    else:
        raise HTTPException(status_code=500, detail="작업 중 오류가 발생했습니다")
    
    

@router.get("/list",
    response_model=List[OrderResponse],
    summary="열린 주문 목록 조회",
    description="사용자의 열린 주문 목록을 조회합니다. 심볼이 지정되면 해당 심볼의 주문만 조회합니다.",
    responses={
        200: {"description": "주문 목록 조회 성공"},
        401: {"description": "인증 오류"},
        503: {"description": "거래소 연결 오류"}
    })
async def get_open_orders(
    user_id: str = Query(
        ...,
        description="사용자 ID (텔레그램 ID 또는 OKX UID)",
        example="1709556958"
    ),
    symbol: Optional[str] = Query(
        None,
        description="조회할 심볼 (선택사항)",
        example="SOL-USDT-SWAP"
    )
) -> List[OrderResponse]:
    # ORDER_BACKEND 사용 여부 확인
    if order_backend_client:
        try:
            orders_data = await order_backend_client.get_open_orders(user_id, symbol)
            return orders_data
        except Exception as e:
            logger.error(f"Backend request failed, falling back to local: {e}")
    
    # 로컬 처리
    # user_id를 OKX UID로 변환
    okx_uid = await get_identifier(user_id)
    async with get_exchange_context(okx_uid) as exchange:
        try:
            # OKX API를 통해 열린 주문 조회
            response = await exchange.privateGetTradeOrdersPending({'instType': 'SWAP'})
            orders_data = response.get('data', [])
            
            # 심볼 필터링
            if symbol:
                symbol = symbol.upper().strip()  # 입력된 심볼 정규화
                orders_data = [
                    order for order in orders_data
                    if order['instId'].upper().strip() == symbol
                ]
                logger.debug(f"Filtered orders for symbol {symbol}: {len(orders_data)} orders found")

            result = []
            for order in orders_data:
                try:
                    # 로그에 표시된 실제 데이터 구조를 확인하여 정확한 필드명 사용
                    sz = safe_float(order['sz'])
                    acc_fill_sz = safe_float(order.get('accFillSz', 0.0))
                    result.append(OrderResponse(
                        order_id=order['ordId'],
                        client_order_id=order.get('clOrdId', ''),
                        symbol=order['instId'],
                        side=OrderSide.BUY if order['side'] == 'buy' else OrderSide.SELL,  # 문자열을 OrderSide Enum으로 변환
                        type=OrderType.MARKET if order['ordType'] == 'market' else OrderType.LIMIT,  # 문자열을 OrderType Enum으로 변환
                        order_type=order['ordType'],
                        amount=sz,
                        filled_amount=acc_fill_sz, #accFillSz일지, fillSz일지 확인
                        remaining_amount=sz - acc_fill_sz,
                        price=Decimal(str(safe_float(order.get('px')))) if order.get('px') else None,
                        average_price=Decimal(str(safe_float(order.get('avgPx')))) if order.get('avgPx') else None,
                        status=OrderStatus.OPEN if (order['state'] == 'live' or order['state'] == 'partially_filled' or order['state'] == 'open')
                               else OrderStatus.FILLED if order['state'] == 'filled'
                               else OrderStatus.CANCELED if order['state'] == 'canceled'
                               else OrderStatus.REJECTED if order['state'] == 'rejected'
                               else OrderStatus.EXPIRED if order['state'] == 'expired'
                               else OrderStatus.PENDING,  # status 값을 OrderStatus Enum으로 변환
                        posSide=order['posSide'],
                        pnl=safe_float(order.get('pnl', '0.0')),
                        created_at=int(order['cTime']) if order.get('cTime') else None,
                        updated_at=int(order['uTime']) if order.get('uTime') else (int(order['cTime']) if order.get('cTime') else None)
                    ))
                except Exception as e:
                    error_logger.error(f"Failed to process order: {str(e)}, Order data: {order}")
                    # 디버깅을 위해 에러가 발생한 주문 데이터의 구조를 더 자세히 기록
                    error_logger.error(f"주문 데이터 구조: client_order_id={order.get('clOrdId')}, order_type={order.get('ordType')}")
                    error_logger.error(f"주문 데이터 모든 필드: {', '.join([f'{k}={v}' for k, v in order.items()])}")
                    continue
            #print("RESULT : ", result)
            return result

        except Exception as e:
            error_logger.error(f"Failed to fetch open orders: {str(e)}", exc_info=True)
            await handle_exchange_error(e)
            
            
    
    


# ------------------------------------------------------
# ✅ (2) 새로운 라우트: 주문 상세 조회 (일반 or 알고주문)
# ------------------------------------------------------
@router.get(
    "/detail/{order_id}",
    response_model=OrderResponse,
    summary="주문 상세 조회 (일반 주문 + 알고주문)",
    description="주문 ID를 기준으로 주문 상세 정보를 조회합니다.",
    responses={
        200: {"description": "주문 조회 성공", "content": {"application/json": {"examples": example_response}}},
        404: {"description": "주문을 찾을 수 없음"},
        401: {"description": "인증 오류"},
        503: {"description": "거래소 연결 오류"},
        500: {"description": "기타 서버 오류"},
    }
)
async def get_order_detail(
    order_id: str = Path(..., description="조회할 주문의 ID(algoId 또는 ordId)"),
    user_id: str = Query("1709556958", description="사용자 ID (텔레그램 ID 또는 OKX UID)"),
    symbol: Optional[str] = Query("SOL-USDT-SWAP", description="심볼 (예: 'BTC-USDT-SWAP')"),
    is_algo: bool = Query(False, description="True면 알고주문으로 간주하여 조회"),
    algo_type: str = Query("trigger", description="알고주문 타입 (trigger 또는 conditional)")
) -> OrderResponse:
    """
    사용 예시:
    - 일반 주문 조회:  
      GET /order/detail/123456789?user_id=1709556958&symbol=BTC-USDT-SWAP  
    - 알고주문 조회:  
      GET /order/detail/987654321?user_id=1709556958&symbol=SOL-USDT-SWAP&is_algo=true  
    """
    # ORDER_BACKEND 사용 여부 확인
    if order_backend_client:
        try:
            order_data = await order_backend_client.get_order_detail(order_id, user_id, symbol, is_algo, algo_type)
            return order_data
        except Exception as e:
            logger.error(f"Backend request failed, falling back to local: {e}")
    
    # 로컬 처리
    # user_id를 OKX UID로 변환
    okx_uid = await get_identifier(user_id)
    async with get_exchange_context(okx_uid) as exchange:
        try:
            #logger.info(f"주문 상세 조회 시작 - order_id: {order_id}, symbol: {symbol}, is_algo: {is_algo}, algo_type: {algo_type}")
            
            # ----------------------------------------
            # (A) is_algo=true → 알고주문만 조회
            # ----------------------------------------
            if is_algo:
                try:
                    algo_data = await fetch_algo_order_by_id(exchange, order_id, symbol, algo_type)
                    #print("ALGO DATA : ", algo_data)
                    if not algo_data:
                        raise HTTPException(status_code=404, detail="알고주문(Trigger)에서 주문을 찾을 수 없습니다")
                    return parse_algo_order_to_order_response(algo_data, algo_type)
                except Exception as e:
                    error_logger.error(f"알고주문 조회 실패: {str(e)}")
                    raise HTTPException(status_code=404, detail=f"알고주문 조회 실패: {str(e)}")

            # ----------------------------------------
            # (B) is_algo=false → 일반 주문 먼저 조회
            # ----------------------------------------
            try:
                # 1) 열린 주문(open orders)에서 찾기
                open_orders = await exchange.fetch_open_orders(symbol=symbol) if symbol else await exchange.fetch_open_orders()
                logger.info(f"열린 주문 조회 결과: {len(open_orders)}개")

                # 디버깅을 위한 로그 추가

                for order in open_orders:
                    current_id = str(order.get('id'))
                    current_ord_id = str(order.get('info', {}).get('ordId'))
  
                # ordId도 함께 확인
                order_data = next((order for order in open_orders 
                                 if str(order.get('id')).strip() == str(order_id).strip() or 
                                    str(order.get('info', {}).get('ordId')).strip() == str(order_id).strip()), None)
            
                #print("ORDER DATA : ", order_data)
                if not order_data and symbol:
                    # 2) 열린 주문에 없다면, fetch_order로 닫힌 주문(체결/취소) 조회
                    try:
                        logger.info(f"닫힌 주문 조회 시도 - order_id: {order_id}, symbol: {symbol}")
                        order_data = await exchange.fetch_order(order_id, symbol)
                        
                        if is_algo:
                            print("FETCH ORDER : ", order_id, symbol)
                            print("")
                            order_data = await exchange.fetch_order(order_id, symbol, params={'stop': True, 'ordType': 'trigger'})
                            print("order_data : ", order_data)
                        await asyncio.sleep(1)
                        print(order_data)
                        pnl = order_data.get("pnl", 0)
                        print("PNL :", pnl)
                        logger.info("닫힌 주문 조회 성공")
                    except Exception as e:
                        #traceback.print_exc()
                        logger.warning(f"닫힌 주문 조회 실패: {str(e)}")
                        order_data = None

                if order_data:
                    #logger.debug("주문 데이터를 OrderResponse로 변환")
                    return OrderResponse(
                        order_id=order_data["id"],
                        client_order_id=order_data.get("clientOrderId"),  # 추가
                        symbol=order_data["symbol"],
                        side=OrderSide.BUY if order_data["side"] == "buy" else OrderSide.SELL,  # Enum으로 변경
                        type=OrderType.MARKET if order_data["type"] == "market" else OrderType.LIMIT,  # Enum으로 변경
                        amount=safe_float(order_data.get("amount", 0.0)),
                        filled_amount=safe_float(order_data.get('filled', 0.0)),
                        remaining_amount=safe_float(order_data.get("remaining", 0.0)),
                        price=Decimal(str(safe_float(order_data.get('price')))) if order_data.get('price') else None,
                        average_price=Decimal(str(safe_float(order_data.get('average')))) if order_data.get('average') else None,
                        status=OrderStatus.FILLED if order_data["status"] == "closed"
                               else OrderStatus.CANCELED if order_data["status"] == "canceled"
                               else OrderStatus.OPEN,  # Enum으로 변경
                        created_at=int(order_data["timestamp"]) if order_data.get("timestamp") else None,
                        updated_at=int(order_data.get("lastUpdateTimestamp", order_data["timestamp"])) if order_data.get("lastUpdateTimestamp") or order_data.get("timestamp") else None,
                        pnl=safe_float(order_data.get('pnl', 0.0)),
                        order_type=order_data.get("type", "unknown"),
                        posSide=order_data.get("info", {}).get("posSide", "unknown")
                    )

                # 3) 일반 주문에서 찾지 못한 경우 → 알고주문(Trigger) 재조회
                logger.debug("일반 주문에서 찾지 못해 알고주문 조회 시도")
                algo_data = await fetch_algo_order_by_id(exchange, order_id, symbol, algo_type)
                if algo_data:
                    return parse_algo_order_to_order_response(algo_data, algo_type)

                #4) 여전히 찾지 못함 → 404
                raise HTTPException(status_code=404, detail="해당 주문을 찾을 수 없습니다")

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"주문 조회 중 예외 발생: {str(e)}")
                if "Not authenticated" in str(e):
                    raise HTTPException(status_code=401, detail="인증 오류가 발생했습니다")
                elif "Network" in str(e):
                    raise HTTPException(status_code=503, detail="거래소 연결 오류가 발생했습니다")
                else:
                    raise HTTPException(status_code=500, detail=f"주문 조회 중 오류 발생: {str(e)}")

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"주문 상세 조회 실패: {str(e)}")
            raise HTTPException(status_code=500, detail="주문 조회 중 오류가 발생했습니다")



@router.post("/",
    response_model=OrderResponse,
    summary="새로운 주문 생성",
    description="거래소에 새로운 주문을 생성합니다.",
    responses={
        200: {"description": "주문 생성 성공"},
        400: {"description": "주문 생성 실패"},
        401: {"description": "인증 오류"},
        503: {"description": "거래소 연결 오류"}
    })
async def create_order(
    order: OrderRequest = Body(..., description="주문 생성을 위한 요청 데이터"),
    user_id: str = Query(..., description="사용자 ID (텔레그램 ID 또는 OKX UID)")
) -> OrderResponse:
    """
    ✨ REFACTORED: Using OrderService

    주문 생성 엔드포인트 - 서비스 레이어를 사용하여 비즈니스 로직 처리
    """
    # ORDER_BACKEND 사용 여부 확인
    if order_backend_client:
        try:
            order_dict = order.model_dump()  # .dict() deprecated, use .model_dump()
            response_data = await order_backend_client.create_order(order_dict, user_id)
            return response_data
        except Exception as e:
            logger.error(f"Backend request failed, falling back to local: {e}")

    # 로컬 처리 - OrderService 사용
    okx_uid = await get_identifier(user_id)
    async with get_exchange_context(okx_uid) as exchange:
        # 레버리지 설정이 있는 경우 적용
        if order.leverage:
            try:
                await exchange.privatePostAccountSetLeverage({
                    'instId': order.symbol,
                    'lever': order.leverage,
                })
            except Exception as e:
                logger.warning(f"Failed to set leverage: {str(e)}")

        # OrderService를 사용하여 주문 생성
        return await OrderService.create_order(
            exchange=exchange,
            symbol=order.symbol,
            side=order.side,
            order_type=order.type,
            amount=order.amount,
            price=order.price
        )



@router.post("/position/close/{symbol}",
    response_model=OrderResponse,
    summary="포지션 종료",
    description="특정 심볼의 포지션을 종료합니다.",
    responses={
        200: {"description": "포지션 종료 성공"},
        404: {"description": "포지션을 찾을 수 없음"},
        400: {"description": "포지션 종료 실패"},
        401: {"description": "인증 오류"},
        503: {"description": "거래소 연결 오류"}
    })
async def close_position(
    symbol: str = Path(..., description="종료할 포지션의 심볼"),
    close_request: ClosePositionRequest = Body(..., description="포지션 종료 요청 데이터"),
    user_id: str = Query(..., description="사용자 ID (텔레그램 ID 또는 OKX UID)"),
    side: Optional[str] = Query(None, description="종료할 포지션 방향 (long/short)")
) -> OrderResponse:
    """
    ✨ REFACTORED: Using PositionService

    포지션 종료 엔드포인트 - 서비스 레이어를 사용하여 비즈니스 로직 처리
    """
    # ORDER_BACKEND 사용 여부 확인 (backward compatibility)
    if order_backend_client:
        try:
            close_data = close_request.dict()
            response_data = await order_backend_client.close_position(symbol, close_data, user_id, side)
            return response_data
        except Exception as e:
            logger.error(f"Backend request failed, falling back to local: {e}")

    # user_id를 OKX UID로 변환
    okx_uid = await get_identifier(user_id)

    # PositionService를 사용하여 포지션 종료 처리
    async with get_exchange_context(okx_uid) as exchange:
        return await PositionService.close_position(
            exchange=exchange,
            user_id=okx_uid,
            symbol=symbol,
            close_type=close_request.close_type,
            price=close_request.price,
            close_percent=close_request.close_percent,
            redis_client=redis_client
        )



# ------------------------------------------------------
# ✅ (1) 알고주문 조회를 위한 헬퍼 함수
# ------------------------------------------------------
async def fetch_algo_order_by_id(exchange_or_wrapper: Any, order_id: str, symbol: Optional[str] = None, algo_type : Optional[str] = "trigger") -> Optional[Dict[str, Any]]:
    
    """
    OKX의 알고리즘 주문(트리거 주문) 조회
    Args:
        exchange_or_wrapper: ccxt.okx 인스턴스 또는 OrderWrapper
        order_id: 알고리즘 주문 ID (algoId)
        symbol: 선택적 심볼
    Returns:
        주문 정보 dict 또는 None
    """
    params = {"instId": symbol, "ordType": algo_type} if symbol else {"ordType": algo_type}

    try:
        # OrderWrapper 또는 직접 exchange 사용
        if hasattr(exchange_or_wrapper, 'exchange'):
            exchange = exchange_or_wrapper.exchange
        else:
            exchange = exchange_or_wrapper
            
        # 활성 주문 조회
        pending_resp = await exchange.privateGetTradeOrdersAlgoPending(
            params=params
        )
        
        if pending_resp.get("code") == "0":
            data_list: List[Dict[str, Any]] = pending_resp.get("data", [])
            if found := next((x for x in data_list if x.get("algoId") == order_id), None):
                return found

        # 히스토리 조회
        history_resp = await exchange.privateGetTradeOrdersAlgoHistory(
            params=params
        )

        if history_resp.get("code") == "0":
            data_list = history_resp.get("data", [])
            if found := next((x for x in data_list if x.get("algoId") == order_id), None):
                return found
                
    except Exception as e:
        traceback.print_exc()
        if "Not authenticated" in str(e):
            raise HTTPException(status_code=401, detail="Authentication error")
        elif "Network" in str(e):
            raise HTTPException(status_code=503, detail="Exchange connection error")
        logger.error(f"Error fetching algo order: {str(e)}")
        
    return None

# Order cancellation utilities
async def cancel_algo_orders_for_symbol(
    exchange: Any,
    symbol: str,
    pos_side: Optional[str] = None
) -> None:
    """
    알고주문(SL 등) 취소 유틸리티 함수
    - pos_side가 지정되면 해당 포지션 사이드의 주문만 취소 (Hedge 모드)
    - pos_side가 None이면 모든 알고주문 취소 (One-way 모드)
    """
    try:
        resp = await exchange.fetch2(
            path=API_ENDPOINTS['ALGO_ORDERS_PENDING'],
            api="private",
            method="GET",
            params={"instId": symbol}
        )
        code = resp.get("code")
        if code != "0":
            msg = resp.get("msg", "")
            logger.warning(f"알고주문 조회 실패: {msg}")
            return

        algo_data = resp.get("data", [])
        if pos_side:
            algo_data = [x for x in algo_data if x.get('posSide') == pos_side]

        for i in range(0, len(algo_data), ALGO_ORDERS_CHUNK_SIZE):
            chunk = algo_data[i:i+ALGO_ORDERS_CHUNK_SIZE]
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
                if c_code != "0":
                    c_msg = cancel_resp.get("msg", "")
                    logger.warning(f"알고주문 취소 실패: {c_msg}")
    except Exception as e:
        logger.error(f"알고주문 취소 중 오류: {str(e)}")

async def cancel_reduce_only_orders_for_symbol(
    exchange: Any,
    symbol: str,
    pos_side: Optional[str] = None
) -> None:
    """
    reduceOnly 주문(TP 등) 취소 유틸리티 함수
    - pos_side가 지정되면 해당 포지션 사이드의 주문만 취소 (Hedge 모드)
    - pos_side가 None이면 모든 reduceOnly 주문 취소 (One-way 모드)
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
            chunk = orders_to_cancel[i:i+REGULAR_ORDERS_CHUNK_SIZE]
            cancel_list = []
            for od in chunk:
                ord_id = od["id"] or od["info"].get("ordId")
                inst_id = od["info"].get("instId", symbol)
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
                if code != "0":
                    msg = resp.get("msg", "")
                    logger.warning(f"reduceOnly 주문 취소 실패: {msg}")
    except Exception as e:
        logger.error(f"reduceOnly 주문 취소 중 오류: {str(e)}")

async def create_exchange_client(user_id: str) -> ccxt.okx:
    """Create a new OKX exchange client instance"""
    api_keys = await get_user_api_keys(user_id)
    return ccxt.okx({
        "apiKey": api_keys.get("api_key"),
        "secret": api_keys.get("api_secret"),
        "password": api_keys.get("passphrase"),
        "enableRateLimit": True,
        "options": {
            "defaultType": "swap",
            "adjustForTimeDifference": True
        }
    })

# parse_order_response는 parsers.py에서 import하여 사용
# 아래 함수는 중복으로 제거됨

def _legacy_parse_order_response(order_data: Dict[str, Any]) -> OrderResponse:
    """
    DEPRECATED: Use parse_order_response from parsers module instead.
    This function is kept temporarily for backward compatibility.
    """
    amt = safe_float(order_data["amount"])
    filled = safe_float(order_data["filled"])
    return OrderResponse(
        order_id=order_data["id"],
        client_order_id=order_data.get("clientOrderId", ""),
        symbol=order_data["symbol"],
        side=OrderSide.BUY if order_data["side"] == "buy" else OrderSide.SELL,
        type=OrderType.MARKET if order_data["type"] == "market" else OrderType.LIMIT,
        order_type=order_data["type"],
        amount=amt,
        filled_amount=filled,
        remaining_amount=amt - filled,
        price=Decimal(str(safe_float(order_data["price"]))) if order_data.get("price") else None,
        average_price=Decimal(str(safe_float(order_data["average"]))) if order_data.get("average") else None,
        status=OrderStatus[order_data["status"].upper()] if order_data.get("status") else OrderStatus.PENDING,
        posSide=order_data.get("info", {}).get("posSide", "net"),
        pnl=safe_float(order_data.get("info", {}).get("pnl", 0)),
        created_at=int(order_data["timestamp"]) if order_data.get("timestamp") else None,
        updated_at=int(order_data["lastUpdateTimestamp"]) if order_data.get("lastUpdateTimestamp") else (int(order_data["timestamp"]) if order_data.get("timestamp") else None)
    )

#==============================================
# 스탑로스 주문 업데이트
#==============================================

async def update_stop_loss_order_redis(
    user_id: str,
    symbol: str,
    side: str,
    new_sl_price: float,
) -> Dict[str, Any]:
    position_key = f"user:{user_id}:position:{symbol}:{side}"
    await redis_client.hset(position_key, "sl_price", new_sl_price)
    await redis_client.hset(position_key, "get_sl", "false")

    return {
        "success": True,
        "symbol": symbol,
        "new_sl_price": new_sl_price,
    }
    
    
@router.post("/position/sl",
    response_model=dict,
    summary="스탑로스 주문 업데이트",
    description="포지션의 스탑로스 가격을 업데이트합니다.",
    responses={
        200: {
            "description": "스탑로스 업데이트 성공",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "symbol": "XRP-USDT-SWAP",
                        "new_sl_price": 1.95,
                        "order_id": "12345"
                    }
                }
            }
        },
        400: {"description": "스탑로스 업데이트 실패"},
        401: {"description": "인증 오류"},
        404: {"description": "포지션을 찾을 수 없음"},
        503: {"description": "거래소 연결 오류"}
    })
async def update_stop_loss_order(
    symbol: str = Query("BTC-USDT-SWAP", description="거래 심볼 (예: XRP-USDT-SWAP)"),
    side: str = Query("sell", description="포지션의 방향 (long 또는 short)"),
    order_side: str = Query("sell", description="주문의 방향 (buy 또는 sell)"),
    contracts_amount: float = Query(..., description="포지션 크기"),
    new_sl_price: float = Query(..., description="새로운 스탑로스 가격"),
    position_qty: Optional[float] = Query(None, description="포지션 수량"),
    user_id: str = Query("1709556958", description="사용자 ID"),
    algo_type: str = Query("trigger", description="알고주문 타입 (trigger 또는 conditional)"),
    is_hedge: bool = Query(False, description="헷지 모드 여부"),
    order_type: str = Query("sl", description="오더 타입(break_even, sl)")
) -> Dict[str, Any]:
    """
    ✨ REFACTORED: Using StopLossService

    스탑로스 주문 업데이트 엔드포인트 - 서비스 레이어를 사용하여 비즈니스 로직 처리
    Note: 일부 커스텀 로직(invalid SL price 처리, monitor key tracking)은
    비즈니스 요구사항에 따라 엔드포인트에서 직접 처리
    """
    # ORDER_BACKEND 사용 여부 확인 (backward compatibility)
    if order_backend_client:
        try:
            params = {
                "symbol": symbol,
                "side": side,
                "order_side": order_side,
                "contracts_amount": contracts_amount,
                "new_sl_price": new_sl_price,
                "position_qty": position_qty,
                "user_id": user_id,
                "algo_type": algo_type,
                "is_hedge": is_hedge,
                "order_type": order_type
            }
            response_data = await order_backend_client.update_stop_loss(params)
            return response_data
        except Exception as e:
            logger.error(f"Backend request failed, falling back to local: {e}")

    # Side 파라미터 정규화
    side_normalized = "buy" if side in ["long", "buy"] else "sell"
    order_side_normalized = "buy" if order_side in ["long", "buy"] else "sell"

    # 입력 검증
    if order_side_normalized == side_normalized:
        pos_type = "롱" if side_normalized == "buy" else "숏"
        sl_side = "sell" if side_normalized == "buy" else "buy"
        raise HTTPException(
            status_code=400,
            detail=f"{pos_type} 포지션의 SL은 {sl_side}여야 합니다"
        )

    # user_id를 OKX UID로 변환
    okx_uid = await get_identifier(user_id)

    async with get_exchange_context(okx_uid) as exchange:
        try:
            # 1. 현재 포지션 조회
            positions = await exchange.private_get_account_positions({'instType': 'SWAP'})
            position = next(
                (pos for pos in positions.get('data', [])
                 if pos['instId'] == symbol and float(pos.get('pos', 0)) != 0),
                None
            )

            if not position:
                logger.info(f"No active position found for {symbol}, skipping SL update")
                await TradingCache.remove_position(okx_uid, symbol, order_side_normalized)
                return {"success": False, "message": "활성화 된 포지션을 찾을 수 없습니다"}

            # 2. 현재가 확인
            ticker = await exchange.fetch_ticker(symbol)
            current_price = ticker['last']
            position_qty = float(position.get('pos', 0))
            pos_side = "long" if position.get('posSide') == 'long' else "short"

            # 3. SL 가격 유효성 검사 - invalid한 경우 시장가로 청산
            side_for_close = "long" if side_normalized == "buy" else "short"
            should_close_at_market = (
                (side_normalized == "buy" and new_sl_price >= current_price) or
                (side_normalized == "sell" and new_sl_price <= current_price)
            )

            if should_close_at_market:
                # Invalid SL price - close position at market
                await update_stop_loss_order_redis(
                    user_id=okx_uid,
                    symbol=symbol,
                    side=side_for_close,
                    new_sl_price=new_sl_price
                )

                try:
                    close_request = ClosePositionRequest(
                        close_type="market",
                        price=current_price,
                        close_percent=100,
                    )
                    await close_position(
                        symbol=symbol,
                        close_request=close_request,
                        user_id=okx_uid,
                        side=side_for_close
                    )
                    # Position cleanup after successful close
                    await PositionService.init_position_data(
                        user_id=okx_uid,
                        symbol=symbol,
                        side=side_for_close,
                        redis_client=redis_client
                    )
                except Exception as e:
                    if "활성화된 포지션을 찾을 수 없습니다" not in str(e) and "no_position" not in str(e):
                        logger.error(f"Failed to close position: {str(e)}")
                        await send_telegram_message(
                            f"[{okx_uid}] 주문 생성 중 오류 발생: {str(e)}\n"
                            f"BreakEven의 변경된 SL이 현재 시장가보다 {'높습니다' if side_normalized == 'buy' else '낮습니다'}.\n"
                            f"{'롱' if side_normalized == 'buy' else '숏'}포지션을 시장가 종료합니다.",
                            okx_uid=1709556958,
                            debug=True
                        )

                return {
                    "success": True,
                    "symbol": symbol,
                    "message": "Invalid SL price - position closed at market"
                }

            # 4. Get existing SL order from Redis
            old_sl_data = await StopLossService.get_stop_loss_from_redis(
                redis_client=redis_client,
                user_id=okx_uid,
                symbol=symbol,
                side=side_for_close
            )

            # 5. Cancel existing algo orders
            try:
                await cancel_algo_orders(
                    symbol=symbol,
                    user_id=okx_uid,
                    side=pos_side,
                    algo_type=algo_type if algo_type == "trigger" else "conditional"
                )
            except Exception as e:
                logger.warning(f"기존 SL algo 주문 취소 중 오류: {str(e)}")

            # 6. Create new SL order using StopLossService
            try:
                new_order = await StopLossService.create_stop_loss_order(
                    exchange=exchange,
                    symbol=symbol,
                    side=order_side_normalized,
                    amount=position_qty,
                    trigger_price=new_sl_price,
                    order_price=new_sl_price,
                    pos_side=pos_side,
                    reduce_only=True
                )

                # 7. Update Redis with new SL data
                await StopLossService.update_stop_loss_redis(
                    redis_client=redis_client,
                    user_id=okx_uid,
                    symbol=symbol,
                    side=side_for_close,
                    trigger_price=new_sl_price,
                    order_id=new_order.order_id,
                    entry_price=float(position.get('avgPx', 0))
                )

                # 8. Update monitor key for order tracking
                now = dt.datetime.now()
                kr_time = now + dt.timedelta(hours=9)
                monitor_key = f"monitor:user:{okx_uid}:{symbol}:order:{new_order.order_id}"
                monitor_data = {
                    "status": "open",
                    "price": str(new_sl_price),
                    "position_side": side_for_close,
                    "contracts_amount": str(contracts_amount),
                    "order_type": order_type,
                    "position_qty": str(position_qty),
                    "ordertime": str(int(now.timestamp())),
                    "filled_contracts_amount": "0",
                    "remain_contracts_amount": str(contracts_amount),
                    "last_updated_time": str(int(now.timestamp())),
                    "last_updated_time_kr": kr_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "is_hedge": str(is_hedge).lower()
                }
                await redis_client.hset(monitor_key, mapping=monitor_data)

                return {
                    "success": True,
                    "symbol": symbol,
                    "new_sl_price": new_sl_price,
                    "order_id": new_order.order_id
                }

            except Exception as e:
                logger.error(f"Failed to create stop loss order: {str(e)}")

                # Fallback: Update Redis with SL price only
                await update_stop_loss_order_redis(
                    user_id=okx_uid,
                    symbol=symbol,
                    side=side_for_close,
                    new_sl_price=new_sl_price
                )

                error_message = str(e)
                if "Order timed out" in error_message or "51149" in error_message:
                    await send_telegram_message(
                        f"[{okx_uid}] 스탑로스 주문 생성 중 타임아웃 발생. "
                        f"시스템이 자동으로 SL 가격을 {new_sl_price}로 설정했지만 실제 주문은 생성되지 않았습니다.",
                        okx_uid=1709556958,
                        debug=True
                    )
                else:
                    await send_telegram_message(
                        f"[{okx_uid}] 스탑로스 주문 생성 중 오류 발생: {str(e)}",
                        okx_uid=1709556958,
                        debug=True
                    )

                return {
                    "success": False,
                    "symbol": symbol,
                    "new_sl_price": new_sl_price,
                    "message": f"스탑로스 주문 생성 실패: {str(e)}",
                    "error": str(e)
                }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to update stop loss: {str(e)}", exc_info=True)
            await handle_exchange_error(e)


@router.delete("/{order_id}",
    response_model=dict,
    summary="주문 취소",
    description="진행 중인 주문을 취소합니다.",
    responses={
        200: {"description": "주문 취소 성공"},
        404: {"description": "주문을 찾을 수 없음"},
        400: {"description": "주문 취소 실패"},
        401: {"description": "인증 오류"},
        503: {"description": "거래소 연결 오류"}
    })
async def cancel_order(
    order_id: str = Path(..., description="취소할 주문의 고유 ID"),
    user_id: str = Query(..., description="사용자 ID"),
    symbol: str = Query(None, description="주문의 심볼")
) -> Dict[str, Any]:
    """
    ✨ REFACTORED: Using OrderService

    주문 취소 엔드포인트 - 서비스 레이어를 사용하여 주문 취소 처리
    """
    # user_id를 OKX UID로 변환
    okx_uid = await get_identifier(user_id)

    async with get_exchange_context(okx_uid) as exchange:
        # OrderService를 사용하여 주문 취소
        success = await OrderService.cancel_order(
            exchange=exchange,
            order_id=order_id,
            symbol=symbol
        )

        return {
            "success": success,
            "order_id": order_id,
            "status": "canceled" if success else "failed"
        }

            
            
            
@router.delete(
    "/cancel-all/{symbol}",
    response_model=CancelOrdersResponse,
    summary="모든 주문 취소",
    description="""
    지정된 거래쌍의 미체결 주문을 모두 취소합니다.

    ## 기능
    - 일반 주문과 트리거 주문(조건부 주문) 모두 취소
    - 선택적으로 매수/매도 방향 필터링 가능
    - Redis에 취소된 주문 정보 저장

    ## 파라미터 설명
    - **symbol**: 거래쌍 심볼 (예: 'BTC/USDT', 'ETH/USDT')
    - **user_id**: 사용자 식별자
    - **side**: 주문 방향 (선택사항: buy/매수 또는 sell/매도)

    ## 응답
    - 성공시: 취소된 주문 수와 주문 ID 목록 반환
    - 실패시: 에러 메시지와 함께 500 에러 반환

    ## 예시
    ```
    DELETE /order/cancel-all/BTC-USDT?user_id=1709556958&side=buy
    ```
    """,
    responses={
        200: {
            "description": "주문 취소 성공",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Successfully cancelled 2 orders",
                        "cancelled_orders_count": 2,
                        "details": {
                            "cancelled_orders": ["123456789", "987654321"]
                        }
                    }
                }
            }
        },
        500: {
            "description": "주문 취소 실패",
            "content": {
                "application/json": {
                    "example": {
                        "success": False,
                        "message": "Failed to cancel orders: Connection error",
                        "cancelled_orders_count": 0
                    }
                }
            }
        }
    }
)
async def cancel_all_orders(
    symbol: str = Path(
        ...,
        description="거래쌍 심볼 (예: 'BTC-USDT-SWAP', 'ETH-USDT-SWAP')"
    ),
    user_id: str = Query(
        ...,
        description="사용자 ID"
    ),
    side: Optional[OrderSide] = Query(
        None,
        description="포지션 방향 (선택사항: buy/long 또는 sell/short)"
    )
) -> CancelOrdersResponse:
    """
    ✨ REFACTORED: Using OrderService and AlgoOrderService

    모든 주문 취소 엔드포인트 - 서비스 레이어를 사용하여 일반 주문과 알고 주문 취소 처리
    """
    # ORDER_BACKEND 사용 여부 확인 (backward compatibility)
    if order_backend_client:
        try:
            response_data = await order_backend_client.cancel_all_orders(symbol, str(user_id), side)
            return response_data
        except Exception as e:
            logger.error(f"Backend request failed, falling back to local: {e}")

    # Side 파라미터 정규화
    side_str: Optional[str] = None
    order_side_for_filter: Optional[str] = None
    pos_side_for_algo: Optional[str] = None

    if side:
        if side == OrderSide.BUY:
            side_str = "buy"
            order_side_for_filter = "sell"  # Regular orders to cancel for buy position
            pos_side_for_algo = "long"  # Algo orders position side
        elif side == OrderSide.SELL:
            side_str = "sell"
            order_side_for_filter = "buy"  # Regular orders to cancel for sell position
            pos_side_for_algo = "short"  # Algo orders position side

    # user_id를 OKX UID로 변환
    okx_uid = await get_identifier(user_id)

    async with get_exchange_context(okx_uid) as exchange:
        try:
            # 1. Fetch open orders
            open_orders = await exchange.fetch_open_orders(symbol)
            logger.debug(f"Found {len(open_orders)} open orders for {symbol}")

            # Filter by side if specified
            if order_side_for_filter:
                open_orders = [
                    order for order in open_orders
                    if order['side'].lower() == order_side_for_filter.lower()
                ]
                logger.debug(f"Filtered to {len(open_orders)} orders for side {order_side_for_filter}")

            initial_orders_count = len(open_orders)

            # 2. Cancel algo/trigger orders using AlgoOrderService
            try:
                await AlgoOrderService.cancel_algo_orders_for_symbol(
                    exchange=exchange,
                    symbol=symbol,
                    pos_side=pos_side_for_algo
                )
                logger.info(f"Successfully cancelled algo orders for {symbol}")
            except Exception as e:
                logger.error(f"Failed to cancel algo orders: {str(e)}")
                # Continue execution even if algo order cancellation fails

            # 3. Cancel regular orders using OrderService
            if open_orders:
                try:
                    await OrderService.cancel_all_orders(
                        exchange=exchange,
                        symbol=symbol,
                        side=order_side_for_filter
                    )
                    logger.info(f"Successfully cancelled {len(open_orders)} regular orders")

                    # 4. Update Redis with cancelled orders
                    closed_orders_key = f"user:{okx_uid}:closed_orders"
                    open_orders_key = f"user:{okx_uid}:open_orders"

                    async with redis_client.pipeline() as pipe:
                        # Save cancelled orders
                        for order in open_orders:
                            await pipe.rpush(closed_orders_key, json.dumps(order))

                        # Update open orders list
                        if order_side_for_filter:
                            # Remove only specific side orders
                            current_orders = await redis_client.lrange(open_orders_key, 0, -1)
                            await pipe.delete(open_orders_key)
                            for order_str in current_orders:
                                order_data = json.loads(order_str)
                                if order_data['side'].lower() != order_side_for_filter.lower():
                                    await pipe.rpush(open_orders_key, order_str)
                        else:
                            # Remove all orders
                            await pipe.delete(open_orders_key)

                        await pipe.execute()

                except Exception as e:
                    logger.error(f"Failed to cancel regular orders: {str(e)}")
                    raise

            return CancelOrdersResponse(
                success=True,
                message=f"Successfully cancelled {initial_orders_count} orders",
                canceled_orders=[order['id'] for order in open_orders] if open_orders else None,
                failed_orders=None
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to cancel all orders: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=CancelOrdersResponse(
                    success=False,
                    message=f"Failed to cancel orders: {str(e)}",
                    canceled_orders=None,
                    failed_orders=None
                ).dict()
            )
            
            
@router.delete(
"/algo-orders/{symbol}",
    response_model=dict,
    summary="알고리즘 주문 취소(최신로직)",
    description="""
    알고리즘 주문(트리거 주문 등)을 취소합니다.

    **기능**
    - 특정 심볼의 모든 알고리즘 주문 취소
    - 특정 주문 ID(algoId)만 선택 취소도 가능(미구현)

    **응답**
    - 성공 시: 취소된 주문 정보 반환
    - 실패 시: 적절한 에러 메시지 반환
    """,
    responses={
        200: {
            "description": "주문 취소 성공",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "알고리즘 주문 취소 완료",
                        "data": {
                            "canceled_orders": ["12345", "67890"]
                        }
                    }
                }
            }
        },
        400: {"description": "잘못된 요청"},
        401: {"description": "인증 오류"},
        500: {"description": "서버 오류"}
    }
)
async def cancel_algo_orders(
    symbol: str = Path(
        ...,  # ... 은 required(필수값)를 의미
        description="취소 대상 심볼"
    ),
    user_id: str = Query("1709556958", description="사용자 ID (API 키 조회에 사용)"),
    side: str = Query(None, description="포지션의 방향(buy/sell)"),
    algo_type: str = Query("trigger", description="알고리즘 주문 타입(trigger/conditional)")
) -> Dict[str, Any]:
    """
    예: DELETE /order/algo-orders/SOL-USDT-SWAP?user_id=1709556958
    """

    try:
        api_keys = await get_user_api_keys(user_id)
        client = TriggerCancelClient(
            api_key=api_keys['api_key'],
            secret_key=api_keys['api_secret'],
            passphrase=api_keys['passphrase']
        )

        await client.cancel_all_trigger_orders(inst_id =  symbol, side = side if side else "", algo_type = algo_type, user_id = user_id)

        return {
            "status": "success",
            "message": f"{symbol} 심볼에 대한 모든 알고리즘 주문 취소 완료"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    
       
@router.get("/algo/{order_id}",
    response_model=Dict[str, Any],
    summary="알고리즘 주문 상세 조회",
    description="""
    OKX의 알고리즘 주문(트리거 주문 등) 정보를 조회합니다.

    **주요 기능**
    - 활성 주문과 히스토리 주문 모두 조회
    - 주문 상태 자동 매핑
    - 상세 주문 정보 제공

    **응답 상태값**
    - open: 활성 주문
    - filled: 체결 완료
    - rejected: 거부됨
    - canceled: 취소됨
    - partially_filled: 부분 체결
    - closed: 종료됨
    """,
    responses={
        200: {
            "description": "주문 조회 성공",
            "content": {
                "application/json": {
                    "example": {
                        "status": "filled",
                        "info": {
                            "algoId": "12345",
                            "instId": "BTC-USDT-SWAP",
                            "ordType": "trigger",
                            "state": "effective"
                        },
                        "data": [],
                        "state": "effective"
                    }
                }
            }
        },
        404: {"description": "주문을 찾을 수 없음"},
        400: {"description": "잘못된 요청"},
        500: {"description": "서버 오류"}
    }
)
async def get_algo_order_info(
    order_id: str = Path(..., description="알고리즘 주문 ID", example="123456789"),
    symbol: str = Query(..., description="거래 심볼", example="BTC-USDT-SWAP"),
    user_id: str = Query(..., description="사용자 ID", example="1709556958"),
    algo_type: str = Query(..., description="알고리즘 주문 타입", example="trigger")
) -> Dict[str, Any]:
    """
    알고리즘 주문 정보를 조회하는 엔드포인트
    """
    # ORDER_BACKEND 사용 여부 확인
    if order_backend_client:
        try:
            response_data = await order_backend_client.get_algo_order_info(order_id, symbol, user_id, algo_type)
            return response_data
        except Exception as e:
            logger.error(f"Backend request failed, falling back to local: {e}")
    
    # 로컬 처리
    async with get_exchange_context(user_id) as exchange:
        try:
            # 활성 주문 조회
            if algo_type == "trigger":
                params = {
                "instId": symbol,
                "algoId": order_id,
                "ordType": "trigger"
            }
            else:
                params = {
                    "instId": symbol,
                    "algoId": order_id,
                    "ordType": "conditional"
                }
            
            try:
                # 활성 주문 조회
                try:
                    pending_resp = await exchange.privateGetTradeOrdersAlgoPending(params=params)
                except Exception as e:
                    if "51603" in str(e) or "Order does not exist" in str(e):
                        pending_resp = {"code": "0", "data": []}
                    else:
                        raise e

                if pending_resp.get("code") == "0":
                    pending_data = pending_resp.get("data", [])
                    if pending_data:
                        order_info = pending_data[0]
                        state = order_info.get("state", "").lower()
                        
                        status_map = {
                            "live": "open",
                            "effective": "filled",
                            "order_failed": "rejected",
                            "canceled": "canceled",
                            "partially_effective": "partially_filled"
                        }
                        
                        return {
                            "status": status_map.get(state, state),
                            "info": order_info,
                            "data": pending_data,
                            "state": state
                        }
                
                # 히스토리 조회
                try:
                    history_resp = await exchange.privateGetTradeOrdersAlgoHistory(params=params)
                except Exception as e:
                    if "51603" in str(e) or "Order does not exist" in str(e):
                        history_resp = {"code": "0", "data": []}
                    else:
                        raise e

                if history_resp.get("code") == "0":
                    history_data = history_resp.get("data", [])
                    if history_data:
                        order_info = history_data[0]
                        state = order_info.get("state", "").lower()
                        
                        status_map = {
                            "live": "open",
                            "effective": "filled",
                            "order_failed": "rejected",
                            "canceled": "canceled",
                            "closed": "closed",
                            "partially_effective": "partially_filled"
                        }
                        
                        return {
                            "status": status_map.get(state, state),
                            "info": order_info,
                            "data": history_data,
                            "state": state
                        }
                
                # 주문을 찾지 못한 경우
                return {
                    "status": "not_found",
                    "info": {},
                    "data": [],
                    "state": "not_found"
                }
                
            except Exception as e:
                logger.error(f"알고리즘 주문 조회 중 예외 발생: {str(e)}")
                return {
                    "status": "not_found",
                    "info": {},
                    "data": [],
                    "state": "not_found"
                }
                    
        except Exception as e:
            logger.error(f"알고리즘 주문 조회 실패: {str(e)}", exc_info=True)
            return {
                "status": "not_found",
                "info": {},
                "data": [],
                "state": "not_found"
            }
            
        