"""
Grid 트레이딩 Celery 워커 관리자
이전 RQ 기반 워커 관리자에서 Celery로 마이그레이션됨
"""
import logging
import asyncio
from typing import Any
from GRID.jobs.celery_app import app as celery_app
from GRID.jobs.celery_tasks import run_grid_trading, cancel_grid_tasks
from GRID.database.redis_database import get_job_status

logger = logging.getLogger(__name__)

# 호환성을 위한 래퍼 함수들
def enqueue_grid_trading_job(exchange_name, enter_strategy, enter_symbol_count, enter_symbol_amount_list,
                             grid_num, leverage, stop_loss, user_id, custom_stop, telegram_id, force_restart=False):
    """
    기존 RQ enqueue_grid_trading_job을 Celery로 대체하는 래퍼 함수

    Args:
        exchange_name: 거래소 이름
        enter_strategy: 진입 전략
        enter_symbol_count: 심볼 개수
        enter_symbol_amount_list: 심볼별 수량 리스트
        grid_num: 그리드 개수
        leverage: 레버리지
        stop_loss: 손절 비율
        user_id: 사용자 ID
        custom_stop: 커스텀 손절
        telegram_id: 텔레그램 ID
        force_restart: 강제 재시작 여부

    Returns:
        Celery AsyncResult 객체
    """
    try:
        result = run_grid_trading.delay(
            exchange_name, enter_strategy, enter_symbol_count, enter_symbol_amount_list,
            grid_num, leverage, stop_loss, user_id, custom_stop, telegram_id, force_restart
        )
        logger.info(f"Grid trading job enqueued for user {user_id} on {exchange_name}, task_id: {result.id}")
        return result
    except Exception as e:
        logger.error(f"Failed to enqueue grid trading job: {str(e)}")
        raise

def get_worker_status():
    """
    Celery 워커 상태 조회 (기존 RQ 워커 상태 함수 대체)
    """
    try:
        # Celery Inspect를 사용하여 활성 워커 수 확인
        inspector = celery_app.control.inspect()
        active_workers = inspector.active()
        
        if active_workers:
            return {"active_workers": len(active_workers)}
        return {"active_workers": 0}
    except Exception as e:
        logger.error(f"Celery 워커 상태 조회 중 오류: {str(e)}")
        return {"active_workers": 0, "error": str(e)}

def stop_grid_trading(user_id: int, exchange_name: str = 'okx') -> Any:
    """
    특정 사용자의 Grid 트레이딩 작업 중지

    Args:
        user_id: 사용자 ID
        exchange_name: 거래소 이름 (기본값: 'okx')

    Returns:
        Celery AsyncResult 객체
    """
    try:
        result = cancel_grid_tasks.delay(exchange_name, user_id)
        logger.info(f"Grid trading cancellation requested for user {user_id} on {exchange_name}, task_id: {result.id}")
        return result
    except Exception as e:
        logger.error(f"Failed to cancel grid trading: {str(e)}")
        raise

def get_grid_status(user_id: int, exchange_name: str = 'okx') -> dict[str, Any]:
    """
    특정 사용자의 Grid 트레이딩 상태 조회

    Args:
        user_id: 사용자 ID
        exchange_name: 거래소 이름 (기본값: 'okx')

    Returns:
        dict: 작업 상태 정보 {'status': str, 'job_id': str}
    """
    try:
        # get_job_status는 async 함수이므로 동기적으로 실행
        status = asyncio.run(get_job_status(exchange_name, user_id))
        return status  # type: ignore[return-value]
    except Exception as e:
        logger.error(f"Failed to get grid status: {str(e)}")
        return {"status": "error", "error": str(e)}

# 기존 코드와의 호환성을 위한 더미 함수들
# 실제로는 Celery가 모든 워커 관리를 담당하므로 이 함수들은 필요 없음
def setup_workers(num_workers, redis_url=None):
    logger.info(f"Celery로 마이그레이션됨: setup_workers({num_workers}) 호출됨")
    return {"message": "Celery로 마이그레이션됨"}

def stop_workers():
    logger.info("Celery로 마이그레이션됨: stop_workers() 호출됨")
    return {"message": "Celery로 마이그레이션됨"}

# 기존 worker_manager 싱글톤 대체
worker_manager = None

# 싱글톤 초기화 함수 (호환성 유지)
def create_worker_manager(redis_url=None):
    logger.info("Celery로 마이그레이션됨: create_worker_manager() 호출됨")
    return None 