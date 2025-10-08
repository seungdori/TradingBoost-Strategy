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
  # Redis 클라이언트 가져오기
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

# ORDER_BACKEND는 항상 자기 자신을 가리키므로 사용하지 않음
order_backend_client = None

async def init_user_position_data(user_id: str, symbol: str, side: str):
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


class ClosePositionRequest(BaseModel):
   close_type: str = "market"  # market 또는 limit
   price: Optional[float] = None  # limit 주문일 경우 가격
   close_percent: float = 100.0  # 종료할 포지션의 퍼센트 (1-100)
   
   model_config = {
       "json_schema_extra": {
           "example": {
               "close_type": "market",
               "price": None,
               "close_percent": 50.0  # 50% 종료 예시
           }
       }
   }

# ✅ Redis에서 사용자 API 키 가져오기
async def get_okx_uid_from_telegram_id(telegram_id: str) -> str:
    """
    텔레그램 ID를 OKX UID로 변환하는 함수
    
    Args:
        telegram_id: 텔레그램 ID
        
    Returns:
        str: OKX UID
    """
    try:
        # 텔레그램 ID로 OKX UID 조회
        okx_uid = await redis_client.get(f"user:{telegram_id}:okx_uid")
        if okx_uid:
            return okx_uid.decode() if isinstance(okx_uid, bytes) else okx_uid
        return None
    except Exception as e:
        logger.error(f"텔레그램 ID를 OKX UID로 변환 중 오류: {str(e)}")
        return None

async def get_identifier(user_id: str) -> str:
    """
    입력된 식별자가 텔레그램 ID인지 OKX UID인지 확인하고 적절한 OKX UID를 반환
    
    Args:
        user_id: 텔레그램 ID 또는 OKX UID
        
    Returns:
        str: OKX UID
    """
    # 11글자 이하면 텔레그램 ID로 간주하고 변환
    if len(str(user_id)) <= 11:
        okx_uid = await get_okx_uid_from_telegram_id(user_id)
        if not okx_uid:
            raise HTTPException(status_code=404, detail=f"텔레그램 ID {user_id}에 대한 OKX UID를 찾을 수 없습니다")
        return okx_uid
    # 12글자 이상이면 이미 OKX UID로 간주
    return user_id

async def get_user_api_keys(user_id: str) -> Dict[str, str]:
    """
    사용자 ID를 기반으로 Redis에서 OKX API 키를 가져오는 함수
    """
    try:
        # 텔레그램 ID인지 OKX UID인지 확인하고 변환
        okx_uid = await get_identifier(user_id)
        
        api_key_format = f"user:{okx_uid}:api:keys"
        api_keys = await redis_client.hgetall(api_key_format)
        
        if not api_keys:
            raise HTTPException(status_code=404, detail="API keys not found in Redis")
        return api_keys
    except HTTPException:
        raise
    except Exception as e:
        error_logger.error(f"API 키 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching API keys: {str(e)}")

# Utility functions
def safe_float(value: Any, default: float = 0.0) -> float:
    """Convert value to float safely"""
    try:
        if value is None or value == '':
            return default
        return float(value)
    except (ValueError, TypeError):
        return default

