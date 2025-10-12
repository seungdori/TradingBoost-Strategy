"""
Request ID Middleware for Error Correlation

Provides request ID tracking for correlation across logs and errors.
"""

import time
import uuid
from contextvars import ContextVar
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from shared.logging import get_logger

logger = get_logger(__name__)

# Context variable for request ID (thread-safe across async contexts)
request_id_var: ContextVar[str] = ContextVar('request_id', default='')


def get_request_id() -> str:
    """
    Get current request ID from context.

    Returns:
        str: Current request ID or empty string if not set
    """
    return request_id_var.get()


def set_request_id(request_id: str) -> None:
    """
    Set request ID in context.

    Args:
        request_id: Request ID to set
    """
    request_id_var.set(request_id)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add request ID to all requests.

    Features:
    - Generates unique request ID per request
    - Adds to response headers (X-Request-ID)
    - Makes available via context variable
    - Logs request/response with ID and timing
    - Supports client-provided request IDs

    Usage in FastAPI:
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable
    ) -> Response:
        """
        Process request and add request ID.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler in chain

        Returns:
            Response: HTTP response with request ID header
        """
        # Generate or extract request ID
        # Prioritize client-provided ID, then generate new one
        request_id = request.headers.get('X-Request-ID', str(uuid.uuid4()))
        set_request_id(request_id)

        # Add to request state for easy access
        request.state.request_id = request_id

        # Track timing
        start_time = time.time()

        # Extract client info
        client_host = request.client.host if request.client else None
        method = request.method
        path = str(request.url.path)
        query_params = str(request.url.query) if request.url.query else None

        # Log request start
        logger.info(
            "Request started",
            extra={
                "request_id": request_id,
                "method": method,
                "path": path,
                "query": query_params,
                "client": client_host,
                "user_agent": request.headers.get("user-agent"),
            }
        )

        try:
            # Process request
            response: Response = await call_next(request)

            # Calculate duration
            duration = time.time() - start_time

            # Add request ID to response headers
            response.headers['X-Request-ID'] = request_id

            # Log response
            logger.info(
                "Request completed",
                extra={
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "status_code": response.status_code,
                    "duration_ms": round(duration * 1000, 2),
                }
            )

            return response

        except Exception as e:
            # Calculate duration even on error
            duration = time.time() - start_time

            # Log error
            logger.error(
                "Request failed",
                extra={
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "duration_ms": round(duration * 1000, 2),
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
                exc_info=True
            )

            # Re-raise to be handled by exception handlers
            raise


from contextlib import contextmanager

# Context manager for error enrichment
from contextvars import ContextVar as CV
from typing import Any

error_context_var: CV[dict[str, Any]] = CV('error_context', default={})


@contextmanager
def error_context(**kwargs):
    """
    Add context to errors within this block.

    Any errors raised within the context manager will have
    this additional context attached for debugging.

    Usage:
        with error_context(user_id=123, symbol="BTC-USDT"):
            await place_order(order_data)
            # Any error will include user_id and symbol in logs

    Args:
        **kwargs: Context key-value pairs to attach to errors
    """
    # Get current context and merge with new context
    current_context = error_context_var.get().copy()
    current_context.update(kwargs)

    token = error_context_var.set(current_context)
    try:
        yield
    finally:
        error_context_var.reset(token)


def get_error_context() -> dict[str, Any]:
    """
    Get current error context.

    Returns:
        dict: Current error context key-value pairs
    """
    return error_context_var.get()


def clear_error_context() -> None:
    """Clear error context"""
    error_context_var.set({})
