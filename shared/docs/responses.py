"""Helper utilities for reusable OpenAPI response examples."""

from __future__ import annotations

from typing import Any, Dict

STATUS_ERROR_CODE_MAP: Dict[int, str] = {
    400: "VALIDATION_ERROR",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "RECORD_NOT_FOUND",
    409: "DUPLICATE_RECORD",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMIT_EXCEEDED",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


def error_code_for_status(status_code: int) -> str:
    """Return default error code string for HTTP status."""

    return STATUS_ERROR_CODE_MAP.get(status_code, "INTERNAL_ERROR")

EXAMPLE_REQUEST_ID = "req-1234567890abcdef"
EXAMPLE_TIMESTAMP = "2025-01-12T15:30:00Z"


def error_example(
    *,
    message: str,
    path: str,
    method: str,
    error_code: str | None = None,
    status_code: int | None = None,
    details: Dict[str, Any] | None = None,
    extra_meta: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Return a standardised ResponseDto error example."""

    resolved_error_code = error_code
    if resolved_error_code is None and status_code is not None:
        resolved_error_code = error_code_for_status(status_code)

    if resolved_error_code is None:
        resolved_error_code = "INTERNAL_ERROR"

    meta: Dict[str, Any] = {
        "error_code": resolved_error_code,
        "request_id": EXAMPLE_REQUEST_ID,
        "path": path,
        "method": method,
        "timestamp": EXAMPLE_TIMESTAMP,
    }

    if details:
        meta["details"] = details

    if extra_meta:
        meta.update(extra_meta)

    return {
        "success": False,
        "message": message,
        "meta": meta,
        "data": None,
    }


def error_content(
    *,
    message: str,
    path: str,
    method: str,
    status_code: int,
    error_code: str | None = None,
    details: Dict[str, Any] | None = None,
    extra_meta: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Return a FastAPI response content block for a standardized error example."""

    return {
        "application/json": {
            "example": error_example(
                message=message,
                path=path,
                method=method,
                error_code=error_code,
                status_code=status_code,
                details=details,
                extra_meta=extra_meta,
            )
        }
    }
