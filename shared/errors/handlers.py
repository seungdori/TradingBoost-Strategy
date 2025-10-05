"""
FastAPI Exception Handlers

Provides centralized error handling for FastAPI applications with:
- Structured error responses
- Request ID tracking for correlation
- Logging integration
- Development vs production error details
- Timestamp tracking
"""

from datetime import datetime
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError, OperationalError
from shared.errors.exceptions import TradingException, ErrorCode, DatabaseException
from shared.errors.middleware import get_request_id, get_error_context
from shared.config import settings
from shared.logging import get_logger

logger = get_logger(__name__)


async def trading_exception_handler(
    request: Request, exc: TradingException
) -> JSONResponse:
    """
    Handle TradingException errors with request ID tracking.

    Args:
        request: FastAPI request
        exc: TradingException instance

    Returns:
        JSONResponse: Structured error response with request ID
    """
    request_id = get_request_id()
    error_ctx = get_error_context()

    # Log error with full context
    logger.error(
        f"Trading error: {exc.code.value}",
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
        exc_info=True
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "request_id": request_id,
                "code": exc.code.value,
                "message": exc.message,
                "details": exc.details,
                "path": str(request.url),
                "timestamp": datetime.utcnow().isoformat()
            }
        },
        headers={"X-Request-ID": request_id}
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """
    Handle Pydantic validation errors with request ID tracking.

    Args:
        request: FastAPI request
        exc: RequestValidationError instance

    Returns:
        JSONResponse: Structured validation error response with request ID
    """
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

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "request_id": request_id,
                "code": ErrorCode.VALIDATION_ERROR.value,
                "message": "Request validation failed",
                "details": {"validation_errors": errors},
                "path": str(request.url),
                "timestamp": datetime.utcnow().isoformat()
            }
        },
        headers={"X-Request-ID": request_id}
    )


async def database_exception_handler(
    request: Request, exc: IntegrityError | OperationalError | DatabaseException
) -> JSONResponse:
    """
    Handle database errors (SQLAlchemy and custom DatabaseException).

    Args:
        request: FastAPI request
        exc: SQLAlchemy or DatabaseException

    Returns:
        JSONResponse: Structured database error response with request ID
    """
    request_id = get_request_id()

    logger.error(
        f"Database error: {type(exc).__name__}",
        extra={
            "request_id": request_id,
            "path": str(request.url),
            "method": request.method,
            "error": str(exc),
        },
        exc_info=True,
    )

    # Determine error code and message based on exception type
    if isinstance(exc, DatabaseException):
        code = ErrorCode.DATABASE_ERROR
        message = exc.message
        details = exc.details if settings.DEBUG else {}
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

    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "request_id": request_id,
                "code": code.value,
                "message": message,
                "details": details,
                "path": str(request.url),
                "timestamp": datetime.utcnow().isoformat()
            }
        },
        headers={"X-Request-ID": request_id}
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handle all uncaught exceptions with request ID tracking.

    Args:
        request: FastAPI request
        exc: Any exception

    Returns:
        JSONResponse: Structured error response with request ID
    """
    request_id = get_request_id()

    logger.exception(
        f"Unhandled exception: {type(exc).__name__}",
        extra={
            "request_id": request_id,
            "path": str(request.url),
            "method": request.method,
        },
    )

    # In production, don't expose internal error details
    message = "An internal error occurred"
    details = {}

    if settings.DEBUG:
        message = str(exc)
        details["exception_type"] = type(exc).__name__

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "request_id": request_id,
                "code": ErrorCode.INTERNAL_ERROR.value,
                "message": message,
                "details": details,
                "path": str(request.url),
                "timestamp": datetime.utcnow().isoformat()
            }
        },
        headers={"X-Request-ID": request_id}
    )


def register_exception_handlers(app):
    """
    Register all exception handlers with FastAPI app.

    Registers handlers in order of specificity (most specific first):
    1. TradingException - Custom trading errors
    2. DatabaseException - Custom database errors
    3. RequestValidationError - Pydantic validation
    4. IntegrityError/OperationalError - SQLAlchemy errors
    5. Exception - Generic catch-all

    Usage:
        from fastapi import FastAPI
        from shared.errors.handlers import register_exception_handlers

        app = FastAPI()
        register_exception_handlers(app)

    Args:
        app: FastAPI application instance
    """
    # Register in order of specificity
    app.add_exception_handler(TradingException, trading_exception_handler)
    app.add_exception_handler(DatabaseException, database_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(IntegrityError, database_exception_handler)
    app.add_exception_handler(OperationalError, database_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    logger.info("Exception handlers registered successfully")
