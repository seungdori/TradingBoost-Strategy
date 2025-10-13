#src/api/routes/order.py
import asyncio
import datetime as dt
import json
import traceback
from decimal import Decimal
from typing import Any, Dict, List, Optional

import aiohttp
import ccxt.async_support as ccxt
from fastapi import APIRouter, Body, HTTPException, Path, Query
from pydantic import BaseModel

from HYPERRSI.src.api.dependencies import get_exchange_context
from HYPERRSI.src.api.exchange.models import (
    CancelOrdersResponse,
    OrderRequest,
    OrderResponse,
    OrderSide,
    OrderStatus,
    OrderType,
)
from HYPERRSI.src.config import settings
from HYPERRSI.src.core.database import TradingCache
from HYPERRSI.src.core.logger import error_logger
from HYPERRSI.src.trading.cancel_trigger_okx import TriggerCancelClient
from HYPERRSI.telegram_message import send_telegram_message
from shared.database.redis_helper import get_redis_client
from shared.errors.exceptions import (
    ErrorCode,
    ExchangeUnavailableException,
    OrderNotFoundException,
    TradingException,
    ValidationException,
)
from shared.helpers.user_id_converter import get_identifier as get_okx_uid_identifier
from shared.logging import get_logger

# shared 모듈에서 공통 함수 import
from shared.utils.type_converters import safe_decimal, safe_float

from .constants import ALGO_ORDERS_CHUNK_SIZE, API_ENDPOINTS, REGULAR_ORDERS_CHUNK_SIZE

# order 모듈 내부 import
from .models import EXAMPLE_RESPONSE, STATUS_MAPPING, ClosePositionRequest
from .parsers import parse_algo_order_to_order_response, parse_order_response
from .services import AlgoOrderService, OrderService, PositionService, StopLossService

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
    await get_redis_client().delete(position_state_key)
    await get_redis_client().delete(dual_side_position_key)
    await get_redis_client().delete(tp_data_key)
    await get_redis_client().delete(ts_key)
    await get_redis_client().delete(dca_count_key)
    await get_redis_client().delete(dca_levels_key)
    await get_redis_client().delete(position_key)
    await get_redis_client().delete(min_size_key)
    #await redis_client.delete(main_position_direction_key)
    await get_redis_client().delete(tp_state)
    await get_redis_client().delete(entry_fail_count_key)
    await get_redis_client().delete(hedging_direction_key)
    await get_redis_client().delete(dual_side_count_key)
    await get_redis_client().delete(current_trade_key)
    await get_redis_client().delete(initial_size_key)
    

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

