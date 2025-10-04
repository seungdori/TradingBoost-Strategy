from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel  
from typing import List, Optional, Any
from HYPERRSI.src.core.database import redis_client
from HYPERRSI.src.core.logger import get_order_logs_by_user_id, get_order_logs_by_date_range, get_user_order_logs_from_file
from datetime import datetime

trading_log_router = APIRouter()

class TradingLogResponse(BaseModel):
    user_id: str
    execution_count: int
    execution_times: List[str]
    
class CleanupResponse(BaseModel):
    user_id: str
    symbol: str
    deleted_keys: list[str]
    success: bool

class OrderLogEntry(BaseModel):
    timestamp: str
    user_id: str
    symbol: str
    action_type: str
    position_side: str
    price: Optional[float] = None
    quantity: Optional[float] = None
    level: Optional[int] = None
    message: Optional[str] = None
    extra: Optional[dict] = None

class OrderLogsResponse(BaseModel):
    user_id: str
    total_count: int
    logs: List[OrderLogEntry]



#TODO : 기간 설정. date to date
@trading_log_router.get(
    "/trading-logs/{user_id}",
    response_model=TradingLogResponse,
    summary="Fetch trading logs for a user",
    description="주어진 user_id의 트레이딩 실행 횟수와 실행 시간을 Redis에서 조회합니다."
)
async def fetch_trading_logs(user_id: str) -> TradingLogResponse:
    """
    ### 트레이딩 로그 조회
    - **user_id**: 유저 식별자
    - Redis에서 다음 키를 조회합니다.
      - `user:{user_id}:trading_execution_count`
      - `user:{user_id}:trading_execution_times`
    - 반환값:
      - **execution_count**: 실행 횟수 (int)
      - **execution_times**: 실행 시간 목록 (List[str])
    """
    # Redis 키 설정
    count_key = f"user:{user_id}:trading_execution_count"
    times_key = f"user:{user_id}:trading_execution_times"
    
    # 실행 횟수 조회
    execution_count = await redis_client.get(count_key)
    if execution_count is None:
        execution_count = 0
    else:
        execution_count = int(execution_count)
    
    # 실행 시간 목록 조회 (List 타입)
    execution_times_bytes = await redis_client.lrange(times_key, 0, -1)
    # Redis에서 가져온 값은 bytes이므로, 디코딩을 해줘야 문자열로 변환됨
    execution_times = [x.decode("utf-8") for x in execution_times_bytes]
    
    return TradingLogResponse(
        user_id=user_id,
        execution_count=execution_count,
        execution_times=execution_times
    )
    
    



@trading_log_router.delete(
    "/cleanup/{user_id}/{symbol}",
    response_model=CleanupResponse,
    summary="Cleanup trading related data",
    description="특정 유저의 트레이딩 관련 데이터를 정리합니다."
)
async def cleanup_trading_data(user_id: str, symbol: str) -> CleanupResponse:
    """
    ### 트레이딩 데이터 정리
    - **user_id**: 유저 식별자
    - **symbol**: 거래 심볼
    
    다음 Redis 키들을 제거합니다:
    - tp_data
    - tp_state
    - dual_side_position
    - dca_levels
    - pyramiding_count
    """
    try:
        # 삭제할 키 패턴 정의
        keys_to_delete = [
            f"user:{user_id}:position:{symbol}:long",
            f"user:{user_id}:position:{symbol}:short",
            f"user:{user_id}:position:{symbol}:long:tp_data",
            f"user:{user_id}:position:{symbol}:short:tp_data",
            f"user:{user_id}:position:{symbol}:position_state",
            f"user:{user_id}:{symbol}:dual_side_position",
            f"user:{user_id}:position:{symbol}:long:dca_levels",
            f"user:{user_id}:position:{symbol}:short:dca_levels",
            f"user:{user_id}:position:{symbol}:pyramiding_count"
        ]
        
        # 키 삭제 실행
        deleted_keys = []
        for key in keys_to_delete:
            if await redis_client.exists(key):
                await redis_client.delete(key)
                deleted_keys.append(key)
        
        return CleanupResponse(
            user_id=user_id,
            symbol=symbol,
            deleted_keys=deleted_keys,
            success=True
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cleanup trading data: {str(e)}"
        )

