# app.py
# Auto-configure PYTHONPATH
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import os

import uvicorn

#celery -A src.core.celery_task worker --loglevel=INFO --concurrency=8 --purge
#celery -A src.core.celery_task beat --loglevel=WARNING
#celery -A src.core.celery_task flower --port=5555
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