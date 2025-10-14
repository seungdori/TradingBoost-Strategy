import asyncio
import json
import logging
import signal
import threading
import time
import traceback
from contextlib import asynccontextmanager, contextmanager

# nest_asyncio import - Celery worker에서 이벤트 루프 중첩 실행 허용
try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    logger = logging.getLogger(__name__)
    logger.warning("nest_asyncio not installed. Event loop nesting may fail.")

# from HYPERRSI.src.core.event_loop_manager import EventLoopManager  # 이벤트 루프 매니저 제거
from datetime import datetime, timedelta, timezone
from types import TracebackType
from typing import Any, AsyncGenerator, Dict, List, Optional, Type

from billiard.exceptions import SoftTimeLimitExceeded, TimeLimitExceeded

from HYPERRSI.src.bot.telegram_message import send_telegram_message
from HYPERRSI.src.core.celery_task import celery_app
from HYPERRSI.src.trading.execute_trading_logic import execute_trading_logic
from shared.database.redis_helper import get_redis_client

logger = logging.getLogger(__name__)

# Redis 키 상수 정의 (user_id -> okx_uid)
REDIS_KEY_TRADING_STATUS = "user:{okx_uid}:trading:status"
REDIS_KEY_TASK_RUNNING = "user:{okx_uid}:task_running"
REDIS_KEY_TASK_ID = "user:{okx_uid}:task_id"
REDIS_KEY_SYMBOL_STATUS = "user:{okx_uid}:symbol:{symbol}:status"
REDIS_KEY_PREFERENCES = "user:{okx_uid}:preferences"  # 선호도 키도 변경
REDIS_KEY_LAST_EXECUTION = "user:{okx_uid}:last_execution"
REDIS_KEY_LAST_LOG_TIME = "user:{okx_uid}:last_log_time"
REDIS_KEY_USER_LOCK = "lock:user:{okx_uid}:{symbol}:{timeframe}" # 락 키 이름 변경 (user -> okx)

# 모듈 수준의 이벤트 루프 관리
_loop = None
_loop_lock = threading.Lock()
_current_task = None  # 현재 실행 중인 작업 추적을 위한 변수
_child_tasks = set()  # 생성된 모든 자식 태스크 추적

# 비동기 컨텍스트 매니저 정의
@asynccontextmanager
async def trading_context(okx_uid: str, symbol: str) -> AsyncGenerator[None, None]: # user_id -> okx_uid (타입은 str 가정)
    """
    트레이딩 작업을 위한 비동기 컨텍스트 매니저.
    모든 리소스가 적절히 정리되도록 보장합니다.
    """
    # 태스크와 리소스 추적

    redis = await get_redis_client()
    task = asyncio.current_task()
    local_resources: List[Any] = []
    
    logger.debug(f"[{okx_uid}] 트레이딩 컨텍스트 시작: {symbol}")
    
    try:
        # 컨텍스트 초기화 작업
        # 트레이딩에 필요한 리소스 설정
        yield
    except asyncio.CancelledError:
        logger.warning(f"[{okx_uid}] 트레이딩 컨텍스트가 취소되었습니다: {symbol}")
        # 취소 처리를 위한 특별 정리 작업
        raise  # 반드시 다시 발생시켜 상위 호출자에게 알림
    except Exception as e:
        logger.error(f"[{okx_uid}] 트레이딩 컨텍스트 오류: {str(e)}")
        raise
    finally:
        # 모든 리소스 정리 작업
        logger.debug(f"[{okx_uid}] 트레이딩 컨텍스트 종료 정리 작업: {symbol}")
        
        # 생성된 모든 자식 태스크 취소
        for resource in local_resources:
            try:
                # 리소스 정리 로직 (db 연결 종료 등)
                pass
            except Exception as e:
                logger.error(f"[{okx_uid}] 리소스 정리 중 오류: {str(e)}")
        
        # 태스크 상태 정리 (okx_uid 사용)
        try:
            await redis.delete(REDIS_KEY_TASK_RUNNING.format(okx_uid=okx_uid))
        except Exception as e:
            logger.error(f"[{okx_uid}] Redis 정리 중 오류: {str(e)}")

