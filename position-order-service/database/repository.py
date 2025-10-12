"""Data Repository Layer

Provides high-level interface for database operations.
"""

import json
from datetime import datetime
from typing import List, Optional, Dict, Any
from decimal import Decimal

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from shared.logging import get_logger
from .models import PositionHistory, OrderHistory, TrailingStopHistory
from .connection import get_db_manager

logger = get_logger(__name__)


class PositionRepository:
    """Repository for position data"""

    @staticmethod
    async def create(
        user_id: str,
        exchange: str,
        symbol: str,
        position_id: str,
        side: str,
        size: Decimal,
        entry_price: Decimal,
        **kwargs
    ) -> Optional[PositionHistory]:
        """
        Create new position record.

        Args:
            user_id: User identifier
            exchange: Exchange name
            symbol: Trading symbol
            position_id: Unique position ID
            side: Position side (long/short)
            size: Position size
            entry_price: Entry price
            **kwargs: Additional fields (leverage, strategy_type, etc.)

        Returns:
            Created PositionHistory object or None if DB disabled
        """
        try:
            db_manager = await get_db_manager()
            if not db_manager.enabled:
                return None

            async with db_manager.get_session() as session:
                position = PositionHistory(
                    user_id=user_id,
                    exchange=exchange,
                    symbol=symbol,
                    position_id=position_id,
                    side=side,
                    size=size,
                    entry_price=entry_price,
                    status='open',
                    **kwargs
                )

                session.add(position)
                await session.flush()

                logger.info(
                    f"Position saved to database: {position_id}",
                    extra={"user_id": user_id, "symbol": symbol}
                )

                return position

        except Exception as e:
            logger.error(f"Failed to create position: {e}", exc_info=True)
            return None

    @staticmethod
    async def update_close(
        position_id: str,
        exit_price: Decimal,
        realized_pnl: Decimal,
        fee: Optional[Decimal] = None
    ) -> bool:
        """
        Update position as closed.

        Args:
            position_id: Position ID
            exit_price: Exit price
            realized_pnl: Realized P&L
            fee: Trading fee

        Returns:
            True if successful
        """
        try:
            db_manager = await get_db_manager()
            if not db_manager.enabled:
                return False

            async with db_manager.get_session() as session:
                stmt = (
                    update(PositionHistory)
                    .where(PositionHistory.position_id == position_id)
                    .values(
                        status='closed',
                        exit_price=exit_price,
                        realized_pnl=realized_pnl,
                        fee=fee,
                        closed_at=datetime.utcnow()
                    )
                )

                result = await session.execute(stmt)

                if result.rowcount > 0:
                    logger.info(f"Position closed in database: {position_id}")
                    return True
                else:
                    logger.warning(f"Position not found: {position_id}")
                    return False

        except Exception as e:
            logger.error(f"Failed to update position: {e}", exc_info=True)
            return False

    @staticmethod
    async def get_open_positions(user_id: str, exchange: str) -> List[PositionHistory]:
        """Get all open positions for user"""
        try:
            db_manager = await get_db_manager()
            if not db_manager.enabled:
                return []

            async with db_manager.get_session() as session:
                stmt = (
                    select(PositionHistory)
                    .where(
                        PositionHistory.user_id == user_id,
                        PositionHistory.exchange == exchange,
                        PositionHistory.status == 'open'
                    )
                    .order_by(PositionHistory.opened_at.desc())
                )

                result = await session.execute(stmt)
                return list(result.scalars().all())

        except Exception as e:
            logger.error(f"Failed to get open positions: {e}", exc_info=True)
            return []


class OrderRepository:
    """Repository for order data"""

    @staticmethod
    async def create(
        user_id: str,
        exchange: str,
        symbol: str,
        order_id: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Optional[Decimal] = None,
        **kwargs
    ) -> Optional[OrderHistory]:
        """Create new order record"""
        try:
            db_manager = await get_db_manager()
            if not db_manager.enabled:
                return None

            async with db_manager.get_session() as session:
                order = OrderHistory(
                    user_id=user_id,
                    exchange=exchange,
                    symbol=symbol,
                    order_id=order_id,
                    side=side,
                    order_type=order_type,
                    quantity=quantity,
                    price=price,
                    status='open',
                    **kwargs
                )

                session.add(order)
                await session.flush()

                logger.info(
                    f"Order saved to database: {order_id}",
                    extra={"user_id": user_id, "symbol": symbol}
                )

                return order

        except Exception as e:
            logger.error(f"Failed to create order: {e}", exc_info=True)
            return None

    @staticmethod
    async def update_filled(
        order_id: str,
        filled_qty: Decimal,
        average_price: Decimal,
        fee: Optional[Decimal] = None
    ) -> bool:
        """Update order as filled"""
        try:
            db_manager = await get_db_manager()
            if not db_manager.enabled:
                return False

            async with db_manager.get_session() as session:
                stmt = (
                    update(OrderHistory)
                    .where(OrderHistory.order_id == order_id)
                    .values(
                        status='filled',
                        filled_qty=filled_qty,
                        average_price=average_price,
                        fee=fee,
                        filled_at=datetime.utcnow()
                    )
                )

                result = await session.execute(stmt)

                if result.rowcount > 0:
                    logger.info(f"Order filled in database: {order_id}")
                    return True
                else:
                    logger.warning(f"Order not found: {order_id}")
                    return False

        except Exception as e:
            logger.error(f"Failed to update order: {e}", exc_info=True)
            return False

    @staticmethod
    async def update_cancelled(order_id: str) -> bool:
        """Update order as cancelled"""
        try:
            db_manager = await get_db_manager()
            if not db_manager.enabled:
                return False

            async with db_manager.get_session() as session:
                stmt = (
                    update(OrderHistory)
                    .where(OrderHistory.order_id == order_id)
                    .values(
                        status='cancelled',
                        cancelled_at=datetime.utcnow()
                    )
                )

                result = await session.execute(stmt)

                if result.rowcount > 0:
                    logger.info(f"Order cancelled in database: {order_id}")
                    return True
                else:
                    logger.warning(f"Order not found: {order_id}")
                    return False

        except Exception as e:
            logger.error(f"Failed to update order: {e}", exc_info=True)
            return False
