"""
Structured JSON Logging

Provides structured logging with JSON formatting for:
- Machine-readable logs
- Log aggregation systems (ELK, Splunk, etc.)
- Request context tracking
- Sensitive data redaction
"""

import logging
import json
from datetime import datetime
from typing import Any
from shared.config import settings


class JSONFormatter(logging.Formatter):
    """
    JSON log formatter for structured logging.

    Outputs logs in JSON format with:
    - Timestamp in ISO format
    - Log level
    - Logger name
    - Message
    - Module, function, line number
    - Extra fields (user_id, request_id, etc.)
    - Exception info (if present)
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON.

        Args:
            record: Log record

        Returns:
            str: JSON-formatted log entry
        """
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add environment and service info
        if hasattr(settings, "ENVIRONMENT"):
            log_data["environment"] = settings.ENVIRONMENT

        # Add extra context fields
        extra_fields = [
            "user_id",
            "request_id",
            "session_id",
            "exchange",
            "symbol",
            "order_id",
            "strategy",
        ]

        for field in extra_fields:
            if hasattr(record, field):
                log_data[field] = getattr(record, field)

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": self.formatException(record.exc_info),
            }

        # Sanitize sensitive data (lazy import to avoid circular dependency)
        from shared.validation import sanitize_log_data
        log_data = sanitize_log_data(log_data)

        return json.dumps(log_data, ensure_ascii=False)


class RequestContextFilter(logging.Filter):
    """
    Add request context to log records.

    Usage:
        logger.addFilter(RequestContextFilter())
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Add request context fields to record.

        Args:
            record: Log record

        Returns:
            bool: Always True (don't filter out)
        """
        # These will be set by middleware/dependency injection
        if not hasattr(record, "request_id"):
            record.request_id = None
        if not hasattr(record, "user_id"):
            record.user_id = None

        return True


def setup_json_logger(
    name: str = "tradingboost",
    level: str | None = None,
) -> logging.Logger:
    """
    Set up logger with JSON formatting.

    Args:
        name: Logger name
        level: Log level (defaults to settings.LOG_LEVEL)

    Returns:
        logging.Logger: Configured logger

    Examples:
        >>> logger = setup_json_logger("my_service")
        >>> logger.info("Service started", extra={"user_id": 123})
        {"timestamp": "2025-10-05T10:00:00Z", "level": "INFO", ...}
    """
    logger = logging.getLogger(name)

    # Set log level
    log_level = level or settings.LOG_LEVEL
    logger.setLevel(getattr(logging, log_level.upper()))

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    # Create console handler
    handler = logging.StreamHandler()

    # Use JSON formatter if enabled
    formatter: logging.Formatter
    if settings.LOG_JSON:
        formatter = JSONFormatter()
    else:
        # Use traditional formatter
        formatter = logging.Formatter(
            fmt=settings.LOG_FORMAT,
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Add request context filter
    logger.addFilter(RequestContextFilter())

    # Prevent propagation to root logger
    logger.propagate = False

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Get or create logger with JSON formatting.

    Args:
        name: Logger name

    Returns:
        logging.Logger: Logger instance

    Examples:
        >>> logger = get_logger(__name__)
        >>> logger.info("Processing order", extra={"order_id": "123"})
    """
    logger = logging.getLogger(name)

    # If logger doesn't have handlers, set it up
    if not logger.handlers:
        return setup_json_logger(name)

    return logger


# ============================================================================
# Convenience Functions
# ============================================================================


def log_with_context(
    logger: logging.Logger,
    level: str,
    message: str,
    **context: Any,
) -> None:
    """
    Log message with additional context.

    Args:
        logger: Logger instance
        level: Log level (debug, info, warning, error, critical)
        message: Log message
        **context: Additional context fields

    Examples:
        >>> logger = get_logger(__name__)
        >>> log_with_context(
        ...     logger, "info", "Order placed",
        ...     user_id=123, order_id="ABC", symbol="BTC/USDT"
        ... )
    """
    log_func = getattr(logger, level.lower())
    log_func(message, extra=context)


def log_error_with_context(
    logger: logging.Logger,
    error: Exception,
    message: str | None = None,
    **context: Any,
) -> None:
    """
    Log error with exception info and context.

    Args:
        logger: Logger instance
        error: Exception object
        message: Optional custom message (defaults to exception message)
        **context: Additional context fields

    Examples:
        >>> logger = get_logger(__name__)
        >>> try:
        ...     risky_operation()
        ... except Exception as e:
        ...     log_error_with_context(
        ...         logger, e, "Operation failed",
        ...         user_id=123, operation="place_order"
        ...     )
    """
    log_message = message or str(error)
    logger.error(log_message, exc_info=True, extra=context)
