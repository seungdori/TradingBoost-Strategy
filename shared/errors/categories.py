"""에러 카테고리 및 심각도 정의

공통으로 사용되는 에러 분류 체계
"""
from enum import Enum
from typing import Dict


class ErrorSeverity(str, Enum):
    """에러 심각도 수준"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ErrorCategory(str, Enum):
    """에러 카테고리 분류"""
    # 연결 관련
    REDIS_CONNECTION = "redis_connection"
    DATABASE_CONNECTION = "database_connection"
    API_CONNECTION = "api_connection"

    # 트레이딩 관련
    TRADING_INIT = "trading_init"
    ORDER_EXECUTION = "order_execution"
    POSITION_MANAGEMENT = "position_management"
    INSUFFICIENT_BALANCE = "insufficient_balance"

    # 시스템 관련
    CELERY_TASK = "celery_task"
    SYSTEM_STATE = "system_state"
    MASS_OPERATION = "mass_operation"

    # 기타
    VALIDATION_ERROR = "validation_error"
    CONFIGURATION_ERROR = "configuration_error"
    UNKNOWN = "unknown"


# 에러 카테고리별 기본 심각도 매핑
ERROR_SEVERITY_MAP: Dict[ErrorCategory, ErrorSeverity] = {
    ErrorCategory.REDIS_CONNECTION: ErrorSeverity.CRITICAL,
    ErrorCategory.DATABASE_CONNECTION: ErrorSeverity.CRITICAL,
    ErrorCategory.API_CONNECTION: ErrorSeverity.HIGH,
    ErrorCategory.TRADING_INIT: ErrorSeverity.HIGH,
    ErrorCategory.ORDER_EXECUTION: ErrorSeverity.HIGH,
    ErrorCategory.POSITION_MANAGEMENT: ErrorSeverity.HIGH,
    ErrorCategory.INSUFFICIENT_BALANCE: ErrorSeverity.MEDIUM,
    ErrorCategory.CELERY_TASK: ErrorSeverity.HIGH,
    ErrorCategory.SYSTEM_STATE: ErrorSeverity.CRITICAL,
    ErrorCategory.MASS_OPERATION: ErrorSeverity.HIGH,
    ErrorCategory.VALIDATION_ERROR: ErrorSeverity.MEDIUM,
    ErrorCategory.CONFIGURATION_ERROR: ErrorSeverity.HIGH,
    ErrorCategory.UNKNOWN: ErrorSeverity.MEDIUM
}


def classify_error(error: Exception) -> ErrorCategory:
    """
    예외를 기반으로 에러 카테고리를 자동 분류

    Args:
        error: 발생한 예외

    Returns:
        ErrorCategory: 분류된 에러 카테고리
    """
    error_msg = str(error).lower()
    error_type = type(error).__name__.lower()

    # Redis 연결 에러
    if "redis" in error_msg or "connectionerror" in error_type:
        return ErrorCategory.REDIS_CONNECTION

    # 데이터베이스 연결 에러
    if any(keyword in error_msg for keyword in ["database", "postgresql", "sqlite", "mysql"]) or \
       any(keyword in error_type for keyword in ["psycopg", "sqlalchemy", "sqlite"]):
        return ErrorCategory.DATABASE_CONNECTION

    # API 연결 에러
    if "api" in error_msg or any(keyword in error_type for keyword in ["httpx", "requests", "aiohttp"]):
        return ErrorCategory.API_CONNECTION

    # 주문 실행 에러
    if "order" in error_msg or "execute" in error_msg:
        return ErrorCategory.ORDER_EXECUTION

    # 포지션 관리 에러
    if "position" in error_msg or "close" in error_msg:
        return ErrorCategory.POSITION_MANAGEMENT

    # 잔액 부족 에러
    if any(keyword in error_msg for keyword in ["insufficient", "balance", "minimum", "funds"]):
        return ErrorCategory.INSUFFICIENT_BALANCE

    # Celery 태스크 에러
    if "celery" in error_msg or "task" in error_msg:
        return ErrorCategory.CELERY_TASK

    # Validation 에러
    if any(keyword in error_type for keyword in ["validation", "value", "type"]) or "validation" in error_msg:
        return ErrorCategory.VALIDATION_ERROR

    # Configuration 에러
    if "config" in error_msg or "setting" in error_msg:
        return ErrorCategory.CONFIGURATION_ERROR

    return ErrorCategory.UNKNOWN
