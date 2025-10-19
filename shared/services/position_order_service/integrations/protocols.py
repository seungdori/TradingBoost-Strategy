"""Strategy Adapter Protocols

Defines interfaces that strategy adapters must implement.
This allows the position-order service to work with strategies
without direct imports, avoiding circular dependencies.
"""

from typing import Any, Dict, Optional, Protocol

from shared.models.trading import Order, Position


class StrategyOrderProtocol(Protocol):
    """Protocol for strategy order management operations"""

    async def cancel_order(
        self,
        user_id: str,
        symbol: str,
        order_id: str,
        side: Optional[str] = None,
        order_type: str = "limit"
    ) -> bool:
        """
        Cancel an order in the strategy.

        Args:
            user_id: User identifier
            symbol: Trading symbol
            order_id: Order ID to cancel
            side: Optional side ('buy' or 'sell')
            order_type: Order type ('limit', 'market', 'stop_loss', etc.)

        Returns:
            True if successful, False otherwise
        """
        ...

    async def get_order(
        self,
        user_id: str,
        symbol: str,
        order_id: str
    ) -> Optional[Order]:
        """
        Get order details from the strategy.

        Args:
            user_id: User identifier
            symbol: Trading symbol
            order_id: Order ID

        Returns:
            Order object or None if not found
        """
        ...


class StrategyPositionProtocol(Protocol):
    """Protocol for strategy position management operations"""

    async def get_position(
        self,
        user_id: str,
        symbol: str,
        side: Optional[str] = None
    ) -> Optional[Position]:
        """
        Get position details from the strategy.

        Args:
            user_id: User identifier
            symbol: Trading symbol
            side: Optional position side ('long' or 'short')

        Returns:
            Position object or None if not found
        """
        ...

    async def update_position(
        self,
        user_id: str,
        symbol: str,
        updates: Dict[str, Any]
    ) -> Optional[Position]:
        """
        Update position in the strategy.

        Args:
            user_id: User identifier
            symbol: Trading symbol
            updates: Dictionary of fields to update

        Returns:
            Updated Position object or None if failed
        """
        ...


class StrategyGridProtocol(Protocol):
    """Protocol for GRID-specific operations"""

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
        ...

    async def get_grid_position(
        self,
        user_id: int,
        exchange: str,
        symbol: str,
        level: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get grid position at specific level.

        Args:
            user_id: User identifier
            exchange: Exchange name
            symbol: Trading symbol
            level: Grid level

        Returns:
            Grid position data or None if not found
        """
        ...
