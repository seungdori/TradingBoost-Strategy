"""Structured logging module"""

from shared.logging.json_logger import (
    JSONFormatter,
    setup_json_logger,
    get_logger,
    RequestContextFilter,
)

from shared.logging.specialized_loggers import (
    setup_order_logger,
    get_user_order_logger,
    log_order,
    setup_alert_logger,
    alert_log,
    setup_debug_logger,
    log_debug,
    log_bot_start,
    log_bot_stop,
    log_bot_error,
    order_logger,
    alert_logger,
    debug_logger,
)

__all__ = [
    # JSON Logger
    "JSONFormatter",
    "setup_json_logger",
    "get_logger",
    "RequestContextFilter",
    # Specialized Loggers
    "setup_order_logger",
    "get_user_order_logger",
    "log_order",
    "setup_alert_logger",
    "alert_log",
    "setup_debug_logger",
    "log_debug",
    "log_bot_start",
    "log_bot_stop",
    "log_bot_error",
    "order_logger",
    "alert_logger",
    "debug_logger",
]
