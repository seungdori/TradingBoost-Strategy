import asyncio
import atexit
import json
import logging
import multiprocessing
import os
import platform
import signal
import time
import trace
import traceback
from asyncio import CancelledError

# Redis 연결 설정
from contextlib import contextmanager

import redis
import redis.asyncio as aioredis
from h11 import Data

from GRID.database import redis_database
from GRID.database.redis_database import (
    get_job_status,
    get_user_keys,
    save_job_id,
    update_job_status,
    update_user_info,
    update_user_running_status,
)
from GRID.strategies import grid
from shared.config import settings

# Set the multiprocessing start method to 'spawn' for all platforms
multiprocessing.set_start_method('spawn', force=True)

# Celery 관련 임포트 추가
from celery import Celery, states
from celery.result import AsyncResult

from GRID.jobs.celery_app import app
from GRID.jobs.celery_tasks import cancel_grid_tasks, cleanup_tasks
from GRID.jobs.celery_tasks import run_grid_trading as celery_run_grid_trading

redis_conn = None
redis_async = None
REDIS_PASSWORD = settings.REDIS_PASSWORD

#================================================================================================
# Redis 연결 설정 
#================================================================================================


#================================================================================================
# CELERY WORKERS
#================================================================================================

def setup_redis():
    global redis_conn

    try:
        if REDIS_PASSWORD:
            redis_conn = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB, password=REDIS_PASSWORD)
        else:
            redis_conn = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB)
        redis_conn.ping()

        print("Successfully connected to Redis")
        # 애플리케이션 종료 시 cleanup 함수 호출 등록
        atexit.register(cleanup)
        
    except redis.RedisError as e:
        print(f"Failed to connect to Redis: {e}")
        raise

def cleanup():
    asyncio.run(async_cleanup())


async def async_cleanup():
    print("Starting async cleanup...")

    try:
        # Celery 작업으로 clean-up 실행
        cleanup_tasks.delay()
    except Exception as e:
        print(f"Error during async cleanup: {e}")
    finally:
        if redis_conn:
            redis_conn.close()


async def get_redis_connection():
    if REDIS_PASSWORD:
        return aioredis.from_url(f'redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}', encoding='utf-8', decode_responses=True, password=REDIS_PASSWORD)
    else:
        return aioredis.from_url(f'redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}', encoding='utf-8', decode_responses=True)


#================================================================================================

            
# RQ 기반 함수를 Celery 기반으로 변경
async def enqueue_grid_trading(exchange_name, enter_strategy, enter_symbol_count, enter_symbol_amount_list, grid_num, leverage, stop_loss, user_id, custom_stop, telegram_id, force_restart=False):
    try:
        # Celery 작업 실행
        task = celery_run_grid_trading.delay(
            exchange_name, enter_strategy, enter_symbol_count, enter_symbol_amount_list, 
            grid_num, leverage, stop_loss, user_id, custom_stop, telegram_id, force_restart
        )
        
        return task.id
    except Exception as e:
        print(f"Error enqueueing grid trading task: {e}")
        raise e


async def start_grid_main_in_process(exchange_name, enter_strategy, enter_symbol_count, enter_symbol_amount_list, grid_num, leverage, stop_loss, user_id, custom_stop, telegram_id, force_restart=False):
    job_id = None
    try:
        # 비동기 함수를 직접 호출
        job_id = await enqueue_grid_trading(
            exchange_name, enter_strategy, enter_symbol_count, enter_symbol_amount_list, 
            grid_num, leverage, stop_loss, user_id, custom_stop, telegram_id, force_restart
        )
        
        # job_id가 유효한지 확인
        if not job_id or not isinstance(job_id, str):
            print(f"Invalid job_id: {job_id}")
            return None

        # 작업 ID를 데이터베이스에 저장
        await store_job_id(user_id, job_id)
        await save_job_id(exchange_name, user_id, job_id)

        # 작업 상태를 'running'으로 업데이트
        await update_job_status(exchange_name, user_id, 'running', job_id)

        print(f"Celery job started successfully. Job ID: {job_id}🌟")
        asyncio.create_task(monitor_job_status(exchange_name=exchange_name, user_id=user_id))
        return job_id

    except Exception as e:
        logging.error(f"Error starting grid main process: {e}")

        if job_id:
            await cancel_and_cleanup_job(exchange_name, user_id, job_id)
        return None

