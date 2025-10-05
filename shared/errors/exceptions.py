"""
Structured Exception Handling for TradingBoost-Strategy

Provides comprehensive error categorization and handling with:
- Typed error codes for programmatic error handling
- Structured error details for debugging
- HTTP status code mapping for API responses
"""

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    """
    Comprehensive error codes for TradingBoost-Strategy platform.

    Categories:
    - VALIDATION_*: Input validation errors
    - EXCHANGE_*: Exchange API errors
    - DATABASE_*: Database operation errors
    - AUTH_*: Authentication/authorization errors
    - TRADING_*: Trading operation errors
    - SYSTEM_*: System/infrastructure errors
    """

    # Validation Errors
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_SYMBOL = "INVALID_SYMBOL"
    INVALID_AMOUNT = "INVALID_AMOUNT"
    INVALID_PRICE = "INVALID_PRICE"
    INVALID_ORDER_TYPE = "INVALID_ORDER_TYPE"

    # Exchange Errors
    EXCHANGE_ERROR = "EXCHANGE_ERROR"
    EXCHANGE_UNAVAILABLE = "EXCHANGE_UNAVAILABLE"
    EXCHANGE_TIMEOUT = "EXCHANGE_TIMEOUT"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    INVALID_API_CREDENTIALS = "INVALID_API_CREDENTIALS"
    MARKET_NOT_FOUND = "MARKET_NOT_FOUND"

    # Trading Errors
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    ORDER_FAILED = "ORDER_FAILED"
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"
    ORDER_ALREADY_FILLED = "ORDER_ALREADY_FILLED"
    ORDER_ALREADY_CANCELLED = "ORDER_ALREADY_CANCELLED"
    POSITION_NOT_FOUND = "POSITION_NOT_FOUND"
    INVALID_POSITION_SIZE = "INVALID_POSITION_SIZE"

    # Risk Management Errors
    RISK_LIMIT_EXCEEDED = "RISK_LIMIT_EXCEEDED"
    MAX_POSITION_EXCEEDED = "MAX_POSITION_EXCEEDED"
    MAX_LEVERAGE_EXCEEDED = "MAX_LEVERAGE_EXCEEDED"

    # Database Errors
    DATABASE_ERROR = "DATABASE_ERROR"
    RECORD_NOT_FOUND = "RECORD_NOT_FOUND"
    DUPLICATE_RECORD = "DUPLICATE_RECORD"
    TRANSACTION_FAILED = "TRANSACTION_FAILED"

    # Authentication/Authorization Errors
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    INVALID_TOKEN = "INVALID_TOKEN"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    USER_NOT_FOUND = "USER_NOT_FOUND"

    # System Errors
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    REDIS_ERROR = "REDIS_ERROR"
    CELERY_ERROR = "CELERY_ERROR"

    # WebSocket Errors
    WEBSOCKET_CONNECTION_FAILED = "WEBSOCKET_CONNECTION_FAILED"
    WEBSOCKET_DISCONNECTED = "WEBSOCKET_DISCONNECTED"


class TradingException(Exception):
    """
    Base exception for all TradingBoost-Strategy errors.

    Provides structured error information with:
    - Error code for programmatic handling
    - Human-readable message
    - Additional context details
    - HTTP status code for API responses
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
        status_code: int = 400,
    ):
        """
        Initialize trading exception.

        Args:
            code: Error code from ErrorCode enum
            message: Human-readable error message
            details: Additional context information
            status_code: HTTP status code for API responses
        """
        self.code = code
        self.message = message
        self.details = details or {}
        self.status_code = status_code
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert exception to dictionary for API responses.

        Returns:
            dict: Structured error information
        """
        return {
            "code": self.code.value,
            "message": self.message,
            "details": self.details,
        }


# ============================================================================
# Validation Exceptions
# ============================================================================


class ValidationException(TradingException):
    """Input validation error"""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            code=ErrorCode.VALIDATION_ERROR,
            message=message,
            details=details,
            status_code=400,
        )


class InvalidSymbolException(TradingException):
    """Invalid trading symbol"""

    def __init__(self, symbol: str):
        super().__init__(
            code=ErrorCode.INVALID_SYMBOL,
            message=f"Invalid trading symbol: {symbol}",
            details={"symbol": symbol},
            status_code=400,
        )


