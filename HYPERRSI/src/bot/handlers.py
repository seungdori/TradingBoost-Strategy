# src/bot/handlers.py

import os
import asyncio
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage

from HYPERRSI.src.bot.command import (
    account,
    basic,
    dual_side_settings,
    generic,
    register,
    settings,
    trading,
)
from HYPERRSI.src.config import TELEGRAM_BOT_TOKEN
from HYPERRSI.src.services.redis_service import RedisService
from shared.logging import get_logger

logger = get_logger(__name__)
redis_service = RedisService()

async def setup_bot(max_retries: int = 5, retry_delay: float = 5.0):
    """봇 설정 및 핸들러 등록 (연결 재시도 로직 포함)"""
    bot: Optional[Bot] = None

    for attempt in range(max_retries):
        try:
            logger.info(f"Setting up Telegram bot... (attempt {attempt + 1}/{max_retries})")

            # Custom session with timeout configuration
            # Use numeric timeout (in seconds) for compatibility with aiogram polling
            session = AiohttpSession(timeout=60)

            # 봇 및 디스패처 초기화
            bot = Bot(
                token=TELEGRAM_BOT_TOKEN,
                session=session,
                default=DefaultBotProperties(
                    parse_mode="HTML"
                )
            )

            # Test connection with getMe
            logger.info("Testing Telegram API connection...")
            bot_info = await asyncio.wait_for(bot.get_me(), timeout=15.0)
            logger.info(f"Successfully connected to Telegram API as @{bot_info.username}")

            dp = Dispatcher(storage=MemoryStorage())

            # 각 모듈의 라우터 등록
            dp.include_router(basic.router)
            dp.include_router(trading.router)
            dp.include_router(settings.router)
            dp.include_router(account.router)
            dp.include_router(register.router)
            dp.include_router(generic.router)
            dp.include_router(dual_side_settings.router)

            # 시작 메시지 전송 (비동기, 실패해도 계속 진행)
            if os.getenv("OWNER_ID"):
                asyncio.create_task(send_startup_message(bot, os.getenv("OWNER_ID")))

            logger.info("Bot setup completed successfully")
            return bot, dp

        except asyncio.TimeoutError:
            logger.error(f"Connection timeout on attempt {attempt + 1}/{max_retries}")
            if bot:
                await bot.session.close()
                bot = None
        except Exception as e:
            logger.error(f"Error setting up bot (attempt {attempt + 1}/{max_retries}): {str(e)}")
            if bot:
                await bot.session.close()
                bot = None

        # Wait before retry (exponential backoff)
        if attempt < max_retries - 1:
            wait_time = retry_delay * (2 ** attempt)
            logger.info(f"Waiting {wait_time:.1f} seconds before retry...")
            await asyncio.sleep(wait_time)

    # All retries failed
    raise ConnectionError(f"Failed to connect to Telegram API after {max_retries} attempts")


async def send_startup_message(bot: Bot, owner_id: str):
    """비동기로 시작 메시지 전송"""
    try:
        await bot.send_message(owner_id, "🤖 봇이 시작되었습니다.")
        logger.info("Startup message sent successfully")
    except Exception as e:
        logger.error(f"Failed to send startup message: {str(e)}")

async def shutdown_bot(bot: Bot):
    """봇 종료 처리"""
    try:
        logger.info("Shutting down Telegram bot...")
        if bot:
            await bot.session.close()
            logger.info("Telegram bot session closed")
    except Exception as e:
        logger.error(f"Error shutting down bot: {str(e)}")
        raise