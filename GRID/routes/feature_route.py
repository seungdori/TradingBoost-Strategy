
import re
import trace
import traceback
from typing import Any, List
from fastapi import APIRouter, Request, BackgroundTasks, Depends, FastAPI
import redis
from GRID.grid_process import start_grid_main_in_process, stop_grid_main_process, get_running_users, update_user_data
from GRID.redis_database import get_user_key, save_running_symbols, reset_user_data
from dtos.feature import  StartFeatureDto, TestFeatureDto, CoinSellFeatureDto, StopFeatureDto, \
    CoinSellAllFeatureDto, CoinDto
from shared.dtos.response import ResponseDto
from shared.dtos.bot_state import BotStateDto, BotStateKeyDto
from services import bot_state_service
import GRID.grid as grid
import GRID.strategy as strategy
import GRID.redis_database as redis_database
import uvicorn
router = APIRouter(prefix="/feature", tags=["feature"])
import json
from shared_state import user_keys 
import asyncio
import socket
import redis.asyncio as aioredis
from zoneinfo import ZoneInfo
from datetime import datetime
import os
from shared.config import settings

REDIS_PASSWORD = settings.REDIS_PASSWORD
DEFAULT_PORT = int(os.environ.get('PORT', 8000))

async def get_redis_connection():
    try:
        if REDIS_PASSWORD:
            redis = aioredis.from_url(settings.REDIS_URL, encoding='utf-8', decode_responses=True, password=REDIS_PASSWORD)
        else:
            redis = aioredis.from_url(settings.REDIS_URL, encoding='utf-8', decode_responses=True)
        return redis
    except Exception as e:
        print(f"Error connecting to Redis: {str(e)}")
        traceback.print_exc()
        redis = None


@router.post("/save_running_symbols")
async def save_running_symbols_router():
    for exchange_id in ['binance', 'upbit', 'bitget', 'binance_spot', 'bitget_spot', 'okx', 'okx_spot', 'bybit', 'bybit_spot']:
        running_users = await get_running_users(exchange_id)
        for user_id in running_users:
            await save_running_symbols(exchange_id, user_id)
    return ResponseDto[None](
        success=True,
        message=f"All running symbols saved.",
        data=None
    )

async def get_request_body(redis, key: str) -> str | None:
    """Redis에서 request_body를 가져옴"""
    value = await redis.get(key)
    return value


def get_request_port(request: Request) -> int:
    """
    요청의 원래 포트를 반환합니다.
    로드밸런서를 통한 요청인 경우 X-Forwarded-Port를 사용하고,
    그렇지 않은 경우 서버의 실제 포트를 사용합니다.
    """
    forwarded_port = request.headers.get("X-Forwarded-Port")
    if forwarded_port:
        return int(forwarded_port)
    return DEFAULT_PORT

def get_app_port(app: FastAPI) -> int:
    """현재 FastAPI 앱이 실행 중인 포트를 반환합니다."""
    config = uvicorn.Config(app)
    server = uvicorn.Server(config)
    return server.config.port

@router.post("/save_request_body")
async def save_all_running_request_body(request: Request):
    redis = await get_redis_connection()
    running_users = await get_running_users('okx', redis)
    for user_id in running_users:
        redis_key = f"okx:request_body:{user_id}"
        request_body_str = await get_request_body(redis, redis_key)
        try:
            if request_body_str is None:
            #if request_body_str is not None:
                user_key = f'okx:user:{user_id}'
                user_data = await redis.hgetall(user_key)
                initial_capital = user_data.get('initial_capital', '[]')
                if isinstance(initial_capital, str):
                    initial_capital = json.loads(initial_capital)
                request_body = {
                    "exchange_name": "okx",
                    "enter_strategy": user_data.get('direction', ''),
                    "enter_symbol_count": int(user_data.get('numbers_to_entry', 0)),
                    "enter_symbol_amount_list": initial_capital,
                    "grid_num": int(user_data.get('grid_num', 0)),
                    "leverage": int(user_data.get('leverage', 0)),
                    "stop_loss": float(user_data.get('stop_loss', 0)),
                    "custom_stop": int(user_data.get('custom_stop', 0)),
                    "telegram_id": int(user_data.get('telegram_id', 0)),
                    "user_id": int(user_id),
                    "api_key": user_data.get('api_key', ''),
                    "api_secret": user_data.get('api_secret', ''),
                    "password": user_data.get('password', '')
                }
                #print("request_body:", request_body)
                
                # Convert the dictionary to a JSON string
                request_body_json = json.dumps(request_body)
                
                # Save the JSON string to Redis
                await redis.set(f"okx:request_body:{user_id}:backup", request_body_json)
        except Exception as e:
            print(f"Error saving request body for user {user_id}: {str(e)}")
            traceback.print_exc()
    print(f"All running user({len(running_users)}) request bodies saved.")


