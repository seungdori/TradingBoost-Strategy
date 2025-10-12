"""Order Manager - Unified Order Management Service

Production-ready order management service for cryptocurrency trading.
Supports HYPERRSI and GRID strategies with exchange-agnostic design.

Features:
- Multi-exchange support (OKX, Binance, Upbit, Bitget, Bybit)
- Redis caching for real-time order tracking
- Order lifecycle management (pending → open → filled/cancelled)
- Retry logic for failed orders
- Order fill monitoring with WebSocket
- Support for all order types (market, limit, stop, trigger, etc.)

Usage:
    from shared.services.order_manager import OrderManager

    manager = OrderManager()

    # Create market order
    order = await manager.create_order(
        user_id="user123",
        exchange="okx",
        symbol="BTC-USDT-SWAP",
        side="buy",
        order_type="market",
        quantity=Decimal("0.1")
    )

    # Cancel order
    success = await manager.cancel_order(order_id=order.id)

    # Monitor order fills
    async for updated_order in manager.monitor_order_fills(order_id=order.id):
        print(f"Order status: {updated_order.status}, Filled: {updated_order.filled_qty}")
"""

import asyncio
import json
from datetime import datetime
from decimal import Decimal
from typing import Any, AsyncGenerator, Dict, List, Optional
from uuid import UUID

import ccxt.async_support as ccxt
from redis.asyncio import Redis

from shared.config import get_settings
from shared.database import RedisConnectionManager
from shared.database.redis_schemas import RedisKeys, RedisSerializer
from shared.logging import get_logger
from shared.models.trading import Exchange, Order, OrderSide, OrderStatus, OrderType, TradeFee
from shared.utils.retry import retry_async

logger = get_logger(__name__)
settings = get_settings()


