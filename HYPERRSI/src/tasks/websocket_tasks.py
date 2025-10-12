
# src/tasks/websocket_tasks.py

import asyncio
import logging

from HYPERRSI.src.services.websocket_service import OKXWebsocketManager

logger = logging.getLogger(__name__)
ws_manager = OKXWebsocketManager()

async def start_websocket_service():
    """웹소켓 서비스 시작"""
    try:
        logger.info("Starting OKX websocket service...")
        await ws_manager.start()
    except Exception as e:
        logger.error(f"Error starting websocket service: {e}")

async def stop_websocket_service():
    """웹소켓 서비스 중지"""
    try:
        logger.info("Stopping OKX websocket service...")
        await ws_manager.stop()
    except Exception as e:
        logger.error(f"Error stopping websocket service: {e}")