async def cancel_and_cleanup_job(exchange_name, user_id, job_id):
    try:
        # Celery 작업 취소
        result = AsyncResult(job_id, app=app)
        if result.state in [states.PENDING, states.STARTED, states.RETRY]:
            result.revoke(terminate=True)
        
        # 작업 상태 및 사용자 상태 업데이트
        await update_job_status(exchange_name, user_id, 'failed', job_id)
        await redis_database.update_user_running_status(exchange_name, user_id, is_running=False)
    except Exception as e:
        logging.error(f"Error cancelling and cleaning up job: {e}")


async def store_job_id(user_id, job_id):
    redis_client = await get_redis_connection()
    if redis_client is None:
        raise ValueError("Failed to get Redis connection")
    await redis_client.set(f"user:{user_id}:job_id", job_id)
    await redis_client.close()
    
#================================================================================================
async def update_user_data(exchange_name, user_id):
    redis_client = await get_redis_connection()
    try:
        user_key = f'{exchange_name}:user:{user_id}'
        
        # Update running_symbols, tasks, completed_trading_symbols, symbols, and is_running
        update_data = {
            'running_symbols': json.dumps([]),
            'tasks': json.dumps([]),
            'completed_trading_symbols': json.dumps([]),
            'symbols': json.dumps([]),
            'is_running': 0
        }
        
        # Update user info in Redis
        await redis_client.hset(user_key, mapping=update_data)
        
        # Retrieve and print updated info
        updated_info = await redis_client.hgetall(user_key)
        return updated_info
    except Exception as e:
        print(f"Error updating user data: {e}")
        raise
    finally:
        await redis_client.close()
        
        
async def stop_grid_main_process(exchange_name, user_id):
    print(f'Stopping grid process: user_id = {user_id}, exchange_name = {exchange_name}')
    try:
        # Celery 작업으로 작업 취소 작업 전송
        cancel_grid_tasks.delay(exchange_name, user_id)
        
        # 작업 상태 및 사용자 상태 업데이트
        await update_job_status(exchange_name, user_id, 'cancelled')
        await update_user_running_status(exchange_name, user_id, False)
        
        return True
    except Exception as e:
        print(f"Error in stop_grid_main_process: {e}")
        print(traceback.format_exc())
    
    return False


async def monitor_job_status(exchange_name, user_id):
    try:
        redis_client = await get_redis_connection()
        while True:
            try:
                result = await get_job_status(exchange_name, user_id, redis_client)
                if result is None:
                    print(f"No job found for user_id: {user_id}")
                    break
                
                status, job_id = result
                celery_result = AsyncResult(job_id, app=app)
                
                if celery_result.ready():
                    if celery_result.successful():
                        logging.info(f"Job {job_id} has finished successfully")
                        await update_job_status(exchange_name, user_id, 'completed', redis_client)
                    else:
                        logging.info(f"Job {job_id} has failed")
                        await update_job_status(exchange_name, user_id, 'failed', redis_client)
                    break
                
                await asyncio.sleep(60)
            except CancelledError:
                print("Job monitoring was cancelled")
                break
            except Exception as e:
                print(f"Error in monitor_job_status: {e}")
                await update_job_status(exchange_name, user_id, 'failed', redis_client)
                break
    finally:
        print(f'{user_id}의 모든 작업이 완료되었습니다.')
        await redis_client.close()
        

async def get_running_users(exchange_name, redis=None):
    should_close = False
    try:
        if redis is None:
            redis = await get_redis_connection()
            should_close = True
        
        user_pattern = f'{exchange_name}:user:*'
        user_keys = await redis.keys(user_pattern)
        running_users = []
        for user_key in user_keys:
            user_key = user_key.decode('utf-8') if isinstance(user_key, bytes) else user_key
            user_id = user_key.split(':')[-1]
            is_running = await redis.hget(user_key, 'is_running')
            is_running = is_running.decode('utf-8') if isinstance(is_running, bytes) else is_running
            if is_running == '1':
                running_users.append(user_id)
        return running_users
    except Exception as e:
        print(f"Error in get_running_users: {e}")
        print(traceback.format_exc())
        return []
    finally:
        if should_close and redis:
            await redis.close()


async def cancel_job(job_id):
    try:
        # Celery 작업 취소
        result = AsyncResult(job_id, app=app)
        if result.state in [states.PENDING, states.STARTED, states.RETRY]:
            result.revoke(terminate=True)
            print(f"Job {job_id} has been cancelled.")
    except Exception as e:
        print(f"Error cancelling job {job_id}: {e}")

# 환경 변수 설정 (macOS에서만 필요)
if platform.system() == 'Darwin':
    os.environ['OBJC_DISABLE_INITIALIZE_FORK_SAFETY'] = 'YES'