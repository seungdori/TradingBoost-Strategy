# Auto-configure PYTHONPATH for monorepo structure
from shared.utils.path_config import configure_pythonpath
configure_pythonpath()

from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import psutil

import asyncio
import logging
from GRID.services import db_service, bot_state_service
from GRID.routes import (
    auth_route, logs_route, trading_route, exchange_route,
    feature_route, bot_state_route, utils_route,
    user_route, telegram_route,
)
from shared.dtos.bot_state import BotStateDto, BotStateKeyDto, BotStateError
from GRID.trading.instance_manager import start_cleanup_task
import os
import json
from GRID.dtos.feature import StartFeatureDto

import GRID.strategies.grid_process
from GRID.strategies.grid_process import update_user_data, start_grid_main_in_process
import redis.asyncio as aioredis
import traceback
import uvicorn

# New infrastructure imports
from shared.config import settings
from shared.errors import register_exception_handlers
from shared.errors.middleware import RequestIDMiddleware
from shared.database.session import init_db, close_db
from shared.database.redis import init_redis, close_redis
from shared.logging import setup_json_logger

# Legacy imports (for backward compatibility)
from GRID.trading.redis_connection_manager import RedisConnectionManager
from contextlib import asynccontextmanager

# Setup structured logging
logger = setup_json_logger("grid")

APP_PORT = None
redis_connection = RedisConnectionManager()
process_pool = None



async def get_request_body(redis, exchange_id : str , user_id : int) -> str | None:
    """Redis에서 request_body를 가져옴"""
    redis_key = f"{exchange_id}:request_body:{user_id}"
    value = await redis.get(redis_key)
    return value


async def get_redis_connection():
    return aioredis.from_url('redis://localhost', encoding='utf-8', decode_responses=True)


async def check_parent_process(parent_pid: int):
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




async def start_bot(dto: StartFeatureDto, request: Request, background_tasks: BackgroundTasks, force_restart = False):
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
        redis = await get_redis_connection()

        # 요청 본문을 Redis에 저장
        await redis.set(f"{exchange_name}:request_body:{dto.user_id}", json.dumps(request_body), ex=1440000)
        print(f"Request body saved to Redis for {exchange_name} user {dto.user_id}")
        
        enter_strategy = dto.enter_strategy
        enter_symbol_count = dto.enter_symbol_count
        enter_symbol_amount_list = dto.enter_symbol_amount_list
        grid_num = dto.grid_num
        leverage = dto.leverage
        stop_loss = dto.stop_loss
        api_keys = dto.api_key
        api_secret = dto.api_secret
        password = dto.password
        user_id = int(dto.user_id)
        custom_stop = dto.custom_stop
        telegram_id = dto.telegram_id
        
        # enter_symbol_amount_list 처리 로직 (변경 없음)
        if enter_symbol_amount_list is None:
            enter_symbol_amount_list = [(max(0, enter_symbol_amount_list[0])) for i in range(grid_num)]
        elif len(enter_symbol_amount_list) < grid_num:
            diff = grid_num - len(enter_symbol_amount_list)
            last_value = max(enter_symbol_amount_list[-1], 0)
            if len(enter_symbol_amount_list) > 1:
                increment = enter_symbol_amount_list[-1] - enter_symbol_amount_list[-2]
            else:
                increment = 0
            
            for i in range(diff):
                last_value += increment
                enter_symbol_amount_list.append(max(last_value,0))
        elif len(enter_symbol_amount_list) > grid_num:
            enter_symbol_amount_list = enter_symbol_amount_list[:grid_num]
        
        initial_capital = enter_symbol_amount_list
        initial_capital_json = json.dumps(initial_capital)

        print(f'{user_id} : [START FEATURE]')
        print(dto)


        

        job_id = await start_grid_main_in_process(
            exchange_name, enter_strategy, enter_symbol_count, enter_symbol_amount_list,
            grid_num, leverage, stop_loss, user_id, custom_stop, telegram_id, force_restart
        )
        print('🍏🔹😇👆',job_id)


    finally:
        # Redis 연결 닫기
        await redis.close()


async def restart_running_bots(app: FastAPI):
    redis = await get_redis_connection()
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
                    #if request_body_str:
                    #    print(f"No port info found for user {user_id}, will restart on port 8000")
                    #    current_port = 8000
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
                    fake_request.json = fake_json
                    
                    background_tasks = BackgroundTasks()
                    await update_user_data(exchange_id, user_id)
                    await start_bot(dto, fake_request, background_tasks, force_restart=True)
                    
                    # 필요한 경우 background_tasks를 실행
                    await background_tasks()
                except Exception as e:
                    print(f"Error restarting bot for user {user_id}: {str(e)}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan with new infrastructure integration"""
    port = None
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
        asyncio.create_task(check_parent_process(parent_pid))
        await asyncio.sleep(2)

        redis = await get_redis_connection()
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

        logger.info("GRID application startup complete", extra={"port": port})

    except Exception as e:
        logger.error(
            "Error initializing GRID application",
            exc_info=True,
            extra={"port": port, "parent_pid": os.getppid()}
        )
        raise

    try:
        yield
    finally:
        try:
            logger.info("Shutting down GRID application", extra={"port": port})

            redis = await get_redis_connection()
            await redis.set('recovery_state', 'True', ex=360)

            await save_running_symbols(app)

            # Cleanup new infrastructure
            await close_db()
            await close_redis()

            logger.info("GRID application shutdown complete")

        except Exception as e:
            logger.error("Error during shutdown", exc_info=True)
        finally:
            redis_connection.close_connection()


async def save_running_symbols(app: FastAPI):
    redis = await get_redis_connection()
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
    description="Grid-based trading strategy with automatic rebalancing",
    version="1.0.0",
    debug=settings.DEBUG,
    lifespan=lifespan
)

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


@app.get("/test-cors")
async def test_cors():
    return {"message": "CORS is working"}