# ============================================================================
# Exchange Exceptions
# ============================================================================


class ExchangeException(TradingException):
    """Base exception for exchange-related errors"""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        exchange: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        details = details or {}
        if exchange:
            details["exchange"] = exchange
        super().__init__(
            code=code, message=message, details=details, status_code=500
        )


class ExchangeUnavailableException(ExchangeException):
    """Exchange service is unavailable"""

    def __init__(self, exchange: str):
        super().__init__(
            code=ErrorCode.EXCHANGE_UNAVAILABLE,
            message=f"Exchange {exchange} is currently unavailable",
            exchange=exchange,
        )


class RateLimitExceededException(ExchangeException):
    """API rate limit exceeded"""

    def __init__(self, exchange: str, retry_after: int | None = None):
        details = {}
        if retry_after:
            details["retry_after"] = retry_after
        super().__init__(
            code=ErrorCode.RATE_LIMIT_EXCEEDED,
            message=f"Rate limit exceeded for {exchange}",
            exchange=exchange,
            details=details,
        )


# ============================================================================
# Trading Exceptions
# ============================================================================


class InsufficientBalanceException(TradingException):
    """Insufficient balance for operation"""

    def __init__(self, required: float, available: float, currency: str):
        super().__init__(
            code=ErrorCode.INSUFFICIENT_BALANCE,
            message=f"Insufficient {currency} balance. Required: {required}, Available: {available}",
            details={
                "required": required,
                "available": available,
                "currency": currency,
            },
            status_code=400,
        )


class OrderFailedException(TradingException):
    """Order placement/execution failed"""

    def __init__(self, reason: str, order_id: str | None = None):
        details = {"reason": reason}
        if order_id:
            details["order_id"] = order_id
        super().__init__(
            code=ErrorCode.ORDER_FAILED,
            message=f"Order failed: {reason}",
            details=details,
            status_code=500,
        )


class OrderNotFoundException(TradingException):
    """Order not found"""

    def __init__(self, order_id: str):
        super().__init__(
            code=ErrorCode.ORDER_NOT_FOUND,
            message=f"Order not found: {order_id}",
            details={"order_id": order_id},
            status_code=404,
        )


# ============================================================================
# Risk Management Exceptions
# ============================================================================


class RiskLimitExceededException(TradingException):
    """Risk limit exceeded"""

    def __init__(self, limit_type: str, current: float, maximum: float):
        super().__init__(
            code=ErrorCode.RISK_LIMIT_EXCEEDED,
            message=f"{limit_type} limit exceeded: {current} > {maximum}",
            details={"type": limit_type, "current": current, "maximum": maximum},
            status_code=400,
        )


# ============================================================================
# Database Exceptions
# ============================================================================


class DatabaseException(TradingException):
    """Database operation error"""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            code=ErrorCode.DATABASE_ERROR,
            message=message,
            details=details,
            status_code=500,
        )


class RecordNotFoundException(TradingException):
    """Database record not found"""

    def __init__(self, model: str, identifier: Any):
        super().__init__(
            code=ErrorCode.RECORD_NOT_FOUND,
            message=f"{model} not found: {identifier}",
            details={"model": model, "identifier": str(identifier)},
            status_code=404,
        )


# ============================================================================
# Authentication Exceptions
# ============================================================================


class UnauthorizedException(TradingException):
    """Authentication required"""

    def __init__(self, message: str = "Authentication required"):
        super().__init__(
            code=ErrorCode.UNAUTHORIZED, message=message, status_code=401
        )


class ForbiddenException(TradingException):
    """Access forbidden"""

    def __init__(self, message: str = "Access forbidden"):
        super().__init__(code=ErrorCode.FORBIDDEN, message=message, status_code=403)


# ============================================================================
# System Exceptions
# ============================================================================


class ConfigurationException(TradingException):
    """Configuration error"""

    def __init__(self, message: str):
        super().__init__(
            code=ErrorCode.CONFIGURATION_ERROR,
            message=f"Configuration error: {message}",
            status_code=500,
        )


class RedisException(TradingException):
    """Redis operation error"""

    def __init__(self, operation: str, error: str):
        super().__init__(
            code=ErrorCode.REDIS_ERROR,
            message=f"Redis {operation} failed: {error}",
            details={"operation": operation, "error": error},
            status_code=500,
        )
