"""Redis Pub/Sub Manager for Event-Driven Architecture

Manages Redis pub/sub channels for real-time event distribution
across position/order management microservice components.
"""

import asyncio
import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from shared.logging import get_logger

from .event_types import (
    BaseEvent,
    ConditionalRuleEvent,
    EventType,
    OrderEvent,
    PositionEvent,
    PriceEvent,
    TrailingStopEvent,
)

logger = get_logger(__name__)


class PubSubManager:
    """
    Redis Pub/Sub event broker for microservice communication.

    Channel Patterns:
    - positions:{user_id}:{exchange}:{symbol}
    - orders:{user_id}:{exchange}
    - prices:{exchange}:{symbol}
    - trailing_stops:{user_id}
    - conditional_rules:{user_id}
    """

    def __init__(self, redis_client: Redis):
        """
        Args:
            redis_client: Redis client instance
        """
        self.redis_client = redis_client
        self.pubsub: Optional[PubSub] = None
        self.subscribers: Dict[str, List[Callable]] = {}  # channel -> [callbacks]
        self.listen_task: Optional[asyncio.Task] = None

    async def start(self):
        """Initialize pub/sub connection"""
        try:
            self.pubsub = self.redis_client.pubsub()
            logger.info("PubSub manager started")
        except Exception as e:
            logger.error(f"Failed to start PubSub manager: {e}", exc_info=True)
            raise

    async def stop(self):
        """Cleanup pub/sub connection"""
        if self.listen_task:
            self.listen_task.cancel()
            try:
                await self.listen_task
            except asyncio.CancelledError:
                pass

        if self.pubsub:
            await self.pubsub.close()

        logger.info("PubSub manager stopped")

    # ==================== Publishing Methods ====================

    async def publish_position_event(self, event: PositionEvent) -> int:
        """
        Publish position event to channel.

        Channel: positions:{user_id}:{exchange}:{symbol}

        Args:
            event: PositionEvent instance

        Returns:
            Number of subscribers who received the message
        """
        try:
            channel = f"positions:{event.user_id}:{event.exchange}:{event.symbol}"
            message = self._serialize_event(event)

            receivers = await self.redis_client.publish(channel, message)

            logger.debug(
                f"Published position event to {receivers} subscribers",
                extra={
                    "channel": channel,
                    "event_type": event.event_type,
                    "position_id": event.position_id
                }
            )

            return receivers

        except Exception as e:
            logger.error(
                f"Failed to publish position event: {e}",
                exc_info=True,
                extra={"event": event.dict()}
            )
            return 0

    async def publish_order_event(self, event: OrderEvent) -> int:
        """
        Publish order event to channel.

        Channel: orders:{user_id}:{exchange}

        Args:
            event: OrderEvent instance

        Returns:
            Number of subscribers who received the message
        """
        try:
            channel = f"orders:{event.user_id}:{event.exchange}"
            message = self._serialize_event(event)

            receivers = await self.redis_client.publish(channel, message)

            logger.debug(
                f"Published order event to {receivers} subscribers",
                extra={
                    "channel": channel,
                    "event_type": event.event_type,
                    "order_id": event.order_id
                }
            )

            return receivers

        except Exception as e:
            logger.error(
                f"Failed to publish order event: {e}",
                exc_info=True,
                extra={"event": event.dict()}
            )
            return 0

    async def publish_price_event(self, event: PriceEvent) -> int:
        """
        Publish price update event to channel.

        Channel: prices:{exchange}:{symbol}

        Args:
            event: PriceEvent instance

        Returns:
            Number of subscribers who received the message
        """
        try:
            channel = f"prices:{event.exchange}:{event.symbol}"
            message = self._serialize_event(event)

            receivers = await self.redis_client.publish(channel, message)

            logger.debug(
                f"Published price event to {receivers} subscribers",
                extra={
                    "channel": channel,
                    "symbol": event.symbol,
                    "price": str(event.price)
                }
            )

            return receivers

        except Exception as e:
            logger.error(
                f"Failed to publish price event: {e}",
                exc_info=True,
                extra={"event": event.dict()}
            )
            return 0

    async def publish_trailing_stop_event(self, event: TrailingStopEvent) -> int:
        """
        Publish trailing stop event to channel.

        Channel: trailing_stops:{user_id}

        Args:
            event: TrailingStopEvent instance

        Returns:
            Number of subscribers who received the message
        """
        try:
            channel = f"trailing_stops:{event.user_id}"
            message = self._serialize_event(event)

            receivers = await self.redis_client.publish(channel, message)

            logger.debug(
                f"Published trailing stop event to {receivers} subscribers",
                extra={
                    "channel": channel,
                    "symbol": event.symbol,
                    "triggered": event.triggered
                }
            )

            return receivers

        except Exception as e:
            logger.error(
                f"Failed to publish trailing stop event: {e}",
                exc_info=True,
                extra={"event": event.dict()}
            )
            return 0

    async def publish_conditional_rule_event(self, event: ConditionalRuleEvent) -> int:
        """
        Publish conditional rule event to channel.

        Channel: conditional_rules:{user_id}

        Args:
            event: ConditionalRuleEvent instance

        Returns:
            Number of subscribers who received the message
        """
        try:
            channel = f"conditional_rules:{event.user_id}"
            message = self._serialize_event(event)

            receivers = await self.redis_client.publish(channel, message)

            logger.debug(
                f"Published conditional rule event to {receivers} subscribers",
                extra={
                    "channel": channel,
                    "rule_id": event.rule_id,
                    "triggered": event.triggered
                }
            )

            return receivers

        except Exception as e:
            logger.error(
                f"Failed to publish conditional rule event: {e}",
                exc_info=True,
                extra={"event": event.dict()}
            )
            return 0

    # ==================== Subscription Methods ====================

    async def subscribe_to_positions(
        self,
        user_id: str,
        exchange: str,
        symbol: str,
        callback: Callable[[PositionEvent], Any]
    ):
        """
        Subscribe to position events for specific symbol.

        Args:
            user_id: User identifier
            exchange: Exchange identifier
            symbol: Trading symbol
            callback: Async callback function to handle events
        """
        channel = f"positions:{user_id}:{exchange}:{symbol}"
        await self._subscribe_to_channel(channel, callback, PositionEvent)

    async def subscribe_to_orders(
        self,
        user_id: str,
        exchange: str,
        callback: Callable[[OrderEvent], Any]
    ):
        """
        Subscribe to order events for user.

        Args:
            user_id: User identifier
            exchange: Exchange identifier
            callback: Async callback function to handle events
        """
        channel = f"orders:{user_id}:{exchange}"
        await self._subscribe_to_channel(channel, callback, OrderEvent)

    async def subscribe_to_prices(
        self,
        exchange: str,
        symbol: str,
        callback: Callable[[PriceEvent], Any]
    ):
        """
        Subscribe to price updates for symbol.

        Args:
            exchange: Exchange identifier
            symbol: Trading symbol
            callback: Async callback function to handle events
        """
        channel = f"prices:{exchange}:{symbol}"
        await self._subscribe_to_channel(channel, callback, PriceEvent)

    async def subscribe_to_trailing_stops(
        self,
        user_id: str,
        callback: Callable[[TrailingStopEvent], Any]
    ):
        """
        Subscribe to trailing stop events for user.

        Args:
            user_id: User identifier
            callback: Async callback function to handle events
        """
        channel = f"trailing_stops:{user_id}"
        await self._subscribe_to_channel(channel, callback, TrailingStopEvent)

    async def subscribe_to_conditional_rules(
        self,
        user_id: str,
        callback: Callable[[ConditionalRuleEvent], Any]
    ):
        """
        Subscribe to conditional rule events for user.

        Args:
            user_id: User identifier
            callback: Async callback function to handle events
        """
        channel = f"conditional_rules:{user_id}"
        await self._subscribe_to_channel(channel, callback, ConditionalRuleEvent)

    async def _subscribe_to_channel(
        self,
        channel: str,
        callback: Callable,
        event_class: type
    ):
        """
        Internal method to subscribe to a channel.

        Args:
            channel: Redis channel name
            callback: Callback function
            event_class: Event class for deserialization
        """
        try:
            if not self.pubsub:
                await self.start()

            # Subscribe to channel
            await self.pubsub.subscribe(channel)

            # Store callback
            if channel not in self.subscribers:
                self.subscribers[channel] = []
            self.subscribers[channel].append((callback, event_class))

            logger.info(f"Subscribed to channel: {channel}")

            # Start listen task if not running
            if not self.listen_task or self.listen_task.done():
                self.listen_task = asyncio.create_task(self._listen_loop())

        except Exception as e:
            logger.error(
                f"Failed to subscribe to channel {channel}: {e}",
                exc_info=True
            )
            raise

    async def _listen_loop(self):
        """Main listen loop for pub/sub messages"""
        logger.info("PubSub listen loop started")

        try:
            async for message in self.pubsub.listen():
                if message['type'] == 'message':
                    channel = message['channel'].decode('utf-8')
                    data = message['data']

                    # Find callbacks for this channel
                    if channel in self.subscribers:
                        for callback, event_class in self.subscribers[channel]:
                            try:
                                # Deserialize event
                                event = self._deserialize_event(data, event_class)

                                # Call callback
                                if asyncio.iscoroutinefunction(callback):
                                    await callback(event)
                                else:
                                    callback(event)

                            except Exception as e:
                                logger.error(
                                    f"Error in callback for channel {channel}: {e}",
                                    exc_info=True
                                )

        except asyncio.CancelledError:
            logger.info("PubSub listen loop cancelled")
        except Exception as e:
            logger.error(f"PubSub listen loop error: {e}", exc_info=True)

    # ==================== Serialization Methods ====================

    def _serialize_event(self, event: BaseEvent) -> str:
        """
        Serialize event to JSON string.

        Args:
            event: Event instance

        Returns:
            JSON string
        """
        # Convert Decimal to string for JSON serialization
        event_dict = event.dict()
        for key, value in event_dict.items():
            if isinstance(value, Decimal):
                event_dict[key] = str(value)

        return json.dumps(event_dict)

    def _deserialize_event(self, data: bytes, event_class: type) -> BaseEvent:
        """
        Deserialize JSON bytes to event object.

        Args:
            data: JSON bytes
            event_class: Event class to deserialize to

        Returns:
            Event instance
        """
        event_dict = json.loads(data)

        # Convert string back to Decimal for numeric fields
        for key, value in event_dict.items():
            if isinstance(value, str) and key in [
                'size', 'entry_price', 'current_price', 'unrealized_pnl',
                'quantity', 'price', 'filled_qty', 'avg_fill_price',
                'activation_price', 'callback_rate', 'current_highest', 'stop_price'
            ]:
                try:
                    event_dict[key] = Decimal(value)
                except:
                    pass

        return event_class(**event_dict)

    async def unsubscribe(self, channel: str):
        """Unsubscribe from a channel"""
        if self.pubsub:
            await self.pubsub.unsubscribe(channel)

            if channel in self.subscribers:
                del self.subscribers[channel]

            logger.info(f"Unsubscribed from channel: {channel}")
