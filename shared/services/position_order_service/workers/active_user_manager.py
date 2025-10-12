"""Active User Manager - Bot-Enabled User Tracking

Tracks users who have enabled the trading bot, regardless of current positions.
Ensures continuous monitoring for all active bot users to detect new positions.
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


class ActiveUserManager:
    """
    Manages tracking for all bot-enabled users.

    Key Concept:
    - "Active user" = user who has enabled the bot
    - NOT based on current positions
    - Monitors continuously for new positions/orders

    Redis Schema:
    - active_users:{service} → Set of active user IDs
    - user:{user_id}:bot:status → "enabled" | "disabled"
    - user:{user_id}:bot:exchanges → Set of exchanges to monitor
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

        # Tracked users: {user_id: {"exchanges": [str], "symbols": Set[str], ...}}
        self.tracked_users: Dict[str, Dict[str, Any]] = {}

        # Worker tasks
        self.worker_task: asyncio.Task = None
        self.symbol_discovery_task: asyncio.Task = None
        self.running = False

        # Scan intervals
        self.user_scan_interval = 300.0  # 5분마다 새 사용자 체크
        self.symbol_discovery_interval = 60.0  # 1분마다 새 심볼 체크

    async def start(self):
        """Start active user management"""
        try:
            logger.info("Starting Active User Manager...")

            # Initial load of active users
            await self.load_active_users()

            # Start background workers
            self.running = True
            self.worker_task = asyncio.create_task(self._user_scan_loop())
            self.symbol_discovery_task = asyncio.create_task(self._symbol_discovery_loop())

            logger.info(
                f"✅ Active User Manager started: {len(self.tracked_users)} users",
                extra={"tracked_users": list(self.tracked_users.keys())}
            )

        except Exception as e:
            logger.error(f"Failed to start Active User Manager: {e}", exc_info=True)
            raise

    async def stop(self):
        """Stop user management"""
        try:
            logger.info("Stopping Active User Manager...")

            self.running = False

            # Cancel workers
            if self.worker_task:
                self.worker_task.cancel()
            if self.symbol_discovery_task:
                self.symbol_discovery_task.cancel()

            try:
                if self.worker_task:
                    await self.worker_task
                if self.symbol_discovery_task:
                    await self.symbol_discovery_task
            except asyncio.CancelledError:
                pass

            # Stop tracking all users
            for user_id in list(self.tracked_users.keys()):
                await self.stop_tracking_user(user_id)

            logger.info("✅ Active User Manager stopped")

        except Exception as e:
            logger.error(f"Error stopping Active User Manager: {e}", exc_info=True)

    async def load_active_users(self):
        """
        Load all bot-enabled users from Redis.

        Checks multiple sources:
        1. active_users:position_order_service (explicit list)
        2. user:{user_id}:bot:status = "enabled"
        3. HYPERRSI/GRID bot status keys
        """
        try:
            logger.info("Loading active users from Redis...")

            active_users = set()

            # Method 1: Explicit active users set
            users_from_set = await self.redis_client.smembers("active_users:position_order_service")
            active_users.update(users_from_set)

            # Method 2: Scan for bot:status keys
            pattern = "user:*:bot:status"
            cursor = 0

            while True:
                cursor, keys = await self.redis_client.scan(
                    cursor,
                    match=pattern,
                    count=100
                )

                for key in keys:
                    status = await self.redis_client.get(key)
                    if status == "enabled":
                        # Extract user_id from key: user:{user_id}:bot:status
                        parts = key.split(':')
                        if len(parts) >= 3:
                            user_id = parts[1]
                            active_users.add(user_id)

                if cursor == 0:
                    break

            # Method 3: HYPERRSI bot status (compatibility)
            # Pattern: user:{user_id}:settings (check bot_enabled field)
            pattern = "user:*:settings"
            cursor = 0

            while True:
                cursor, keys = await self.redis_client.scan(
                    cursor,
                    match=pattern,
                    count=100
                )

                for key in keys:
                    settings_data = await self.redis_client.hgetall(key)
                    if settings_data.get('bot_enabled') == 'true':
                        # Extract user_id
                        parts = key.split(':')
                        if len(parts) >= 2:
                            user_id = parts[1]
                            active_users.add(user_id)

                if cursor == 0:
                    break

            # Method 4: GRID bot status
            # Pattern: {exchange}:user:{user_id} (check if has API keys)
            for exchange in ['okx', 'binance', 'upbit', 'bitget', 'bybit']:
                pattern = f"{exchange}:user:*"
                cursor = 0

                while True:
                    cursor, keys = await self.redis_client.scan(
                        cursor,
                        match=pattern,
                        count=100
                    )

                    for key in keys:
                        user_data = await self.redis_client.hgetall(key)
                        if user_data.get('api_key'):
                            # Extract user_id
                            parts = key.split(':')
                            if len(parts) >= 3:
                                user_id = parts[2]
                                active_users.add(user_id)

                    if cursor == 0:
                        break

            # Start tracking all active users
            for user_id in active_users:
                await self.add_active_user(user_id)

            logger.info(
                f"Loaded {len(active_users)} active users",
                extra={"users": list(active_users)}
            )

        except Exception as e:
            logger.error(f"Failed to load active users: {e}", exc_info=True)

    async def add_active_user(self, user_id: str, exchanges: List[str] = None):
        """
        Add a bot-enabled user for tracking.

        Args:
            user_id: User identifier
            exchanges: List of exchanges to monitor (default: auto-detect)
        """
        try:
            if user_id in self.tracked_users:
                logger.debug(f"User {user_id} already tracked")
                return

            # Auto-detect exchanges if not provided
            if not exchanges:
                exchanges = await self._detect_user_exchanges(user_id)

            if not exchanges:
                logger.warning(f"No exchanges found for user {user_id}")
                return

            logger.info(
                f"Adding active user: {user_id}",
                extra={"user_id": user_id, "exchanges": exchanges}
            )

            # Start tracking on all exchanges
            for exchange in exchanges:
                await self._start_tracking_exchange(user_id, exchange)

            # Store in Redis
            await self.redis_client.sadd("active_users:position_order_service", user_id)

            logger.info(
                f"✅ Active user added: {user_id}",
                extra={"user_id": user_id, "exchanges": exchanges}
            )

        except Exception as e:
            logger.error(
                f"Failed to add active user: {e}",
                exc_info=True,
                extra={"user_id": user_id}
            )

    async def remove_active_user(self, user_id: str):
        """
        Remove a user from tracking (bot disabled).

        Args:
            user_id: User identifier
        """
        try:
            if user_id not in self.tracked_users:
                return

            logger.info(f"Removing active user: {user_id}")

            await self.stop_tracking_user(user_id)

            # Remove from Redis
            await self.redis_client.srem("active_users:position_order_service", user_id)

            logger.info(f"✅ Active user removed: {user_id}")

        except Exception as e:
            logger.error(f"Failed to remove active user: {e}", exc_info=True)

    async def _start_tracking_exchange(self, user_id: str, exchange: str):
        """
        Start tracking user on specific exchange.

        Args:
            user_id: User identifier
            exchange: Exchange identifier
        """
        try:
            # Get API credentials
            api_credentials = await self._get_user_api_credentials(user_id, exchange)
            if not api_credentials:
                logger.warning(
                    f"No API credentials for user {user_id} on {exchange}",
                    extra={"user_id": user_id, "exchange": exchange}
                )
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

            # Get initial symbols (from existing positions/orders)
            symbols = await self._get_user_symbols(user_id, exchange)

            # Subscribe to positions and orders
            # Use wildcard or "all" to monitor ALL symbols
            if not symbols:
                # No existing positions - subscribe to common symbols or use watchlist
                symbols = await self._get_user_watchlist(user_id, exchange)

            if symbols:
                await self.websocket_manager.subscribe_positions(
                    user_id=user_id,
                    exchange_id=exchange,
                    symbols=symbols
                )

                await self.websocket_manager.subscribe_orders(
                    user_id=user_id,
                    exchange_id=exchange,
                    symbols=symbols
                )

                await self.position_tracker.start_tracking(
                    user_id=user_id,
                    exchange=exchange,
                    symbols=symbols
                )

            # Always start order tracking (symbol-independent)
            await self.order_tracker.start_tracking(
                user_id=user_id,
                exchange=exchange
            )

            # Store tracking info
            if user_id not in self.tracked_users:
                self.tracked_users[user_id] = {
                    "exchanges": [],
                    "symbols": {},
                    "started_at": datetime.utcnow()
                }

            self.tracked_users[user_id]["exchanges"].append(exchange)
            self.tracked_users[user_id]["symbols"][exchange] = set(symbols)

            logger.info(
                f"Tracking started: {user_id} on {exchange}",
                extra={"user_id": user_id, "exchange": exchange, "symbols": symbols}
            )

        except Exception as e:
            logger.error(
                f"Failed to start tracking exchange: {e}",
                exc_info=True,
                extra={"user_id": user_id, "exchange": exchange}
            )

    async def stop_tracking_user(self, user_id: str):
        """Stop tracking user on all exchanges"""
        try:
            if user_id not in self.tracked_users:
                return

            user_info = self.tracked_users[user_id]

            for exchange in user_info["exchanges"]:
                # Stop trackers
                symbols = user_info["symbols"].get(exchange, [])
                for symbol in symbols:
                    await self.position_tracker.stop_tracking(
                        user_id=user_id,
                        exchange=exchange,
                        symbol=symbol
                    )

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

            logger.info(f"Stopped tracking user: {user_id}")

        except Exception as e:
            logger.error(f"Failed to stop tracking user: {e}", exc_info=True)

    async def _user_scan_loop(self):
        """Background loop to check for new active users"""
        logger.info("User scan loop started")

        try:
            while self.running:
                await asyncio.sleep(self.user_scan_interval)
                await self.load_active_users()

        except asyncio.CancelledError:
            logger.info("User scan loop cancelled")
        except Exception as e:
            logger.error(f"User scan loop error: {e}", exc_info=True)

    async def _symbol_discovery_loop(self):
        """Background loop to discover new symbols for tracked users"""
        logger.info("Symbol discovery loop started")

        try:
            while self.running:
                await asyncio.sleep(self.symbol_discovery_interval)

                for user_id, user_info in list(self.tracked_users.items()):
                    for exchange in user_info["exchanges"]:
                        # Get current symbols
                        current_symbols = user_info["symbols"].get(exchange, set())

                        # Discover new symbols
                        all_symbols = await self._get_user_symbols(user_id, exchange)
                        new_symbols = set(all_symbols) - current_symbols

                        if new_symbols:
                            logger.info(
                                f"New symbols discovered for {user_id}: {new_symbols}",
                                extra={"user_id": user_id, "symbols": list(new_symbols)}
                            )

                            # Subscribe to new symbols
                            await self.websocket_manager.subscribe_positions(
                                user_id=user_id,
                                exchange_id=exchange,
                                symbols=list(new_symbols)
                            )

                            await self.position_tracker.start_tracking(
                                user_id=user_id,
                                exchange=exchange,
                                symbols=list(new_symbols)
                            )

                            # Update tracked symbols
                            user_info["symbols"][exchange].update(new_symbols)

        except asyncio.CancelledError:
            logger.info("Symbol discovery loop cancelled")
        except Exception as e:
            logger.error(f"Symbol discovery loop error: {e}", exc_info=True)

    async def _detect_user_exchanges(self, user_id: str) -> List[str]:
        """Detect which exchanges user has API keys for"""
        exchanges = []

        for exchange in ['okx', 'binance', 'upbit', 'bitget', 'bybit']:
            # Check for API keys
            key1 = f"user:{user_id}:api:keys"
            key2 = f"{exchange}:user:{user_id}"

            data1 = await self.redis_client.hgetall(key1)
            data2 = await self.redis_client.hgetall(key2)

            if data1.get('api_key') or data2.get('api_key'):
                exchanges.append(exchange)

        return exchanges

    async def _get_user_api_credentials(self, user_id: str, exchange: str) -> Dict[str, str]:
        """Get user API credentials"""
        # Try format 1
        key = f"user:{user_id}:api:keys"
        data = await self.redis_client.hgetall(key)

        if data.get('api_key'):
            return {
                'api_key': data.get('api_key'),
                'api_secret': data.get('api_secret'),
                'passphrase': data.get('passphrase') or data.get('password')
            }

        # Try format 2
        key = f"{exchange}:user:{user_id}"
        data = await self.redis_client.hgetall(key)

        if data.get('api_key'):
            return {
                'api_key': data.get('api_key'),
                'api_secret': data.get('api_secret'),
                'passphrase': data.get('password')
            }

        return {}

    async def _get_user_symbols(self, user_id: str, exchange: str) -> List[str]:
        """Get symbols from existing positions/orders"""
        symbols = set()

        # From positions
        pattern = f"positions:realtime:{user_id}:{exchange}:*"
        cursor = 0

        while True:
            cursor, keys = await self.redis_client.scan(cursor, match=pattern, count=100)

            for key in keys:
                parts = key.split(':')
                if len(parts) >= 5:
                    symbols.add(parts[4])

            if cursor == 0:
                break

        # From orders
        open_orders_key = f"orders:open:{user_id}:{exchange}"
        order_ids = await self.redis_client.smembers(open_orders_key)

        for order_id in order_ids:
            order_key = f"orders:realtime:{user_id}:{exchange}:{order_id}"
            order_data = await self.redis_client.hgetall(order_key)

            if order_data.get('symbol'):
                symbols.add(order_data['symbol'])

        return list(symbols)

    async def _get_user_watchlist(self, user_id: str, exchange: str) -> List[str]:
        """Get user's symbol watchlist"""
        try:
            # Check Redis for watchlist
            watchlist_key = f"user:{user_id}:watchlist:{exchange}"
            symbols = await self.redis_client.smembers(watchlist_key)

            if symbols:
                return list(symbols)

            # Default watchlist if none configured
            return ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]

        except Exception as e:
            logger.error(f"Failed to get watchlist: {e}", exc_info=True)
            return ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
