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
from HYPERRSI.src.trading.utils.position_handler.constants import (
    DCA_COUNT_KEY,
    DCA_LEVELS_KEY,
    POSITION_KEY,
    POSITION_STATE_KEY,
    SL_DATA_KEY,
    TP_DATA_KEY,
)
from HYPERRSI.src.utils.error_logger import log_error_to_db
from shared.database.redis_helper import get_redis_client
from shared.database.redis_patterns import redis_context, RedisTimeout
from shared.dtos.trading import ClosePositionRequest, OpenPositionRequest, PositionResponse
from shared.helpers.user_id_resolver import get_okx_uid_from_telegram, resolve_user_identifier
from shared.utils.redis_utils import get_user_settings as redis_get_user_settings

from HYPERRSI.src.api.trading.Calculate_signal import TrendStateCalculator
from HYPERRSI.src.trading.trading_service import TradingService
from HYPERRSI.src.trading.utils.position_handler.entry import handle_no_position

from HYPERRSI.src.api.routes.position_docs import (
    FETCH_OKX_POSITION_DESCRIPTION,
    FETCH_OKX_POSITION_RESPONSES,
    SET_POSITION_LEVERAGE_DESCRIPTION,
    SET_POSITION_LEVERAGE_RESPONSES,
    OPEN_POSITION_DESCRIPTION,
    OPEN_POSITION_RESPONSES,
    CLOSE_POSITION_DESCRIPTION,
    CLOSE_POSITION_RESPONSES,
    GET_POSITION_DETAIL_DESCRIPTION,
    GET_POSITION_DETAIL_RESPONSES,
)

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


class EntrySignalPayload(BaseModel):
    is_oversold: bool = Field(description="RSI 기준 과매도 여부")
    is_overbought: bool = Field(description="RSI 기준 과매수 여부")


