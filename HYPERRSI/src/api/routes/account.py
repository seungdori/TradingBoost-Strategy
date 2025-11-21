#src/api/routes/account.py

import asyncio
import hmac
import json
import logging
import os
import time
from datetime import date, datetime, timedelta
from typing import List, Optional

import ccxt.async_support as ccxt
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from HYPERRSI.src.api.dependencies import get_exchange_context
from shared.database.redis_helper import get_redis_client
from shared.database.redis_patterns import redis_context, RedisTimeout

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/account", tags=["Account Management"])


SYMBOL_INFO_PREFIX = "symbol_info:"

class Position(BaseModel):
    """
    단일 포지션 정보를 담는 모델
    """
    instrument: str           # instId
    size: float               # pos
    side: str                 # posSide
    entry_price: float        # avgPx
    mark_price: float         # markPx
    unrealized_pnl: float     # upl
    margin_ratio: float       # mgnRatio
    leverage: float           # lever
    liquidation_price: float  # liqPx
    margin: float             # imr
    

class Balance(BaseModel):
    """
    사용자 계정의 잔고 정보 모델
    """
    total_equity: float
    available_margin: float
    used_margin: float
    currency: str
    margin_ratio: float
    update_time: datetime
    positions: List[Position]


class SimplePosition(BaseModel):
    """간소화된 포지션 정보 모델"""
    symbol: str                # 거래 심볼 (예: XRP-USDT-SWAP)
    direction: str            # 'long' 또는 'short'
    size: float               # 포지션 크기(qty형식)
    entry_price: float        # 진입가
    mark_price: float         # 현재가
    unrealized_pnl: float     # 미실현 손익
    leverage: float             # 레버리지
    margin: float             # 사용 중인 증거금
    liquidation_price: float  # 청산가

class PositionsResponse(BaseModel):
    """
    복수 포지션 정보를 요약해 응답하는 모델
    """
    positions: List[SimplePosition]
    total_unrealized_pnl: float
    update_time: datetime



class TradeHistory(BaseModel):
    timestamp: str
    side: str
    size: float
    entry_price: float
    exit_price: float
    pnl: float
    pnl_percent: float
    
    model_config = {
        "json_schema_extra": {
            "examples": [{
                "timestamp": "2024-03-15 10:30:00",
                "side": "long",
                "size": 0.01,
                "entry_price": 50000.0,
                "exit_price": 51000.0,
                "pnl": 10.0,
                "pnl_percent": 2.0
            }]
        }
    }

class TradeVolume(BaseModel):
    """거래량 정보 모델"""
    total_volume: float
    total_fee: float
    currency: str
    start_date: str
    end_date: str
    total_contracts: float
    
    model_config = {
        "json_schema_extra": {
            "examples": [{
                "total_volume": 1000.0,
                "total_fee": 2.5,
                "currency": "USDT",
                "start_date": "2024-05-01",
                "end_date": "2024-05-31",
                "total_contracts": 0.1
            }]
        }
    }

# --- 헬퍼 함수: Redis 키 생성 ---
def get_redis_keys(user_id: str):
    return {
        'history': f"user:{user_id}:trade_history",
        'api_keys': f"user:{user_id}:api:keys"
    }


# 환경 변수나 별도의 설정 파일에서 가져오는 방식을 권장합니다.
from HYPERRSI.src.config import OKX_API_KEY as API_KEY
from HYPERRSI.src.config import OKX_PASSPHRASE as API_PASSPHRASE
from HYPERRSI.src.config import OKX_SECRET_KEY as API_SECRET

BASE_URL = "https://www.okx.com"


async def update_contract_specifications(user_id: str):
    """
    계약 사양을 업데이트하는 헬퍼 함수
    마지막 업데이트가 24시간 이전이면 새로 조회합니다
    """
    def safe_float(value, default=0.0):
        """
        문자열을 float로 안전하게 변환
        빈 문자열이나 None은 default 값 반환
        """
        try:
            if value is None or value == '':
                return default
            return float(value)
        except (ValueError, TypeError):
            return default

    try:
        # Use context manager for proper connection management and timeout protection
        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            # 마지막 업데이트 시간 확인
            last_update = await asyncio.wait_for(
                redis.get("symbol_info:contract_specs_last_update"),
                timeout=RedisTimeout.FAST_OPERATION
            )
            current_time = int(time.time())

            if not last_update or (current_time - int(last_update)) > 86400:
                async with get_exchange_context(user_id) as exchange:
                    response = await exchange.publicGetPublicInstruments(params={'instType': 'SWAP'})

                    # 모든 계약 사양 저장
                    specs_dict = {}
                    for instrument in response['data']:
                        # safe_float로 빈 문자열이나 None 값 안전하게 처리
                        specs_dict[instrument['instId']] = {
                            'contractSize': safe_float(instrument.get('ctVal'), 1.0),
                            'tickSize': safe_float(instrument.get('tickSz'), 0.01),
                            'minSize': safe_float(instrument.get('minSz'), 0.01),
                            'ctType': instrument.get('ctType', ''),
                            'quoteCcy': instrument.get('quoteCcy', ''),
                            'baseCcy': instrument.get('baseCcy', ''),
                            'settleCcy': instrument.get('settleCcy', ''),
                            'maxLeverage': safe_float(instrument.get('maxLever'), 100.0),
                            'update_time': current_time
                        }

                    # Redis에 저장 (만료시간 없이)
                    await asyncio.wait_for(
                        redis.set("symbol_info:contract_specifications", json.dumps(specs_dict)),
                        timeout=RedisTimeout.FAST_OPERATION
                    )
                    await asyncio.wait_for(
                        redis.set("symbol_info:contract_specs_last_update", str(current_time)),
                        timeout=RedisTimeout.FAST_OPERATION
                    )

                    return specs_dict

            # 기존 데이터 반환
            specs = await asyncio.wait_for(
                redis.get("symbol_info:contract_specifications"),
                timeout=RedisTimeout.FAST_OPERATION
            )
            return json.loads(specs) if specs else {}
        
    except Exception as e:
        logger.error(f"Failed to update contract specifications: {str(e)}", exc_info=True)
        return {}

