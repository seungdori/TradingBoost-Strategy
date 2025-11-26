import asyncio
import logging
import os
import signal
from contextlib import asynccontextmanager
from typing import Set

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from HYPERRSI.src.api.middleware import setup_middlewares
from HYPERRSI.src.api.routes import (
    account,
    chart,
    errors,
    okx,
    order,
    position,
    preset,
    settings,
    stats,
    status,
    telegram,
    trading,
    trading_log,
    user,
)

# Infrastructure imports
from HYPERRSI.src.core.error_handler import log_error
from shared.config import settings as app_settings
from shared.database.redis import close_redis, get_redis, init_redis
from shared.database.session import close_db, init_db
from shared.database.init_error_db import initialize_error_database
from shared.database.error_db_session import close_error_db
from shared.docs.openapi import attach_standard_error_examples
from shared.errors import register_exception_handlers
from shared.errors.middleware import RequestIDMiddleware
from shared.logging import get_logger, setup_json_logger

# State change logger for PostgreSQL SSOT
from HYPERRSI.src.services.state_change_logger import (
    start_state_change_logger,
    stop_state_change_logger,
)

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
    """비동기 예외 핸들러 - 종료 중 발생하는 예외 필터링"""
    if 'exception' in context:
        exc = context['exception']
        # 종료 중 발생하는 정상적인 예외들 무시
        if _is_shutting_down and isinstance(exc, (asyncio.CancelledError, RuntimeError)):
            return
        # RuntimeError for event loop stopped는 종료 시 정상
        if isinstance(exc, RuntimeError) and "Event loop stopped" in str(exc):
            return

    # 비정상적인 예외만 로깅
    if not _is_shutting_down:
        logger.error(f"Caught exception: {context}")

async def shutdown(signal_name: str):
    """
    Graceful shutdown handler with proper cleanup and forced termination.

    This function is called when the application receives a shutdown signal
    (e.g., SIGINT from Ctrl+C). It performs cleanup operations by setting
    the shutdown flag, allowing the lifespan context manager to handle cleanup.

    If shutdown takes too long (>10s), it forces termination to prevent hanging.

    Args:
        signal_name: Name of the signal that triggered the shutdown
    """
    global _is_shutting_down
    if _is_shutting_down:
        return

    _is_shutting_down = True
    logger.info(f"Received exit signal {signal_name}. Triggering graceful shutdown...")

    try:
        # Cancel all tracked tasks using TaskTracker
        await task_tracker.cancel_all(timeout=5.0)

        # Cancel any remaining legacy tasks
        current_task = asyncio.current_task()
        pending_tasks = [t for t in tasks if t is not current_task and not t.done()]

        if pending_tasks:
            logger.info(f"Cancelling {len(pending_tasks)} legacy tasks")
            for task in pending_tasks:
                task.cancel()
            # Wait briefly for task cancellation
            await asyncio.wait(pending_tasks, timeout=3.0)

        # Get all running tasks and cancel them
        all_tasks = [t for t in asyncio.all_tasks() if t is not current_task and not t.done()]
        if all_tasks:
            logger.info(f"Force cancelling {len(all_tasks)} remaining async tasks")
            for task in all_tasks:
                task.cancel()
            # Wait with timeout
            await asyncio.wait(all_tasks, timeout=2.0)

    except Exception as e:
        logger.error(f"Error during shutdown task cleanup: {e}", exc_info=True)
    finally:
        logger.info("Signal handler cleanup completed. Lifespan will handle final cleanup.")

async def force_shutdown_after_timeout():
    """Force shutdown after timeout to prevent hanging"""
    await asyncio.sleep(10.0)  # Wait 10 seconds
    if _is_shutting_down:
        logger.warning("Graceful shutdown timeout exceeded. Forcing immediate exit.")
        os._exit(1)

def handle_signals():
    """시그널 핸들러 설정"""
    loop = asyncio.get_event_loop()

    # 예외 핸들러 설정
    loop.set_exception_handler(handle_exception)

    def sigint_handler():
        """SIGINT 핸들러 - 종료 프로세스를 시작하고 타임아웃 보호를 추가"""
        # Don't track shutdown task to avoid recursive cancellation
        asyncio.create_task(shutdown("SIGINT"), name="shutdown-handler")
        # Start force shutdown timer
        asyncio.create_task(force_shutdown_after_timeout(), name="force-shutdown-timer")

    # Ctrl+C (SIGINT)에만 반응하도록 설정
    loop.add_signal_handler(signal.SIGINT, sigint_handler)


