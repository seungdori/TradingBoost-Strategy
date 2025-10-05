"""
Error handling module for TradingBoost-Strategy

Exports:
    - Exception classes (new structured exceptions)
    - Error codes
    - Exception handlers
    - Legacy error models (for backward compatibility)
"""

# New structured exception system
from shared.errors.exceptions import (
    # Base exceptions
    TradingException,
    ErrorCode,
    # Validation exceptions
    ValidationException,
    InvalidSymbolException,
    # Exchange exceptions
    ExchangeException,
    ExchangeUnavailableException,
    RateLimitExceededException,
    # Trading exceptions
    InsufficientBalanceException,
    OrderFailedException,
    OrderNotFoundException,
    # Risk management exceptions
    RiskLimitExceededException,
    # Database exceptions
    DatabaseException,
    RecordNotFoundException,
    # Authentication exceptions
    UnauthorizedException,
    ForbiddenException,
    # System exceptions
    ConfigurationException,
    RedisException,
)

from shared.errors.handlers import (
    trading_exception_handler,
    validation_exception_handler,
    database_exception_handler,
    generic_exception_handler,
    register_exception_handlers,
)

# Legacy error system (for backward compatibility)
from shared.errors.categories import ErrorCategory, ErrorSeverity, ERROR_SEVERITY_MAP, classify_error
from shared.errors.models import ErrorInfo, ErrorContext, ErrorResponse

__all__ = [
    # New exception system
    "TradingException",
    "ErrorCode",
    "ValidationException",
    "InvalidSymbolException",
    "ExchangeException",
    "ExchangeUnavailableException",
    "RateLimitExceededException",
    "InsufficientBalanceException",
    "OrderFailedException",
    "OrderNotFoundException",
    "RiskLimitExceededException",
    "DatabaseException",
    "RecordNotFoundException",
    "UnauthorizedException",
    "ForbiddenException",
    "ConfigurationException",
    "RedisException",
    # Handlers
    "trading_exception_handler",
    "validation_exception_handler",
    "database_exception_handler",
    "generic_exception_handler",
    "register_exception_handlers",
    # Legacy system (backward compatibility)
    'ErrorCategory',
    'ErrorSeverity',
    'ERROR_SEVERITY_MAP',
    'ErrorInfo',
    'ErrorContext',
    'ErrorResponse',
    'classify_error',
]