@router.get(
    "/contract-specs",
    summary="계약 사양 조회",
    description="모든 선물 계약의 사양(계약 크기 등)을 조회합니다. 24시간마다 자동 업데이트됩니다.",
)
async def get_contract_specifications(
    user_id: str = Query(..., description="사용자 ID(문자열)"),
    force_update: bool = Query(False, description="강제 업데이트 여부")
):
    """
    계약 사양 조회 API
    - 마지막 업데이트가 24시간 이전이면 자동으로 새로 조회
    - force_update=true로 요청하면 강제로 새로 조회
    """
    try:
        # Use context manager for proper connection management and timeout protection
        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            if force_update:
                # Redis 데이터 삭제 후 새로 조회
                await asyncio.wait_for(
                    redis.delete("symbol_info:contract_specifications"),
                    timeout=RedisTimeout.FAST_OPERATION
                )
                await asyncio.wait_for(
                    redis.delete("symbol_info:contract_specs_last_update"),
                    timeout=RedisTimeout.FAST_OPERATION
                )

            specs_dict = await update_contract_specifications(user_id)

            last_update = await asyncio.wait_for(
                redis.get("symbol_info:contract_specs_last_update"),
                timeout=RedisTimeout.FAST_OPERATION
            )

        return {
            "success": True,
            "data": specs_dict,
            "last_update": last_update
        }
    
    except Exception as e:
        logger.error(f"Failed to fetch contract specifications: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="계약 사양 조회 중 오류가 발생했습니다"
        )


