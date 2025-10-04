# app.py
import uvicorn
import os

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