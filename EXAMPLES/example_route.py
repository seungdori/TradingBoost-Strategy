"""
Example FastAPI Routes with New Infrastructure

Demonstrates:
- Input validation with Pydantic and sanitizers
- Dependency injection for database and services
- Structured exception handling
- Request context logging
"""

from fastapi import APIRouter, Depends, Query, Path, Body
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field, validator
from typing import List
from decimal import Decimal

from shared.database.session import get_db
from shared.errors import (
    ValidationException,
    RecordNotFoundException,
    UnauthorizedException,
)
from shared.validation import (
    sanitize_symbol,
    validate_trading_amount,
    validate_order_side,
)
from shared.logging import get_logger

# Example service import (adjust based on your structure)
# from GRID.services.trading_service import TradingService


logger = get_logger(__name__)
router = APIRouter(prefix="/api/trading", tags=["trading"])


# ============================================================================
# Pydantic Models (DTOs)
# ============================================================================


class OrderCreateRequest(BaseModel):
    """Order creation request with validation"""

    symbol: str = Field(..., description="Trading symbol (e.g., BTC/USDT)")
    side: str = Field(..., description="Order side: buy or sell")
    amount: float = Field(..., gt=0, description="Order amount")
    price: float | None = Field(None, gt=0, description="Order price (None for market order)")

    @validator("symbol")
    def validate_symbol(cls, v):
        """Sanitize and validate symbol"""
        return sanitize_symbol(v)

    @validator("side")
    def validate_side(cls, v):
        """Validate order side"""
        return validate_order_side(v)

    @validator("amount")
    def validate_amount(cls, v):
        """Validate amount"""
        validate_trading_amount(v)
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "symbol": "BTC/USDT",
                "side": "buy",
                "amount": 0.1,
                "price": 50000.0,
            }
        }


class OrderResponse(BaseModel):
    """Order response"""

    id: str
    user_id: int
    symbol: str
    side: str
    amount: float
    price: float | None
    status: str
    created_at: str


class OrderListResponse(BaseModel):
    """Order list response"""

    total: int
    orders: List[OrderResponse]


# ============================================================================
# Dependency Injection Examples
# ============================================================================


async def get_current_user_id(
    # In real app, extract from JWT token
    user_id: int = Query(..., description="User ID")
) -> int:
    """
    Get current user ID from request.

    In production, this would extract user_id from JWT token.
    """
    if not user_id or user_id <= 0:
        raise UnauthorizedException("Invalid user ID")
    return user_id