@router.get(
    "/balance",
    response_model=Balance,
    summary="계정 잔고 및 포지션 조회",
    description="""
# 계정 잔고 및 포지션 조회

사용자 계정의 전체 잔고 정보(총자산, 가용 마진, 사용 중인 마진, 마진 비율)와 현재 보유 중인 모든 포지션을 조회합니다.

## 쿼리 파라미터

- **user_id** (string, required): 사용자 식별자
  - OKX UID (18자리) 또는 텔레그램 ID
  - 텔레그램 ID인 경우 자동으로 OKX UID로 변환

## 동작 방식

1. **사용자 인증**: Redis에서 API 키 조회
2. **CCXT 클라이언트 생성**: OKX API 접근 준비
3. **잔고 조회**: fetch_balance()로 계정 잔고 가져오기
4. **포지션 조회**: private_get_account_positions()로 활성 포지션 가져오기
5. **계약 사양 동기화**: update_contract_specifications()로 최신 계약 정보 업데이트
6. **데이터 파싱**: USDT 잔고 추출 및 포지션 정보 변환
7. **응답 반환**: 잔고 및 포지션 메타데이터

## 반환 정보 (Balance)

### 잔고 정보

- **total_equity** (float): 총자산 (USDT)
  - 계정의 총 가치 (보유 자산 + 미실현 손익)
- **available_margin** (float): 가용 마진 (USDT)
  - 새로운 포지션 진입에 사용 가능한 마진
- **used_margin** (float): 사용 중인 마진 (USDT)
  - 현재 포지션 유지에 사용 중인 마진
- **currency** (string): 기축통화 (항상 "USDT")
- **margin_ratio** (float): 마진 비율
  - 사용 중인 마진 / 총자산
  - 높을수록 청산 리스크 증가
- **update_time** (datetime): 조회 시간 (UTC)

### 포지션 정보

- **positions** (array): 현재 보유 포지션 목록
  - **instrument** (string): 거래 심볼 (예: "BTC-USDT-SWAP")
  - **size** (float): 포지션 크기 (기준 화폐 단위)
  - **side** (string): 포지션 방향 ("long" 또는 "short")
  - **entry_price** (float): 평균 진입가
  - **mark_price** (float): 현재 마크 가격
  - **unrealized_pnl** (float): 미실현 손익 (USDT)
  - **margin_ratio** (float): 포지션별 마진 비율
  - **leverage** (float): 레버리지
  - **liquidation_price** (float): 청산가
  - **margin** (float): 포지션 마진 (USDT)

## 사용 시나리오

-  **자산 확인**: 총자산 및 가용 마진 모니터링
-  **포지션 관리**: 모든 활성 포지션 한눈에 확인
-  **리스크 체크**: 마진 비율 및 청산가 모니터링
-  **손익 추적**: 미실현 손익 실시간 확인
-  **거래 계획**: 가용 마진 기반 신규 포지션 계획

## 계약 사양 자동 업데이트

이 엔드포인트는 내부적으로 `update_contract_specifications()`를 호출하여:
- 24시간마다 자동으로 계약 사양 업데이트
- 계약 크기, 최소 주문 수량, 최대 레버리지 등 동기화
- Redis에 캐싱하여 성능 최적화

## 예시 URL

```
GET /account/balance?user_id=518796558012178692
GET /account/balance?user_id=1709556958
```
""",
    responses={
        200: {
            "description": " 잔고 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "balance_with_positions": {
                            "summary": "포지션 보유 중",
                            "value": {
                                "total_equity": 1000.0,
                                "available_margin": 850.0,
                                "used_margin": 150.0,
                                "currency": "USDT",
                                "margin_ratio": 0.15,
                                "update_time": "2025-01-12T16:30:00Z",
                                "positions": [
                                    {
                                        "instrument": "BTC-USDT-SWAP",
                                        "size": 0.1,
                                        "side": "long",
                                        "entry_price": 92000.0,
                                        "mark_price": 92500.0,
                                        "unrealized_pnl": 50.0,
                                        "margin_ratio": 0.08,
                                        "leverage": 10.0,
                                        "liquidation_price": 83000.0,
                                        "margin": 920.0
                                    }
                                ]
                            }
                        },
                        "balance_without_positions": {
                            "summary": "포지션 없음",
                            "value": {
                                "total_equity": 2000.0,
                                "available_margin": 2000.0,
                                "used_margin": 0.0,
                                "currency": "USDT",
                                "margin_ratio": 0.0,
                                "update_time": "2025-01-12T16:35:00Z",
                                "positions": []
                            }
                        },
                        "multiple_positions": {
                            "summary": "여러 포지션 보유",
                            "value": {
                                "total_equity": 5000.0,
                                "available_margin": 4200.0,
                                "used_margin": 800.0,
                                "currency": "USDT",
                                "margin_ratio": 0.16,
                                "update_time": "2025-01-12T16:40:00Z",
                                "positions": [
                                    {
                                        "instrument": "BTC-USDT-SWAP",
                                        "size": 0.1,
                                        "side": "long",
                                        "entry_price": 92000.0,
                                        "unrealized_pnl": 50.0
                                    },
                                    {
                                        "instrument": "ETH-USDT-SWAP",
                                        "size": 2.0,
                                        "side": "short",
                                        "entry_price": 2650.0,
                                        "unrealized_pnl": -20.0
                                    }
                                ]
                            }
                        }
                    }
                }
            },
        },
        400: {
            "description": " 잘못된 요청 - 거래소 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "exchange_error": {
                            "summary": "거래소 오류",
                            "value": {
                                "detail": "거래소 오류: Invalid request"
                            }
                        }
                    }
                }
            }
        },
        401: {
            "description": " 인증 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "authentication_error": {
                            "summary": "인증 실패",
                            "value": {
                                "detail": "인증 오류가 발생했습니다"
                            }
                        },
                        "invalid_api_keys": {
                            "summary": "잘못된 API 키",
                            "value": {
                                "detail": "Invalid API credentials"
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " API 키를 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "api_keys_not_found": {
                            "summary": "API 키 미등록",
                            "value": {
                                "detail": "API 키가 등록되지 않았습니다. API 키를 먼저 등록해주세요."
                            }
                        }
                    }
                }
            }
        },
        503: {
            "description": " 서비스 이용 불가 - 거래소 연결 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "network_error": {
                            "summary": "네트워크 오류",
                            "value": {
                                "detail": "거래소 연결 오류가 발생했습니다"
                            }
                        },
                        "exchange_maintenance": {
                            "summary": "거래소 점검",
                            "value": {
                                "detail": "거래소가 점검 중입니다"
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "server_error": {
                            "summary": "서버 내부 오류",
                            "value": {
                                "detail": "잔고 조회 중 오류가 발생했습니다"
                            }
                        },
                        "redis_error": {
                            "summary": "Redis 오류",
                            "value": {
                                "detail": "Failed to update contract specifications"
                            }
                        }
                    }
                }
            }
        },
    }
)
async def get_balance(
    user_id: str = Query(..., description="사용자 ID(문자열)")
):
    """
    # 사용자 잔고 및 포지션 조회 API

    - **user_id**: 사용자 식별자
    - **반환 정보**:
        - `total_equity`: 총자산
        - `available_margin`: 가용 마진
        - `used_margin`: 사용 중인 마진
        - `currency`: 기축통화 (예: USDT)
        - `margin_ratio`: 마진 비율
        - `update_time`: 조회 시점의 UTC 시간
        - `positions`: 현재 보유 중인 선물 포지션 목록
    """
    start_time = time.time()
    async with get_exchange_context(user_id) as exchange:
        try:
            balance = await exchange.fetch_balance()
 
            positions_response = await exchange.private_get_account_positions({'instType': 'SWAP'})
            # USDT 잔고 정보
            usdt_details = next(
                (detail for detail in balance['info']['data'][0]['details'] 
                 if detail['ccy'] == 'USDT'), {}
            )
            specs_dict = await update_contract_specifications(user_id)
            end_time = time.time()
            print(f"get_balance2 소요시간: {end_time - start_time}초")
            print("================================================")
            # 포지션 정보 파싱
            def safe_float(value, default=0.0):
                try:
                    if value is None or value == '':
                        return default
                    return float(value)
                except (ValueError, TypeError):
                    return default
            positions = []
            if positions_response.get('data'):
                for pos in positions_response['data']:
                    if safe_float(pos.get('pos', 0)) != 0:  # 실제 포지션이 있는 경우만
                        contract_spec = specs_dict.get(pos['instId'], {})
                        contract_size = contract_spec.get('contractSize', 1)
                        positions.append(Position(
                            instrument=pos['instId'],
                            size=safe_float(pos['pos']) * contract_size,
                            side=pos['posSide'],
                            entry_price=safe_float(pos['avgPx']),
                            mark_price=safe_float(pos['markPx']),
                            unrealized_pnl=safe_float(pos['upl']),
                            margin_ratio=safe_float(pos['mgnRatio']),
                            leverage=safe_float(pos['lever']),
                            liquidation_price=safe_float(pos['liqPx']),
                            margin=safe_float(pos['imr'])
                        ))
            end_time = time.time()
            print("================================================")
            print(f"get_balance3 소요시간: {end_time - start_time}초")
            print("================================================")

            return Balance(
                total_equity=safe_float(usdt_details.get('eq', 0)),
                available_margin=safe_float(usdt_details.get('availEq', 0)),
                used_margin=safe_float(usdt_details.get('imr', 0)),
                currency='USDT',
                margin_ratio = safe_float(usdt_details.get('mgnRatio', '0') or '0'),
                update_time=datetime.utcnow(),
                positions=positions
            )
            
        except HTTPException as e:
            # API 키가 없는 경우 적절한 에러 반환
            if e.status_code == 404 and "API keys not found" in str(e.detail):
                logger.info(f"사용자 {user_id}의 API 키가 등록되지 않음")
                raise HTTPException(
                    status_code=404,
                    detail="API 키가 등록되지 않았습니다. API 키를 먼저 등록해주세요."
                )
            raise e
        except Exception as e:
            logger.error(f"Failed to fetch balance for user {user_id}: {str(e)}", exc_info=True)
            if isinstance(e, ccxt.NetworkError):
                raise HTTPException(status_code=503, detail="거래소 연결 오류가 발생했습니다")
            elif isinstance(e, ccxt.AuthenticationError):
                raise HTTPException(status_code=401, detail="인증 오류가 발생했습니다")
            elif isinstance(e, ccxt.ExchangeError):
                raise HTTPException(status_code=400, detail=f"거래소 오류: {str(e)}")
            else:
                raise HTTPException(status_code=500, detail="잔고 조회 중 오류가 발생했습니다")
        

