import logging
import multiprocessing
import os
import signal
import time
from urllib.parse import quote_plus

from redis import Redis
from rq import Queue, Worker

from shared.config import settings

REDIS_PASSWORD = settings.REDIS_PASSWORD

def get_redis_url():    
    redis_host = os.getenv('REDIS_HOST', 'localhost')
    redis_port = os.getenv('REDIS_PORT', '6379')
    
    if REDIS_PASSWORD:
        redis_password = REDIS_PASSWORD
        # URL-encode the password to handle special characters
        encoded_password = quote_plus(redis_password)
        return f'redis://:{encoded_password}@{redis_host}:{redis_port}'
    else:
        # 비밀번호가 없는 경우 단순 URL 반환
        return f'redis://{redis_host}:{redis_port}'



def worker_process(stop_event, redis_url):
    def signal_handler(signum, frame):
        logging.info(f"Worker process {multiprocessing.current_process().name} received signal {signum}. Initiating graceful shutdown...")
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    redis_conn = Redis.from_url(redis_url)
    worker = Worker(['grid_trading'], connection=redis_conn)
    worker.work(burst=False)

    while not stop_event.is_set():
        time.sleep(1)

    logging.info(f"Worker process {multiprocessing.current_process().name} stopped gracefully.")

class WorkerManager:
    def __init__(self, redis_url=None):
        self.redis_url = redis_url or get_redis_url()
        self.processes = []
        self.stop_events = []

    def start_workers(self, num_workers):
        for _ in range(num_workers):
            stop_event = multiprocessing.Event()
            p = multiprocessing.Process(target=worker_process, args=(stop_event, self.redis_url))
            p.start()
            self.processes.append(p)
            self.stop_events.append(stop_event)
        logging.info(f"Started {num_workers} worker processes")

    def stop_workers(self):
        logging.info("Shutting down worker processes...")
        for event in self.stop_events:
            event.set()
        for p in self.processes:
            p.join(timeout=5)
            if p.is_alive():
                logging.warning(f"Force terminating worker process {p.name}")
                p.terminate()
        self.processes.clear()
        self.stop_events.clear()
        logging.info("All worker processes have been stopped.")

    def get_active_workers_count(self):
        return sum(1 for p in self.processes if p.is_alive())

def create_worker_manager(redis_url=None):
    return WorkerManager(redis_url)


worker_manager = None

def setup_workers(num_workers, redis_url=None):
    global worker_manager
    if worker_manager is None:
        worker_manager = create_worker_manager(redis_url)
    worker_manager.start_workers(num_workers)
    
def stop_workers():
    if worker_manager:
        worker_manager.stop_workers()

def get_worker_status():
    if worker_manager:
        return {"active_workers": worker_manager.get_active_workers_count()}
    return {"active_workers": 0}

def enqueue_grid_trading_job(exchange_name, enter_strategy, enter_symbol_count, enter_symbol_amount_list,
                             grid_num, leverage, stop_loss, user_id, custom_stop, telegram_id, force_restart=False):
    redis_conn = Redis.from_url(worker_manager.redis_url) # type: ignore[union-attr]
    queue = Queue('grid_trading', connection=redis_conn)
    job = queue.enqueue('grid_process.run_grid_trading',
                        exchange_name, enter_strategy, enter_symbol_count, enter_symbol_amount_list,
                        grid_num, leverage, stop_loss, user_id, custom_stop, telegram_id, force_restart)
    logging.info(f"Enqueued job {job.id}")
    return job.id