# 트레이딩 래퍼 함수
async def execute_trading_with_context(okx_uid: str, symbol: str, timeframe: str, restart: bool = False) -> None: # user_id -> okx_uid
    """
    컨텍스트 매니저를 사용하여 트레이딩 로직을 실행하는 래퍼 함수
    """
    async with trading_context(okx_uid, symbol):
        # 명시적인 try/except로 감싸 태스크 취소 적절히 처리
        try:
            user_id = okx_uid # user_id -> okx_uid
            # execute_trading_logic 호출 시 okx_uid 전달 (가정)
            await execute_trading_logic(
                user_id=user_id, symbol=symbol, timeframe=timeframe, restart=restart
            )
        except asyncio.CancelledError:
            logger.warning(f"[{okx_uid}] 트레이딩 로직이 취소되었습니다: {symbol}")
            raise
        except Exception as e:
            logger.error(f"[{okx_uid}] 트레이딩 로직 오류: {str(e)}")
            raise

# 태스크 추적 기능 강화
def register_child_task(task):
    """
    자식 태스크를 글로벌 세트에 등록하여 추적
    """
    global _child_tasks
    _child_tasks.add(task)
    
    # 완료 시 자동으로 세트에서 제거하는 콜백 추가
    def _remove_task(t):
        if t in _child_tasks:
            _child_tasks.remove(t)
    
    task.add_done_callback(_remove_task)
    return task

def cancel_all_child_tasks():
    """
    모든 자식 태스크 취소
    """
    global _child_tasks
    for task in list(_child_tasks):
        if not task.done():
            task.cancel()

# 타임아웃 시그널 핸들러
def timeout_handler(signum, frame):
    """
    소프트/하드 타임아웃 시그널을 처리하는 핸들러
    현재 실행 중인 태스크를 취소합니다
    """
    global _current_task, _loop
    logger.warning(f"타임아웃 감지! 시그널: {signum}")
    
    # 현재 실행 중인 태스크가 있으면 취소
    if _current_task and not _current_task.done():
        logger.warning(f"실행 중인 비동기 태스크를 취소합니다: {_current_task}")
        _loop.call_soon_threadsafe(_current_task.cancel)
    
    # 모든 자식 태스크 취소
    cancel_all_child_tasks()
    
    # 시그널에 따라 적절한 예외 발생
    if signum == signal.SIGALRM:  # 하드 타임아웃
        raise TimeLimitExceeded()
    else:  # 소프트 타임아웃
        raise SoftTimeLimitExceeded()

# 타임아웃 시그널 핸들러 등록
signal.signal(signal.SIGALRM, timeout_handler)
signal.signal(signal.SIGTERM, timeout_handler)

def get_event_loop():
    """
    스레드 안전한 방식으로 이벤트 루프를 가져오는 함수
    """
    global _loop
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_loop)
        return _loop

@contextmanager
def timeout_protection():
    """
    타임아웃 발생 시 이벤트 루프와 관련 리소스를 정리하는 컨텍스트 매니저
    """
    try:
        yield
    except (SoftTimeLimitExceeded, TimeLimitExceeded) as e:
        logger.warning(f"태스크 타임아웃 감지: {str(e)}")
        # 모든 자식 태스크 취소
        cancel_all_child_tasks()
        # 이벤트 루프 내 진행 중인 태스크 취소
        cleanup_event_loop()
        # 예외 다시 발생시켜 Celery가 처리하도록 함
        raise

def run_async(coroutine, timeout=45):
    """
    비동기 코루틴을 동기적으로 실행하는 유틸리티 함수

    nest_asyncio가 적용되어 있어 이미 실행 중인 이벤트 루프에서도 안전하게 실행 가능
    타임아웃 및 리소스 정리 지원

    Solo pool 모드에서는 이벤트 루프를 재사용하여 Redis 연결 문제를 방지
    """
    global _loop

    # 기존 글로벌 이벤트 루프가 있고 닫히지 않았다면 재사용
    if _loop is not None and not _loop.is_closed():
        loop = _loop
        logger.debug("기존 글로벌 이벤트 루프 재사용")
        should_close = False
    else:
        # 이벤트 루프가 없거나 닫혀있으면 새로 생성
        try:
            # 먼저 실행 중인 이벤트 루프가 있는지 확인
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                logger.debug("닫힌 이벤트 루프 감지, 새 루프 생성")
            else:
                logger.debug("기존 이벤트 루프 재사용")
        except RuntimeError:
            # 이벤트 루프가 없으면 새로 생성
            logger.debug("새 이벤트 루프 생성")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # 글로벌 루프로 저장 (재사용을 위해)
        _loop = loop
        should_close = False  # Solo pool에서는 이벤트 루프를 닫지 않음

        # Redis 클라이언트는 lazy initialization으로 처리됨

    try:
        # wait_for로 타임아웃 설정하여 실행
        return loop.run_until_complete(asyncio.wait_for(coroutine, timeout=timeout))
    except asyncio.TimeoutError:
        logger.warning(f"비동기 작업이 타임아웃되었습니다 ({timeout}초)")
        raise
    except Exception as e:
        logger.error(f"비동기 작업 실행 중 오류: {str(e)}")
        raise
    finally:
        # Solo pool 모드에서는 이벤트 루프를 닫지 않음 (재사용)
        # 단, 미완료 태스크는 정리
        if not should_close:
            try:
                pending = asyncio.all_tasks(loop)
                for t in pending:
                    # 현재 실행 중인 태스크는 제외하고 취소
                    if not t.done() and t != asyncio.current_task(loop):
                        t.cancel()
            except Exception as cleanup_error:
                logger.debug(f"태스크 정리 중 오류 (무시됨): {str(cleanup_error)}")

