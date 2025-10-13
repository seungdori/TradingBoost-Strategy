# app.py
# Auto-configure PYTHONPATH
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import uvicorn

# Celery 실행 방법 (monorepo 절대 경로 필요):
#
# 방법 1 (권장): 스크립트 사용
# bash start_celery_worker.sh
# bash stop_celery_worker.sh
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
        "main:app",
        host="0.0.0.0",
        port=8000,  
        reload=True,
        workers=4,
   )   