"""
FastAPI Exception Handlers

Provides centralized error handling for FastAPI applications with:
- Unified ResponseDto error payloads
- Request ID tracking for correlation
- Logging integration
- Development vs production error details
- Timestamp tracking
"""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError

from shared.config import settings
from shared.dtos.response import ResponseDto
from shared.errors.exceptions import DatabaseException, ErrorCode, TradingException
from shared.errors.middleware import get_error_context, get_request_id
from shared.logging import get_logger

logger = get_logger(__name__)


def _iso_timestamp() -> str:
    """Return current UTC timestamp in ISO-8601 with trailing Z."""

    return datetime.utcnow().isoformat() + "Z"


def _build_error_meta(
    *,
    request: Request,
    request_id: str | None,
    error_code: str,
    details: dict | None = None,
    extra_meta: dict | None = None,
) -> dict:
    """Create a standard meta payload for error responses."""

    meta: dict[str, object] = {
        "error_code": error_code,
        "path": str(request.url),
        "method": request.method,
        "timestamp": _iso_timestamp(),
    }

    if request_id:
        meta["request_id"] = request_id

    if details:
        meta["details"] = details

    if extra_meta:
        meta.update(extra_meta)

    return meta


def _error_response(
    *,
    status_code: int,
    message: str,
    request: Request,
    error_code: str,
    request_id: str | None,
    details: dict | None = None,
    extra_meta: dict | None = None,
) -> JSONResponse:
    """Return a JSONResponse using the unified ResponseDto format."""

    meta = _build_error_meta(
        request=request,
        request_id=request_id,
        error_code=error_code,
        details=details,
        extra_meta=extra_meta,
    )

    dto = ResponseDto[None](
        success=False,
        message=message,
        meta=meta,
        data=None,
    )

    headers = {"X-Request-ID": request_id} if request_id else None

    return JSONResponse(
        status_code=status_code,
        content=dto.model_dump(),
        headers=headers,
    )


async def trading_exception_handler(
    request: Request, exc: TradingException
) -> JSONResponse:
    """Handle TradingException errors with request ID tracking."""

    request_id = get_request_id()
    error_ctx = get_error_context()

    logger.error(
        "Trading error",
        extra={
            "request_id": request_id,
            "error_code": exc.code.value,
            "message": exc.message,
            "details": exc.details,
            "error_context": error_ctx,
            "path": str(request.url),
            "method": request.method,
            "user_agent": request.headers.get("user-agent"),
        },
        exc_info=True,
    )

    return _error_response(
        status_code=exc.status_code,
        message=exc.message,
        request=request,
        error_code=exc.code.value,
        request_id=request_id,
        details=exc.details,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle Pydantic validation errors with request ID tracking."""

    request_id = get_request_id()
    errors = exc.errors()

    logger.warning(
        "Validation error",
        extra={
            "request_id": request_id,
            "path": str(request.url),
            "method": request.method,
            "errors": errors,
        },
    )

    return _error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        message="Request validation failed",
        request=request,
        error_code=ErrorCode.VALIDATION_ERROR.value,
        request_id=request_id,
        details={"validation_errors": errors},
    )


async def database_exception_handler(
    request: Request, exc: IntegrityError | OperationalError | DatabaseException
) -> JSONResponse:
    """Handle database errors (SQLAlchemy and custom DatabaseException)."""

    request_id = get_request_id()

    logger.error(
        "Database error",
        extra={
            "request_id": request_id,
            "path": str(request.url),
            "method": request.method,
            "error": str(exc),
        },
        exc_info=True,
    )

    if isinstance(exc, DatabaseException):
        code = ErrorCode.DATABASE_ERROR
        message = exc.message
        details = exc.details if settings.DEBUG else exc.details or {}
        status_code = exc.status_code
    elif isinstance(exc, IntegrityError):
        code = ErrorCode.DUPLICATE_RECORD
        message = "Database integrity constraint violated"
        status_code = status.HTTP_409_CONFLICT
        details = {"error": str(exc)} if settings.DEBUG else {}
    else:
        code = ErrorCode.DATABASE_ERROR
        message = "Database operation failed"
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        details = {"error": str(exc)} if settings.DEBUG else {}

    return _error_response(
        status_code=status_code,
        message=message,
        request=request,
        error_code=code.value,
        request_id=request_id,
        details=details or None,
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle all uncaught exceptions with request ID tracking."""

    request_id = get_request_id()

    logger.exception(
        "Unhandled exception",
        extra={
            "request_id": request_id,
            "path": str(request.url),
            "method": request.method,
        },
    )

    message = "An internal error occurred"
    details: dict[str, object] | None = None

    if settings.DEBUG:
        message = str(exc)
        details = {"exception_type": type(exc).__name__}

    return _error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        message=message,
        request=request,
        error_code=ErrorCode.INTERNAL_ERROR.value,
        request_id=request_id,
        details=details,
    )


HTTP_STATUS_CODE_TO_ERROR_CODE: dict[int, ErrorCode] = {
    status.HTTP_400_BAD_REQUEST: ErrorCode.VALIDATION_ERROR,
    status.HTTP_401_UNAUTHORIZED: ErrorCode.UNAUTHORIZED,
    status.HTTP_403_FORBIDDEN: ErrorCode.FORBIDDEN,
    status.HTTP_404_NOT_FOUND: ErrorCode.RECORD_NOT_FOUND,
    status.HTTP_409_CONFLICT: ErrorCode.DUPLICATE_RECORD,
    status.HTTP_422_UNPROCESSABLE_ENTITY: ErrorCode.VALIDATION_ERROR,
    status.HTTP_429_TOO_MANY_REQUESTS: ErrorCode.RATE_LIMIT_EXCEEDED,
    status.HTTP_500_INTERNAL_SERVER_ERROR: ErrorCode.INTERNAL_ERROR,
    status.HTTP_503_SERVICE_UNAVAILABLE: ErrorCode.SERVICE_UNAVAILABLE,
}


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Normalize FastAPI HTTPException responses to the standard ResponseDto payload."""

    request_id = get_request_id()

    if isinstance(exc.detail, str):
        message = exc.detail
        details = None
    elif isinstance(exc.detail, dict):
        message = (
            exc.detail.get("message")
            or exc.detail.get("detail")
            or "Request failed"
        )
        details = exc.detail
    else:
        message = str(exc.detail)
        details = {"detail": exc.detail}

    error_code = HTTP_STATUS_CODE_TO_ERROR_CODE.get(
        exc.status_code, ErrorCode.INTERNAL_ERROR
    )

    extra_meta = None
    if exc.headers and "Retry-After" in exc.headers:
        extra_meta = {"retry_after": exc.headers["Retry-After"]}

    return _error_response(
        status_code=exc.status_code,
        message=message or "Request failed",
        request=request,
        error_code=error_code.value,
        request_id=request_id,
        details=details if isinstance(details, dict) else None,
        extra_meta=extra_meta,
    )


def register_exception_handlers(app):
    """Register all exception handlers with FastAPI app."""

    app.add_exception_handler(TradingException, trading_exception_handler)
    app.add_exception_handler(DatabaseException, database_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(IntegrityError, database_exception_handler)
    app.add_exception_handler(OperationalError, database_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    logger.info("Exception handlers registered successfully")
