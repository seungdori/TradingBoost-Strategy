"""공통 경로 헬퍼 유틸리티

프로젝트의 로그 및 데이터 디렉토리 경로를 관리합니다.
"""
import sys
from pathlib import Path

# Path to the directory where the fast api packaged binary is located
packaged_binary_dir = Path(sys.executable).parent
current_dir = Path(__file__).resolve().parent

logs_dir = packaged_binary_dir / 'logs'

grid_dir = logs_dir / 'Grid_Data'

logs_dir.mkdir(parents=True, exist_ok=True)  # Create the logs directory if it doesn't exist
grid_dir.mkdir(parents=True, exist_ok=True)  # Create the grid directory if it doesn't exist

exchanges = ['bitget', 'binance', 'upbit', 'okx', 'bitget_spot', 'okx_spot', 'binance_spot']

# Create a directory for each exchange
for exchange in exchanges:
    exchange_dir = grid_dir / exchange
    exchange_dir.mkdir(parents=True, exist_ok=True)
    trading_results_dir_long = exchange_dir / 'long'
    trading_results_dir_short = exchange_dir / 'short'
    trading_results_dir_longshort = exchange_dir / 'long-short'
    trading_results_dir_long.mkdir(parents=True, exist_ok=True)
    trading_results_dir_short.mkdir(parents=True, exist_ok=True)
    trading_results_dir_longshort.mkdir(parents=True, exist_ok=True)
