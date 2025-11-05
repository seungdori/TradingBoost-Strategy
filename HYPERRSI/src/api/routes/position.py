import asyncio
import json
import logging
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional

import ccxt.async_support as ccxt
from fastapi import APIRouter, Body, HTTPException, Path
from pydantic import BaseModel, Field, field_validator

from HYPERRSI.src.core.error_handler import log_error
from shared.database.redis_helper import get_redis_client
from shared.database.redis_patterns import redis_context, RedisTimeout
from shared.dtos.trading import ClosePositionRequest, OpenPositionRequest, PositionResponse
from shared.helpers.user_id_resolver import get_okx_uid_from_telegram, resolve_user_identifier

logger = logging.getLogger(__name__)

#  FastAPI 라우터 설정
router = APIRouter(prefix="/position", tags=["Position Management"])

#  Pydantic 모델 정의
class Info(BaseModel):
    adl: Optional[str]
    avgPx: Optional[float]
    instId: Optional[str]
    instType: Optional[str]
    lever: Optional[float]
    mgnMode: Optional[str]
    pos: Optional[float]
    upl: Optional[float]
    uplRatio: Optional[float]

class Position(BaseModel):
    info: Info
    id: str
    symbol: str
    notional: Optional[float]
    marginMode: str
    liquidationPrice: Optional[float]
    entryPrice: Optional[float]
    unrealizedPnl: Optional[float]
    realizedPnl: Optional[float]
    percentage: Optional[float]
    contracts: Optional[float]
    contractSize: Optional[float]
    markPrice: Optional[float]
    side: str
    timestamp: int
    datetime: str
    lastUpdateTimestamp: Optional[int]
    maintenanceMargin: Optional[float]
    maintenanceMarginPercentage: Optional[float]
    collateral: Optional[float]
    initialMargin: Optional[float]
    initialMarginPercentage: Optional[float]
    leverage: Optional[float]
    marginRatio: Optional[float]
    stopLossPrice: Optional[float]
    takeProfitPrice: Optional[float]

class ApiResponse(BaseModel):
    timestamp: str
    logger: str
    message: str
    data: List[Position]
    position_qty: float


class LeverageRequest(BaseModel):
    leverage: float = Field(
        default=10, 
        ge=1, 
        le=125, 
        description="설정할 레버리지 값 (1-125)"
    )
    marginMode: str = Field(
        default="cross",
        description="마진 모드 (cross 또는 isolated)"
    )
    posSide: Optional[str] = Field(
        default="long",
        description="포지션 방향 (long/short/net). isolated 모드에서만 필요"
    )

    @field_validator('marginMode')
    @classmethod
    def validate_margin_mode(cls, v: str) -> str:
        if v not in ['cross', 'isolated']:
            raise ValueError('marginMode must be either "cross" or "isolated"')
        return v

    @field_validator('posSide')
    @classmethod
    def validate_pos_side(cls, v: str) -> str:
        if v not in ['long', 'short', 'net']:
            raise ValueError('posSide must be one of "long", "short", or "net"')
        return v
class LeverageResponse(BaseModel):
    timestamp: str
    message: str
    symbol: str
    leverage: float
    marginMode: str
    posSide: Optional[str]
    status: str

from HYPERRSI.src.trading.trading_service import TradingService

# ----------------------------
# 요청(Request) / 응답(Response) 모델
# ----------------------------

# Trading DTOs are now imported from shared.dtos.trading


#  Redis에서 사용자 API 키 가져오기
async def get_user_api_keys(user_id: str) -> Dict[str, str]:
    """
    사용자 ID를 기반으로 Redis에서 OKX API 키를 가져오는 함수
    """
    try:
        # 텔레그램 ID인지 OKX UID인지 확인하고 변환
        okx_uid = await resolve_user_identifier(user_id)

        # Use context manager for proper connection management and timeout protection
        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            api_key_format = f"user:{okx_uid}:api:keys"
            api_keys = await asyncio.wait_for(
                redis.hgetall(api_key_format),
                timeout=RedisTimeout.FAST_OPERATION
            )

            if not api_keys:
                raise HTTPException(status_code=404, detail="API keys not found in Redis")
            return dict(api_keys)
    except HTTPException:
        raise
    except Exception as e:
        log_error(
            error=e,
            user_id=user_id,
            additional_info={
                "function": "get_user_api_keys",
                "timestamp": datetime.now().isoformat()
            }
        )
        logger.error(f"1API 키 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching API keys: {str(e)}")


#  FastAPI 엔드포인트
@router.get("/{user_id}/{symbol}", response_model=ApiResponse, include_in_schema=False)
async def fetch_okx_position_with_symbol(
    user_id: str = Path(..., example="1709556958", description="사용자 ID (텔레그램 ID 또는 OKX UID)"),
    symbol: str = Path(..., example="BTC-USDT-SWAP")
) -> ApiResponse:
    """리다이렉션 용도로만 사용되는 레거시 엔드포인트"""
    return await fetch_okx_position(user_id, symbol)

