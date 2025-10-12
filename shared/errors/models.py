"""에러 정보 모델

에러 관련 데이터 모델 정의
"""
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from shared.errors.categories import ErrorCategory, ErrorSeverity


class ErrorInfo(BaseModel):
    """에러 정보 (GRID의 BotStateError 호환)"""
    name: str = Field(..., description="에러 이름")
    message: str = Field(..., description="에러 메시지")
    meta: Optional[Dict[str, Any]] = Field(None, description="추가 메타데이터")

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "ConnectionError",
                "message": "Failed to connect to Redis",
                "meta": {"error_detail": "Connection timeout after 30s"}
            }
        }
    }


class ErrorContext(BaseModel):
    """에러 컨텍스트 정보 (HYPERRSI의 handle_critical_error 컨텍스트 호환)"""
    category: ErrorCategory = Field(..., description="에러 카테고리")
    severity: ErrorSeverity = Field(..., description="에러 심각도")
    error_type: str = Field(..., description="에러 타입")
    error_message: str = Field(..., description="에러 메시지")
    user_id: Optional[str] = Field(None, description="사용자 ID")
    function_name: Optional[str] = Field(None, description="에러 발생 함수")
    additional_info: Optional[Dict[str, Any]] = Field(None, description="추가 정보")
    stack_trace: Optional[str] = Field(None, description="스택 트레이스")

    model_config = {
        "json_schema_extra": {
            "example": {
                "category": "order_execution",
                "severity": "high",
                "error_type": "OrderExecutionError",
                "error_message": "Failed to execute order",
                "user_id": "123456",
                "function_name": "place_order",
                "additional_info": {"symbol": "BTC-USDT", "side": "buy"},
                "stack_trace": "Traceback..."
            }
        }
    }


class ErrorResponse(BaseModel):
    """에러 응답 (API 응답용)"""
    success: bool = Field(False, description="성공 여부")
    error: ErrorInfo = Field(..., description="에러 정보")
    timestamp: Optional[str] = Field(None, description="에러 발생 시각")

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": False,
                "error": {
                    "name": "ValidationError",
                    "message": "Invalid input parameters",
                    "meta": {"field": "symbol", "issue": "required field missing"}
                },
                "timestamp": "2025-10-05T10:30:00Z"
            }
        }
    }
