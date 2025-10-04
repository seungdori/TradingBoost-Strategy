"""공통 에러 처리 모듈

GRID와 HYPERRSI 프로젝트에서 공통으로 사용하는 에러 카테고리, 심각도, 핸들러
"""
from shared.errors.categories import ErrorCategory, ErrorSeverity, ERROR_SEVERITY_MAP, classify_error
from shared.errors.models import ErrorInfo, ErrorContext, ErrorResponse

__all__ = [
    'ErrorCategory',
    'ErrorSeverity',
    'ERROR_SEVERITY_MAP',
    'ErrorInfo',
    'ErrorContext',
    'ErrorResponse',
    'classify_error',
]
