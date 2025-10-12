"""User Tracker - Automatic User Monitoring

Automatically discovers and tracks users with active positions/orders.
Ensures all active users are continuously monitored.
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Set

from redis.asyncio import Redis

from shared.config import get_settings
from shared.logging import get_logger
from shared.services.position_order_service.core.websocket_manager import WebSocketManager
from shared.services.position_order_service.managers.order_tracker import OrderTracker
from shared.services.position_order_service.managers.position_tracker import PositionTracker

logger = get_logger(__name__)
settings = get_settings()


class UserTracker:
    """
    Automatic user discovery and tracking service.

    Features:
    - Scans Redis for users with active positions/orders
    - Automatically starts WebSocket subscriptions
    - Periodically checks for new users
    - Handles user cleanup when no active positions remain
    """

    def __init__(
        self,
        redis_client: Redis,
        websocket_manager: WebSocketManager,
        position_tracker: PositionTracker,
        order_tracker: OrderTracker
    ):
        """
        Args:
            redis_client: Redis client
            websocket_manager: WebSocket manager
            position_tracker: Position tracker
            order_tracker: Order tracker
        """
        self.redis_client = redis_client
        self.websocket_manager = websocket_manager
        self.position_tracker = position_tracker
        self.order_tracker = order_tracker

        # Tracked users: {user_id: {"exchange": str, "symbols": Set[str]}}
        self.tracked_users: Dict[str, Dict[str, Any]] = {}

        # Worker task
        self.worker_task: asyncio.Task = None
        self.running = False

        # Scan interval (seconds)
        self.scan_interval = 60.0  # 1분마다 스캔

    async def start(self):
        """Start automatic user tracking"""
        try:
            logger.info("Starting User Tracker...")

            # Initial scan
            await self.scan_active_users()

            # Start background worker
            self.running = True
            self.worker_task = asyncio.create_task(self._worker_loop())

            logger.info("✅ User Tracker started")

        except Exception as e:
            logger.error(f"Failed to start User Tracker: {e}", exc_info=True)
            raise

    async def stop(self):
        """Stop user tracking"""
        try:
            logger.info("Stopping User Tracker...")

            self.running = False

            if self.worker_task:
                self.worker_task.cancel()
                try:
                    await self.worker_task
                except asyncio.CancelledError:
                    pass

            # Stop tracking all users
            for user_id in list(self.tracked_users.keys()):
                await self.stop_tracking_user(user_id)

            logger.info("✅ User Tracker stopped")

        except Exception as e:
            logger.error(f"Error stopping User Tracker: {e}", exc_info=True)

    async def _worker_loop(self):
        """Background worker loop for periodic user scanning"""
        logger.info("User Tracker worker loop started")

        try:
            while self.running:
                await asyncio.sleep(self.scan_interval)

                # Periodic scan
                await self.scan_active_users()

        except asyncio.CancelledError:
            logger.info("User Tracker worker loop cancelled")
        except Exception as e:
            logger.error(f"User Tracker worker loop error: {e}", exc_info=True)

    async def scan_active_users(self):
        """
        Scan Redis for users with active positions/orders.

        Checks:
        - positions:index:{user_id}:{exchange}
        - orders:open:{user_id}:{exchange}
        - positions:realtime:{user_id}:*
        """
        try:
            logger.debug("Scanning for active users...")

            # 1. Scan position indices
            await self._scan_position_indices()

            # 2. Scan open orders
            await self._scan_open_orders()

            # 3. Scan realtime positions
            await self._scan_realtime_positions()

            logger.info(
                f"Active users scan complete: {len(self.tracked_users)} users tracked",
                extra={"tracked_users": list(self.tracked_users.keys())}
            )

        except Exception as e:
            logger.error(f"Failed to scan active users: {e}", exc_info=True)

    async def _scan_position_indices(self):
        """Scan position index keys"""
        try:
            # Pattern: positions:index:{user_id}:{exchange}
            pattern = "positions:index:*"
            cursor = 0

            while True:
                cursor, keys = await self.redis_client.scan(
                    cursor,
                    match=pattern,
                    count=100
                )

                for key in keys:
                    # Parse key: positions:index:{user_id}:{exchange}
                    parts = key.split(':')
                    if len(parts) >= 4:
                        user_id = parts[2]
                        exchange = parts[3]

                        # Check if user has positions
                        position_ids = await self.redis_client.smembers(key)
                        if position_ids:
                            await self._ensure_user_tracked(user_id, exchange)

                if cursor == 0:
                    break

        except Exception as e:
            logger.error(f"Error scanning position indices: {e}", exc_info=True)

    async def _scan_open_orders(self):
        """Scan open order keys"""
        try:
            # Pattern: orders:open:{user_id}:{exchange}
            pattern = "orders:open:*"
            cursor = 0

            while True:
                cursor, keys = await self.redis_client.scan(
                    cursor,
                    match=pattern,
                    count=100
                )

                for key in keys:
                    # Parse key: orders:open:{user_id}:{exchange}
                    parts = key.split(':')
                    if len(parts) >= 4:
                        user_id = parts[2]
                        exchange = parts[3]

                        # Check if user has open orders
                        order_ids = await self.redis_client.smembers(key)
                        if order_ids:
                            await self._ensure_user_tracked(user_id, exchange)

                if cursor == 0:
                    break

        except Exception as e:
            logger.error(f"Error scanning open orders: {e}", exc_info=True)

    async def _scan_realtime_positions(self):
        """Scan realtime position keys"""
        try:
            # Pattern: positions:realtime:{user_id}:{exchange}:{symbol}:{side}
            pattern = "positions:realtime:*"
            cursor = 0

            while True:
                cursor, keys = await self.redis_client.scan(
                    cursor,
                    match=pattern,
                    count=100
                )

                for key in keys:
                    # Parse key
                    parts = key.split(':')
                    if len(parts) >= 5:
                        user_id = parts[2]
                        exchange = parts[3]
                        symbol = parts[4]

                        await self._ensure_user_tracked(user_id, exchange, symbol)

                if cursor == 0:
                    break

        except Exception as e:
            logger.error(f"Error scanning realtime positions: {e}", exc_info=True)

    async def _ensure_user_tracked(
        self,
        user_id: str,
        exchange: str,
        symbol: str = None
    ):
        """
        Ensure user is being tracked.

        Args:
            user_id: User identifier
            exchange: Exchange identifier
            symbol: Optional symbol to track
        """
        try:
            # Check if user is already tracked
            if user_id not in self.tracked_users:
                # New user - start tracking
                await self.start_tracking_user(user_id, exchange)

            # Add symbol to tracked symbols if provided
            if symbol and user_id in self.tracked_users:
                if symbol not in self.tracked_users[user_id]["symbols"]:
                    self.tracked_users[user_id]["symbols"].add(symbol)

                    # Subscribe to position events for this symbol
                    await self.position_tracker.start_tracking(
                        user_id=user_id,
                        exchange=exchange,
                        symbols=[symbol]
                    )

        except Exception as e:
            logger.error(
                f"Error ensuring user tracked: {e}",
                exc_info=True,
                extra={"user_id": user_id, "exchange": exchange}
            )

    async def start_tracking_user(self, user_id: str, exchange: str):
        """
        Start tracking a new user.

        Args:
            user_id: User identifier
            exchange: Exchange identifier
        """
        try:
            logger.info(
                f"Starting tracking for user: {user_id} on {exchange}",
                extra={"user_id": user_id, "exchange": exchange}
            )

            # Get user's API credentials from Redis
            api_credentials = await self._get_user_api_credentials(user_id, exchange)
            if not api_credentials:
                logger.warning(f"No API credentials found for user {user_id}")
                return

            # Connect WebSocket
            connected = await self.websocket_manager.connect(
                exchange_id=exchange,
                user_id=user_id,
                api_credentials=api_credentials
            )

            if not connected:
                logger.error(f"Failed to connect WebSocket for user {user_id}")
                return

            # Get user's active symbols
            symbols = await self._get_user_active_symbols(user_id, exchange)

            # Subscribe to positions
            await self.websocket_manager.subscribe_positions(
                user_id=user_id,
                exchange_id=exchange,
                symbols=symbols
            )

            # Subscribe to orders
            await self.websocket_manager.subscribe_orders(
                user_id=user_id,
                exchange_id=exchange,
                symbols=symbols
            )

            # Start position tracking
            await self.position_tracker.start_tracking(
                user_id=user_id,
                exchange=exchange,
                symbols=symbols
            )

            # Start order tracking
            await self.order_tracker.start_tracking(
                user_id=user_id,
                exchange=exchange
            )

            # Store tracking info
            self.tracked_users[user_id] = {
                "exchange": exchange,
                "symbols": set(symbols),
                "started_at": datetime.utcnow()
            }

            logger.info(
                f"✅ User tracking started: {user_id}",
                extra={
                    "user_id": user_id,
                    "exchange": exchange,
                    "symbols": symbols
                }
            )

        except Exception as e:
            logger.error(
                f"Failed to start tracking user: {e}",
                exc_info=True,
                extra={"user_id": user_id, "exchange": exchange}
            )

    async def stop_tracking_user(self, user_id: str):
        """
        Stop tracking a user.

        Args:
            user_id: User identifier
        """
        try:
            if user_id not in self.tracked_users:
                return

            user_info = self.tracked_users[user_id]
            exchange = user_info["exchange"]

            logger.info(
                f"Stopping tracking for user: {user_id}",
                extra={"user_id": user_id}
            )

            # Stop position tracking
            for symbol in user_info["symbols"]:
                await self.position_tracker.stop_tracking(
                    user_id=user_id,
                    exchange=exchange,
                    symbol=symbol
                )

            # Stop order tracking
            await self.order_tracker.stop_tracking(
                user_id=user_id,
                exchange=exchange
            )

            # Disconnect WebSocket
            await self.websocket_manager.disconnect(
                user_id=user_id,
                exchange_id=exchange
            )

            # Remove from tracked users
            del self.tracked_users[user_id]

            logger.info(
                f"✅ User tracking stopped: {user_id}",
                extra={"user_id": user_id}
            )

        except Exception as e:
            logger.error(
                f"Failed to stop tracking user: {e}",
                exc_info=True,
                extra={"user_id": user_id}
            )

    async def _get_user_api_credentials(
        self,
        user_id: str,
        exchange: str
    ) -> Dict[str, str]:
        """
        Get user API credentials from Redis.

        Args:
            user_id: User identifier
            exchange: Exchange identifier

        Returns:
            API credentials dictionary
        """
        try:
            # Try HYPERRSI format: user:{user_id}:api:keys
            api_key_format = f"user:{user_id}:api:keys"
            api_keys = await self.redis_client.hgetall(api_key_format)

            if api_keys:
                return {
                    'api_key': api_keys.get('api_key'),
                    'api_secret': api_keys.get('api_secret'),
                    'passphrase': api_keys.get('passphrase') or api_keys.get('password')
                }

            # Try alternate format: {exchange}:user:{user_id}
            api_key_format = f"{exchange}:user:{user_id}"
            user_data = await self.redis_client.hgetall(api_key_format)

            if user_data:
                return {
                    'api_key': user_data.get('api_key'),
                    'api_secret': user_data.get('api_secret'),
                    'passphrase': user_data.get('password')
                }

            return {}

        except Exception as e:
            logger.error(
                f"Failed to get API credentials: {e}",
                exc_info=True,
                extra={"user_id": user_id}
            )
            return {}

    async def _get_user_active_symbols(
        self,
        user_id: str,
        exchange: str
    ) -> List[str]:
        """
        Get list of symbols user has active positions/orders on.

        Args:
            user_id: User identifier
            exchange: Exchange identifier

        Returns:
            List of symbols
        """
        try:
            symbols = set()

            # Scan realtime positions
            pattern = f"positions:realtime:{user_id}:{exchange}:*"
            cursor = 0

            while True:
                cursor, keys = await self.redis_client.scan(
                    cursor,
                    match=pattern,
                    count=100
                )

                for key in keys:
                    # Parse key: positions:realtime:{user_id}:{exchange}:{symbol}:{side}
                    parts = key.split(':')
                    if len(parts) >= 5:
                        symbol = parts[4]
                        symbols.add(symbol)

                if cursor == 0:
                    break

            # Scan open orders
            open_orders_key = f"orders:open:{user_id}:{exchange}"
            order_ids = await self.redis_client.smembers(open_orders_key)

            for order_id in order_ids:
                order_key = f"orders:realtime:{user_id}:{exchange}:{order_id}"
                order_data = await self.redis_client.hgetall(order_key)

                if order_data and 'symbol' in order_data:
                    symbols.add(order_data['symbol'])

            return list(symbols)

        except Exception as e:
            logger.error(
                f"Failed to get active symbols: {e}",
                exc_info=True,
                extra={"user_id": user_id}
            )
            return []
