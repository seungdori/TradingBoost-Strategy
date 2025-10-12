# Auto-configure PYTHONPATH for monorepo structure
from shared.utils.path_config import configure_pythonpath

configure_pythonpath()

import asyncio
import logging
import os
import signal
from contextlib import asynccontextmanager
from typing import Set

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from HYPERRSI.src.api.middleware import setup_middlewares
from HYPERRSI.src.api.routes import (
    account,
    chart,
    okx,
    order,
    position,
    settings,
    stats,
    status,
    telegram,
    trading,
    trading_log,
    user,
)

# Legacy imports (for backward compatibility)
from HYPERRSI.src.core.database import init_db, init_global_redis_clients
from HYPERRSI.src.core.error_handler import log_error
from HYPERRSI.src.services.redis_service import init_redis

# New infrastructure imports
from shared.config import settings as app_settings
from shared.database.redis import close_redis
from shared.database.redis import init_redis as init_new_redis
from shared.database.session import close_db
from shared.database.session import init_db as init_new_db
from shared.docs.openapi import attach_standard_error_examples
from shared.errors import register_exception_handlers
from shared.errors.middleware import RequestIDMiddleware
from shared.logging import get_logger, setup_json_logger

# Task tracking utility
from shared.utils.task_tracker import TaskTracker

# Setup structured logging
logger_new = setup_json_logger("hyperrsi")

# Legacy logger (for backward compatibility)
logger = get_logger(__name__)

_is_shutting_down = False
tasks: Set[asyncio.Task] = set()

# Global task tracker for background tasks
task_tracker = TaskTracker(name="hyperrsi-main")


def handle_exception(loop, context):
    """비동기 예외 핸들러"""
    if 'exception' in context:
        exc = context['exception']
        if isinstance(exc, asyncio.CancelledError) and _is_shutting_down:
            # 종료 중 발생하는 CancelledError는 무시
            return
    logger.error(f"Caught exception: {context}")

async def shutdown(signal_name: str):
    """
    Graceful shutdown handler with proper cleanup.

    This function is called when the application receives a shutdown signal
    (e.g., SIGINT from Ctrl+C). It performs cleanup operations and then
    stops the event loop, allowing cleanup handlers and __del__ methods to run.

    Args:
        signal_name: Name of the signal that triggered the shutdown
    """
    global _is_shutting_down
    if _is_shutting_down:
        return

    _is_shutting_down = True
    logger.info(f"Received exit signal {signal_name}")

    try:
        ## Trading session cleanup
        #await deactivate_all_trading()

        # Cancel all tracked tasks using TaskTracker
        await task_tracker.cancel_all(timeout=10.0)

        # Cancel any remaining legacy tasks
        current_task = asyncio.current_task()
        pending_tasks = [t for t in tasks if t is not current_task and not t.done()]

        if pending_tasks:
            logger.info(f"Cancelling {len(pending_tasks)} legacy tasks")
            for task in pending_tasks:
                task.cancel()
            # Wait for tasks to complete cancellation
            await asyncio.gather(*pending_tasks, return_exceptions=True)

        # Close infrastructure connections
        await close_db()
        await close_redis()

    except Exception as e:
        logger.error(f"Error during shutdown: {e}", exc_info=True)
    finally:
        logger.info("Shutdown completed")
        # Stop the event loop gracefully instead of os._exit(0)
        # This allows finally blocks and __del__ methods to run
        loop = asyncio.get_event_loop()
        loop.stop()

def handle_signals():
    """시그널 핸들러 설정"""
    loop = asyncio.get_event_loop()

    # 예외 핸들러 설정
    loop.set_exception_handler(handle_exception)

    # Ctrl+C (SIGINT)에만 반응하도록 설정
    loop.add_signal_handler(
        signal.SIGINT,
        lambda: task_tracker.create_task(shutdown("SIGINT"), name="shutdown-handler")
    )

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan with new infrastructure integration"""
    try:
        # New infrastructure initialization
        logger_new.info(
            "Starting HYPERRSI application",
            extra={
                "environment": app_settings.ENVIRONMENT,
                "debug": app_settings.DEBUG,
            }
        )

        handle_signals()

        # Initialize new infrastructure
        await init_new_db()
        await init_new_redis()

        # Legacy database initialization
        await init_db()
        await init_redis()

        # Initialize global Redis clients for legacy code compatibility
        await init_global_redis_clients()

        logger_new.info("HYPERRSI application startup complete")
        logger.info("Starting application...")

        yield

    finally:
        if not _is_shutting_down:
            logger_new.info("Shutting down HYPERRSI application")
            logger.info("Shutting down application...")

            # Cleanup new infrastructure
            await close_db()
            await close_redis()

            logger_new.info("HYPERRSI application shutdown complete")

# FastAPI 앱 설정
app = FastAPI(
    title="HYPERRSI Trading Strategy API",
    description="""
# HYPERRSI Trading Strategy API

RSI 및 트렌드 분석 기반의 자동화된 거래 API입니다.