async def restart_single_user(exchange_id, user_id, request_body_str):
    if request_body_str:
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
            # 가짜 Request 객체에 json 메서드 추가
            async def fake_json():
                return dto.model_dump()
            fake_request = Request(scope=fake_scope)
            fake_request.json = fake_json
            
            background_tasks = BackgroundTasks()
            await update_user_data(exchange_id, user_id)
            await start_bot(dto, fake_request, background_tasks, force_restart=True)
        except Exception as e:
            print(f"Error restarting bot for user {user_id}: {str(e)}")          
            
            
            
@router.post("/force_restart")
async def restart_running_bots(request: Request):
    redis = await get_redis_connection()
    #current_port = get_request_port(request)  # Request 객체에서 포트 정보 가져오기
    print("Restarting running bots")
    for exchange_id in ['binance', 'upbit', 'bitget', 'binance_spot', 'bitget_spot', 'okx', 'okx_spot', 'bybit', 'bybit_spot']:
        running_users = await get_running_users(exchange_id)
        for user_id in running_users:
            redis_key = f"{exchange_id}:request_body:{user_id}"
            request_body_str = await get_request_body(redis, redis_key)
            print(f"Checking for request body in {redis_key}")
            if not request_body_str:
                all_keys = await redis.keys(f"{exchange_id}:request_body:{user_id}:*")
                if not all_keys:
                    # 포트 정보가 없는 경우
                    redis_key = f"{exchange_id}:request_body:{user_id}"
                    request_body_str = await get_request_body(redis, redis_key)
                #else:
                #    # 다른 포트에 데이터가 있는 경우, 해당 봇은 건너뜁니다.
                #    print(f"Bot for user {user_id} is running on a different port, skipping")
                #    continue
            if request_body_str:
                await asyncio.sleep(3)
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
                    await save_running_symbols(exchange_id, user_id)
                    await update_user_data(exchange_id, user_id)
                    await start_bot(dto, fake_request, background_tasks, force_restart=True)
                    
                    # 필요한 경우 background_tasks를 실행
                    await background_tasks()
                    new_redis_key = f"{exchange_id}:request_body:{user_id}"
                    await redis.set(new_redis_key, request_body_str)
                    if redis_key != new_redis_key:
                        await redis.delete(redis_key)
                except Exception as e:
                    print(f"Error restarting bot for user {user_id}: {str(e)}")



