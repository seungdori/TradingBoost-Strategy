"""HYPERRSI Integration Adapter

Integrates HYPERRSI position/order management logic with the microservice.
Preserves all existing HYPERRSI functionality while enabling real-time tracking.
"""

import asyncio
from decimal import Decimal
from typing import Any, Dict, Optional

import ccxt.async_support as ccxt
from redis.asyncio import Redis

from HYPERRSI.src.trading.modules.order_manager import OrderManager as HYPERRSIOrderManager
from HYPERRSI.src.trading.modules.position_manager import PositionManager as HYPERRSIPositionManager
from shared.logging import get_logger

logger = get_logger(__name__)


class HYPERRSIAdapter:
    """
    Adapter for HYPERRSI strategy integration.

    Wraps HYPERRSI's OrderManager and PositionManager to provide:
    - Order cancellation with Algo/normal order handling
    - Position management with DCA/Hedge/TP/SL support
    - Redis settings and cooldown management
    """

    def __init__(self, redis_client: Redis):
        """
        Args:
            redis_client: Redis client instance
        """
        self.redis_client = redis_client

    async def cancel_order(
        self,
        user_id: str,
        symbol: str,
        order_id: str,
        side: Optional[str] = None,
        order_type: str = "limit"
    ) -> bool:
        """
        Cancel order using HYPERRSI OrderManager logic.

        Handles both normal and Algo orders (trigger, stop_loss, etc.).

        Args:
            user_id: User identifier
            symbol: Trading symbol
            order_id: Order ID to cancel
            side: Optional side ('buy' or 'sell')
            order_type: Order type ('limit', 'market', 'stop_loss', 'trigger')

        Returns:
            True if successful
        """
        try:
            # Create temporary HYPERRSI trading service instance
            # (In production, this would be a singleton or injected dependency)
            from HYPERRSI.src.trading.trading_service import TradingService

            trading_service = TradingService(user_id=user_id)

            # Create OrderManager instance
            order_manager = HYPERRSIOrderManager(trading_service)

            # Call HYPERRSI's _cancel_order method
            await order_manager._cancel_order(
                user_id=user_id,
                symbol=symbol,
                order_id=order_id,
                side=side,
                order_type=order_type
            )

            logger.info(
                f"Order cancelled via HYPERRSI adapter",
                extra={
                    "user_id": user_id,
                    "order_id": order_id,
                    "order_type": order_type
                }
            )

            # Cleanup
            await order_manager.cleanup()

            return True

        except Exception as e:
            logger.error(
                f"Failed to cancel order via HYPERRSI adapter: {e}",
                exc_info=True,
                extra={"user_id": user_id, "order_id": order_id}
            )
            return False

    async def open_position(
        self,
        user_id: str,
        symbol: str,
        direction: str,  # 'long' or 'short'
        size: float,
        leverage: float = 10.0,
        settings: Optional[Dict[str, Any]] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        is_DCA: bool = False,
        is_hedge: bool = False
    ) -> Optional[Any]:
        """
        Open position using HYPERRSI PositionManager logic.

        Preserves all HYPERRSI functionality:
        - Redis settings retrieval
        - Cooldown check
        - DCA mode support
        - Hedge mode support
        - TP/SL automatic creation
        - Leverage setting
        - Minimum quantity checks
        - Trade history recording
        - Telegram notifications

        Args:
            user_id: User identifier
            symbol: Trading symbol
            direction: Position direction ('long' or 'short')
            size: Position size
            leverage: Leverage (default: 10)
            settings: Optional settings dict
            stop_loss: Optional stop loss price
            take_profit: Optional take profit price
            is_DCA: DCA mode flag
            is_hedge: Hedge mode flag

        Returns:
            Position object or None
        """
        try:
            # Create temporary HYPERRSI trading service instance
            from HYPERRSI.src.trading.trading_service import TradingService

            trading_service = TradingService(user_id=user_id)

            # Create PositionManager instance
            position_manager = HYPERRSIPositionManager(trading_service)

            # Call HYPERRSI's open_position method (preserves all logic)
            position = await position_manager.open_position(
                user_id=user_id,
                symbol=symbol,
                direction=direction,
                size=size,
                leverage=leverage,
                settings=settings or {},
                stop_loss=stop_loss,
                take_profit=[take_profit] if take_profit else None,
                is_DCA=is_DCA,
                is_hedge=is_hedge
            )

            logger.info(
                f"Position opened via HYPERRSI adapter",
                extra={
                    "user_id": user_id,
                    "symbol": symbol,
                    "direction": direction,
                    "size": size
                }
            )

            return position

        except Exception as e:
            logger.error(
                f"Failed to open position via HYPERRSI adapter: {e}",
                exc_info=True,
                extra={"user_id": user_id, "symbol": symbol}
            )
            return None

    async def close_position(
        self,
        user_id: str,
        symbol: str,
        direction: str,
        size: Optional[float] = None,
        reason: str = "Manual close"
    ) -> bool:
        """
        Close position using HYPERRSI PositionManager logic.

        Handles:
        - TP/SL order cancellation
        - Full/partial position closing
        - Redis cleanup
        - Trade history updates
        - Telegram notifications

        Args:
            user_id: User identifier
            symbol: Trading symbol
            direction: Position direction
            size: Optional partial close size
            reason: Close reason

        Returns:
            True if successful
        """
        try:
            # Create temporary HYPERRSI trading service instance
            from HYPERRSI.src.trading.trading_service import TradingService

            trading_service = TradingService(user_id=user_id)

            # Create PositionManager instance
            position_manager = HYPERRSIPositionManager(trading_service)

            # Call HYPERRSI's close_position method
            result = await position_manager.close_position(
                user_id=user_id,
                symbol=symbol,
                direction=direction,
                size=size,
                reason=reason
            )

            logger.info(
                f"Position closed via HYPERRSI adapter",
                extra={
                    "user_id": user_id,
                    "symbol": symbol,
                    "direction": direction,
                    "reason": reason
                }
            )

            return result is not None

        except Exception as e:
            logger.error(
                f"Failed to close position via HYPERRSI adapter: {e}",
                exc_info=True,
                extra={"user_id": user_id, "symbol": symbol}
            )
            return False

    async def get_user_settings(self, user_id: str) -> Dict[str, Any]:
        """
        Get user settings from Redis (HYPERRSI format).

        Args:
            user_id: User identifier

        Returns:
            Settings dictionary
        """
        try:
            settings_key = f"user:{user_id}:settings"
            settings_data = await self.redis_client.hgetall(settings_key)

            return dict(settings_data) if settings_data else {}

        except Exception as e:
            logger.error(
                f"Failed to get user settings: {e}",
                exc_info=True,
                extra={"user_id": user_id}
            )
            return {}

    async def check_cooldown(
        self,
        user_id: str,
        symbol: str,
        direction: str
    ) -> bool:
        """
        Check if user is in cooldown period (HYPERRSI logic).

        Args:
            user_id: User identifier
            symbol: Trading symbol
            direction: Position direction

        Returns:
            True if in cooldown, False otherwise
        """
        try:
            cooldown_key = f"user:{user_id}:cooldown:{symbol}:{direction}"
            cooldown_value = await self.redis_client.get(cooldown_key)

            return cooldown_value is not None

        except Exception as e:
            logger.error(
                f"Failed to check cooldown: {e}",
                exc_info=True,
                extra={"user_id": user_id, "symbol": symbol}
            )
            return False