# 태스크 실행 상태 관리 함수들
async def check_if_running(okx_uid: str) -> bool: # user_id -> okx_uid
    """
    사용자의 트레이딩 상태가 여전히 'running'인지 확인
    """

    redis = await get_redis_client()
    status = await redis.get(REDIS_KEY_TRADING_STATUS.format(okx_uid=okx_uid))
    
    # 바이트 문자열을 디코딩
    if isinstance(status, bytes):
        status = status.decode('utf-8')
    
    # 문자열 정규화 (공백 제거 및 따옴표 제거)
    if status:
        status = status.strip().strip('"\'')

    return bool(status == "running")

async def set_trading_status(okx_uid: str, status: str) -> None: # user_id -> okx_uid
    """
    사용자의 트레이딩 상태 설정
    """

    redis = await get_redis_client()
    key = REDIS_KEY_TRADING_STATUS.format(okx_uid=okx_uid)
    await redis.set(key, status)
    logger.info(f"[{okx_uid}] 트레이딩 상태를 '{status}'로 설정")

async def set_symbol_status(okx_uid: str, symbol: str, status: str) -> None: # user_id -> okx_uid
    """
    특정 심볼에 대한 트레이딩 상태 설정
    """

    redis = await get_redis_client()
    key = REDIS_KEY_SYMBOL_STATUS.format(okx_uid=okx_uid, symbol=symbol)
    await redis.set(key, status)
    logger.info(f"[{okx_uid}] {symbol} 심볼 상태를 '{status}'로 설정")

async def set_task_running(okx_uid: str, running: bool = True, expiry: int = 900) -> None: # user_id -> okx_uid
    """
    사용자의 태스크 실행 상태를 설정
    만료 시간을 설정하여 비정상 종료 시에만 만료되도록 함
    """

    redis = await get_redis_client()
    status_key = REDIS_KEY_TASK_RUNNING.format(okx_uid=okx_uid)
    
    if running:
        # 현재 시간도 함께 저장하여 시작 시간 추적
        current_time = datetime.now().timestamp()
        await redis.delete(status_key)
        await redis.hset(status_key, mapping={
            "status": "running",
            "started_at": str(current_time)
        })
        await redis.expire(status_key, expiry)
        logger.debug(f"[{okx_uid}] 태스크 상태를 'running'으로 설정 (만료: {expiry}초)")
    else:
        await redis.delete(status_key)
        logger.debug(f"[{okx_uid}] 태스크 상태를 삭제함")

async def is_task_running(okx_uid: str) -> bool: # user_id -> okx_uid
    """
    현재 사용자에 대한 태스크가 실행 중인지 확인
    실행 중이면서도 오래된 태스크인 경우 상태를 초기화하는 로직 추가
    Redis 키 타입 오류 처리 추가
    """

    redis = await get_redis_client()
    status_key = REDIS_KEY_TASK_RUNNING.format(okx_uid=okx_uid)
    
    try:
        # 키 타입 확인 (hash인지 검증)
        key_type = await redis.type(status_key)
        
        # 키가 없거나 해시가 아닌 경우
        if key_type == "none" or key_type != "hash":
            if key_type != "none":
                logger.warning(f"[{okx_uid}] 태스크 상태 키가 잘못된 타입({key_type})입니다. 초기화합니다.")
                await redis.delete(status_key)
            else:
                logger.debug(f"[{okx_uid}] 태스크 상태 없음 (실행 중 아님)")
            return False
            
        # 정상적인 해시 타입이면 값을 가져옴
        status = await redis.hgetall(status_key)
        
        if not status:
            logger.debug(f"[{okx_uid}] 태스크 상태 없음 (실행 중 아님)")
            return False
            
        # 너무 오래된 태스크인지 확인 (60초)
        if "started_at" in status:
            try:
                started_at = float(status["started_at"])
                current_time = datetime.now().timestamp()
                
                # 60초 이상 실행 중인 경우 비정상으로 간주하고 초기화
                if current_time - started_at > 60:
                    logger.warning(f"[{okx_uid}] 오래된 태스크 감지 (60초 초과). 상태 초기화함")
                    await redis.delete(status_key)
                    return False
                    
                elapsed = int(current_time - started_at)
                logger.debug(f"[{okx_uid}] 태스크 실행 시간: {elapsed}초")
            except (ValueError, TypeError):
                logger.warning(f"[{okx_uid}] 시작 시간 파싱 오류: {status.get('started_at')}")
        
        is_running: bool = status.get("status") == "running"
        logger.debug(f"[{okx_uid}] 태스크 실행 상태: {is_running}")
        return is_running
        
    except Exception as e:
        logger.error(f"[{okx_uid}] 태스크 실행 상태 확인 중 오류: {str(e)}")
        # 오류 발생 시 안전하게 False 반환
        return False

