#bot.py
# Auto-configure PYTHONPATH
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import asyncio
import logging
import signal
from typing import Optional

from aiogram import Bot
from HYPERRSI.src.bot.handlers import setup_bot, shutdown_bot
from HYPERRSI.src.services.redis_service import init_redis
from shared.logging import get_logger

# aiogram 로그 레벨을 WARNING으로 설정 (INFO 레벨의 "is not handled" 메시지 숨김)
logging.getLogger("aiogram").setLevel(logging.WARNING)

logger = get_logger(__name__)

# Global variables for signal handling
bot_instance: Optional[Bot] = None
shutdown_event = asyncio.Event()

async def main():
    global bot_instance

    try:
        logger.info("Starting Telegram bot application...")

        # 초기화
        await init_redis()
        logger.info("Redis initialized successfully")

        # 봇 설정 (재시도 로직 포함)
        bot, dp = await setup_bot(max_retries=5, retry_delay=5.0)
        bot_instance = bot

        # 시그널 핸들러 설정
        def signal_handler(sig, _frame):
            logger.info(f"Received signal {sig}, initiating graceful shutdown...")
            shutdown_event.set()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        logger.info("Starting polling loop...")

        # 폴링과 종료 이벤트를 동시에 대기
        polling_task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
        shutdown_task = asyncio.create_task(shutdown_event.wait())

        # 둘 중 하나가 완료될 때까지 대기
        _done, pending = await asyncio.wait(
            {polling_task, shutdown_task},
            return_when=asyncio.FIRST_COMPLETED
        )

        # 남은 태스크 취소
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        logger.info("Polling stopped")

    except ConnectionError as e:
        logger.error(f"Failed to connect to Telegram API: {e}")
        logger.error("Please check your internet connection and try again later")
    except Exception as e:
        logger.error(f"Error in bot main: {e}", exc_info=True)
    finally:
        if bot_instance:
            logger.info("Shutting down bot...")
            await shutdown_bot(bot_instance)
            logger.info("Bot shutdown complete")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)