@trading_log_router.get(
    "/order-logs/user/{user_id}",
    response_model=OrderLogsResponse,
    summary="사용자 ID별 거래 로그 조회",
    description="특정 사용자의 거래 주문 로그를 조회합니다."
)
async def get_user_order_logs(
    user_id: str,
    limit: int = Query(100, ge=1, le=1000, description="반환할 최대 로그 수"),
    offset: int = Query(0, ge=0, description="건너뛸 로그 수")
) -> OrderLogsResponse:
    """
    ### 사용자별 거래 로그 조회
    - **user_id**: 조회할 사용자 ID
    - **limit**: 반환할 최대 로그 수 (기본값: 100, 최대: 1000)
    - **offset**: 건너뛸 로그 수 (페이지네이션 용)
    
    반환값:
    - 사용자의 거래 로그 목록
    """
    try:
        # 사용자별 로그 파일에서 먼저 조회 시도
        logs = get_user_order_logs_from_file(user_id, limit, offset)
        
        # 응답 형식으로 변환
        formatted_logs = []
        for log in logs:
            # 기본 필드 추출
            entry = {
                "timestamp": log.get("timestamp", ""),
                "user_id": str(log.get("user_id", 0)),
                "symbol": log.get("symbol", ""),
                "action_type": log.get("action_type", ""),
                "position_side": log.get("position_side", ""),
                "price": log.get("price"),
                "quantity": log.get("quantity"),
                "level": log.get("level"),
                "message": log.get("message", "")
            }
            
            # 나머지 필드는 extra에 포함
            extra = {}
            for key, value in log.items():
                if key not in entry:
                    extra[key] = value
            
            entry["extra"] = extra if extra else None
            formatted_logs.append(OrderLogEntry(**entry))
        
        return OrderLogsResponse(
            user_id=str(user_id),
            total_count=len(formatted_logs),
            logs=formatted_logs
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"로그 조회 중 오류 발생: {str(e)}"
        )

@trading_log_router.get(
    "/order-logs/date-range",
    response_model=OrderLogsResponse,
    summary="날짜 범위별 거래 로그 조회",
    description="특정 날짜 범위 내의 거래 주문 로그를 조회합니다. 선택적으로 사용자 ID로 필터링할 수 있습니다."
)
async def get_order_logs_by_date(
    start_date: str = Query(..., description="시작 날짜 (YYYY-MM-DD)"),
    end_date: str = Query(..., description="종료 날짜 (YYYY-MM-DD)"),
    user_id: Optional[int] = Query(None, description="조회할 사용자 ID (선택적)"),
    limit: int = Query(100, ge=1, le=1000, description="반환할 최대 로그 수"),
    offset: int = Query(0, ge=0, description="건너뛸 로그 수")
) -> OrderLogsResponse:
    """
    ### 날짜 범위별 거래 로그 조회
    - **start_date**: 시작 날짜 (YYYY-MM-DD)
    - **end_date**: 종료 날짜 (YYYY-MM-DD)
    - **user_id**: 조회할 사용자 ID (선택적)
    - **limit**: 반환할 최대 로그 수 (기본값: 100, 최대: 1000)
    - **offset**: 건너뛸 로그 수 (페이지네이션 용)
    
    반환값:
    - 조건에 맞는 거래 로그 목록
    """
    try:
        # 날짜 문자열을 datetime 객체로 변환
        start_datetime = datetime.strptime(start_date, "%Y-%m-%d")
        end_datetime = datetime.strptime(end_date, "%Y-%m-%d")
        end_datetime = datetime(end_datetime.year, end_datetime.month, end_datetime.day, 23, 59, 59)
        
        # 로그 조회
        logs = get_order_logs_by_date_range(start_datetime, end_datetime, user_id, limit, offset)
        
        # 응답 형식으로 변환
        formatted_logs = []
        for log in logs:
            # 기본 필드 추출
            entry = {
                "timestamp": log.get("timestamp", ""),
                "user_id": str(log.get("user_id", 0)),
                "symbol": log.get("symbol", ""),
                "action_type": log.get("action_type", ""),
                "position_side": log.get("position_side", ""),
                "price": log.get("price"),
                "quantity": log.get("quantity"),
                "level": log.get("level"),
                "message": log.get("message", "")
            }
            
            # 나머지 필드는 extra에 포함
            extra = {}
            for key, value in log.items():
                if key not in entry:
                    extra[key] = value
            
            entry["extra"] = extra if extra else None
            formatted_logs.append(OrderLogEntry(**entry))
        
        return OrderLogsResponse(
            user_id=str(user_id or 0),  # user_id가 None이면 0을 문자열로 변환하여 사용
            total_count=len(formatted_logs),
            logs=formatted_logs
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"날짜 형식이 잘못되었습니다: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"로그 조회 중 오류 발생: {str(e)}"
        )