async def get_trading_service(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Create trading service instance.

    This is a factory dependency that creates a service instance
    with proper session and user context.
    """
    # return TradingService(db, user_id)
    pass  # Placeholder


# ============================================================================
# Route Handlers
# ============================================================================


@router.post("/orders", response_model=OrderResponse, status_code=201)
async def create_order(
    order_request: OrderCreateRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Create new trading order.

    Demonstrates:
    - Automatic request validation with Pydantic
    - Database session injection
    - Structured error handling (automatic via exception handlers)
    - Request logging with context

    Args:
        order_request: Order data (validated by Pydantic)
        user_id: Current user ID (from dependency)
        db: Database session (auto-commits on success)

    Returns:
        OrderResponse: Created order

    Raises:
        ValidationException: Invalid input
        InsufficientBalanceException: Not enough balance
        OrderFailedException: Order placement failed

    Example:
        ```bash
        curl -X POST "http://localhost:8000/api/trading/orders?user_id=123" \\
             -H "Content-Type: application/json" \\
             -d '{
                   "symbol": "BTC/USDT",
                   "side": "buy",
                   "amount": 0.1,
                   "price": 50000.0
                 }'
        ```
    """
    logger.info(
        "Creating order",
        extra={
            "user_id": user_id,
            "symbol": order_request.symbol,
            "side": order_request.side,
            "amount": order_request.amount,
        }
    )

    # Create service (in real app, use dependency injection)
    # service = TradingService(db, user_id)

    # Place order (exceptions are automatically handled by exception handlers)
    # order = await service.place_order(
    #     symbol=order_request.symbol,
    #     side=order_request.side,
    #     amount=order_request.amount,
    #     price=order_request.price,
    # )

    # Example response
    order = OrderResponse(
        id="order_123",
        user_id=user_id,
        symbol=order_request.symbol,
        side=order_request.side,
        amount=order_request.amount,
        price=order_request.price,
        status="pending",
        created_at="2025-10-05T10:00:00Z",
    )

    logger.info(
        "Order created successfully",
        extra={"user_id": user_id, "order_id": order.id}
    )

    return order


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: str = Path(..., description="Order ID"),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Get order by ID.

    Demonstrates:
    - Path parameter validation
    - Record not found handling
    - Authorization check

    Args:
        order_id: Order ID from URL path
        user_id: Current user ID
        db: Database session

    Returns:
        OrderResponse: Order details

    Raises:
        RecordNotFoundException: Order not found
        ForbiddenException: Not authorized to view this order

    Example:
        ```bash
        curl "http://localhost:8000/api/trading/orders/order_123?user_id=123"
        ```
    """
    logger.info(
        "Fetching order",
        extra={"user_id": user_id, "order_id": order_id}
    )

    # Get order from repository
    # order = await order_repo.get_by_id(order_id)

    # if not order:
    #     raise RecordNotFoundException("Order", order_id)

    # Check authorization
    # if order["user_id"] != user_id:
    #     raise ForbiddenException("Not authorized to view this order")

    # Example response
    return OrderResponse(
        id=order_id,
        user_id=user_id,
        symbol="BTC/USDT",
        side="buy",
        amount=0.1,
        price=50000.0,
        status="filled",
        created_at="2025-10-05T10:00:00Z",
    )


@router.get("/orders", response_model=OrderListResponse)
async def list_orders(
    user_id: int = Depends(get_current_user_id),
    status: str | None = Query(None, description="Filter by status"),
    symbol: str | None = Query(None, description="Filter by symbol"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: AsyncSession = Depends(get_db),
):
    """
    List user orders with filtering and pagination.

    Demonstrates:
    - Query parameter validation
    - Optional filters
    - Pagination

    Args:
        user_id: Current user ID
        status: Filter by status (optional)
        symbol: Filter by symbol (optional)
        limit: Maximum results
        offset: Pagination offset
        db: Database session

    Returns:
        OrderListResponse: List of orders with total count

    Example:
        ```bash
        curl "http://localhost:8000/api/trading/orders?user_id=123&status=filled&limit=50"
        ```
    """
    logger.info(
        "Listing orders",
        extra={
            "user_id": user_id,
            "status": status,
            "symbol": symbol,
            "limit": limit,
            "offset": offset,
        }
    )

    # Sanitize symbol if provided
    if symbol:
        symbol = sanitize_symbol(symbol)

    # Get orders from repository
    # orders = await order_repo.get_by_user(
    #     user_id=user_id,
    #     status=status,
    #     symbol=symbol,
    #     limit=limit,
    #     offset=offset
    # )

    # Example response
    return OrderListResponse(
        total=1,
        orders=[
            OrderResponse(
                id="order_123",
                user_id=user_id,
                symbol="BTC/USDT",
                side="buy",
                amount=0.1,
                price=50000.0,
                status="filled",
                created_at="2025-10-05T10:00:00Z",
            )
        ],
    )


@router.delete("/orders/{order_id}")
async def cancel_order(
    order_id: str = Path(..., description="Order ID"),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Cancel order.

    Demonstrates:
    - DELETE method
    - Transaction handling
    - Success response

    Args:
        order_id: Order ID to cancel
        user_id: Current user ID
        db: Database session

    Returns:
        dict: Success message

    Raises:
        RecordNotFoundException: Order not found
        OrderFailedException: Cancellation failed

    Example:
        ```bash
        curl -X DELETE "http://localhost:8000/api/trading/orders/order_123?user_id=123"
        ```
    """
    logger.info(
        "Cancelling order",
        extra={"user_id": user_id, "order_id": order_id}
    )

    # Cancel order via service
    # service = TradingService(db, user_id)
    # cancelled = await service.cancel_order(order_id)

    logger.info(
        "Order cancelled successfully",
        extra={"user_id": user_id, "order_id": order_id}
    )

    return {
        "status": "success",
        "message": "Order cancelled successfully",
        "order_id": order_id,
    }


# ============================================================================
# Health Check Endpoint
# ============================================================================


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    Health check endpoint.

    Verifies database connectivity.

    Example:
        ```bash
        curl "http://localhost:8000/api/trading/health"
        ```
    """
    try:
        # Simple query to check database
        from sqlalchemy import text
        await db.execute(text("SELECT 1"))

        return {
            "status": "healthy",
            "database": "connected",
        }
    except Exception as e:
        logger.error("Health check failed", exc_info=True)
        return {
            "status": "unhealthy",
            "database": "disconnected",
            "error": str(e),
        }
