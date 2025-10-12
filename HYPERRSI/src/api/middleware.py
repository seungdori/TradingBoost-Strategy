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
        """전역 에러 처리"""
        try:
            return await call_next(request)
        except Exception as e:
            logger.error(f"Unhandled error: {e}")
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"}
            ) 