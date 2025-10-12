# Auto-configure PYTHONPATH for monorepo structure
from shared.utils.path_config import configure_pythonpath

configure_pythonpath()

import argparse
import multiprocessing
import os
import platform
import signal
import sys

import uvicorn
from starlette.middleware.cors import CORSMiddleware

from GRID.api.app import app  # FastAPI 앱 임포트
from GRID.jobs.worker_manager import setup_workers, stop_workers
from GRID.strategies.grid_process import setup_redis


def configure_cors():
    # CORS 미들웨어 설정
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "https://localhost:3000",
            "http://0.0.0.0:3000",
            "https://0.0.0.0:3000",
            "https://tradingboostdemo.com",
            # 프로덕션 도메인도 추가
            "http://158.247.206.127:3000",
            "https://158.247.206.127:3000",
            # 필요한 다른 도메인들 추가
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

def configure_multiprocessing():
    if platform.system() == 'Darwin':  # macOS
        try:
            multiprocessing.set_start_method('spawn', force=True)
        except RuntimeError:
            pass
    elif platform.system() == 'Windows':  # Windows
        try:
            multiprocessing.set_start_method('spawn', force=True)
        except RuntimeError:
            pass
    else:  # Linux 및 기타 시스템
        try:
            multiprocessing.set_start_method('fork', force=True)
        except RuntimeError:
            pass


def signal_handler(signum, frame):
    print('Graceful shutdown initiated')
    stop_workers()
    sys.exit(0)



def run_server(host, port):
    setup_redis()
    setup_workers(2)  # 32 workers 시작
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    # CORS 설정
    configure_cors()

    try:
        uvicorn.run("GRID.api.app:app", host=host, port=port, reload=False)
    finally:
        print("Shutting down worker processes...")
        stop_workers()
        print("All worker processes have been stopped.")
if __name__ == "__main__":
    configure_multiprocessing()
    multiprocessing.freeze_support()

    parser = argparse.ArgumentParser(description="Run FastAPI server.")
    parser.add_argument("--port", type=int, default=8012, help="Port to run the server on")
    args = parser.parse_args()

    host = "0.0.0.0"
    port = args.port
    run_server(host, port)  