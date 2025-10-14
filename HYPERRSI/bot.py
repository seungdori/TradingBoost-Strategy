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

from HYPERRSI.src.bot.handlers import setup_bot, shutdown_bot
from HYPERRSI.src.services.redis_service import init_redis
from shared.logging import get_logger

# aiogram 로그 레벨을 WARNING으로 설정 (INFO 레벨의 "is not handled" 메시지 숨김)
logging.getLogger("aiogram").setLevel(logging.WARNING)

logger = get_logger(__name__)

async def main():
    try:
        # 초기화
        await init_redis()

        # 봇 설정
        bot, dp = await setup_bot()
        
        # 시그널 핸들러 설정
        def signal_handler(sig, frame): 
            logger.info(f"Received signal {sig}")
            asyncio.create_task(shutdown_bot(bot))
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # 봇 실행
        await dp.start_polling(bot)
        
    except Exception as e:
        logger.error(f"Error in bot main: {e}")
    finally:
        if 'bot' in locals():
            await shutdown_bot(bot)

if __name__ == "__main__":
    asyncio.run(main())