async def update_last_execution(okx_uid: str, success: bool, error_message: Optional[str] = None) -> None: # user_id -> okx_uid
    """
    마지막 실행 정보 업데이트
    """

    redis = await get_redis_client()
    key = REDIS_KEY_LAST_EXECUTION.format(okx_uid=okx_uid)
    data: Dict[str, Any] = {
        "timestamp": datetime.now().timestamp(),
        "success": success
    }

    if error_message:
        data["error"] = error_message
    
    await redis.set(key, json.dumps(data))

async def get_active_trading_users(): # 내부 로직 변경 필요
    """
    Redis에서 'running' 상태인 모든 활성 사용자 정보(OKX UID 기준) 가져오기
    오류 처리 강화
    """

    redis = await get_redis_client()
    active_users = []
    cursor = '0'
    pattern = 'user:*:trading:status' # 스캔 패턴 변경

    try:
        while cursor != '0':
            cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100)

            for key in keys:
                try:
                    # 키 형식: user:{okx_uid}:trading:status
                    key_parts = key.split(':')
                    if len(key_parts) < 3 or key_parts[0] != 'user' or key_parts[2] != 'trading' or key_parts[3] != 'status':
                        logger.warning(f"예상치 못한 키 형식 발견: {key}")
                        continue

                    okx_uid = key_parts[1] # okx_uid 추출

                    # 상태 키 타입 확인
                    key_type = await redis.type(key)

                    # 올바른 타입(string)이 아니면 다음으로
                    if key_type != "string":
                        logger.warning(f"[{okx_uid}] 트레이딩 상태 키가 잘못된 타입({key_type})입니다.")
                        continue

                    status = await redis.get(key)
                    
                    # 바이트 문자열을 디코딩
                    if isinstance(status, bytes):
                        status = status.decode('utf-8')
                    
                    # 문자열 정규화 (공백 제거 및 따옴표 제거)
                    if status:
                        status = status.strip().strip('"\'')

                    if status == "running":
                        try:
                            # 이미 실행 중인 태스크가 있는지 확인 (okx_uid 사용)
                            is_running = await is_task_running(okx_uid)

                            # 실행 중인 태스크가 없거나 오래된 태스크일 경우 강제로 상태 초기화 후 추가
                            if is_running:
                                # 오래된 태스크가 있다면 강제로 초기화
                                task_key = REDIS_KEY_TASK_RUNNING.format(okx_uid=okx_uid)
                                status_data = await redis.hgetall(task_key)

                                if "started_at" in status_data:
                                    started_at = float(status_data["started_at"])
                                    current_time = datetime.now().timestamp()

                                    # 30초 이상 실행 중인 경우 비정상으로 간주하고 초기화
                                    if current_time - started_at > 30:
                                        logger.warning(f"[{okx_uid}] 오래된 태스크 상태 초기화 (30초 초과)")
                                        await redis.delete(task_key)


                            if not is_running:
                                # 선호도 정보 가져오기 (okx_uid 사용)
                                pref_key = REDIS_KEY_PREFERENCES.format(okx_uid=okx_uid) # 변경된 키 사용
                                pref_type = await redis.type(pref_key)

                                if pref_type != "hash":
                                    logger.warning(f"[{okx_uid}] 선호도 키가 잘못된 타입({pref_type})입니다.")
                                    # 선호도 정보가 없으면 이 사용자를 처리할 수 없으므로 스킵
                                    continue

                                preference = await redis.hgetall(pref_key)
                                symbol = preference.get("symbol", "unknown")
                                timeframe = preference.get("timeframe", "unknown")

                                if symbol == "unknown" or timeframe == "unknown":
                                    logger.warning(f"[{okx_uid}] 선호도 정보 불완전: symbol={symbol}, timeframe={timeframe}")
                                    # 선호도 정보가 불완전하면 스킵
                                    continue

                                # 로그 제한 로직 추가 - 5분(300초)에 한 번만 로깅
                                should_log = True
                                current_time = datetime.now().timestamp()

                                try:
                                    # 마지막 로그 시간 가져오기 (okx_uid 사용)
                                    last_log_key = REDIS_KEY_LAST_LOG_TIME.format(okx_uid=okx_uid)
                                    last_log_time = await redis.get(last_log_key)

                                    if last_log_time:
                                        last_time = float(last_log_time)
                                        # 마지막 로그 시간으로부터 300초(5분) 이내면 로깅 스킵
                                        if current_time - last_time < 300:
                                            should_log = False
                                            logger.debug(f"[{okx_uid}] 로그 제한: 마지막 로그 시간 {int(current_time - last_time)}초 전")
                                except Exception as log_err:
                                    logger.debug(f"[{okx_uid}] 로그 제한 확인 중 오류: {str(log_err)}")

                                # 5분이 지났거나 처음 로그하는 경우에만 로그 출력
                                if should_log:
                                    logger.info(f"활성 트레이더 로깅 okx_uid={okx_uid}, symbol={symbol}, timeframe={timeframe}")
                                    # 마지막 로그 시간 업데이트
                                    try:
                                        await redis.set(last_log_key, str(current_time))
                                        # 키 만료 시간 설정 (선택 사항 - 청소를 위해)
                                        await redis.expire(last_log_key, 86400)  # 1일 후 만료
                                    except Exception as update_err:
                                        logger.debug(f"[{okx_uid}] 로그 시간 업데이트 중 오류: {str(update_err)}")

                                active_users.append({
                                    'okx_uid': okx_uid, # user_id -> okx_uid
                                    'symbol': symbol,
                                    'timeframe': timeframe
                                })
                        except Exception as e:
                            logger.error(f"[{okx_uid}] 활성 사용자 처리 중 오류: {str(e)}")
                            continue
                except (ValueError, TypeError, IndexError) as e:
                    logger.warning(f"유효하지 않은 키 형식 또는 파싱 오류: {key}, 오류: {str(e)}")
                    continue
                except Exception as e:
                    logger.error(f"키 처리 중 예상치 못한 오류: {key}, 오류: {str(e)}")
                    continue
    except Exception as e:
        logger.error(f"활성 사용자 가져오기 중 오류: {str(e)}")

    return active_users

