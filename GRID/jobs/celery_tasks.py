import asyncio
import logging
import json
from GRID.jobs.celery_app import app
from GRID.strategies import grid
from GRID.database.redis_database import (
    update_job_status, update_user_running_status, save_job_id, get_job_status, 
    get_user_keys, update_user_info
)

@app.task(bind=True, name='grid_trading.run_grid_trading')
def run_grid_trading(self, exchange_name, enter_strategy, enter_symbol_count, enter_symbol_amount_list,
                     grid_num, leverage, stop_loss, user_id, custom_stop, telegram_id, force_restart=False):
    """
    그리드 트레이딩 작업을 실행하는 Celery 작업
    """
    try:
        # 작업 ID를 저장 (Celery에서는 request.id를 통해 작업 ID에 접근)
        asyncio.run(save_job_id(exchange_name, user_id, self.request.id))
        asyncio.run(update_job_status(exchange_name, user_id, 'running', self.request.id))
        
        # 실제 그리드 트레이딩 로직 실행
        result = asyncio.run(grid.main(exchange_name, enter_strategy, enter_symbol_count,
                                       enter_symbol_amount_list, grid_num, leverage, stop_loss,
                                       user_id, custom_stop, telegram_id, force_restart))
        
        # 작업 상태 업데이트
        asyncio.run(update_job_status(exchange_name, user_id, 'completed', self.request.id))
        logging.info(f"Grid trading completed successfully for user {user_id} on {exchange_name}")
        
        return {'status': 'success', 'result': result}
    except Exception as e:
        error_message = f"Error in run_grid_trading for user {user_id} on {exchange_name}: {str(e)}"
        logging.error(error_message)
        
        # 작업 실패 상태 업데이트
        asyncio.run(update_job_status(exchange_name, user_id, 'failed', self.request.id))
        
        return {'status': 'error', 'error': error_message}


@app.task
def cancel_grid_tasks(exchange_name, user_id):
    """
    진행 중인 그리드 트레이딩 작업을 취소하는 Celery 작업
    """
    try:
        # 작업 취소 로직
        asyncio.run(grid.cancel_tasks(user_id, exchange_name))
        asyncio.run(update_user_info(user_id=user_id, exchange_name=exchange_name, running_status=False))
        
        # 유저 데이터 초기화
        user_key = f'{exchange_name}:user:{user_id}'
        update_data = {
            'running_symbols': json.dumps([]),
            'tasks': json.dumps([]),
            'completed_trading_symbols': json.dumps([]),
            'symbols': json.dumps([]),
            'is_running': 0
        }
        
        # Redis에 상태 업데이트
        asyncio.run(update_job_status(exchange_name, user_id, 'cancelled'))
        asyncio.run(update_user_running_status(exchange_name, user_id, False))
        
        return {'status': 'success', 'message': f'Cancelled tasks for user {user_id} on {exchange_name}'}
    except Exception as e:
        error_message = f"Error cancelling tasks for user {user_id} on {exchange_name}: {str(e)}"
        logging.error(error_message)
        return {'status': 'error', 'error': error_message}


@app.task
def cleanup_tasks():
    """
    모든 실행 중인 작업을 정리하는 Celery 작업
    """
    try:
        exchanges = ['okx', 'upbit']
        for exchange_name in exchanges:
            running_users = asyncio.run(get_user_keys(exchange_name))
            for user_id, user_data in running_users.items():
                if user_data.get("is_running"):
                    asyncio.run(grid.cancel_tasks(user_id, exchange_name))
                    asyncio.run(update_user_running_status(exchange_name, int(user_id), False))
                    
        return {'status': 'success', 'message': 'Cleaned up all running tasks'}
    except Exception as e:
        error_message = f"Error during cleanup: {str(e)}"
        logging.error(error_message)
        return {'status': 'error', 'error': error_message} 