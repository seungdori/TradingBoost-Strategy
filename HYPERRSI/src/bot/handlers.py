# src/bot/handlers.py

from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from HYPERRSI.src.bot.command import basic, trading, settings, register, generic, account, dual_side_settings
from HYPERRSI.src.config import TELEGRAM_BOT_TOKEN
import os
from HYPERRSI.src.services.redis_service import RedisService
from HYPERRSI.src.core.logger import get_logger

logger = get_logger(__name__)
redis_service = RedisService()

async def setup_bot():
    """봇 설정 및 핸들러 등록"""
    try:
        logger.info("Setting up Telegram bot...")
        
        # 봇 및 디스패처 초기화
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        dp = Dispatcher(storage=MemoryStorage())
        
        # 각 모듈의 라우터 등록
        dp.include_router(basic.router)
        dp.include_router(trading.router)
        dp.include_router(settings.router)
        dp.include_router(account.router)
        dp.include_router(register.router)
        dp.include_router(generic.router)
        dp.include_router(dual_side_settings.router)
        # 시작 메시지 전송
        if os.getenv("OWNER_ID"):
            try:
                await bot.send_message(os.getenv("OWNER_ID"), "봇이 시작되었습니다.")
            except Exception as e:
                logger.error(f"Failed to send startup message: {str(e)}")
        
        logger.info("Bot setup completed successfully")
        return bot, dp
            
    except Exception as e:
        logger.error(f"Error setting up bot: {str(e)}")
        raise

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