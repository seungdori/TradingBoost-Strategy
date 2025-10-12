"""Trailing Stop Manager

Manages trailing stop orders that automatically adjust stop price
based on favorable price movements.
"""

import asyncio
import json
from typing import Optional, Dict, Any, List
from datetime import datetime
from decimal import Decimal

from redis.asyncio import Redis
import ccxt.async_support as ccxt

from shared.logging import get_logger
from shared.config import get_settings

from core.event_types import TrailingStopEvent, EventType, PriceEvent
from core.pubsub_manager import PubSubManager

logger = get_logger(__name__)
settings = get_settings()


class TrailingStopConfig:
    """Trailing stop configuration"""

    def __init__(
        self,
        user_id: str,
        exchange: str,
        symbol: str,
        side: str,  # 'long' or 'short'
        activation_price: Decimal,
        callback_rate: Decimal,  # e.g., 0.02 for 2%
        size: Decimal,
        order_id: Optional[str] = None
    ):
        self.user_id = user_id
        self.exchange = exchange
        self.symbol = symbol
        self.side = side
        self.activation_price = activation_price
        self.callback_rate = callback_rate
        self.size = size
        self.order_id = order_id

        # Runtime state
        self.activated = False
        self.current_highest = Decimal("0")  # For long
        self.current_lowest = Decimal("0")  # For short
        self.stop_price = Decimal("0")
        self.created_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for Redis storage"""
        return {
            "user_id": self.user_id,
            "exchange": self.exchange,
            "symbol": self.symbol,
            "side": self.side,
            "activation_price": str(self.activation_price),
            "callback_rate": str(self.callback_rate),
            "size": str(self.size),
            "order_id": self.order_id or "",
            "activated": str(self.activated),
            "current_highest": str(self.current_highest),
            "current_lowest": str(self.current_lowest),
            "stop_price": str(self.stop_price),
            "created_at": self.created_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TrailingStopConfig':
        """Create from dictionary"""
        config = cls(
            user_id=data['user_id'],
            exchange=data['exchange'],
            symbol=data['symbol'],
            side=data['side'],
            activation_price=Decimal(data['activation_price']),
            callback_rate=Decimal(data['callback_rate']),
            size=Decimal(data['size']),
            order_id=data.get('order_id') or None
        )
        config.activated = data.get('activated', 'False') == 'True'
        config.current_highest = Decimal(data.get('current_highest', '0'))
        config.current_lowest = Decimal(data.get('current_lowest', '0'))
        config.stop_price = Decimal(data.get('stop_price', '0'))

        if data.get('created_at'):
            config.created_at = datetime.fromisoformat(data['created_at'])

        return config


class TrailingStopManager:
    """
    Trailing stop management service.

    Features:
    - Price-based activation
    - Dynamic stop price adjustment
    - Automatic order execution on trigger
    - Pub/sub notifications
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

        # Active trailing stops: {user_id:symbol:side -> TrailingStopConfig}
        self.active_trailing_stops: Dict[str, TrailingStopConfig] = {}

        # Price subscriptions
        self.price_subscriptions: Dict[str, bool] = {}

    async def set_trailing_stop(
        self,
        user_id: str,
        exchange: str,
        symbol: str,
        side: str,
        activation_price: Decimal,
        callback_rate: Decimal,
        size: Decimal,
        order_id: Optional[str] = None
    ) -> str:
        """
        Set a trailing stop rule.

        Args:
            user_id: User identifier
            exchange: Exchange identifier
            symbol: Trading symbol
            side: Position side ('long' or 'short')
            activation_price: Price at which trailing stop activates
            callback_rate: Callback rate (e.g., 0.02 for 2%)
            size: Position size to close
            order_id: Optional order ID to associate

        Returns:
            Trailing stop ID
        """
        try:
            # Create trailing stop config
            config = TrailingStopConfig(
                user_id=user_id,
                exchange=exchange,
                symbol=symbol,
                side=side,
                activation_price=activation_price,
                callback_rate=callback_rate,
                size=size,
                order_id=order_id
            )

            # Store in Redis
            redis_key = f"trailing_stops:{user_id}:{symbol}:{side}"
            await self.redis_client.hset(redis_key, mapping=config.to_dict())
            await self.redis_client.expire(redis_key, 86400)  # 24 hours

            # Add to active tracking
            tracking_key = f"{user_id}:{symbol}:{side}"
            self.active_trailing_stops[tracking_key] = config

            # Subscribe to price updates for this symbol
            await self._subscribe_to_prices(exchange, symbol)

            logger.info(
                f"Set trailing stop: {symbol} {side}",
                extra={
                    "user_id": user_id,
                    "activation_price": str(activation_price),
                    "callback_rate": str(callback_rate)
                }
            )

            return redis_key

        except Exception as e:
            logger.error(
                f"Failed to set trailing stop: {e}",
                exc_info=True,
                extra={"user_id": user_id, "symbol": symbol}
            )
            raise

    async def _subscribe_to_prices(self, exchange: str, symbol: str):
        """Subscribe to price updates for symbol"""
        sub_key = f"{exchange}:{symbol}"

        if sub_key not in self.price_subscriptions:
            await self.pubsub_manager.subscribe_to_prices(
                exchange=exchange,
                symbol=symbol,
                callback=self._handle_price_update
            )
            self.price_subscriptions[sub_key] = True

            logger.debug(f"Subscribed to price updates: {symbol}")

    async def _handle_price_update(self, event: PriceEvent):
        """
        Handle price update and check trailing stops.

        Args:
            event: PriceEvent instance
        """
        try:
            current_price = event.price

            # Check all active trailing stops for this symbol
            for tracking_key, config in list(self.active_trailing_stops.items()):
                if config.symbol != event.symbol or config.exchange != event.exchange:
                    continue

                # Update trailing stop state
                await self._update_trailing_stop(config, current_price)

        except Exception as e:
            logger.error(
                f"Error handling price update: {e}",
                exc_info=True,
                extra={"event": event.dict()}
            )

    async def _update_trailing_stop(
        self,
        config: TrailingStopConfig,
        current_price: Decimal
    ):
        """
        Update trailing stop based on current price.

        Args:
            config: TrailingStopConfig instance
            current_price: Current market price
        """
        try:
            # Check if trailing stop should activate
            if not config.activated:
                if config.side == 'long' and current_price >= config.activation_price:
                    config.activated = True
                    config.current_highest = current_price
                    config.stop_price = current_price * (Decimal("1") - config.callback_rate)

                    logger.info(
                        f"Trailing stop activated: {config.symbol} {config.side}",
                        extra={
                            "user_id": config.user_id,
                            "activation_price": str(config.activation_price),
                            "current_price": str(current_price)
                        }
                    )

                elif config.side == 'short' and current_price <= config.activation_price:
                    config.activated = True
                    config.current_lowest = current_price
                    config.stop_price = current_price * (Decimal("1") + config.callback_rate)

                    logger.info(
                        f"Trailing stop activated: {config.symbol} {config.side}",
                        extra={
                            "user_id": config.user_id,
                            "activation_price": str(config.activation_price),
                            "current_price": str(current_price)
                        }
                    )

            # If activated, update stop price
            if config.activated:
                if config.side == 'long':
                    # Update highest price
                    if current_price > config.current_highest:
                        config.current_highest = current_price
                        config.stop_price = current_price * (Decimal("1") - config.callback_rate)

                        logger.debug(
                            f"Trailing stop updated: {config.symbol}",
                            extra={
                                "current_highest": str(config.current_highest),
                                "stop_price": str(config.stop_price)
                            }
                        )

                    # Check if stop triggered
                    if current_price <= config.stop_price:
                        await self._trigger_trailing_stop(config, current_price)

                elif config.side == 'short':
                    # Update lowest price
                    if current_price < config.current_lowest:
                        config.current_lowest = current_price
                        config.stop_price = current_price * (Decimal("1") + config.callback_rate)

                        logger.debug(
                            f"Trailing stop updated: {config.symbol}",
                            extra={
                                "current_lowest": str(config.current_lowest),
                                "stop_price": str(config.stop_price)
                            }
                        )

                    # Check if stop triggered
                    if current_price >= config.stop_price:
                        await self._trigger_trailing_stop(config, current_price)

                # Update Redis state
                redis_key = f"trailing_stops:{config.user_id}:{config.symbol}:{config.side}"
                await self.redis_client.hset(redis_key, mapping=config.to_dict())

        except Exception as e:
            logger.error(
                f"Error updating trailing stop: {e}",
                exc_info=True,
                extra={"config": config.to_dict()}
            )

    async def _trigger_trailing_stop(
        self,
        config: TrailingStopConfig,
        trigger_price: Decimal
    ):
        """
        Trigger trailing stop and execute market order.

        Args:
            config: TrailingStopConfig instance
            trigger_price: Price at which stop was triggered
        """
        try:
            logger.warning(
                f"Trailing stop TRIGGERED: {config.symbol} {config.side}",
                extra={
                    "user_id": config.user_id,
                    "stop_price": str(config.stop_price),
                    "trigger_price": str(trigger_price)
                }
            )

            # Execute market order to close position
            # (This would integrate with OrderManager from HYPERRSI)
            # For now, we'll publish an event

            # Publish trailing stop triggered event
            event = TrailingStopEvent(
                event_type=EventType.TRAILING_STOP_TRIGGERED,
                user_id=config.user_id,
                exchange=config.exchange,
                symbol=config.symbol,
                activation_price=config.activation_price,
                callback_rate=config.callback_rate,
                current_highest=config.current_highest if config.side == 'long' else config.current_lowest,
                stop_price=config.stop_price,
                triggered=True
            )

            await self.pubsub_manager.publish_trailing_stop_event(event)

            # Remove from active tracking
            tracking_key = f"{config.user_id}:{config.symbol}:{config.side}"
            if tracking_key in self.active_trailing_stops:
                del self.active_trailing_stops[tracking_key]

            # Remove from Redis
            redis_key = f"trailing_stops:{config.user_id}:{config.symbol}:{config.side}"
            await self.redis_client.delete(redis_key)

            logger.info(
                f"Trailing stop triggered and removed",
                extra={"user_id": config.user_id, "symbol": config.symbol}
            )

        except Exception as e:
            logger.error(
                f"Error triggering trailing stop: {e}",
                exc_info=True,
                extra={"config": config.to_dict()}
            )

    async def remove_trailing_stop(
        self,
        user_id: str,
        symbol: str,
        side: str
    ) -> bool:
        """
        Remove trailing stop rule.

        Args:
            user_id: User identifier
            symbol: Trading symbol
            side: Position side

        Returns:
            True if removed successfully
        """
        try:
            tracking_key = f"{user_id}:{symbol}:{side}"

            # Remove from active tracking
            if tracking_key in self.active_trailing_stops:
                del self.active_trailing_stops[tracking_key]

            # Remove from Redis
            redis_key = f"trailing_stops:{user_id}:{symbol}:{side}"
            await self.redis_client.delete(redis_key)

            logger.info(
                f"Removed trailing stop",
                extra={"user_id": user_id, "symbol": symbol, "side": side}
            )

            return True

        except Exception as e:
            logger.error(
                f"Failed to remove trailing stop: {e}",
                exc_info=True,
                extra={"user_id": user_id, "symbol": symbol}
            )
            return False

    async def get_trailing_stops(
        self,
        user_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get all trailing stops for user.

        Args:
            user_id: User identifier

        Returns:
            List of trailing stop configurations
        """
        try:
            trailing_stops = []

            # Scan Redis for user's trailing stops
            pattern = f"trailing_stops:{user_id}:*"
            cursor = 0

            while True:
                cursor, keys = await self.redis_client.scan(
                    cursor,
                    match=pattern,
                    count=100
                )

                for key in keys:
                    data = await self.redis_client.hgetall(key)
                    if data:
                        trailing_stops.append(data)

                if cursor == 0:
                    break

            return trailing_stops

        except Exception as e:
            logger.error(
                f"Failed to get trailing stops: {e}",
                exc_info=True,
                extra={"user_id": user_id}
            )
            return []