@router.get(
    "/{user_id}",
    response_model=ApiResponse,
    summary="OKX 포지션 조회",
    description="""
# OKX 포지션 조회

특정 사용자의 OKX 포지션 정보를 조회하고 Redis에 자동으로 동기화합니다.

## URL 파라미터

- **user_id** (string, required): 사용자 식별자
  - OKX UID (18자리) 또는 텔레그램 ID
  - 텔레그램 ID인 경우 자동으로 OKX UID로 변환

## 쿼리 파라미터

- **symbol** (string, optional): 거래 심볼
  - 형식: "BTC-USDT-SWAP", "ETH-USDT-SWAP" 등
  - 미지정 시: 모든 활성 포지션 조회
  - 지정 시: 해당 심볼만 조회

## 동작 방식

1. **사용자 인증**: Redis에서 API 키 조회
2. **OKX API 호출**: CCXT를 통한 포지션 정보 조회
3. **데이터 검증**: 유효한 포지션 필터링 및 기본값 설정
4. **Redis 동기화**: 포지션 정보를 Redis에 저장
   - 롱/숏 포지션 정보 개별 저장
   - 포지션 상태(position_state) 업데이트
   - 청산된 포지션 자동 삭제
5. **응답 반환**: 포지션 목록 및 메타데이터

## 반환 정보 (ApiResponse)

- **timestamp** (string): 조회 시간 (UTC)
- **logger** (string): 로거 이름
- **message** (string): 결과 메시지
- **data** (array): 포지션 정보 배열
  - **symbol** (string): 거래 심볼
  - **side** (string): 포지션 방향 (long/short)
  - **entryPrice** (float): 평균 진입가
  - **markPrice** (float): 현재 마크 가격
  - **liquidationPrice** (float): 청산 가격
  - **leverage** (float): 레버리지
  - **contracts** (float): 계약 수량
  - **notional** (float): 명목가치 (USDT)
  - **unrealizedPnl** (float): 미실현 손익
  - **percentage** (float): 손익률 (%)
- **position_qty** (float): 총 포지션 수

## Redis 키 구조

포지션 정보는 다음 Redis 키에 저장됩니다:
- `user:{okx_uid}:position:{symbol}:long` - 롱 포지션 정보
- `user:{okx_uid}:position:{symbol}:short` - 숏 포지션 정보
- `user:{okx_uid}:position:{symbol}:position_state` - 포지션 상태

## 사용 시나리오

-  **실시간 모니터링**: 대시보드에 포지션 현황 표시
-  **손익 계산**: 미실현 손익 및 손익률 확인
-  **리스크 관리**: 청산가 대비 현재가 모니터링
-  **자동 동기화**: Redis 상태와 실제 포지션 동기화
-  **통계 분석**: 포지션 히스토리 및 성과 분석

## 예시 URL

```
GET /position/518796558012178692
GET /position/518796558012178692?symbol=BTC-USDT-SWAP
GET /position/1709556958?symbol=ETH-USDT-SWAP
```
""",
    responses={
        200: {
            "description": " 포지션 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "with_positions": {
                            "summary": "포지션 보유 중",
                            "value": {
                                "timestamp": "2025-01-12T16:30:00",
                                "logger": "root",
                                "message": "OKX 포지션 조회 결과",
                                "data": [
                                    {
                                        "symbol": "BTC-USDT-SWAP",
                                        "side": "long",
                                        "entryPrice": 45000.0,
                                        "markPrice": 45500.0,
                                        "liquidationPrice": 43000.0,
                                        "leverage": 10.0,
                                        "contracts": 0.1,
                                        "notional": 4550.0,
                                        "unrealizedPnl": 50.0,
                                        "percentage": 1.11
                                    }
                                ],
                                "position_qty": 1.0
                            }
                        },
                        "no_positions": {
                            "summary": "포지션 없음",
                            "value": {
                                "timestamp": "2025-01-12T16:30:00",
                                "logger": "root",
                                "message": "포지션이 없습니다",
                                "data": [],
                                "position_qty": 0.0
                            }
                        },
                        "multiple_positions": {
                            "summary": "여러 포지션",
                            "value": {
                                "timestamp": "2025-01-12T16:30:00",
                                "logger": "root",
                                "message": "OKX 포지션 조회 결과",
                                "data": [
                                    {
                                        "symbol": "BTC-USDT-SWAP",
                                        "side": "long",
                                        "entryPrice": 45000.0,
                                        "unrealizedPnl": 50.0
                                    },
                                    {
                                        "symbol": "ETH-USDT-SWAP",
                                        "side": "short",
                                        "entryPrice": 2500.0,
                                        "unrealizedPnl": -10.0
                                    }
                                ],
                                "position_qty": 2.0
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
                            "summary": "API 키 없음",
                            "value": {
                                "detail": "API keys not found in Redis"
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
                        "fetch_error": {
                            "summary": "포지션 조회 실패",
                            "value": {
                                "detail": "Error fetching position: Connection timeout"
                            }
                        },
                        "api_key_error": {
                            "summary": "API 키 조회 오류",
                            "value": {
                                "detail": "Error fetching API keys: Redis connection failed"
                            }
                        }
                    }
                }
            }
        }
    }
)
async def fetch_okx_position(
    user_id: str = Path(..., example="1709556958", description="사용자 ID (텔레그램 ID 또는 OKX UID)"),
    symbol: Optional[str] = None
) -> ApiResponse:
    client = None
    try:
        # user_id를 OKX UID로 변환
        okx_uid = await resolve_user_identifier(user_id)
        
        #  Redis에서 API 키 가져오기        
        api_keys = await get_user_api_keys(okx_uid)
        #  OKX 클라이언트 생성
        client = ccxt.okx({
            'apiKey': api_keys.get('api_key'),
            'secret': api_keys.get('api_secret'),
            'password': api_keys.get('passphrase'),
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })

        await client.load_markets()

        #  포지션 조회 (symbol 파라미터가 None이면 모든 포지션 조회)
        if symbol:
            positions = await client.fetch_positions([symbol], params={'instType': 'SWAP'})
        else:
            positions = await client.fetch_positions(params={'instType': 'SWAP'})
        
        try:
            await client.close()  # CCXT 클라이언트 리소스 해제
        except Exception as e:
            log_error(
                error=e,
                user_id=okx_uid,
                additional_info={
                    "function": "close_client",
                    "timestamp": datetime.now().isoformat()
                }
            )
            logger.warning(f"CCXT 클라이언트 종료 중 오류 발생: {str(e)}")

        # 포지션이 없거나 비어있는 경우 처리
        if not positions or all(float(pos.get('info', {}).get('pos', 0)) == 0 for pos in positions):
            if symbol:
                # Use context manager for proper connection management and timeout protection
                async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
                    # 특정 심볼에 대한 포지션이 없는 경우, Redis에 저장된 해당 종목 포지션 키(long, short)를 삭제
                    for side in ['long', 'short']:
                        redis_key = f"user:{okx_uid}:position:{symbol}:{side}"
                        await asyncio.wait_for(
                            redis.delete(redis_key),
                            timeout=RedisTimeout.FAST_OPERATION
                        )
                    position_state_key = f"user:{okx_uid}:position:{symbol}:position_state"
                    current_state = await asyncio.wait_for(
                        redis.get(position_state_key),
                        timeout=RedisTimeout.FAST_OPERATION
                    )
                    if current_state and int(current_state) != 0:
                        await asyncio.wait_for(
                            redis.set(position_state_key, "0"),
                            timeout=RedisTimeout.FAST_OPERATION
                        )
            return ApiResponse(
                timestamp=str(datetime.utcnow()),
                logger="root",
                message="포지션이 없습니다",
                data=[],
                position_qty=0.0
            )

        # 유효한 포지션만 필터링
        valid_positions = []
        symbols_to_update = set()
        
        for pos in positions:
            try:
                # 심볼 정보 추출 (Redis 업데이트를 위해)
                pos_symbol = pos.get('symbol')
                if pos_symbol:
                    symbols_to_update.add(pos_symbol)
                
                # None 값을 기본값으로 대체
                pos.setdefault('notional', 0.0)
                pos.setdefault('entryPrice', 0.0)
                pos.setdefault('unrealizedPnl', 0.0)
                pos.setdefault('realizedPnl', 0.0)
                pos.setdefault('percentage', 0.0)
                pos.setdefault('markPrice', 0.0)
                pos.setdefault('side', 'none')
                pos.setdefault('collateral', 0.0)
                pos.setdefault('initialMargin', 0.0)
                pos.setdefault('initialMarginPercentage', 0.0)
                pos.setdefault('leverage', 0.0)
                pos.setdefault('marginRatio', 0.0)

                # info 객체 내부의 빈 문자열을 0으로 변환
                if 'info' in pos:
                    info = pos['info']
                    for key in ['avgPx', 'lever', 'upl', 'uplRatio']:
                        if key in info and info[key] == '':
                            info[key] = 0.0

                valid_position = Position(**pos)
                valid_positions.append(valid_position)
            except Exception as e:
                log_error(
                    error=e,
                    user_id=okx_uid,
                    additional_info={
                        "function": "validate_position",
                        "timestamp": datetime.now().isoformat()
                    }
                )   
                logger.warning(f"포지션 데이터 변환 중 오류 발생: {str(e)}")
                continue

        # === Redis 업데이트 로직 ===
        # Use context manager for proper connection management and timeout protection
        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            symbols_to_process = [symbol] if symbol else symbols_to_update

            for curr_symbol in symbols_to_process:
                # 해당 심볼에 대한 유효한 포지션 필터링
                symbol_positions = [p for p in valid_positions if p.symbol == curr_symbol]

                # 양 방향("long", "short")에 대해, Redis에 저장된 포지션과 조회된 포지션을 비교하여 업데이트 또는 삭제
                for side in ['long', 'short']:
                    redis_key = f"user:{okx_uid}:position:{curr_symbol}:{side}"
                    # 조회된 포지션 중 해당 side에 해당하는 포지션 찾기
                    fetched_position = next((p for p in symbol_positions if p.side.lower() == side), None)
                    # Redis에 저장된 데이터 가져오기 (hash 형식)
                    redis_data = await asyncio.wait_for(
                        redis.hgetall(redis_key),
                        timeout=RedisTimeout.FAST_OPERATION
                    )
                    if fetched_position:
                        # 조회된 포지션이 있는 경우
                        new_position_info = fetched_position.json()
                        # redis_data가 없거나 기존에 저장된 정보와 다르면 업데이트
                        if not redis_data or redis_data.get("position_info") != new_position_info:
                            position_data = {
                                "position_info": new_position_info,
                                "entry_price": str(fetched_position.entryPrice),
                                "size": str(fetched_position.contracts),
                                "leverage": str(fetched_position.leverage),
                                "liquidation_price": str(fetched_position.liquidationPrice),
                            }
                            # 기존 initial_size와 last_entry_size 보존
                            if redis_data:
                                if "initial_size" in redis_data:
                                    position_data["initial_size"] = redis_data["initial_size"]
                                if "last_entry_size" in redis_data:
                                    position_data["last_entry_size"] = redis_data["last_entry_size"]
                            await asyncio.wait_for(
                                redis.hset(redis_key, mapping=position_data),
                                timeout=RedisTimeout.FAST_OPERATION
                            )
                    else:
                        # 조회된 포지션이 없는 경우, Redis에 해당 키가 있다면 삭제
                        if redis_data:
                            await asyncio.wait_for(
                                redis.delete(redis_key),
                                timeout=RedisTimeout.FAST_OPERATION
                            )

                # === 추가 로직: position_state 업데이트 ===
                position_state_key = f"user:{okx_uid}:position:{curr_symbol}:position_state"
                current_state = await asyncio.wait_for(
                    redis.get(position_state_key),
                    timeout=RedisTimeout.FAST_OPERATION
                )
                try:
                    position_state = int(current_state) if current_state is not None else 0
                except Exception:
                    position_state = 0

                # 존재하는 포지션 여부
                long_exists = any(p for p in symbol_positions if p.side.lower() == "long")
                short_exists = any(p for p in symbol_positions if p.side.lower() == "short")

                # 조건 1: position_state > 1 인데 long 포지션이 없고 short 포지션만 있을 경우 -> -1로 업데이트
                if position_state > 1 and (not long_exists) and short_exists:
                    position_state = -1
                # 조건 2: position_state < -1 인데 short 포지션이 없고 long 포지션만 있을 경우 -> 1로 업데이트
                elif position_state < -1 and (not short_exists) and long_exists:
                    position_state = 1
                # 조건 3: position_state가 0이 아닌데, 양쪽 모두 포지션이 없으면 -> 0으로 업데이트
                elif position_state != 0 and (not long_exists and not short_exists):
                    position_state = 0

                await asyncio.wait_for(
                    redis.set(position_state_key, str(position_state)),
                    timeout=RedisTimeout.FAST_OPERATION
                )
        # ==============================
        
        return ApiResponse(
            timestamp=str(datetime.utcnow()),
            logger="root",
            message="OKX 포지션 조회 결과",
            data=valid_positions,
            position_qty=len(valid_positions)
        )

    except Exception as e:
        log_error(
            error=e,
            user_id=okx_uid,
            additional_info={
                "function": "fetch_okx_position",
                "timestamp": datetime.now().isoformat()
            }
        )
        if client is not None:
            await client.close()
        logger.error(f"포지션 조회 실패 ({symbol or '전체'}): {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching position: {str(e)}")
    