@router.post("/start")
async def start(dto: StartFeatureDto, request: Request, background_tasks: BackgroundTasks) -> ResponseDto[BotStateDto | None]:
    return await start_bot(dto, request, background_tasks)


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
        redis_key = f"{exchange_name}:request_body:{dto.user_id}"
        await redis.set(redis_key, json.dumps(request_body), ex=1440000)
        user_id = int(dto.user_id)
        #await redis.set(f"{exchange_name}:request_body:{dto.user_id}", json.dumps(request_body), ex=1440000)
        print(f"Request body saved to Redis for {redis_key}")
        korea_tz = ZoneInfo("Asia/Seoul")
        current_time = datetime.now(korea_tz).isoformat()
        await redis.hset(f"{exchange_name}:user:{dto.user_id}", 'last_started', current_time)
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
        await redis_database.save_user(user_id, api_key= api_keys, api_secret= api_secret, password = password ,initial_capital=initial_capital_json, direction = enter_strategy, numbers_to_entry = enter_symbol_count,grid_num = grid_num,leverage=leverage, stop_loss=stop_loss, exchange_name=exchange_name)

        print(f'{user_id} : [START FEATURE]')
        print(dto)

        current_bot_state = await bot_state_service.get_bot_state(dto=BotStateKeyDto(
            exchange_name=exchange_name,
            enter_strategy=enter_strategy,
            user_id=user_id
        ))
        
        if current_bot_state is None:
            # 봇 상태가 없으면 새로 생성
            current_bot_state = BotStateDto(
                key=f"{exchange_name}_{enter_strategy}_{user_id}",
                exchange_name=exchange_name,
                enter_strategy=enter_strategy,
                user_id=user_id,
                is_running=False
            )

        if not force_restart and current_bot_state.is_running:
            return ResponseDto[None](
                success=False,
                message=f"{exchange_name} {enter_strategy} already running.",
                data=None
            )   
        
        job_id = await start_grid_main_in_process(
            exchange_name, enter_strategy, enter_symbol_count, enter_symbol_amount_list,
            grid_num, leverage, stop_loss, user_id, custom_stop, telegram_id,force_restart
        )
        await redis.hset(f"{exchange_name}:user:{user_id}", 'is_stopped', '0')
        print('🍏🔹😇👆',job_id)

        updated_state: BotStateDto = await bot_state_service.set_bot_state(
            new_state=BotStateDto(
                key=current_bot_state.key,
                exchange_name=exchange_name,
                enter_strategy=enter_strategy,
                user_id=user_id,
                is_running=True
            )
        )

        return ResponseDto[BotStateDto](
            success=True,
            message=f"{exchange_name} {enter_strategy} start feature success.",
            data=updated_state
        )
    except Exception as e:
        print('[CATCH START EXCEPTION]', e)
        print(traceback.format_exc())
        bot_state_key_dto = BotStateKeyDto(
            exchange_name=dto.exchange_name,
            enter_strategy=dto.enter_strategy,
            user_id=int(dto.user_id)
        )
        current_bot_state = await bot_state_service.get_bot_state(dto=bot_state_key_dto)

        if current_bot_state and current_bot_state.is_running:
            updated_fail_state: BotStateDto = await bot_state_service.set_bot_state(
                new_state=BotStateDto(
                    key=current_bot_state.key,
                    exchange_name=current_bot_state.exchange_name,
                    enter_strategy=current_bot_state.enter_strategy,
                    user_id=current_bot_state.user_id,
                    is_running=False
                )
            )
            print('[START EXCEPTION UPDATED BOT STATE]', updated_fail_state)
            await grid.cancel_tasks(user_id, exchange_name)
            await redis.hset(f"{exchange_name}:user:{user_id}", 'is_stopped', '1')
            await redis.hset(f"{exchange_name}:user:{user_id}", 'is_running', '0')
            print('[START EXCEPTION UPDATED BOT STATE]', updated_fail_state)

        return ResponseDto[None](
            success=False,
            message=f"{dto.exchange_name} {dto.enter_strategy} start feature fail",
            meta={"error": str(e)},
            data=None,
        )
    finally:
        # Redis 연결 닫기
        await redis.close()

@router.post("/cancel_all_limit_orders")
async def cancel_all_limit_orders(exchange_name='okx' ,user_id=0000) :
    if (user_id is None) or user_id == 0000:
        try:
            running_user = await get_running_users(exchange_name)
            for user_id in running_user:
                await grid.cancel_user_limit_orders(user_id, exchange_name)
        except Exception as e:
            print('[CANCEL ALL LIMIT ORDERS]', str(e))
            
    try:
        await grid.cancel_user_limit_orders(user_id, exchange_name)
        return True
    except Exception as e:
        return False
    

#@router.post("/cancel_specific_symbol_limit_orders")
#async def cancel_specific_symbol_limit_orders(exchange_name='okx', user_id=0000, symbol='BTC/USDT'):
#    if (user_id is None) or user_id == 0000:
#        try:
#            running_user = await get_running_users(exchange_name)
#            for user_id in running_user:
#                await grid.cancel_specific_symbol_limit_orders(user_id, exchange_name, symbol)
#        except Exception as e:
#            print('[CANCEL SPECIFIC SYMBOL LIMIT ORDERS]', str(e))
#            
#    try:
#        await grid.cancel_specific_symbol_limit_orders(user_id, exchange_name, symbol)
#        return True
#    except Exception as e:
#        return False
    