class EntryTriggerRequest(BaseModel):
    user_id: str = Field(description="텔레그램 ID 또는 OKX UID")
    symbol: str = Field(description="거래 심볼 (예: BTC-USDT-SWAP)")
    timeframe: str = Field(description="진입을 판단한 타임프레임")
    current_rsi: float = Field(description="현재 RSI 값")
    rsi_signals: EntrySignalPayload
    current_state: int = Field(..., ge=-2, le=2, description="TrendStateCalculator가 산출한 현재 상태")
    settings: Optional[Dict[str, Any]] = Field(
        default=None,
        description="(옵션) 사용자 설정 덮어쓰기. 지정하지 않으면 Redis 설정을 사용"
    )

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
        # errordb 로깅
        log_error_to_db(
            error=e,
            error_type="APIKeyFetchError",
            user_id=user_id,
            severity="ERROR",
            metadata={"component": "position.get_user_api_keys"}
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
    description=FETCH_OKX_POSITION_DESCRIPTION,
    responses=FETCH_OKX_POSITION_RESPONSES
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
        #  OrderWrapper 사용 (Exchange 객체 재사용 - CCXT 권장사항)
        from HYPERRSI.src.trading.services.order_wrapper import OrderWrapper
        client = OrderWrapper(str(okx_uid), api_keys)

        # load_markets()는 OrderWrapper 내부에서 자동으로 캐싱됨

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
            # errordb 로깅
            log_error_to_db(
                error=e,
                error_type="CCXTClientCloseError",
                user_id=okx_uid,
                severity="WARNING",
                symbol=symbol,
                metadata={"component": "position.fetch_okx_position"}
            )
            logger.warning(f"CCXT 클라이언트 종료 중 오류 발생: {str(e)}")

        # 포지션이 없거나 비어있는 경우 처리
        if not positions or all(float(pos.get('info', {}).get('pos', 0)) == 0 for pos in positions):
            if symbol:
                # Use context manager for proper connection management and timeout protection
                async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
                    # 특정 심볼에 대한 포지션이 없는 경우, Redis에 저장된 해당 종목 포지션 키(long, short)를 삭제
                    for side in ['long', 'short']:
                        redis_key = POSITION_KEY.format(user_id=okx_uid, symbol=symbol, side=side)
                        await asyncio.wait_for(
                            redis.delete(redis_key),
                            timeout=RedisTimeout.FAST_OPERATION
                        )
                    position_state_key = POSITION_STATE_KEY.format(user_id=okx_uid, symbol=symbol)
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
                # errordb 로깅
                log_error_to_db(
                    error=e,
                    error_type="PositionValidationError",
                    user_id=okx_uid,
                    severity="WARNING",
                    symbol=symbol,
                    metadata={"component": "position.fetch_okx_position", "position_data": str(pos)[:500]}
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
                    redis_key = POSITION_KEY.format(user_id=okx_uid, symbol=curr_symbol, side=side)
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
        # errordb 로깅
        log_error_to_db(
            error=e,
            error_type="FetchPositionError",
            user_id=okx_uid,
            severity="ERROR",
            symbol=symbol,
            metadata={"component": "position.fetch_okx_position"}
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
    description=SET_POSITION_LEVERAGE_DESCRIPTION,
    responses=SET_POSITION_LEVERAGE_RESPONSES
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

        # OrderWrapper 사용 (Exchange 객체 재사용 - CCXT 권장사항)
        from HYPERRSI.src.trading.services.order_wrapper import OrderWrapper
        client = OrderWrapper(str(okx_uid), api_keys)

        # load_markets()는 OrderWrapper 내부에서 자동으로 캐싱됨

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
        # errordb 로깅
        log_error_to_db(
            error=e,
            error_type="LeverageSetError",
            user_id=user_id,
            severity="ERROR",
            symbol=symbol,
            metadata={"component": "position.set_leverage", "leverage": request.leverage, "marginMode": request.marginMode}
        )
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
    description=OPEN_POSITION_DESCRIPTION,
    responses=OPEN_POSITION_RESPONSES
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

        # 심볼별 트레이딩 상태 체크 - 중지되었으면 주문하지 않음
        redis = await get_redis_client()
        symbol = req.symbol
        trading_status = await redis.get(f"user:{okx_uid}:symbol:{symbol}:status")
        if isinstance(trading_status, bytes):
            trading_status = trading_status.decode('utf-8')

        if trading_status != "running":
            logger.info(f"[{okx_uid}] {symbol} 트레이딩이 중지된 상태입니다. 주문을 생성하지 않습니다. (status: {trading_status})")
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
            # errordb 로깅
            severity = "WARNING" if "자금 부족" in error_msg or "Insufficient" in error_msg else "ERROR"
            log_error_to_db(
                error=e,
                error_type="OpenPositionError",
                user_id=okx_uid,
                severity=severity,
                symbol=req.symbol,
                side=req.direction,
                metadata={"component": "position.open_position_endpoint", "is_dca": is_dca, "is_hedge": is_hedge}
            )
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
        # errordb 로깅
        log_error_to_db(
            error=e,
            error_type="OpenPositionEndpointError",
            user_id=req.user_id,
            severity="ERROR",
            symbol=req.symbol,
            side=req.direction,
            metadata={"component": "position.open_position_endpoint"}
        )
        logger.error(f"[open_position] Error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/entry-trigger",
    summary="외부 신호 기반 포지션 진입 실행",
    description="RSI·트렌드 신호와 현재 상태를 전달하면 HyperRSI의 handle_no_position 로직을 실행합니다."
)
async def trigger_manual_entry(request: EntryTriggerRequest) -> Dict[str, Any]:
    try:
        okx_uid = await resolve_user_identifier(str(request.user_id))

        # 설정 로드: 요청에서 오버라이드하거나 Redis에서 가져옴
        settings = request.settings
        if settings is None:
            redis = await get_redis_client()
            settings = await redis_get_user_settings(redis, okx_uid)

        if not settings:
            raise HTTPException(status_code=400, detail="사용자 설정을 찾을 수 없습니다.")

        trading_service = await TradingService.create_for_user(okx_uid)
        calculator = TrendStateCalculator()

        await handle_no_position(
            user_id=okx_uid,
            settings=settings,
            trading_service=trading_service,
            calculator=calculator,
            symbol=request.symbol,
            timeframe=request.timeframe,
            current_rsi=request.current_rsi,
            rsi_signals=request.rsi_signals.model_dump(),
            current_state=request.current_state
        )

        return {
            "status": "ok",
            "message": "Entry trigger processed",
            "user_id": okx_uid,
            "symbol": request.symbol
        }

    except HTTPException:
        raise
    except Exception as e:
        log_error(
            error=e,
            user_id=request.user_id,
            additional_info={
                "function": "trigger_manual_entry",
                "timestamp": datetime.now().isoformat()
            }
        )
        # errordb 로깅
        log_error_to_db(
            error=e,
            error_type="TriggerManualEntryError",
            user_id=request.user_id,
            severity="ERROR",
            symbol=request.symbol,
            metadata={"component": "position.trigger_manual_entry", "timeframe": request.timeframe}
        )
        logger.error(f"[entry-trigger] Error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/close",
    summary="포지션 청산 (전체/부분)",
    description=CLOSE_POSITION_DESCRIPTION,
    responses=CLOSE_POSITION_RESPONSES
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
        # errordb 로깅
        log_error_to_db(
            error=e,
            error_type="ClosePositionEndpointError",
            user_id=req.user_id,
            severity="ERROR",
            symbol=req.symbol,
            side=req.side,
            metadata={"component": "position.close_position_endpoint", "percent": req.percent}
        )
        logger.error(f"[close_position] Error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))


# ------------------------------------------------------
#  TP/SL/Trailing Stop 정보 조회 API
# ------------------------------------------------------
class StopLossInfo(BaseModel):
    price: Optional[float] = Field(None, description="손절 가격")
    algo_id: Optional[str] = Field(None, description="알고리즘 주문 ID")
    trigger_price: Optional[float] = Field(None, description="트리거 가격")


class TakeProfitInfo(BaseModel):
    price: Optional[float] = Field(None, description="익절 가격")
    size: Optional[float] = Field(None, description="익절 수량")
    algo_id: Optional[str] = Field(None, description="알고리즘 주문 ID")
    trigger_price: Optional[float] = Field(None, description="트리거 가격")


class TrailingStopInfo(BaseModel):
    active: bool = Field(False, description="트레일링 스톱 활성화 여부")
    price: Optional[float] = Field(None, description="현재 트레일링 스톱 가격")
    offset: Optional[float] = Field(None, description="트레일링 오프셋 값")
    highest_price: Optional[float] = Field(None, description="최고가 (롱 포지션)")
    lowest_price: Optional[float] = Field(None, description="최저가 (숏 포지션)")
    activation_price: Optional[float] = Field(None, description="트레일링 활성화 가격")


class PositionTPSLInfo(BaseModel):
    side: Optional[str] = Field(None, description="포지션 방향 (long/short)")
    entry_price: Optional[float] = Field(None, description="진입 가격")
    size: Optional[float] = Field(None, description="포지션 수량")
    leverage: Optional[float] = Field(None, description="레버리지")
    entry_count: Optional[int] = Field(None, description="현재 진입 횟수 (DCA 포함)")
    entry_time: Optional[int] = Field(None, description="포지션 진입/업데이트 시간 (Unix timestamp, 초)")


class DCAInfo(BaseModel):
    next_entry_price: Optional[float] = Field(None, description="다음 DCA 진입 가격")
    remaining_levels: int = Field(0, description="남은 DCA 레벨 수")
    all_levels: List[float] = Field(default_factory=list, description="모든 DCA 레벨 가격 목록")


class PositionDetailResponse(BaseModel):
    user_id: str = Field(..., description="사용자 ID")
    symbol: str = Field(..., description="거래 심볼")
    position: Optional[PositionTPSLInfo] = Field(None, description="포지션 정보")
    stop_loss: Optional[StopLossInfo] = Field(None, description="손절 정보")
    take_profit: List[TakeProfitInfo] = Field(default_factory=list, description="익절 정보 목록")
    trailing_stop: Optional[TrailingStopInfo] = Field(None, description="트레일링 스톱 정보")
    dca: Optional[DCAInfo] = Field(None, description="DCA(물타기) 정보")
    timestamp: str = Field(..., description="조회 시간")


@router.get(
    "/{user_id}/{symbol}/detail",
    response_model=PositionDetailResponse,
    summary="포지션 상세 정보 조회 (TP/SL/Trailing/DCA)",
    description=GET_POSITION_DETAIL_DESCRIPTION,
    responses=GET_POSITION_DETAIL_RESPONSES
)
async def get_position_detail(
    user_id: str = Path(..., example="1709556958", description="사용자 ID (텔레그램 ID 또는 OKX UID)"),
    symbol: str = Path(..., example="BTC-USDT-SWAP", description="거래 심볼")
) -> PositionDetailResponse:
    """
    특정 심볼의 포지션 상세 정보(TP/SL/Trailing Stop/DCA)를 조회합니다.
    """
    client = None
    try:
        # user_id를 OKX UID로 변환
        okx_uid = await resolve_user_identifier(user_id)
        logger.info(f"[get_position_detail] 입력 user_id={user_id}, 변환된 okx_uid={okx_uid}, symbol={symbol}")

        # Redis에서 API 키 가져오기
        api_keys = await get_user_api_keys(okx_uid)

        # OrderWrapper 사용
        from HYPERRSI.src.trading.services.order_wrapper import OrderWrapper
        client = OrderWrapper(str(okx_uid), api_keys)

        # 결과 초기화
        position_info = None
        stop_loss_info = None
        take_profit_list = []
        trailing_stop_info = None
        dca_info = None

        # Redis에서 포지션 정보 조회
        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            # 양방향(long/short) 포지션 확인
            position_side = None
            position_data = None

            for side in ['long', 'short']:
                position_key = POSITION_KEY.format(user_id=okx_uid, symbol=symbol, side=side)
                pos_data = await asyncio.wait_for(
                    redis.hgetall(position_key),
                    timeout=RedisTimeout.FAST_OPERATION
                )
                logger.debug(f"[get_position_detail] 조회 키={position_key}, 데이터 존재={bool(pos_data)}")
                if pos_data:
                    position_side = side
                    position_data = pos_data
                    logger.info(f"[get_position_detail] ✅ 포지션 발견: side={side}, entry_price={pos_data.get('entry_price')}, size={pos_data.get('size')}")
                    break

            if not position_data:
                logger.warning(f"[get_position_detail] ⚠️ 포지션 없음: okx_uid={okx_uid}, symbol={symbol}")

            if position_data:
                # 포지션 정보 파싱
                entry_price = float(position_data.get('entry_price', 0) or 0)
                size = float(position_data.get('size', 0) or 0)
                leverage = float(position_data.get('leverage', 0) or 0)

                # 현재 진입 횟수 조회
                dca_count_key = DCA_COUNT_KEY.format(user_id=okx_uid, symbol=symbol, side=position_side)
                dca_count_raw = await asyncio.wait_for(
                    redis.get(dca_count_key),
                    timeout=RedisTimeout.FAST_OPERATION
                )
                entry_count = None
                if dca_count_raw:
                    try:
                        count_val = dca_count_raw.decode() if isinstance(dca_count_raw, bytes) else dca_count_raw
                        entry_count = int(count_val)
                    except (ValueError, TypeError):
                        pass

                # 포지션 진입/업데이트 시간 조회
                entry_time = None
                last_update_time_raw = position_data.get('last_update_time')
                if last_update_time_raw:
                    try:
                        entry_time = int(last_update_time_raw)
                    except (ValueError, TypeError):
                        pass

                position_info = PositionTPSLInfo(
                    side=position_side,
                    entry_price=entry_price if entry_price > 0 else None,
                    size=size if size > 0 else None,
                    leverage=leverage if leverage > 0 else None,
                    entry_count=entry_count,
                    entry_time=entry_time
                )

                # Redis에 저장된 SL 가격 확인 (메인 hash → 별도 sl_data hash 순서로 조회)
                redis_sl_price = position_data.get('sl_price')
                if redis_sl_price:
                    try:
                        sl_price_val = float(redis_sl_price)
                        if sl_price_val > 0:
                            stop_loss_info = StopLossInfo(price=sl_price_val)
                    except (ValueError, TypeError):
                        pass

                # 별도 sl_data hash에서 SL 정보 조회 (메인 hash에 없는 경우)
                if not stop_loss_info:
                    sl_data_key = SL_DATA_KEY.format(user_id=okx_uid, symbol=symbol, side=position_side)
                    sl_data_raw = await asyncio.wait_for(
                        redis.hgetall(sl_data_key),
                        timeout=RedisTimeout.FAST_OPERATION
                    )
                    if sl_data_raw:
                        # bytes 디코딩
                        sl_data_decoded = {}
                        for k, v in sl_data_raw.items():
                            dk = k.decode() if isinstance(k, bytes) else k
                            dv = v.decode() if isinstance(v, bytes) else v
                            sl_data_decoded[dk] = dv

                        sl_trigger = sl_data_decoded.get('trigger_price') or sl_data_decoded.get('sl_price')
                        sl_order_id = sl_data_decoded.get('order_id') or sl_data_decoded.get('algo_id')
                        if sl_trigger:
                            try:
                                sl_price_val = float(sl_trigger)
                                if sl_price_val > 0:
                                    stop_loss_info = StopLossInfo(
                                        price=sl_price_val,
                                        algo_id=sl_order_id,
                                        trigger_price=sl_price_val
                                    )
                            except (ValueError, TypeError):
                                pass

                # 별도 tp_data에서 TP 정보 조회
                tp_data_key = TP_DATA_KEY.format(user_id=okx_uid, symbol=symbol, side=position_side)
                tp_data_raw = await asyncio.wait_for(
                    redis.get(tp_data_key),
                    timeout=RedisTimeout.FAST_OPERATION
                )

                # 디버깅: TP 데이터 존재 여부 확인
                tp_in_hash = position_data.get('tp_data')
                logger.info(f"[get_position_detail] TP 데이터 확인: 별도키={tp_data_key}, 존재={bool(tp_data_raw)}, 해시필드 tp_data 존재={bool(tp_in_hash)}")
                if tp_data_raw:
                    logger.debug(f"[get_position_detail] 별도 tp_data 내용: {tp_data_raw[:200] if isinstance(tp_data_raw, (str, bytes)) else tp_data_raw}")
                if tp_in_hash:
                    logger.debug(f"[get_position_detail] 해시 tp_data 내용: {tp_in_hash[:200] if isinstance(tp_in_hash, (str, bytes)) else tp_in_hash}")

                if tp_data_raw:
                    try:
                        tp_data_str = tp_data_raw.decode() if isinstance(tp_data_raw, bytes) else tp_data_raw
                        # JSON 배열 형식 파싱: [88010.6, 88186.3, 88361.9]
                        import json
                        tp_prices_list = json.loads(tp_data_str)
                        if isinstance(tp_prices_list, list):
                            for i, tp_price in enumerate(tp_prices_list):
                                try:
                                    tp_price_val = float(tp_price)
                                    if tp_price_val > 0:
                                        take_profit_list.append(TakeProfitInfo(
                                            price=tp_price_val,
                                            size=None,
                                            algo_id=None,
                                            trigger_price=tp_price_val
                                        ))
                                except (ValueError, TypeError):
                                    continue
                    except (json.JSONDecodeError, ValueError, TypeError):
                        pass

                # 트레일링 스톱 정보 조회
                trailing_active = position_data.get('trailing_stop_active', 'false')
                if isinstance(trailing_active, bytes):
                    trailing_active = trailing_active.decode()

                if str(trailing_active).lower() == 'true':
                    trailing_key = f"user:{okx_uid}:trailing:{symbol}:{position_side}"
                    ts_data = await asyncio.wait_for(
                        redis.hgetall(trailing_key),
                        timeout=RedisTimeout.FAST_OPERATION
                    )

                    if ts_data:
                        # bytes 디코딩
                        ts_decoded = {}
                        for k, v in ts_data.items():
                            dk = k.decode() if isinstance(k, bytes) else k
                            dv = v.decode() if isinstance(v, bytes) else v
                            ts_decoded[dk] = dv

                        trailing_stop_info = TrailingStopInfo(
                            active=True,
                            price=float(ts_decoded.get('trailing_stop_price', 0) or 0) or None,
                            offset=float(ts_decoded.get('trailing_offset', 0) or 0) or None,
                            highest_price=float(ts_decoded.get('highest_price', 0) or 0) or None,
                            lowest_price=float(ts_decoded.get('lowest_price', 0) or 0) or None,
                            activation_price=float(ts_decoded.get('activation_price', 0) or 0) or None
                        )
                    else:
                        trailing_stop_info = TrailingStopInfo(active=True)
                else:
                    trailing_stop_info = TrailingStopInfo(active=False)

                # DCA 레벨 정보 조회
                dca_levels_key = DCA_LEVELS_KEY.format(user_id=okx_uid, symbol=symbol, side=position_side)
                dca_levels_raw = await asyncio.wait_for(
                    redis.lrange(dca_levels_key, 0, -1),  # 모든 레벨 가져오기
                    timeout=RedisTimeout.FAST_OPERATION
                )

                # 디버깅: DCA 레벨 데이터 확인
                logger.info(f"[get_position_detail] DCA 레벨 확인: 키={dca_levels_key}, 레벨수={len(dca_levels_raw) if dca_levels_raw else 0}")

                if dca_levels_raw and len(dca_levels_raw) > 0:
                    dca_levels_parsed = []
                    for level in dca_levels_raw:
                        try:
                            level_val = level.decode() if isinstance(level, bytes) else level
                            dca_levels_parsed.append(float(level_val))
                        except (ValueError, TypeError):
                            continue

                    if dca_levels_parsed:
                        dca_info = DCAInfo(
                            next_entry_price=dca_levels_parsed[0] if dca_levels_parsed else None,
                            remaining_levels=len(dca_levels_parsed),
                            all_levels=dca_levels_parsed
                        )

        # OKX API에서 알고리즘 주문 조회 (TP/SL)
        try:
            # 여러 타입의 알고리즘 주문 조회
            ord_types = ["conditional", "trigger", "oco", "move_order_stop"]
            all_algo_orders = []

            for ord_type in ord_types:
                try:
                    resp = await client.privateGetTradeOrdersAlgoPending(
                        params={"instId": symbol, "ordType": ord_type}
                    )
                    code = resp.get("code")
                    if code == "0":
                        data = resp.get("data", [])
                        all_algo_orders.extend(data)
                except Exception:
                    continue

            # 포지션 방향에 맞는 주문만 필터링
            for algo in all_algo_orders:
                algo_pos_side = algo.get('posSide', 'net').lower()

                # 포지션 방향 필터 (position_side가 있으면 해당 방향만)
                if position_side and algo_pos_side != 'net' and algo_pos_side != position_side:
                    continue

                sl_trigger_px = algo.get("slTriggerPx", "")
                tp_trigger_px = algo.get("tpTriggerPx", "")
                algo_id = algo.get("algoId", "")
                sz = algo.get("sz", "")

                # SL 주문
                if sl_trigger_px and sl_trigger_px != "":
                    stop_loss_info = StopLossInfo(
                        price=float(sl_trigger_px),
                        algo_id=algo_id,
                        trigger_price=float(sl_trigger_px)
                    )

                # TP 주문
                if tp_trigger_px and tp_trigger_px != "":
                    tp_info = TakeProfitInfo(
                        price=float(tp_trigger_px),
                        size=float(sz) if sz else None,
                        algo_id=algo_id,
                        trigger_price=float(tp_trigger_px)
                    )
                    take_profit_list.append(tp_info)

            # TP 주문을 가격 기준으로 정렬 (롱: 오름차순, 숏: 내림차순)
            if position_side == 'long':
                take_profit_list.sort(key=lambda x: x.price or 0)
            else:
                take_profit_list.sort(key=lambda x: x.price or 0, reverse=True)

        except Exception as e:
            logger.warning(f"알고리즘 주문 조회 실패: {str(e)}")

        return PositionDetailResponse(
            user_id=str(okx_uid),
            symbol=symbol,
            position=position_info,
            stop_loss=stop_loss_info,
            take_profit=take_profit_list,
            trailing_stop=trailing_stop_info,
            dca=dca_info,
            timestamp=str(datetime.utcnow())
        )

    except HTTPException:
        raise
    except Exception as e:
        log_error(
            error=e,
            user_id=user_id,
            additional_info={
                "function": "get_position_detail",
                "symbol": symbol,
                "timestamp": datetime.now().isoformat()
            }
        )
        log_error_to_db(
            error=e,
            error_type="GetPositionDetailError",
            user_id=user_id,
            severity="ERROR",
            symbol=symbol,
            metadata={"component": "position.get_position_detail"}
        )
        logger.error(f"포지션 상세 정보 조회 실패 ({symbol}): {str(e)}")
        raise HTTPException(status_code=500, detail=f"포지션 상세 정보 조회 실패: {str(e)}")
    finally:
        if client:
            try:
                await client.close()
            except Exception:
                pass