@asynccontextmanager
async def acquire_okx_lock(okx_uid: str, symbol: str, timeframe: str, ttl: int = 60) -> AsyncGenerator[bool, None]: # 함수 이름 및 파라미터 변경
    """
    특정 OKX UID, 심볼, 타임프레임 조합에 대한 분산 락을 획득하는 비동기 컨텍스트 매니저

    :param okx_uid: OKX UID
    :param symbol: 트레이딩 심볼
    :param timeframe: 타임프레임
    :param ttl: 락의 유효시간(초)
    :return: 락 획득 성공 여부
    """

    redis = await get_redis_client()
    lock_key = REDIS_KEY_USER_LOCK.format(okx_uid=okx_uid, symbol=symbol, timeframe=timeframe) # 변경된 키 사용 (이름은 유지)
    lock_value = f"{datetime.now().timestamp()}:{threading.get_ident()}"
    acquired = False

    try:
        # 락 획득 시도 (SETNX 패턴)
        acquired = await redis.set(lock_key, lock_value, nx=True, ex=ttl)

        if acquired:
            logger.debug(f"[{okx_uid}] 락 획득 성공: {symbol}/{timeframe}")
            yield True
        else:
            logger.warning(f"[{okx_uid}] 락 획득 실패 (이미 다른 프로세스가 실행 중): {symbol}/{timeframe}")
            yield False
    finally:
        # 락을 획득한 경우에만 해제 시도
        if acquired:
            try:
                # 내가 설정한 락인지 확인 후 삭제
                current_value = await redis.get(lock_key)
                if current_value == lock_value:
                    await redis.delete(lock_key)
                    logger.debug(f"[{okx_uid}] 락 해제 완료: {symbol}/{timeframe}")
            except Exception as e:
                logger.error(f"[{okx_uid}] 락 해제 중 오류: {str(e)}")