@router.get(
    "/positions",
    summary="현재 보유 포지션(원본) 조회",
    description="현재 보유 중인 포지션 목록을 raw 데이터 형태로 조회합니다. ccxt의 fetch_positions() 응답 그대로 반환합니다.",
    responses={
        200: {
            "description": "성공적으로 포지션 정보를 조회했습니다."
        },
        500: {
            "description": "포지션 조회 중 서버 오류",
        },
    }
)
async def get_positions(
    user_id: str = Query(..., description="사용자 ID(문자열)")
):
    """
    # 사용자의 모든 포지션(raw) 조회 API

    이 엔드포인트는 fetch_positions()로부터 받은 **원본 포지션 데이터**를 반환합니다.
    """
    async with get_exchange_context(user_id) as exchange:
        try:
            positions = await exchange.fetch_positions()
            return positions
        except Exception as e:
            logger.error(f"Failed to fetch positions: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/history",
    response_model=List[TradeHistory],
    summary="거래 내역 조회",
    description="특정 사용자 ID의 최근 10개 거래 내역을 조회합니다. 실시간 거래소 데이터와 함께 제공됩니다.",
    responses={
        200: {
            "description": "성공적으로 거래 내역을 조회했습니다.",
            "content": {
                "application/json": {
                    "examples": [{
                        "timestamp": "2024-03-15 10:30:00",
                        "symbol": "BTC-USDT-SWAP",
                        "side": "long",
                        "size": 0.01,
                        "leverage": 10,
                        "entry_price": 50000.0,
                        "exit_price": 51000.0,
                        "pnl": 10.0,
                        "pnl_percent": 2.0,
                        "status": "closed",
                        "close_type": "TP",
                        "fee": {"cost": 0.1, "currency": "USDT"}
                    }]
                }
            }
        },
        400: {"description": "등록되지 않은 사용자 (API 키 없음)"},
        500: {"description": "거래 내역 조회 중 서버 오류"},
    }
)
async def get_history(
    user_id: str = Query(..., description="사용자 ID(문자열). 예 : 1709556985"),
    limit: int = Query(10, description="조회할 거래 내역 수"),

):
    """
    사용자의 거래 내역을 조회하고 실시간 정보로 업데이트합니다.

    - 거래소에서 실시간 주문 상태 확인
    - PNL 및 수수료 정보 포함
    - 청산 유형(TP/SL/Manual) 구분
    """
    keys = get_redis_keys(user_id)

    try:
        # Use context manager for proper connection management and timeout protection
        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            history_list = await asyncio.wait_for(
                redis.lrange(keys['history'], 0, limit - 1),
                timeout=RedisTimeout.FAST_OPERATION
            )
            if not history_list:
                return []

            results = []
            async with get_exchange_context(str(user_id)) as exchange:
                for trade_data in history_list:
                    trade_info = json.loads(trade_data)

                    # 주문 상태 업데이트
                    if trade_info.get('order_id') and trade_info.get('symbol'):
                        try:
                            print("fetch_order 호출", trade_info['order_id'], trade_info['symbol'])
                            order = await exchange.fetch_order(
                                trade_info['order_id'],
                                trade_info['symbol']
                            )

                            if order['status'] in ['closed', 'canceled', 'expired']:
                                # 체결 정보 업데이트
                                trade_info['status'] = 'closed'
                                trade_info['exit_price'] = float(order['average']) if order.get('average') else float(order['price'])
                                trade_info['exit_timestamp'] = datetime.fromtimestamp(
                                    order.get('lastTradeTimestamp', order['timestamp']) / 1000
                                ).strftime('%Y-%m-%d %H:%M:%S')

                                # PNL 계산
                                entry_price = float(trade_info['entry_price'])
                                exit_price = float(trade_info['exit_price'])
                                size = float(trade_info['size'])
                                is_long = trade_info['side'] == 'long'

                                if entry_price > 0 and size > 0:
                                    pnl = (exit_price - entry_price) * size if is_long else (entry_price - exit_price) * size
                                    trade_info['pnl'] = pnl
                                    trade_info['pnl_percent'] = (pnl / (entry_price * size)) * 100

                                # 수수료 정보
                                if order.get('fee'):
                                    trade_info['fee'] = {
                                        'cost': float(order['fee']['cost']),
                                        'currency': order['fee']['currency']
                                    }

                                # 청산 유형 확인
                                info = order.get('info', {})
                                if info.get('tpTriggerPx'):
                                    trade_info['close_type'] = 'TP'
                                elif info.get('slTriggerPx'):
                                    trade_info['close_type'] = 'SL'
                                else:
                                    trade_info['close_type'] = 'Manual'

                                # Redis 업데이트
                                await asyncio.wait_for(
                                    redis.lset(
                                        keys['history'],
                                        history_list.index(trade_data),
                                        json.dumps(trade_info)
                                    ),
                                    timeout=RedisTimeout.FAST_OPERATION
                                )

                        except Exception as e:
                            logger.error(f"주문 정보 업데이트 실패 - order_id: {trade_info.get('order_id')}, error: {str(e)}")

                    results.append(TradeHistory(**trade_info))
                
            return results

    except HTTPException:
        # HTTPException은 그대로 전파 (API 키 없음, 인증 오류 등)
        raise
    except Exception as e:
        logger.error(f"[get_history] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="거래 내역 조회 중 오류가 발생했습니다.")
                            
@router.get(
    "/positions/summary",
    response_model=PositionsResponse,
    summary="활성 포지션 요약 조회",
    description="""
# 활성 포지션 요약 조회

현재 보유 중인 선물 포지션의 요약 정보를 간소화된 형태로 조회합니다. 모든 활성 포지션의 미실현 손익 합계를 포함합니다.

## 쿼리 파라미터

- **user_id** (string, required): 사용자 식별자
  - OKX UID (18자리) 또는 텔레그램 ID
  - 텔레그램 ID인 경우 자동으로 OKX UID로 변환

## 동작 방식

1. **사용자 인증**: Redis에서 API 키 조회
2. **CCXT 클라이언트 생성**: OKX API 접근 준비
3. **포지션 조회**: private_get_account_positions()로 SWAP 포지션 조회
4. **계약 사양 로드**: update_contract_specifications()로 계약 정보 가져오기
5. **데이터 변환**: 원본 데이터를 SimplePosition 형태로 변환
6. **손익 집계**: 모든 포지션의 미실현 손익 합산
7. **응답 반환**: 간소화된 포지션 요약 정보

## 반환 정보 (PositionsResponse)

- **positions** (array): 활성 포지션 목록 (SimplePosition)
  - **symbol** (string): 거래 심볼 (예: "BTC-USDT-SWAP")
  - **direction** (string): 포지션 방향 ("long" 또는 "short")
  - **size** (float): 포지션 크기 (기준 화폐 단위)
  - **entry_price** (float): 평균 진입가
  - **mark_price** (float): 현재 마크 가격
  - **unrealized_pnl** (float): 미실현 손익 (USDT)
  - **leverage** (int): 레버리지
  - **margin** (float): 포지션 마진 (USDT)
  - **liquidation_price** (float): 청산가
- **total_unrealized_pnl** (float): 전체 미실현 손익 합계
- **update_time** (datetime): 조회 시간 (UTC)

## 사용 시나리오

-  **대시보드**: 포지션 현황 한눈에 파악
-  **손익 모니터링**: 전체 미실현 손익 실시간 추적
-  **리스크 관리**: 청산가 대비 현재가 모니터링
-  **포트폴리오 분석**: 심볼별 포지션 분포 확인
-  **거래 전략**: 포지션 밸런스 최적화

## GET /balance와의 차이점

### GET /balance
- 전체 계정 잔고 정보 포함
- 총자산, 가용 마진, 사용 마진 제공
- 포지션 정보는 부가 데이터
- 계정 전체 상태 확인에 적합

### GET /positions/summary
- 포지션 정보에만 집중
- 간소화된 포지션 데이터 구조
- 전체 미실현 손익 집계
- 빠른 포지션 현황 파악에 적합

## 예시 URL

```
GET /account/positions/summary?user_id=518796558012178692
GET /account/positions/summary?user_id=1709556958
```
""",
    responses={
        200: {
            "description": " 포지션 요약 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "single_long_position": {
                            "summary": "롱 포지션 1개",
                            "value": {
                                "positions": [
                                    {
                                        "symbol": "BTC-USDT-SWAP",
                                        "direction": "long",
                                        "size": 0.1,
                                        "entry_price": 92000.0,
                                        "mark_price": 92500.0,
                                        "unrealized_pnl": 50.0,
                                        "leverage": 10,
                                        "margin": 920.0,
                                        "liquidation_price": 83000.0
                                    }
                                ],
                                "total_unrealized_pnl": 50.0,
                                "update_time": "2025-01-12T17:00:00Z"
                            }
                        },
                        "multiple_positions_profit": {
                            "summary": "여러 포지션 (수익)",
                            "value": {
                                "positions": [
                                    {
                                        "symbol": "BTC-USDT-SWAP",
                                        "direction": "long",
                                        "size": 0.1,
                                        "entry_price": 92000.0,
                                        "mark_price": 93000.0,
                                        "unrealized_pnl": 100.0,
                                        "leverage": 10,
                                        "margin": 920.0,
                                        "liquidation_price": 83000.0
                                    },
                                    {
                                        "symbol": "ETH-USDT-SWAP",
                                        "direction": "long",
                                        "size": 2.0,
                                        "entry_price": 2600.0,
                                        "mark_price": 2650.0,
                                        "unrealized_pnl": 100.0,
                                        "leverage": 10,
                                        "margin": 520.0,
                                        "liquidation_price": 2340.0
                                    }
                                ],
                                "total_unrealized_pnl": 200.0,
                                "update_time": "2025-01-12T17:05:00Z"
                            }
                        },
                        "mixed_positions": {
                            "summary": "롱/숏 혼합 (손익 혼재)",
                            "value": {
                                "positions": [
                                    {
                                        "symbol": "BTC-USDT-SWAP",
                                        "direction": "long",
                                        "size": 0.1,
                                        "entry_price": 92000.0,
                                        "mark_price": 91000.0,
                                        "unrealized_pnl": -100.0,
                                        "leverage": 10
                                    },
                                    {
                                        "symbol": "ETH-USDT-SWAP",
                                        "direction": "short",
                                        "size": 2.0,
                                        "entry_price": 2650.0,
                                        "mark_price": 2600.0,
                                        "unrealized_pnl": 100.0,
                                        "leverage": 10
                                    }
                                ],
                                "total_unrealized_pnl": 0.0,
                                "update_time": "2025-01-12T17:10:00Z"
                            }
                        },
                        "no_positions": {
                            "summary": "포지션 없음",
                            "value": {
                                "positions": [],
                                "total_unrealized_pnl": 0.0,
                                "update_time": "2025-01-12T17:15:00Z"
                            }
                        }
                    }
                }
            },
        },
        400: {
            "description": " 잘못된 요청 - 거래소 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "exchange_error": {
                            "summary": "거래소 오류",
                            "value": {
                                "detail": "거래소 오류: Invalid request"
                            }
                        }
                    }
                }
            }
        },
        401: {
            "description": " 인증 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "authentication_error": {
                            "summary": "인증 실패",
                            "value": {
                                "detail": "인증 오류가 발생했습니다"
                            }
                        }
                    }
                }
            }
        },
        503: {
            "description": " 서비스 이용 불가 - 거래소 연결 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "network_error": {
                            "summary": "네트워크 오류",
                            "value": {
                                "detail": "거래소 연결 오류가 발생했습니다"
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "server_error": {
                            "summary": "서버 내부 오류",
                            "value": {
                                "detail": "포지션 조회 중 오류가 발생했습니다"
                            }
                        }
                    }
                }
            }
        },
    }
)
async def get_positions_summary(
    user_id: str = Query(..., description="사용자 ID(문자열)")
):
    """
    # 활성 포지션 요약 조회 API

    - **user_id**: 사용자 식별자
    - **반환 정보**: 
        - `positions`: 활성화된 선물 포지션 목록(간소화된 형태)
        - `total_unrealized_pnl`: 모든 포지션의 미실현 손익 합계
        - `update_time`: 조회 시점의 UTC 시간
    """
    async with get_exchange_context(user_id) as exchange:
        try:
            positions_data = await exchange.private_get_account_positions({'instType': 'SWAP'})
            specs_dict = await update_contract_specifications(user_id)
            positions = []
            total_pnl = 0.0
            
            # safe_float 함수 정의 (get_balance와 동일한 함수 사용)
            def safe_float(value, default=0.0):
                try:
                    if value is None or value == '':
                        return default
                    return float(value)
                except (ValueError, TypeError):
                    return default
            
            for pos in positions_data.get('data', []):
                if safe_float(pos.get('pos', 0)) != 0:  # 실제 포지션이 있는 경우만
                    contract_spec = specs_dict.get(pos['instId'], {})
                    contract_size = contract_spec.get('contractSize', 1)
                    position_qty = safe_float(pos['pos']) * contract_size
                    
                    positions.append(SimplePosition(
                        symbol=pos['instId'],
                        direction='long' if safe_float(pos['pos']) > 0 else 'short',
                        size=abs(position_qty),
                        entry_price=safe_float(pos['avgPx']),
                        mark_price=safe_float(pos['markPx']),
                        unrealized_pnl=safe_float(pos['upl']),
                        leverage=int(safe_float(pos['lever'])),
                        margin=safe_float(pos['imr']),
                        liquidation_price=safe_float(pos['liqPx'])
                    ))
                    total_pnl += safe_float(pos['upl'])

            return PositionsResponse(
                positions=positions,
                total_unrealized_pnl=total_pnl,
                update_time=datetime.utcnow()
            )

        except Exception as e:
            logger.error(f"Failed to fetch positions for user {user_id}: {str(e)}", exc_info=True)
            if isinstance(e, ccxt.NetworkError):
                raise HTTPException(status_code=503, detail="거래소 연결 오류가 발생했습니다")
            elif isinstance(e, ccxt.AuthenticationError):
                raise HTTPException(status_code=401, detail="인증 오류가 발생했습니다")
            elif isinstance(e, ccxt.ExchangeError):
                raise HTTPException(status_code=400, detail=f"거래소 오류: {str(e)}")
            else:
                raise HTTPException(status_code=500, detail="포지션 조회 중 오류가 발생했습니다")

