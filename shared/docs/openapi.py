"""Utilities to post-process the generated OpenAPI schema."""

from __future__ import annotations

from typing import Any, Dict, Iterable

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from shared.docs.responses import error_example, error_code_for_status

STANDARD_ERROR_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["success", "message", "meta", "data"],
    "properties": {
        "success": {"type": "boolean", "example": False},
        "message": {"type": "string", "example": "Request failed"},
        "meta": {
            "type": "object",
            "description": "추가 에러 메타데이터",
            "properties": {
                "error_code": {"type": "string", "example": "VALIDATION_ERROR"},
                "request_id": {"type": "string", "example": "req-1234567890abcdef"},
                "path": {"type": "string", "example": "/auth/signup"},
                "method": {"type": "string", "example": "POST"},
                "timestamp": {"type": "string", "example": "2025-01-12T15:30:00Z"},
                "details": {"type": "object"},
                "retry_after": {"type": "integer", "example": 30},
            },
            "required": ["error_code", "path", "method", "timestamp"],
            "additionalProperties": True,
        },
        "data": {"type": "null", "default": None},
    },
}


def _first_example_value(content: Dict[str, Any]) -> Any:
    """Extract the first example value from OpenAPI response content."""

    examples = content.get("examples")
    if isinstance(examples, dict):
        for example in examples.values():
            if isinstance(example, dict) and "value" in example:
                return example["value"]

    return content.get("example")


def _derive_message_and_details(example_value: Any) -> tuple[str, Dict[str, Any] | None]:
    """Infer message and details from an arbitrary example payload."""

    default_message = "Request failed"
    if isinstance(example_value, dict):
        message = (
            example_value.get("message")
            or example_value.get("detail")
            or default_message
        )
        details = example_value.get("details")
        if not isinstance(details, dict):
            meta = example_value.get("meta")
            if isinstance(meta, dict) and isinstance(meta.get("details"), dict):
                details = meta.get("details")
            else:
                details = None
        return message, details

    if isinstance(example_value, str):
        return example_value, None

    return default_message, None


def _http_methods() -> Iterable[str]:
    return {"get", "put", "post", "delete", "patch", "options", "head"}


def attach_standard_error_examples(app: FastAPI) -> None:
    """Override the app.openapi generator to normalise error responses."""

    def custom_openapi() -> Dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema

        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )

        paths = openapi_schema.get("paths", {})
        for path, path_item in paths.items():
            for method, operation in path_item.items():
                if method not in _http_methods():
                    continue

                responses = operation.get("responses", {})
                for status_code_str, response in responses.items():
                    if not status_code_str.isdigit():
                        continue

                    status_code = int(status_code_str)
                    if status_code < 400:
                        continue

                    content = response.setdefault("content", {}).setdefault(
                        "application/json", {}
                    )

                    example_value = _first_example_value(content)
                    message, details = _derive_message_and_details(example_value)
                    error_code = error_code_for_status(status_code)

                    content["example"] = error_example(
                        message=message,
                        path=path,
                        method=method.upper(),
                        error_code=error_code,
                        details=details,
                    )

                    content.pop("examples", None)
                    content.setdefault("schema", STANDARD_ERROR_SCHEMA)

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi  # type: ignore[assignment]
