#src/core/celery_task.py
# Auto-configure PYTHONPATH for monorepo structure
from shared.utils.path_config import configure_pythonpath

configure_pythonpath()

#실행 명령어

#celery -A HYPERRSI.src.core.celery_task worker --loglevel=INFO --concurrency=8

#celery -A HYPERRSI.src.core.celery_task worker --loglevel=WARNING --concurrency=8


#비트 사용할 필요 없음.
#celery -A HYPERRSI.src.core.celery_task beat --loglevel=WARNING
#celery -A HYPERRSI.src.core.celery_task flower --port=5555

import asyncio
import logging
import os
import signal

from celery import Celery
from celery.signals import worker_init, worker_process_init, worker_ready, worker_shutdown
from celery.utils.log import get_task_logger

from HYPERRSI.src.core.config import settings

task_logger = get_task_logger('trading_tasks.check_and_execute_trading')
task_logger.setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Redis clients are initialized lazily when first accessed

# 시그널 핸들러 함수 추가
def signal_handler(signum, frame):
    """
    시그널 수신 시 처리 핸들러
    """
    logger.warning(f"시그널 {signum} 수신: 워커를 안전하게 종료합니다.")
    # 이벤트 루프 종료 처리
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            logger.info("실행 중인 이벤트 루프를 중지합니다.")
            loop.stop()
        if not loop.is_closed():
            logger.info("이벤트 루프를 닫습니다.")
            loop.close()
    except Exception as e:
        logger.error(f"이벤트 루프 종료 중 오류: {e}")
    
    # 프로세스 종료
    if signum in (signal.SIGINT, signal.SIGTERM):
        import sys
        sys.exit(0)

def init_worker():
    """
    Celery 워커 초기화 함수

    이 함수는 각 워커 프로세스가 시작될 때 호출됩니다.
    비동기 이벤트 루프 관련 설정을 초기화합니다.
    """
    try:
        # 시그널 핸들러 등록
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # 기존 이벤트 루프 확인 및 정리
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                logger.warning("이미 실행 중인 이벤트 루프가 있습니다. 확인이 필요합니다.")
            if loop.is_closed():
                logger.info("닫힌 이벤트 루프가 감지되었습니다. 새 루프를 생성합니다.")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            # 이벤트 루프가 없는 경우 새로 생성
            logger.info("이벤트 루프가 없어 새로 생성합니다.")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # Redis clients are initialized lazily when first accessed

        logger.debug("Celery 워커 초기화 완료: 이벤트 루프 설정됨")
    except Exception as e:
        logger.error(f"Celery 워커 초기화 중 오류 발생: {str(e)}")

# 워커 프로세스 초기화 시그널 연결
@worker_process_init.connect
def setup_worker_process(**kwargs):
    """워커 프로세스 초기화 시 Redis 및 시그널 핸들러 설정"""
    logger.info("워커 프로세스 초기화: Redis 및 시그널 핸들러 설정")

    # Redis clients are initialized lazily when first accessed

    # 시그널 핸들러 설정
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

# 워커 종료 시그널 연결
@worker_shutdown.connect
def cleanup_worker(**kwargs):
    """워커 종료 시 리소스 정리"""
    logger.info("워커 종료: 리소스 정리 중")
    try:
        # 남아있는 이벤트 루프 정리
        try:
            loop = asyncio.get_event_loop()
            if not loop.is_closed():
                logger.info("이벤트 루프 종료 중")
                loop.close()
        except Exception as e:
            logger.warning(f"이벤트 루프 정리 중 오류: {e}")
    except Exception as e:
        logger.error(f"워커 종료 정리 중 오류: {e}")


# Beat 스케줄 정의
beat_schedule = {
    'check-active-traders': {
        'task': 'trading_tasks.check_and_execute_trading',
        'schedule': 5.0,  # 5초마다 실행
    },
}

# Celery 애플리케이션 설정
celery_app = Celery(
    "trading_bot",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        'HYPERRSI.src.tasks.trading_tasks',  # 트레이딩 태스크
        'HYPERRSI.src.tasks.grid_trading_tasks',  # Grid 트레이딩 태스크 추가
    ]
)
celery_app.conf.update(
    broker_connection_retry_on_startup=True,
    timezone="Asia/Seoul",
    enable_utc=True,
    result_expires=3600,
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    worker_init=init_worker,
    beat_schedule=beat_schedule,  # beat_schedule 설정 추가
    worker_prefetch_multiplier=1,
)

# 커맨드라인에서 Celery 실행 시 대기 중인 태스크 제거 옵션 추가
# 실행 명령어: celery -A src.core.celery_task worker --loglevel=INFO --concurrency=8 --purge
# --purge 옵션을 사용하면 시작 시 대기 중인 태스크를 자동으로 제거합니다.