"""
File operation utilities
"""
import os
import time
import fcntl
import pandas as pd
from functools import lru_cache
from typing import Any


def lock_file(file_path: str, timeout: int = 10) -> Any:
    """파일 잠금을 획득합니다."""
    start_time = time.time()
    while True:
        try:
            file_handle = open(file_path, 'r+')
            fcntl.flock(file_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return file_handle
        except IOError:
            if time.time() - start_time > timeout:
                raise TimeoutError("Could not acquire lock")
            time.sleep(0.1)


@lru_cache(maxsize=200)
def get_cached_data(file_path: str, timestamp: int) -> pd.DataFrame | None:
    """파일 경로와 타임스탬프 기반으로 캐시된 데이터를 반환합니다."""
    return pd.read_csv(file_path) if os.path.exists(file_path) else None
