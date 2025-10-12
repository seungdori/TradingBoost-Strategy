# Auto-configure PYTHONPATH for monorepo structure
from shared.utils.path_config import configure_pythonpath

configure_pythonpath()

import os

from celery import Celery

from shared.config import settings

# Celery 애플리케이션 설정
app = Celery('grid_trading',
             broker=f'redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}',
             backend=f'redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}')

# Redis 패스워드가 설정되어 있는 경우 추가
if settings.REDIS_PASSWORD:
    app.conf.broker_url = f'redis://:{settings.REDIS_PASSWORD}@{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}'
    app.conf.result_backend = f'redis://:{settings.REDIS_PASSWORD}@{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}'

# Celery 설정
app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Seoul',
    enable_utc=True,
    task_acks_late=True,
    worker_max_tasks_per_child=1,  # 작업당 워커를 재시작하여 메모리 누수 방지
    task_time_limit=None,  # 무제한 실행 시간
    result_expires=86400 * 2,  # 2일 동안 결과 저장
)

# 작업을 자동으로 가져오도록 설정
app.autodiscover_tasks(['GRID']) 