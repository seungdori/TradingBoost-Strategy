"""Position/Order Management Microservice - Main Entry Point

Real-time position and order tracking microservice with WebSocket integration,
pub/sub event system, trailing stops, and conditional order management.

Usage:
    python main.py --port 8020

Features:
    - WebSocket-based real-time position/order tracking
    - Redis Pub/Sub event system
    - Trailing stop management
    - Conditional order cancellation
    - REST API for management operations
"""

import sys
from pathlib import Path

# PYTHONPATH 자동 설정
project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import asyncio
import argparse
import signal
from typing import Optional
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis
import uvicorn

from shared.logging import get_logger
from shared.config import get_settings
from shared.database import RedisConnectionManager

from core.websocket_manager import WebSocketManager
from core.pubsub_manager import PubSubManager
from managers.position_tracker import PositionTracker
from managers.order_tracker import OrderTracker
from managers.trailing_stop_manager import TrailingStopManager
from managers.conditional_cancellation import ConditionalCancellationManager
from workers.active_user_manager import ActiveUserManager
from api.routes import router, init_managers

logger = get_logger(__name__)
settings = get_settings()


class PositionOrderService:
    """Main service orchestrator"""

    def __init__(self):
        self.redis_client: Optional[Redis] = None
        self.redis_manager: Optional[RedisConnectionManager] = None
        self.db_manager = None  # PostgreSQL manager

        self.websocket_manager: Optional[WebSocketManager] = None
        self.pubsub_manager: Optional[PubSubManager] = None
        self.position_tracker: Optional[PositionTracker] = None
        self.order_tracker: Optional[OrderTracker] = None
        self.trailing_stop_manager: Optional[TrailingStopManager] = None
        self.conditional_manager: Optional[ConditionalCancellationManager] = None
        self.active_user_manager: Optional[ActiveUserManager] = None

        self.running = False

    async def start(self):
        """Initialize and start all service components"""
        try:
            logger.info("Starting Position/Order Management Service...")

            # 1. Initialize PostgreSQL (Optional)
            try:
                from database.connection import get_db_manager
                self.db_manager = await get_db_manager()
                logger.info("PostgreSQL connection initialized")
            except Exception as e:
                logger.warning(f"PostgreSQL not available - running in Redis-only mode: {e}")
                self.db_manager = None

            # 2. Initialize Redis connection
            self.redis_manager = RedisConnectionManager(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=0,
                password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None
            )
            self.redis_client = await self.redis_manager.get_connection_async(decode_responses=True)

            logger.info("Redis connection established")

            # 2. Initialize PubSub Manager
            self.pubsub_manager = PubSubManager(self.redis_client)
            await self.pubsub_manager.start()

            logger.info("PubSub manager started")

            # 3. Initialize WebSocket Manager
            self.websocket_manager = WebSocketManager(
                redis_client=self.redis_client,
                pubsub_callback=self._handle_websocket_event
            )

            logger.info("WebSocket manager initialized")

            # 4. Initialize Position Tracker
            self.position_tracker = PositionTracker(
                redis_client=self.redis_client,
                pubsub_manager=self.pubsub_manager
            )

            logger.info("Position tracker initialized")

            # 5. Initialize Order Tracker
            self.order_tracker = OrderTracker(
                redis_client=self.redis_client,
                pubsub_manager=self.pubsub_manager
            )

            logger.info("Order tracker initialized")

            # 6. Initialize Trailing Stop Manager
            self.trailing_stop_manager = TrailingStopManager(
                redis_client=self.redis_client,
                pubsub_manager=self.pubsub_manager
            )

            logger.info("Trailing stop manager initialized")

            # 7. Initialize Conditional Cancellation Manager
            self.conditional_manager = ConditionalCancellationManager(
                redis_client=self.redis_client,
                pubsub_manager=self.pubsub_manager
            )

            # Register order tracker callback for conditional rules
            self.order_tracker.register_callback(
                self.conditional_manager.check_and_execute
            )

            logger.info("Conditional cancellation manager initialized")

            # 8. Initialize Active User Manager (자동 사용자 추적!)
            self.active_user_manager = ActiveUserManager(
                redis_client=self.redis_client,
                websocket_manager=self.websocket_manager,
                position_tracker=self.position_tracker,
                order_tracker=self.order_tracker
            )

            await self.active_user_manager.start()

            logger.info("Active user manager initialized")

            # 9. Initialize API routes with managers
            init_managers(
                position_tracker=self.position_tracker,
                order_tracker=self.order_tracker,
                trailing_stop_manager=self.trailing_stop_manager,
                conditional_manager=self.conditional_manager,
                active_user_manager=self.active_user_manager
            )

            logger.info("API routes initialized")

            self.running = True
            logger.info("✅ Position/Order Management Service started successfully")

        except Exception as e:
            logger.error(f"Failed to start service: {e}", exc_info=True)
            raise

    async def stop(self):
        """Graceful shutdown of all service components"""
        try:
            logger.info("Stopping Position/Order Management Service...")

            self.running = False

            # Stop Active User Manager first
            if self.active_user_manager:
                await self.active_user_manager.stop()

            # Stop PubSub manager
            if self.pubsub_manager:
                await self.pubsub_manager.stop()

            # Cleanup WebSocket manager
            if self.websocket_manager:
                await self.websocket_manager.cleanup()

            # Close Redis connection
            if self.redis_client:
                await self.redis_client.close()

            logger.info("✅ Position/Order Management Service stopped")

        except Exception as e:
            logger.error(f"Error during service shutdown: {e}", exc_info=True)

    async def _handle_websocket_event(self, event):
        """
        Handle WebSocket events from WebSocketManager.

        Publishes events to appropriate pub/sub channels.
        """
        try:
            from .core.event_types import PositionEvent, OrderEvent

            if isinstance(event, PositionEvent):
                await self.pubsub_manager.publish_position_event(event)
            elif isinstance(event, OrderEvent):
                await self.pubsub_manager.publish_order_event(event)

        except Exception as e:
            logger.error(f"Error handling WebSocket event: {e}", exc_info=True)


# Global service instance
service: Optional[PositionOrderService] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager"""
    global service

    # Startup
    service = PositionOrderService()
    await service.start()

    yield

    # Shutdown
    if service:
        await service.stop()


# Create FastAPI app
app = FastAPI(
    title="Position/Order Management Service",
    description="Real-time position and order tracking microservice",
    version="1.0.0",
    lifespan=lifespan
)

# Include API routes
app.include_router(router)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "position-order-management",
        "timestamp": datetime.utcnow().isoformat()
    }


def signal_handler(sig, frame):
    """Handle shutdown signals"""
    logger.info(f"Received signal {sig}, initiating shutdown...")
    if service:
        asyncio.create_task(service.stop())


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Position/Order Management Service")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8020, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")

    args = parser.parse_args()

    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info(f"Starting service on {args.host}:{args.port}")

    # Run FastAPI with uvicorn
    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info"
    )


if __name__ == "__main__":
    main()