@celery_app.task(name='trading_tasks.check_and_execute_trading', ignore_result=True)
def check_and_execute_trading():
    """
    Beat으로 주기적으로 실행되는 태스크.
    활성 사용자를 확인하고(OKX UID 기준), 필요한 경우 트레이딩 태스크를 등록
    """
    try:
        # 활성 사용자 목록 가져오기 - 직접 이벤트 루프 관리
        active_users = run_async(get_active_trading_users()) # 내부 로직에서 okx_uid 반환

        if active_users:
            logger.debug(f"활성 트레이더 목록: {len(active_users)}명")
        else:
            logger.debug("활성 트레이더가 없거나 가져오기 실패")

        for user_data in active_users:
            okx_uid = user_data['okx_uid'] # user_id -> okx_uid
            symbol = user_data['symbol']
            timeframe = user_data['timeframe']

            # 태스크 등록
            try:
                logger.debug(f"[{okx_uid}] 새 트레이딩 사이클 태스크 등록")

                # 락 획득 시도 - 이미 실행 중인 인스턴스 확인 (okx_uid 사용)
                lock_key = REDIS_KEY_USER_LOCK.format(okx_uid=okx_uid, symbol=symbol, timeframe=timeframe)
                lock_exists = run_async(get_redis_client().exists(lock_key))

                if lock_exists:
                    logger.info(f"[{okx_uid}] {symbol}/{timeframe}에 대한 태스크가 이미 실행 중입니다. 스킵합니다.")
                    continue

                # 태스크 실행 상태를 True로 설정 (okx_uid 사용)
                run_async(set_task_running(okx_uid, True, expiry=60))

                # Celery 태스크 등록 (okx_uid 전달)
                task = execute_trading_cycle.apply_async(
                    args=[okx_uid, symbol, timeframe, True], # user_id -> okx_uid
                    expires=300,  # 5분 내 실행되지 않으면 만료
                    retry=True,
                    retry_policy={
                        'max_retries': 3,
                        'interval_start': 1,
                        'interval_step': 2,
                        'interval_max': 5,
                    }
                )

                # 태스크 ID 저장 (okx_uid 사용)
                try:
                    run_async(
                        get_redis_client().set(
                            REDIS_KEY_TASK_ID.format(okx_uid=okx_uid),
                            task.id
                        )
                    )
                except Exception as redis_err:
                    logger.error(f"[{okx_uid}] 태스크 ID 저장 중 오류: {str(redis_err)}")

                #logger.info(f"[{okx_uid}] 트레이딩 태스크 등록 완료: task_id={task.id}, 심볼={symbol}")
            except Exception as e:
                logger.error(f"[{okx_uid}] 트레이딩 태스크 등록 중 오류: {str(e)}", exc_info=True)
                # 등록 실패 시 running 해제 (okx_uid 사용)
                try:
                    run_async(set_task_running(okx_uid, False))
                except Exception as cleanup_err:
                    logger.error(f"[{okx_uid}] 실패 후 상태 정리 중 오류: {str(cleanup_err)}")
    except Exception as e:
        logger.error(f"check_and_execute_trading 태스크 실행 중 오류: {str(e)}", exc_info=True)
        traceback.print_exc()

@celery_app.task(name='trading_tasks.execute_trading_cycle', bind=True, max_retries=3, time_limit=50, soft_time_limit=45)
def execute_trading_cycle(self: Any, okx_uid: str, symbol: str, timeframe: str, restart: bool = False) -> Dict[str, Any]: # user_id -> okx_uid
    """
    하나의 트레이딩 사이클 실행 태스크 (OKX UID 기반)
    time_limit과 soft_time_limit을 추가하여 무한 실행 방지
    """
    # 태스크 시작 시 태스크 ID와 함께 명확한 로그 출력
    task_id = self.request.id
    logger.debug(f"[{okx_uid}] execute_trading_cycle 태스크 실행 시작 (task_id: {task_id})")

    start_time = time.time()

    # 타임아웃 보호 컨텍스트 사용
    with timeout_protection():
        try:
            # 실제 비동기 로직 실행 - 타임아웃 45초 설정 (okx_uid 전달)
            # 모든 비동기 작업을 _execute_trading_cycle 내에서 처리
            result: Dict[str, Any] = run_async(
                _execute_trading_cycle(okx_uid, task_id, symbol, timeframe, restart),
                timeout=45
            )

            # 태스크 실행 시간 기록
            execution_time = time.time() - start_time
            if execution_time > 10:
                logger.warning(f"[{okx_uid}] 트레이딩 사이클 완료: 실행 시간={execution_time:.2f}초")

            return result
        except asyncio.TimeoutError:
            error_message = "비동기 작업이 내부 타임아웃을 초과했습니다"
            logger.error(f"[{okx_uid}] {error_message}")
            return {"status": "error", "error": error_message}
        except Exception as e:
            error_message = str(e)
            logger.error(f"[{okx_uid}] 트레이딩 사이클 실행 중 오류 발생: {error_message}", exc_info=True)
            return {"status": "error", "error": error_message}

