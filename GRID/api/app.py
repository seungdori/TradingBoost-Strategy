# ruff: noqa: E402
# Auto-configure PYTHONPATH for monorepo structure
from shared.database.redis_patterns import redis_context, RedisTTL
from shared.utils.path_config import configure_pythonpath

configure_pythonpath()

import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import psutil
import uvicorn
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html

import GRID.strategies.grid_process
from GRID.core.redis import get_redis_connection
from GRID.dtos.feature import StartFeatureDto
from GRID.routes import (
    auth_route,
    bot_state_route,
    exchange_route,
    feature_route,
    logs_route,
    telegram_route,
    trading_route,
    user_route,
    utils_route,
)
from GRID.services import bot_state_service, db_service
from GRID.strategies.grid_process import start_grid_main_in_process, update_user_data
from GRID.trading.instance_manager import start_cleanup_task

# Legacy imports (for backward compatibility)
from GRID.trading.redis_connection_manager import RedisConnectionManager

# New infrastructure imports
from shared.api.health import router as health_router
from shared.config import settings
from shared.database.redis import close_redis, init_redis
from shared.database.session import close_db, init_db
from shared.docs.openapi import attach_standard_error_examples
from shared.errors import register_exception_handlers
from shared.errors.middleware import RequestIDMiddleware
from shared.logging import setup_json_logger

# Setup structured logging
logger = setup_json_logger("grid")

APP_PORT = None
redis_connection = RedisConnectionManager()
process_pool = None



async def get_request_body(redis: Any, exchange_id : str , user_id : int) -> str | None:
    """Redis에서 request_body를 가져옴"""
    redis_key = f"{exchange_id}:request_body:{user_id}"
    value: str | None = await redis.get(redis_key)
    return value


async def check_parent_process(parent_pid: int) -> None:
    """Background task to check if the parent process is still alive."""
    while True:
        await asyncio.sleep(10)  # Check every 10 seconds
        if not psutil.pid_exists(parent_pid):
            print("Parent process is gone. Shutting down server.")
            os._exit(0)  # Forcefully exits the current program

def get_app_port(app: FastAPI) -> int:
    """현재 FastAPI 앱이 실행 중인 포트를 반환합니다."""
    config = uvicorn.Config(app)
    server = uvicorn.Server(config)
    return server.config.port




async def start_bot(dto: StartFeatureDto, request: Request, background_tasks: BackgroundTasks, force_restart: bool = False) -> None:
    request_body = await request.json()
    exchange_name = dto.exchange_name
    #try:
    #    server_port = request.headers.get("X-Forwarded-Port")
    #    if server_port is None:
    #        server_port = request.url.port
    #    client_host = request.client.host
    #    print(f"Request received from {client_host} on port {server_port}")
    #except:
    #    print(traceback.format_exc())
    print("Request body:", request_body)  # 요청 본문을 출력합니다
    try:
        # Redis 연결 생성
        async with redis_context() as redis:

            # 요청 본문을 Redis에 저장
            await redis.set(f"{exchange_name}:request_body:{dto.user_id}", json.dumps(request_body), ex=1440000)
            print(f"Request body saved to Redis for {exchange_name} user {dto.user_id}")
            enter_strategy = dto.enter_strategy
            enter_symbol_count = dto.enter_symbol_count
            enter_symbol_amount_list = dto.enter_symbol_amount_list
            grid_num = dto.grid_num
            leverage = dto.leverage
            stop_loss = dto.stop_loss
            user_id = int(dto.user_id) if dto.user_id is not None else 0
            custom_stop = dto.custom_stop
            telegram_id = dto.telegram_id

            # enter_symbol_amount_list 처리 로직 (변경 없음)
            if enter_symbol_amount_list is None:
                enter_symbol_amount_list = [0.0 for i in range(grid_num)]
            elif len(enter_symbol_amount_list) < grid_num:
                diff = grid_num - len(enter_symbol_amount_list)
                last_value = max(enter_symbol_amount_list[-1], 0)
                if len(enter_symbol_amount_list) > 1:
                    increment = enter_symbol_amount_list[-1] - enter_symbol_amount_list[-2]
                else:
                    increment = 0
                for i in range(diff):
                    last_value += increment
                    enter_symbol_amount_list.append(max(last_value, 0))
            elif len(enter_symbol_amount_list) > grid_num:
                enter_symbol_amount_list = enter_symbol_amount_list[:grid_num]

            print(f'{user_id} : [START FEATURE]')
            print(dto)

            job_id = await start_grid_main_in_process(
                exchange_name, enter_strategy, enter_symbol_count, enter_symbol_amount_list,
                grid_num, leverage, stop_loss, user_id, custom_stop, telegram_id, force_restart
            )
            print('🍏🔹😇👆', job_id)


        finally:
            # Redis 연결 닫기
