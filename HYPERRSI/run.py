import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from shared.logging import get_logger

logger = get_logger(__name__)

# Get project root directory
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
HYPERRSI_DIR = Path(__file__).parent.resolve()

class ProcessManager:
    def __init__(self):
        self.processes = []
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}. Shutting down all processes...")
        self.shutdown()
        sys.exit(0)

    def run_process(self, name, command, cwd=None):
        try:
            logger.info(f"Starting {name}...")
            logger.info(f"  Command: {' '.join(command)}")
            if cwd:
                logger.info(f"  Working directory: {cwd}")
            process = subprocess.Popen(command, cwd=cwd)
            self.processes.append((name, process))
            return process
        except Exception as e:
            logger.error(f"Error starting {name}: {e}")
            return None

    def shutdown(self):
        for name, process in self.processes:
            logger.info(f"Shutting down {name}...")
            process.terminate()
            try:
                process.wait(timeout=5)  # 5초 동안 프로세스가 종료되기를 기다림
            except subprocess.TimeoutExpired:
                logger.warning(f"{name} did not terminate gracefully, killing...")
                process.kill()

def main():
    manager = ProcessManager()

    # macOS fork safety 설정
    os.environ['OBJC_DISABLE_INITIALIZE_FORK_SAFETY'] = 'YES'

    # FastAPI 서버 실행 (HYPERRSI 디렉토리에서)
    fastapi_process = manager.run_process(
        "FastAPI Server",
        ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"],
        cwd=str(HYPERRSI_DIR)
    )

    # Telegram 봇 실행 (HYPERRSI 디렉토리에서)
    bot_process = manager.run_process(
        "Telegram Bot",
        [sys.executable, "bot.py"],
        cwd=str(HYPERRSI_DIR)
    )

    # Celery Worker 실행 (프로젝트 루트에서)
    celery_worker = manager.run_process(
        "Celery Worker",
        ["celery", "-A", "HYPERRSI.src.core.celery_task", "worker", "--loglevel=warning", "--concurrency=2"],
        cwd=str(PROJECT_ROOT)
    )

    # Celery Beat 실행 (프로젝트 루트에서)
    celery_beat = manager.run_process(
        "Celery Beat",
        ["celery", "-A", "HYPERRSI.src.core.celery_task", "beat", "--loglevel=warning"],
        cwd=str(PROJECT_ROOT)
    )

    try:
        # 모든 프로세스가 실행 중인지 주기적으로 확인
        while True:
            for name, process in manager.processes[:]:  # 리스트 복사본으로 반복
                if process.poll() is not None:  # 프로세스가 종료됨
                    logger.error(f"{name} has stopped unexpectedly. Return code: {process.returncode}")
                    manager.shutdown()
                    sys.exit(1)
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
        manager.shutdown()
        sys.exit(0)

if __name__ == "__main__":
    main()