async def cleanup_redis_on_startup():
    """
    서버 시작 시 Redis에 남아있는 오래된 태스크 상태 초기화

    서버가 비정상 종료되었을 때 Redis에 남은 task_running, lock 키들을
    정리하여 정상적인 재시작을 보장합니다.
    """
    try:
        redis = await get_redis()

        # task_running 패턴 키 삭제
        pattern = "user:*:task_running"
        cursor = 0
        task_keys = []

        while True:
            cursor, keys = await redis.scan(cursor, match=pattern, count=100)
            task_keys.extend(keys)
            if cursor == 0:
                break

        if task_keys:
            await redis.delete(*task_keys)
            logger.info(f"✅ 서버 시작: {len(task_keys)}개의 task_running 키 삭제")

        # lock 패턴 키 삭제
        pattern = "lock:user:*"
        cursor = 0
        lock_keys = []

        while True:
            cursor, keys = await redis.scan(cursor, match=pattern, count=100)
            lock_keys.extend(keys)
            if cursor == 0:
                break

        if lock_keys:
            await redis.delete(*lock_keys)
            logger.info(f"✅ 서버 시작: {len(lock_keys)}개의 lock 키 삭제")

        if not task_keys and not lock_keys:
            logger.info("✅ 서버 시작: 정리할 태스크 상태 없음")

    except Exception as e:
        logger.error(f"❌ Redis 초기화 중 오류: {e}", exc_info=True)
        # 초기화 실패해도 서버는 계속 시작 (critical하지 않음)


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

        # Initialize infrastructure
        await init_db()
        await init_redis()

        # Clean up stale Redis task states (from abnormal shutdown)
        try:
            await asyncio.wait_for(cleanup_redis_on_startup(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Redis cleanup timed out, continuing startup...")

        # Initialize error database (separate pool)
        try:
            await initialize_error_database()
            logger_new.info("Error database initialized (separate pool)")

            # Initialize HYPERRSI error table
            from HYPERRSI.src.database.hyperrsi_error_db import initialize_hyperrsi_error_db
            await initialize_hyperrsi_error_db()
            logger_new.info("HYPERRSI error table initialized")

            # Initialize Stop Loss error table
            from HYPERRSI.src.database.stoploss_error_db import initialize_stoploss_error_db
            await initialize_stoploss_error_db()
            logger_new.info("Stop Loss error table initialized")
        except Exception as e:
            logger.warning(f"Error database initialization failed (continuing without it): {e}")
            # Continue even if error DB fails - it's not critical for main operations

        # Start StateChangeLogger for PostgreSQL SSOT (batch writes)
        try:
            await start_state_change_logger()
            logger_new.info("StateChangeLogger started (batch writes to PostgreSQL)")
        except Exception as e:
            logger.warning(f"StateChangeLogger initialization failed (continuing without it): {e}")
            # Continue even if StateChangeLogger fails - Redis cache still works

        logger_new.info("HYPERRSI application startup complete")
        logger.info("Starting application...")

        yield

    except Exception as e:
        logger.error(f"Error during application lifecycle: {e}", exc_info=True)
    finally:
        logger_new.info("Shutting down HYPERRSI application")
        logger.info("Shutting down application...")

        try:
            # Stop StateChangeLogger first (flushes remaining changes to PostgreSQL)
            try:
                await stop_state_change_logger()
                logger_new.info("StateChangeLogger stopped (remaining changes flushed)")
            except Exception as e:
                logger.warning(f"StateChangeLogger shutdown failed: {e}")

            # Cleanup infrastructure connections with timeout and shield from cancellation
            cleanup_tasks = [
                asyncio.create_task(close_db(), name="close_db"),
                asyncio.create_task(close_redis(), name="close_redis"),
                asyncio.create_task(close_error_db(), name="close_error_db")
            ]

            # Wait for cleanup with timeout
            done, pending = await asyncio.wait(cleanup_tasks, timeout=5.0)

            # Cancel any pending tasks
            for task in pending:
                task.cancel()
                logger.warning(f"Cleanup task {task.get_name()} timed out and was cancelled")

            # Check if any tasks failed
            for task in done:
                if not task.cancelled():
                    try:
                        task.result()
                    except asyncio.CancelledError:
                        # Normal during shutdown
                        pass
                    except Exception as e:
                        logger.error(f"Cleanup task {task.get_name()} failed: {e}")

        except asyncio.CancelledError:
            # Suppress CancelledError during shutdown - this is normal
            logger.debug("Cleanup operations cancelled during shutdown")
            pass
        except Exception as e:
            logger.error(f"Error during final cleanup: {e}", exc_info=True)
        finally:
            logger_new.info("HYPERRSI application shutdown complete")

# FastAPI 앱 설정
app = FastAPI(
    title="HYPERRSI Trading Strategy API",
    description="HyperRSI Swagger",
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
    swagger_ui_parameters={
        "filter": True,  # 검색 필터 활성화
        "tryItOutEnabled": True,  # Try it out 기본 활성화
        "persistAuthorization": True,  # 인증 정보 유지
        "displayOperationId": False,
        "displayRequestDuration": True,  # 요청 시간 표시
    },
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
        },
        {
            "name": "errors",
            "description": "에러 로그 조회 및 통계"
        },
        {
            "name": "presets",
            "description": "트레이딩 프리셋 관리 (생성, 조회, 수정, 삭제)"
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
        "http://localhost:3009",
        "http://localhost:3010",
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
app.include_router(errors.router, prefix="/api")
app.include_router(preset.router, prefix="/api")

# Add Redis pool monitoring endpoint
from shared.api.health import router as health_router
app.include_router(health_router, prefix="/api", tags=["health"])

app.include_router(chart.router)
app.mount("/src/static", StaticFiles(directory=static_dir), name="static")



@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """전역 예외 처리 + errordb 자동 로깅"""
    # 요청에서 user_id, telegram_id 추출 시도
    user_id = None
    telegram_id = None
    try:
        # 헤더나 토큰에서 user_id 추출
        if 'user_id' in request.headers:
            user_id = request.headers['user_id']
        # 또는 query params에서
        elif 'user_id' in request.query_params:
            user_id = request.query_params['user_id']

        # telegram_id 추출
        if 'telegram_id' in request.headers:
            telegram_id = int(request.headers['telegram_id'])
        elif 'telegram_id' in request.query_params:
            telegram_id = int(request.query_params['telegram_id'])
    except Exception:
        pass

    # 파일 로그 (기존)
    log_error(
        error=exc,
        user_id=user_id,
        additional_info={
            'path': request.url.path,
            'method': request.method
        }
    )

    # errordb에 자동 기록 (HYPERRSI 전용 테이블)
    try:
        from HYPERRSI.src.database.hyperrsi_error_db import log_hyperrsi_error

        # Request ID 추출 (있으면)
        request_id = request.headers.get('X-Request-ID') or request.state.__dict__.get('request_id')

        # 에러 타입 결정
        error_type = exc.__class__.__name__

        # 심각도 결정
        severity = "ERROR"
        if isinstance(exc, (ValueError, KeyError, AttributeError)):
            severity = "WARNING"
        elif "Critical" in error_type or "Fatal" in error_type:
            severity = "CRITICAL"

        # 비동기로 DB에 기록 (실패해도 응답은 반환)
        asyncio.create_task(
            log_hyperrsi_error(
                error=exc,
                error_type=error_type,
                user_id=user_id,
                telegram_id=telegram_id,
                severity=severity,
                module="global_exception_handler",
                function_name="global_exception_handler",
                metadata={
                    'path': request.url.path,
                    'method': request.method,
                    'headers': dict(request.headers),
                    'query_params': dict(request.query_params),
                },
                request_id=request_id,
            )
        )
    except Exception as e:
        # DB 로깅 실패해도 응답은 반환
        logger.error(f"Failed to log error to errordb: {e}")

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

# Custom ReDoc endpoint with enhanced search
@app.get("/redoc", include_in_schema=False)
async def redoc_html():
    """
    ReDoc documentation with enhanced search capabilities.
    ReDoc provides better search functionality than Swagger UI.
    """
    return get_redoc_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - ReDoc",
        redoc_js_url="https://cdn.jsdelivr.net/npm/redoc@latest/bundles/redoc.standalone.js",
    )

# Note: @app.on_event decorators are deprecated in FastAPI.
# All startup/shutdown logic is now handled by the lifespan context manager above.

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )
