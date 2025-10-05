import subprocess
import sys
import signal
import time
from shared.logging import get_logger

logger = get_logger(__name__)

class ProcessManager:
    def __init__(self):
        self.processes = []
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}. Shutting down all processes...")
        self.shutdown()
        sys.exit(0)

    def run_process(self, name, command):
        try:
            logger.info(f"Starting {name}...")
            process = subprocess.Popen(command)
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

    # FastAPI 서버 실행
    fastapi_process = manager.run_process(
        "FastAPI Server",
        [sys.executable, "main.py"]
    )

    # Telegram 봇 실행
    bot_process = manager.run_process(
        "Telegram Bot",
        [sys.executable, "bot.py"]
    )

    # Celery Worker 실행
    celery_worker = manager.run_process(
        "Celery Worker",
        ["celery", "-A", "src.core.celery_task", "worker", "--loglevel=warning"]
    )

    # Celery Beat 실행
    celery_beat = manager.run_process(
        "Celery Beat",
        ["celery", "-A", "src.core.celery_task", "beat", "--loglevel=warning"]
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