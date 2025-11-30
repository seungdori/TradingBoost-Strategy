# app.py
import uvicorn
#실행해야하는 것 -> start_celery worker,app.py, bot.py, position_monitor.py, integrated_data_collector.py, HYPERRSI.src.trading.monitoring.core

# Celery 실행 방법 (monorepo 절대 경로 필요):
#
# 방법 1 (권장): 스크립트 사용
# bash start_celery_worker.sh
# bash stop_celery_worker.sh

# 모니터링 루프(core.py) 실행 (패키지 모드, 별도 프로세스로 상시 구동)
# python -m HYPERRSI.src.trading.monitoring.core
#
# 방법 2: 직접 실행 (프로젝트 루트에서)
# celery -A HYPERRSI.src.core.celery_task worker --loglevel=INFO --concurrency=4 --purge
# celery -A HYPERRSI.src.core.celery_task beat --loglevel=WARNING
# celery -A HYPERRSI.src.core.celery_task flower --port=5555
#
#
# python -m arq src.trading.arq_config.WorkerSettings
if __name__ == "__main__":
    uvicorn.run(
        "HYPERRSI.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # reload + workers 조합은 문제 발생 가능
        workers=4,     # 테스트를 위해 단일 워커로 변경
    )
