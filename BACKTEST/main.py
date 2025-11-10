"""
BACKTEST Service - TradingBoost Strategy Backtesting System

FastAPI application for backtesting trading strategies.
"""

import uvicorn
import subprocess
import signal
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from BACKTEST.config import backtest_config
from shared.logging import get_logger
from shared.database.session import init_db
from shared.api.health import router as health_router

logger = get_logger(__name__)


def kill_process_on_port(port: int) -> bool:
    """
    특정 포트를 사용 중인 프로세스를 찾아서 종료합니다.

    Args:
        port: 확인할 포트 번호

    Returns:
        bool: 프로세스를 종료했으면 True, 없으면 False
    """
    try:
        # lsof로 포트를 사용 중인 프로세스 PID 찾기
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True
        )

        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                if pid:
                    logger.info(f"포트 {port}를 사용 중인 프로세스 발견 (PID: {pid})")
                    try:
                        # SIGTERM으로 우아하게 종료 시도
                        subprocess.run(["kill", "-15", pid], check=True)
                        logger.info(f"프로세스 {pid}에 종료 신호 전송 (SIGTERM)")

                        # 프로세스 종료 대기 (최대 5초)
                        for _ in range(10):
                            check = subprocess.run(
                                ["kill", "-0", pid],
                                capture_output=True
                            )
                            if check.returncode != 0:
                                logger.info(f"프로세스 {pid} 정상 종료 완료")
                                break
                            time.sleep(0.5)
                        else:
                            # 5초 후에도 종료되지 않으면 강제 종료
                            logger.warning(f"프로세스 {pid} 강제 종료 시도 (SIGKILL)")
                            subprocess.run(["kill", "-9", pid], check=True)
                            logger.info(f"프로세스 {pid} 강제 종료 완료")

                    except subprocess.CalledProcessError as e:
                        logger.error(f"프로세스 {pid} 종료 실패: {e}")
                        return False
            return True
        else:
            logger.info(f"포트 {port}를 사용 중인 프로세스가 없습니다")
            return False

    except FileNotFoundError:
        logger.warning("lsof 명령어를 찾을 수 없습니다. macOS/Linux에서만 작동합니다.")
        return False
    except Exception as e:
        logger.error(f"포트 확인 중 오류 발생: {e}")
        return False


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events.

    Replaces deprecated @app.on_event("startup") and @app.on_event("shutdown").

    Args:
        _app: FastAPI application instance (unused but required by protocol)
    """
    # Startup
    logger.info("Starting BACKTEST service...")

    # Initialize database
    try:
        await init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

    logger.info(f"BACKTEST service started on port {backtest_config.PORT}")

    yield  # Application runs here

    # Shutdown
    logger.info("Shutting down BACKTEST service...")


# Initialize FastAPI app with lifespan
app = FastAPI(
    title="TradingBoost BACKTEST API",
    description="Trading strategy backtesting service",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "BACKTEST",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs"
    }


# Import and include routers
from BACKTEST.api.routes import backtest, results

app.include_router(health_router, prefix="/health", tags=["health"])
app.include_router(backtest.router, prefix="/backtest", tags=["backtest"])
app.include_router(results.router, prefix="/api", tags=["results"])


def main():
    """Run the BACKTEST service."""
    # 시작 전 포트 확인 및 기존 프로세스 종료
    logger.info(f"BACKTEST 서비스 시작 준비 중... (포트: {backtest_config.PORT})")
    kill_process_on_port(backtest_config.PORT)

    # 잠시 대기 후 서비스 시작
    time.sleep(1)

    logger.info(f"BACKTEST 서비스 시작: {backtest_config.HOST}:{backtest_config.PORT}")
    uvicorn.run(
        "BACKTEST.main:app",
        host=backtest_config.HOST,
        port=backtest_config.PORT,
        reload=True,
        log_level="info"
    )


if __name__ == "__main__":
    main()