@router.get(
    "/volume/month",
    response_model=TradeVolume,
    summary="이번달 거래량 조회 (Bills 기준)",
    description="""
# 이번달 거래량 조회 (Bills 기준)

사용자의 이번달 총 거래량(거래금액)과 수수료를 bills API를 통해 조회합니다. 모든 거래 활동(포지션 진입/청산)이 포함됩니다.

## 쿼리 파라미터

- **user_id** (string, required): 사용자 식별자
  - OKX UID (18자리) 또는 텔레그램 ID
  - 텔레그램 ID인 경우 자동으로 OKX UID로 변환

## 동작 방식

1. **사용자 인증**: Redis에서 API 키 조회
2. **CCXT 클라이언트 생성**: OKX API 접근 준비
3. **기간 설정**: 이번달 1일 ~ 오늘까지
4. **Bills 조회**: private_get_account_bills()로 거래 내역 조회
5. **데이터 집계**:
   - 거래 타입 필터링 (type='2', subType in ['3','4','5','6'])
   - 거래량 = size × price
   - 수수료 합산 (절대값)
   - 계약 수량 합산
6. **응답 반환**: 집계된 거래량 및 수수료 정보

## 반환 정보 (TradeVolume)

- **total_volume** (float): 총 거래량 (USDT)
  - 포지션 진입 + 청산의 총 거래금액
  - 계산: Σ(size × price)
- **total_fee** (float): 총 수수료 (USDT)
  - 거래소에 지불한 수수료 합계
  - 메이커/테이커 수수료 모두 포함
- **currency** (string): 기축통화 (항상 "USDT")
- **start_date** (string): 조회 시작일 (이번달 1일)
  - 형식: "YYYY-MM-DD"
- **end_date** (string): 조회 종료일 (오늘)
  - 형식: "YYYY-MM-DD"
- **total_contracts** (float): 총 계약 수량
  - 거래한 계약 수의 합계

## 사용 시나리오

-  **월간 통계**: 이번달 거래 활동 분석
-  **수수료 계산**: 거래 비용 추적 및 최적화
-  **활동 모니터링**: 거래량 추이 파악
-  **VIP 등급**: 거래소 VIP 등급 산정 기준 확인
- 💼 **세무 자료**: 월별 거래 내역 정리

## Bills API vs Orders API

### GET /volume/month (Bills 기준) - 현재 엔드포인트
- **데이터 소스**: Account bills (계정 입출금 내역)
- **포함 범위**: 모든 거래 활동
- **장점**: 정확한 수수료 반영, 포괄적인 데이터
- **용도**: 공식적인 거래량 산정

### GET /volume/month/orders (Orders 기준)
- **데이터 소스**: Trade fills (체결 내역)
- **포함 범위**: 체결된 주문만
- **장점**: 주문별 상세 정보
- **용도**: 세부 거래 분석

## 예시 URL

```
GET /account/volume/month?user_id=518796558012178692
GET /account/volume/month?user_id=1709556958
```
""",
    responses={
        200: {
            "description": " 거래량 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "active_trader": {
                            "summary": "활발한 거래 (고거래량)",
                            "value": {
                                "total_volume": 50000.0,
                                "total_fee": 25.0,
                                "currency": "USDT",
                                "start_date": "2025-01-01",
                                "end_date": "2025-01-12",
                                "total_contracts": 5.5
                            }
                        },
                        "moderate_trader": {
                            "summary": "중간 수준 거래",
                            "value": {
                                "total_volume": 10000.0,
                                "total_fee": 5.0,
                                "currency": "USDT",
                                "start_date": "2025-01-01",
                                "end_date": "2025-01-12",
                                "total_contracts": 1.1
                            }
                        },
                        "low_activity": {
                            "summary": "낮은 활동",
                            "value": {
                                "total_volume": 1000.0,
                                "total_fee": 0.5,
                                "currency": "USDT",
                                "start_date": "2025-01-01",
                                "end_date": "2025-01-12",
                                "total_contracts": 0.1
                            }
                        },
                        "no_trades": {
                            "summary": "거래 없음",
                            "value": {
                                "total_volume": 0.0,
                                "total_fee": 0.0,
                                "currency": "USDT",
                                "start_date": "2025-01-01",
                                "end_date": "2025-01-12",
                                "total_contracts": 0.0
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": " 잘못된 요청 - 거래소 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "exchange_error": {
                            "summary": "거래소 오류",
                            "value": {
                                "detail": "거래소 오류: Invalid request"
                            }
                        }
                    }
                }
            }
        },
        401: {
            "description": " 인증 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "authentication_error": {
                            "summary": "인증 실패",
                            "value": {
                                "detail": "인증 오류가 발생했습니다"
                            }
                        }
                    }
                }
            }
        },
        503: {
            "description": " 서비스 이용 불가 - 거래소 연결 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "network_error": {
                            "summary": "네트워크 오류",
                            "value": {
                                "detail": "거래소 연결 오류가 발생했습니다"
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "server_error": {
                            "summary": "서버 내부 오류",
                            "value": {
                                "detail": "거래량 조회 중 오류가 발생했습니다"
                            }
                        }
                    }
                }
            }
        }
    }
)
async def get_monthly_volume(
    user_id: str = Query(..., description="사용자 ID(문자열)")
):
    """
    # 이번달 거래량 조회 API
    
    - **user_id**: 사용자 식별자
    - **반환 정보**:
        - `total_volume`: 이번달 총 거래량 (거래금액, USDT 기준)
        - `total_fee`: 이번달 총 수수료
        - `currency`: 기축통화 (예: USDT)
        - `start_date`: 조회 시작일 (이번달 1일)
        - `end_date`: 조회 종료일 (오늘)
        - `total_contracts`: 이번달 총 계약 수량
    """
    async with get_exchange_context(user_id) as exchange:
        try:
            # 이번달 시작일과 종료일 설정
            today = date.today()
            start_date = date(today.year, today.month, 1)
            end_date = today
            
            # 시작일과 종료일을 ISO 형식으로 변환
            start_ts = int(datetime.combine(start_date, datetime.min.time()).timestamp() * 1000)
            end_ts = int(datetime.combine(end_date, datetime.max.time()).timestamp() * 1000)
            
            # OKX API 매개변수 설정
            params = {
                'instType': 'SWAP',  # 선물만 조회
                'begin': start_ts,
                'end': end_ts
            }
            
            # 거래 내역 조회
            bills = await exchange.private_get_account_bills(params)
            print(bills)
            total_volume = 0.0
            total_fee = 0.0
            total_contracts = 0.0
            
            if bills.get('data'):
                for bill in bills['data']:
                    # OKX에서 거래 타입은 '2'이며, subType으로 거래 종류가 구분됨
                    if bill.get('type') == '2' and bill.get('subType') in ['3', '4', '5', '6']:
                        # 거래량 합산
                        if bill.get('sz') and bill.get('px'):
                            size = abs(float(bill['sz']))
                            price = float(bill['px'])
                            total_volume += size * price
                            total_contracts += size
                        
                        # 수수료 합산 (수수료는 음수로 표시되므로 절대값 사용)
                        if bill.get('fee'):
                            total_fee += abs(float(bill['fee']))
            
            return TradeVolume(
                total_volume=total_volume,
                total_fee=total_fee,
                currency='USDT',
                start_date=start_date.strftime('%Y-%m-%d'),
                end_date=end_date.strftime('%Y-%m-%d'),
                total_contracts=total_contracts
            )
            
        except Exception as e:
            logger.error(f"Failed to fetch monthly volume for user {user_id}: {str(e)}", exc_info=True)
            if isinstance(e, ccxt.NetworkError):
                raise HTTPException(status_code=503, detail="거래소 연결 오류가 발생했습니다")
            elif isinstance(e, ccxt.AuthenticationError):
                raise HTTPException(status_code=401, detail="인증 오류가 발생했습니다")
            elif isinstance(e, ccxt.ExchangeError):
                raise HTTPException(status_code=400, detail=f"거래소 오류: {str(e)}")
            else:
                raise HTTPException(status_code=500, detail="거래량 조회 중 오류가 발생했습니다")

