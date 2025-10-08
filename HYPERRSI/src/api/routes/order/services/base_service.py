"""
Base Service

모든 서비스 클래스의 공통 기능을 제공하는 베이스 클래스
"""
from typing import Optional, Callable, Any, TypeVar, ParamSpec, Dict
from functools import wraps
import ccxt.async_support as ccxt
from fastapi import HTTPException

from shared.logging import get_logger
from HYPERRSI.src.core.logger import error_logger
from ..error_messages import (
    EXCHANGE_NOT_INITIALIZED,
    EXCHANGE_CONNECTION_ERROR,
    EXCHANGE_AUTH_ERROR,
    INSUFFICIENT_FUNDS,
    INVALID_ORDER,
    ORDER_NOT_FOUND,
    MISSING_REQUIRED_PARAMS
)

logger = get_logger(__name__)

# Type variables for generic decorators
P = ParamSpec('P')
T = TypeVar('T')


class BaseService:
    """
    모든 서비스 클래스의 베이스 클래스

    공통 기능:
    - 에러 처리 및 변환
    - 로깅
    - 검증
    """

    @staticmethod
    def handle_exchange_error(operation: str) -> Callable:
        """
        거래소 API 에러를 HTTPException으로 변환하는 데코레이터

        Args:
            operation: 작업 설명 (로깅용)

        Returns:
            Callable: 데코레이터 함수

        Usage:
            @BaseService.handle_exchange_error("주문 생성")
            async def create_order(...):
                ...
        """
        def decorator(func: Callable[P, T]) -> Callable[P, T]:
            @wraps(func)
            async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                try:
                    return await func(*args, **kwargs)
                except HTTPException:
                    # HTTPException은 그대로 전파
                    raise
                except ccxt.NetworkError as e:
                    detail = BaseService.create_error_detail(operation, e)
                    error_logger.error(f"네트워크 오류 - {detail}")
                    raise HTTPException(status_code=503, detail=EXCHANGE_CONNECTION_ERROR)
                except ccxt.AuthenticationError as e:
                    detail = BaseService.create_error_detail(operation, e)
                    error_logger.error(f"인증 오류 - {detail}")
                    raise HTTPException(status_code=401, detail=EXCHANGE_AUTH_ERROR)
                except ccxt.InsufficientFunds as e:
                    detail = BaseService.create_error_detail(operation, e)
                    error_logger.error(f"잔고 부족 - {detail}")
                    raise HTTPException(status_code=400, detail=INSUFFICIENT_FUNDS)
                except ccxt.InvalidOrder as e:
                    detail = BaseService.create_error_detail(operation, e)
                    error_logger.error(f"잘못된 주문 - {detail}")
                    raise HTTPException(status_code=400, detail=f"{INVALID_ORDER}: {str(e)}")
                except ccxt.OrderNotFound as e:
                    detail = BaseService.create_error_detail(operation, e)
                    error_logger.error(f"주문 없음 - {detail}")
                    raise HTTPException(status_code=404, detail=ORDER_NOT_FOUND)
                except Exception as e:
                    detail = BaseService.create_error_detail(operation, e)
                    error_logger.error(detail, exc_info=True)
                    raise HTTPException(status_code=500, detail=detail)

            return wrapper
        return decorator

    @staticmethod
    def log_operation(operation: str, include_args: bool = False) -> Callable:
        """
        서비스 메서드 실행을 로깅하는 데코레이터

        Args:
            operation: 작업 설명
            include_args: 인자 로깅 여부

        Returns:
            Callable: 데코레이터 함수

        Usage:
            @BaseService.log_operation("주문 생성", include_args=True)
            async def create_order(...):
                ...
        """
        def decorator(func: Callable[P, T]) -> Callable[P, T]:
            @wraps(func)
            async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                # 시작 로그
                if include_args:
                    logger.info(f"{operation} 시작 - args: {args[1:]}, kwargs: {kwargs}")
                else:
                    logger.info(f"{operation} 시작")

                try:
                    result = await func(*args, **kwargs)
                    logger.info(f"{operation} 완료")
                    return result
                except Exception as e:
                    logger.error(f"{operation} 실패: {str(e)}")
                    raise

            return wrapper
        return decorator

    @staticmethod
    def validate_exchange(exchange: Optional[ccxt.okx]) -> None:
        """
        Exchange 객체 검증

        Args:
            exchange: 거래소 클라이언트

        Raises:
            HTTPException: exchange가 None이거나 유효하지 않은 경우
        """
        if exchange is None:
            raise HTTPException(
                status_code=500,
                detail=EXCHANGE_NOT_INITIALIZED
            )

    @staticmethod
    def validate_required_params(**params: Any) -> None:
        """
        필수 파라미터 검증

        Args:
            **params: 검증할 파라미터들 (키=값 형태)

        Raises:
            HTTPException: 필수 파라미터가 None이거나 빈 문자열인 경우

        Usage:
            BaseService.validate_required_params(
                symbol=symbol,
                side=side,
                amount=amount
            )
        """
        missing_params = []

        for param_name, param_value in params.items():
            if param_value is None:
                missing_params.append(param_name)
            elif isinstance(param_value, str) and not param_value.strip():
                missing_params.append(param_name)

        if missing_params:
            raise HTTPException(
                status_code=400,
                detail=f"{MISSING_REQUIRED_PARAMS}: {', '.join(missing_params)}"
            )

    @staticmethod
    def create_error_detail(
        operation: str,
        error: Exception,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        상세한 에러 메시지 생성

        Args:
            operation: 작업 설명
            error: 발생한 예외
            context: 추가 컨텍스트 정보

        Returns:
            str: 상세한 에러 메시지
        """
        error_msg = f"{operation} 실패: {str(error)}"

        if context:
            context_str = ", ".join([f"{k}={v}" for k, v in context.items()])
            error_msg += f" (context: {context_str})"

        return error_msg