async def _execute_trading_cycle(
    okx_uid: str, task_id: str, symbol: str, timeframe: str, restart: bool = False # user_id -> okx_uid
) -> Dict[str, Any]:
    """
    실제 비동기 트레이딩 로직 (OKX UID 기반)
    컨텍스트 매니저 패턴 적용
    모든 async 작업을 단일 이벤트 루프에서 처리
    """
    # 상태 추적 변수
    success = False
    error_message: Optional[str] = None

    redis = await get_redis_client()

    try:
        # 1. 태스크 실행 상태를 True로 설정 (60초 만료)
        await set_task_running(okx_uid, True, expiry=60)

        lock_key = REDIS_KEY_USER_LOCK.format(okx_uid=okx_uid, symbol=symbol, timeframe=timeframe)

        # 재시작 모드이거나 첫 실행일 경우 기존 락 삭제
        if restart:
            try:
                # 이벤트 루프가 열려있는지 확인
                try:
                    loop = asyncio.get_running_loop()
                    if loop.is_closed():
                        logger.warning(f"[{okx_uid}] 이벤트 루프가 닫혀있어 락 삭제를 건너뜁니다")
                    else:
                        lock_exists = await redis.exists(lock_key)
                        if lock_exists:
                            logger.info(f"[{okx_uid}] 재시작 모드: 기존 락 강제 삭제 {symbol}/{timeframe}")
                            await redis.delete(lock_key)
                            # 잠시 대기하여 완전히 삭제되도록 함
                            await asyncio.sleep(0.5)
                except RuntimeError:
                    # 실행 중인 이벤트 루프가 없는 경우
                    logger.debug(f"[{okx_uid}] 실행 중인 이벤트 루프 없음, 락 삭제 건너뜀")
            except Exception as lock_err:
                logger.debug(f"[{okx_uid}] 기존 락 삭제 중 오류 (무시됨): {str(lock_err)}")

        # 락 획득 시도 (okx_uid 사용)
        async with acquire_okx_lock(okx_uid, symbol, timeframe, ttl=60) as lock_acquired: # acquire_user_lock -> acquire_okx_lock
            if not lock_acquired:
                logger.warning(f"[{okx_uid}] {symbol}/{timeframe}에 대한 락 획득 실패. 이미 다른 프로세스가 실행 중입니다.")
                error_message = "이미 다른 프로세스가 실행 중입니다."
                await update_last_execution(okx_uid, success, error_message)
                return {"status": "skipped", "message": error_message}

            try:
                # 쿨다운 키 삭제 - 첫 실행에서 쿨다운 무시를 위해
                if restart:
                    for direction in ["long", "short"]:
                        cooldown_key = f"user:{okx_uid}:cooldown:{symbol}:{direction}"
                        try:
                            # 이벤트 루프 상태 확인
                            try:
                                loop = asyncio.get_running_loop()
                                if not loop.is_closed():
                                    cooldown_exists = await redis.exists(cooldown_key)
                                    if cooldown_exists:
                                        logger.info(f"[{okx_uid}] 재시작 모드: 쿨다운 삭제 {symbol}/{direction}")
                                        await redis.delete(cooldown_key)
                            except RuntimeError:
                                logger.debug(f"[{okx_uid}] 실행 중인 이벤트 루프 없음, 쿨다운 삭제 건너뜀")
                        except Exception as cooldown_err:
                            logger.debug(f"[{okx_uid}] 쿨다운 삭제 중 오류 (무시됨): {str(cooldown_err)}")

                # 상태 확인 - 실패 시 재시도 (okx_uid 사용)
                is_running = False
                retry_count = 0
                while retry_count < 3:
                    try:
                        is_running = await check_if_running(okx_uid)
                        break
                    except Exception as check_err:
                        logger.warning(f"[{okx_uid}] 상태 확인 실패 (시도 {retry_count+1}/3): {str(check_err)}")
                        retry_count += 1
                        await asyncio.sleep(1)

                if retry_count == 3:
                    logger.warning(f"[{okx_uid}] 상태 확인에 최대 시도 횟수 도달 -> 기본값으로 계속 진행")
                    is_running = True  # 확인 불가 시 기본값으로 진행

                logger.debug(f"[{okx_uid}] 트레이딩 상태 확인 결과: {is_running}")

                if is_running:
                    # 컨텍스트 매니저를 통한 실행으로 확실한 자원 정리 (okx_uid 사용)
                    # restart 파라미터를 그대로 전달하여 execute_trading_logic에서도 재시작 모드 인식
                    await execute_trading_with_context(
                        okx_uid=okx_uid, symbol=symbol, timeframe=timeframe, restart=restart
                    )

                    # 다음 사이클까지 작은 지연 추가
                    await asyncio.sleep(1)

                    # 성공 상태 기록
                    success = True
                    await update_last_execution(okx_uid, success)
                    return {"status": "success", "message": f"[{okx_uid}] 트레이딩 사이클 완료"}
                else:
                    # 중지 상태일 경우 태스크 ID 삭제 및 상태 업데이트 (okx_uid 사용)
                    await redis.delete(REDIS_KEY_TASK_ID.format(okx_uid=okx_uid))
                    await set_trading_status(okx_uid, "stopped")
                    # user_id 대신 okx_uid를 보내는 것이 맞는지 확인 필요. 우선 그대로 둠.
                    await send_telegram_message(f"⚠️[{okx_uid}] User의 상태를 Stopped로 강제 변경6.", okx_uid, debug=True)
                    await set_symbol_status(okx_uid, symbol, "stopped")

                    logger.info(f"[{okx_uid}] 트레이딩 중지 상태 감지 - 사이클 실행 중단")
                    success = True  # 정상 중지는 성공으로 간주
                    await update_last_execution(okx_uid, success)
                    return {"status": "stopped", "message": "트레이딩이 중지되었습니다."}

            except Exception as e:
                logger.error(f"[{okx_uid}] 트레이딩 사이클 오류: {str(e)}", exc_info=True)
                error_message = str(e)
                success = False
                await update_last_execution(okx_uid, success, error_message)
                raise  # 상위 함수에서 처리하도록 예외 전파

    except Exception as e:
        # 최상위 예외 처리
        error_message = str(e)
        success = False
        logger.error(f"[{okx_uid}] _execute_trading_cycle 최상위 오류: {error_message}", exc_info=True)
        try:
            await update_last_execution(okx_uid, success, error_message)
        except Exception as update_err:
            logger.error(f"[{okx_uid}] update_last_execution 실패: {str(update_err)}")
        raise

    finally:
        # 항상 task_running 상태를 False로 설정
        try:
            await set_task_running(okx_uid, False)
        except Exception as cleanup_err:
            logger.error(f"[{okx_uid}] set_task_running cleanup 실패: {str(cleanup_err)}")

