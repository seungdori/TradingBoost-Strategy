"""
Specialized Loggers for Trading Operations

주문, 알림, 디버깅 등 특수 목적 로거들
"""

import logging
import sys
import os
import json
import traceback
from pathlib import Path
from logging.handlers import RotatingFileHandler
from datetime import datetime
from typing import Optional, Dict, Any

# 로그 디렉토리 기본 경로
DEFAULT_LOG_DIR = Path.cwd() / 'logs'


def _get_log_dir(log_type: str = 'general') -> Path:
    """로그 디렉토리 경로를 반환합니다."""
    log_dir = DEFAULT_LOG_DIR / log_type
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


# ============================================================================
# Order Logger
# ============================================================================

class OrderJSONFormatter(logging.Formatter):
    """주문 로그 전용 JSON 포맷터"""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            'timestamp': datetime.now().isoformat(),
            'level': record.levelname,
            'message': record.getMessage()
        }

        # 추가 정보가 있는 경우 로그 데이터에 추가
        if hasattr(record, 'order_data') and record.order_data:
            log_data.update(record.order_data)

        return json.dumps(log_data, ensure_ascii=False)


def setup_order_logger() -> logging.Logger:
    """
    거래 주문(오더) 전용 로거를 설정합니다.
    유저 ID, 심볼, 포지션 타입, 진입 가격 등 트레이딩 정보를 로깅합니다.
    """
    order_logger = logging.getLogger('order_logger')
    order_logger.setLevel(logging.INFO)

    # 로그 디렉토리 생성
    log_dir = _get_log_dir('orders')

    # 파일 핸들러 설정 (용량 기반 로테이션)
    order_file_handler = RotatingFileHandler(
        filename=f'{log_dir}/trading_orders.log',
        maxBytes=10*1024*1024,  # 10MB
        backupCount=30,
        encoding='utf-8'
    )

    order_file_handler.setFormatter(OrderJSONFormatter())
    order_logger.addHandler(order_file_handler)

    # 콘솔에도 출력
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(OrderJSONFormatter())
    order_logger.addHandler(console_handler)

    return order_logger


def get_user_order_logger(user_id: str) -> logging.Logger:
    """
    특정 사용자 ID 전용 주문 로거를 설정합니다.
    사용자별로 분리된 로그 파일을 생성합니다.

    Args:
        user_id: 사용자 ID

    Returns:
        logging.Logger: 사용자 전용 로거 인스턴스
    """
    try:
        # 파라미터 안전성 검증
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            logging.warning(f"유효하지 않은 user_id={user_id}, 기본값 0으로 설정합니다.")
            user_id = 0

        # 사용자 전용 로거 생성
        logger_name = f'order_logger_user_{user_id}'
        user_logger = logging.getLogger(logger_name)
        user_logger.setLevel(logging.INFO)

        # 이미 핸들러가 설정되어 있으면 바로 반환
        if user_logger.handlers:
            return user_logger

        # 사용자별 로그 디렉토리 생성
        log_dir = _get_log_dir('orders') / 'users'
        os.makedirs(log_dir, exist_ok=True)

        # 파일 핸들러 설정
        user_file_handler = RotatingFileHandler(
            filename=f'{log_dir}/user_{user_id}_orders.log',
            maxBytes=5*1024*1024,  # 5MB
            backupCount=10,
            encoding='utf-8'
        )

        user_file_handler.setFormatter(OrderJSONFormatter())
        user_logger.addHandler(user_file_handler)

        # 상위 로거로의 전파 방지
        user_logger.propagate = False

        return user_logger

    except Exception as e:
        logging.error(f"get_user_order_logger 함수 실행 중 오류: {str(e)}", exc_info=True)
        # 최후의 보호장치 - 기본 로거 반환
        fallback_logger = logging.getLogger('fallback_logger')
        if not fallback_logger.handlers:
            fallback_handler = logging.StreamHandler()
            fallback_logger.addHandler(fallback_handler)
        return fallback_logger


def log_order(
    user_id: str,
    symbol: str,
    action_type: str,
    position_side: str,
    price: float = None,
    quantity: float = None,
    level: int = None,
    **additional_data
):
    """
    트레이딩 주문 정보를 로깅합니다.

    Args:
        user_id: 사용자 ID
        symbol: 거래 심볼 (예: BTC-USDT)
        action_type: 액션 타입 (entry, exit, dca, sl, tp 등)
        position_side: 포지션 방향 (long, short)
        price: 주문 가격
        quantity: 주문 수량
        level: DCA 레벨 (해당하는 경우)
        **additional_data: 추가 데이터
    """
    try:
        # 파라미터 안전성 검증
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            user_id = 0
            additional_data['original_user_id'] = str(user_id)

        log_data = {
            'user_id': user_id,
            'symbol': symbol,
            'action_type': action_type,
            'position_side': position_side,
            'price': price,
            'quantity': quantity,
            'level': level
        }

        # None이 아닌 추가 데이터만 포함
        for key, value in additional_data.items():
            if value is not None:
                try:
                    json.dumps({key: value})
                    log_data[key] = value
                except (TypeError, OverflowError, ValueError):
                    log_data[key] = str(value)

        # 로그 메시지 생성
        log_message = f"{action_type.upper()} - {symbol} {position_side}"
        if price is not None:
            log_message += f" @ {price}"

        # 로거에 추가 정보 전달
        record = logging.LogRecord(
            name='order_logger',
            level=logging.INFO,
            pathname='',
            lineno=0,
            msg=log_message,
            args=(),
            exc_info=None,
            func=None
        )
        record.order_data = log_data

        # 글로벌 로거와 사용자별 로거에 모두 로깅
        order_logger = logging.getLogger('order_logger')
        order_logger.handle(record)

        user_logger = get_user_order_logger(user_id)
        user_logger.handle(record)

    except Exception as e:
        logging.error(f"주문 로깅 과정에서 예상치 못한 오류 발생: {str(e)}", exc_info=True)