async def handle_exchange_error(e: Exception):
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
):
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

            def safe_float(value, default=0.0):
                try:
                    if value is None or value == '':
                        return default
                    return float(value)
                except (ValueError, TypeError):
                    return default

            result = []
            for order in orders_data:
                try:
                    # 로그에 표시된 실제 데이터 구조를 확인하여 정확한 필드명 사용
                    result.append(OrderResponse(
                        order_id=order['ordId'],
                        client_order_id=order.get('clOrdId', ''),
                        symbol=order['instId'],
                        side=OrderSide.BUY if order['side'] == 'buy' else OrderSide.SELL,  # 문자열을 OrderSide Enum으로 변환
                        type=OrderType.MARKET if order['ordType'] == 'market' else OrderType.LIMIT,  # 문자열을 OrderType Enum으로 변환
                        order_type=order['ordType'],
                        amount=safe_float(order['sz']),
                        filled_amount=safe_float(order.get('accFillSz', 0.0)), #accFillSz일지, fillSz일지 확인
                        remaining_amount=safe_float(order['sz']) - safe_float(order.get('accFillSz', 0.0)),
                        price=safe_float(order.get('px')),
                        average_price=safe_float(order.get('avgPx')),
                        status=OrderStatus.OPEN if (order['state'] == 'live' or order['state'] == 'partially_filled' or order['state'] == 'open') 
                               else OrderStatus.FILLED if order['state'] == 'filled' 
                               else OrderStatus.CANCELED if order['state'] == 'canceled' 
                               else OrderStatus.REJECTED if order['state'] == 'rejected' 
                               else OrderStatus.EXPIRED if order['state'] == 'expired' 
                               else OrderStatus.PENDING,  # status 값을 OrderStatus Enum으로 변환
                        posSide=order['posSide'],
                        pnl=safe_float(order.get('pnl', '0.0')),
                        created_at=int(order.get('cTime', dt.datetime.now().timestamp() * 1000)),
                        updated_at=int(order.get('uTime', order.get('cTime', dt.datetime.now().timestamp() * 1000)))
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
):
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
                        amount=Decimal(str(safe_float(order_data["amount"]) if order_data.get("amount") else 0.0)),
                        filled_amount=safe_float(order_data.get('filled', 0.0)),
                        remaining_amount=Decimal(str(order_data["remaining"]) if order_data.get("remaining") else 0.0),
                        price=Decimal(str(safe_float(order_data.get('price')) if order_data.get('price') else 0.0)),
                        average_price=Decimal(str(safe_float(order_data.get('average')) if order_data.get('average') else 0.0)),
                        status=OrderStatus.FILLED if order_data["status"] == "closed" 
                               else OrderStatus.CANCELED if order_data["status"] == "canceled"
                               else OrderStatus.OPEN,  # Enum으로 변경
                        created_at=int(order_data["timestamp"]) if order_data.get("timestamp") else int(dt.datetime.now().timestamp()),
                        updated_at=int(order_data.get("lastUpdateTimestamp", order_data["timestamp"]) if order_data.get("lastUpdateTimestamp") else int(dt.datetime.now().timestamp())),
                        pnl=Decimal(str(safe_float(order_data.get('pnl')) if order_data.get('pnl') else 0.0)),
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
):
    # ORDER_BACKEND 사용 여부 확인
    if order_backend_client:
        try:
            order_dict = order.dict()
            response_data = await order_backend_client.create_order(order_dict, user_id)
            return response_data
        except Exception as e:
            logger.error(f"Backend request failed, falling back to local: {e}")
    
    # 로컬 처리
    # user_id를 OKX UID로 변환
    okx_uid = await get_identifier(user_id)
    async with get_exchange_context(okx_uid) as exchange:
        try:
            # 레버리지 설정이 있는 경우 적용
            if order.leverage:
                await exchange.privatePostAccountSetLeverage({
                    'instId': order.symbol,
                    'lever': order.leverage,
                })

            response = await exchange.create_order(
                symbol=order.symbol,
                type=order.type,
                side=order.side,
                amount=order.amount,
                price=order.price
            )

            return OrderResponse(
                order_id=response['id'],
                client_order_id=response.get('clientOrderId', f"order_{int(dt.datetime.now().timestamp())}"),
                symbol=response['symbol'],
                side=response['side'],
                type=response['type'],
                order_type=response['type'],
                amount=safe_float(response.get('amount')),
                filled_amount=safe_float(response.get('filled', 0)),
                remaining_amount=safe_float(response.get('amount', 0)) - safe_float(response.get('filled', 0)),
                price=safe_float(response.get('price')),
                average_price=safe_float(response.get('average')),
                status=status_mapping.get(response.get('status', 'unknown'), 'pending'),
                posSide=response.get('info', {}).get('posSide', 'net'),
                pnl=safe_float(response.get('info', {}).get('pnl', 0)),
                created_at=int(response.get('timestamp', dt.datetime.now().timestamp())),
                updated_at=int(response.get('timestamp', dt.datetime.now().timestamp()))
            )

        except Exception as e:
            logger.error(f"Failed to create order: {str(e)}", exc_info=True)
            await handle_exchange_error(e)



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
):
    # ORDER_BACKEND 사용 여부 확인
    if order_backend_client:
        try:
            close_data = close_request.dict()
            response_data = await order_backend_client.close_position(symbol, close_data, user_id, side)
            return response_data
        except Exception as e:
            logger.error(f"Backend request failed, falling back to local: {e}")
    
    # 로컬 처리
    # user_id를 OKX UID로 변환
    okx_uid = await get_identifier(user_id)
    async with get_exchange_context(okx_uid) as exchange:
        try:
            positions_resp = await exchange.private_get_account_positions({'instType': 'SWAP'})
            all_positions = positions_resp.get('data', [])

            # side 파라미터가 있을 경우 해당 방향의 포지션만 필터링
            position = next(
                (p for p in all_positions
                 if p['instId'] == symbol and float(p.get('pos', '0')) != 0
                 and (not side or p.get('posSide') == side)),  # side 파라미터로 필터링 추가
                None
            )

            if not position:
                logger.info(f"포지션 종료 요청 - 활성화된 포지션 없음: {symbol} {side if side else '(모든 방향)'}")
                try:
                    return OrderResponse(
                        order_id='no_position',
                        client_order_id=f"no_position_{int(dt.datetime.now().timestamp())}",
                        symbol=symbol,
                        side='sell' if side == 'long' or side == 'buy' else 'buy',
                        type='market',
                        order_type='market',
                        amount=0,
                        filled_amount=0,
                        remaining_amount=0,
                        price=0,
                        average_price=0,
                        status='rejected',
                        posSide=side if side else 'net',
                        pnl=0,
                        created_at=int(dt.datetime.now().timestamp() * 1000),
                        updated_at=int(dt.datetime.now().timestamp() * 1000)
                    )
                except Exception as e:
                    logger.error(f"포지션 종료 요청 중 오류: {str(e)}")
                    traceback.print_exc()
                    raise HTTPException(status_code=404, detail=f"지정한 방향{side}의 활성화된 포지션을 찾을 수 없습니다" if side else "활성화된 포지션을 찾을 수 없습니다")
            # side 파라미터로 이미 필터링된 포지션의 실제 posSide 값
            found_pos_side = position.get('posSide', side)  # 실제 posSide 값 사용, 없으면 side 사용
            current_size = float(position['pos'])  
            abs_size = abs(current_size)

            # (2) 종료할 수량 계산
            close_size = abs_size * (close_request.close_percent / 100.0)

            # (3) 종료 주문 사이드
            #     - pos>0 → 롱 → 청산(side="sell")
            #     - pos<0 → 숏 → 청산(side="buy") (Hedge 모드에서 -값이 들어올 수도 있으나,
            #       OKX REST API에선 포지션이 -값을 주지 않고 posSide="short" & pos>0로 주는 경우도 있음)
            close_side = 'sell' if (found_pos_side == 'long' or found_pos_side == 'buy') else 'buy'
            
            print(f"found_pos_side: {found_pos_side}")
            # (4) SL/TP 취소 로직
            try:
                if found_pos_side == "net":
                # --- One-way 모드: 해당 심볼의 모든 SL/TP(알고+reduceOnly) 취소 ---
                    await cancel_all_orders(symbol, user_id, pos_side = None)
                    #await cancel_reduce_only_orders_for_symbol(exchange, symbol)
                else:
                    # --- Hedge 모드: 해당 posSide에 해당하는 주문만 골라 취소 ---
                    await cancel_all_orders(symbol, user_id, side=found_pos_side)
                    #await cancel_reduce_only_orders_for_symbol_and_side(exchange, symbol, found_pos_side)
            except Exception as e:
                logger.error(f"Failed to cancel orders: {str(e)}")
                traceback.print_exc()
                await send_telegram_message(f"주문 조회하는 데에 오류 발생: {str(e)}", okx_uid = 1709556958, debug=True)
                
            tdMode = await redis_client.get(f"user:{user_id}:position:{symbol}:tdMode")
            if tdMode is None:
                tdMode = "cross"  # 기본값 설정
            # (5) 포지션 종료
            order_params = {
                'tdMode': tdMode,          # 필요시 'isolated'
                'posSide': found_pos_side,  # net / long / short,
                'reduceOnly': True
            }
            if close_request.close_type == 'limit' and close_request.price:
                order_params['price'] = close_request.price

            try:
                response = await exchange.create_order(
                    symbol=symbol,
                    type=close_request.close_type,
                    side=close_side,
                    amount=close_size,
                    params=order_params
                )
                await init_user_position_data(user_id, symbol, side)
            except Exception as e:
                logger.error(f"Failed to create order: {str(e)}")
                traceback.print_exc()
                await send_telegram_message(f"주문 생성 중 오류 발생: {str(e)}", okx_uid = 1709556958, debug=True)
                
                # 오류 상황에서도 필수 필드를 모두 포함하여 OrderResponse 객체를 생성합니다
                return OrderResponse(
                    order_id='failed',
                    client_order_id=f"failed_{int(dt.datetime.now().timestamp())}",  # 타임스탬프로 유니크한 ID 생성
                    symbol=symbol,
                    side=close_side,
                    type=close_request.close_type,
                    order_type=close_request.close_type,
                    amount=close_size,
                    filled_amount=0,
                    remaining_amount=close_size,  # 남은 수량은 전체 수량과 같음
                    price=close_request.price if close_request.close_type == 'limit' else 0,
                    average_price=close_request.price if close_request.close_type == 'limit' else 0,
                    status='rejected',  # 'failed'대신 Pydantic 모델에서 허용하는 값 사용
                    posSide=found_pos_side,
                    pnl=0,
                    created_at=int(dt.datetime.now().timestamp() * 1000),  # milliseconds
                    updated_at=int(dt.datetime.now().timestamp() * 1000)   # milliseconds
                )
            if response['id']:
                try:
                    order_details = await exchange.fetch_order(response['id'], symbol)
                    response.update(order_details)  # 상세 정보로 응답 업데이트
                except Exception as e:
                    logger.error(f"Failed to fetch order details: {str(e)}")
            if response is not None:
                try:
                    status = None
                    if hasattr(response, 'status'):
                        status = getattr(response, 'status', None)
                    # 그렇지 않고, response가 dict라면 dict 형태로 상태값을 가져옴
                    elif isinstance(response, dict):
                        status = response.get('status')
                    if status in ['closed', 'filled']:
                        await redis_client.delete(f"user:{user_id}:position:{symbol}:{side}")
                        await redis_client.delete(f"user:{user_id}:position:{symbol}:position_state")
                        await redis_client.delete(f"user:{user_id}:position:{symbol}:{side}:dca_count")
                        await redis_client.delete(f"user:{user_id}:position:{symbol}:{side}:dca_levels")
                        await redis_client.delete(f"user:{user_id}:position:{symbol}:{side}:tp_data")
                except Exception as e:
                    logger.error(f"Failed to delete position state: {str(e)}")
                    traceback.print_exc()
            # (6) 결과 반환
            

            return OrderResponse(
                order_id=response['id'],
                client_order_id=response['clientOrderId'],  # 추가
                symbol=response['symbol'],
                side=response['side'],
                type=response['type'],
                order_type=response['type'],  # 추가
                amount=safe_float(response.get('amount')),
                filled_amount=safe_float(response.get('filled')),  # filled -> filled_amount
                remaining_amount=safe_float(response.get('amount', 0)) - safe_float(response.get('filled', 0)),  # 남은 수량 추가
                price=safe_float(response.get('price')),
                average_price=safe_float(response.get('average')),
                status=status_mapping.get(response.get('status', 'unknown'), 'pending'),  # status 매핑 추가
                posSide=response['info'].get('posSide'),  # 추가
                pnl=safe_float(response['info'].get('pnl', 0)),  # response['info'] 대신 order에서 직접 가져오기
                created_at=int(response.get('timestamp', dt.datetime.now().timestamp())),  # timestamp -> created_at
                updated_at=int(response.get('timestamp', dt.datetime.now().timestamp()))   # updated_at 추가
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to close position: {str(e)}", exc_info=True)
            await handle_exchange_error(e)



# ------------------------------------------------------
# ✅ (1) 알고주문 조회를 위한 헬퍼 함수
# ------------------------------------------------------
async def fetch_algo_order_by_id(exchange_or_wrapper, order_id: str, symbol: Optional[str] = None, algo_type : Optional[str] = "trigger") -> Optional[dict]:
    
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
            if found := next((x for x in pending_resp.get("data", []) if x.get("algoId") == order_id), None):
                return found
        
        # 히스토리 조회
        history_resp = await exchange.privateGetTradeOrdersAlgoHistory(
            params=params
        )
        
        if history_resp.get("code") == "0":
            if found := next((x for x in history_resp.get("data", []) if x.get("algoId") == order_id), None):
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
    OKX 알고주문(Trigger) 데이터를 OrderResponse 형태로 변환.
    """
    def safe_decimal(val, default="0"):
        if val is None or val == '':
            return Decimal(default)
        try:
            return Decimal(str(val))
        except:
            return Decimal(default)

    # 기본 정보 매핑
    order_id = algo_order.get("algoId", "N/A")
    client_order_id = algo_order.get("clOrdId")  # 필수 필드 추가
    symbol = algo_order.get("instId", "N/A")
    
    # side 매핑
    side_str = algo_order.get("side", "").lower()
    side = OrderSide.BUY if side_str == "buy" else OrderSide.SELL
    
    # type 매핑
    o_type_str = algo_order.get("ordType", algo_type)
    o_type = OrderType.MARKET if o_type_str == "market" else OrderType.LIMIT
    
    # 수량 관련
    amount = safe_decimal(algo_order.get("sz", 0.0))
    filled_amount = safe_decimal(algo_order.get("fillSz", 0.0))  # 필수 필드 추가
    remaining_amount = Decimal(amount - filled_amount)
    
    # 가격 관련
    price = safe_decimal(algo_order.get("triggerPx"))
    average_price = safe_decimal(algo_order.get("actualPx")) or None
    
    # 상태 매핑 (OrderStatus enum에 맞게)
    status_map = {
        "live": OrderStatus.OPEN,
        "canceled": OrderStatus.CANCELED,
        "partially_filled": OrderStatus.PARTIALLY_FILLED,
        "filled": OrderStatus.FILLED,
        "failed": OrderStatus.REJECTED
    }
    status = status_map.get(algo_order.get("state", "").lower(), OrderStatus.PENDING)
    
    # 시간 처리
    created_at = int(algo_order.get("cTime")) if algo_order.get("cTime", "").isdigit() else None
    updated_at = int(algo_order.get("uTime")) if algo_order.get("uTime", "").isdigit() else None
    
    # PNL 처리
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
        posSide=algo_order.get("posSide", "unknown")
    )


# Order cancellation utilities
async def cancel_algo_orders_for_symbol(
    exchange,
    symbol: str,
    pos_side: Optional[str] = None
):
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
    exchange,
    symbol: str,
    pos_side: Optional[str] = None
):
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

def parse_order_response(order_data: dict) -> OrderResponse:
    """Convert exchange order data to OrderResponse model"""
    return OrderResponse(
        order_id=order_data["id"],
        symbol=order_data["symbol"],
        side=order_data["side"],
        type=order_data["type"],
        amount=safe_float(order_data["amount"]),
        filled=safe_float(order_data["filled"]),
        price=safe_float(order_data["price"]) if order_data.get("price") else None,
        average_price=safe_float(order_data["average"]) if order_data.get("average") else None,
        status=order_data["status"],
        timestamp=dt.datetime.fromtimestamp(order_data["timestamp"] / 1000) if order_data.get("timestamp") else dt.datetime.now(),
        pnl=safe_float(order_data["info"].get("pnl"))  # PNL 정보 추가
    )

#==============================================
# 스탑로스 주문 업데이트
#==============================================

async def update_stop_loss_order_redis(
    user_id: str,
    symbol: str,
    side: str,
    new_sl_price: float,
):
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
):
    # ORDER_BACKEND 사용 여부 확인
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
    if side == "long":
        side = "buy"
    if side == "short":
        side = "sell"
    if order_side == "long":
        order_side = "buy"
    if order_side == "short":
        order_side = "sell"
    print(f"side: {side}, order_side: {order_side}")
    if order_side == "sell" and side == "sell":
        raise HTTPException(status_code=400, detail="숏 포지션의 SL은 buy여야 합니다")
    if order_side == "buy" and side == "buy":
        raise HTTPException(status_code=400, detail="롱 포지션의 SL은 sell여야 합니다")
    
    if algo_type == "trigger":
        algo_type = "trigger"
    else:
        algo_type = "conditional"
    async with get_exchange_context(user_id) as exchange:
        try:
            # 1. 현재 포지션 확인

            positions = await exchange.private_get_account_positions({'instType': 'SWAP'})
            position = next((pos for pos in positions.get('data', []) 
                        if pos['instId'] == symbol and float(pos.get('pos', 0)) != 0), None)
            contracts_amount = float(position.get('pos', 0)) if position else 0
            if not position:
                logger.info(f"No active position found for {symbol}, skipping SL update")
                removed = await TradingCache.remove_position(user_id, symbol, order_side)
                if removed:
                    logger.info(f"Successfully removed position from cache for {symbol}")
                return {
                    "success": False,
                    "message": "활성화 된 포지션을 찾을 수 없습니다"
                }

            # 2. 현재가 확인 및 SL 가격 유효성 검사
            ticker = await exchange.fetch_ticker(symbol)
            current_price = ticker['last']

            try:
                # 롱 포지션의 경우 SL 주문은 sell, 숏은 buy로 주문되므로,
                # algo 주문 취소 시에는 posSide 매개변수를 "long" (sell 주문) 또는 "short" (buy 주문)으로 설정합니다.
                pos_side = "net"
                if side == "long" or side == "buy":
                    pos_side = "long"
                elif side == "short" or side == "sell":
                    pos_side = "short"
                
                
                await cancel_algo_orders(
                    symbol=symbol,
                    user_id=user_id,
                    side=pos_side,
                    algo_type=algo_type
                )
            except Exception as e:
                logger.warning(f"기존 SL algo 주문 취소 중 오류: {str(e)}")
                traceback.print_exc()


            if side == "long" or side == "buy":
                side = "long"
                if new_sl_price >= current_price:
                    await update_stop_loss_order_redis(
                        user_id=user_id,
                        symbol=symbol,
                        side=side,
                        new_sl_price=new_sl_price
                    )
                    close_request = ClosePositionRequest(
                        close_type="market",
                        price=current_price,
                        close_percent=100,
                    )
                    try:
                        response = await close_position(
                            symbol=symbol,
                            close_request=close_request,
                            user_id=user_id,
                            side=side
                        )
                        try:
                            status = None
                            if hasattr(response, 'status'):
                                status = getattr(response, 'status', None)
                            # 그렇지 않고, response가 dict라면 dict 형태로 상태값을 가져옴
                            elif isinstance(response, dict):
                                status = response.get('status')
                            if status in ['closed', 'filled']:
                                await redis_client.delete(f"user:{user_id}:position:{symbol}:{side}")
                                await redis_client.delete(f"user:{user_id}:position:{symbol}:position_state")
                                await redis_client.delete(f"user:{user_id}:position:{symbol}:{side}:dca_count")
                                await redis_client.delete(f"user:{user_id}:position:{symbol}:{side}:dca_levels")
                                await redis_client.delete(f"user:{user_id}:position:{symbol}:{side}:tp_data")
                        except Exception as e:
                            logger.error(f"Failed to delete position state: {str(e)}")
                            traceback.print_exc()
                    except Exception as e:
                        # "활성화된 포지션을 찾을 수 없습니다" 에러를 별도로 처리
                        if "활성화된 포지션을 찾을 수 없습니다" in str(e) or "no_position" in str(e):
                            logger.info(f"포지션 종료 요청 - 이미 종료된 포지션: {symbol} {side}")
                        else:
                            # 다른 오류는 기존대로 처리
                            logger.error(f"Failed to close position: {str(e)}")
                            traceback.print_exc()
                            await send_telegram_message(f"주문 생성 중 오류 발생: {str(e)} \n BreakEven의 변경된 SL이 현재 시장가보다 높습니다.\n롱포지션을 시장가 종료합니다.", okx_uid = 1709556958, debug=True)

            else:  # short
                side = "short"
                if new_sl_price <= current_price:
                    try:
                        await update_stop_loss_order_redis(
                            user_id=user_id,
                            symbol=symbol,
                            side=side,
                            new_sl_price=new_sl_price
                        )   
                    except Exception as e:
                        logger.error(f"Failed to update stop loss order redis: {str(e)}")
                        traceback.print_exc()
                        await send_telegram_message(f"스탑로스 업데이트 중 오류 발생: {str(e)}", okx_uid = 1709556958, debug=True)
                    close_request = ClosePositionRequest(
                        close_type="market",
                        price=current_price,
                        close_percent=100,
                    )
                    try:
                        response = await close_position(
                            symbol=symbol,
                            close_request=close_request,
                            user_id=user_id,
                            side=side
                        )
                        if response is not None:
                            try:
                                status = None
                                if hasattr(response, 'status'):
                                    status = getattr(response, 'status', None)
                                # 그렇지 않고, response가 dict라면 dict 형태로 상태값을 가져옴
                                elif isinstance(response, dict):
                                    status = response.get('status')
                                if status in ['closed', 'filled']:
                                    await redis_client.delete(f"user:{user_id}:position:{symbol}:{side}")
                                    await redis_client.delete(f"user:{user_id}:position:{symbol}:position_state")
                                    await redis_client.delete(f"user:{user_id}:position:{symbol}:{side}:dca_count")
                                    await redis_client.delete(f"user:{user_id}:position:{symbol}:{side}:dca_levels")
                                    await redis_client.delete(f"user:{user_id}:position:{symbol}:{side}:tp_data")
                            except Exception as e:
                                logger.error(f"Failed to delete position state: {str(e)}")
                                traceback.print_exc()
                    except Exception as e:
                        # "활성화된 포지션을 찾을 수 없습니다" 에러를 별도로 처리
                        if "활성화된 포지션을 찾을 수 없습니다" in str(e) or "no_position" in str(e):
                            logger.info(f"포지션 종료 요청 - 이미 종료된 포지션: {symbol} {side}")
                        else:
                            # 다른 오류는 기존대로 처리
                            logger.error(f"Failed to close position: {str(e)}")
                            traceback.print_exc()
                            await send_telegram_message(f"[{user_id}] 주문 생성 중 오류 발생: {str(e)} \n BreakEven의 변경된 SL이 현재 시장가보다 낮습니다.\n숏포지션을 시장가 종료합니다.", okx_uid = 1709556958, debug=True)


            # (b) OKX Algo 주문 취소  
            # SL 주문을 algo 방식으로 생성한 경우, 해당 주문도 별도 API를 통해 취소해야 합니다.

            # 4. 새로운 SL 주문 생성
            print(f"position.get('posSide'): {position.get('posSide')}")
            pos_side = "long" if position.get('posSide') == 'long' else "short"
            print("size : ", contracts_amount)
            position_qty = float(position.get('pos', 0))
            print("position_qty : ", position_qty)
            tdMode = await redis_client.get(f"user:{user_id}:position:{symbol}:tdMode")
            if tdMode is None:
                tdMode = "cross"
            try:
                # 타임아웃 재시도 로직 추가
                max_retries = 3
                retry_count = 0
                sl_order = None
                
                while retry_count < max_retries:
                    try:
                        sl_order = await exchange.create_order(
                            symbol=symbol,
                            type=algo_type,  # 거래소에 따라 'stop_market' 등으로 변경될 수 있음
                            side=order_side,
                            amount=position_qty,
                            price=new_sl_price,  # 실제 체결 가격
                            params={
                                'stopPrice': new_sl_price,  # 트리거 가격
                                'reduceOnly': True,  # 포지션 종료용 주문임을 명시
                                'posSide': pos_side,
                                'slTriggerPxType': 'last',
                                'slOrdPxType': 'last',
                                'tdMode': tdMode,
                            }
                        )
                        # 성공적으로 주문이 생성되면 루프 종료
                        break
                    except Exception as retry_error:
                        error_str = str(retry_error)
                        # 타임아웃 에러일 경우에만 재시도
                        if "Order timed out" in error_str or "51149" in error_str:
                            retry_count += 1
                            if retry_count < max_retries:
                                logger.warning(f"스탑로스 주문 타임아웃 발생, {retry_count}/{max_retries} 재시도 중...")
                                # 재시도 전 대기 시간 (점진적으로 증가)
                                await asyncio.sleep(0.5 * retry_count)
                                continue
                        # 타임아웃이 아니거나 최대 재시도 횟수를 초과한 경우
                        raise retry_error
                
                # 주문 생성 성공한 경우에만 실행
                if sl_order:
                    # 5. 손절 주문 저장
                    position_key = f"user:{user_id}:position:{symbol}:{side}"
                    await redis_client.hset(
                        position_key,
                        mapping={
                            'sl_price': new_sl_price,
                            'sl_order_id': sl_order['id'],
                            'get_sl': 'false'
                        }
                    )
                    now = dt.datetime.now()
                    kr_time = now + dt.timedelta(hours=9)
                
                    monitor_key = f"monitor:user:{user_id}:{symbol}:order:{sl_order['id']}"
                    last_updated_time = int(now.timestamp())
                    last_updated_time_kr = kr_time.strftime("%Y-%m-%d %H:%M:%S")
                    
                    is_hedge_str = "true" if is_hedge else "false"
                    
                    try:
                        monitor_data = {
                            "status": "open",
                            "price": str(new_sl_price),
                            "position_side": side,
                            "contracts_amount": str(contracts_amount),
                            "order_type": order_type,
                            "position_qty": str(position_qty),
                            "ordertime": str(int(now.timestamp())),
                            "filled_contracts_amount": "0",
                            "remain_contracts_amount": str(contracts_amount),
                            "last_updated_time": str(int(now.timestamp())),
                            "last_updated_time_kr": kr_time.strftime("%Y-%m-%d %H:%M:%S"),
                            "is_hedge": str(is_hedge_str).lower()
                        }

                        await redis_client.hset(monitor_key, mapping=monitor_data)
                    except Exception as e:
                        logger.error(f"Failed to set monitor data: {str(e)}")
                        traceback.print_exc()
                    
                    # 재시도 후 성공한 경우 알림
                    if retry_count > 0:
                        await send_telegram_message(f"[{user_id}] 스탑로스 주문이 {retry_count+1}번째 시도에 성공적으로 생성되었습니다. 심볼: {symbol}, 가격: {new_sl_price}", okx_uid=1709556958, debug=True)
                    
                    return {
                        "success": True,
                        "symbol": symbol,
                        "new_sl_price": new_sl_price,
                        "order_id": sl_order['id'],
                        "retries": retry_count
                    }
                else:
                    # 최대 재시도 후에도 주문 생성 실패한 경우
                    raise Exception(f"최대 재시도 횟수({max_retries}회)를 초과했습니다. 스탑로스 주문 생성 실패")

            except Exception as e:
                # SL 주문 생성 실패 시 Redis에 SL 가격만 업데이트하고 예외 처리 후 응답
                logger.error(f"Failed to create stop loss order: {str(e)}")
                traceback.print_exc()
                
                error_message = str(e)
                # 타임아웃 오류 특별 처리
                if "Order timed out" in error_message or "51149" in error_message:
                    await send_telegram_message(f"[{user_id}] 스탑로스 주문 생성 중 타임아웃 발생. 최대 {max_retries}회 재시도했으나 실패했습니다. 시스템이 자동으로 SL 가격을 {new_sl_price}로 설정했지만 실제 주문은 생성되지 않았습니다.", okx_uid=1709556958, debug=True)
                else:
                    await send_telegram_message(f"[{user_id}] 스탑로스 주문 생성 중 오류 발생: {str(e)}", okx_uid=1709556958, debug=True)
                
                # 주문 생성은 실패했지만 SL 가격 업데이트
                position_key = f"user:{user_id}:position:{symbol}:{side}"
                await redis_client.hset(
                    position_key,
                    mapping={
                        'sl_price': new_sl_price,
                        'get_sl': 'false'
                    }
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
):
    async with get_exchange_context(user_id) as exchange:
        try:
            response = await exchange.cancel_order(order_id, symbol=symbol)
            return {
                "success": True,
                "order_id": order_id,
                "status": "canceled"
            }

        except Exception as e:
            logger.error(f"Failed to cancel order: {str(e)}", exc_info=True)
            await handle_exchange_error(e)

            
            
            
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
        description="거래쌍 심볼 (예: 'BTC-USDT-SWAP', 'ETH-USDT-SWAP')",
        examples={
            "BTC": {"value": "BTC-USDT-SWAP", "summary": "비트코인 USDT 선물"},
        }
    ),
    user_id: str = Query(
        ..., 
        description="사용자 ID",
        example=1709556958
    ),
    side: Optional[OrderSide] = Query(
        None, 
        description="포지션 방향 (선택사항: buy/long 또는 sell/short)",
        examples={
            "buy": {"value": "buy", "summary": "롱포지션의 주문만 취소"},
            "sell": {"value": "sell", "summary": "숏포지션의 주문만 취소"}
        }
    )
):
    # ORDER_BACKEND 사용 여부 확인
    if order_backend_client:
        try:
            response_data = await order_backend_client.cancel_all_orders(symbol, str(user_id), side)
            return response_data
        except Exception as e:
            logger.error(f"Backend request failed, falling back to local: {e}")
    if side == "long" or side == "buy":
        side = "buy"
        order_side = "sell"
    elif side == "short" or side == "sell":
        side = "sell"
        order_side = "buy"
    else:
        side = None
        order_side = None
    async with get_exchange_context(user_id) as exchange:
            
        try:
            # 미체결 주문 조회
            open_orders = await exchange.fetch_open_orders(symbol)
            print(f"open_orders: {open_orders}")
            # side로 필터링
            if side:
                open_orders = [order for order in open_orders if order['side'].lower() == order_side.lower()]
            
            initial_orders_count = len(open_orders)
            
            #if initial_orders_count == 0:
            #    return CancelOrdersResponse(
            #        success=True,
            #        message="No open orders to cancel",
            #        cancelled_orders_count=0,
            #        details={"cancelled_orders": []}
            #    )
            print(f"algo_cancel_side: {side}")
            # 트리거 주문 취소
            try:
                api_keys = await get_user_api_keys(user_id) 
                trigger_cancel_client = TriggerCancelClient(
                    api_key=api_keys.get('api_key'),
                    secret_key=api_keys.get('api_secret'),
                    passphrase=api_keys.get('passphrase')
                )
                await trigger_cancel_client.cancel_all_trigger_orders(inst_id = symbol, side = side if side else None, algo_type="trigger", user_id=user_id)
            except Exception as e:
                # 트리거 주문 취소 실패는 로깅하되 계속 진행
                logger.error(f"트리거 주문 취소 실패: {str(e)}")

            # 일반 주문 취소 요청 준비
            cancellation_requests = [
                {
                    "id": order['id'],
                    "symbol": order['symbol'],
                    "clientOrderId": order.get('clientOrderId')
                }
                for order in open_orders
            ]
            
            # 주문 취소 실행
            if cancellation_requests:
                response = await exchange.cancel_orders_for_symbols(cancellation_requests)
                
                # Redis 업데이트
                closed_orders_key = f"user:{user_id}:closed_orders"
                open_orders_key = f"user:{user_id}:open_orders"
                
                async with redis_client.pipeline() as pipe:
                    # 취소된 주문 저장
                    for order in open_orders:
                        await pipe.rpush(closed_orders_key, json.dumps(order))
                    
                    # 열린 주문 목록 업데이트
                    if side:
                        current_orders = await redis_client.lrange(open_orders_key, 0, -1)
                        await pipe.delete(open_orders_key)
                        for order_str in current_orders:
                            order = json.loads(order_str)
                            if order['side'].lower() != order_side.lower():
                                await pipe.rpush(open_orders_key, order_str)
                    else:
                        await pipe.delete(open_orders_key)
                    
                    await pipe.execute()

            return CancelOrdersResponse(
                success=True,
                message=f"Successfully cancelled {initial_orders_count} orders",
                cancelled_orders_count=initial_orders_count,
                details={"cancelled_orders": [order['id'] for order in open_orders]}
            )

        except Exception as e:
            logger.error(f"주문 취소 중 오류 발생: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=CancelOrdersResponse(
                    success=False,
                    message=f"Failed to cancel orders: {str(e)}",
                    cancelled_orders_count=0,
                    details={"cancelled_orders": []}
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
        description="취소 대상 심볼",
        examples={"default": "SOL-USDT-SWAP"}
    ),
    user_id: str = Query(1709556958, examples=1709556958, description="사용자 ID (API 키 조회에 사용)"),
    side: str = Query(None, examples="buy/sell", description="포지션의 방향(buy/sell)"),
    algo_type: str = Query("trigger", examples="trigger", description="알고리즘 주문 타입(trigger/conditional)")
):
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
            
        await client.cancel_all_trigger_orders(inst_id =  symbol, side = side if side else None, algo_type = algo_type, user_id = user_id)

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
                            "state": "effective",
                            # ... 기타 주문 정보 ...
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
):
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
            
        