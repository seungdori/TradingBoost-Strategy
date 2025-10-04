from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from HYPERRSI.src.api.routes import trading, account, order, position, telegram, chart, trading_log, settings, stats, status, user, okx
from HYPERRSI.src.api.middleware import setup_middlewares
from HYPERRSI.src.core.logger import get_logger
from fastapi.middleware.cors import CORSMiddleware
from HYPERRSI.src.core.database import init_db

from HYPERRSI.src.services.redis_service import init_redis
#from HYPERRSI.src.core.shutdown import deactivate_all_trading
import asyncio
import os
import signal
import logging
from typing import Set
from HYPERRSI.src.core.error_handler import log_error


# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = get_logger(__name__)

_is_shutting_down = False
tasks: Set[asyncio.Task] = set()


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
    우아한 종료 처리
    """
    global _is_shutting_down
    if _is_shutting_down:
        return
        
    _is_shutting_down = True
    logger.info(f"Received exit signal {signal_name}")
    
    ## 트레이딩 세션 종료
    #await deactivate_all_trading()
    
    # 실행 중인 태스크 정리
    current_task = asyncio.current_task()
    pending_tasks = [t for t in tasks if t is not current_task and not t.done()]
    
    if pending_tasks:
        logger.info(f"Cancelling {len(pending_tasks)} outstanding tasks")
        for task in pending_tasks:
            task.cancel()
        await asyncio.gather(*pending_tasks, return_exceptions=True)
    
    logger.info("Shutdown completed")
    
    # 서버 종료
    os._exit(0)

def handle_signals():
    """시그널 핸들러 설정"""
    loop = asyncio.get_event_loop()
    
    # 예외 핸들러 설정
    loop.set_exception_handler(handle_exception)
    
    # Ctrl+C (SIGINT)에만 반응하도록 설정
    loop.add_signal_handler(
        signal.SIGINT,
        lambda: asyncio.create_task(shutdown("SIGINT"))
    )

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        logger.info("Starting application...")
        handle_signals()
        await init_db()
        await init_redis()
        yield
    finally:
        if not _is_shutting_down:
            logger.info("Shutting down application...")

# FastAPI 앱 설정
app = FastAPI(
    title="Trading Platform API",
    description="암호화폐 트레이딩 플랫폼 API",
    version="0.9.0",
    lifespan=lifespan,
    proxy_headers=True,              # <--- 이 줄 추가: X-Forwarded-* 헤더를 사용하도록 설정
    forwarded_allow_ips="127.0.0.1"  # <--- 이 줄 추가: 로컬호스트(Nginx)에서 오는 프록시 헤더만 신뢰
)
# CORS 설정 추가
app.add_middleware(
    CORSMiddleware,
    #allow_origins=["https://beta.tradingboost.io"],  # 모든 origin 허용
    allow_origins=["*"],  # 모든 origin 허용
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

@app.on_event("startup")
async def startup_event():
    """서버 시작 시 실행"""
    handle_signals()
    logger.info("Application startup complete")

@app.on_event("shutdown")
async def shutdown_event():
    """서버 종료 시 실행"""
    global _is_shutting_down
    if not _is_shutting_down:
        await shutdown("SHUTDOWN_EVENT")
    logger.info("Application shutdown complete")