"""
Error Handling and Middleware Tests

Tests for:
- shared/errors/middleware.py (Request ID tracking)
- shared/errors/handlers.py (Exception handlers)
"""

import pytest
import uuid
from unittest.mock import AsyncMock, Mock
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError
from shared.errors.middleware import (
    RequestIDMiddleware,
    get_request_id,
    set_request_id,
    error_context,
    get_error_context,
)
from shared.errors import TradingException, ErrorCode, DatabaseException
from shared.errors.handlers import (
    trading_exception_handler,
    validation_exception_handler,
    database_exception_handler,
    generic_exception_handler,
)


class TestRequestIDMiddleware:
    """Test Request ID middleware"""

    def test_middleware_generates_request_id(self):
        """Test middleware generates request ID if not provided"""
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.get("/test")
        async def test_route():
            return {"request_id": get_request_id()}

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        data = response.json()
        assert "request_id" in data
        # Should be a valid UUID
        uuid.UUID(data["request_id"])

    def test_middleware_uses_client_request_id(self):
        """Test middleware uses client-provided X-Request-ID"""
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        client_request_id = str(uuid.uuid4())

        @app.get("/test")
        async def test_route():
            return {"request_id": get_request_id()}

        client = TestClient(app)
        response = client.get("/test", headers={"X-Request-ID": client_request_id})

        assert response.status_code == 200
        data = response.json()
        assert data["request_id"] == client_request_id

    def test_middleware_adds_request_id_to_response(self):
        """Test middleware adds X-Request-ID header to response"""
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.get("/test")
        async def test_route():
            return {"message": "ok"}

        client = TestClient(app)
        response = client.get("/test")

        assert "X-Request-ID" in response.headers
        # Should be a valid UUID
        uuid.UUID(response.headers["X-Request-ID"])


class TestErrorContext:
    """Test error context manager"""

    def test_error_context_sets_values(self):
        """Test error_context sets context values"""
        with error_context(user_id=123, symbol="BTC-USDT"):
            ctx = get_error_context()
            assert ctx["user_id"] == 123
            assert ctx["symbol"] == "BTC-USDT"

    def test_error_context_clears_after_exit(self):
        """Test error_context clears after exiting"""
        with error_context(user_id=123):
            pass

        ctx = get_error_context()
        assert ctx == {}

    def test_error_context_available_in_nested_calls(self):
        """Test error context is available in nested function calls"""
        def inner_function():
            ctx = get_error_context()
            return ctx.get("user_id")

        with error_context(user_id=456):
            result = inner_function()

        assert result == 456


class TestTradingExceptionHandler:
    """Test TradingException handler"""

    @pytest.mark.asyncio
    async def test_trading_exception_response_format(self):
        """Test trading exception returns correct response format"""
        app = FastAPI()

        @app.get("/test")
        async def test_route():
            raise TradingException(
                code=ErrorCode.ORDER_FAILED,
                message="Order execution failed",
                details={"symbol": "BTC-USDT", "amount": 100}
            )

        from shared.errors.handlers import register_exception_handlers
        register_exception_handlers(app)

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 500
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == ErrorCode.ORDER_FAILED.value
        assert data["error"]["message"] == "Order execution failed"
        assert "request_id" in data["error"]
        assert "timestamp" in data["error"]
        assert "X-Request-ID" in response.headers

    @pytest.mark.asyncio
    async def test_trading_exception_includes_context(self):
        """Test trading exception includes error context"""
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.get("/test")
        async def test_route():
            with error_context(user_id=123, symbol="BTC-USDT"):
                raise TradingException(
                    code=ErrorCode.ORDER_FAILED,
                    message="Order failed"
                )

        from shared.errors.handlers import register_exception_handlers
        register_exception_handlers(app)

        client = TestClient(app)
        response = client.get("/test")

        # Context should be logged but not necessarily exposed in response
        assert response.status_code == 500


class TestValidationExceptionHandler:
    """Test RequestValidationError handler"""

    def test_validation_error_response(self):
        """Test validation error returns correct format"""
        app = FastAPI()

        @app.get("/test")
        async def test_route(value: int):
            return {"value": value}

        from shared.errors.handlers import register_exception_handlers
        register_exception_handlers(app)

        client = TestClient(app)
        response = client.get("/test?value=invalid")

        assert response.status_code == 422
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == ErrorCode.VALIDATION_ERROR.value
        assert "request_id" in data["error"]
        assert "timestamp" in data["error"]


class TestDatabaseExceptionHandler:
    """Test database exception handlers"""

    def test_integrity_error_response(self):
        """Test IntegrityError returns correct response"""
        app = FastAPI()

        @app.get("/test")
        async def test_route():
            raise IntegrityError("", "", orig=Mock())

        from shared.errors.handlers import register_exception_handlers
        register_exception_handlers(app)

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 409  # Conflict
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == ErrorCode.DUPLICATE_RECORD.value

    def test_database_exception_response(self):
        """Test DatabaseException returns correct response"""
        app = FastAPI()

        @app.get("/test")
        async def test_route():
            raise DatabaseException(
                message="Database operation failed",
                details={"table": "orders"}
            )

        from shared.errors.handlers import register_exception_handlers
        register_exception_handlers(app)

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 500
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == ErrorCode.DATABASE_ERROR.value


class TestGenericExceptionHandler:
    """Test generic exception handler"""

    def test_generic_exception_response(self):
        """Test generic exception returns correct response"""
        app = FastAPI()

        @app.get("/test")
        async def test_route():
            raise ValueError("Something went wrong")

        from shared.errors.handlers import register_exception_handlers
        register_exception_handlers(app)

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 500
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == ErrorCode.INTERNAL_ERROR.value
        assert "request_id" in data["error"]


class TestErrorHandlerIntegration:
    """Integration tests for error handling system"""

    def test_full_error_flow_with_request_id(self):
        """Test complete error flow with request ID tracking"""
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        custom_request_id = str(uuid.uuid4())

        @app.get("/test")
        async def test_route():
            # Verify request ID is set
            assert get_request_id() == custom_request_id

            raise TradingException(
                code=ErrorCode.ORDER_FAILED,
                message="Test error"
            )

        from shared.errors.handlers import register_exception_handlers
        register_exception_handlers(app)

        client = TestClient(app)
        response = client.get("/test", headers={"X-Request-ID": custom_request_id})

        # Request ID should be in response
        assert response.json()["error"]["request_id"] == custom_request_id
        assert response.headers["X-Request-ID"] == custom_request_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
