import os
from celery import Celery

# Redis 연결 정보를 환경 변수에서 가져오기
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = os.getenv('REDIS_PORT', '6379')
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD')

if REDIS_PASSWORD:
    redis_url = f'redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/0'
else:
    redis_url = f'redis://{REDIS_HOST}:{REDIS_PORT}/0'

app = Celery('tasks', broker=redis_url, backend=redis_url)

app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)