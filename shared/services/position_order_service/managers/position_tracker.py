"""Real-Time Position Tracker

Tracks active positions via WebSocket updates and maintains
real-time state in Redis.
"""

import asyncio
import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from redis.asyncio import Redis

from shared.database.redis_schemas import RedisKeys, RedisSerializer
from shared.logging import get_logger
from shared.models.trading import Exchange, Position, PositionSide, PositionStatus
from shared.services.position_order_service.core.event_types import EventType, PositionEvent
from shared.services.position_order_service.core.pubsub_manager import PubSubManager

logger = get_logger(__name__)


class PositionTracker:
    """
    Real-time position tracking service.

    Features:
    - WebSocket event-driven updates
    - Redis state synchronization
    - P&L calculation
    - Alert generation
    """

    def __init__(
        self,
        redis_client: Redis,
        pubsub_manager: PubSubManager
    ):
        """
        Args:
            redis_client: Redis client
            pubsub_manager: PubSub manager for events
        """
        self.redis_client = redis_client
        self.pubsub_manager = pubsub_manager

        # Subscriptions
        self.active_subscriptions: Dict[str, bool] = {}

    async def start_tracking(
        self,
        user_id: str,
        exchange: str,
        symbols: List[str]
    ):
        """
        Start tracking positions for user.

        Args:
            user_id: User identifier
            exchange: Exchange identifier
            symbols: List of symbols to track
        """
        try:
            # Subscribe to position events for each symbol
            for symbol in symbols:
                await self.pubsub_manager.subscribe_to_positions(
                    user_id=user_id,
                    exchange=exchange,
                    symbol=symbol,
                    callback=self._handle_position_event
                )

                # Mark as active
                key = f"{user_id}:{exchange}:{symbol}"
                self.active_subscriptions[key] = True

            logger.info(
                f"Started position tracking",
                extra={"user_id": user_id, "exchange": exchange, "symbols": symbols}
            )

        except Exception as e:
            logger.error(
                f"Failed to start position tracking: {e}",
                exc_info=True,
                extra={"user_id": user_id, "exchange": exchange}
            )
            raise

    async def stop_tracking(
        self,
        user_id: str,
        exchange: str,
        symbol: str
    ):
        """
        Stop tracking position for symbol.

        Args:
            user_id: User identifier
            exchange: Exchange identifier
            symbol: Trading symbol
        """
        try:
            # Unsubscribe from position events
            channel = f"positions:{user_id}:{exchange}:{symbol}"
            await self.pubsub_manager.unsubscribe(channel)

            # Remove from active subscriptions
            key = f"{user_id}:{exchange}:{symbol}"
            if key in self.active_subscriptions:
                del self.active_subscriptions[key]

            logger.info(
                f"Stopped position tracking",
                extra={"user_id": user_id, "exchange": exchange, "symbol": symbol}
            )

        except Exception as e:
            logger.error(
                f"Failed to stop position tracking: {e}",
                exc_info=True,
                extra={"user_id": user_id, "exchange": exchange, "symbol": symbol}
            )

    async def _handle_position_event(self, event: PositionEvent):
        """
        Handle position update event.

        Updates Redis state and calculates P&L.

        Args:
            event: PositionEvent instance
        """
        try:
            logger.debug(
                f"Handling position event",
                extra={
                    "event_type": event.event_type,
                    "user_id": event.user_id,
                    "symbol": event.symbol
                }
            )

            # Update real-time position state in Redis
            await self._update_redis_state(event)

            # Calculate and update P&L
            if event.current_price:
                await self._calculate_pnl(event)

            # Log position update
            logger.info(
                f"Position updated: {event.symbol} {event.side}",
                extra={
                    "user_id": event.user_id,
                    "size": str(event.size),
                    "entry_price": str(event.entry_price),
                    "current_price": str(event.current_price) if event.current_price else None,
                    "unrealized_pnl": str(event.unrealized_pnl) if event.unrealized_pnl else None
                }
            )

        except Exception as e:
            logger.error(
                f"Error handling position event: {e}",
                exc_info=True,
                extra={"event": event.dict()}
            )

    async def _update_redis_state(self, event: PositionEvent):
        """
        Update position state in Redis.

        Stores in:
        - positions:realtime:{user_id}:{exchange}:{symbol}:{side}
        - positions:index:{user_id}:{exchange}

        Args:
            event: PositionEvent instance
        """
        try:
            # Build Redis key for real-time state
            redis_key = f"positions:realtime:{event.user_id}:{event.exchange}:{event.symbol}:{event.side}"

            # Prepare position data
            position_data = {
                "position_id": event.position_id,
                "user_id": event.user_id,
                "exchange": event.exchange,
                "symbol": event.symbol,
                "side": event.side,
                "size": str(event.size),
                "entry_price": str(event.entry_price),
                "current_price": str(event.current_price) if event.current_price else "",
                "unrealized_pnl": str(event.unrealized_pnl) if event.unrealized_pnl else "",
                "leverage": str(event.leverage),
                "grid_level": str(event.grid_level) if event.grid_level is not None else "",
                "last_updated": datetime.utcnow().isoformat(),
                "event_type": event.event_type.value
            }

            # Store in Redis hash
            await self.redis_client.hset(redis_key, mapping=position_data)

            # Add to index
            index_key = f"positions:index:{event.user_id}:{event.exchange}"
            await self.redis_client.sadd(index_key, event.position_id)

            # Set TTL (24 hours)
            await self.redis_client.expire(redis_key, 86400)

            logger.debug(
                f"Updated Redis position state",
                extra={"redis_key": redis_key}
            )

        except Exception as e:
            logger.error(
                f"Failed to update Redis state: {e}",
                exc_info=True,
                extra={"event": event.dict()}
            )

    async def _calculate_pnl(self, event: PositionEvent):
        """
        Calculate and update P&L for position.

        Args:
            event: PositionEvent instance
        """
        try:
            if not event.current_price or not event.entry_price:
                return

            # Calculate price difference
            price_diff = event.current_price - event.entry_price
            if event.side == 'short':
                price_diff = -price_diff

            # Calculate unrealized P&L
            unrealized_pnl = event.size * price_diff * event.leverage

            # Update Redis with calculated P&L
            redis_key = f"positions:realtime:{event.user_id}:{event.exchange}:{event.symbol}:{event.side}"
            await self.redis_client.hset(
                redis_key,
                mapping={"unrealized_pnl": str(unrealized_pnl)}
            )

            logger.debug(
                f"Calculated P&L",
                extra={
                    "position_id": event.position_id,
                    "unrealized_pnl": str(unrealized_pnl)
                }
            )

        except Exception as e:
            logger.error(
                f"Failed to calculate P&L: {e}",
                exc_info=True,
                extra={"event": event.dict()}
            )

    async def get_current_positions(
        self,
        user_id: str,
        exchange: str,
        symbol: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get current active positions from Redis.

        Args:
            user_id: User identifier
            exchange: Exchange identifier
            symbol: Optional symbol filter

        Returns:
            List of position data dictionaries
        """
        try:
            positions = []

            if symbol:
                # Get specific symbol positions
                for side in ['long', 'short']:
                    redis_key = f"positions:realtime:{user_id}:{exchange}:{symbol}:{side}"
                    data = await self.redis_client.hgetall(redis_key)

                    if data:
                        positions.append(data)
            else:
                # Get all positions for user
                index_key = f"positions:index:{user_id}:{exchange}"
                position_ids = await self.redis_client.smembers(index_key)

                for position_id in position_ids:
                    # Parse position_id to get symbol and side
                    # Format: {user_id}:{exchange}:{symbol}:{side}
                    parts = position_id.split(':')
                    if len(parts) >= 4:
                        sym = parts[2]
                        side = parts[3]

                        redis_key = f"positions:realtime:{user_id}:{exchange}:{sym}:{side}"
                        data = await self.redis_client.hgetall(redis_key)

                        if data:
                            positions.append(data)

            return positions

        except Exception as e:
            logger.error(
                f"Failed to get current positions: {e}",
                exc_info=True,
                extra={"user_id": user_id, "exchange": exchange}
            )
            return []

    async def get_position_pnl(
        self,
        user_id: str,
        exchange: str,
        symbol: str,
        side: str
    ) -> Optional[Decimal]:
        """
        Get current P&L for position.

        Args:
            user_id: User identifier
            exchange: Exchange identifier
            symbol: Trading symbol
            side: Position side ('long' or 'short')

        Returns:
            Unrealized P&L or None
        """
        try:
            redis_key = f"positions:realtime:{user_id}:{exchange}:{symbol}:{side}"
            data = await self.redis_client.hgetall(redis_key)

            if data and 'unrealized_pnl' in data:
                return Decimal(data['unrealized_pnl'])

            return None

        except Exception as e:
            logger.error(
                f"Failed to get position P&L: {e}",
                exc_info=True,
                extra={"user_id": user_id, "exchange": exchange, "symbol": symbol}
            )
            return None
