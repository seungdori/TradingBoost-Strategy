"""
Example Repository Pattern with New Infrastructure

Demonstrates:
- Transaction management with automatic commit/rollback
- Proper session handling
- Type-safe queries
- Error handling
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from sqlalchemy.exc import IntegrityError
from typing import List
from decimal import Decimal

from shared.database.session import transactional_session
from shared.errors import (
    DatabaseException,
    RecordNotFoundException,
    TradingException,
    ErrorCode,
)


# Example Model (adjust imports based on your actual models)
# from GRID.models.user import User
# from GRID.models.order import Order


class OrderRepository:
    """
    Example repository for Order entity.

    Demonstrates best practices for data access with new infrastructure.
    """

    def __init__(self, session: AsyncSession):
        """
        Initialize repository with database session.

        Args:
            session: SQLAlchemy async session
        """
        self.session = session

    async def get_by_id(self, order_id: str) -> dict | None:
        """
        Get order by ID.

        Args:
            order_id: Order ID

        Returns:
            Order dict or None if not found

        Example:
            >>> repo = OrderRepository(session)
            >>> order = await repo.get_by_id("order_123")
        """
        try:
            # Replace with your actual model
            query = select(Order).where(Order.id == order_id)
            result = await self.session.execute(query)
            order = result.scalar_one_or_none()

            if order is None:
                return None

            # Convert to dict (or use Pydantic model)
            return {
                "id": order.id,
                "user_id": order.user_id,
                "symbol": order.symbol,
                "side": order.side,
                "amount": float(order.amount),
                "price": float(order.price),
                "status": order.status,
                "created_at": order.created_at.isoformat(),
            }

        except Exception as e:
            raise DatabaseException(
                f"Failed to get order {order_id}",
                details={"order_id": order_id, "error": str(e)}
            )

    async def get_by_user(self, user_id: int, limit: int = 100) -> List[dict]:
        """
        Get orders by user ID.

        Args:
            user_id: User ID
            limit: Maximum number of orders to return

        Returns:
            List of order dicts

        Example:
            >>> orders = await repo.get_by_user(user_id=123, limit=50)
        """
        try:
            query = (
                select(Order)
                .where(Order.user_id == user_id)
                .order_by(Order.created_at.desc())
                .limit(limit)
            )

            result = await self.session.execute(query)
            orders = result.scalars().all()

            return [
                {
                    "id": order.id,
                    "symbol": order.symbol,
                    "side": order.side,
                    "amount": float(order.amount),
                    "price": float(order.price),
                    "status": order.status,
                    "created_at": order.created_at.isoformat(),
                }
                for order in orders
            ]

        except Exception as e:
            raise DatabaseException(
                f"Failed to get orders for user {user_id}",
                details={"user_id": user_id, "error": str(e)}
            )

    async def create(self, order_data: dict) -> dict:
        """
        Create new order.

        Args:
            order_data: Order data

        Returns:
            Created order dict

        Raises:
            DatabaseException: If creation fails
            TradingException: If validation fails

        Example:
            >>> order = await repo.create({
            ...     "user_id": 123,
            ...     "symbol": "BTC/USDT",
            ...     "side": "buy",
            ...     "amount": 0.1,
            ...     "price": 50000.0
            ... })
        """
        try:
            # Create model instance
            order = Order(
                user_id=order_data["user_id"],
                symbol=order_data["symbol"],
                side=order_data["side"],
                amount=Decimal(str(order_data["amount"])),
                price=Decimal(str(order_data["price"])),
                status="pending",
            )

            self.session.add(order)
            await self.session.flush()  # Get ID without committing

            return {
                "id": order.id,
                "user_id": order.user_id,
                "symbol": order.symbol,
                "side": order.side,
                "amount": float(order.amount),
                "price": float(order.price),
                "status": order.status,
                "created_at": order.created_at.isoformat(),
            }

        except IntegrityError as e:
            raise TradingException(
                code=ErrorCode.DUPLICATE_RECORD,
                message="Order already exists",
                details={"order_id": order_data.get("id"), "error": str(e)},
            )
        except Exception as e:
            raise DatabaseException(
                f"Failed to create order",
                details={"order_data": order_data, "error": str(e)}
            )

    async def update_status(self, order_id: str, status: str) -> dict:
        """
        Update order status.

        Args:
            order_id: Order ID
            status: New status

        Returns:
            Updated order dict

        Raises:
            RecordNotFoundException: If order not found

        Example:
            >>> order = await repo.update_status("order_123", "filled")
        """
        try:
            # Check if order exists
            order = await self.get_by_id(order_id)
            if not order:
                raise RecordNotFoundException("Order", order_id)

            # Update status
            query = (
                update(Order)
                .where(Order.id == order_id)
                .values(status=status)
            )

            await self.session.execute(query)
            await self.session.flush()

            # Return updated order
            return await self.get_by_id(order_id)

        except RecordNotFoundException:
            raise
        except Exception as e:
            raise DatabaseException(
                f"Failed to update order status",
                details={"order_id": order_id, "status": status, "error": str(e)}
            )

    async def delete(self, order_id: str) -> bool:
        """
        Delete order.

        Args:
            order_id: Order ID

        Returns:
            True if deleted

        Raises:
            RecordNotFoundException: If order not found

        Example:
            >>> deleted = await repo.delete("order_123")
        """
        try:
            # Check if order exists
            order = await self.get_by_id(order_id)
            if not order:
                raise RecordNotFoundException("Order", order_id)

            query = delete(Order).where(Order.id == order_id)
            await self.session.execute(query)
            await self.session.flush()

            return True

        except RecordNotFoundException:
            raise
        except Exception as e:
            raise DatabaseException(
                f"Failed to delete order",
                details={"order_id": order_id, "error": str(e)}
            )


# Example usage in service layer
async def example_service_usage(session: AsyncSession):
    """
    Example of using repository in service layer with transaction management.
    """
    repo = OrderRepository(session)

    # Single operation (auto-commits with get_db dependency)
    order = await repo.get_by_id("order_123")

    # Multiple operations in single transaction
    async with transactional_session(session) as tx_session:
        tx_repo = OrderRepository(tx_session)

        # Create order
        new_order = await tx_repo.create({
            "user_id": 123,
            "symbol": "BTC/USDT",
            "side": "buy",
            "amount": 0.1,
            "price": 50000.0,
        })

        # Update balance (example - would be in different repository)
        # await balance_repo.decrease(tx_session, user_id=123, amount=5000.0)

        # Send notification (example)
        # await notification_repo.create(tx_session, order_id=new_order["id"])

        # All operations commit together at end of block
        # If any operation fails, everything rolls back


# FastAPI route example
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from shared.database.session import get_db

router = APIRouter()

@router.get("/orders/{order_id}")
async def get_order(
    order_id: str,
    db: AsyncSession = Depends(get_db)
):
    repo = OrderRepository(db)
    order = await repo.get_by_id(order_id)

    if not order:
        raise RecordNotFoundException("Order", order_id)

    return order


@router.post("/orders")
async def create_order(
    order_data: dict,
    db: AsyncSession = Depends(get_db)
):
    # Session auto-commits on success, rolls back on error
    repo = OrderRepository(db)
    order = await repo.create(order_data)
    return order
"""
