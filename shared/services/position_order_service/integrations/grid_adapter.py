"""GRID Strategy Integration Adapter

Integrates GRID strategy logic with the microservice.
Preserves GRID-specific functionality including grid level management.

Uses dynamic imports to avoid circular dependencies.
"""

import asyncio
import importlib
from decimal import Decimal
from typing import Any, Dict, Optional

import ccxt.async_support as ccxt
from redis.asyncio import Redis

from shared.logging import get_logger

logger = get_logger(__name__)


def _get_grid_redis_database():
    """Dynamically import GRID redis_database to avoid circular dependency"""
    try:
        module = importlib.import_module("GRID.database.redis_database")
        return module
    except ImportError as e:
        logger.error(f"Failed to import GRID redis_database: {e}")
        return None


def _get_grid_strategy():
    """Dynamically import GRID strategy to avoid circular dependency"""
    try:
        module = importlib.import_module("GRID.strategies.strategy")
        return module
    except ImportError as e:
        logger.error(f"Failed to import GRID strategy: {e}")
        return None


class GRIDAdapter:
    """
    Adapter for GRID strategy integration.

    Provides:
    - Grid level management (0-20 levels)
    - Grid position tracking
    - Exchange-specific handling (OKX, Upbit, etc.)
    """

    def __init__(self, redis_client: Redis):
        """
        Args:
            redis_client: Redis client instance
        """
        self.redis_client = redis_client

    async def initialize_grid_position(
        self,
        user_id: int,
        exchange: str,
        symbol: str,
        level: int,
        price: float,
        qty: float,
        order_id: str
    ) -> bool:
        """
        Initialize grid position at specific level.

        Args:
            user_id: User identifier
            exchange: Exchange name
            symbol: Trading symbol
            level: Grid level (0-20)
            price: Entry price
            qty: Position quantity
            order_id: Order ID

        Returns:
            True if successful
        """
        try:
            # Dynamically import to avoid circular dependencies
            redis_db = _get_grid_redis_database()

            if not redis_db:
                logger.error("Failed to import GRID redis_database")
                return False

            await redis_db.initialize_active_grid(
                user_id=user_id,
                exchange=exchange,
                symbol=symbol,
                level=level,
                price=price,
                qty=qty,
                order_id=order_id
            )

            logger.info(
                f"Grid position initialized: level {level}",
                extra={
                    "user_id": user_id,
                    "symbol": symbol,
                    "level": level,
                    "price": price
                }
            )

            return True

        except Exception as e:
            logger.error(
                f"Failed to initialize grid position: {e}",
                exc_info=True,
                extra={"user_id": user_id, "symbol": symbol, "level": level}
            )
            return False

    async def get_grid_position(
        self,
        user_id: int,
        exchange: str,
        symbol: str,
        level: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get grid position data at specific level.

        Args:
            user_id: User identifier
            exchange: Exchange name
            symbol: Trading symbol
            level: Grid level

        Returns:
            Grid position data or None
        """
        try:
            # Dynamically import to avoid circular dependencies
            redis_db = _get_grid_redis_database()

            if not redis_db:
                logger.error("Failed to import GRID redis_database")
                return None

            grid_data = await redis_db.get_active_grid(
                user_id=user_id,
                exchange=exchange,
                symbol=symbol,
                level=level
            )

            return grid_data

        except Exception as e:
            logger.error(
                f"Failed to get grid position: {e}",
                exc_info=True,
                extra={"user_id": user_id, "symbol": symbol, "level": level}
            )
            return None

    async def update_grid_position(
        self,
        user_id: int,
        exchange: str,
        symbol: str,
        level: int,
        updates: Dict[str, Any]
    ) -> bool:
        """
        Update grid position data.

        Args:
            user_id: User identifier
            exchange: Exchange name
            symbol: Trading symbol
            level: Grid level
            updates: Dictionary of fields to update

        Returns:
            True if successful
        """
        try:
            # Dynamically import to avoid circular dependencies
            redis_db = _get_grid_redis_database()

            if not redis_db:
                logger.error("Failed to import GRID redis_database")
                return False

            # Extract update fields
            price = updates.get('price')
            qty = updates.get('qty')
            order_id = updates.get('order_id')
            direction = updates.get('direction')

            await redis_db.update_active_grid(
                user_id=user_id,
                exchange=exchange,
                symbol=symbol,
                level=level,
                price=price,
                qty=qty,
                order_id=order_id,
                direction=direction
            )

            logger.info(
                f"Grid position updated: level {level}",
                extra={
                    "user_id": user_id,
                    "symbol": symbol,
                    "level": level,
                    "updates": updates
                }
            )

            return True

        except Exception as e:
            logger.error(
                f"Failed to update grid position: {e}",
                exc_info=True,
                extra={"user_id": user_id, "symbol": symbol, "level": level}
            )
            return False

    async def close_grid_position(
        self,
        user_id: int,
        exchange: str,
        symbol: str,
        level: int,
        qty: Optional[float] = None
    ) -> bool:
        """
        Close grid position at specific level.

        Uses GRID's close_position logic with exchange-specific handling.

        Args:
            user_id: User identifier
            exchange: Exchange name
            symbol: Trading symbol
            level: Grid level
            qty: Optional partial close quantity

        Returns:
            True if successful
        """
        try:
            # Get grid position data
            grid_data = await self.get_grid_position(
                user_id=user_id,
                exchange=exchange,
                symbol=symbol,
                level=level
            )

            if not grid_data:
                logger.warning(f"Grid position not found: level {level}")
                return False

            # Dynamically import GRID's close_position function
            grid_strategy = _get_grid_strategy()

            if not grid_strategy:
                logger.error("Failed to import GRID strategy")
                return False

            # Execute close order (uses exchange-specific logic)
            order = await grid_strategy.close_position(
                symbol=symbol,
                exchange=exchange,
                user_id=user_id,
                qty=qty or float(grid_data.get('qty', 0)),
                action='close_long',  # or 'close_short' based on direction
                order_id=grid_data.get('order_id')
            )

            if order:
                logger.info(
                    f"Grid position closed: level {level}",
                    extra={
                        "user_id": user_id,
                        "symbol": symbol,
                        "level": level
                    }
                )
                return True

            return False

        except Exception as e:
            logger.error(
                f"Failed to close grid position: {e}",
                exc_info=True,
                extra={"user_id": user_id, "symbol": symbol, "level": level}
            )
            return False

    async def get_all_grid_positions(
        self,
        user_id: int,
        exchange: str,
        symbol: str
    ) -> Dict[int, Dict[str, Any]]:
        """
        Get all grid positions for symbol (all levels).

        Args:
            user_id: User identifier
            exchange: Exchange name
            symbol: Trading symbol

        Returns:
            Dictionary of {level: grid_data}
        """
        try:
            grid_positions = {}

            # Check all possible grid levels (0-20)
            for level in range(21):
                grid_data = await self.get_grid_position(
                    user_id=user_id,
                    exchange=exchange,
                    symbol=symbol,
                    level=level
                )

                if grid_data:
                    grid_positions[level] = grid_data

            return grid_positions

        except Exception as e:
            logger.error(
                f"Failed to get all grid positions: {e}",
                exc_info=True,
                extra={"user_id": user_id, "symbol": symbol}
            )
            return {}

    async def update_take_profit_orders(
        self,
        user_id: int,
        exchange: str,
        symbol: str,
        level: int,
        tp_orders: Dict[str, Any]
    ) -> bool:
        """
        Update take profit orders for grid level.

        Args:
            user_id: User identifier
            exchange: Exchange name
            symbol: Trading symbol
            level: Grid level
            tp_orders: Take profit order data

        Returns:
            True if successful
        """
        try:
            await update_take_profit_orders_info(
                user_id=user_id,
                exchange=exchange,
                symbol=symbol,
                level=level,
                **tp_orders
            )

            logger.info(
                f"Take profit orders updated: level {level}",
                extra={
                    "user_id": user_id,
                    "symbol": symbol,
                    "level": level
                }
            )

            return True

        except Exception as e:
            logger.error(
                f"Failed to update take profit orders: {e}",
                exc_info=True,
                extra={"user_id": user_id, "symbol": symbol, "level": level}
            )
            return False
