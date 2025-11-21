"""
HYPERRSI Error Logs API

HYPERRSI 시스템에서 발생한 에러 로그를 조회하는 API 엔드포인트
"""

from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field

from HYPERRSI.src.database.hyperrsi_error_db import get_recent_errors
from shared.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/errors", tags=["errors"])


class ErrorLogResponse(BaseModel):
    """에러 로그 응답 모델"""
    id: int
    timestamp: datetime
    user_id: Optional[str] = None
    telegram_id: Optional[int] = None
    error_type: str
    severity: str
    error_message: str
    error_details: Optional[dict] = None
    module: Optional[str] = None
    function_name: Optional[str] = None
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    traceback: Optional[str] = None
    symbol: Optional[str] = None
    side: Optional[str] = None
    order_type: Optional[str] = None
    position_info: Optional[dict] = None
    metadata: Optional[dict] = None
    request_id: Optional[str] = None
    resolved: bool = False
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    resolution_notes: Optional[str] = None


class ErrorLogsListResponse(BaseModel):
    """에러 로그 목록 응답"""
    total: int = Field(..., description="총 에러 개수")
    errors: List[ErrorLogResponse] = Field(..., description="에러 목록")


@router.get("/", response_model=ErrorLogsListResponse)
async def get_error_logs(
    user_id: Optional[str] = Query(None, description="사용자 ID로 필터링"),
    telegram_id: Optional[int] = Query(None, description="텔레그램 ID로 필터링"),
    severity: Optional[str] = Query(None, description="심각도로 필터링 (DEBUG, INFO, WARNING, ERROR, CRITICAL)"),
    error_type: Optional[str] = Query(None, description="에러 타입으로 필터링"),
    symbol: Optional[str] = Query(None, description="거래 심볼로 필터링"),
    resolved: Optional[bool] = Query(None, description="해결 여부로 필터링"),
    hours: int = Query(24, description="조회할 시간 범위 (시간 단위)", ge=1, le=720),
    limit: int = Query(100, description="최대 조회 개수", ge=1, le=1000)
):
    """
    HYPERRSI 에러 로그 조회

    - **user_id**: 사용자 ID로 필터링 (옵션)
    - **telegram_id**: 텔레그램 ID로 필터링 (옵션)
    - **severity**: 심각도로 필터링 (옵션)
    - **error_type**: 에러 타입으로 필터링 (옵션)
    - **symbol**: 거래 심볼로 필터링 (옵션)
    - **resolved**: 해결 여부로 필터링 (옵션)
    - **hours**: 조회할 시간 범위 (기본: 24시간)
    - **limit**: 최대 조회 개수 (기본: 100개, 최대: 1000개)
    """
    try:
        # 시작 시간 계산
        since = datetime.now() - timedelta(hours=hours)

        # 필터 구성
        filters = {}
        if user_id:
            filters['user_id'] = user_id
        if telegram_id:
            filters['telegram_id'] = telegram_id
        if severity:
            filters['severity'] = severity.upper()
        if error_type:
            filters['error_type'] = error_type
        if symbol:
            filters['symbol'] = symbol
        if resolved is not None:
            filters['resolved'] = resolved

        # 에러 로그 조회
        errors = await get_recent_errors(
            since=since,
            limit=limit,
            **filters
        )

        # 응답 형식으로 변환
        error_responses = [
            ErrorLogResponse(
                id=error['id'],
                timestamp=error['timestamp'],
                user_id=error.get('user_id'),
                telegram_id=error.get('telegram_id'),
                error_type=error['error_type'],
                severity=error['severity'],
                error_message=error['error_message'],
                error_details=error.get('error_details'),
                module=error.get('module'),
                function_name=error.get('function_name'),
                file_path=error.get('file_path'),
                line_number=error.get('line_number'),
                traceback=error.get('traceback'),
                symbol=error.get('symbol'),
                side=error.get('side'),
                order_type=error.get('order_type'),
                position_info=error.get('position_info'),
                metadata=error.get('metadata'),
                request_id=error.get('request_id'),
                resolved=error.get('resolved', False),
                resolved_at=error.get('resolved_at'),
                resolved_by=error.get('resolved_by'),
                resolution_notes=error.get('resolution_notes')
            )
            for error in errors
        ]

        return ErrorLogsListResponse(
            total=len(error_responses),
            errors=error_responses
        )

    except Exception as e:
        logger.error(f"에러 로그 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"에러 로그 조회 실패: {str(e)}")


@router.get("/stats", response_model=dict)
async def get_error_stats(
    hours: int = Query(24, description="통계 조회 시간 범위 (시간)", ge=1, le=720)
):
    """
    에러 통계 조회

    최근 N시간 동안의 에러 통계를 반환합니다.
    - 심각도별 개수
    - 에러 타입별 개수
    - 사용자별 개수
    - 심볼별 개수
    """
    try:
        since = datetime.now() - timedelta(hours=hours)

        # 모든 에러 조회
        all_errors = await get_recent_errors(since=since, limit=10000)

        # 통계 계산
        stats = {
            "total_errors": len(all_errors),
            "time_range_hours": hours,
            "by_severity": {},
            "by_error_type": {},
            "by_user": {},
            "by_symbol": {},
            "resolved_count": 0,
            "unresolved_count": 0
        }

        for error in all_errors:
            # 심각도별
            severity = error['severity']
            stats['by_severity'][severity] = stats['by_severity'].get(severity, 0) + 1

            # 에러 타입별
            error_type = error['error_type']
            stats['by_error_type'][error_type] = stats['by_error_type'].get(error_type, 0) + 1

            # 사용자별
            user_id = error.get('user_id') or error.get('telegram_id')
            if user_id:
                user_key = str(user_id)
                stats['by_user'][user_key] = stats['by_user'].get(user_key, 0) + 1

            # 심볼별
            symbol = error.get('symbol')
            if symbol:
                stats['by_symbol'][symbol] = stats['by_symbol'].get(symbol, 0) + 1

            # 해결 여부
            if error.get('resolved', False):
                stats['resolved_count'] += 1
            else:
                stats['unresolved_count'] += 1

        # 상위 10개만 반환
        stats['by_error_type'] = dict(sorted(
            stats['by_error_type'].items(),
            key=lambda x: x[1],
            reverse=True
        )[:10])

        stats['by_user'] = dict(sorted(
            stats['by_user'].items(),
            key=lambda x: x[1],
            reverse=True
        )[:10])

        stats['by_symbol'] = dict(sorted(
            stats['by_symbol'].items(),
            key=lambda x: x[1],
            reverse=True
        )[:10])

        return stats

    except Exception as e:
        logger.error(f"에러 통계 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"에러 통계 조회 실패: {str(e)}")


@router.get("/latest", response_model=ErrorLogsListResponse)
async def get_latest_errors(
    limit: int = Query(20, description="조회할 개수", ge=1, le=100)
):
    """
    최신 에러 로그 조회

    가장 최근 발생한 에러 로그를 조회합니다.
    """
    try:
        # 최근 24시간 내 에러 조회
        since = datetime.now() - timedelta(hours=24)
        errors = await get_recent_errors(since=since, limit=limit)

        # 응답 형식으로 변환
        error_responses = [
            ErrorLogResponse(
                id=error['id'],
                timestamp=error['timestamp'],
                user_id=error.get('user_id'),
                telegram_id=error.get('telegram_id'),
                error_type=error['error_type'],
                severity=error['severity'],
                error_message=error['error_message'],
                error_details=error.get('error_details'),
                module=error.get('module'),
                function_name=error.get('function_name'),
                file_path=error.get('file_path'),
                line_number=error.get('line_number'),
                traceback=error.get('traceback'),
                symbol=error.get('symbol'),
                side=error.get('side'),
                order_type=error.get('order_type'),
                position_info=error.get('position_info'),
                metadata=error.get('metadata'),
                request_id=error.get('request_id'),
                resolved=error.get('resolved', False),
                resolved_at=error.get('resolved_at'),
                resolved_by=error.get('resolved_by'),
                resolution_notes=error.get('resolution_notes')
            )
            for error in errors
        ]

        return ErrorLogsListResponse(
            total=len(error_responses),
            errors=error_responses
        )

    except Exception as e:
        logger.error(f"최신 에러 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"최신 에러 조회 실패: {str(e)}")


@router.get("/critical", response_model=ErrorLogsListResponse)
async def get_critical_errors(
    hours: int = Query(24, description="조회할 시간 범위 (시간)", ge=1, le=720),
    limit: int = Query(50, description="최대 조회 개수", ge=1, le=500)
):
    """
    심각한 에러만 조회 (CRITICAL + ERROR)

    CRITICAL 및 ERROR 레벨의 에러만 조회합니다.
    """
    try:
        since = datetime.now() - timedelta(hours=hours)

        # CRITICAL 에러 조회
        critical_errors = await get_recent_errors(
            since=since,
            severity='CRITICAL',
            limit=limit
        )

        # ERROR 에러 조회
        error_errors = await get_recent_errors(
            since=since,
            severity='ERROR',
            limit=limit
        )

        # 합치고 timestamp 기준으로 정렬
        all_errors = critical_errors + error_errors
        all_errors.sort(key=lambda x: x['timestamp'], reverse=True)
        all_errors = all_errors[:limit]

        # 응답 형식으로 변환
        error_responses = [
            ErrorLogResponse(
                id=error['id'],
                timestamp=error['timestamp'],
                user_id=error.get('user_id'),
                telegram_id=error.get('telegram_id'),
                error_type=error['error_type'],
                severity=error['severity'],
                error_message=error['error_message'],
                error_details=error.get('error_details'),
                module=error.get('module'),
                function_name=error.get('function_name'),
                file_path=error.get('file_path'),
                line_number=error.get('line_number'),
                traceback=error.get('traceback'),
                symbol=error.get('symbol'),
                side=error.get('side'),
                order_type=error.get('order_type'),
                position_info=error.get('position_info'),
                metadata=error.get('metadata'),
                request_id=error.get('request_id'),
                resolved=error.get('resolved', False),
                resolved_at=error.get('resolved_at'),
                resolved_by=error.get('resolved_by'),
                resolution_notes=error.get('resolution_notes')
            )
            for error in all_errors
        ]

        return ErrorLogsListResponse(
            total=len(error_responses),
            errors=error_responses
        )

    except Exception as e:
        logger.error(f"심각한 에러 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"심각한 에러 조회 실패: {str(e)}")
