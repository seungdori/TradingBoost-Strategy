"""
Grid 트레이딩 전략을 Celery 태스크로 구현한 모듈
이전 RQ 기반 워커 관리자에서 Celery로 마이그레이션됨
"""
import asyncio
import json
import logging
import os
from datetime import datetime
from urllib.parse import quote_plus

from HYPERRSI.src.core.celery_task import celery_app
from HYPERRSI.src.core.config import settings
from shared.database.redis_helper import get_redis_client

logger = logging.getLogger(__name__)

# Redis 키 상수 정의
REDIS_KEY_GRID_STATUS = "user:{user_id}:grid_trading:status"
REDIS_KEY_GRID_JOB_ID = "user:{user_id}:grid_trading:job_id"
REDIS_KEY_GRID_INFO = "user:{user_id}:grid_trading:info"

# Redis 연결 정보 가져오기
def get_redis_url():    
    redis_host = os.getenv('REDIS_HOST', 'localhost')
    redis_port = os.getenv('REDIS_PORT', '6379')
    
    if settings.REDIS_PASSWORD:
        redis_password = settings.REDIS_PASSWORD
        # URL-encode the password to handle special characters
        encoded_password = quote_plus(redis_password)
        return f'redis://:{encoded_password}@{redis_host}:{redis_port}'
    else:
        # 비밀번호가 없는 경우 단순 URL 반환
        return f'redis://{redis_host}:{redis_port}'

# Grid 트레이딩 상태 관리 함수
async def set_grid_trading_status(user_id: str, status: str):
    """사용자의 Grid 트레이딩 상태 설정"""
    key = REDIS_KEY_GRID_STATUS.format(user_id=user_id)
    await redis.set(key, status)
    logger.info(f"[{user_id}] Grid 트레이딩 상태를 '{status}'로 설정")

async def get_grid_trading_status(user_id: str) -> str:
    """사용자의 Grid 트레이딩 상태 가져오기"""
    key = REDIS_KEY_GRID_STATUS.format(user_id=user_id)
    status = await redis.get(key)
    return status or "stopped"

async def update_grid_trading_info(user_id: str, info: dict):
    """Grid 트레이딩 정보 업데이트"""
    key = REDIS_KEY_GRID_INFO.format(user_id=user_id)
    await redis.set(key, json.dumps(info))

async def get_grid_trading_info(user_id: str) -> dict:
    """Grid 트레이딩 정보 가져오기"""
    key = REDIS_KEY_GRID_INFO.format(user_id=user_id)
    info_str = await redis.get(key)
    if not info_str:
        return {}
    try:
        return json.loads(info_str)
    except json.JSONDecodeError:
        logger.error(f"[{user_id}] Grid 트레이딩 정보 파싱 오류")
        return {}

# Grid 트레이딩 Celery 태스크
@celery_app.task(name='grid_trading_tasks.run_grid_trading', bind=True, max_retries=3)
def run_grid_trading(self, exchange_name, enter_strategy, enter_symbol_count, 
                     enter_symbol_amount_list, grid_num, leverage, stop_loss, 
                     user_id, custom_stop, telegram_id, force_restart=False):
    """

    redis = await get_redis_client()
    Grid 트레이딩 실행 태스크
    """
    logger.info(f"[{user_id}] Grid 트레이딩 태스크 시작: exchange={exchange_name}, 전략={enter_strategy}")
    
    # 비동기 작업을 위한 이벤트 루프 생성
    try:
        # 태스크 시작 상태 기록
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        # Redis에 작업 ID 저장
        loop.run_until_complete(
            get_redis_client().set(
                REDIS_KEY_GRID_JOB_ID.format(user_id=user_id),
                self.request.id
            )
        )
        
        # Grid 트레이딩 상태를 running으로 설정
        loop.run_until_complete(
            set_grid_trading_status(user_id, "running")
        )
        
        # Grid 정보 업데이트
        grid_info = {
            "exchange": exchange_name,
            "strategy": enter_strategy,
            "symbol_count": enter_symbol_count,
            "grid_num": grid_num,
            "leverage": leverage,
            "stop_loss": stop_loss,
            "started_at": datetime.now().isoformat(),
            "status": "running"
        }
        loop.run_until_complete(
            update_grid_trading_info(user_id, grid_info)
        )

        # GRID strategy 호출 - HTTP API 방식으로 변경
        # (순환 참조 방지를 위해 direct import 제거)
        import httpx

        async def call_grid_api():
            """GRID API를 호출하여 grid trading 시작"""
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        "http://localhost:8012/api/grid/start",
                        json={
                            "exchange_name": exchange_name,
                            "enter_strategy": enter_strategy,
                            "enter_symbol_count": enter_symbol_count,
                            "enter_symbol_amount_list": enter_symbol_amount_list,
                            "grid_num": grid_num,
                            "leverage": leverage,
                            "stop_loss": stop_loss,
                            "user_id": user_id,
                            "custom_stop": custom_stop,
                            "telegram_id": telegram_id,
                            "force_restart": force_restart
                        }
                    )

                    if response.status_code == 200:
                        return response.json()
                    else:
                        logger.error(f"GRID API call failed: {response.status_code} - {response.text}")
                        return None

            except httpx.ConnectError:
                logger.error("Failed to connect to GRID service at localhost:8012")
                logger.info("Attempting fallback to dynamic import...")

                # Fallback: dynamic import (for development/testing)
                try:
                    import importlib
                    grid_main_module = importlib.import_module("GRID.main.grid_main")
                    return await grid_main_module.main(
                        exchange_name, enter_strategy, enter_symbol_count, enter_symbol_amount_list,
                        grid_num, leverage, stop_loss, user_id, custom_stop, telegram_id, force_restart
                    )
                except ImportError as e:
                    logger.error(f"Fallback import failed: {e}")
                    return None

            except Exception as e:
                logger.error(f"Unexpected error calling GRID API: {e}", exc_info=True)
                return None

        result = loop.run_until_complete(call_grid_api())
        
        # 태스크 완료 상태 기록
        grid_info["status"] = "completed"
        grid_info["completed_at"] = datetime.now().isoformat()
        grid_info["result"] = result
        loop.run_until_complete(
            update_grid_trading_info(user_id, grid_info)
        )
        
        logger.info(f"[{user_id}] Grid 트레이딩 태스크 완료")
        return result
        
    except Exception as e:
        logger.error(f"[{user_id}] Grid 트레이딩 태스크 오류: {str(e)}", exc_info=True)
        # 오류 상태 기록
        try:
            grid_info = {
                "status": "error",
                "error": str(e),
                "error_at": datetime.now().isoformat()
            }
            loop = asyncio.get_event_loop()
            if not loop.is_closed():
                loop.run_until_complete(
                    update_grid_trading_info(user_id, grid_info)
                )
                loop.run_until_complete(
                    set_grid_trading_status(user_id, "error")
                )
        except Exception as redis_err:
            logger.error(f"[{user_id}] 오류 상태 기록 중 추가 오류: {str(redis_err)}")
            
        # 실패 시 재시도 로직
        try:
            self.retry(countdown=60, max_retries=3)
        except self.MaxRetriesExceededError:
            logger.error(f"[{user_id}] Grid 트레이딩 최대 재시도 횟수 초과")
        
        raise

