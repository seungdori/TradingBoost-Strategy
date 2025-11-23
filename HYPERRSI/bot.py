#bot.py
import asyncio
import logging
import os
import signal
from pathlib import Path
from typing import Optional

from aiogram import Bot
from HYPERRSI.src.bot.handlers import setup_bot, shutdown_bot
from HYPERRSI.src.services.redis_service import init_redis
from shared.logging import get_logger

# aiogram 로그 레벨을 WARNING으로 설정 (INFO 레벨의 "is not handled" 메시지 숨김)
logging.getLogger("aiogram").setLevel(logging.WARNING)

logger = get_logger(__name__)

# PID 파일 경로
PID_FILE = Path(__file__).parent / "bot.pid"

# Global variables for signal handling
bot_instance: Optional[Bot] = None
shutdown_event = asyncio.Event()


def check_and_create_pidfile():
    """PID 파일을 확인하고 중복 실행 방지"""
    if PID_FILE.exists():
        try:
            with open(PID_FILE, 'r') as f:
                old_pid = int(f.read().strip())

            # 기존 프로세스가 실행 중인지 확인
            try:
                os.kill(old_pid, 0)  # 프로세스 존재 여부만 확인
                logger.error(f"Bot is already running with PID {old_pid}")
                logger.error(f"If you're sure it's not running, remove {PID_FILE}")
                return False
            except OSError:
                # 프로세스가 없으면 오래된 PID 파일 제거
                logger.warning(f"Removing stale PID file (PID {old_pid})")
                PID_FILE.unlink()
        except (ValueError, IOError) as e:
            logger.warning(f"Invalid PID file, removing: {e}")
            PID_FILE.unlink()

    # 새 PID 파일 생성
    try:
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
        logger.info(f"Created PID file: {PID_FILE} (PID: {os.getpid()})")
        return True
    except IOError as e:
        logger.error(f"Failed to create PID file: {e}")
        return False


def remove_pidfile():
    """PID 파일 제거"""
    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
            logger.info(f"Removed PID file: {PID_FILE}")
    except Exception as e:
        logger.error(f"Failed to remove PID file: {e}")

async def main():
    global bot_instance

    # PID 파일 확인 및 생성 (중복 실행 방지)
    if not check_and_create_pidfile():
        logger.error("Cannot start bot: another instance is already running")
        return

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

        # 폴링 설정 (재시도 로직 강화)
        polling_config = {
            "allowed_updates": None,  # 모든 업데이트 수신
            "timeout": 60,            # Long polling timeout
            "handle_signals": False,  # 시그널 핸들링 직접 관리
        }

        # 폴링과 종료 이벤트를 동시에 대기
        polling_task = asyncio.create_task(
            dp.start_polling(bot, **polling_config),
            name="telegram-polling"
        )
        shutdown_task = asyncio.create_task(shutdown_event.wait(), name="shutdown-event")

        # 둘 중 하나가 완료될 때까지 대기
        done, pending = await asyncio.wait(
            {polling_task, shutdown_task},
            return_when=asyncio.FIRST_COMPLETED
        )

        # 완료된 태스크의 예외 확인
        for task in done:
            if task.exception():
                logger.error(f"Task {task.get_name()} failed: {task.exception()}", exc_info=task.exception())

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
        # PID 파일 제거
        remove_pidfile()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)