async def restart_running_bots(app: FastAPI) -> None:
    async with redis_context() as redis:
        current_port = get_app_port(app)
        print(f"Restarting running bots on {current_port}")
        for exchange_id in ['binance', 'upbit', 'bitget', 'binance_spot', 'bitget_spot', 'okx', 'okx_spot', 'bybit', 'bybit_spot']:
            running_users = await GRID.strategies.grid_process.get_running_users(exchange_id)
            for user_id in running_users:
                redis_key = f"{exchange_id}:request_body:{user_id}"
                print(f"Checking for request body in {redis_key}")
                request_body_str = await get_request_body(redis, exchange_id, user_id)
                if not request_body_str:
                    request_body_str = await redis.keys(f"{exchange_id}:request_body:{user_id}:*")
                    # if request_body_str:
                    #     print(f"No port info found for user {user_id}, will restart on port 8000")
                    #     current_port = 8000
                if request_body_str:
                    await asyncio.sleep(6)
                    try:
                        request_dict = json.loads(request_body_str)
                        dto = StartFeatureDto(**request_dict)
                        print(f"Restarting bot for user {user_id}")
                        # 가짜 Request 객체 생성
                        fake_scope = {
                            "type": "http",
                            "client": ("127.0.0.1", 0),
                            "method": "POST",
                            "path": "/start_bot",
                            "headers": []
                        }
                        fake_request = Request(scope=fake_scope)
                        # 가짜 Request 객체에 json 메서드 추가
                    async def fake_json():
                        return dto.model_dump()
                    fake_request.json = fake_json  # type: ignore[method-assign]
                    background_tasks = BackgroundTasks()
                    await update_user_data(exchange_id, user_id)
                    await start_bot(dto, fake_request, background_tasks, force_restart=True)
                    # 필요한 경우 background_tasks를 실행
                    await background_tasks()
                except Exception as e:
                    print(f"Error restarting bot for user {user_id}: {str(e)}")

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan with new infrastructure integration"""
    port = None
    background_tasks: list[asyncio.Task[Any]] = []
    try:
        # Initialize new infrastructure
        logger.info(
            "Starting GRID application",
            extra={
                "environment": settings.ENVIRONMENT,
                "debug": settings.DEBUG,
            }
        )

        # Initialize database and Redis (new infrastructure)
        await init_db()
        await init_redis()

        # Legacy database initialization
        exchange_names = ['binance', 'upbit', 'bitget', 'binance_spot', 'bitget_spot', 'okx', 'okx_spot', 'bybit', 'bybit_spot']
        await db_service.init_database(exchange_names)

        port = get_app_port(app)
        app.state.port = port
        parent_pid = os.getppid()
        parent_watch_task = asyncio.create_task(check_parent_process(parent_pid))
        background_tasks.append(parent_watch_task)
        await asyncio.sleep(2)

        async with redis_context() as redis:
            recovery_state = await redis.get('recovery_state')
            logger.info(
                "Recovery state checked",
                extra={"recovery_state": recovery_state, "port": port}
            )

            bot_states = await bot_state_service.get_all_bot_state(app)
            logger.info(
                "Bot states loaded",
                extra={"bot_count": len(bot_states) if bot_states else 0, "port": port}
            )

            cleanup_task = asyncio.create_task(start_cleanup_task())
            background_tasks.append(cleanup_task)

            logger.info("GRID application startup complete", extra={"port": port})

        except Exception:
            logger.error(
                "Error initializing GRID application",
                exc_info=True,
                extra={"port": port, "parent_pid": os.getppid()}
            )
            for task in background_tasks:
                task.cancel()
            if background_tasks:
                await asyncio.gather(*background_tasks, return_exceptions=True)
            raise

        try:
            yield
        finally:
            try:
                logger.info("Shutting down GRID application", extra={"port": port})

                async with redis_context() as redis:
                    await redis.set('recovery_state', 'True', ex=360)

                    await save_running_symbols(app)

                    # Cleanup new infrastructure
                    await close_db()
                    await close_redis()

                    logger.info("GRID application shutdown complete")

                except Exception:
                    logger.error("Error during shutdown", exc_info=True)
                finally:
                    redis_connection.close_connection()  # type: ignore[attr-defined]
                    for task in background_tasks:
                        task.cancel()
                    if background_tasks:
                        await asyncio.gather(*background_tasks, return_exceptions=True)


async def save_running_symbols(app: FastAPI) -> None:
    async with redis_context() as redis:
        try:
            for exchange_id in ['binance', 'upbit', 'bitget', 'binance_spot', 'bitget_spot', 'okx', 'okx_spot', 'bybit', 'bybit_spot']:
                running_users = await GRID.strategies.grid_process.get_running_users(exchange_id)
                for user_id in running_users:
                    running_symbols = await GRID.strategies.grid.get_running_symbols(exchange_id, user_id)
                    if running_symbols:
                        redis_key = f"running_symbols:{exchange_id}:{user_id}"
                        await redis.set(redis_key, json.dumps(running_symbols))
        except Exception as e:
            print(f"Error saving running symbols: {e}")
        print("Saved running symbols for all users")


    app = FastAPI(
        title="GRID Trading Strategy API",
        description="""
    # GRID Trading Strategy API

    그리드 트레이딩 전략을 위한 자동화된 거래 API입니다.

    ## 주요 기능

    - **자동 그리드 거래**: 가격 레벨에 따라 자동으로 주문을 배치하고 관리합니다
    - **다중 거래소 지원**: OKX, Binance, Upbit, Bitget, Bybit 등을 지원합니다
    - **실시간 모니터링**: WebSocket을 통한 실시간 로그 및 상태 업데이트
    - **포지션 관리**: 자동 리밸런싱 및 손익 관리
    - **리스크 관리**: 손절매, 레버리지 설정, 심볼 화이트/블랙리스트

    ## 시작하기

    1. API 키 등록: `/exchange/keys` 엔드포인트를 통해 거래소 API 키를 설정하세요
    2. 봇 시작: `/feature/start` 엔드포인트로 그리드 트레이딩 봇을 시작하세요
    3. 모니터링: `/logs/ws/{user_id}` WebSocket으로 실시간 로그를 확인하세요

    ## 보안 주의사항

    - API 키는 암호화되어 저장됩니다
    - 읽기 전용 권한만 부여하는 것을 권장합니다
    - 프로덕션 환경에서는 반드시 HTTPS를 사용하세요
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
        debug=settings.DEBUG,
        lifespan=lifespan,
        swagger_ui_parameters={
            "filter": True,  # 검색 필터 활성화
            "tryItOutEnabled": True,  # Try it out 기본 활성화
            "persistAuthorization": True,  # 인증 정보 유지
            "displayOperationId": False,
            "displayRequestDuration": True,  # 요청 시간 표시
        },
        openapi_tags=[
            {
                "name": "feature",
                "description": "봇 제어 및 기능 관리 엔드포인트 (시작, 중지, 재시작, 매도 등)"
            },
            {
                "name": "state",
                "description": "봇 상태 조회 및 관리 엔드포인트"
            },
            {
                "name": "trading",
                "description": "거래 데이터 조회 (승률, 차트, 심볼 관리 등)"
            },
            {
                "name": "exchange",
                "description": "거래소 정보 및 API 키 관리"
            },
            {
                "name": "telegram",
                "description": "텔레그램 알림 설정 및 관리"
            },
            {
                "name": "logs",
                "description": "로그, 거래량, 손익 데이터 조회 및 WebSocket 연결"
            },
            {
                "name": "user",
                "description": "사용자 정보 조회 및 관리"
            },
            {
                "name": "auth",
                "description": "인증 및 회원가입"
            },
            {
                "name": "utils",
                "description": "유틸리티 엔드포인트 (헬스체크, 버전 등)"
            }
        ]
    )

    attach_standard_error_examples(app)

    # Register exception handlers (new infrastructure)
    register_exception_handlers(app)

    # Register Request ID middleware (MUST be first for proper tracking)
    app.add_middleware(RequestIDMiddleware)

    # CORS 미들웨어 설정 - 라우터 등록 전에 추가
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 모든 origin 허용. 프로덕션에서는 구체적인 도메인 지정 필요
        allow_credentials=True,  # 쿠키 등 인증 정보 허용
        allow_methods=["*"],  # 모든 HTTP 메서드 허용
        allow_headers=["*"],  # 모든 헤더 허용
        expose_headers=["*"],  # 클라이언트에게 노출할 헤더
    )

    # WebSocket 전용 CORS 설정을 위한 미들웨어
    @app.middleware("http")
async def add_websocket_cors_headers(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/logs/ws/"):
        response.headers["Access-Control-Allow-Origin"] = "*"
    return response



app.include_router(router=bot_state_route.router)
app.include_router(router=utils_route.router)
app.include_router(router=logs_route.router)
app.include_router(router=user_route.router)
app.include_router(router=auth_route.router)
app.include_router(router=trading_route.router)
app.include_router(router=exchange_route.router)
app.include_router(router=feature_route.router)
app.include_router(router=telegram_route.router)

# Add Redis pool monitoring endpoint
app.include_router(health_router, tags=["health", "utils"])


@app.get("/test-cors")
async def test_cors():
    return {"message": "CORS is working"}

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