@router.get(
    "/volume/month/orders",
    response_model=TradeVolume,
    summary="이번달 거래량 조회 (주문 내역 기준)",
    description="사용자의 이번달 총 거래량(거래금액)과 수수료를 주문 내역 기준으로 조회합니다.",
    responses={
        200: {
            "description": "성공적으로 거래량 정보를 조회했습니다.",
            "content": {
                "application/json": {
                    "example": {
                        "total_volume": 1000.0,
                        "total_fee": 2.5,
                        "currency": "USDT",
                        "start_date": "2024-05-01",
                        "end_date": "2024-05-31",
                        "total_contracts": 0.1
                    }
                }
            }
        },
        400: {"description": "거래소 오류"},
        401: {"description": "인증 오류"},
        503: {"description": "거래소 연결 오류"},
        500: {"description": "거래량 조회 중 서버 오류"}
    }
)
async def get_monthly_volume_from_orders(
    user_id: str = Query(..., description="사용자 ID(문자열)")
):
    """
    # 이번달 거래량 조회 API (주문 내역 기준)
    
    - **user_id**: 사용자 식별자
    - **반환 정보**:
        - `total_volume`: 이번달 총 거래량 (거래금액, USDT 기준)
        - `total_fee`: 이번달 총 수수료
        - `currency`: 기축통화 (예: USDT)
        - `start_date`: 조회 시작일 (이번달 1일)
        - `end_date`: 조회 종료일 (오늘)
        - `total_contracts`: 이번달 총 계약 수량
    """
    async with get_exchange_context(user_id) as exchange:
        try:
            # 이번달 시작일과 종료일 설정
            today = date.today()
            start_date = date(today.year, today.month, 1)
            end_date = today
            
            # 시작일과 종료일을 ISO 형식으로 변환
            start_ts = int(datetime.combine(start_date, datetime.min.time()).timestamp() * 1000)
            end_ts = int(datetime.combine(end_date, datetime.max.time()).timestamp() * 1000)
            
            # 주문 내역 조회 API 매개변수 설정
            params = {
                'instType': 'SWAP',  # 선물만 조회
                'begin': start_ts,
                'end': end_ts,
                'state': 'filled'    # 체결된 주문만 조회
            }
            
            # 주문 내역 조회 (최근 주문부터 조회)
            orders = await exchange.private_get_trade_fills(params)
            
            total_volume = 0.0
            total_fee = 0.0
            total_contracts = 0.0
            
            if orders.get('data'):
                for order in orders['data']:
                    # 실제 체결된 거래만 처리
                    if order.get('fillSz') and order.get('fillPx'):
                        size = abs(float(order['fillSz']))
                        price = float(order['fillPx'])
                        total_volume += size * price
                        total_contracts += size
                    
                    # 수수료 합산
                    if order.get('fee'):
                        total_fee += abs(float(order['fee']))
            
            return TradeVolume(
                total_volume=total_volume,
                total_fee=total_fee,
                currency='USDT',
                start_date=start_date.strftime('%Y-%m-%d'),
                end_date=end_date.strftime('%Y-%m-%d'),
                total_contracts=total_contracts
            )
        except Exception as e:
            logger.error(f"Failed to fetch monthly volume from orders for user {user_id}: {str(e)}", exc_info=True)
            if isinstance(e, ccxt.NetworkError):
                raise HTTPException(status_code=503, detail="거래소 연결 오류가 발생했습니다")
            elif isinstance(e, ccxt.AuthenticationError):
                raise HTTPException(status_code=401, detail="인증 오류가 발생했습니다")
            elif isinstance(e, ccxt.ExchangeError):
                raise HTTPException(status_code=400, detail=f"거래소 오류: {str(e)}")
            else:
                raise HTTPException(status_code=500, detail="거래량 조회 중 오류가 발생했습니다")