# Grid 트레이딩 작업 큐에 등록하는 함수 (API 엔드포인트에서 호출)
def enqueue_grid_trading_job(exchange_name, enter_strategy, enter_symbol_count, enter_symbol_amount_list,
                           grid_num, leverage, stop_loss, user_id, custom_stop, telegram_id, force_restart=False):
    """
    Grid 트레이딩 작업을 Celery 큐에 등록
    이전 RQ enqueue를 Celery 태스크 호출로 대체
    """
    task = run_grid_trading.apply_async(
        args=[
            exchange_name, enter_strategy, enter_symbol_count, enter_symbol_amount_list,
            grid_num, leverage, stop_loss, user_id, custom_stop, telegram_id, force_restart
        ],
        countdown=1  # 1초 후 실행 (선택적)
    )
    
    logger.info(f"[{user_id}] Grid 트레이딩 작업 등록: task_id={task.id}")
    return task.id

# Grid 트레이딩 작업 취소 함수
def cancel_grid_trading_job(user_id: str):
    """
    사용자의 Grid 트레이딩 작업 취소
    """
    try:
        # 비동기 작업을 위한 이벤트 루프 생성
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        # 작업 ID 확인
        job_id = loop.run_until_complete(
            get_redis_client().get(REDIS_KEY_GRID_JOB_ID.format(user_id=user_id))
        )
        
        if job_id:
            # Celery 작업 취소
            celery_app.control.revoke(job_id, terminate=True)
            logger.info(f"[{user_id}] Grid 트레이딩 작업 취소: job_id={job_id}")
            
            # 상태 업데이트
            loop.run_until_complete(
                set_grid_trading_status(user_id, "stopped")
            )
            grid_info = loop.run_until_complete(
                get_grid_trading_info(user_id)
            )
            grid_info["status"] = "stopped"
            grid_info["stopped_at"] = datetime.now().isoformat()
            loop.run_until_complete(
                update_grid_trading_info(user_id, grid_info)
            )
            
            return True
        else:
            logger.warning(f"[{user_id}] 취소할 Grid 트레이딩 작업 ID를 찾을 수 없음")
            return False
    except Exception as e:
        logger.error(f"[{user_id}] Grid 트레이딩 작업 취소 중 오류: {str(e)}")
        return False

# Grid 트레이딩 상태 조회
def get_grid_trading_status_sync(user_id: str) -> dict:
    """
    사용자의 Grid 트레이딩 상태 동기식으로 조회
    API 엔드포인트에서 호출하기 위한 함수
    """
    try:
        # 비동기 작업을 위한 이벤트 루프 생성
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        # 상태 조회
        status = loop.run_until_complete(
            get_grid_trading_status(user_id)
        )
        
        # 정보 조회
        info = loop.run_until_complete(
            get_grid_trading_info(user_id)
        )
        
        return {
            "status": status,
            "info": info
        }
    except Exception as e:
        logger.error(f"[{user_id}] Grid 트레이딩 상태 조회 중 오류: {str(e)}")
        return {"status": "unknown", "error": str(e)} 