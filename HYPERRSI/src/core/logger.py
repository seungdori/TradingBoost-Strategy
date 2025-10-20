import json
import logging
import os
import sys
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from .config import settings

#주석 : 로그를 생성하는 순서가 중간중간에 있는 이유는, 에러 로거 등이 다른 로거에 대해 의존적이기 때문이다. 

# 현재 실행 위치를 기준으로 로그 디렉토리 경로 설정
BASE_DIR = Path(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LOG_DIR = BASE_DIR / 'logs' / 'errors'
os.makedirs(LOG_DIR, exist_ok=True)


#get_logger에 대한 활용이 없다.
def get_logger(name: str) -> logging.Logger:
    """
    지정된 이름으로 로거를 생성하고 반환합니다.
    """
    logger = logging.getLogger(name)
    
    if not logger.handlers:  # 핸들러가 없는 경우에만 설정
        logger.setLevel(getattr(logging, settings.LOG_LEVEL))
        
        # 상위 로거로의 전파 방지
        logger.propagate = False
        
        # 포맷터 생성
        formatter = logging.Formatter(settings.LOG_FORMAT)
        
        # 콘솔 핸들러
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # 파일 핸들러
        log_dir = Path(LOG_DIR)
        log_dir.mkdir(exist_ok=True)
        
        file_handler = RotatingFileHandler(
            filename=log_dir / f"{name}.log",
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        # 개발 환경에서는 더 자세한 로깅
        if settings.DEBUG:
            logger.setLevel(logging.DEBUG)
    
    return logger 

def setup_error_logger():
    # 에러 로그 전용 로거 생성
    error_logger = logging.getLogger('error_logger')
    error_logger.setLevel(logging.ERROR)
    
    # 로그 디렉토리 생성
    log_dir = LOG_DIR
    os.makedirs(log_dir, exist_ok=True)
    
    # 파일 핸들러 설정 (날짜별 로테이션)
    error_file_handler = RotatingFileHandler(
        filename=f'{log_dir}/error.log',
        maxBytes=10*1024*1024,  # 10MB
        backupCount=30
    )
    
    # 포맷터 설정 - 'user_id' 필드 의존성 제거
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s [%(name)s:%(lineno)s] - %(message)s'
    )
    error_file_handler.setFormatter(formatter)
    
    error_logger.addHandler(error_file_handler)
    return error_logger

# 전역 에러 로거 인스턴스 생성
error_logger = setup_error_logger()

def setup_order_logger():
    """
    거래 주문(오더) 전용 로거를 설정합니다.
    유저 ID, 심볼, 포지션 타입, 진입 가격 등 트레이딩 정보를 로깅합니다.
    """
    # 주문 로그 전용 로거 생성
    order_logger = logging.getLogger('order_logger')
    order_logger.setLevel(logging.INFO)
    
    # 로그 디렉토리 생성
    log_dir = Path(LOG_DIR).parent / 'orders'
    os.makedirs(log_dir, exist_ok=True)
    
    # 파일 핸들러 설정 (용량 기반 로테이션)
    order_file_handler = RotatingFileHandler(
        filename=f'{log_dir}/trading_orders.log',
        maxBytes=10*1024*1024,  # 10MB
        backupCount=30,
        encoding='utf-8'
    )
    
    # JSON 형식으로 로그를 남기기 위한 사용자 정의 포맷터
    class OrderJSONFormatter(logging.Formatter):
        def format(self, record):
            log_data = {
                'timestamp': datetime.now().isoformat(),
                'level': record.levelname,
                'message': record.getMessage()
            }
            
            # 추가 정보가 있는 경우 로그 데이터에 추가
            if hasattr(record, 'order_data') and record.order_data:
                log_data.update(record.order_data)
                
            return json.dumps(log_data, ensure_ascii=False)
    
    order_file_handler.setFormatter(OrderJSONFormatter())
    order_logger.addHandler(order_file_handler)
    
    # 콘솔에도 출력
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(OrderJSONFormatter())
    order_logger.addHandler(console_handler)
    
    return order_logger

def get_user_order_logger(user_id: str | int) -> logging.Logger:
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
        user_id_int: int
        try:
            user_id_int = int(user_id)
        except (ValueError, TypeError):
            error_logger.warning(f"유효하지 않은 user_id={user_id}, 기본값 0으로 설정합니다.")
            user_id_int = 0  # 기본값 설정
        
        # 사용자 전용 로거 생성
        logger_name = f'order_logger_user_{user_id_int}'
        user_logger = logging.getLogger(logger_name)
        user_logger.setLevel(logging.INFO)

        # 이미 핸들러가 설정되어 있으면 바로 반환
        if user_logger.handlers:
            return user_logger

        try:
            # 사용자별 로그 디렉토리 생성
            log_dir = Path(LOG_DIR).parent / 'orders' / 'users'
            os.makedirs(log_dir, exist_ok=True)

            # 파일 핸들러 설정
            user_file_handler = RotatingFileHandler(
                filename=f'{log_dir}/user_{user_id_int}_orders.log',
                maxBytes=5*1024*1024,  # 5MB
                backupCount=10,
                encoding='utf-8'
            )
            
            # JSON 형식 포맷터
            class OrderJSONFormatter(logging.Formatter):
                def format(self, record: logging.LogRecord) -> str:
                    try:
                        log_data = {
                            'timestamp': datetime.now().isoformat(),
                            'level': record.levelname,
                            'message': record.getMessage(),
                            'user_id': user_id_int  # 항상 user_id 포함
                        }
                        
                        # 추가 정보가 있는 경우 로그 데이터에 추가
                        if hasattr(record, 'order_data') and record.order_data:
                            # 직렬화 가능한 데이터만 추가
                            for k, v in record.order_data.items():
                                try:
                                    json.dumps({k: v})
                                    log_data[k] = v
                                except Exception as e:
                                    log_data[k] = str(v)
                                    
                        return json.dumps(log_data, ensure_ascii=False, default=str)
                    except Exception as e:
                        # 포맷팅 실패 시 최소한의 로깅 시도
                        error_logger.error(f"로그 포맷팅 실패: {str(e)}")
                        return json.dumps({
                            'timestamp': datetime.now().isoformat(),
                            'level': 'ERROR',
                            'message': f'로그 포맷팅 실패: {str(e)}',
                            'user_id': user_id_int
                        }, ensure_ascii=False)
            
            user_file_handler.setFormatter(OrderJSONFormatter())
            user_logger.addHandler(user_file_handler)
            
            # 상위 로거로의 전파 방지
            user_logger.propagate = False
        except Exception as e:
            error_logger.error(f"사용자 로거 설정 실패: {str(e)}")
            # 대체 로거 생성 - 파일 대신 콘솔에만 출력
            fallback_handler = logging.StreamHandler()
            fallback_handler.setFormatter(logging.Formatter('[%(asctime)s] - %(message)s'))
            user_logger.addHandler(fallback_handler)
        
        return user_logger
    except Exception as e:
        error_logger.error(f"get_user_order_logger 함수 실행 중 오류: {str(e)}", exc_info=True)
        # 최후의 보호장치 - 기본 로거 반환
        fallback_logger = logging.getLogger('fallback_logger')
        if not fallback_logger.handlers:
            fallback_handler = logging.StreamHandler()
            fallback_logger.addHandler(fallback_handler)
        return fallback_logger


def setup_debug_logger(name='debug_logger'):
    """
    디버깅 목적의 특별 로거를 설정합니다.
    복잡한 컴포넌트나 모듈의 상세 동작을 추적하고 디버깅하는 데 사용됩니다.
    
    Args:
        name: 로거 이름 (기본값: 'debug_logger')
    
    Returns:
        logging.Logger: 디버깅용 로거 인스턴스
    """
    # 디버깅 로그 전용 로거 생성
    debug_logger = logging.getLogger(name)
    debug_logger.setLevel(logging.DEBUG)
    
    # 로그 디렉토리 생성
    log_dir = Path(LOG_DIR).parent / 'debug'
    os.makedirs(log_dir, exist_ok=True)
    
    # 파일 핸들러 설정 (날짜별 로그 파일)
    current_date = datetime.now().strftime('%Y-%m-%d')
    debug_file_handler = RotatingFileHandler(
        filename=f'{log_dir}/{name}_{current_date}.log',
        maxBytes=50*1024*1024,  # 50MB
        backupCount=10,
        encoding='utf-8'
    )
    
    # 상세한 정보를 포함하는 포맷터
    class DetailedJsonFormatter(logging.Formatter):
        def format(self, record):
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
    
    debug_file_handler.setFormatter(DetailedJsonFormatter())
    debug_logger.addHandler(debug_file_handler)
    
    # 콘솔 출력 핸들러 (개발용)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(DetailedJsonFormatter())
    debug_logger.addHandler(console_handler)
    
    return debug_logger

# 전역 디버그 로거 인스턴스 생성
debug_logger = setup_debug_logger()

def setup_alert_logger():
    """
    봇의 시작, 종료, 오류 등 중요 알림을 위한 전용 로거를 설정합니다.
    """
    # 알림 로그 전용 로거 생성
    alert_logger = logging.getLogger('alert_logger')
    alert_logger.setLevel(logging.INFO)
    
    # 로그 디렉토리 생성
    log_dir = Path(LOG_DIR).parent / 'alerts'
    os.makedirs(log_dir, exist_ok=True)
    
    # 파일 핸들러 설정 (날짜별 로그 파일)
    current_date = datetime.now().strftime('%Y-%m-%d')
    alert_file_handler = RotatingFileHandler(
        filename=f'{log_dir}/system_alerts_{current_date}.log',
        maxBytes=10*1024*1024,  # 10MB
        backupCount=30,
        encoding='utf-8'
    )
    
    # JSON 형식으로 로그를 남기기 위한 사용자 정의 포맷터
    class AlertJSONFormatter(logging.Formatter):
        def format(self, record):
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
    
    alert_file_handler.setFormatter(AlertJSONFormatter())
    alert_logger.addHandler(alert_file_handler)
    
    # 콘솔에도 출력
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(AlertJSONFormatter())
    alert_logger.addHandler(console_handler)
    
    return alert_logger

# 전역 알림 로거 인스턴스 생성
alert_logger = setup_alert_logger()

def log_debug(
    module: str,
    function: str,
    message: str,
    level: str = 'DEBUG',
    exception: Exception | None = None,
    **additional_data: Any
) -> None:
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
    
    debug_logger.handle(record)

def log_dual_side_debug(
    user_id: str,
    symbol: str,
    function_name: str,
    message: str,
    level: str = 'DEBUG',
    exception: Exception | None = None,
    **additional_data: Any
) -> None:
    """
    dual_side_entry 모듈 전용 디버깅 로그 함수입니다.
    양방향 엔트리 관련 로직을 추적하기 위한 특별 로거입니다.
    
    Args:
        user_id: 사용자 ID
        symbol: 거래 심볼
        function_name: 함수 이름
        message: 디버그 메시지
        level: 로그 레벨 ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
        exception: 예외 객체 (오류 발생 시)
        **additional_data: 추가 디버깅 데이터
    """
    # 기본 정보 설정
    data = {
        'user_id': user_id,
        'symbol': symbol
    }
    
    # 추가 데이터 병합
    data.update(additional_data)
    
    # 디버그 로그 기록
    log_debug(
        module='dual_side_entry',
        function=function_name,
        message=message,
        level=level,
        exception=exception,
        **data
    )
    
    
def alert_log(
    user_id: str | int,
    symbol: str,
    message: str,
    level: str = 'INFO',
    exception: Exception | None = None,
    **additional_data: Any
) -> None:
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
        # 파라미터 안전성 검증 및 기본값 설정
        user_id_int: int
        try:
            user_id_int = int(user_id)
        except (ValueError, TypeError):
            user_id_int = 0  # 기본값 설정
            additional_data['original_user_id'] = str(user_id)  # 원래 값 보존
        
        if not symbol or not isinstance(symbol, str):
            symbol = 'UNKNOWN'
            additional_data['original_symbol'] = str(symbol)  # 원래 값 보존
            
        if not message or not isinstance(message, str):
            message = str(message) if message is not None else '메시지 없음'
            
        # 로그 레벨 설정 (잘못된 레벨은 INFO로 기본 설정)
        try:
            log_level = getattr(logging, level.upper())
        except (AttributeError, TypeError):
            log_level = logging.INFO
            level = 'INFO'
        
        # 알림 데이터 준비
        alert_data = {
            'user_id': user_id_int,
            'symbol': symbol,
            'message': message,
            'alert_type': 'system_alert'
        }
        
        # 추가 데이터 병합
        if additional_data:
            # 추가 데이터 안전성 확인 - 직렬화 가능한 데이터만 포함
            safe_additional_data = {}
            for key, value in additional_data.items():
                try:
                    # 직렬화 테스트
                    json.dumps({key: value}, default=str)
                    safe_additional_data[key] = value
                except (TypeError, OverflowError, ValueError):
                    # 직렬화 불가능한 경우 문자열로 변환
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
        try:
            alert_logger.handle(record)
        except Exception as e:
            error_logger.error(f"알림 로거 처리 실패: {str(e)}")
        
        # 사용자별 로그 디렉토리 및 파일
        log_dir = Path(LOG_DIR).parent / 'alerts' / 'users'
        os.makedirs(log_dir, exist_ok=True)
        user_log_file = log_dir / f'user_{user_id_int}_alerts.log'
        
        # 사용자별 로그 파일에 JSON 형식으로 직접 기록
        try:
            with open(user_log_file, 'a', encoding='utf-8') as f:
                # 타임스탬프 추가
                alert_data['timestamp'] = datetime.now().isoformat()
                
                # 예외 정보가 있는 경우 추가
                if exception:
                    try:
                        alert_data['error'] = {
                            'type': type(exception).__name__,
                            'message': str(exception),
                            'traceback': ''.join(traceback.format_exception(type(exception), exception, exception.__traceback__))
                        }
                    except Exception as ex:
                        alert_data['error'] = {
                            'type': 'Error',
                            'message': f'예외 정보 직렬화 실패: {str(ex)}',
                            'original_error': str(exception)
                        }
                
                f.write(json.dumps(alert_data, ensure_ascii=False, default=str) + '\n')
        except Exception as e:
            error_logger.error(f"사용자별 알림 로그 파일 쓰기 실패: {str(e)}")
        
        # 로그 레벨이 ERROR 이상이면 에러 로거에도 기록
        if log_level >= logging.ERROR:
            try:
                error_logger.log(log_level, f"알림 오류 - 사용자: {user_id}, 심볼: {symbol}, 메시지: {message}", 
                                exc_info=exception if exception else None)
            except Exception as e:
                error_logger.error(f"에러 로거 처리 실패: {str(e)}")
                
    except Exception as e:
        # 최후의 보호장치 - 로깅 자체가 실패한 경우
        try:
            error_logger.error(f"알림 로깅 과정에서 예상치 못한 오류 발생: {str(e)}", exc_info=True)
        except Exception as e:
            # 모든 로깅 시도가 실패한 경우 콘솔에 출력
            print(f"[CRITICAL] 알림 로깅 완전 실패: {str(e)}")

def log_order(
    user_id: str,
    symbol: str,
    action_type: str,
    position_side: str,
    price: float | None = None,
    quantity: float | None = None,
    level: int | None = None,
    **additional_data: Any
) -> None:
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
        # 파라미터 안전성 검증 및 기본값 설정
        user_id_int: int
        try:
            user_id_int = int(user_id)
        except (ValueError, TypeError):
            user_id_int = 0  # 기본값 설정
            additional_data['original_user_id'] = str(user_id)  # 원래 값 보존
        
        if not symbol or not isinstance(symbol, str):
            symbol = 'UNKNOWN'
            additional_data['original_symbol'] = str(symbol)  # 원래 값 보존
            
        if not action_type or not isinstance(action_type, str):
            action_type = str(action_type) if action_type is not None else 'unknown'
            
        if not position_side or not isinstance(position_side, str):
            position_side = str(position_side) if position_side is not None else 'unknown'
        
        # 숫자 데이터 검증
        try:
            price = float(price) if price is not None else None
        except (ValueError, TypeError):
            additional_data['original_price'] = str(price)
            price = None
            
        try:
            quantity = float(quantity) if quantity is not None else None
        except (ValueError, TypeError):
            additional_data['original_quantity'] = str(quantity)
            quantity = None
            
        try:
            level = int(level) if level is not None else None
        except (ValueError, TypeError):
            additional_data['original_level'] = str(level)
            level = None
        
        log_data = {
            'user_id': user_id_int,
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
                # 직렬화 가능한지 확인
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
        try:
            order_logger.handle(record)
        except Exception as e:
            error_logger.error(f"주문 로거 처리 실패: {str(e)}")
        
        # 사용자별 로그 파일에도 기록
        try:
            user_logger = get_user_order_logger(user_id_int)
            user_logger.handle(record)
        except Exception as e:
            error_logger.error(f"사용자별 주문 로거 처리 실패: {str(e)}")

            # 직접 로그 파일에 기록 시도
            try:
                log_dir = Path(LOG_DIR).parent / 'orders' / 'users'
                os.makedirs(log_dir, exist_ok=True)
                log_file = log_dir / f'user_{user_id_int}_orders_fallback.log'
                
                with open(log_file, 'a', encoding='utf-8') as f:
                    log_data['timestamp'] = datetime.now().isoformat()
                    log_data['message'] = log_message
                    log_data['note'] = '로거 처리 실패로 인한 직접 기록'
                    f.write(json.dumps(log_data, ensure_ascii=False, default=str) + '\n')
            except Exception as ex:
                error_logger.error(f"대체 로그 파일 쓰기 실패: {str(ex)}")
                
    except Exception as e:
        # 최후의 보호장치 - 로깅 자체가 실패한 경우
        try:
            error_logger.error(f"주문 로깅 과정에서 예상치 못한 오류 발생: {str(e)}", exc_info=True)
        except Exception as e:
            # 모든 로깅 시도가 실패한 경우 콘솔에 출력
            print(f"[CRITICAL] 주문 로깅 완전 실패: {str(e)}")

def get_order_logs_by_user_id(user_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    """
    특정 사용자 ID에 해당하는 주문 로그를 조회합니다.

    Args:
        user_id: 조회할 사용자 ID
        limit: 반환할 최대 로그 수 (기본값: 100)
        offset: 건너뛸 로그 수 (기본값: 0)

    Returns:
        list: 사용자의 주문 로그 목록
    """
    try:
        # 파라미터 안전성 검증
        user_id_int: int
        try:
            user_id_int = int(user_id)
            limit = max(1, min(int(limit), 1000))  # 1~1000 사이로 제한
            offset = max(0, int(offset))
        except (ValueError, TypeError):
            error_logger.error(f"잘못된 파라미터: user_id={user_id}, limit={limit}, offset={offset}")
            return []  # 안전한 기본값 반환
        
        log_dir = Path(LOG_DIR).parent / 'orders'
        log_file = log_dir / 'trading_orders.log'
        
        if not log_file.exists():
            return []
        
        user_logs = []
        count = 0
        skipped = 0
        
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    try:
                        log_entry = json.loads(line)
                        # user_id가 일치하는 로그만 필터링
                        if 'user_id' in log_entry and log_entry['user_id'] == user_id_int:
                            if skipped < offset:
                                skipped += 1
                                continue
                            
                            user_logs.append(log_entry)
                            count += 1
                            
                            if count >= limit:
                                break
                    except json.JSONDecodeError:
                        error_logger.warning(f"로그 파일 {log_file} 라인 {line_num}에서 JSON 파싱 오류")
                        continue
                    except Exception as e:
                        error_logger.error(f"로그 파싱 중 오류 발생: {str(e)}")
                        continue
        except IOError as e:
            error_logger.error(f"로그 파일 {log_file} 읽기 실패: {str(e)}")
            # 대체 파일 시도 (fallback)
            fallback_file = log_dir / 'trading_orders_backup.log'
            if fallback_file.exists():
                try:
                    with open(fallback_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            try:
                                log_entry = json.loads(line)
                                if 'user_id' in log_entry and log_entry['user_id'] == user_id_int:
                                    if skipped < offset:
                                        skipped += 1
                                        continue
                                    
                                    user_logs.append(log_entry)
                                    count += 1
                                    
                                    if count >= limit:
                                        break
                            except Exception:
                                continue
                except Exception:
                    error_logger.error(f"대체 로그 파일 {fallback_file} 읽기도 실패")
        
        return user_logs
    except Exception as e:
        error_logger.error(f"get_order_logs_by_user_id 함수 실행 중 오류: {str(e)}", exc_info=True)
        return []  # 안전한 기본값 반환

def get_order_logs_by_date_range(start_date: datetime, end_date: datetime, user_id: str | None = None, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    """
    특정 날짜 범위 내의 주문 로그를 조회합니다. 선택적으로 사용자 ID로 필터링할 수 있습니다.

    Args:
        start_date: 시작 날짜 (datetime 객체)
        end_date: 종료 날짜 (datetime 객체)
        user_id: 조회할 사용자 ID (선택적)
        limit: 반환할 최대 로그 수 (기본값: 100)
        offset: 건너뛸 로그 수 (기본값: 0)

    Returns:
        list: 조건에 맞는 주문 로그 목록
    """
    try:
        # start_date와 end_date 교정
        if start_date > end_date:
            start_date, end_date = end_date, start_date  # 자동 교정

        user_id_int: int | None = None
        try:
            limit = max(1, min(int(limit), 1000))  # 1~1000 사이로 제한
            offset = max(0, int(offset))
            if user_id is not None:
                user_id_int = int(user_id)
        except (ValueError, TypeError):
            error_logger.error(f"잘못된 파라미터: limit={limit}, offset={offset}, user_id={user_id}")
            return []  # 안전한 기본값 반환
            
        log_dir = Path(LOG_DIR).parent / 'orders'
        log_file = log_dir / 'trading_orders.log'
        
        if not log_file.exists():
            return []
        
        filtered_logs = []
        count = 0
        skipped = 0
        
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    try:
                        log_entry = json.loads(line)
                        
                        # 타임스탬프 파싱
                        if 'timestamp' in log_entry:
                            try:
                                log_time = datetime.fromisoformat(log_entry['timestamp'])
                            except (ValueError, TypeError):
                                # 타임스탬프 형식이 잘못된 경우 스킵
                                continue
                            
                            # 날짜 범위 체크
                            if start_date <= log_time <= end_date:
                                # 사용자 ID 필터링 (지정된 경우)
                                if user_id_int is not None:
                                    if 'user_id' in log_entry and log_entry['user_id'] == user_id_int:
                                        if skipped < offset:
                                            skipped += 1
                                            continue

                                        filtered_logs.append(log_entry)
                                        count += 1
                                else:
                                    if skipped < offset:
                                        skipped += 1
                                        continue

                                    filtered_logs.append(log_entry)
                                    count += 1
                                
                                if count >= limit:
                                    break
                    except json.JSONDecodeError:
                        error_logger.warning(f"로그 파일 {log_file} 라인 {line_num}에서 JSON 파싱 오류")
                        continue
                    except Exception as e:
                        error_logger.error(f"로그 파싱 중 오류 발생: {str(e)}")
                        continue
        except IOError as e:
            error_logger.error(f"로그 파일 {log_file} 읽기 실패: {str(e)}")
        
        return filtered_logs
    except Exception as e:
        error_logger.error(f"get_order_logs_by_date_range 함수 실행 중 오류: {str(e)}", exc_info=True)
        return []  # 안전한 기본값 반환

def get_user_order_logs_from_file(user_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    """
    사용자별 로그 파일에서 직접 주문 로그를 조회합니다.
    이 함수는 사용자별 로그 파일이 존재할 때 더 효율적입니다.

    Args:
        user_id: 조회할 사용자 ID
        limit: 반환할 최대 로그 수 (기본값: 100)
        offset: 건너뛸 로그 수 (기본값: 0)

    Returns:
        list: 사용자의 주문 로그 목록
    """
    try:
        # 파라미터 안전성 검증
        user_id_int: int
        try:
            user_id_int = int(user_id)
            limit = max(1, min(int(limit), 1000))  # 1~1000 사이로 제한
            offset = max(0, int(offset))
        except (ValueError, TypeError):
            error_logger.error(f"잘못된 파라미터: user_id={user_id}, limit={limit}, offset={offset}")
            return []  # 안전한 기본값 반환
            
        log_dir = Path(LOG_DIR).parent / 'orders' / 'users'
        log_file = log_dir / f'user_{user_id_int}_orders.log'

        # 사용자별 로그 파일이 없으면 전체 로그에서 필터링
        if not log_file.exists():
            print(f"{user_id_int}의 로그 파일이 없어서 user_id를 기준으로 로그 파일을 가져옵니다.")
            return get_order_logs_by_user_id(str(user_id_int), limit, offset)
        
        user_logs = []
        count = 0
        skipped = 0
        
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    try:
                        log_entry = json.loads(line)
                        # 필요한 offset만큼 건너뛰기
                        if skipped < offset:
                            skipped += 1
                            continue
                        
                        # 로그 엔트리 유효성 확인
                        if 'user_id' not in log_entry or log_entry['user_id'] != user_id_int:
                            continue  # 잘못된 사용자 ID인 경우 스킵
                        
                        user_logs.append(log_entry)
                        count += 1
                        
                        if count >= limit:
                            break
                    except json.JSONDecodeError:
                        error_logger.warning(f"로그 파일 {log_file} 라인 {line_num}에서 JSON 파싱 오류")
                        continue
                    except Exception as e:
                        error_logger.error(f"로그 파싱 중 오류 발생: {str(e)}")
                        continue
        except IOError as e:
            error_logger.error(f"로그 파일 {log_file} 읽기 실패: {str(e)}")
            # 사용자 로그 파일 읽기 실패시 전체 로그에서 필터링 시도
            try:
                return get_order_logs_by_user_id(str(user_id_int), limit, offset)
            except Exception:
                error_logger.error(f"대체 메서드 get_order_logs_by_user_id 호출 실패")
                return []
        
        return user_logs
    except Exception as e:
        error_logger.error(f"get_user_order_logs_from_file 함수 실행 중 오류: {str(e)}", exc_info=True)
        return []  # 안전한 기본값 반환

# 편의 함수: 봇 시작 로깅
def log_bot_start(user_id: str, symbol: str, config: dict[str, Any] | None = None) -> None:
    """
    트레이딩 봇 시작을 로깅합니다.

    Args:
        user_id: 사용자 ID
        symbol: 거래 심볼
        config: 봇 설정 정보
    """
    try:
        message = f"트레이딩 봇 시작 - {symbol}"
        additional_data: dict[str, Any] = {'event_type': 'bot_start'}

        if config:
            # config 데이터가 직렬화 가능한지 확인
            try:
                json.dumps(config)
                additional_data = {
                    'config': config,
                    'event_type': 'bot_start'
                }
            except (TypeError, OverflowError, ValueError):
                # 직렬화 불가능한 경우 주요 필드만 추출
                safe_config = {}
                for k, v in config.items():
                    try:
                        json.dumps({k: v})
                        safe_config[k] = v
                    except Exception as e:
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
    except Exception as e:
        error_logger.error(f"봇 시작 로깅 실패: {str(e)}", exc_info=True)
        print(f"[ERROR] 봇 시작 로깅 실패: {str(e)}")

# 편의 함수: 봇 종료 로깅
def log_bot_stop(user_id: str, symbol: str, reason: str | None = None) -> None:
    """
    트레이딩 봇 종료를 로깅합니다.

    Args:
        user_id: 사용자 ID
        symbol: 거래 심볼
        reason: 종료 이유
    """
    try:
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
    except Exception as e:
        error_logger.error(f"봇, 종료 로깅 실패: {str(e)}", exc_info=True)
        print(f"[ERROR] 봇 종료 로깅 실패: {str(e)}")

# 편의 함수: 봇 오류 로깅
def log_bot_error(user_id: str, symbol: str, error_message: str, exception: Exception | None = None, **additional_data: Any) -> None:
    """
    트레이딩 봇 오류를 로깅합니다.

    Args:
        user_id: 사용자 ID
        symbol: 거래 심볼
        error_message: 오류 메시지
        exception: 예외 객체
        **additional_data: 추가 데이터 (예: component, error_type 등)
    """
    try:
        message = f"트레이딩 봇 오류 - {symbol} - {error_message}"
        
        # 추가 데이터 안전성 검증
        safe_additional_data = {'event_type': 'bot_error'}
        for k, v in additional_data.items():
            try:
                json.dumps({k: v})
                safe_additional_data[k] = v
            except Exception as e:
                safe_additional_data[k] = str(v)
        
        alert_log(
            user_id=user_id,
            symbol=symbol,
            message=message,
            level='ERROR',
            exception=exception,
            **safe_additional_data
        )
    except Exception as e:
        error_logger.error(f"봇 오류 로깅 실패: {str(e)}", exc_info=True)
        print(f"[ERROR] 봇 오류 로깅 실패: {str(e)}")



#===로거 생성====
# 전역 주문 로거 인스턴스 생성
order_logger = setup_order_logger()
