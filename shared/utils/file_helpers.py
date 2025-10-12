"""파일 작업 유틸리티

공통적으로 사용되는 파일 작업 관련 유틸리티 함수들
"""
import fcntl
import os
import time
from contextlib import contextmanager
from functools import lru_cache
from typing import IO, Any, Generator

import pandas as pd


@contextmanager
def lock_file(file_path: str, timeout: int = 10) -> Generator[IO[str], None, None]:
    """
    파일 잠금을 획득합니다 (Context Manager).

    Args:
        file_path: 잠글 파일 경로
        timeout: 잠금 획득 타임아웃 (초)

    Yields:
        IO[str]: 열린 파일 핸들

    Raises:
        TimeoutError: 타임아웃 시간 내에 잠금을 획득하지 못한 경우

    Examples:
        >>> with lock_file('/path/to/file') as f:
        ...     data = f.read()
        ...     # 파일 작업
    """
    start_time = time.time()
    file_handle = None

    try:
        # 잠금 획득 시도
        while True:
            try:
                file_handle = open(file_path, 'r+')
                fcntl.flock(file_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break  # 잠금 획득 성공
            except IOError as e:
                # 파일이 이미 잠겨있는 경우
                if file_handle:
                    file_handle.close()
                    file_handle = None

                if time.time() - start_time > timeout:
                    raise TimeoutError(f"Could not acquire lock for {file_path} after {timeout}s")
                time.sleep(0.1)

        yield file_handle

    finally:
        # 잠금 해제 및 파일 닫기
        if file_handle:
            try:
                fcntl.flock(file_handle, fcntl.LOCK_UN)
            except Exception as e:
                # 잠금 해제 실패는 로깅만 하고 계속 진행
                pass
            finally:
                file_handle.close()


@lru_cache(maxsize=200)
def get_cached_data(file_path: str, timestamp: int) -> pd.DataFrame | None:
    """
    파일 경로와 타임스탬프 기반으로 캐시된 데이터를 반환합니다.

    Args:
        file_path: CSV 파일 경로
        timestamp: 파일 수정 시간 (Unix timestamp)

    Returns:
        pd.DataFrame | None: 캐시된 데이터프레임 또는 None

    Examples:
        >>> import os
        >>> file_path = '/path/to/data.csv'
        >>> timestamp = int(os.path.getmtime(file_path))
        >>> df = get_cached_data(file_path, timestamp)
    """
    return pd.read_csv(file_path) if os.path.exists(file_path) else None