# 애플리케이션 종료 시 이벤트 루프 정리 함수
def cleanup_event_loop():
    """
    애플리케이션 종료 시 이벤트 루프 정리
    """
    global _loop
    with _loop_lock:
        if _loop and not _loop.is_closed():
            try:
                # 자식 태스크 먼저 취소
                cancel_all_child_tasks()
                
                # 실행 중인 모든 태스크 가져오기
                pending = asyncio.all_tasks(loop=_loop)
                if pending:
                    logger.info(f"{len(pending)}개의 대기 중인 태스크를 취소합니다")
                    # 모든 태스크 취소
                    for task in pending:
                        if not task.done():
                            task.cancel()
                    
                    # 잔여 태스크 정리를 위한 짧은 실행 (최대 3초)
                    try:
                        # 취소된 태스크가 정리될 시간 부여
                        _loop.run_until_complete(
                            asyncio.wait_for(
                                asyncio.gather(*pending, return_exceptions=True),
                                timeout=3
                            )
                        )
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        logger.warning("태스크 취소 대기 시간 초과")
                
                # 비동기 제너레이터 정리
                _loop.run_until_complete(_loop.shutdown_asyncgens())
                _loop.close()
                logger.info("이벤트 루프가 정상적으로 정리되었습니다")
            except Exception as e:
                logger.error(f"이벤트 루프 정리 중 오류: {str(e)}")
            finally:
                _loop = None

# 프로세스 종료 시 이벤트 루프 정리 등록
import atexit

# Dynamic redis_client access

# redis_client = get_redis_client()  # Removed - causes import-time error
atexit.register(cleanup_event_loop)
