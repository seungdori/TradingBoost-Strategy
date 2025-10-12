"""Real-Time Order Tracker

Tracks active orders via WebSocket updates and maintains
real-time state in Redis.
"""

import asyncio
import json
from typing import Optional, Dict, Any, List
from datetime import datetime
from decimal import Decimal

from redis.asyncio import Redis

from shared.logging import get_logger
from shared.models.trading import Order, OrderStatus, OrderSide, Exchange

from core.event_types import OrderEvent, EventType
from core.pubsub_manager import PubSubManager

logger = get_logger(__name__)


class OrderTracker:
    """
    Real-time order tracking service.

    Features:
    - WebSocket event-driven updates
    - Redis state synchronization
    - Order status monitoring
    - Fill notifications
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

        # Callbacks for order events (for conditional cancellation, etc.)
        self.order_callbacks: List[callable] = []

    async def start_tracking(
        self,
        user_id: str,
        exchange: str
    ):
        """
        Start tracking orders for user.

        Args:
            user_id: User identifier
            exchange: Exchange identifier
        """
        try:
            # Subscribe to order events
            await self.pubsub_manager.subscribe_to_orders(
                user_id=user_id,
                exchange=exchange,
                callback=self._handle_order_event
            )

            # Mark as active
            key = f"{user_id}:{exchange}"
            self.active_subscriptions[key] = True

            logger.info(
                f"Started order tracking",
                extra={"user_id": user_id, "exchange": exchange}
            )

        except Exception as e:
            logger.error(
                f"Failed to start order tracking: {e}",
                exc_info=True,
                extra={"user_id": user_id, "exchange": exchange}
            )
            raise

    async def stop_tracking(
        self,
        user_id: str,
        exchange: str
    ):
        """
        Stop tracking orders for user.

        Args:
            user_id: User identifier
            exchange: Exchange identifier
        """
        try:
            # Unsubscribe from order events
            channel = f"orders:{user_id}:{exchange}"
            await self.pubsub_manager.unsubscribe(channel)

            # Remove from active subscriptions
            key = f"{user_id}:{exchange}"
            if key in self.active_subscriptions:
                del self.active_subscriptions[key]

            logger.info(
                f"Stopped order tracking",
                extra={"user_id": user_id, "exchange": exchange}
            )

        except Exception as e:
            logger.error(
                f"Failed to stop order tracking: {e}",
                exc_info=True,
                extra={"user_id": user_id, "exchange": exchange}
            )

    def register_callback(self, callback: callable):
        """
        Register callback for order events.

        Used by conditional cancellation manager and other components.

        Args:
            callback: Async callback function
        """
        self.order_callbacks.append(callback)

    async def _handle_order_event(self, event: OrderEvent):
        """
        Handle order update event.

        Updates Redis state and triggers callbacks.

        Args:
            event: OrderEvent instance
        """
        try:
            logger.debug(
                f"Handling order event",
                extra={
                    "event_type": event.event_type,
                    "user_id": event.user_id,
                    "order_id": event.order_id,
                    "status": event.status
                }
            )

            # Update real-time order state in Redis
            await self._update_redis_state(event)

            # Trigger registered callbacks
            for callback in self.order_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(event)
                    else:
                        callback(event)
                except Exception as e:
                    logger.error(
                        f"Error in order callback: {e}",
                        exc_info=True
                    )

            # Log order update
            logger.info(
                f"Order updated: {event.order_id} - {event.status}",
                extra={
                    "user_id": event.user_id,
                    "symbol": event.symbol,
                    "side": event.side,
                    "order_type": event.order_type,
                    "filled_qty": str(event.filled_qty),
                    "quantity": str(event.quantity)
                }
            )

        except Exception as e:
            logger.error(
                f"Error handling order event: {e}",
                exc_info=True,
                extra={"event": event.dict()}
            )

    async def _update_redis_state(self, event: OrderEvent):
        """
        Update order state in Redis.

        Stores in:
        - orders:realtime:{user_id}:{exchange}:{order_id}
        - orders:open:{user_id}:{exchange}  (set of open order IDs)
        - orders:closed:{user_id}:{exchange}  (list of closed orders)

        Args:
            event: OrderEvent instance
        """
        try:
            # Build Redis key for real-time state
            redis_key = f"orders:realtime:{event.user_id}:{event.exchange}:{event.order_id}"

            # Prepare order data
            order_data = {
                "order_id": event.order_id,
                "user_id": event.user_id,
                "exchange": event.exchange,
                "symbol": event.symbol,
                "side": event.side,
                "order_type": event.order_type,
                "quantity": str(event.quantity),
                "price": str(event.price) if event.price else "",
                "filled_qty": str(event.filled_qty),
                "avg_fill_price": str(event.avg_fill_price) if event.avg_fill_price else "",
                "status": event.status,
                "last_updated": datetime.utcnow().isoformat(),
                "event_type": event.event_type.value
            }

            # Store in Redis hash
            await self.redis_client.hset(redis_key, mapping=order_data)

            # Update open/closed order sets
            open_set_key = f"orders:open:{event.user_id}:{event.exchange}"
            closed_list_key = f"orders:closed:{event.user_id}:{event.exchange}"

            if event.status in ['filled', 'canceled', 'failed']:
                # Remove from open set
                await self.redis_client.srem(open_set_key, event.order_id)

                # Add to closed list
                await self.redis_client.lpush(closed_list_key, json.dumps(order_data))

                # Trim closed list to last 1000 orders
                await self.redis_client.ltrim(closed_list_key, 0, 999)

                # Delete real-time key after moving to closed
                await self.redis_client.expire(redis_key, 3600)  # Keep for 1 hour

            else:
                # Add to open set
                await self.redis_client.sadd(open_set_key, event.order_id)

                # Set TTL (24 hours)
                await self.redis_client.expire(redis_key, 86400)

            logger.debug(
                f"Updated Redis order state",
                extra={"redis_key": redis_key, "status": event.status}
            )

        except Exception as e:
            logger.error(
                f"Failed to update Redis state: {e}",
                exc_info=True,
                extra={"event": event.dict()}
            )

    async def get_open_orders(
        self,
        user_id: str,
        exchange: str,
        symbol: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get current open orders from Redis.

        Args:
            user_id: User identifier
            exchange: Exchange identifier
            symbol: Optional symbol filter

        Returns:
            List of order data dictionaries
        """
        try:
            orders = []

            # Get all open order IDs
            open_set_key = f"orders:open:{user_id}:{exchange}"
            order_ids = await self.redis_client.smembers(open_set_key)

            for order_id in order_ids:
                redis_key = f"orders:realtime:{user_id}:{exchange}:{order_id}"
                data = await self.redis_client.hgetall(redis_key)

                if data:
                    # Apply symbol filter if specified
                    if symbol is None or data.get('symbol') == symbol:
                        orders.append(data)

            return orders

        except Exception as e:
            logger.error(
                f"Failed to get open orders: {e}",
                exc_info=True,
                extra={"user_id": user_id, "exchange": exchange}
            )
            return []

    async def get_closed_orders(
        self,
        user_id: str,
        exchange: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get recent closed orders from Redis.

        Args:
            user_id: User identifier
            exchange: Exchange identifier
            limit: Maximum number of orders to return

        Returns:
            List of order data dictionaries
        """
        try:
            closed_list_key = f"orders:closed:{user_id}:{exchange}"
            order_data_list = await self.redis_client.lrange(closed_list_key, 0, limit - 1)

            orders = [json.loads(data) for data in order_data_list]

            return orders

        except Exception as e:
            logger.error(
                f"Failed to get closed orders: {e}",
                exc_info=True,
                extra={"user_id": user_id, "exchange": exchange}
            )
            return []

    async def get_order_status(
        self,
        user_id: str,
        exchange: str,
        order_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get current status of specific order.

        Args:
            user_id: User identifier
            exchange: Exchange identifier
            order_id: Order ID

        Returns:
            Order data dictionary or None
        """
        try:
            redis_key = f"orders:realtime:{user_id}:{exchange}:{order_id}"
            data = await self.redis_client.hgetall(redis_key)

            if data:
                return data

            # Check in closed orders
            closed_list_key = f"orders:closed:{user_id}:{exchange}"
            order_data_list = await self.redis_client.lrange(closed_list_key, 0, 999)

            for data_json in order_data_list:
                data = json.loads(data_json)
                if data.get('order_id') == order_id:
                    return data

            return None

        except Exception as e:
            logger.error(
                f"Failed to get order status: {e}",
                exc_info=True,
                extra={"user_id": user_id, "exchange": exchange, "order_id": order_id}
            )
            return None