# ============================================================================
# Alert Logger
# ============================================================================

class AlertJSONFormatter(logging.Formatter):
    """알림 로그 전용 JSON 포맷터"""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            'timestamp': datetime.now().isoformat(),
            'level': record.levelname,
            'message': record.getMessage()
        }

        # 추가 정보가 있는 경우 로그 데이터에 추가
        if hasattr(record, 'alert_data') and record.alert_data:
            log_data.update(record.alert_data)

        # 예외 정보가 있는 경우 추가
        if record.exc_info:
            exc_type, exc_value, exc_traceback = record.exc_info
            formatted_traceback = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            log_data['exception'] = {
                'type': exc_type.__name__,
                'message': str(exc_value),
                'traceback': formatted_traceback
            }

        return json.dumps(log_data, ensure_ascii=False, default=str)


def setup_alert_logger() -> logging.Logger:
    """
    봇의 시작, 종료, 오류 등 중요 알림을 위한 전용 로거를 설정합니다.
    """
    alert_logger = logging.getLogger('alert_logger')
    alert_logger.setLevel(logging.INFO)

    # 로그 디렉토리 생성
    log_dir = _get_log_dir('alerts')

    # 파일 핸들러 설정
    current_date = datetime.now().strftime('%Y-%m-%d')
    alert_file_handler = RotatingFileHandler(
        filename=f'{log_dir}/system_alerts_{current_date}.log',
        maxBytes=10*1024*1024,  # 10MB
        backupCount=30,
        encoding='utf-8'
    )

    alert_file_handler.setFormatter(AlertJSONFormatter())
    alert_logger.addHandler(alert_file_handler)

    # 콘솔에도 출력
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(AlertJSONFormatter())
    alert_logger.addHandler(console_handler)

    return alert_logger


def alert_log(
    user_id: str,
    symbol: str,
    message: str,
    level: str = 'INFO',
    exception: Exception = None,
    **additional_data
):
    """
    봇의 시작, 종료, 오류 등의 중요 알림 메시지를 로깅합니다.

    Args:
        user_id: 사용자 ID
        symbol: 거래 심볼 (예: BTC-USDT)
        message: 알림 메시지
        level: 로그 레벨 ('INFO', 'WARNING', 'ERROR', 'CRITICAL')
        exception: 예외 객체 (오류 발생 시)
        **additional_data: 추가로 저장할 데이터
    """
    try:
        # 파라미터 안전성 검증
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            user_id = 0
            additional_data['original_user_id'] = str(user_id)

        try:
            log_level = getattr(logging, level.upper())
        except (AttributeError, TypeError):
            log_level = logging.INFO

        # 알림 데이터 준비
        alert_data = {
            'user_id': user_id,
            'symbol': symbol,
            'message': message,
            'alert_type': 'system_alert'
        }

        # 추가 데이터 병합
        if additional_data:
            safe_additional_data = {}
            for key, value in additional_data.items():
                try:
                    json.dumps({key: value}, default=str)
                    safe_additional_data[key] = value
                except (TypeError, OverflowError, ValueError):
                    safe_additional_data[key] = str(value)

            alert_data.update(safe_additional_data)

        # 로거에 추가 정보 전달
        record = logging.LogRecord(
            name='alert_logger',
            level=log_level,
            pathname='',
            lineno=0,
            msg=message,
            args=(),
            exc_info=(type(exception), exception, exception.__traceback__) if exception else None,
            func=None
        )
        record.alert_data = alert_data

        # 전역 알림 로거에 기록
        alert_logger = logging.getLogger('alert_logger')
        alert_logger.handle(record)

    except Exception as e:
        logging.error(f"알림 로깅 과정에서 예상치 못한 오류 발생: {str(e)}", exc_info=True)


# ============================================================================
# Debug Logger
# ============================================================================