# API 엔드포인트 추가
@router.post(
    "/{user_id}/{symbol}/leverage",
    response_model=LeverageResponse,
    summary="포지션 레버리지 설정",
    description="""
# 포지션 레버리지 설정

특정 심볼의 레버리지를 변경하고 마진 모드(cross/isolated)를 설정합니다.

## URL 파라미터

- **user_id** (string, required): 사용자 식별자
  - OKX UID (18자리) 또는 텔레그램 ID
  - 텔레그램 ID인 경우 자동으로 OKX UID로 변환
- **symbol** (string, required): 거래 심볼
  - 형식: "BTC-USDT-SWAP", "ETH-USDT-SWAP" 등
  - 반드시 SWAP(무기한 선물) 거래쌍이어야 함

## 요청 본문 (LeverageRequest)

- **leverage** (float, required): 설정할 레버리지 값
  - 범위: 1 ~ 125
  - OKX 거래소 기준, 심볼별로 최대 레버리지가 다를 수 있음
  - 기본값: 10
- **marginMode** (string, required): 마진 모드
  - "cross": 교차 마진 (전체 계좌 잔고 사용)
  - "isolated": 격리 마진 (포지션별 독립된 마진)
  - 기본값: "cross"
- **posSide** (string, optional): 포지션 방향
  - "long": 롱 포지션
  - "short": 숏 포지션
  - "net": 단방향 포지션 (cross 모드에서만 사용)
  - isolated 모드에서는 필수 입력
  - 기본값: "long"

## 마진 모드 설명

### Cross Margin (교차 마진)
- 전체 계좌 잔고를 마진으로 사용
- 포지션 간 마진 공유로 청산 리스크 감소
- 한 포지션 청산 시 전체 계좌에 영향

### Isolated Margin (격리 마진)
- 포지션별로 독립된 마진 할당
- 포지션별 리스크 격리
- 한 포지션 청산이 다른 포지션에 영향 없음

## 동작 방식

1. **사용자 인증**: Redis에서 API 키 조회
2. **CCXT 클라이언트 생성**: OKX API 접근 준비
3. **마켓 정보 로드**: 심볼 유효성 검증
4. **레버리지 변경**: OKX API를 통한 레버리지 설정
5. **응답 반환**: 설정 결과 및 메타데이터

## 반환 정보 (LeverageResponse)

- **timestamp** (string): 설정 완료 시간 (UTC)
- **message** (string): 결과 메시지
- **symbol** (string): 거래 심볼
- **leverage** (float): 설정된 레버리지
- **marginMode** (string): 설정된 마진 모드
- **posSide** (string): 설정된 포지션 방향
- **status** (string): 처리 상태 ("success" 또는 "failed")

## 사용 시나리오

-  **레버리지 조정**: 시장 변동성에 따라 레버리지 조절
-  **리스크 관리**: 높은 변동성 구간에서 레버리지 낮춤
-  **전략 최적화**: 전략별 최적 레버리지 설정
-  **마진 모드 전환**: cross ↔ isolated 전환
-  **포트폴리오 관리**: 심볼별 레버리지 차별화

## 주의사항

- 레버리지 변경은 기존 포지션에도 즉시 적용됩니다
- 마진 모드 변경 시 기존 오픈 오더가 취소될 수 있습니다
- 최대 레버리지는 심볼과 계정 등급에 따라 다릅니다
- 레버리지가 높을수록 청산 리스크가 증가합니다

## 예시 URL

```bash
# Cross Margin 10배 레버리지 설정
POST /position/518796558012178692/BTC-USDT-SWAP/leverage
{
  "leverage": 10,
  "marginMode": "cross"
}

# Isolated Margin 롱 포지션 20배 레버리지 설정
POST /position/1709556958/ETH-USDT-SWAP/leverage
{
  "leverage": 20,
  "marginMode": "isolated",
  "posSide": "long"
}

# 보수적 레버리지 5배 설정
POST /position/518796558012178692/SOL-USDT-SWAP/leverage
{
  "leverage": 5,
  "marginMode": "cross"
}
```
""",
    responses={
        200: {
            "description": " 레버리지 설정 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "cross_margin_success": {
                            "summary": "교차 마진 레버리지 설정 성공",
                            "value": {
                                "timestamp": "2025-01-12T16:45:00",
                                "message": "레버리지 설정이 완료되었습니다",
                                "symbol": "BTC-USDT-SWAP",
                                "leverage": 10.0,
                                "marginMode": "cross",
                                "posSide": "net",
                                "status": "success"
                            }
                        },
                        "isolated_long_success": {
                            "summary": "격리 마진 롱 포지션 레버리지 설정",
                            "value": {
                                "timestamp": "2025-01-12T16:50:00",
                                "message": "레버리지 설정이 완료되었습니다",
                                "symbol": "ETH-USDT-SWAP",
                                "leverage": 20.0,
                                "marginMode": "isolated",
                                "posSide": "long",
                                "status": "success"
                            }
                        },
                        "isolated_short_success": {
                            "summary": "격리 마진 숏 포지션 레버리지 설정",
                            "value": {
                                "timestamp": "2025-01-12T16:55:00",
                                "message": "레버리지 설정이 완료되었습니다",
                                "symbol": "SOL-USDT-SWAP",
                                "leverage": 15.0,
                                "marginMode": "isolated",
                                "posSide": "short",
                                "status": "success"
                            }
                        },
                        "conservative_leverage": {
                            "summary": "보수적 레버리지 설정 (5배)",
                            "value": {
                                "timestamp": "2025-01-12T17:00:00",
                                "message": "레버리지 설정이 완료되었습니다",
                                "symbol": "BTC-USDT-SWAP",
                                "leverage": 5.0,
                                "marginMode": "cross",
                                "posSide": "net",
                                "status": "success"
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
                        "invalid_leverage_range": {
                            "summary": "레버리지 범위 초과",
                            "value": {
                                "detail": {
                                    "message": "레버리지 설정 실패",
                                    "error": "Leverage must be between 1 and 125",
                                    "symbol": "BTC-USDT-SWAP"
                                }
                            }
                        },
                        "invalid_margin_mode": {
                            "summary": "잘못된 마진 모드",
                            "value": {
                                "detail": {
                                    "message": "레버리지 설정 실패",
                                    "error": "marginMode must be either 'cross' or 'isolated'",
                                    "symbol": "ETH-USDT-SWAP"
                                }
                            }
                        },
                        "missing_pos_side": {
                            "summary": "격리 마진에서 posSide 누락",
                            "value": {
                                "detail": {
                                    "message": "레버리지 설정 실패",
                                    "error": "posSide is required for isolated margin mode",
                                    "symbol": "SOL-USDT-SWAP"
                                }
                            }
                        },
                        "invalid_symbol": {
                            "summary": "지원하지 않는 심볼",
                            "value": {
                                "detail": {
                                    "message": "레버리지 설정 실패",
                                    "error": "Symbol not found or not supported",
                                    "symbol": "INVALID-USDT-SWAP"
                                }
                            }
                        }
                    }
                }
            }
        },
        401: {
            "description": " 인증 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_api_keys": {
                            "summary": "잘못된 API 키",
                            "value": {
                                "detail": {
                                    "message": "레버리지 설정 실패",
                                    "error": "Invalid API credentials",
                                    "symbol": "BTC-USDT-SWAP"
                                }
                            }
                        },
                        "expired_api_keys": {
                            "summary": "만료된 API 키",
                            "value": {
                                "detail": {
                                    "message": "레버리지 설정 실패",
                                    "error": "API key has expired",
                                    "symbol": "ETH-USDT-SWAP"
                                }
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 리소스를 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "api_keys_not_found": {
                            "summary": "API 키 없음",
                            "value": {
                                "detail": "API keys not found in Redis"
                            }
                        },
                        "user_not_found": {
                            "summary": "사용자 없음",
                            "value": {
                                "detail": {
                                    "message": "레버리지 설정 실패",
                                    "error": "User not found",
                                    "symbol": "BTC-USDT-SWAP"
                                }
                            }
                        }
                    }
                }
            }
        },
        429: {
            "description": "⏱️ 요청 속도 제한 초과",
            "content": {
                "application/json": {
                    "examples": {
                        "rate_limit_exceeded": {
                            "summary": "API 요청 한도 초과",
                            "value": {
                                "detail": {
                                    "message": "레버리지 설정 실패",
                                    "error": "Rate limit exceeded. Please try again later.",
                                    "symbol": "BTC-USDT-SWAP",
                                    "retry_after": 60
                                }
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
                        "exchange_api_error": {
                            "summary": "거래소 API 오류",
                            "value": {
                                "detail": {
                                    "message": "레버리지 설정 실패",
                                    "error": "OKX API connection failed",
                                    "symbol": "BTC-USDT-SWAP"
                                }
                            }
                        },
                        "network_timeout": {
                            "summary": "네트워크 타임아웃",
                            "value": {
                                "detail": {
                                    "message": "레버리지 설정 실패",
                                    "error": "Request timeout",
                                    "symbol": "ETH-USDT-SWAP"
                                }
                            }
                        },
                        "redis_error": {
                            "summary": "Redis 연결 실패",
                            "value": {
                                "detail": "Error fetching API keys: Redis connection failed"
                            }
                        },
                        "ccxt_close_error": {
                            "summary": "CCXT 클라이언트 종료 오류",
                            "value": {
                                "detail": {
                                    "message": "레버리지 설정 실패",
                                    "error": "Failed to close CCXT client",
                                    "symbol": "SOL-USDT-SWAP"
                                }
                            }
                        }
                    }
                }
            }
        }
    }
)
async def set_position_leverage(
    user_id: str = Path(..., example="1709556958", description="사용자 ID (텔레그램 ID 또는 OKX UID)"),
    symbol: str = Path(..., example="BTC-USDT-SWAP", description="거래 심볼"),
    request: LeverageRequest = Body(..., description="레버리지 설정 요청")
) -> LeverageResponse:
    """
    특정 심볼의 레버리지를 변경하는 API 엔드포인트

    Args:
        user_id: 사용자 ID (텔레그램 ID 또는 OKX UID)
        symbol: 거래 심볼 (예: BTC-USDT-SWAP)
        request: 레버리지 설정 정보

    Returns:
        LeverageResponse: 레버리지 설정 결과
    """
    client = None
    try:
        # user_id를 OKX UID로 변환
        okx_uid = await resolve_user_identifier(user_id)
        
        # Redis에서 API 키 가져오기
        api_keys = await get_user_api_keys(okx_uid)
        
        # OKX 클라이언트 생성
        client = ccxt.okx({
            'apiKey': api_keys.get('api_key'),
            'secret': api_keys.get('api_secret'),
            'password': api_keys.get('passphrase'),
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })

        await client.load_markets()

        # 레버리지 설정
        params = {
            'marginMode': request.marginMode
        }
        
        if request.marginMode == 'cross' and request.posSide:
            params['posSide'] = request.posSide

        await client.set_leverage(request.leverage, symbol, params)

        return LeverageResponse(
            timestamp=str(datetime.utcnow()),
            message="레버리지 설정이 완료되었습니다",
            symbol=symbol,
            leverage=request.leverage,
            marginMode=request.marginMode,
            posSide=request.posSide,
            status="success"
        )

    except Exception as e:
        logger.error(f"레버리지 설정 실패 ({symbol}): {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "message": "레버리지 설정 실패",
                "error": str(e),
                "symbol": symbol
            }
        )
    finally:
        if client:
            try:
                await client.close()
            except Exception as e:
                logger.warning(f"CCXT 클라이언트 종료 중 오류 발생: {str(e)}")
                
                
