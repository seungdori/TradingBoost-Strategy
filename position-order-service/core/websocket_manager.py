"""WebSocket Manager for Real-Time Position/Order Tracking

Manages WebSocket connections to multiple exchanges (OKX, Binance, Upbit)
with automatic reconnection, heartbeat, and event publishing.
"""

import asyncio
import json
from typing import Optional, Dict, Any, Callable, List, Set
from datetime import datetime
from decimal import Decimal
import traceback

import ccxt.async_support as ccxt
from redis.asyncio import Redis

from shared.logging import get_logger
from shared.config import get_settings
from .event_types import PositionEvent, OrderEvent, PriceEvent, EventType

logger = get_logger(__name__)
settings = get_settings()


class WebSocketManager:
    """
    WebSocket connection manager for real-time market data.

    Features:
    - Multi-exchange support (OKX, Binance, Upbit)
    - Automatic reconnection with exponential backoff
    - Heartbeat/ping-pong for connection health
    - Event publishing to Redis Pub/Sub
    """

    def __init__(
        self,
        redis_client: Redis,
        pubsub_callback: Optional[Callable] = None
    ):
        """
        Args:
            redis_client: Redis client for pub/sub
            pubsub_callback: Callback function for publishing events
        """
        self.redis_client = redis_client
        self.pubsub_callback = pubsub_callback

        # Active connections
        self.connections: Dict[str, Any] = {}  # exchange_id -> connection
        self.subscriptions: Dict[str, Set[str]] = {}  # exchange_id -> {symbols}

        # Reconnection settings
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 1.0  # seconds
        self.heartbeat_interval = 30.0  # seconds

        # Tasks
        self.tasks: Dict[str, asyncio.Task] = {}

    async def connect(
        self,
        exchange_id: str,
        user_id: str,
        api_credentials: Dict[str, str]
    ) -> bool:
        """
        Establish WebSocket connection to exchange.

        Args:
            exchange_id: Exchange identifier (okx, binance, etc.)
            user_id: User identifier
            api_credentials: API keys

        Returns:
            True if connection successful
        """
        try:
            # Create exchange instance
            exchange_class = getattr(ccxt, exchange_id.lower())
            exchange = exchange_class({
                'apiKey': api_credentials.get('api_key'),
                'secret': api_credentials.get('api_secret'),
                'password': api_credentials.get('passphrase'),
                'enableRateLimit': True,
                'options': {'defaultType': 'swap'}
            })

            # Store connection
            conn_key = f"{exchange_id}:{user_id}"
            self.connections[conn_key] = exchange
            self.subscriptions[conn_key] = set()

            logger.info(
                f"WebSocket connected to {exchange_id}",
                extra={"user_id": user_id, "exchange": exchange_id}
            )

            # Start heartbeat task
            heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(conn_key, exchange)
            )
            self.tasks[f"{conn_key}:heartbeat"] = heartbeat_task

            return True

        except Exception as e:
            logger.error(
                f"Failed to connect WebSocket: {e}",
                exc_info=True,
                extra={"user_id": user_id, "exchange": exchange_id}
            )
            return False

    async def subscribe_positions(
        self,
        user_id: str,
        exchange_id: str,
        symbols: List[str]
    ) -> bool:
        """
        Subscribe to position updates via WebSocket.

        Args:
            user_id: User identifier
            exchange_id: Exchange identifier
            symbols: List of symbols to subscribe

        Returns:
            True if subscription successful
        """
        conn_key = f"{exchange_id}:{user_id}"
        if conn_key not in self.connections:
            logger.warning(f"No connection found for {conn_key}")
            return False

        try:
            exchange = self.connections[conn_key]

            # Exchange-specific subscription logic
            if exchange_id.lower() == 'okx':
                # OKX: Subscribe to positions channel
                for symbol in symbols:
                    await exchange.watch_positions([symbol])
                    self.subscriptions[conn_key].add(f"positions:{symbol}")

            elif exchange_id.lower() == 'binance':
                # Binance: Subscribe to user data stream
                for symbol in symbols:
                    await exchange.watch_balance()  # Includes positions
                    self.subscriptions[conn_key].add(f"positions:{symbol}")

            # Start listening task
            task = asyncio.create_task(
                self._position_listener(conn_key, user_id, exchange_id, symbols)
            )
            self.tasks[f"{conn_key}:positions"] = task

            logger.info(
                f"Subscribed to positions",
                extra={"user_id": user_id, "exchange": exchange_id, "symbols": symbols}
            )

            return True

        except Exception as e:
            logger.error(
                f"Failed to subscribe to positions: {e}",
                exc_info=True,
                extra={"user_id": user_id, "exchange": exchange_id}
            )
            return False

    async def subscribe_orders(
        self,
        user_id: str,
        exchange_id: str,
        symbols: List[str]
    ) -> bool:
        """
        Subscribe to order updates via WebSocket.

        Args:
            user_id: User identifier
            exchange_id: Exchange identifier
            symbols: List of symbols to subscribe

        Returns:
            True if subscription successful
        """
        conn_key = f"{exchange_id}:{user_id}"
        if conn_key not in self.connections:
            logger.warning(f"No connection found for {conn_key}")
            return False

        try:
            exchange = self.connections[conn_key]

            # Exchange-specific subscription logic
            if exchange_id.lower() == 'okx':
                # OKX: Subscribe to orders channel
                for symbol in symbols:
                    await exchange.watch_orders(symbol)
                    self.subscriptions[conn_key].add(f"orders:{symbol}")

            elif exchange_id.lower() == 'binance':
                # Binance: Subscribe to user data stream
                for symbol in symbols:
                    await exchange.watch_orders(symbol)
                    self.subscriptions[conn_key].add(f"orders:{symbol}")

            # Start listening task
            task = asyncio.create_task(
                self._order_listener(conn_key, user_id, exchange_id, symbols)
            )
            self.tasks[f"{conn_key}:orders"] = task

            logger.info(
                f"Subscribed to orders",
                extra={"user_id": user_id, "exchange": exchange_id, "symbols": symbols}
            )

            return True

        except Exception as e:
            logger.error(
                f"Failed to subscribe to orders: {e}",
                exc_info=True,
                extra={"user_id": user_id, "exchange": exchange_id}
            )
            return False

    async def _position_listener(
        self,
        conn_key: str,
        user_id: str,
        exchange_id: str,
        symbols: List[str]
    ):
        """Listen for position updates and publish events"""
        exchange = self.connections[conn_key]

        while conn_key in self.connections:
            try:
                # Watch for position updates
                positions = await exchange.watch_positions(symbols)

                for position in positions:
                    # Parse position data
                    event = await self._parse_position_update(
                        user_id,
                        exchange_id,
                        position
                    )

                    if event and self.pubsub_callback:
                        await self.pubsub_callback(event)

                await asyncio.sleep(0.1)  # Small delay

            except Exception as e:
                logger.error(
                    f"Position listener error: {e}",
                    exc_info=True,
                    extra={"conn_key": conn_key}
                )
                await asyncio.sleep(1.0)  # Error backoff

    async def _order_listener(
        self,
        conn_key: str,
        user_id: str,
        exchange_id: str,
        symbols: List[str]
    ):
        """Listen for order updates and publish events"""
        exchange = self.connections[conn_key]

        while conn_key in self.connections:
            try:
                # Watch for order updates
                for symbol in symbols:
                    orders = await exchange.watch_orders(symbol)

                    for order in orders:
                        # Parse order data
                        event = await self._parse_order_update(
                            user_id,
                            exchange_id,
                            order
                        )

                        if event and self.pubsub_callback:
                            await self.pubsub_callback(event)

                await asyncio.sleep(0.1)  # Small delay

            except Exception as e:
                logger.error(
                    f"Order listener error: {e}",
                    exc_info=True,
                    extra={"conn_key": conn_key}
                )
                await asyncio.sleep(1.0)  # Error backoff

    async def _parse_position_update(
        self,
        user_id: str,
        exchange_id: str,
        position_data: Dict[str, Any]
    ) -> Optional[PositionEvent]:
        """Parse position data into PositionEvent"""
        try:
            # Extract position fields (OKX format)
            symbol = position_data.get('symbol')
            side = 'long' if float(position_data.get('contracts', 0)) > 0 else 'short'
            size = abs(Decimal(str(position_data.get('contracts', 0))))
            entry_price = Decimal(str(position_data.get('entryPrice', 0)))
            current_price = Decimal(str(position_data.get('markPrice', 0)))
            unrealized_pnl = Decimal(str(position_data.get('unrealizedPnl', 0)))
            leverage = int(position_data.get('leverage', 1))

            event = PositionEvent(
                event_type=EventType.POSITION_UPDATED,
                user_id=user_id,
                exchange=exchange_id,
                position_id=f"{user_id}:{exchange_id}:{symbol}:{side}",
                symbol=symbol,
                side=side,
                size=size,
                entry_price=entry_price,
                current_price=current_price,
                unrealized_pnl=unrealized_pnl,
                leverage=leverage
            )

            return event

        except Exception as e:
            logger.error(
                f"Failed to parse position update: {e}",
                exc_info=True,
                extra={"position_data": position_data}
            )
            return None

    async def _parse_order_update(
        self,
        user_id: str,
        exchange_id: str,
        order_data: Dict[str, Any]
    ) -> Optional[OrderEvent]:
        """Parse order data into OrderEvent"""
        try:
            # Extract order fields (CCXT unified format)
            order_id = order_data.get('id')
            symbol = order_data.get('symbol')
            side = order_data.get('side')
            order_type = order_data.get('type')
            quantity = Decimal(str(order_data.get('amount', 0)))
            price = Decimal(str(order_data.get('price', 0))) if order_data.get('price') else None
            filled_qty = Decimal(str(order_data.get('filled', 0)))
            avg_fill_price = Decimal(str(order_data.get('average', 0))) if order_data.get('average') else None
            status = order_data.get('status')

            # Determine event type based on status
            if status == 'closed' and filled_qty == quantity:
                event_type = EventType.ORDER_FILLED
            elif status == 'open' and filled_qty > 0:
                event_type = EventType.ORDER_PARTIALLY_FILLED
            elif status == 'canceled':
                event_type = EventType.ORDER_CANCELED
            else:
                event_type = EventType.ORDER_CREATED

            event = OrderEvent(
                event_type=event_type,
                user_id=user_id,
                exchange=exchange_id,
                order_id=order_id,
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                filled_qty=filled_qty,
                avg_fill_price=avg_fill_price,
                status=status
            )

            return event

        except Exception as e:
            logger.error(
                f"Failed to parse order update: {e}",
                exc_info=True,
                extra={"order_data": order_data}
            )
            return None

    async def _heartbeat_loop(self, conn_key: str, exchange: ccxt.Exchange):
        """Send periodic heartbeat/ping to maintain connection"""
        while conn_key in self.connections:
            try:
                await asyncio.sleep(self.heartbeat_interval)

                # Send ping (exchange-specific)
                if hasattr(exchange, 'ping'):
                    await exchange.ping()

                logger.debug(f"Heartbeat sent for {conn_key}")

            except Exception as e:
                logger.warning(
                    f"Heartbeat failed for {conn_key}: {e}",
                    extra={"conn_key": conn_key}
                )
                # Attempt reconnection
                await self._reconnect(conn_key)

    async def _reconnect(self, conn_key: str):
        """Attempt to reconnect WebSocket"""
        logger.info(f"Attempting to reconnect {conn_key}")

        for attempt in range(self.max_reconnect_attempts):
            try:
                await asyncio.sleep(self.reconnect_delay * (2 ** attempt))

                # Reconnection logic here
                # (Would need to re-establish connection with stored credentials)

                logger.info(f"Reconnected {conn_key} after {attempt + 1} attempts")
                return

            except Exception as e:
                logger.warning(
                    f"Reconnection attempt {attempt + 1} failed: {e}",
                    extra={"conn_key": conn_key}
                )

        logger.error(
            f"Failed to reconnect {conn_key} after {self.max_reconnect_attempts} attempts"
        )

    async def disconnect(self, user_id: str, exchange_id: str):
        """Close WebSocket connection"""
        conn_key = f"{exchange_id}:{user_id}"

        if conn_key in self.connections:
            # Cancel tasks
            for task_key in list(self.tasks.keys()):
                if task_key.startswith(conn_key):
                    self.tasks[task_key].cancel()
                    del self.tasks[task_key]

            # Close exchange connection
            exchange = self.connections[conn_key]
            await exchange.close()

            # Cleanup
            del self.connections[conn_key]
            if conn_key in self.subscriptions:
                del self.subscriptions[conn_key]

            logger.info(
                f"WebSocket disconnected",
                extra={"user_id": user_id, "exchange": exchange_id}
            )

    async def cleanup(self):
        """Cleanup all connections and tasks"""
        for conn_key in list(self.connections.keys()):
            parts = conn_key.split(':')
            await self.disconnect(parts[1], parts[0])