class DetailedJsonFormatter(logging.Formatter):
    """디버그 로그 전용 상세 JSON 포맷터"""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            'timestamp': datetime.now().isoformat(),
            'level': record.levelname,
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
            'message': record.getMessage()
        }

        # 추가 정보가 있는 경우 로그 데이터에 추가
        if hasattr(record, 'debug_data') and record.debug_data:
            log_data['debug_data'] = record.debug_data

        # 예외 정보가 있는 경우 추가
        if record.exc_info:
            exc_type, exc_value, exc_traceback = record.exc_info
            formatted_traceback = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            log_data['exception'] = {
                'type': exc_type.__name__,
                'message': str(exc_value),
                'traceback': formatted_traceback
            }

        return json.dumps(log_data, ensure_ascii=False, default=str)


def setup_debug_logger(name='debug_logger') -> logging.Logger:
    """
    디버깅 목적의 특별 로거를 설정합니다.
    복잡한 컴포넌트나 모듈의 상세 동작을 추적하고 디버깅하는 데 사용됩니다.

    Args:
        name: 로거 이름 (기본값: 'debug_logger')

    Returns:
        logging.Logger: 디버깅용 로거 인스턴스
    """
    debug_logger = logging.getLogger(name)
    debug_logger.setLevel(logging.DEBUG)

    # 로그 디렉토리 생성
    log_dir = _get_log_dir('debug')

    # 파일 핸들러 설정 (날짜별 로그 파일)
    current_date = datetime.now().strftime('%Y-%m-%d')
    debug_file_handler = RotatingFileHandler(
        filename=f'{log_dir}/{name}_{current_date}.log',
        maxBytes=50*1024*1024,  # 50MB
        backupCount=10,
        encoding='utf-8'
    )

    debug_file_handler.setFormatter(DetailedJsonFormatter())
    debug_logger.addHandler(debug_file_handler)

    # 콘솔 출력 핸들러 (개발용)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(DetailedJsonFormatter())
    debug_logger.addHandler(console_handler)

    return debug_logger


def log_debug(
    module: str,
    function: str,
    message: str,
    level: str = 'DEBUG',
    exception: Exception = None,
    **additional_data
):
    """
    디버깅용 로그를 기록합니다.
    복잡한 로직이나 특정 모듈의 동작을 상세하게 추적할 때 사용합니다.

    Args:
        module: 모듈 이름 (예: 'dual_side_entry')
        function: 함수 이름
        message: 디버그 메시지
        level: 로그 레벨 ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
        exception: 예외 객체 (오류 발생 시)
        **additional_data: 추가 디버깅 데이터
    """
    log_level = getattr(logging, level.upper())

    # 추가 디버깅 데이터 준비
    debug_data = {
        'module': module,
        'function': function
    }

    # 추가 데이터 병합
    debug_data.update(additional_data)

    # 로거에 추가 정보 전달
    record = logging.LogRecord(
        name='debug_logger',
        level=log_level,
        pathname='',
        lineno=0,
        msg=message,
        args=(),
        exc_info=(type(exception), exception, exception.__traceback__) if exception else None,
        func=function
    )
    record.debug_data = debug_data

    debug_logger = logging.getLogger('debug_logger')
    debug_logger.handle(record)


# ============================================================================
# 전역 로거 인스턴스
# ============================================================================

# 모듈 import 시 자동으로 로거 초기화
order_logger = setup_order_logger()
alert_logger = setup_alert_logger()
debug_logger = setup_debug_logger()


# ============================================================================
# 편의 함수
# ============================================================================

def log_bot_start(user_id: str, symbol: str, config: dict = None):
    """트레이딩 봇 시작을 로깅합니다."""
    message = f"트레이딩 봇 시작 - {symbol}"
    additional_data = {}

    if config:
        try:
            json.dumps(config)
            additional_data = {
                'config': config,
                'event_type': 'bot_start'
            }
        except (TypeError, OverflowError, ValueError):
            safe_config = {}
            for k, v in config.items():
                try:
                    json.dumps({k: v})
                    safe_config[k] = v
                except:
                    safe_config[k] = str(v)
            additional_data = {
                'config': safe_config,
                'event_type': 'bot_start'
            }

    alert_log(
        user_id=user_id,
        symbol=symbol,
        message=message,
        level='INFO',
        **additional_data
    )


def log_bot_stop(user_id: str, symbol: str, reason: str = None):
    """트레이딩 봇 종료를 로깅합니다."""
    message = f"트레이딩 봇 종료 - {symbol}"
    if reason:
        message += f" - 이유: {reason}"

    alert_log(
        user_id=user_id,
        symbol=symbol,
        message=message,
        level='INFO',
        event_type='bot_stop',
        stop_reason=reason
    )


def log_bot_error(user_id: str, symbol: str, error_message: str, exception: Exception = None, **additional_data):
    """트레이딩 봇 오류를 로깅합니다."""
    message = f"트레이딩 봇 오류 - {symbol} - {error_message}"

    safe_additional_data = {'event_type': 'bot_error'}
    for k, v in additional_data.items():
        try:
            json.dumps({k: v})
            safe_additional_data[k] = v
        except:
            safe_additional_data[k] = str(v)

    alert_log(
        user_id=user_id,
        symbol=symbol,
        message=message,
        level='ERROR',
        exception=exception,
        **safe_additional_data
    )