@router.post("/recovery_mode")
async def recovery_mode(exchange_name='okx', ttl = 600):
    try:
        redis = await get_redis_connection()
        # 'recovery_mode' 키를 'true'로 설정하고 600초(10분) 후 만료되도록 설정
        await redis.set("recovery_state", 'True', ex=ttl)
        for exchange_id in ['binance', 'upbit', 'bitget', 'binance_spot', 'bitget_spot', 'okx', 'okx_spot', 'bybit', 'bybit_spot']:
            running_users = await get_running_users(exchange_id)
            for user_id in running_users:
                await save_running_symbols(exchange_id, user_id)
        return {"success": True, "message": "Recovery state activated for 600 seconds"}
    except Exception as e:
        return {"success": False, "message": f"Failed to activate recovery state: {str(e)}"}
    
# Stop 버튼 클릭시 호출
# Todo: Check required param
@router.post("/stop")
async def stop(dto: StopFeatureDto, request: Request) -> ResponseDto[BotStateDto | None]:
    redis = await get_redis_connection()
    try:
        exchange_name = dto.exchange_name
        korea_tz = ZoneInfo("Asia/Seoul")
        current_time = datetime.now(korea_tz).isoformat()
        user_id = int(dto.user_id)
        print(f'{user_id} : [STOP FEATURE]')
        print('[STOP]', dto)

        #await redis.hset(f"{exchange_name}:user:{user_id}", 'is_running', '0')
        #await redis.hset(f"{exchange_name}:user:{user_id}", 'is_stopped', '1')
        #await redis.hset(f"{exchange_name}:user:{user_id}", 'stop_task_only', '1')
        success = await stop_grid_main_process(exchange_name, user_id)
        await reset_user_data(user_id, exchange_name)
        
        print('[STOP]', dto)
        
        if success:
            print('[STOP]', dto)
            return ResponseDto[None](
                success=True,
                message=f"{user_id}의 {exchange_name} 스탑 요청 성공",
                data=None
            )
        else:
            return ResponseDto[None](
                success=False,
                message=f"{user_id}의 {exchange_name} 테스크를 찾을 수 없거나 이미 종료되었습니다.",
                data=None
            )
    except Exception as e:
        print('[CATCH STOP FEATURE ROUTE]', e)
        return ResponseDto[None](
            success=False,
            message=f"{dto.exchange_name} 스탑 요청 실패",
            meta={'error': str(e)},
            data=None
        )
    finally : 
        await redis.hset(f"{exchange_name}:user:{user_id}", 'is_running', 0)
        await redis.hset(f"{exchange_name}:user:{user_id}", 'is_stopped', '1')
        await redis.hset(f"{exchange_name}:user:{user_id}", 'last_stopped', current_time)

@router.post("/stop_task_only")
async def stop_task_only(dto: StopFeatureDto, request: Request) -> ResponseDto[BotStateDto | None]:
    redis = await get_redis_connection()
    try:
        await redis.set("recovery_state", 'True', ex=20)
        

        exchange_name = dto.exchange_name
        korea_tz = ZoneInfo("Asia/Seoul")
        current_time = datetime.now(korea_tz).isoformat()
        user_id = int(dto.user_id)
        print(f'{user_id} : [STOP ONLY TASK FEATURE]')
        print('[STOP TASK ONLY]', dto)
        #await redis.hset(f"{exchange_name}:user:{user_id}", 'is_running', '0')
        #await redis.hset(f"{exchange_name}:user:{user_id}", 'is_stopped', '1')
        await redis.hset(f'{exchange_name}:user:{user_id}', 'stop_task_only', '1')
        
        success = await stop_grid_main_process(exchange_name, user_id)
     
        if success:
            print('[STOP]', dto)
            return ResponseDto[None](
                success=True,
                message=f"{user_id}의 {exchange_name} 스탑 요청 성공",
                data=None
            )
        else:
            return ResponseDto[None](
                success=False,
                message=f"{user_id}의 {exchange_name} 테스크를 찾을 수 없거나 이미 종료되었습니다.",
                data=None
            )
    except Exception as e:
        print('[CATCH STOP FEATURE ROUTE]', e)
        return ResponseDto[None](
            success=False,
            message=f"{dto.exchange_name} 스탑 요청 실패",
            meta={'error': str(e)},
            data=None
        )
    finally : 
        await redis.hset(f"{exchange_name}:user:{user_id}", 'is_running', 0)
        await redis.hset(f"{exchange_name}:user:{user_id}", 'last_stopped', current_time)