## 주요 기능

- **RSI 기반 진입**: Relative Strength Index를 활용한 과매수/과매도 진입 전략
- **트렌드 분석**: 이동평균선 및 추세 지표를 활용한 시장 방향성 판단
- **자동 주문 실행**: 지정가, 시장가, 조건부 주문 자동 실행
- **포지션 관리**: 자동 손절매, 익절, 포지션 사이징
- **실시간 모니터링**: 계좌 잔고, 포지션, 주문 상태 실시간 조회
- **텔레그램 알림**: 중요 이벤트에 대한 실시간 알림

## 시작하기

1. 계좌 설정: `/api/account` 엔드포인트에서 거래소 계정 정보를 확인하세요
2. 거래 활성화: `/api/trading/activate` 엔드포인트로 자동 거래를 시작하세요
3. 포지션 모니터링: `/api/position` 엔드포인트에서 현재 포지션을 확인하세요

## 지원 거래소

- OKX (선물)
- Binance (선물)
- Bybit (선물)

## 보안 주의사항

- API 키는 안전하게 저장되며 암호화됩니다
- 프로덕션 환경에서는 반드시 HTTPS를 사용하세요
- 2FA 인증을 활성화하는 것을 권장합니다
""",
    version="1.0.0",
    contact={
        "name": "TradingBoost Support",
        "url": "https://tradingboost.io",
        "email": "support@tradingboost.io"
    },
    license_info={
        "name": "Proprietary",
        "url": "https://tradingboost.io/license"
    },
    terms_of_service="https://tradingboost.io/terms",
    debug=app_settings.DEBUG,
    lifespan=lifespan,
    proxy_headers=True,
    forwarded_allow_ips="127.0.0.1",
    openapi_tags=[
        {
            "name": "trading",
            "description": "거래 관리 및 실행 엔드포인트 (활성화, 비활성화, 상태 조회)"
        },
        {
            "name": "account",
            "description": "계좌 정보 조회 (잔고, 레버리지, 마진 등)"
        },
        {
            "name": "order",
            "description": "주문 관리 (생성, 취소, 조회, 히스토리)"
        },
        {
            "name": "position",
            "description": "포지션 관리 및 조회"
        },
        {
            "name": "telegram",
            "description": "텔레그램 알림 설정 및 관리"
        },
        {
            "name": "chart",
            "description": "차트 데이터 및 시각화"
        },
        {
            "name": "trading_log",
            "description": "거래 로그 및 히스토리"
        },
        {
            "name": "settings",
            "description": "전략 설정 및 파라미터 관리"
        },
        {
            "name": "stats",
            "description": "통계 및 성과 분석"
        },
        {
            "name": "status",
            "description": "시스템 상태 및 헬스체크"
        },
        {
            "name": "user",
            "description": "사용자 정보 및 관리"
        },
        {
            "name": "okx",
            "description": "OKX 거래소 전용 엔드포인트"
        }
    ]
)

attach_standard_error_examples(app)

# Register exception handlers (new infrastructure)
register_exception_handlers(app)

# Register Request ID middleware (MUST be first for proper tracking)
app.add_middleware(RequestIDMiddleware)

# CORS 설정 추가
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://beta.tradingboost.io",
        "https://tradingboost.io",
        "https://tradingboostdemo.com",
        "http://localhost:3000",
        "https://localhost:3000",
        "http://158.247.206.127:3000",
        "https://158.247.206.127:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],  # 모든 HTTP 메소드 허용
    allow_headers=["*"],  # 모든 HTTP 헤더 허용
)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(BASE_DIR, "src", "static")

setup_middlewares(app)



app.include_router(trading.router, prefix="/api")
app.include_router(order.router, prefix="/api")
app.include_router(position.router, prefix="/api")
app.include_router(account.router, prefix="/api")
app.include_router(telegram.router, prefix="/api")
app.include_router(trading_log.trading_log_router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
app.include_router(status.router, prefix="/api")
app.include_router(user.router, prefix="/api")
app.include_router(okx.router, prefix="/api")

app.include_router(chart.router)
app.mount("/src/static", StaticFiles(directory=static_dir), name="static")



@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """전역 예외 처리"""
    # 요청에서 user_id 추출 시도
    user_id = None
    try:
        # 헤더나 토큰에서 user_id 추출
        if 'user_id' in request.headers:
            user_id = request.headers['user_id']
        # 또는 query params에서
        elif 'user_id' in request.query_params:
            user_id = request.query_params['user_id']
    except:
        pass

    # 에러 로깅
    log_error(
        error=exc,
        user_id=user_id,
        additional_info={
            'path': request.url.path,
            'method': request.method
        }
    )

    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "message": "서버 오류가 발생했습니다."
        }
    )

@app.get("/") 
async def root():
    return {"status": "running"}

@app.get("/health")
async def health_check():
    return {
        "status": "healthy"
    }

# Note: @app.on_event decorators are deprecated in FastAPI.
# All startup/shutdown logic is now handled by the lifespan context manager above.