# APIRouter 인스턴스 생성
router = APIRouter(tags=["order"])

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
    redis_client = get_redis_client()
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
        result: Dict[str, Any] = await get_redis_client().hgetall(api_key_format)
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
    description="""
# 열린 주문 목록 조회

사용자의 미체결(열린) 주문 목록을 조회합니다. 심볼 필터 옵션을 통해 특정 거래쌍의 주문만 조회할 수 있습니다.

## 동작 방식

1. **사용자 식별**: OKX UID 또는 Telegram ID 변환
2. **Exchange 연결**: get_exchange_context로 OKX API 접근
3. **API 호출**: privateGetTradeOrdersPending (instType='SWAP')
4. **심볼 필터링**: symbol 파라미터가 있으면 해당 심볼만 필터
5. **데이터 변환**: OKX 응답 → OrderResponse 모델 변환
6. **상태 매핑**: OKX state → OrderStatus Enum
7. **응답 반환**: OrderResponse 리스트

## 지원 주문 유형

- **Market**: 시장가 주문
- **Limit**: 지정가 주문
- **Stop**: 스탑 주문
- **Conditional**: 조건부 주문

## 상태 매핑

- **live/open** → OrderStatus.OPEN
- **filled** → OrderStatus.FILLED
- **canceled** → OrderStatus.CANCELED
- **rejected** → OrderStatus.REJECTED
- **expired** → OrderStatus.EXPIRED
- **partially_filled** → OrderStatus.OPEN

## OrderResponse 필드

- **order_id**: 주문 ID (ordId)
- **client_order_id**: 클라이언트 주문 ID (clOrdId)
- **symbol**: 거래쌍 (예: BTC-USDT-SWAP)
- **side**: 주문 방향 (buy/sell)
- **type**: 주문 타입 (market/limit)
- **amount**: 주문 수량 (sz)
- **filled_amount**: 체결 수량 (accFillSz)
- **remaining_amount**: 미체결 수량 (sz - accFillSz)
- **price**: 주문 가격 (px)
- **average_price**: 평균 체결가 (avgPx)
- **status**: 주문 상태 (state)
- **posSide**: 포지션 방향 (long/short/net)
- **pnl**: 손익
- **created_at**: 생성 시각 (cTime)
- **updated_at**: 수정 시각 (uTime)

## 사용 시나리오

-  **포지션 관리**: 현재 미체결 주문 현황 파악
-  **주문 확인**: 특정 심볼의 활성 주문 조회
-  **대시보드**: 전체 미체결 주문 모니터링
- ⏰ **알림**: 미체결 주문 수 체크
-  **전략 검증**: 주문 실행 여부 확인
""",
    responses={
        200: {
            "description": " 주문 목록 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "multiple_orders": {
                            "summary": "여러 주문 조회",
                            "value": [
                                {
                                    "order_id": "2205764866869846016",
                                    "client_order_id": "e847386590ce4dBC",
                                    "symbol": "BTC-USDT-SWAP",
                                    "side": "buy",
                                    "type": "limit",
                                    "order_type": "limit",
                                    "amount": 0.1,
                                    "filled_amount": 0.05,
                                    "remaining_amount": 0.05,
                                    "price": "91500.0",
                                    "average_price": "91480.0",
                                    "status": "open",
                                    "posSide": "long",
                                    "pnl": 0.0,
                                    "created_at": 1738239315673,
                                    "updated_at": 1738239315674
                                },
                                {
                                    "order_id": "2205764866869846017",
                                    "client_order_id": "f958497601de5eCD",
                                    "symbol": "ETH-USDT-SWAP",
                                    "side": "sell",
                                    "type": "limit",
                                    "order_type": "limit",
                                    "amount": 1.0,
                                    "filled_amount": 0.0,
                                    "remaining_amount": 1.0,
                                    "price": "3600.0",
                                    "average_price": None,
                                    "status": "open",
                                    "posSide": "short",
                                    "pnl": 0.0,
                                    "created_at": 1738239320000,
                                    "updated_at": 1738239320000
                                }
                            ]
                        },
                        "single_symbol": {
                            "summary": "특정 심볼 조회 (BTC)",
                            "value": [
                                {
                                    "order_id": "2205764866869846016",
                                    "client_order_id": "e847386590ce4dBC",
                                    "symbol": "BTC-USDT-SWAP",
                                    "side": "buy",
                                    "type": "limit",
                                    "order_type": "limit",
                                    "amount": 0.1,
                                    "filled_amount": 0.0,
                                    "remaining_amount": 0.1,
                                    "price": "91000.0",
                                    "average_price": None,
                                    "status": "open",
                                    "posSide": "long",
                                    "pnl": 0.0,
                                    "created_at": 1738239315673,
                                    "updated_at": 1738239315673
                                }
                            ]
                        },
                        "empty_list": {
                            "summary": "미체결 주문 없음",
                            "value": []
                        }
                    }
                }
            }
        },
        401: {
            "description": " 인증 오류 - API 키 문제",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_api_key": {
                            "summary": "유효하지 않은 API 키",
                            "value": {"detail": "인증 오류가 발생했습니다"}
                        }
                    }
                }
            }
        },
        404: {
            "description": " 사용자 정보 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "user_not_found": {
                            "summary": "사용자 미등록",
                            "value": {"detail": "사용자 ID 1709556958에 대한 OKX UID를 찾을 수 없습니다"}
                        },
                        "api_keys_not_found": {
                            "summary": "API 키 미등록",
                            "value": {"detail": "API keys not found in Redis"}
                        }
                    }
                }
            }
        },
        503: {
            "description": "⏱️ 거래소 연결 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "connection_error": {
                            "summary": "네트워크 오류",
                            "value": {"detail": "거래소 연결 오류가 발생했습니다"}
                        }
                    }
                }
            }
        }
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
#  (2) 새로운 라우트: 주문 상세 조회 (일반 or 알고주문)
# ------------------------------------------------------
@router.get(
    "/detail/{order_id}",
    response_model=OrderResponse,
    summary="주문 상세 조회 (일반 주문 + 알고주문)",
    description="""
# 주문 상세 조회 (일반 주문 + 알고주문)

주문 ID(ordId 또는 algoId)를 기준으로 일반 주문 및 알고리즘 주문의 상세 정보를 조회합니다. 3단계 폴백 조회 전략으로 모든 주문 유형을 지원합니다.

## 조회 전략 (3단계 Fallback)

### is_algo=false (일반 주문 우선 조회)
1. **열린 주문 조회**: fetch_open_orders로 활성 주문 검색
   - ordId와 id 필드 모두 확인
   - 정확한 매칭을 위해 문자열 비교
2. **닫힌 주문 조회**: fetch_order로 체결/취소 주문 검색
   - symbol 필요 (선택 파라미터지만 닫힌 주문 조회 시 필수)
   - 1초 대기 후 결과 반환
3. **알고주문 폴백**: fetch_algo_order_by_id로 트리거 주문 검색
   - 일반 주문에서 찾지 못한 경우 자동 시도
   - algo_type 파라미터에 따라 trigger/conditional 조회

### is_algo=true (알고주문 전용 조회)
- **알고주문만 조회**: fetch_algo_order_by_id 직접 호출
- **활성 주문 우선**: privateGetTradeOrdersAlgoPending 먼저 조회
- **히스토리 폴백**: privateGetTradeOrdersAlgoHistory로 체결/취소 주문 조회

## 알고주문 타입

- **trigger**: 트리거 주문 (Stop Loss, Take Profit 등)
  - 조건 가격 도달 시 실행
  - reduceOnly 플래그로 포지션 청산용 구분
- **conditional**: 조건부 주문
  - 복잡한 조건식 기반 실행
  - 다단계 전략 구현용

## OrderResponse 필드

- **order_id**: 주문 ID (일반: ordId, 알고: algoId)
- **client_order_id**: 클라이언트 주문 ID (선택 사항)
- **symbol**: 거래쌍 (예: BTC-USDT-SWAP)
- **side**: 주문 방향 (buy/sell)
- **type**: 주문 타입 (market/limit)
- **amount**: 주문 수량
- **filled_amount**: 체결된 수량
- **remaining_amount**: 미체결 수량
- **price**: 주문 가격 (Decimal)
- **average_price**: 평균 체결가 (Decimal)
- **status**: 주문 상태 (open/filled/canceled/rejected/expired)
- **posSide**: 포지션 방향 (long/short/net)
- **pnl**: 실현 손익
- **order_type**: 원본 주문 타입
- **created_at**: 생성 시각 (timestamp)
- **updated_at**: 최종 수정 시각 (timestamp)

## 상태 매핑 (일반 주문)

- **closed** → OrderStatus.FILLED
- **canceled** → OrderStatus.CANCELED
- **기타** → OrderStatus.OPEN

## 알고주문 상태 매핑

- **live** → open (활성)
- **effective** → filled (체결 완료)
- **order_failed** → rejected (거부)
- **canceled** → canceled (취소)
- **partially_effective** → partially_filled (부분 체결)

## 사용 시나리오

-  **주문 추적**: 특정 주문의 현재 상태 확인
-  **손익 계산**: 체결된 주문의 PNL 조회
-  **디버깅**: 주문 실행 문제 진단
-  **보고서**: 거래 내역 상세 분석
- ⏰ **알림**: 주문 상태 변경 감지
-  **전략 검증**: 알고주문 트리거 확인

## 예시 요청

```bash
# 일반 주문 조회
GET /order/detail/2205764866869846016?user_id=1709556958&symbol=BTC-USDT-SWAP

# 알고주문 조회
GET /order/detail/987654321?user_id=1709556958&symbol=SOL-USDT-SWAP&is_algo=true&algo_type=trigger

# 조건부 주문 조회
GET /order/detail/123456789?user_id=1709556958&symbol=ETH-USDT-SWAP&is_algo=true&algo_type=conditional
```
""",
    responses={
        200: {
            "description": " 주문 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "filled_order": {
                            "summary": "체결 완료된 주문",
                            "value": {
                                "order_id": "2205764866869846016",
                                "client_order_id": "e847386590ce4dBCe66cc0a9f0cbbbd5",
                                "symbol": "SOL-USDT-SWAP",
                                "side": "sell",
                                "type": "market",
                                "order_type": "market",
                                "amount": 0.01,
                                "filled_amount": 0.01,
                                "remaining_amount": 0.0,
                                "price": "240.7",
                                "average_price": "240.7",
                                "status": "filled",
                                "posSide": "net",
                                "pnl": 0.0343,
                                "created_at": 1738239315673,
                                "updated_at": 1738239315674
                            }
                        },
                        "open_limit_order": {
                            "summary": "미체결 지정가 주문",
                            "value": {
                                "order_id": "2205764866869846017",
                                "client_order_id": "f958497601de5eCD",
                                "symbol": "BTC-USDT-SWAP",
                                "side": "buy",
                                "type": "limit",
                                "order_type": "limit",
                                "amount": 0.1,
                                "filled_amount": 0.0,
                                "remaining_amount": 0.1,
                                "price": "91000.0",
                                "average_price": None,
                                "status": "open",
                                "posSide": "long",
                                "pnl": 0.0,
                                "created_at": 1738239315673,
                                "updated_at": 1738239315673
                            }
                        },
                        "partially_filled": {
                            "summary": "부분 체결된 주문",
                            "value": {
                                "order_id": "2205764866869846018",
                                "client_order_id": "a123456789bcDEF",
                                "symbol": "ETH-USDT-SWAP",
                                "side": "sell",
                                "type": "limit",
                                "order_type": "limit",
                                "amount": 1.0,
                                "filled_amount": 0.3,
                                "remaining_amount": 0.7,
                                "price": "3600.0",
                                "average_price": "3605.0",
                                "status": "open",
                                "posSide": "short",
                                "pnl": 0.015,
                                "created_at": 1738239320000,
                                "updated_at": 1738239325000
                            }
                        },
                        "algo_trigger_order": {
                            "summary": "알고주문 (트리거)",
                            "value": {
                                "order_id": "987654321",
                                "client_order_id": "",
                                "symbol": "SOL-USDT-SWAP",
                                "side": "sell",
                                "type": "trigger",
                                "order_type": "trigger",
                                "amount": 0.1,
                                "filled_amount": 0.0,
                                "remaining_amount": 0.1,
                                "price": "235.0",
                                "average_price": None,
                                "status": "open",
                                "posSide": "long",
                                "pnl": 0.0,
                                "created_at": 1738239330000,
                                "updated_at": 1738239330000
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 주문을 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "order_not_found": {
                            "summary": "주문 ID 없음",
                            "value": {"detail": "해당 주문을 찾을 수 없습니다"}
                        },
                        "algo_order_not_found": {
                            "summary": "알고주문 없음",
                            "value": {"detail": "알고주문(Trigger)에서 주문을 찾을 수 없습니다"}
                        },
                        "symbol_required": {
                            "summary": "심볼 파라미터 필요",
                            "value": {"detail": "닫힌 주문 조회를 위해 symbol 파라미터가 필요합니다"}
                        }
                    }
                }
            }
        },
        401: {
            "description": " 인증 오류 - API 키 문제",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_api_key": {
                            "summary": "유효하지 않은 API 키",
                            "value": {"detail": "인증 오류가 발생했습니다"}
                        },
                        "not_authenticated": {
                            "summary": "인증되지 않음",
                            "value": {"detail": "Authentication error"}
                        }
                    }
                }
            }
        },
        503: {
            "description": "⏱️ 거래소 연결 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "network_error": {
                            "summary": "네트워크 오류",
                            "value": {"detail": "거래소 연결 오류가 발생했습니다"}
                        },
                        "exchange_connection_error": {
                            "summary": "거래소 연결 실패",
                            "value": {"detail": "Exchange connection error"}
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 내부 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "general_error": {
                            "summary": "일반 서버 오류",
                            "value": {"detail": "주문 조회 중 오류가 발생했습니다"}
                        },
                        "query_failed": {
                            "summary": "주문 조회 실패",
                            "value": {"detail": "주문 조회 중 오류 발생: Internal server error"}
                        },
                        "algo_query_failed": {
                            "summary": "알고주문 조회 실패",
                            "value": {"detail": "알고주문 조회 실패: Failed to parse order data"}
                        }
                    }
                }
            }
        }
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
    description="""
# 새로운 주문 생성

거래소(OKX)에 새로운 주문을 생성합니다. OrderService를 사용하여 비즈니스 로직을 처리하며, 선택적으로 레버리지 설정을 지원합니다.

## 동작 방식

1. **사용자 식별**: user_id를 OKX UID로 변환
2. **Exchange 연결**: get_exchange_context로 OKX API 접근
3. **레버리지 설정** (선택사항): leverage 파라미터가 있으면 privatePostAccountSetLeverage 호출
4. **주문 생성**: OrderService.create_order로 주문 실행
5. **응답 변환**: OKX 응답 → OrderResponse 모델 변환
6. **응답 반환**: 생성된 주문 정보 반환

## OrderRequest 필드

- **symbol** (string, required): 거래쌍 (예: "BTC-USDT-SWAP")
  - 형식: BASE-QUOTE-SWAP
  - 대소문자 구분 없음 (자동 정규화)
- **side** (OrderSide, required): 주문 방향
  - OrderSide.BUY: 매수 (long 진입 또는 short 청산)
  - OrderSide.SELL: 매도 (short 진입 또는 long 청산)
- **type** (OrderType, required): 주문 유형
  - OrderType.MARKET: 시장가 주문 (즉시 체결)
  - OrderType.LIMIT: 지정가 주문 (가격 지정 필수)
- **amount** (float, required): 주문 수량
  - 최소 수량: 거래쌍별 상이 (예: BTC 0.001)
  - 단위: 계약 수 (contracts)
- **price** (Decimal, optional): 주문 가격
  - 지정가 주문 시 필수
  - 시장가 주문 시 무시됨
- **leverage** (int, optional): 레버리지 배율
  - 범위: 1-125 (거래쌍별 상이)
  - 설정 시 자동으로 적용

## 레버리지 설정

주문 생성 전 레버리지를 설정할 수 있습니다:
- **자동 설정**: leverage 파라미터 제공 시 자동 적용
- **실패 처리**: 레버리지 설정 실패 시 경고 로그 기록 후 계속 진행
- **주의사항**: 포지션이 있는 상태에서 레버리지 변경 불가

## 사용 시나리오

-  **진입 주문**: 새로운 포지션 진입
-  **청산 주문**: 기존 포지션 청산
-  **익절/손절**: Take Profit / Stop Loss 주문
-  **전략 실행**: 자동매매 전략의 주문 생성
- ⚖️ **레버리지 조정**: 주문과 동시에 레버리지 설정

## 예시 요청

```bash
# 시장가 매수 (레버리지 10x)
POST /order/
{
  "symbol": "BTC-USDT-SWAP",
  "side": "buy",
  "type": "market",
  "amount": 0.1,
  "leverage": 10
}

# 지정가 매도 (레버리지 미설정)
POST /order/
{
  "symbol": "ETH-USDT-SWAP",
  "side": "sell",
  "type": "limit",
  "amount": 1.0,
  "price": "3600.50"
}
```
""",
    responses={
        200: {
            "description": " 주문 생성 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "market_buy": {
                            "summary": "시장가 매수 성공",
                            "value": {
                                "order_id": "2205764866869846019",
                                "client_order_id": "b234567890cdEFG",
                                "symbol": "BTC-USDT-SWAP",
                                "side": "buy",
                                "type": "market",
                                "order_type": "market",
                                "amount": 0.1,
                                "filled_amount": 0.1,
                                "remaining_amount": 0.0,
                                "price": None,
                                "average_price": "91250.0",
                                "status": "filled",
                                "posSide": "long",
                                "pnl": 0.0,
                                "created_at": 1738239350000,
                                "updated_at": 1738239350100
                            }
                        },
                        "limit_sell": {
                            "summary": "지정가 매도 성공",
                            "value": {
                                "order_id": "2205764866869846020",
                                "client_order_id": "c345678901deGHI",
                                "symbol": "ETH-USDT-SWAP",
                                "side": "sell",
                                "type": "limit",
                                "order_type": "limit",
                                "amount": 1.0,
                                "filled_amount": 0.0,
                                "remaining_amount": 1.0,
                                "price": "3600.50",
                                "average_price": None,
                                "status": "open",
                                "posSide": "short",
                                "pnl": 0.0,
                                "created_at": 1738239360000,
                                "updated_at": 1738239360000
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": " 잘못된 요청",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_amount": {
                            "summary": "최소 수량 미달",
                            "value": {"detail": "잘못된 요청: Order size does not meet the minimum requirement"}
                        },
                        "invalid_leverage": {
                            "summary": "레버리지 범위 초과",
                            "value": {"detail": "잘못된 요청: Leverage must be between 1 and 125"}
                        },
                        "insufficient_margin": {
                            "summary": "증거금 부족",
                            "value": {"detail": "잘못된 요청: Insufficient margin"}
                        },
                        "invalid_symbol": {
                            "summary": "유효하지 않은 심볼",
                            "value": {"detail": "잘못된 요청: Invalid instrument ID"}
                        }
                    }
                }
            }
        },
        401: {
            "description": " 인증 오류 - API 키 문제",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_api_key": {
                            "summary": "유효하지 않은 API 키",
                            "value": {"detail": "인증 오류가 발생했습니다"}
                        }
                    }
                }
            }
        },
        503: {
            "description": "⏱️ 거래소 연결 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "network_error": {
                            "summary": "네트워크 오류",
                            "value": {"detail": "거래소 연결 오류가 발생했습니다"}
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 내부 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "order_creation_failed": {
                            "summary": "주문 생성 실패",
                            "value": {"detail": "작업 중 오류가 발생했습니다"}
                        }
                    }
                }
            }
        }
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
    summary="포지션 종료 (시장가/지정가 + 부분청산)",
    description="""
# 포지션 종료 (시장가/지정가 + 부분청산)

특정 심볼의 포지션을 종료합니다. PositionService를 사용하여 시장가/지정가 종료 및 부분 청산(퍼센트 기반)을 지원합니다.

## 동작 방식

1. **사용자 식별**: user_id를 OKX UID로 변환
2. **Exchange 연결**: get_exchange_context로 OKX API 접근
3. **파라미터 검증**:
   - 심볼 형식: BASE-QUOTE-SWAP 패턴
   - close_percent: 1-100 범위 검증
4. **현재 포지션 조회**: fetch_positions([symbol])로 활성 포지션 확인
5. **종료 수량 계산**: contracts * (close_percent / 100)
6. **포지션 사이드 확인**: long → sell / short → buy 결정
7. **기존 주문 취소**:
   - 알고리즘 주문 취소 (SL/TP 등)
   - reduceOnly 주문 취소 (기존 청산 주문)
8. **종료 주문 생성**: OrderService.create_order (reduceOnly=True)
9. **Redis 상태 업데이트**: user:{user_id}:position:{symbol}:closing (5분 TTL)
10. **응답 반환**: 생성된 종료 주문 정보

## ClosePositionRequest 필드

- **close_type** (string, required): 종료 주문 유형
  - "market": 시장가 종료 (즉시 체결, 가격 무시)
  - "limit": 지정가 종료 (price 필수, 체결 대기)
  - 기본값: "market"
- **price** (float, optional): 지정가 주문 가격
  - close_type="limit"일 때 필수
  - close_type="market"일 때 무시됨
  - 형식: USD 단위 (예: 67450.5)
- **close_percent** (float, optional): 종료할 포지션 비율
  - 범위: 1.0 - 100.0 (%)
  - 기본값: 100.0 (전체 청산)
  - 예시: 50.0 → 포지션의 50% 청산

## Path 파라미터

- **symbol** (string, required): 종료할 포지션의 거래쌍
  - 형식: BASE-QUOTE-SWAP
  - 예시: "BTC-USDT-SWAP", "ETH-USDT-SWAP"

## Query 파라미터

- **user_id** (string, required): 사용자 ID (텔레그램 ID 또는 OKX UID)
- **side** (string, optional): 종료할 포지션 방향
  - "long": 롱 포지션 청산 (매도 주문 생성)
  - "short": 숏 포지션 청산 (매수 주문 생성)
  - 생략 시: 활성 포지션의 방향 자동 감지

## 종료 주문 로직

### 시장가 종료 (close_type="market")
- 즉시 체결 (현재 시장가로 실행)
- 슬리피지 발생 가능
- 빠른 청산 필요 시 사용

### 지정가 종료 (close_type="limit")
- 지정한 가격에서만 체결
- 체결 보장 없음 (시장가가 도달해야 체결)
- 더 나은 가격으로 청산하고 싶을 때 사용

### 부분 청산 (close_percent < 100)
- 포지션의 일부만 청산
- 나머지 포지션 유지 (지속적인 모니터링 필요)
- 리스크 관리 전략에 활용

## 기존 주문 자동 취소

포지션 종료 시 다음 주문들이 자동으로 취소됩니다:
- **알고리즘 주문**: 트리거 주문, 조건부 주문 (SL/TP 포함)
- **reduceOnly 주문**: 기존 청산 주문

취소 범위:
- **One-way 모드** (posSide='net'): 해당 심볼의 모든 주문
- **Hedge 모드** (posSide='long'/'short'): 해당 사이드의 주문만

## Redis 상태 관리

**Closing 상태 키**: `user:{user_id}:position:{symbol}:closing`
- 값: "true"
- TTL: 300초 (5분)
- 용도: 포지션 청산 중 상태 추적 및 중복 청산 방지

## 사용 시나리오

-  **전체 청산**: close_percent=100 (기본값) → 포지션 완전 종료
-  **일부 익절**: close_percent=50 → 수익의 절반 실현, 나머지 보유
-  **손절 실행**: close_type="market" → 즉시 시장가로 손실 제한
-  **지정가 익절**: close_type="limit", price=목표가 → 목표가 도달 시 청산
-  **단계적 청산**: 여러 번 호출하여 점진적으로 포지션 축소
-  **리스크 관리**: 변동성 증가 시 포지션 크기 줄이기

## 예시 요청

```bash
# 시장가 전체 청산
curl -X POST "http://localhost:8000/order/position/close/BTC-USDT-SWAP?user_id=1709556958" \\
     -H "Content-Type: application/json" \\
     -d '{
           "close_type": "market",
           "close_percent": 100.0
         }'

# 지정가로 50% 청산
curl -X POST "http://localhost:8000/order/position/close/ETH-USDT-SWAP?user_id=1709556958" \\
     -H "Content-Type: application/json" \\
     -d '{
           "close_type": "limit",
           "price": 3500.0,
           "close_percent": 50.0
         }'

# 롱 포지션 전체 청산 (사이드 명시)
curl -X POST "http://localhost:8000/order/position/close/SOL-USDT-SWAP?user_id=1709556958&side=long" \\
     -H "Content-Type: application/json" \\
     -d '{
           "close_type": "market",
           "close_percent": 100.0
         }'
```
""",
    responses={
        200: {
            "description": " 포지션 종료 성공 - 청산 주문 생성됨",
            "content": {
                "application/json": {
                    "examples": {
                        "market_full_close": {
                            "summary": "시장가 전체 청산 (즉시 체결)",
                            "value": {
                                "order_id": "710582134659948544",
                                "client_order_id": "d8e2f1a5b3c94d8e9f0a1b2c3d4e5f6g",
                                "symbol": "BTC-USDT-SWAP",
                                "side": "sell",
                                "type": "market",
                                "order_type": "market",
                                "amount": 0.1,
                                "filled_amount": 0.1,
                                "remaining_amount": 0.0,
                                "price": None,
                                "average_price": "67823.5",
                                "status": "filled",
                                "posSide": "net",
                                "pnl": "123.45",
                                "created_at": 1738240500000,
                                "updated_at": 1738240500250
                            }
                        },
                        "limit_partial_close": {
                            "summary": "지정가로 50% 부분 청산 (대기 중)",
                            "value": {
                                "order_id": "710582234759958645",
                                "client_order_id": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
                                "symbol": "ETH-USDT-SWAP",
                                "side": "sell",
                                "type": "limit",
                                "order_type": "limit",
                                "amount": 0.5,
                                "filled_amount": 0.0,
                                "remaining_amount": 0.5,
                                "price": "3500.0",
                                "average_price": None,
                                "status": "open",
                                "posSide": "long",
                                "pnl": "0.0",
                                "created_at": 1738240600000,
                                "updated_at": 1738240600000
                            }
                        },
                        "hedge_mode_close": {
                            "summary": "헷지 모드 숏 포지션 청산",
                            "value": {
                                "order_id": "710582334859968746",
                                "client_order_id": "q1r2s3t4u5v6w7x8y9z0a1b2c3d4e5f6",
                                "symbol": "SOL-USDT-SWAP",
                                "side": "buy",
                                "type": "market",
                                "order_type": "market",
                                "amount": 2.0,
                                "filled_amount": 2.0,
                                "remaining_amount": 0.0,
                                "price": None,
                                "average_price": "142.35",
                                "status": "filled",
                                "posSide": "short",
                                "pnl": "-8.70",
                                "created_at": 1738240700000,
                                "updated_at": 1738240700180
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": " 잘못된 요청 - 유효성 검증 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_close_percent": {
                            "summary": "잘못된 청산 비율 (범위 초과)",
                            "value": {
                                "detail": "Invalid close percent: must be between 1 and 100",
                                "symbol": "BTC-USDT-SWAP",
                                "close_percent": 150.0,
                                "valid_range": "1.0 - 100.0"
                            }
                        },
                        "no_position_to_close": {
                            "summary": "청산할 포지션 없음 (계약 수량 0)",
                            "value": {
                                "detail": "No position to close",
                                "symbol": "ETH-USDT-SWAP",
                                "contracts": 0.0,
                                "reason": "Position size is zero"
                            }
                        },
                        "invalid_symbol_format": {
                            "summary": "잘못된 심볼 형식",
                            "value": {
                                "detail": "Invalid symbol format: expected BASE-QUOTE-SWAP",
                                "symbol": "BTCUSDT",
                                "valid_format": "BASE-QUOTE-SWAP",
                                "example": "BTC-USDT-SWAP"
                            }
                        },
                        "invalid_close_amount": {
                            "summary": "잘못된 청산 수량 (계산 결과 0 이하)",
                            "value": {
                                "detail": "Invalid close amount: must be greater than 0",
                                "calculated_amount": 0.0,
                                "contracts": 0.01,
                                "close_percent": 1.0,
                                "reason": "Position too small for partial close"
                            }
                        }
                    }
                }
            }
        },
        401: {
            "description": " 인증 오류 - API 키 없음 또는 만료됨",
            "content": {
                "application/json": {
                    "examples": {
                        "authentication_error": {
                            "summary": "API 키 인증 실패",
                            "value": {
                                "detail": "Authentication error",
                                "user_id": "1709556958",
                                "reason": "Invalid API credentials or expired session"
                            }
                        },
                        "user_not_found": {
                            "summary": "사용자 미등록 (API 키 없음)",
                            "value": {
                                "detail": "User not found",
                                "user_id": "unknown_user_123",
                                "suggestion": "Please register API keys first"
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 포지션 없음 - 해당 심볼에 활성 포지션 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "position_not_found": {
                            "summary": "포지션 조회 불가 (심볼 없음)",
                            "value": {
                                "detail": "Position not found",
                                "symbol": "BTC-USDT-SWAP",
                                "user_id": "1709556958",
                                "reason": "No active position for this symbol"
                            }
                        },
                        "already_closed": {
                            "summary": "이미 청산된 포지션",
                            "value": {
                                "detail": "Position not found",
                                "symbol": "ETH-USDT-SWAP",
                                "reason": "Position was already closed or never existed",
                                "last_close_time": "2025-01-12T16:30:00Z"
                            }
                        }
                    }
                }
            }
        },
        503: {
            "description": "⏱️ 거래소 연결 오류 - OKX API 응답 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "exchange_connection_error": {
                            "summary": "OKX API 연결 실패",
                            "value": {
                                "detail": "Exchange connection error",
                                "exchange": "OKX",
                                "error": "Connection timeout",
                                "retry_suggestion": "Please try again in a few moments"
                            }
                        },
                        "network_timeout": {
                            "summary": "네트워크 타임아웃",
                            "value": {
                                "detail": "Network timeout while closing position",
                                "symbol": "BTC-USDT-SWAP",
                                "timeout_seconds": 30,
                                "suggestion": "Check network connection and retry"
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 내부 오류 - 청산 처리 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "position_service_error": {
                            "summary": "PositionService 오류",
                            "value": {
                                "detail": "Internal server error during position close",
                                "symbol": "BTC-USDT-SWAP",
                                "error": "Failed to create close order",
                                "suggestion": "Contact support if issue persists"
                            }
                        },
                        "redis_update_failed": {
                            "summary": "Redis 상태 업데이트 실패 (청산은 성공)",
                            "value": {
                                "detail": "Position closed but Redis update failed",
                                "order_id": "710582134659948544",
                                "warning": "State tracking may be inaccurate",
                                "suggestion": "Verify position status manually"
                            }
                        }
                    }
                }
            }
        }
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

    # Redis 클라이언트 초기화
    redis_client = get_redis_client()

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
#  (1) 알고주문 조회를 위한 헬퍼 함수
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
    await get_redis_client().hset(position_key, "sl_price", new_sl_price)
    await get_redis_client().hset(position_key, "get_sl", "false")

    return {
        "success": True,
        "symbol": symbol,
        "new_sl_price": new_sl_price,
    }
    
    
@router.post("/position/sl",
    response_model=dict,
    summary="스탑로스 주문 업데이트 (자동 포지션 청산 포함)",
    description="""
# 스탑로스 주문 업데이트 (자동 포지션 청산 포함)

포지션의 스탑로스(SL) 가격을 업데이트합니다. StopLossService를 사용하여 기존 SL 주문을 취소하고 새로운 SL 주문을 생성합니다. SL 가격이 유효하지 않을 경우 자동으로 시장가 청산을 수행합니다.

## 동작 방식

1. **사용자 식별**: user_id를 OKX UID로 변환
2. **파라미터 정규화**: side/order_side 정규화 (long → buy, short → sell)
3. **입력 검증**: order_side ≠ side 확인 (롱 포지션의 SL은 매도여야 함)
4. **Exchange 연결**: get_exchange_context로 OKX API 접근
5. **현재 포지션 조회**: private_get_account_positions로 활성 포지션 확인
6. **현재가 조회**: fetch_ticker로 시장가 확인
7. **SL 가격 유효성 검증**:
   - 롱 포지션: new_sl_price < current_price 확인
   - 숏 포지션: new_sl_price > current_price 확인
   - **Invalid한 경우**: 즉시 시장가 청산 실행 (자동 손절)
8. **기존 SL 데이터 조회**: Redis에서 old SL 정보 가져오기
9. **기존 알고주문 취소**: cancel_algo_orders로 기존 SL 주문 취소
10. **새로운 SL 주문 생성**: StopLossService.create_stop_loss_order
11. **Redis 상태 업데이트**:
    - SL 가격, order_id, entry_price 저장
    - Monitor key 생성 (주문 추적용)
12. **응답 반환**: 업데이트 결과 (success, order_id, new_sl_price)

## Query 파라미터

- **symbol** (string, required): 거래 심볼
  - 형식: BASE-QUOTE-SWAP
  - 예시: "BTC-USDT-SWAP", "ETH-USDT-SWAP"
  - 기본값: "BTC-USDT-SWAP"
- **side** (string, required): 포지션 방향
  - "long" 또는 "buy": 롱 포지션
  - "short" 또는 "sell": 숏 포지션
  - 기본값: "sell"
- **order_side** (string, required): SL 주문 방향
  - "buy": 매수 SL (숏 포지션용)
  - "sell": 매도 SL (롱 포지션용)
  - **중요**: side와 반대여야 함 (롱 포지션의 SL은 매도)
  - 기본값: "sell"
- **contracts_amount** (float, required): 포지션 크기 (계약 수)
  - 형식: 양수 실수
  - 단위: contracts
  - 예시: 0.1, 1.5, 10.0
- **new_sl_price** (float, required): 새로운 스탑로스 트리거 가격
  - 형식: USD 단위
  - 제약:
    - 롱 포지션: 현재가보다 낮아야 함
    - 숏 포지션: 현재가보다 높아야 함
  - 예시: 67000.0, 3200.5
- **position_qty** (float, optional): 포지션 수량 (contracts_amount와 동일)
  - 기본값: None (position에서 자동 조회)
- **user_id** (string, required): 사용자 ID
  - 텔레그램 ID 또는 OKX UID
  - 기본값: "1709556958"
- **algo_type** (string, optional): 알고주문 타입
  - "trigger": 트리거 주문 (스탑로스)
  - "conditional": 조건부 주문
  - 기본값: "trigger"
- **is_hedge** (bool, optional): 헷지 모드 여부
  - true: Hedge 모드 (long/short 분리)
  - false: One-way 모드 (net)
  - 기본값: false
- **order_type** (string, optional): 오더 타입
  - "sl": 스탑로스
  - "break_even": 손익분기점 SL
  - 기본값: "sl"

## SL 가격 유효성 검증 로직

### 롱 포지션 (side="long")
- **유효한 SL**: new_sl_price < current_price
- **Invalid한 SL**: new_sl_price >= current_price
  - 조치: 즉시 시장가 청산 (자동 손절)
  - Redis에 SL 가격 저장 후 close_position 호출
  - 텔레그램 알림 발송

### 숏 포지션 (side="short")
- **유효한 SL**: new_sl_price > current_price
- **Invalid한 SL**: new_sl_price <= current_price
  - 조치: 즉시 시장가 청산 (자동 손절)
  - Redis에 SL 가격 저장 후 close_position 호출
  - 텔레그램 알림 발송

## Redis 키 구조

### SL 데이터 키
**키**: `user:{user_id}:position:{symbol}:{side}:sl_data`
- trigger_price: 트리거 가격
- order_id: 알고주문 ID
- entry_price: 진입 가격
- get_sl: SL 설정 상태 ("true"/"false")

### Monitor 키
**키**: `monitor:user:{user_id}:{symbol}:order:{order_id}`
- status: 주문 상태 ("open")
- price: SL 가격
- position_side: 포지션 방향
- contracts_amount: 계약 수량
- order_type: 주문 타입 ("sl" 또는 "break_even")
- ordertime: 주문 생성 시간 (Unix timestamp)
- last_updated_time: 마지막 업데이트 시간
- last_updated_time_kr: KST 기준 시간

## 에러 처리 및 Fallback

### SL 주문 생성 실패 시
1. **Fallback 동작**: Redis에 SL 가격만 업데이트
2. **텔레그램 알림**: 관리자에게 실패 알림 발송
3. **응답**: success=false, error 메시지 포함

### 타임아웃 오류 (51149)
- 특별 처리: SL 가격은 저장되지만 주문 미생성 알림
- 수동 확인 필요

### 포지션 없음
- Redis에서 포지션 데이터 제거
- success=false 반환

## 사용 시나리오

-  **SL 가격 조정**: 시장 상황에 따라 손실 제한 가격 변경
-  **손익분기점 이동**: 수익 발생 시 SL을 진입가로 이동 (break_even)
-  **긴급 손절**: Invalid한 SL 입력 시 자동 시장가 청산
-  **트레일링 스탑**: 가격 상승 시 SL을 따라 올리기
-  **리스크 관리**: 변동성 증가 시 SL을 더 가깝게 설정
-  **자동 SL 업데이트**: 전략 봇이 자동으로 SL 조정

## 예시 요청

```bash
# 롱 포지션 SL 업데이트 (유효한 가격)
curl -X POST "http://localhost:8000/order/position/sl" \\
     -H "Content-Type: application/json" \\
     -d "symbol=BTC-USDT-SWAP&side=long&order_side=sell&contracts_amount=0.1&new_sl_price=67000.0&user_id=1709556958&algo_type=trigger&is_hedge=false&order_type=sl"

# 숏 포지션 SL 업데이트 (손익분기점)
curl -X POST "http://localhost:8000/order/position/sl" \\
     -H "Content-Type: application/json" \\
     -d "symbol=ETH-USDT-SWAP&side=short&order_side=buy&contracts_amount=1.0&new_sl_price=3200.0&position_qty=1.0&user_id=1709556958&algo_type=trigger&order_type=break_even"

# 헷지 모드 롱 포지션 SL
curl -X POST "http://localhost:8000/order/position/sl" \\
     -H "Content-Type: application/json" \\
     -d "symbol=SOL-USDT-SWAP&side=buy&order_side=sell&contracts_amount=2.0&new_sl_price=140.0&user_id=1709556958&is_hedge=true"
```
""",
    responses={
        200: {
            "description": " 스탑로스 업데이트 성공 - 새로운 SL 주문 생성됨",
            "content": {
                "application/json": {
                    "examples": {
                        "sl_updated_successfully": {
                            "summary": "SL 업데이트 성공 (롱 포지션)",
                            "value": {
                                "success": True,
                                "symbol": "BTC-USDT-SWAP",
                                "new_sl_price": 67000.0,
                                "order_id": "780912345678901234"
                            }
                        },
                        "break_even_sl": {
                            "summary": "손익분기점 SL 설정 (숏 포지션)",
                            "value": {
                                "success": True,
                                "symbol": "ETH-USDT-SWAP",
                                "new_sl_price": 3200.0,
                                "order_id": "780923456789012345"
                            }
                        },
                        "hedge_mode_sl": {
                            "summary": "헷지 모드 SL 업데이트",
                            "value": {
                                "success": True,
                                "symbol": "SOL-USDT-SWAP",
                                "new_sl_price": 140.0,
                                "order_id": "780934567890123456"
                            }
                        },
                        "invalid_sl_market_close": {
                            "summary": "Invalid SL → 자동 시장가 청산",
                            "value": {
                                "success": True,
                                "symbol": "BTC-USDT-SWAP",
                                "message": "Invalid SL price - position closed at market"
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": " 잘못된 요청 - 유효성 검증 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_side_combination": {
                            "summary": "잘못된 side 조합 (SL 방향 오류)",
                            "value": {
                                "detail": "롱 포지션의 SL은 sell여야 합니다",
                                "side": "long",
                                "order_side": "buy",
                                "expected_order_side": "sell",
                                "reason": "SL must be opposite of position direction"
                            }
                        },
                        "invalid_short_sl": {
                            "summary": "숏 포지션 SL 방향 오류",
                            "value": {
                                "detail": "숏 포지션의 SL은 buy여야 합니다",
                                "side": "short",
                                "order_side": "sell",
                                "expected_order_side": "buy",
                                "reason": "Short position SL must be a buy order"
                            }
                        },
                        "zero_contracts": {
                            "summary": "계약 수량 0 (Invalid amount)",
                            "value": {
                                "detail": "Invalid contracts amount",
                                "contracts_amount": 0.0,
                                "reason": "Contracts amount must be greater than 0"
                            }
                        }
                    }
                }
            }
        },
        401: {
            "description": " 인증 오류 - API 키 없음 또는 만료됨",
            "content": {
                "application/json": {
                    "examples": {
                        "authentication_error": {
                            "summary": "API 키 인증 실패",
                            "value": {
                                "detail": "Authentication error",
                                "user_id": "1709556958",
                                "reason": "Invalid API credentials or expired session"
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 포지션 없음 - 활성 포지션 조회 불가",
            "content": {
                "application/json": {
                    "examples": {
                        "no_active_position": {
                            "summary": "활성화된 포지션 없음",
                            "value": {
                                "success": False,
                                "message": "활성화 된 포지션을 찾을 수 없습니다",
                                "symbol": "BTC-USDT-SWAP",
                                "reason": "No active position for this symbol"
                            }
                        },
                        "position_already_closed": {
                            "summary": "포지션 이미 청산됨",
                            "value": {
                                "success": False,
                                "message": "활성화 된 포지션을 찾을 수 없습니다",
                                "symbol": "ETH-USDT-SWAP",
                                "reason": "Position was closed before SL update"
                            }
                        }
                    }
                }
            }
        },
        503: {
            "description": "⏱️ 거래소 연결 오류 - OKX API 응답 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "exchange_connection_error": {
                            "summary": "OKX API 연결 실패",
                            "value": {
                                "detail": "Exchange connection error",
                                "exchange": "OKX",
                                "error": "Connection timeout",
                                "retry_suggestion": "Please try again in a few moments"
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 내부 오류 - SL 주문 생성 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "sl_order_creation_failed": {
                            "summary": "SL 주문 생성 실패 (Fallback: Redis 저장)",
                            "value": {
                                "success": False,
                                "symbol": "BTC-USDT-SWAP",
                                "new_sl_price": 67000.0,
                                "message": "스탑로스 주문 생성 실패: Order creation error",
                                "error": "Order creation error",
                                "fallback": "SL price saved to Redis only"
                            }
                        },
                        "order_timeout": {
                            "summary": "주문 생성 타임아웃 (OKX 51149)",
                            "value": {
                                "success": False,
                                "symbol": "ETH-USDT-SWAP",
                                "new_sl_price": 3200.0,
                                "message": "스탑로스 주문 생성 실패: Order timed out",
                                "error": "Order timed out",
                                "telegram_alert": "Timeout notification sent to admin"
                            }
                        },
                        "stop_loss_service_error": {
                            "summary": "StopLossService 오류",
                            "value": {
                                "success": False,
                                "symbol": "SOL-USDT-SWAP",
                                "message": "스탑로스 주문 생성 실패: Internal error",
                                "error": "Internal error",
                                "suggestion": "Check logs and retry"
                            }
                        }
                    }
                }
            }
        }
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

    # Redis 클라이언트 초기화
    redis_client = get_redis_client()

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
                await get_redis_client().hset(monitor_key, mapping=monitor_data)

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
    summary="단일 주문 취소 (일반 + 알고주문)",
    description="""
# 단일 주문 취소 (일반 + 알고주문)

지정한 주문 ID로 진행 중인 주문을 취소합니다. OrderService를 사용하여 일반 주문 및 알고리즘 주문(트리거/조건부) 모두 처리합니다.

## 동작 방식

1. **사용자 식별**: user_id를 OKX UID로 변환
2. **Exchange 연결**: get_exchange_context로 OKX API 접근
3. **주문 취소 시도**: OrderService.cancel_order 호출
   - symbol 제공 시: cancel_order(order_id, symbol)로 빠른 취소
   - symbol 미제공 시: 주문 조회 후 취소 (느림, 권장하지 않음)
4. **응답 반환**: 취소 성공 여부 (success: true/false)

## OrderService.cancel_order 로직

1. **Symbol 기반 취소 (권장)**:
   - exchange.cancel_order(order_id, symbol) 시도
   - 빠르고 정확한 취소 보장
2. **Fallback: 주문 조회 후 취소**:
   - symbol 미제공 시 fetch_order로 주문 정보 조회
   - 조회된 symbol로 재시도
   - 조회 실패 시 모든 열린 주문 검색 (매우 느림)

## Path 파라미터

- **order_id** (string, required): 취소할 주문의 고유 ID
  - 형식: OKX ordId (예: "710582134659948544")
  - 일반 주문 ID와 알고주문 ID 모두 지원

## Query 파라미터

- **user_id** (string, required): 사용자 ID
  - 텔레그램 ID 또는 OKX UID
  - 예시: "1709556958"
- **symbol** (string, optional): 주문의 거래쌍 심볼
  - 형식: BASE-QUOTE-SWAP
  - 예시: "BTC-USDT-SWAP"
  - **권장**: 성능 향상을 위해 항상 제공하는 것이 좋음
  - 미제공 시: 주문 조회 오버헤드 발생

## 주문 취소 제한사항

### 취소 가능한 주문 상태
- **open**: 대기 중인 미체결 주문
- **partially_filled**: 부분 체결된 주문 (남은 수량만 취소)

### 취소 불가능한 주문 상태
- **filled**: 이미 완전히 체결된 주문
- **canceled**: 이미 취소된 주문
- **rejected**: 거래소에서 거부된 주문
- **expired**: 만료된 주문

## 사용 시나리오

-  **주문 정정**: 가격/수량 변경 필요 시 기존 주문 취소 후 재생성
- ⏱️ **타임아웃 방지**: 긴 시간 대기 중인 지정가 주문 취소
-  **전략 변경**: 시장 상황 변화에 따른 대기 주문 취소
-  **정확한 취소**: symbol 제공으로 빠른 취소 실행
-  **재주문**: 실수로 잘못 생성한 주문 즉시 취소
-  **리스크 관리**: 위험한 대기 주문 긴급 취소

## 예시 요청

```bash
# symbol 제공 (권장 - 빠름)
curl -X DELETE "http://localhost:8000/order/710582134659948544?user_id=1709556958&symbol=BTC-USDT-SWAP"

# symbol 미제공 (느림 - 권장하지 않음)
curl -X DELETE "http://localhost:8000/order/710582134659948544?user_id=1709556958"

# 알고주문 취소
curl -X DELETE "http://localhost:8000/order/780912345678901234?user_id=1709556958&symbol=ETH-USDT-SWAP"
```
""",
    responses={
        200: {
            "description": " 주문 취소 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "cancel_success": {
                            "summary": "주문 취소 성공 (symbol 제공)",
                            "value": {
                                "success": True,
                                "order_id": "710582134659948544",
                                "status": "canceled"
                            }
                        },
                        "cancel_success_without_symbol": {
                            "summary": "주문 취소 성공 (symbol 미제공)",
                            "value": {
                                "success": True,
                                "order_id": "710582234759958645",
                                "status": "canceled"
                            }
                        },
                        "algo_order_cancel": {
                            "summary": "알고주문 취소 성공",
                            "value": {
                                "success": True,
                                "order_id": "780912345678901234",
                                "status": "canceled"
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": " 주문 취소 실패 - 취소 불가능한 상태",
            "content": {
                "application/json": {
                    "examples": {
                        "order_already_filled": {
                            "summary": "이미 체결된 주문 (취소 불가)",
                            "value": {
                                "success": False,
                                "order_id": "710582134659948544",
                                "status": "failed",
                                "reason": "Order already filled",
                                "order_status": "filled"
                            }
                        },
                        "order_already_canceled": {
                            "summary": "이미 취소된 주문",
                            "value": {
                                "success": False,
                                "order_id": "710582234759958645",
                                "status": "failed",
                                "reason": "Order already canceled",
                                "order_status": "canceled"
                            }
                        },
                        "invalid_order_id": {
                            "summary": "잘못된 주문 ID 형식",
                            "value": {
                                "success": False,
                                "order_id": "invalid_id",
                                "status": "failed",
                                "reason": "Invalid order ID format"
                            }
                        }
                    }
                }
            }
        },
        401: {
            "description": " 인증 오류 - API 키 없음 또는 만료됨",
            "content": {
                "application/json": {
                    "examples": {
                        "authentication_error": {
                            "summary": "API 키 인증 실패",
                            "value": {
                                "detail": "Authentication error",
                                "user_id": "1709556958",
                                "reason": "Invalid API credentials or expired session"
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 주문 없음 - 주문 ID 조회 불가",
            "content": {
                "application/json": {
                    "examples": {
                        "order_not_found": {
                            "summary": "주문 조회 실패 (없는 ID)",
                            "value": {
                                "success": False,
                                "order_id": "999999999999999999",
                                "status": "failed",
                                "reason": "Order not found",
                                "suggestion": "Check order ID or order may have been filled/canceled"
                            }
                        },
                        "order_expired": {
                            "summary": "만료된 주문 (취소 불가)",
                            "value": {
                                "success": False,
                                "order_id": "710582134659948544",
                                "status": "failed",
                                "reason": "Order expired",
                                "order_status": "expired"
                            }
                        }
                    }
                }
            }
        },
        503: {
            "description": "⏱️ 거래소 연결 오류 - OKX API 응답 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "exchange_connection_error": {
                            "summary": "OKX API 연결 실패",
                            "value": {
                                "detail": "Exchange connection error",
                                "exchange": "OKX",
                                "error": "Connection timeout",
                                "retry_suggestion": "Please try again in a few moments"
                            }
                        },
                        "cancel_timeout": {
                            "summary": "주문 취소 타임아웃",
                            "value": {
                                "success": False,
                                "order_id": "710582134659948544",
                                "status": "failed",
                                "reason": "Cancel request timeout",
                                "suggestion": "Verify order status manually"
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 내부 오류 - 취소 처리 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "order_service_error": {
                            "summary": "OrderService 오류",
                            "value": {
                                "success": False,
                                "order_id": "710582134659948544",
                                "status": "failed",
                                "error": "Internal error during order cancellation",
                                "suggestion": "Contact support if issue persists"
                            }
                        },
                        "exchange_error": {
                            "summary": "거래소 오류 응답",
                            "value": {
                                "success": False,
                                "order_id": "710582234759958645",
                                "status": "failed",
                                "error": "Exchange rejected cancel request",
                                "exchange_code": "50000",
                                "suggestion": "Check exchange error code documentation"
                            }
                        }
                    }
                }
            }
        }
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
    summary="심볼의 모든 주문 일괄 취소 (일반 + 알고주문 + Side 필터)",
    description="""
# 심볼의 모든 주문 일괄 취소 (일반 + 알고주문 + Side 필터)

지정된 거래쌍의 모든 미체결 주문을 일괄 취소합니다. OrderService와 AlgoOrderService를 사용하여 일반 주문과 알고리즘 주문(트리거/조건부) 모두 처리하며, 선택적으로 side 필터링이 가능합니다.

## 동작 방식

1. **사용자 식별**: user_id를 OKX UID로 변환
2. **Side 정규화** (선택사항):
   - side=BUY(long): order_side_for_filter="sell", pos_side_for_algo="long"
   - side=SELL(short): order_side_for_filter="buy", pos_side_for_algo="short"
3. **Exchange 연결**: get_exchange_context로 OKX API 접근
4. **열린 주문 조회**: fetch_open_orders(symbol)로 모든 미체결 주문 가져오기
5. **Side 필터링** (선택사항): order_side_for_filter로 주문 필터
6. **알고주문 취소**: AlgoOrderService.cancel_algo_orders_for_symbol
   - pos_side 기준으로 알고주문 취소 (SL, TP 등)
7. **일반 주문 취소**: OrderService.cancel_all_orders
   - 모든 열린 일반 주문 취소
8. **Redis 업데이트**:
   - closed_orders 키에 취소된 주문 저장
   - open_orders 키에서 취소된 주문 제거
9. **응답 반환**: 취소 성공 여부 및 주문 ID 리스트

## Path 파라미터

- **symbol** (string, required): 거래쌍 심볼
  - 형식: BASE-QUOTE-SWAP
  - 예시: "BTC-USDT-SWAP", "ETH-USDT-SWAP"

## Query 파라미터

- **user_id** (string, required): 사용자 ID
  - 텔레그램 ID 또는 OKX UID
  - 예시: "1709556958"
- **side** (OrderSide, optional): 취소할 주문의 포지션 방향
  - **OrderSide.BUY** (또는 "long"): 롱 포지션 관련 주문만 취소
    - 취소 대상: sell 주문 (롱 청산용) + long 알고주문
  - **OrderSide.SELL** (또는 "short"): 숏 포지션 관련 주문만 취소
    - 취소 대상: buy 주문 (숏 청산용) + short 알고주문
  - **미제공 시**: 모든 주문 취소 (양방향)

## Side 파라미터 동작 로직

### side=BUY (롱 포지션)
- **order_side_for_filter**: "sell" → 롱 포지션 청산용 매도 주문 취소
- **pos_side_for_algo**: "long" → 롱 포지션 알고주문 취소 (SL, TP)
- **사용 시나리오**: 롱 포지션 완전 종료 전 모든 관련 주문 정리

### side=SELL (숏 포지션)
- **order_side_for_filter**: "buy" → 숏 포지션 청산용 매수 주문 취소
- **pos_side_for_algo**: "short" → 숏 포지션 알고주문 취소 (SL, TP)
- **사용 시나리오**: 숏 포지션 완전 종료 전 모든 관련 주문 정리

### side 미제공
- **모든 주문 취소**: 롱/숏 구분 없이 해당 심볼의 모든 주문 취소
- **사용 시나리오**: 거래쌍 전체 정리, 긴급 청산 준비

## Redis 키 구조

### Closed Orders 키
**키**: `user:{user_id}:closed_orders`
- 타입: List (RPUSH)
- 값: JSON 직렬화된 주문 데이터
- 용도: 취소된 주문 히스토리 추적

### Open Orders 키
**키**: `user:{user_id}:open_orders`
- 타입: List
- 업데이트: side 필터 시 특정 side 주문만 제거, 전체 취소 시 키 삭제
- 용도: 활성 주문 목록 관리

## 취소 대상 주문 유형

### 일반 주문 (Regular Orders)
- 시장가 주문 (market)
- 지정가 주문 (limit)
- 부분 체결된 주문 (partially filled)

### 알고리즘 주문 (Algo Orders)
- 스탑로스 주문 (stop-loss)
- 테이크프로핏 주문 (take-profit)
- 트리거 주문 (trigger orders)
- 조건부 주문 (conditional orders)

## 사용 시나리오

- 🧹 **전체 정리**: 거래쌍의 모든 대기 주문 일괄 취소
-  **포지션별 정리**: 롱/숏 포지션 관련 주문만 선택적 취소
-  **긴급 청산 준비**: 포지션 청산 전 모든 관련 주문 정리
-  **전략 변경**: 새로운 전략 적용 전 기존 주문 전체 취소
-  **재시작**: 봇 재시작 시 기존 주문 정리
-  **리스크 관리**: 시장 변동성 증가 시 대기 주문 일괄 제거

## 예시 요청

```bash
# 모든 주문 취소 (side 미제공)
curl -X DELETE "http://localhost:8000/order/cancel-all/BTC-USDT-SWAP?user_id=1709556958"

# 롱 포지션 관련 주문만 취소
curl -X DELETE "http://localhost:8000/order/cancel-all/ETH-USDT-SWAP?user_id=1709556958&side=buy"

# 숏 포지션 관련 주문만 취소
curl -X DELETE "http://localhost:8000/order/cancel-all/SOL-USDT-SWAP?user_id=1709556958&side=sell"
```
""",
    responses={
        200: {
            "description": " 주문 취소 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "all_orders_canceled": {
                            "summary": "모든 주문 취소 성공 (side 미제공)",
                            "value": {
                                "success": True,
                                "message": "Successfully cancelled 5 orders",
                                "canceled_orders": [
                                    "710582134659948544",
                                    "710582234759958645",
                                    "780912345678901234",
                                    "780923456789012345",
                                    "710582334859968746"
                                ],
                                "failed_orders": None
                            }
                        },
                        "long_position_orders_canceled": {
                            "summary": "롱 포지션 주문만 취소 (side=buy)",
                            "value": {
                                "success": True,
                                "message": "Successfully cancelled 2 orders",
                                "canceled_orders": [
                                    "710582134659948544",
                                    "780912345678901234"
                                ],
                                "failed_orders": None
                            }
                        },
                        "short_position_orders_canceled": {
                            "summary": "숏 포지션 주문만 취소 (side=sell)",
                            "value": {
                                "success": True,
                                "message": "Successfully cancelled 3 orders",
                                "canceled_orders": [
                                    "710582234759958645",
                                    "780923456789012345",
                                    "710582334859968746"
                                ],
                                "failed_orders": None
                            }
                        },
                        "no_orders_to_cancel": {
                            "summary": "취소할 주문 없음",
                            "value": {
                                "success": True,
                                "message": "Successfully cancelled 0 orders",
                                "canceled_orders": None,
                                "failed_orders": None
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": " 잘못된 요청 - 유효성 검증 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_symbol_format": {
                            "summary": "잘못된 심볼 형식",
                            "value": {
                                "success": False,
                                "message": "Invalid symbol format",
                                "detail": "Symbol must be in BASE-QUOTE-SWAP format",
                                "example": "BTC-USDT-SWAP"
                            }
                        },
                        "invalid_side": {
                            "summary": "잘못된 side 파라미터",
                            "value": {
                                "success": False,
                                "message": "Invalid side parameter",
                                "detail": "Side must be 'buy' or 'sell'",
                                "provided": "invalid_side"
                            }
                        }
                    }
                }
            }
        },
        401: {
            "description": " 인증 오류 - API 키 없음 또는 만료됨",
            "content": {
                "application/json": {
                    "examples": {
                        "authentication_error": {
                            "summary": "API 키 인증 실패",
                            "value": {
                                "detail": "Authentication error",
                                "user_id": "1709556958",
                                "reason": "Invalid API credentials or expired session"
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 주문 없음 - 취소할 주문이 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "no_open_orders": {
                            "summary": "열린 주문 없음",
                            "value": {
                                "success": True,
                                "message": "Successfully cancelled 0 orders",
                                "canceled_orders": None,
                                "failed_orders": None,
                                "info": "No open orders found for this symbol"
                            }
                        }
                    }
                }
            }
        },
        503: {
            "description": "⏱️ 거래소 연결 오류 - OKX API 응답 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "exchange_connection_error": {
                            "summary": "OKX API 연결 실패",
                            "value": {
                                "detail": "Exchange connection error",
                                "exchange": "OKX",
                                "error": "Connection timeout",
                                "retry_suggestion": "Please try again in a few moments"
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 내부 오류 - 일괄 취소 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "partial_cancellation_failure": {
                            "summary": "일부 주문 취소 실패",
                            "value": {
                                "success": False,
                                "message": "Failed to cancel orders: Partial failure",
                                "canceled_orders": [
                                    "710582134659948544",
                                    "710582234759958645"
                                ],
                                "failed_orders": [
                                    "780912345678901234"
                                ],
                                "error": "Some orders could not be canceled"
                            }
                        },
                        "redis_update_failed": {
                            "summary": "Redis 업데이트 실패 (취소는 성공)",
                            "value": {
                                "success": True,
                                "message": "Orders canceled but Redis update failed",
                                "canceled_orders": [
                                    "710582134659948544"
                                ],
                                "warning": "State tracking may be inaccurate"
                            }
                        },
                        "complete_cancellation_failure": {
                            "summary": "전체 취소 실패",
                            "value": {
                                "success": False,
                                "message": "Failed to cancel orders: Connection error",
                                "canceled_orders": None,
                                "failed_orders": None,
                                "error": "Complete failure during cancellation"
                            }
                        }
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

                    async with get_redis_client().pipeline() as pipe:
                        # Save cancelled orders
                        for order in open_orders:
                            await pipe.rpush(closed_orders_key, json.dumps(order))

                        # Update open orders list
                        if order_side_for_filter:
                            # Remove only specific side orders
                            current_orders = await get_redis_client().lrange(open_orders_key, 0, -1)
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
    summary="알고리즘 주문 일괄 취소 (SL/TP/트리거/조건부)",
    description="""
# 알고리즘 주문 일괄 취소 (SL/TP/트리거/조건부)

특정 심볼의 모든 알고리즘 주문을 일괄 취소합니다. TriggerCancelClient를 사용하여 트리거 주문과 조건부 주문을 효율적으로 취소합니다.

## 동작 방식

1. **사용자 식별**: user_id로 API 키 조회
2. **TriggerCancelClient 생성**: API 자격증명으로 클라이언트 초기화
3. **알고주문 취소**: cancel_all_trigger_orders 호출
   - symbol, side, algo_type 조건으로 필터링
4. **응답 반환**: 취소 완료 메시지

## Path 파라미터

- **symbol** (string, required): 거래쌍 심볼
  - 형식: BASE-QUOTE-SWAP
  - 예시: "BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"

## Query 파라미터

- **user_id** (string, optional): 사용자 ID
  - 텔레그램 ID 또는 OKX UID
  - 기본값: "1709556958"
- **side** (string, optional): 포지션 방향 필터
  - "buy" (또는 "long"): 롱 포지션 알고주문만 취소
  - "sell" (또는 "short"): 숏 포지션 알고주문만 취소
  - **미제공 시**: 모든 방향의 알고주문 취소
- **algo_type** (string, optional): 알고리즘 주문 타입
  - "trigger": 트리거 주문 (스탑로스, 테이크프로핏)
  - "conditional": 조건부 주문 (TWAP, Iceberg 등)
  - 기본값: "trigger"

## 알고리즘 주문 유형

### 트리거 주문 (algo_type="trigger")
- **Stop Loss (SL)**: 손실 제한 주문
- **Take Profit (TP)**: 이익 실현 주문
- **Stop Market**: 스탑 가격 도달 시 시장가 주문
- **Stop Limit**: 스탑 가격 도달 시 지정가 주문

### 조건부 주문 (algo_type="conditional")
- **TWAP**: Time-Weighted Average Price (시간 가중 평균가 주문)
- **Iceberg**: 부분 체결 숨김 주문
- **Grid**: 그리드 트레이딩 주문

## TriggerCancelClient 기능

- **일괄 취소**: symbol + side + algo_type 조건으로 필터링된 모든 알고주문 취소
- **배치 처리**: 여러 알고주문을 효율적으로 일괄 취소
- **OKX API 직접 호출**: CCXT가 아닌 OKX REST API 직접 사용

## 사용 시나리오

- 🧹 **전체 알고주문 정리**: 특정 심볼의 모든 SL/TP 주문 취소
-  **포지션별 정리**: 롱 또는 숏 포지션 알고주문만 선택적 취소
-  **긴급 정리**: 시장 급변 시 모든 자동 주문 제거
-  **전략 변경**: 새로운 SL/TP 설정 전 기존 알고주문 제거
-  **재설정**: 알고주문 재생성 전 기존 주문 정리
-  **리스크 관리**: 변동성 증가 시 자동 손절/익절 주문 제거

## 예시 요청

```bash
# 모든 알고주문 취소 (side 미제공)
curl -X DELETE "http://localhost:8000/order/algo-orders/BTC-USDT-SWAP?user_id=1709556958&algo_type=trigger"

# 롱 포지션 알고주문만 취소
curl -X DELETE "http://localhost:8000/order/algo-orders/ETH-USDT-SWAP?user_id=1709556958&side=buy&algo_type=trigger"

# 숏 포지션 조건부 주문 취소
curl -X DELETE "http://localhost:8000/order/algo-orders/SOL-USDT-SWAP?user_id=1709556958&side=sell&algo_type=conditional"
```
""",
    responses={
        200: {
            "description": " 알고리즘 주문 취소 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "all_algo_canceled": {
                            "summary": "모든 알고주문 취소 성공",
                            "value": {
                                "status": "success",
                                "message": "BTC-USDT-SWAP 심볼에 대한 모든 알고리즘 주문 취소 완료"
                            }
                        },
                        "long_algo_canceled": {
                            "summary": "롱 포지션 알고주문만 취소",
                            "value": {
                                "status": "success",
                                "message": "ETH-USDT-SWAP 심볼에 대한 모든 알고리즘 주문 취소 완료"
                            }
                        },
                        "short_conditional_canceled": {
                            "summary": "숏 포지션 조건부 주문 취소",
                            "value": {
                                "status": "success",
                                "message": "SOL-USDT-SWAP 심볼에 대한 모든 알고리즘 주문 취소 완료"
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": " 잘못된 요청 - 유효성 검증 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_algo_type": {
                            "summary": "잘못된 algo_type",
                            "value": {
                                "detail": "Invalid algo_type",
                                "algo_type": "invalid_type",
                                "valid_values": ["trigger", "conditional"]
                            }
                        }
                    }
                }
            }
        },
        401: {
            "description": " 인증 오류 - API 키 없음 또는 만료됨",
            "content": {
                "application/json": {
                    "examples": {
                        "authentication_error": {
                            "summary": "API 키 인증 실패",
                            "value": {
                                "detail": "Authentication error",
                                "user_id": "1709556958",
                                "reason": "Invalid API credentials"
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 주문 없음 - 취소할 알고주문이 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "no_algo_orders": {
                            "summary": "알고주문 없음",
                            "value": {
                                "status": "success",
                                "message": "No algo orders to cancel",
                                "symbol": "BTC-USDT-SWAP"
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 내부 오류 - 알고주문 취소 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "trigger_cancel_error": {
                            "summary": "TriggerCancelClient 오류",
                            "value": {
                                "detail": "Failed to cancel algo orders: Internal error",
                                "symbol": "BTC-USDT-SWAP",
                                "error": "TriggerCancelClient initialization failed"
                            }
                        },
                        "okx_api_error": {
                            "summary": "OKX API 오류",
                            "value": {
                                "detail": "OKX API error during cancellation",
                                "symbol": "ETH-USDT-SWAP",
                                "exchange_code": "50000",
                                "suggestion": "Check OKX API status"
                            }
                        }
                    }
                }
            }
        }
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
    summary="알고리즘 주문 상세 조회 (트리거/조건부 + 활성/히스토리)",
    description="""
# 알고리즘 주문 상세 조회 (트리거/조건부 + 활성/히스토리)

OKX의 알고리즘 주문(트리거 주문, 조건부 주문) 정보를 상세히 조회합니다. 활성 주문(pending)과 히스토리 주문(history)을 모두 검색하여 정보를 반환합니다.

## 동작 방식

1. **사용자 식별**: user_id를 OKX UID로 변환
2. **Exchange 연결**: get_exchange_context로 OKX API 접근
3. **파라미터 설정**: algo_type에 따라 ordType 결정
   - algo_type="trigger" → ordType="trigger"
   - algo_type="conditional" → ordType="conditional"
4. **활성 주문 조회**: privateGetTradeOrdersAlgoPending 호출
   - symbol, algoId, ordType 조건으로 검색
5. **히스토리 주문 조회** (활성 주문 없을 시):
   - privateGetTradeOrdersAlgoHistory 호출
   - 완료/취소된 알고주문 검색
6. **상태 매핑**: OKX state → 표준 status 변환
7. **응답 반환**: 주문 상태 및 상세 정보

## Path 파라미터

- **order_id** (string, required): 알고리즘 주문 ID
  - 형식: OKX algoId (예: "780912345678901234")
  - 트리거 주문 및 조건부 주문 ID 모두 지원

## Query 파라미터

- **symbol** (string, required): 거래쌍 심볼
  - 형식: BASE-QUOTE-SWAP
  - 예시: "BTC-USDT-SWAP"
- **user_id** (string, required): 사용자 ID
  - 텔레그램 ID 또는 OKX UID
  - 예시: "1709556958"
- **algo_type** (string, required): 알고리즘 주문 타입
  - "trigger": 트리거 주문 (SL, TP)
  - "conditional": 조건부 주문 (TWAP, Iceberg)

## OKX 상태 매핑

### Pending 상태 (활성 주문)
- **live**: 대기 중 → status="open"
- **effective**: 트리거 대기 중 → status="open"
- **order_failed**: 주문 실패 → status="rejected"

### History 상태 (완료/취소된 주문)
- **filled**: 완전 체결 → status="filled"
- **canceled**: 사용자 취소 → status="canceled"
- **expired**: 만료됨 → status="expired"
- **partially_filled**: 부분 체결 후 취소 → status="partially_filled"

## 응답 데이터 구조

- **status** (string): 표준 주문 상태
  - open, filled, canceled, rejected, expired, partially_filled
- **info** (object): OKX 원본 주문 정보
  - algoId: 알고주문 ID
  - instId: 거래쌍 심볼
  - ordType: 주문 타입 (trigger/conditional)
  - state: OKX 원본 상태
  - triggerPx: 트리거 가격 (트리거 주문)
  - orderPx: 주문 가격
  - sz: 주문 크기
  - posSide: 포지션 방향 (long/short/net)
  - actualSz: 실제 체결 수량
  - actualPx: 실제 체결 가격
- **data** (array): 추가 데이터 (있을 경우)
- **state** (string): OKX 원본 상태값

## 사용 시나리오

-  **SL/TP 확인**: 설정된 스탑로스/테이크프로핏 주문 상태 확인
-  **트리거 주문 모니터링**: 트리거 대기 중인 주문 추적
- ⏱️ **체결 상태 확인**: 알고주문이 체결되었는지 확인
-  **취소 확인**: 알고주문 취소 여부 검증
-  **히스토리 조회**: 과거 알고주문 실행 내역 확인
-  **정확한 주문 정보**: algoId로 특정 알고주문 상세 정보 조회

## 예시 요청

```bash
# 트리거 주문 조회 (SL/TP)
curl "http://localhost:8000/order/algo/780912345678901234?symbol=BTC-USDT-SWAP&user_id=1709556958&algo_type=trigger"

# 조건부 주문 조회 (TWAP, Iceberg)
curl "http://localhost:8000/order/algo/780923456789012345?symbol=ETH-USDT-SWAP&user_id=1709556958&algo_type=conditional"

# 히스토리 알고주문 조회
curl "http://localhost:8000/order/algo/780934567890123456?symbol=SOL-USDT-SWAP&user_id=1709556958&algo_type=trigger"
```
""",
    responses={
        200: {
            "description": " 알고리즘 주문 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "active_trigger_order": {
                            "summary": "활성 트리거 주문 (대기 중)",
                            "value": {
                                "status": "open",
                                "info": {
                                    "algoId": "780912345678901234",
                                    "instId": "BTC-USDT-SWAP",
                                    "ordType": "trigger",
                                    "state": "effective",
                                    "triggerPx": "67000.0",
                                    "orderPx": "67000.0",
                                    "sz": "0.1",
                                    "posSide": "net",
                                    "actualSz": "0",
                                    "actualPx": "0"
                                },
                                "data": [],
                                "state": "effective"
                            }
                        },
                        "filled_trigger_order": {
                            "summary": "체결된 트리거 주문",
                            "value": {
                                "status": "filled",
                                "info": {
                                    "algoId": "780923456789012345",
                                    "instId": "ETH-USDT-SWAP",
                                    "ordType": "trigger",
                                    "state": "filled",
                                    "triggerPx": "3200.0",
                                    "orderPx": "3200.0",
                                    "sz": "1.0",
                                    "posSide": "long",
                                    "actualSz": "1.0",
                                    "actualPx": "3201.5"
                                },
                                "data": [],
                                "state": "filled"
                            }
                        },
                        "canceled_algo_order": {
                            "summary": "취소된 알고주문",
                            "value": {
                                "status": "canceled",
                                "info": {
                                    "algoId": "780934567890123456",
                                    "instId": "SOL-USDT-SWAP",
                                    "ordType": "trigger",
                                    "state": "canceled",
                                    "triggerPx": "140.0",
                                    "orderPx": "140.0",
                                    "sz": "2.0",
                                    "posSide": "short",
                                    "actualSz": "0",
                                    "actualPx": "0"
                                },
                                "data": [],
                                "state": "canceled"
                            }
                        },
                        "conditional_order": {
                            "summary": "조건부 주문 (TWAP)",
                            "value": {
                                "status": "open",
                                "info": {
                                    "algoId": "780945678901234567",
                                    "instId": "BTC-USDT-SWAP",
                                    "ordType": "conditional",
                                    "state": "live",
                                    "sz": "1.0",
                                    "posSide": "net",
                                    "actualSz": "0.3",
                                    "actualPx": "67500.0"
                                },
                                "data": [],
                                "state": "live"
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": " 잘못된 요청 - 유효성 검증 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_algo_type": {
                            "summary": "잘못된 algo_type",
                            "value": {
                                "detail": "Invalid algo_type",
                                "algo_type": "invalid_type",
                                "valid_values": ["trigger", "conditional"]
                            }
                        },
                        "missing_symbol": {
                            "summary": "symbol 파라미터 누락",
                            "value": {
                                "detail": "Missing required parameter: symbol",
                                "required_params": ["symbol", "user_id", "algo_type"]
                            }
                        }
                    }
                }
            }
        },
        401: {
            "description": " 인증 오류 - API 키 없음 또는 만료됨",
            "content": {
                "application/json": {
                    "examples": {
                        "authentication_error": {
                            "summary": "API 키 인증 실패",
                            "value": {
                                "detail": "Authentication error",
                                "user_id": "1709556958",
                                "reason": "Invalid API credentials or expired session"
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 주문 없음 - 알고주문 조회 불가",
            "content": {
                "application/json": {
                    "examples": {
                        "algo_order_not_found": {
                            "summary": "알고주문 조회 실패",
                            "value": {
                                "detail": "Algo order not found",
                                "algoId": "999999999999999999",
                                "symbol": "BTC-USDT-SWAP",
                                "algo_type": "trigger",
                                "suggestion": "Check algoId or order may have been canceled/filled long ago"
                            }
                        },
                        "order_expired": {
                            "summary": "만료된 알고주문",
                            "value": {
                                "status": "expired",
                                "info": {
                                    "algoId": "780912345678901234",
                                    "state": "expired"
                                },
                                "message": "Algo order has expired"
                            }
                        }
                    }
                }
            }
        },
        503: {
            "description": "⏱️ 거래소 연결 오류 - OKX API 응답 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "exchange_connection_error": {
                            "summary": "OKX API 연결 실패",
                            "value": {
                                "detail": "Exchange connection error",
                                "exchange": "OKX",
                                "error": "Connection timeout",
                                "retry_suggestion": "Please try again in a few moments"
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 내부 오류 - 알고주문 조회 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "okx_api_error": {
                            "summary": "OKX API 오류",
                            "value": {
                                "detail": "Failed to fetch algo order",
                                "algoId": "780912345678901234",
                                "error": "OKX API error: code 50000",
                                "suggestion": "Check OKX API status and error code documentation"
                            }
                        },
                        "parsing_error": {
                            "summary": "응답 파싱 오류",
                            "value": {
                                "detail": "Failed to parse algo order response",
                                "algoId": "780923456789012345",
                                "error": "Unexpected response format",
                                "suggestion": "Contact support if issue persists"
                            }
                        }
                    }
                }
            }
        }
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
            
        