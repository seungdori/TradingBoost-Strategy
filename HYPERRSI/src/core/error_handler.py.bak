from typing import Optional, Dict, Any
import traceback
from HYPERRSI.src.bot.telegram_message import send_telegram_message
from HYPERRSI.src.core.logger import error_logger as logger
import asyncio

# 공통 에러 모듈 사용
from shared.errors import ErrorCategory, ErrorSeverity, ERROR_SEVERITY_MAP
from shared.errors.categories import classify_error as _classify_error

async def handle_critical_error(
    error: Exception,
    category: ErrorCategory,
    context: Dict[str, Any],
    okx_uid: Optional[str] = None,
    severity_override: Optional[ErrorSeverity] = None
):
    """
    중요한 에러를 처리하고 관리자에게 알림을 보냅니다.
    
    Args:
        error: 발생한 예외
        category: 에러 카테고리
        context: 에러 컨텍스트 정보 (추가 정보)
        okx_uid: 사용자 ID (해당되는 경우)
        severity_override: 기본 심각도를 재정의할 경우
    """
    try:
        severity = severity_override or ERROR_SEVERITY_MAP.get(category, ErrorSeverity.MEDIUM)
        error_type = type(error).__name__
        error_message = str(error)
        stack_trace = traceback.format_exc()
        
        # 로그 기록
        logger.error(f"[{category.value}] {error_type}: {error_message}")
        if context:
            logger.error(f"Context: {context}")
        
        # 관리자 알림 메시지 구성
        admin_message = f"""
<b>시스템 에러 발생</b>

<b>카테고리:</b> {category.value}
<b>심각도:</b> {severity.value.upper()}
<b>에러 타입:</b> {error_type}
<b>메시지:</b> {error_message}
"""
        
        if okx_uid:
            admin_message += f"<b>사용자 ID:</b> {okx_uid}\n"
        
        if context:
            context_str = "\n".join([f"  • {k}: {v}" for k, v in context.items()])
            admin_message += f"\n<b>컨텍스트:</b>\n{context_str}\n"
        
        # 스택 트레이스는 중요 에러에만 포함
        if severity in [ErrorSeverity.HIGH, ErrorSeverity.CRITICAL]:
            # 스택 트레이스를 간략하게 표시
            trace_lines = stack_trace.split('\n')[-10:]  # 마지막 10줄만
            trace_str = '\n'.join(trace_lines)
            admin_message += f"\n<b>스택 트레이스 (마지막 10줄):</b>\n<code>{trace_str}</code>"
        
        # 심각도가 MEDIUM 이상인 경우에만 관리자에게 알림
        if severity in [ErrorSeverity.MEDIUM, ErrorSeverity.HIGH, ErrorSeverity.CRITICAL]:
            # error=True를 설정하면 ERROR_TELEGRAM_ID로 전송됨
            # 하지만 메시지에 사용자 정보를 포함시키기 위해 okx_uid는 전달
            await send_telegram_message(
                message=admin_message,
                okx_uid=okx_uid or "system",
                error=True
            )
        
    except Exception as e:
        # 에러 핸들러 자체의 에러는 로그만 기록
        logger.error(f"Error in handle_critical_error: {e}")
        logger.error(f"Error details - category: {category}, okx_uid: {okx_uid}, error_type: {type(error).__name__}")
        traceback.print_exc()
        
        # 에러 핸들러가 실패해도 최소한의 알림은 전송
        try:
            simple_message = f"🚨 에러 핸들러 실행 중 오류 발생\n\n원본 에러: {str(error)}\n핸들러 에러: {str(e)}"
            from HYPERRSI.src.bot.telegram_message import send_telegram_message
            import asyncio
            if asyncio.iscoroutinefunction(send_telegram_message):
                await send_telegram_message(simple_message, "system", error=True)
        except:
            print(f"Critical: Failed to send error notification - {str(e)}")

# 공통 classify_error 사용 (shared.errors.categories에서 import)
classify_error = _classify_error

# 에러 핸들링 데코레이터
def error_handler(category: Optional[ErrorCategory] = None):
    """
    함수에 에러 핸들링을 추가하는 데코레이터
    
    Args:
        category: 에러 카테고리 (None이면 자동 분류)
    """
    def decorator(func):
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                error_category = category or classify_error(e)
                context = {
                    "function": func.__name__,
                    "args": str(args)[:200],  # 너무 길면 잘라냄
                    "kwargs": str(kwargs)[:200]
                }
                
                # okx_uid 추출 시도
                okx_uid = kwargs.get('okx_uid') or kwargs.get('user_id')
                
                await handle_critical_error(
                    error=e,
                    category=error_category,
                    context=context,
                    okx_uid=okx_uid
                )
                raise  # 원래 예외를 다시 발생
        
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_category = category or classify_error(e)
                context = {
                    "function": func.__name__,
                    "args": str(args)[:200],
                    "kwargs": str(kwargs)[:200]
                }
                
                # okx_uid 추출 시도
                okx_uid = kwargs.get('okx_uid') or kwargs.get('user_id')
                
                # 동기 함수에서는 asyncio.create_task 사용
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(
                    handle_critical_error(
                        error=e,
                        category=error_category,
                        context=context,
                        okx_uid=okx_uid
                    )
                )
                raise
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator

def log_error(
    error: Exception,
    user_id: Optional[str] = None,
    additional_info: Optional[Dict[str, Any]] = None
):
    """
    에러를 로깅하는 간단한 함수
    
    Args:
        error: 발생한 예외
        user_id: 사용자 ID (선택사항)
        additional_info: 추가 정보 (선택사항)
    """
    try:
        error_message = f"[{type(error).__name__}] {str(error)}"
        
        if user_id:
            error_message = f"[User: {user_id}] {error_message}"
        
        logger.error(error_message)
        
        if additional_info:
            logger.error(f"Additional info: {additional_info}")
        
        # 스택 트레이스 로깅
        logger.error(traceback.format_exc())
        
    except Exception as e:
        # 로깅 자체의 에러는 출력만
        print(f"Error in log_error: {e}")
        traceback.print_exc()