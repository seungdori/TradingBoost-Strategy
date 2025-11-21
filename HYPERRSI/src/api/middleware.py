from typing import Any, Callable

from fastapi import Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from shared.logging import get_logger

logger = get_logger(__name__)

def setup_middlewares(app: Any) -> None:
    """미들웨어 설정"""



    @app.middleware("http")
    async def logging_middleware(request: Request, call_next: Callable) -> Response:
        """요청/응답 로깅"""
        logger.info(f"Request: {request.method} {request.url}")
        response = await call_next(request)
        return response

    @app.middleware("http")
    async def error_handler(request: Request, call_next: Callable) -> Response:
        """전역 에러 처리 + errordb 자동 로깅"""
        try:
            return await call_next(request)
        except Exception as e:
            logger.error(f"Unhandled error: {e}")

            # errordb에 자동 기록
            try:
                import asyncio
                from HYPERRSI.src.database.hyperrsi_error_db import log_hyperrsi_error

                # user_id, telegram_id 추출
                user_id = request.headers.get('user_id') or request.query_params.get('user_id')
                telegram_id_str = request.headers.get('telegram_id') or request.query_params.get('telegram_id')
                telegram_id = int(telegram_id_str) if telegram_id_str else None

                # 에러 타입과 심각도 결정
                error_type = e.__class__.__name__
                severity = "ERROR"
                if isinstance(e, (ValueError, KeyError, AttributeError)):
                    severity = "WARNING"
                elif "Critical" in error_type or "Fatal" in error_type:
                    severity = "CRITICAL"

                # 비동기로 DB에 기록 (blocking 방지)
                asyncio.create_task(
                    log_hyperrsi_error(
                        error=e,
                        error_type=error_type,
                        user_id=user_id,
                        telegram_id=telegram_id,
                        severity=severity,
                        module="middleware",
                        function_name="error_handler",
                        metadata={
                            'path': str(request.url.path),
                            'method': request.method,
                            'query_params': dict(request.query_params),
                        },
                        request_id=request.headers.get('X-Request-ID'),
                    )
                )
            except Exception as db_error:
                # DB 로깅 실패해도 응답은 반환
                logger.error(f"Failed to log error to errordb: {db_error}")

            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"}
            ) 