@router.delete(
    "/margin/unblock",
    summary="마진 차단 해제",
    description="""
# 마진 차단 해제 API

자금 부족으로 인해 차단된 심볼의 거래를 수동으로 해제합니다.

## 쿼리 파라미터

- **user_id** (string, required): 사용자 ID
- **symbol** (string, required): 심볼 (예: "ETH-USDT-SWAP")

## 동작 방식

1. Redis에서 차단 키 확인 (`margin_block:{user_id}:{symbol}`)
2. 차단 키가 존재하면 삭제
3. 재시도 카운트 키도 함께 삭제 (`margin_retry:{user_id}:{symbol}`)
4. 삭제 결과 반환

## 자동 차단 해제 조건

현재는 **TTL 만료(10분)만** 자동 해제 조건입니다:
- 차단 설정 시 600초(10분) TTL로 Redis 키 생성
- 10분 후 자동으로 키가 만료되어 차단 해제
- 잔고 증가나 성공적인 거래는 자동 해제 조건이 아님

## 사용 시나리오

- 🔓 잔고를 추가 입금한 후 즉시 거래 재개
- 🔄 시스템 오류로 인한 잘못된 차단 해제
- ⚡ 긴급한 거래가 필요한 경우 10분 대기 없이 즉시 해제

## 예시 URL

```
DELETE /account/margin/unblock?user_id=586156710277369942&symbol=ETH-USDT-SWAP
```
""",
    responses={
        200: {
            "description": "차단 해제 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "unblocked": {
                            "summary": "차단 해제됨",
                            "value": {
                                "success": True,
                                "message": "ETH-USDT-SWAP 심볼의 마진 차단이 해제되었습니다",
                                "user_id": "586156710277369942",
                                "symbol": "ETH-USDT-SWAP",
                                "keys_deleted": 2
                            }
                        },
                        "not_blocked": {
                            "summary": "차단되지 않음",
                            "value": {
                                "success": True,
                                "message": "ETH-USDT-SWAP 심볼은 차단되지 않았습니다",
                                "user_id": "586156710277369942",
                                "symbol": "ETH-USDT-SWAP",
                                "keys_deleted": 0
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": "서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "server_error": {
                            "summary": "Redis 연결 오류",
                            "value": {
                                "detail": "차단 해제 중 오류가 발생했습니다"
                            }
                        }
                    }
                }
            }
        }
    }
)
async def unblock_margin(
    user_id: str = Query(..., description="사용자 ID"),
    symbol: str = Query(..., description="심볼 (예: ETH-USDT-SWAP)")
):
    """
    # 마진 차단 수동 해제 API

    자금 부족으로 차단된 심볼의 거래를 즉시 해제합니다.

    - **user_id**: 사용자 식별자
    - **symbol**: 차단 해제할 심볼
    - **반환 정보**:
        - `success`: 성공 여부
        - `message`: 결과 메시지
        - `keys_deleted`: 삭제된 Redis 키 개수
    """
    try:
        redis = await get_redis_client()

        # 차단 관련 키들
        block_key = f"margin_block:{user_id}:{symbol}"
        retry_key = f"margin_retry:{user_id}:{symbol}"

        # 키 삭제
        deleted_count = 0

        # 차단 키 확인 및 삭제
        if await redis.exists(block_key):
            await redis.delete(block_key)
            deleted_count += 1
            logger.info(f"[{user_id}] ✅ 마진 차단 키 삭제: {block_key}")

        # 재시도 카운트 키 확인 및 삭제
        if await redis.exists(retry_key):
            await redis.delete(retry_key)
            deleted_count += 1
            logger.info(f"[{user_id}] ✅ 재시도 카운트 키 삭제: {retry_key}")

        # 결과 메시지
        if deleted_count > 0:
            message = f"{symbol} 심볼의 마진 차단이 해제되었습니다"
            logger.info(f"[{user_id}] 🔓 {message} (삭제된 키: {deleted_count}개)")
        else:
            message = f"{symbol} 심볼은 차단되지 않았습니다"
            logger.info(f"[{user_id}] ℹ️ {message}")

        return {
            "success": True,
            "message": message,
            "user_id": user_id,
            "symbol": symbol,
            "keys_deleted": deleted_count
        }

    except Exception as e:
        logger.error(f"[{user_id}] ❌ 차단 해제 실패 - symbol: {symbol}, error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="차단 해제 중 오류가 발생했습니다")
