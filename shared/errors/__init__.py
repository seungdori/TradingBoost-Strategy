"""
Error handling module for TradingBoost-Strategy

Exports:
    - Exception classes (new structured exceptions)
    - Error codes
    - Exception handlers
    - Legacy error models (for backward compatibility)
"""

# Legacy error system (for backward compatibility)
from shared.errors.categories import (
    ERROR_SEVERITY_MAP,
    ErrorCategory,
    ErrorSeverity,
    classify_error,
)

# New structured exception system
from shared.errors.exceptions import (  # Base exceptions; Validation exceptions; Exchange exceptions; Trading exceptions; Risk management exceptions; Database exceptions; Authentication exceptions; System exceptions
    ConfigurationException,
    DatabaseException,
    ErrorCode,
    ExchangeException,
    ExchangeUnavailableException,
    ForbiddenException,
    InsufficientBalanceException,
    InvalidSymbolException,
    OrderFailedException,
    OrderNotFoundException,
    RateLimitExceededException,
    RecordNotFoundException,
    RedisException,
    RiskLimitExceededException,
    TradingException,
    UnauthorizedException,
    ValidationException,
)
from shared.errors.handlers import (
    database_exception_handler,
    generic_exception_handler,
    register_exception_handlers,
    trading_exception_handler,
    validation_exception_handler,
)
from shared.errors.models import ErrorContext, ErrorInfo, ErrorResponse

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
