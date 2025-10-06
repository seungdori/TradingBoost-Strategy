"""로깅 설정 모듈"""
import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Optional


def setup_logger(
    name: str,
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    format_string: Optional[str] = None,
    console_output: bool = True
) -> logging.Logger:
    """
    표준 로거 설정

    Args:
        name: 로거 이름
        log_level: 로그 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: 로그 파일 경로 (None이면 콘솔만)
        max_bytes: 로그 파일 최대 크기
        backup_count: 백업 파일 개수
        format_string: 커스텀 포맷 문자열
        console_output: 콘솔 출력 여부

    Returns:
        설정된 로거

    Examples:
        >>> logger = setup_logger('my_app', log_level='DEBUG')
        >>> logger.info("Application started")

        >>> logger = setup_logger('my_app', log_file='logs/app.log')
        >>> logger.error("Error occurred")
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper()))

    # 기존 핸들러 제거 (중복 방지)
    logger.handlers.clear()

    # 포맷 설정
    if format_string is None:
        format_string = (
            "[%(asctime)s] [%(name)s] [%(levelname)s] "
            "%(filename)s:%(lineno)d - %(message)s"
        )

    formatter = logging.Formatter(format_string)

    # 콘솔 핸들러 (선택적)
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # 파일 핸들러 (선택적)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # 상위 로거로의 전파 방지
    logger.propagate = False

    return logger


def get_logger(
    name: str,
    log_level: str = "INFO",
    log_file: Optional[str] = None
) -> logging.Logger:
    """
    기본 설정으로 로거 생성 (간편 함수)

    Args:
        name: 로거 이름
        log_level: 로그 레벨
        log_file: 로그 파일 경로 (선택)

    Returns:
        설정된 로거

    Examples:
        >>> logger = get_logger(__name__)
        >>> logger.info("Info message")

        >>> logger = get_logger('app', log_file='logs/app.log')
        >>> logger.warning("Warning message")
    """
    # 이미 핸들러가 설정된 로거인 경우 그대로 반환
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    return setup_logger(name, log_level, log_file)


def configure_root_logger(
    log_level: str = "INFO",
    format_string: Optional[str] = None
) -> None:
    """
    루트 로거 설정 (애플리케이션 전역 로깅)

    Args:
        log_level: 로그 레벨
        format_string: 커스텀 포맷 문자열

    Examples:
        >>> configure_root_logger('DEBUG')
        >>> logging.info("This uses root logger")
    """
    if format_string is None:
        format_string = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format=format_string
    )


# 편의 함수들

def create_file_logger(
    name: str,
    log_file: str,
    log_level: str = "INFO"
) -> logging.Logger:
    """
    파일 로거 전용 생성 (콘솔 출력 없음)

    Args:
        name: 로거 이름
        log_file: 로그 파일 경로
        log_level: 로그 레벨

    Returns:
        파일 전용 로거

    Examples:
        >>> logger = create_file_logger('audit', 'logs/audit.log')
        >>> logger.info("Audit event")
    """
    return setup_logger(
        name=name,
        log_level=log_level,
        log_file=log_file,
        console_output=False
    )


def create_console_logger(
    name: str,
    log_level: str = "INFO"
) -> logging.Logger:
    """
    콘솔 로거 전용 생성 (파일 출력 없음)

    Args:
        name: 로거 이름
        log_level: 로그 레벨

    Returns:
        콘솔 전용 로거

    Examples:
        >>> logger = create_console_logger('dev')
        >>> logger.debug("Debug message")
    """
    return setup_logger(
        name=name,
        log_level=log_level,
        log_file=None,
        console_output=True
    )


def add_file_handler(
    logger: logging.Logger,
    log_file: str,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    format_string: Optional[str] = None
) -> None:
    """
    기존 로거에 파일 핸들러 추가

    Args:
        logger: 로거 객체
        log_file: 로그 파일 경로
        max_bytes: 파일 최대 크기
        backup_count: 백업 파일 개수
        format_string: 포맷 문자열

    Examples:
        >>> logger = get_logger('app')
        >>> add_file_handler(logger, 'logs/app.log')
    """
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if format_string is None:
        format_string = (
            "[%(asctime)s] [%(name)s] [%(levelname)s] "
            "%(filename)s:%(lineno)d - %(message)s"
        )

    formatter = logging.Formatter(format_string)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


# ============================================================================
# JSON 로거 - JSON 형식으로 로그를 저장하는 전용 로거
# ============================================================================

import json
import sys
import traceback
from datetime import datetime


class JSONFormatter(logging.Formatter):
    """JSON 형식 로그 포맷터"""

    def format(self, record):
        log_data = {
            'timestamp': datetime.now().isoformat(),
            'level': record.levelname,
            'message': record.getMessage()
        }

        # 추가 정보가 있는 경우 로그 데이터에 추가
        if hasattr(record, 'extra_data') and record.extra_data:
            log_data.update(record.extra_data)

        # 예외 정보가 있는 경우 추가
        if record.exc_info:
            exc_type, exc_value, exc_traceback = record.exc_info
            formatted_traceback = ''.join(
                traceback.format_exception(exc_type, exc_value, exc_traceback)
            )
            log_data['exception'] = {
                'type': exc_type.__name__ if exc_type else 'Unknown',
                'message': str(exc_value),
                'traceback': formatted_traceback
            }

        return json.dumps(log_data, ensure_ascii=False, default=str)


def setup_json_logger(
    name: str,
    log_file: str,
    log_level: str = "INFO",
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    console_output: bool = True
) -> logging.Logger:
    """
    JSON 형식으로 로그를 저장하는 로거 설정

    Args:
        name: 로거 이름
        log_file: 로그 파일 경로
        log_level: 로그 레벨
        max_bytes: 로그 파일 최대 크기
        backup_count: 백업 파일 개수
        console_output: 콘솔 출력 여부

    Returns:
        설정된 JSON 로거

    Examples:
        >>> logger = setup_json_logger('order_logger', 'logs/orders.log')
        >>> logger.info("Order placed", extra={'extra_data': {'order_id': '123'}})
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper()))
    logger.handlers.clear()
    logger.propagate = False

    formatter = JSONFormatter()

    # 파일 핸들러
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 콘솔 핸들러 (선택적)
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger


def should_log(log_key: str, interval_seconds: int = 300, _last_log_times: dict = {}) -> bool:
    """
    지정된 키에 대해 로깅을 해야 하는지 확인합니다.
    (로그 스팸 방지용)

    Args:
        log_key: 로그 타입을 구분하는 키
        interval_seconds: 로깅 간격 (기본 5분)
        _last_log_times: 마지막 로그 시간 저장용 dict (내부 사용)

    Returns:
        bool: 로깅을 해야 하면 True, 아니면 False

    Examples:
        >>> if should_log('api_error', 60):
        ...     logger.error("API error occurred")
    """
    import time
    current_time = time.time()
    last_logged = _last_log_times.get(log_key, 0)

    if current_time - last_logged >= interval_seconds:
        _last_log_times[log_key] = current_time
        return True
    return False