# 전체 매도 버튼 클릭시 호출
@router.post("/sell/all")
async def sell_all_coins(dto: CoinSellAllFeatureDto) -> ResponseDto[Any | None]:
    try:
        exchange_name = dto.exchange_name
        user_id = dto.user_id
        print(f'[{exchange_name} SELL ALL COINS]')
        await grid.sell_all_coins(exchange_name, user_id)

        ##################################
        # Todo: Impl '전체 매도 버튼' feature
        ##################################

        return ResponseDto[Any](
            success=True,
            message=f"{user_id} , {exchange_name} sell all coins success.",
            data={}
        )

    except Exception as e:
        return ResponseDto[None](
            success=False,
            message=f"{user_id} sell_all_coins fail",
            meta={'error': str(e)},
            data=None
        )


# 해당 코인 매도 버튼 클릭시 호출.
# Body - 선택한 코인들 DTO 배열.
@router.post("/sell")
async def sell_coins(dto: CoinSellFeatureDto, redis: aioredis.Redis = Depends(get_redis_connection)) -> ResponseDto[List[CoinDto] | None]:
    try:
        exchange_name = dto.exchange_name
        user_id = dto.user_id
        coins = dto.coins
        if dto.qty_percent is not None:
            qty_percent = dto.qty_percent
        else:
            qty_percent = None
        user_key = f'{exchange_name}:user:{user_id}'

        print(f'[{exchange_name} SELL COINS]', coins)

        for coin in coins:
            user_data = await redis.hgetall(user_key)
            #user_data = json.loads(await redis.hget(user_key, 'data') or '{}')
            running_symbols_json = await redis.hget(user_key, 'running_symbols')
            completed_symbols_json = await redis.hget(user_key, 'completed_trading_symbols')
            is_running = user_data.get('is_running', '0')
            print('is_running:', is_running)
            #running_symbols = set(user_data.get('running_symbols', []))
            running_symbols = set(json.loads(running_symbols_json)) if running_symbols_json else set()
            print('running_symbols:', running_symbols)
            await strategy.close(exchange=exchange_name, symbol=coin.symbol, qty_perc=qty_percent, user_id=user_id)

            # Redis에서 사용자 데이터 가져오기
            print('user_data:', user_data)
            # running_symbols 및 completed_trading_symbols 업데이트
            print('currnet running_symbols:', running_symbols)
            completed_trading_symbols = set(json.loads(completed_symbols_json)) if completed_symbols_json else set()

            if coin.symbol in running_symbols:
                #await redis.srem(f"{user_key}:running_symbols", coin.symbol) #<-- 단일로 읽어오는 방식 
                running_symbols.remove(coin.symbol)
                print('removed running_symbols:', running_symbols)
            if coin.symbol not in completed_trading_symbols:
                #await redis.sadd(f"{user_key}:completed_trading_symbols", coin.symbol)
                completed_trading_symbols.add(coin.symbol)

            # 업데이트된 데이터를 Redis에 저장
            #print('before updated running_symbols:', running_symbols)
            await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
            #print('updated running_symbols:', running_symbols)
            await redis.hset(user_key, 'completed_trading_symbols', json.dumps(list(completed_trading_symbols)))

        return ResponseDto[List[CoinDto]](
            success=True,
            message=f"{exchange_name} sell coins request success",
            data=coins
        )
    except Exception as e:
        return ResponseDto[None](
            success=False,
            message="sell coins request fail",
            meta={'error': str(e)},
            data=None
        )
    finally:
        await redis.aclose()