@router.post(
    "/open",
    response_model=PositionResponse,
    summary="포지션 오픈 (롱/숏)",
    description="""
# 포지션 오픈 (롱/숏)

지정된 심볼에 대해 롱(매수) 또는 숏(매도) 포지션을 오픈하고, 옵션으로 TP(Take Profit)/SL(Stop Loss) 주문을 설정합니다.

## 요청 본문 (OpenPositionRequest)

### 필수 파라미터

- **user_id** (int, required): 사용자 식별자
  - OKX UID (18자리) 또는 텔레그램 ID
  - 텔레그램 ID인 경우 자동으로 OKX UID로 변환
- **symbol** (string, required): 거래 심볼
  - 형식: "BTC-USDT-SWAP", "ETH-USDT-SWAP" 등
  - 반드시 SWAP(무기한 선물) 거래쌍
- **direction** (string, required): 포지션 방향
  - "long": 매수 포지션 (가격 상승 예상)
  - "short": 매도 포지션 (가격 하락 예상)
- **size** (float, required): 포지션 크기
  - 기준 화폐 단위 (예: BTC 수량)
  - 최소 주문 수량은 심볼별로 상이

### 선택 파라미터

- **leverage** (float, optional): 레버리지
  - 범위: 1 ~ 125
  - 기본값: 10.0
  - 심볼별 최대 레버리지 제한 적용
- **stop_loss** (float, optional): 손절가
  - 롱: 진입가보다 낮은 가격
  - 숏: 진입가보다 높은 가격
  - 미설정 시 손절 주문 생성 안 함
- **take_profit** (array of float, optional): 이익실현가 목록
  - 여러 TP 레벨 설정 가능
  - 첫 번째 값이 주요 TP로 사용됨
  - 미설정 시 TP 주문 생성 안 함
- **is_DCA** (bool, optional): DCA(Dollar Cost Averaging) 모드
  - True: 기존 포지션에 추가 진입 (평균 단가 조정)
  - False: 신규 포지션 진입
  - 기본값: False
- **is_hedge** (bool, optional): 헤지 포지션 여부
  - True: 반대 방향 포지션으로 헤지
  - False: 일반 포지션
  - 기본값: False
- **hedge_tp_price** (float, optional): 헤지 포지션 TP
- **hedge_sl_price** (float, optional): 헤지 포지션 SL

## 동작 방식

1. **사용자 인증**: Redis/TimescaleDB에서 API 키 조회
2. **TradingService 생성**: CCXT 클라이언트 초기화
3. **파라미터 검증**: direction, size, leverage 유효성 확인
4. **포지션 오픈**: OKX API를 통한 시장가 주문 실행
5. **TP/SL 설정**: take_profit, stop_loss가 있으면 조건부 주문 생성
6. **DCA 처리**: is_DCA=True인 경우 기존 TP/SL 취소 후 재생성
7. **Redis 동기화**: 포지션 정보를 Redis에 저장
8. **응답 반환**: 포지션 생성 결과 및 메타데이터

## 반환 정보 (PositionResponse)

- **symbol** (string): 거래 심볼
- **side** (string): 포지션 방향 (long/short)
- **size** (float): 포지션 크기
- **entry_price** (float): 평균 진입가
- **leverage** (float): 레버리지
- **sl_price** (float): 손절가
- **tp_prices** (array): 이익실현가 목록
- **order_id** (string): 주문 ID
- **last_filled_price** (float): 최종 체결가

## 사용 시나리오

-  **롱 포지션**: 상승 추세 포착, 지지선 반등 매수
-  **숏 포지션**: 하락 추세 포착, 저항선 돌파 실패
-  **TP/SL 설정**: 리스크 관리 및 자동 청산
-  **DCA 전략**: 가격 하락 시 추가 매수로 평균 단가 낮춤
-  **헤지**: 기존 포지션 리스크 헤지

## 주의사항

- 충분한 잔고가 있어야 포지션 오픈 가능
- 레버리지가 높을수록 청산 리스크 증가
- DCA 모드는 기존 포지션이 있을 때만 유효
- TP/SL 가격은 진입가 대비 논리적으로 유효해야 함
- 시장가 주문은 슬리피지가 발생할 수 있음

## 예시 요청

```bash
# 기본 롱 포지션 (TP/SL 포함)
curl -X POST "http://localhost:8000/position/open" \\
  -H "Content-Type: application/json" \\
  -d '{
    "user_id": 1709556958,
    "symbol": "BTC-USDT-SWAP",
    "direction": "long",
    "size": 0.1,
    "leverage": 10,
    "stop_loss": 89520.0,
    "take_profit": [96450.6, 96835.6, 97124.4]
  }'

# DCA 모드 추가 진입
curl -X POST "http://localhost:8000/position/open" \\
  -H "Content-Type: application/json" \\
  -d '{
    "user_id": 1709556958,
    "symbol": "BTC-USDT-SWAP",
    "direction": "long",
    "size": 0.05,
    "is_DCA": true
  }'

# 숏 포지션 (헤지)
curl -X POST "http://localhost:8000/position/open" \\
  -H "Content-Type: application/json" \\
  -d '{
    "user_id": 1709556958,
    "symbol": "ETH-USDT-SWAP",
    "direction": "short",
    "size": 1.0,
    "leverage": 5,
    "is_hedge": true
  }'
```
""",
   responses={
       200: {
           "description": " 포지션 생성 성공",
           "content": {
               "application/json": {
                   "examples": {
                       "long_position_with_tp_sl": {
                           "summary": "롱 포지션 (TP/SL 포함)",
                           "value": {
                               "symbol": "BTC-USDT-SWAP",
                               "side": "long",
                               "size": 0.1,
                               "entry_price": 92450.5,
                               "leverage": 10.0,
                               "sl_price": 89520.0,
                               "tp_prices": [96450.6, 96835.6, 97124.4],
                               "order_id": "123456789012345678",
                               "last_filled_price": 92450.5
                           }
                       },
                       "short_position_simple": {
                           "summary": "숏 포지션 (기본)",
                           "value": {
                               "symbol": "ETH-USDT-SWAP",
                               "side": "short",
                               "size": 1.0,
                               "entry_price": 2650.3,
                               "leverage": 10.0,
                               "sl_price": 0.0,
                               "tp_prices": [],
                               "order_id": "987654321098765432",
                               "last_filled_price": 2650.3
                           }
                       },
                       "dca_entry": {
                           "summary": "DCA 추가 진입",
                           "value": {
                               "symbol": "BTC-USDT-SWAP",
                               "side": "long",
                               "size": 0.05,
                               "entry_price": 91200.0,
                               "leverage": 10.0,
                               "sl_price": 89000.0,
                               "tp_prices": [95000.0],
                               "order_id": "555666777888999000",
                               "last_filled_price": 91200.0
                           }
                       },
                       "hedge_position": {
                           "summary": "헤지 포지션",
                           "value": {
                               "symbol": "SOL-USDT-SWAP",
                               "side": "short",
                               "size": 10.0,
                               "entry_price": 125.5,
                               "leverage": 5.0,
                               "sl_price": 130.0,
                               "tp_prices": [120.0],
                               "order_id": "111222333444555666",
                               "last_filled_price": 125.5
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
                       "insufficient_balance": {
                           "summary": "잔고 부족",
                           "value": {
                               "detail": "주문에 필요한 잔고가 부족합니다. 현재 잔고: 100 USDT, 필요 마진: 150 USDT"
                           }
                       },
                       "invalid_direction": {
                           "summary": "잘못된 포지션 방향",
                           "value": {
                               "detail": "direction must be 'long' or 'short'"
                           }
                       },
                       "invalid_size": {
                           "summary": "잘못된 포지션 크기",
                           "value": {
                               "detail": "주문 수량이 최소 주문 수량(0.01)보다 작습니다"
                           }
                       },
                       "invalid_tp_price": {
                           "summary": "잘못된 TP 가격",
                           "value": {
                               "detail": "롱 포지션의 TP 가격은 진입가보다 높아야 합니다"
                           }
                       },
                       "invalid_sl_price": {
                           "summary": "잘못된 SL 가격",
                           "value": {
                               "detail": "숏 포지션의 SL 가격은 진입가보다 낮아야 합니다"
                           }
                       }
                   }
               }
           }
       },
       401: {
           "description": " 인증 실패",
           "content": {
               "application/json": {
                   "examples": {
                       "invalid_api_keys": {
                           "summary": "잘못된 API 키",
                           "value": {
                               "detail": "유효하지 않은 API 키입니다"
                           }
                       },
                       "api_permission_denied": {
                           "summary": "API 권한 부족",
                           "value": {
                               "detail": "API 키에 트레이딩 권한이 없습니다"
                           }
                       }
                   }
               }
           }
       },
       404: {
           "description": " 리소스를 찾을 수 없음",
           "content": {
               "application/json": {
                   "examples": {
                       "user_not_found": {
                           "summary": "사용자 없음",
                           "value": {
                               "detail": "User not found"
                           }
                       },
                       "api_keys_not_found": {
                           "summary": "API 키 없음",
                           "value": {
                               "detail": "API keys not found in Redis"
                           }
                       }
                   }
               }
           }
       },
       429: {
           "description": "⏱️ 요청 속도 제한 초과",
           "content": {
               "application/json": {
                   "examples": {
                       "rate_limit_exceeded": {
                           "summary": "API 요청 한도 초과",
                           "value": {
                               "detail": "Rate limit exceeded. Please try again later.",
                               "retry_after": 60
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
                       "exchange_api_error": {
                           "summary": "거래소 API 오류",
                           "value": {
                               "detail": "거래소 연결 오류: Connection timeout"
                           }
                       },
                       "order_execution_failed": {
                           "summary": "주문 실행 실패",
                           "value": {
                               "detail": "Order execution failed: Market is closed"
                           }
                       },
                       "trading_service_error": {
                           "summary": "TradingService 오류",
                           "value": {
                               "detail": "Failed to create TradingService for user"
                           }
                       }
                   }
               }
           }
       },
       503: {
           "description": " 서비스 이용 불가",
           "content": {
               "application/json": {
                   "examples": {
                       "insufficient_funds": {
                           "summary": "자금 부족 (일시적)",
                           "value": {
                               "detail": "자금 부족으로 주문을 실행할 수 없습니다. 잠시 후 다시 시도해주세요.",
                               "retry_after": 300
                           }
                       },
                       "exchange_maintenance": {
                           "summary": "거래소 점검",
                           "value": {
                               "detail": "거래소가 점검 중입니다",
                               "retry_after": 1800
                           }
                       }
                   }
               }
           }
       }
   }
)
async def open_position_endpoint(
    req: OpenPositionRequest = Body(
        ...,
        example={
            "basic_example": {
                "summary": "기본 포지션 생성 예시",
                "value": {
                    "user_id": 1709556958,
                    "symbol": "BTC-USDT-SWAP",
                    "direction": "long",
                    "size": 0.1,
                    "leverage": 10,
                    "stop_loss": 89520.0,
                    "take_profit": [96450.6, 96835.6, 97124.4],
                    "is_DCA": True,
                    "order_concept": "",
                    "is_hedge": False,
                    "hedge_tp_price": 0,
                    "hedge_sl_price": 0
                }
            }
        },
        description="포지션 생성 매개변수"
    )
) -> PositionResponse:
    """
    지정된 매개변수로 새로운 트레이딩 포지션을 생성합니다.

    매개변수:
    - user_id (str): API 키 조회를 위한 사용자 식별자
    - symbol (str): 거래 쌍 심볼 (예: "BTC-USDT-SWAP")
    - direction (str): 포지션 방향 - "long" 또는 "short"
    - size (float): 기준 화폐 단위의 포지션 크기
    - leverage (float, 선택): 포지션 레버리지, 기본값 10.0
    - stop_loss (float, 선택): 손절가 설정
    - take_profit (float, 선택): 이익실현가 설정
    - is_DCA (bool, 선택): DCA 모드 활성화 여부, 기본값 False

    반환값:
    - 생성된 포지션 상세 정보가 담긴 PositionResponse 객체

    발생 가능한 예외:
    - HTTPException(400): 잘못된 매개변수 또는 불충분한 잔고
    - HTTPException(401): 잘못된 API 인증 정보
    - HTTPException(500): 거래소 연결 오류
    """
    try:
        # user_id를 OKX UID로 변환
        okx_uid = await resolve_user_identifier(str(req.user_id))

        # 트레이딩 상태 체크 - 중지되었으면 주문하지 않음
        redis = await get_redis_client()
        trading_status = await redis.get(f"user:{okx_uid}:trading:status")
        if isinstance(trading_status, bytes):
            trading_status = trading_status.decode('utf-8')

        if trading_status != "running":
            logger.info(f"[{okx_uid}] 트레이딩이 중지된 상태입니다. 주문을 생성하지 않습니다. (status: {trading_status})")
            raise HTTPException(
                status_code=400,
                detail=f"트레이딩이 중지된 상태입니다. 주문을 생성할 수 없습니다. (현재 상태: {trading_status})"
            )

        client = await TradingService.create_for_user(okx_uid)

        try:
            is_dca = req.is_DCA
        except AttributeError:
            is_dca = False

        try:
            is_hedge = req.is_hedge
        except AttributeError:
            is_hedge = False

        try:
            hedge_tp_price = req.hedge_tp_price
        except AttributeError:
            hedge_tp_price = None

        try:
            hedge_sl_price = req.hedge_sl_price
        except AttributeError:
            hedge_sl_price = None

        # take_profit 변환: list → float (첫 번째 값 사용)
        take_profit_value = req.take_profit[0] if req.take_profit and len(req.take_profit) > 0 else None

        try:
            position_result = await client.open_position(
                user_id=okx_uid,
                symbol=req.symbol,
                direction=req.direction,
                size=req.size,
                leverage=req.leverage,
                stop_loss=req.stop_loss,
                take_profit=take_profit_value,
                is_DCA=is_dca,
                is_hedge=is_hedge,
                hedge_tp_price=hedge_tp_price,
                hedge_sl_price=hedge_sl_price
            )
        except Exception as e:
            error_msg = str(e)
            # 자금 부족 에러 감지
            if "자금 부족" in error_msg or "Insufficient" in error_msg:
                # 503 Service Unavailable 상태 코드를 사용하여 일시적인 불가용성을 나타냄
                raise HTTPException(
                    status_code=503, 
                    detail=error_msg,
                    headers={"Retry-After": "300"}  # 5분 후 재시도 가능함을 나타냄
                )
            raise HTTPException(status_code=400, detail=error_msg)
        # position_result가 문자열인 경우 처리
        if isinstance(position_result, str):
            # 자금 부족 에러 감지
            if "자금 부족" in position_result or "Insufficient" in position_result:
                raise HTTPException(
                    status_code=503,
                    detail=position_result,
                    headers={"Retry-After": "300"}
                )
            raise ValueError(position_result)
            
        # position_result가 딕셔너리인 경우 처리
        if isinstance(position_result, dict):
            return PositionResponse(
                symbol=position_result.get('symbol', req.symbol),
                side=position_result.get('side', req.direction),
                size=position_result.get('size', req.size),
                entry_price=position_result.get('entry_price', 0.0),
                leverage=position_result.get('leverage', req.leverage),
                sl_price=position_result.get('sl_price', req.stop_loss),
                tp_prices=position_result.get('tp_prices', req.take_profit),
                order_id=position_result.get('order_id', ''),
                last_filled_price=position_result.get('last_filled_price', 0.0)
            )
            
        # Position 객체인 경우 처리
        return PositionResponse(
            symbol=position_result.symbol,
            side=position_result.side,
            size=position_result.size,
            entry_price=position_result.entry_price,
            leverage=position_result.leverage,
            sl_price=position_result.sl_price,
            tp_prices=position_result.tp_prices,
            order_id=position_result.order_id,
            last_filled_price=position_result.last_filled_price
        )
    except HTTPException:
        # HTTPException은 이미 적절한 메시지와 상태 코드를 가지고 있으므로 그대로 raise
        raise
    except Exception as e:
        log_error(
            error=e,
            user_id=req.user_id,
            additional_info={
                "function": "open_position_endpoint",
                "timestamp": datetime.now().isoformat()
            }
        )
        logger.error(f"[open_position] Error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/close",
    summary="포지션 청산 (전체/부분)",
    description="""
# 포지션 청산 (전체/부분)

기존 포지션을 전체 또는 부분적으로 청산합니다. 청산 비율 또는 수량을 지정하여 포지션을 종료할 수 있습니다.

## 요청 본문 (ClosePositionRequest)

### 필수 파라미터

- **user_id** (int, required): 사용자 식별자
  - OKX UID (18자리) 또는 텔레그램 ID
  - 텔레그램 ID인 경우 자동으로 OKX UID로 변환
- **symbol** (string, required): 거래 심볼
  - 형식: "BTC-USDT-SWAP", "ETH-USDT-SWAP" 등
  - 청산할 포지션의 심볼과 정확히 일치해야 함

### 선택 파라미터

- **side** (string, optional): 포지션 방향
  - "long": 롱 포지션 청산
  - "short": 숏 포지션 청산
  - 기본값: "long"
  - 미지정 시 TradingService가 자동으로 심볼의 포지션 방향 감지
- **size** (float, optional): 청산할 수량
  - 기준 화폐 단위 (예: BTC 수량)
  - 0 또는 미지정 시 percent 사용
  - size 우선순위가 percent보다 높음
- **percent** (float, optional): 청산 비율
  - 범위: 0 ~ 100
  - 100: 전체 청산
  - 50: 절반 청산
  - size가 지정되지 않은 경우에만 사용됨
- **comment** (string, optional): 청산 사유
  - 로깅 및 추적을 위한 메모
  - 예: "TP 도달", "수동 청산", "리스크 관리"

## 동작 방식

1. **사용자 인증**: Redis/TimescaleDB에서 API 키 조회
2. **TradingService 생성**: CCXT 클라이언트 초기화
3. **포지션 확인**: Redis에서 현재 포지션 상태 조회
4. **청산량 계산**:
   - size 지정: 해당 수량만큼 청산
   - percent 지정: 포지션의 지정 비율만큼 청산
   - 미지정: 전체 포지션 청산
5. **주문 실행**: OKX API를 통한 시장가 청산 주문
6. **Redis 업데이트**: 포지션 상태 동기화
7. **TP/SL 취소**: 청산 완료 시 관련 TP/SL 주문 자동 취소
8. **응답 반환**: 청산 성공 여부 및 메타데이터

## 반환 정보

- **success** (boolean): 청산 성공 여부 (true/false)
- **message** (string): 결과 메시지

## 사용 시나리오

-  **이익 실현**: 목표 수익 달성 시 전체 또는 부분 청산
-  **손절**: 손실 확대 방지를 위한 조기 청산
-  **리밸런싱**: 포트폴리오 비율 조정을 위한 부분 청산
- ⚖️ **리스크 관리**: 변동성 증가 시 포지션 축소
-  **전략 전환**: 시장 상황 변화에 따른 포지션 종료

## 청산 방식 비교

### 전체 청산
- **size**: 미지정 또는 0
- **percent**: 100 또는 미지정
- 포지션 전체를 한 번에 청산

### 부분 청산 (비율)
- **size**: 미지정 또는 0
- **percent**: 1 ~ 99
- 포지션의 일부를 비율로 청산

### 부분 청산 (수량)
- **size**: 청산할 구체적 수량
- **percent**: 무시됨
- 정확한 수량만큼 청산

## 주의사항

- 청산 시 TP/SL 주문이 자동으로 취소됩니다
- 시장가 청산은 슬리피지가 발생할 수 있습니다
- 부분 청산 후 남은 포지션은 유지됩니다
- 포지션이 없는 경우 404 오류 반환
- size와 percent를 동시 지정 시 size가 우선됩니다

## 예시 요청

```bash
# 전체 청산
curl -X POST "http://localhost:8000/position/close" \\
  -H "Content-Type: application/json" \\
  -d '{
    "user_id": 1709556958,
    "symbol": "BTC-USDT-SWAP",
    "side": "long",
    "comment": "목표 수익 달성"
  }'

# 50% 부분 청산
curl -X POST "http://localhost:8000/position/close" \\
  -H "Content-Type: application/json" \\
  -d '{
    "user_id": 1709556958,
    "symbol": "ETH-USDT-SWAP",
    "side": "short",
    "percent": 50,
    "comment": "리스크 감소"
  }'

# 수량 지정 청산
curl -X POST "http://localhost:8000/position/close" \\
  -H "Content-Type: application/json" \\
  -d '{
    "user_id": 1709556958,
    "symbol": "SOL-USDT-SWAP",
    "side": "long",
    "size": 5.0,
    "comment": "부분 이익 실현"
  }'
```
""",
    responses={
        200: {
            "description": " 포지션 청산 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "full_close_success": {
                            "summary": "전체 청산 성공",
                            "value": {
                                "success": True,
                                "message": "Position closed successfully."
                            }
                        },
                        "partial_close_percent": {
                            "summary": "50% 부분 청산 성공",
                            "value": {
                                "success": True,
                                "message": "Position closed successfully. (50% closed)"
                            }
                        },
                        "partial_close_size": {
                            "summary": "수량 지정 청산 성공",
                            "value": {
                                "success": True,
                                "message": "Position closed successfully. (0.05 BTC closed)"
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
                        "invalid_percent": {
                            "summary": "잘못된 청산 비율",
                            "value": {
                                "detail": "percent must be between 0 and 100"
                            }
                        },
                        "invalid_size": {
                            "summary": "잘못된 청산 수량",
                            "value": {
                                "detail": "청산 수량이 보유 포지션(0.1 BTC)보다 큽니다"
                            }
                        },
                        "invalid_side": {
                            "summary": "잘못된 포지션 방향",
                            "value": {
                                "detail": "side must be 'long' or 'short'"
                            }
                        },
                        "close_order_failed": {
                            "summary": "청산 주문 실패",
                            "value": {
                                "detail": "Failed to execute close order: Insufficient position"
                            }
                        }
                    }
                }
            }
        },
        401: {
            "description": " 인증 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_api_keys": {
                            "summary": "잘못된 API 키",
                            "value": {
                                "detail": "유효하지 않은 API 키입니다"
                            }
                        },
                        "api_permission_denied": {
                            "summary": "API 권한 부족",
                            "value": {
                                "detail": "API 키에 트레이딩 권한이 없습니다"
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 포지션을 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "no_position": {
                            "summary": "활성 포지션 없음",
                            "value": {
                                "detail": "포지션 청산 실패 혹은 활성화된 포지션이 없습니다."
                            }
                        },
                        "user_not_found": {
                            "summary": "사용자 없음",
                            "value": {
                                "detail": "User not found"
                            }
                        },
                        "symbol_not_found": {
                            "summary": "심볼에 포지션 없음",
                            "value": {
                                "detail": "No active position found for symbol BTC-USDT-SWAP"
                            }
                        }
                    }
                }
            }
        },
        429: {
            "description": "⏱️ 요청 속도 제한 초과",
            "content": {
                "application/json": {
                    "examples": {
                        "rate_limit_exceeded": {
                            "summary": "API 요청 한도 초과",
                            "value": {
                                "detail": "Rate limit exceeded. Please try again later.",
                                "retry_after": 60
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
                        "exchange_api_error": {
                            "summary": "거래소 API 오류",
                            "value": {
                                "detail": "거래소 연결 오류: Connection timeout"
                            }
                        },
                        "redis_sync_error": {
                            "summary": "Redis 동기화 실패",
                            "value": {
                                "detail": "Failed to update position state in Redis"
                            }
                        },
                        "trading_service_error": {
                            "summary": "TradingService 오류",
                            "value": {
                                "detail": "Failed to create TradingService for user"
                            }
                        },
                        "cancel_orders_failed": {
                            "summary": "TP/SL 취소 실패",
                            "value": {
                                "detail": "Position closed but failed to cancel TP/SL orders"
                            }
                        }
                    }
                }
            }
        },
        503: {
            "description": " 서비스 이용 불가",
            "content": {
                "application/json": {
                    "examples": {
                        "exchange_maintenance": {
                            "summary": "거래소 점검",
                            "value": {
                                "detail": "거래소가 점검 중입니다",
                                "retry_after": 1800
                            }
                        },
                        "market_closed": {
                            "summary": "시장 종료",
                            "value": {
                                "detail": "Market is currently closed"
                            }
                        }
                    }
                }
            }
        }
    }
)
async def close_position_endpoint(req: ClosePositionRequest) -> Dict[str, Any]:
    """
    TradingService.close_position() 호출 → 포지션 청산
    """
    print("close_position_endpoint", req)
    try:
        # user_id를 OKX UID로 변환
        okx_uid = await resolve_user_identifier(str(req.user_id))

        client = await TradingService.create_for_user(okx_uid)

        # side가 None이면 기본값 설정
        position_side = req.side if req.side is not None else "long"

        # size가 None이고 percent가 지정된 경우에만 percent 사용
        if (req.size is None or req.size == 0) and req.percent and req.percent > 0:
            use_size = None  # trading_service가 percent를 사용하도록 함
        else:
            use_size = req.size

        success = await client.close_position(
            user_id=okx_uid,
            symbol=req.symbol,
            side=position_side,
            size=use_size,
            reason=req.comment
        )

        if not success:
            raise HTTPException(
                status_code=404,
                detail="포지션 청산 실패 혹은 활성화된 포지션이 없습니다."
            )
        return {"success": True, "message": "Position closed successfully."}
    except Exception as e:
        log_error(
            error=e,
            user_id=okx_uid,
            additional_info={
                "function": "close_position_endpoint",
                "timestamp": datetime.now().isoformat()
            }
        )   
        logger.error(f"[close_position] Error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))