class OrderManager:
    """Unified Order Manager for all trading strategies

    Manages order lifecycle from creation to execution/cancellation across multiple exchanges.
    Provides Redis caching for real-time queries and order fill monitoring.
    """

    def __init__(self):
        """Initialize Order Manager with Redis connection"""
        self._redis_manager = RedisConnectionManager(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=0,
            password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None
        )

    async def _get_redis(self) -> Redis:
        """Get Redis connection with decode_responses=True"""
        return await self._redis_manager.get_connection_async(decode_responses=True)

    async def _get_user_api_keys(self, user_id: str) -> Dict[str, str]:
        """Get user API keys from Redis

        Args:
            user_id: User identifier (OKX UID or Telegram ID)

        Returns:
            Dict with api_key, api_secret, passphrase

        Raises:
            ValueError: If API keys not found
        """
        redis = await self._get_redis()
        try:
            # Support both formats
            api_key_format = f"user:{user_id}:api:keys"
            api_keys_raw = await redis.hgetall(api_key_format)

            if not api_keys_raw:
                # Try alternate format
                api_key_format = f"okx:user:{user_id}"
                user_data = await redis.hgetall(api_key_format)
                if user_data:
                    api_keys_raw = {
                        'api_key': user_data.get('api_key'),
                        'api_secret': user_data.get('api_secret'),
                        'passphrase': user_data.get('password')
                    }

            if not api_keys_raw:
                raise ValueError(f"API keys not found for user {user_id}")

            return {
                'api_key': api_keys_raw.get('api_key'),
                'api_secret': api_keys_raw.get('api_secret'),
                'passphrase': api_keys_raw.get('passphrase') or api_keys_raw.get('password')
            }
        finally:
            pass

    async def _create_exchange_client(self, user_id: str, exchange: str) -> ccxt.Exchange:
        """Create CCXT exchange client

        Args:
            user_id: User identifier
            exchange: Exchange name (okx, binance, etc.)

        Returns:
            Initialized CCXT exchange client
        """
        api_keys = await self._get_user_api_keys(user_id)

        exchange_class = getattr(ccxt, exchange.lower())
        client = exchange_class({
            'apiKey': api_keys['api_key'],
            'secret': api_keys['api_secret'],
            'password': api_keys.get('passphrase'),
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })

        await client.load_markets()
        return client

    @retry_async(max_attempts=3, delay=1.0, backoff=2.0)
    async def create_order(
        self,
        user_id: str,
        exchange: str,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Optional[Decimal] = None,
        trigger_price: Optional[Decimal] = None,
        reduce_only: bool = False,
        post_only: bool = False,
        time_in_force: str = "GTC",
        grid_level: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Order:
        """Create a new order

        Args:
            user_id: User identifier
            exchange: Exchange name
            symbol: Trading symbol
            side: Order side ('buy' or 'sell')
            order_type: Order type ('market', 'limit', 'stop_market', 'stop_limit', 'trigger')
            quantity: Order quantity
            price: Limit price (required for limit orders)
            trigger_price: Trigger price (for stop/trigger orders)
            reduce_only: Reduce-only flag (position closing only)
            post_only: Post-only flag (maker-only)
            time_in_force: Time in force (GTC, IOC, FOK)
            grid_level: Grid level for GRID strategy (optional)
            metadata: Additional metadata (optional)

        Returns:
            Created Order object

        Raises:
            ValueError: Invalid parameters
            Exception: Exchange API or Redis errors
        """
        logger.info(
            f"Creating order for user {user_id}: {symbol} {side} {quantity} {order_type}",
            extra={"user_id": user_id, "symbol": symbol, "side": side, "order_type": order_type}
        )

        # Validate parameters
        if side not in ('buy', 'sell'):
            raise ValueError(f"Invalid side: {side}. Must be 'buy' or 'sell'")

        if quantity <= 0:
            raise ValueError(f"Invalid quantity: {quantity}. Must be positive")

        if order_type in ('limit', 'stop_limit') and not price:
            raise ValueError(f"Price required for {order_type} orders")

        if order_type in ('stop_market', 'stop_limit', 'trigger') and not trigger_price:
            raise ValueError(f"Trigger price required for {order_type} orders")

        # Create exchange client
        client = None
        try:
            client = await self._create_exchange_client(user_id, exchange)

            # Prepare order parameters
            params = {
                'reduceOnly': reduce_only,
                'postOnly': post_only,
                'timeInForce': time_in_force
            }

            # Place order based on type
            exchange_order = None

            if order_type == 'market':
                exchange_order = await client.create_market_order(
                    symbol=symbol,
                    side=side,
                    amount=float(quantity),
                    params=params
                )
            elif order_type == 'limit':
                exchange_order = await client.create_limit_order(
                    symbol=symbol,
                    side=side,
                    amount=float(quantity),
                    price=float(price),
                    params=params
                )
            elif order_type == 'stop_market':
                params['stopPrice'] = float(trigger_price)
                exchange_order = await client.create_order(
                    symbol=symbol,
                    type='stop_market',
                    side=side,
                    amount=float(quantity),
                    params=params
                )
            elif order_type == 'stop_limit':
                params['stopPrice'] = float(trigger_price)
                exchange_order = await client.create_order(
                    symbol=symbol,
                    type='stop_limit',
                    side=side,
                    amount=float(quantity),
                    price=float(price),
                    params=params
                )
            elif order_type == 'trigger':
                # OKX algo order
                params['triggerPrice'] = float(trigger_price)
                params['algoType'] = 'trigger'
                exchange_order = await client.private_post_trade_order_algo({
                    'instId': symbol,
                    'tdMode': 'cross',
                    'side': side,
                    'ordType': 'trigger',
                    'sz': str(quantity),
                    'triggerPx': str(trigger_price),
                    **params
                })

            # Create Order object
            order = Order(
                user_id=user_id,
                exchange=Exchange(exchange),
                exchange_order_id=exchange_order.get('id') or exchange_order.get('algoId'),
                symbol=symbol,
                side=OrderSide(side),
                order_type=OrderType(order_type),
                quantity=quantity,
                price=price,
                trigger_price=trigger_price,
                filled_qty=Decimal(str(exchange_order.get('filled', 0))),
                avg_fill_price=Decimal(str(exchange_order.get('average', 0))) if exchange_order.get('average') else None,
                status=OrderStatus.OPEN if exchange_order.get('status') == 'open' else OrderStatus.FILLED,
                reduce_only=reduce_only,
                post_only=post_only,
                time_in_force=time_in_force,
                grid_level=grid_level,
                metadata=metadata or {},
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )

            # Save to Redis
            redis = await self._get_redis()
            order_key = RedisKeys.order(str(order.id))
            order_data = RedisSerializer.order_to_dict(order)
            await redis.hset(order_key, mapping=order_data)

            # Update user order index
            user_index_key = RedisKeys.order_index(user_id, exchange)
            await redis.sadd(user_index_key, str(order.id))

            # Update open orders set
            if order.status in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED):
                open_orders_key = RedisKeys.order_open(exchange, symbol)
                await redis.sadd(open_orders_key, str(order.id))

            logger.info(
                f"Order created successfully: {order.id}",
                extra={"order_id": str(order.id), "exchange_order_id": order.exchange_order_id}
            )

            return order

        except Exception as e:
            logger.error(
                f"Failed to create order for user {user_id}: {e}",
                exc_info=True,
                extra={"user_id": user_id, "symbol": symbol, "side": side}
            )
            raise

        finally:
            if client:
                await client.close()

    async def cancel_order(
        self,
        user_id: str,
        exchange: str,
        symbol: str,
        order_id: UUID,
        order_type: Optional[str] = None
    ) -> bool:
        """Cancel an existing order

        Args:
            user_id: User identifier
            exchange: Exchange name
            symbol: Trading symbol
            order_id: Internal order ID
            order_type: Order type (for algo order cancellation)

        Returns:
            True if successful, False otherwise
        """
        logger.info(
            f"Cancelling order {order_id} for user {user_id}",
            extra={"user_id": user_id, "order_id": str(order_id)}
        )

        redis = await self._get_redis()
        client = None

        try:
            # Get order from Redis
            order_key = RedisKeys.order(str(order_id))
            order_data = await redis.hgetall(order_key)

            if not order_data:
                logger.warning(f"Order not found: {order_id}")
                return False

            order = RedisSerializer.dict_to_order(order_data)

            # Create exchange client
            client = await self._create_exchange_client(user_id, exchange)

            # Cancel order
            is_algo_order = order_type in ('stop_loss', 'trigger', 'conditional', 'stopLoss')

            if is_algo_order:
                # OKX algo order cancellation
                await client.private_post_trade_cancel_algos({
                    "algoId": [order.exchange_order_id],
                    "instId": symbol
                })
            else:
                # Standard order cancellation
                await client.cancel_order(order.exchange_order_id, symbol)

            # Update order status
            order.status = OrderStatus.CANCELLED
            order.updated_at = datetime.utcnow()

            # Save to Redis
            order_data = RedisSerializer.order_to_dict(order)
            await redis.hset(order_key, mapping=order_data)

            # Remove from open orders
            open_orders_key = RedisKeys.order_open(exchange, symbol)
            await redis.srem(open_orders_key, str(order.id))

            logger.info(f"Order cancelled successfully: {order_id}")

            return True

        except Exception as e:
            logger.error(
                f"Failed to cancel order {order_id}: {e}",
                exc_info=True,
                extra={"user_id": user_id, "order_id": str(order_id)}
            )
            return False

        finally:
            if client:
                await client.close()

    async def get_order(
        self,
        order_id: UUID
    ) -> Optional[Order]:
        """Get order by ID

        Args:
            order_id: Order UUID

        Returns:
            Order object or None if not found
        """
        redis = await self._get_redis()

        try:
            order_key = RedisKeys.order(str(order_id))
            order_data = await redis.hgetall(order_key)

            if not order_data:
                return None

            return RedisSerializer.dict_to_order(order_data)

        except Exception as e:
            logger.error(f"Failed to get order {order_id}: {e}", exc_info=True)
            raise

    async def get_open_orders(
        self,
        user_id: str,
        exchange: str,
        symbol: Optional[str] = None
    ) -> List[Order]:
        """Get open orders

        Args:
            user_id: User identifier
            exchange: Exchange name
            symbol: Trading symbol (optional, filters by symbol)

        Returns:
            List of open Order objects
        """
        redis = await self._get_redis()
        orders = []

        try:
            if symbol:
                # Get orders for specific symbol
                open_orders_key = RedisKeys.order_open(exchange, symbol)
                order_ids = await redis.smembers(open_orders_key)

                for order_id in order_ids:
                    order_key = RedisKeys.order(order_id)
                    order_data = await redis.hgetall(order_key)

                    if order_data:
                        order = RedisSerializer.dict_to_order(order_data)
                        if order.user_id == user_id:
                            orders.append(order)
            else:
                # Get all open orders for user
                user_index_key = RedisKeys.order_index(user_id, exchange)
                order_ids = await redis.smembers(user_index_key)

                for order_id in order_ids:
                    order_key = RedisKeys.order(order_id)
                    order_data = await redis.hgetall(order_key)

                    if order_data:
                        order = RedisSerializer.dict_to_order(order_data)
                        if order.is_active:
                            orders.append(order)

            return orders

        except Exception as e:
            logger.error(f"Failed to get open orders for user {user_id}: {e}", exc_info=True)
            raise

    async def update_order_status(
        self,
        order_id: UUID,
        status: OrderStatus,
        filled_qty: Decimal,
        avg_fill_price: Optional[Decimal] = None
    ) -> Optional[Order]:
        """Update order status and fill information

        Args:
            order_id: Order UUID
            status: New order status
            filled_qty: Filled quantity
            avg_fill_price: Average fill price (optional)

        Returns:
            Updated Order object or None if not found
        """
        redis = await self._get_redis()

        try:
            order_key = RedisKeys.order(str(order_id))
            order_data = await redis.hgetall(order_key)

            if not order_data:
                return None

            order = RedisSerializer.dict_to_order(order_data)

            # Update order
            order.status = status
            order.filled_qty = filled_qty
            if avg_fill_price:
                order.avg_fill_price = avg_fill_price
            order.updated_at = datetime.utcnow()

            if status == OrderStatus.FILLED:
                order.filled_at = datetime.utcnow()

            # Save to Redis
            order_data = RedisSerializer.order_to_dict(order)
            await redis.hset(order_key, mapping=order_data)

            # Update open orders set
            if status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED):
                open_orders_key = RedisKeys.order_open(order.exchange.value, order.symbol)
                await redis.srem(open_orders_key, str(order.id))

            return order

        except Exception as e:
            logger.error(f"Failed to update order status for {order_id}: {e}", exc_info=True)
            raise

    async def monitor_order_fills(
        self,
        order_id: UUID,
        user_id: str,
        exchange: str,
        symbol: str,
        poll_interval: float = 1.0,
        timeout: float = 60.0
    ) -> AsyncGenerator[Order, None]:
        """Monitor order fills in real-time

        Args:
            order_id: Order UUID
            user_id: User identifier
            exchange: Exchange name
            symbol: Trading symbol
            poll_interval: Poll interval in seconds
            timeout: Timeout in seconds

        Yields:
            Updated Order objects as fills occur
        """
        logger.info(f"Monitoring fills for order {order_id}")

        client = None
        start_time = datetime.utcnow()

        try:
            client = await self._create_exchange_client(user_id, exchange)

            # Get order from Redis
            order = await self.get_order(order_id)
            if not order:
                logger.error(f"Order not found: {order_id}")
                return

            while True:
                # Check timeout
                elapsed = (datetime.utcnow() - start_time).total_seconds()
                if elapsed > timeout:
                    logger.info(f"Order monitoring timeout for {order_id}")
                    break

                # Fetch order from exchange
                try:
                    exchange_order = await client.fetch_order(order.exchange_order_id, symbol)

                    # Update order status
                    new_status = OrderStatus.OPEN
                    if exchange_order['status'] == 'closed':
                        new_status = OrderStatus.FILLED
                    elif exchange_order['status'] == 'canceled':
                        new_status = OrderStatus.CANCELLED

                    filled_qty = Decimal(str(exchange_order['filled']))
                    avg_fill_price = Decimal(str(exchange_order['average'])) if exchange_order.get('average') else None

                    # Update if changed
                    if (new_status != order.status or
                            filled_qty != order.filled_qty or
                            avg_fill_price != order.avg_fill_price):

                        order = await self.update_order_status(
                            order_id=order_id,
                            status=new_status,
                            filled_qty=filled_qty,
                            avg_fill_price=avg_fill_price
                        )

                        if order:
                            yield order

                        # Stop monitoring if order is filled or cancelled
                        if new_status in (OrderStatus.FILLED, OrderStatus.CANCELLED):
                            break

                except Exception as e:
                    logger.error(f"Error fetching order {order_id}: {e}")

                await asyncio.sleep(poll_interval)

        finally:
            if client:
                await client.close()
