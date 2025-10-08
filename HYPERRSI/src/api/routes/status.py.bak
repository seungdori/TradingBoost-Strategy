from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from HYPERRSI.src.services.redis_service import RedisService, redis_service
from shared.logging import get_logger
import time
from datetime import datetime

logger = get_logger(__name__)

# Dynamic redis_client access
def _get_redis_client():
    """Get redis_client dynamically to avoid import-time errors"""
    from HYPERRSI.src.core import database as db_module
    return db_module.redis_client
router = APIRouter(prefix="/status", tags=["status"])

# 서버 시작 시간 저장
SERVER_START_TIME = datetime.now().isoformat()

@router.get("/")
async def check_status():
    """
    시스템 상태 확인 API
    Redis 연결 상태와 서버 가동 시간 정보를 제공합니다.
    """
    try:
        # Redis 연결 상태 확인
        redis_status = "disconnected"
        try:
            # Redis ping 직접 호출
            await redis_service.ping()
            redis_status = "connected"
        except Exception as e:
            logger.error(f"Redis ping failed: {str(e)}")
            redis_status = "error"
            
        # 현재 시간과 서버 시작 시간
        current_time = datetime.now().isoformat()
        
        # 응답 생성
        response = {
            "status": "running" if redis_status == "connected" else "degraded",
            "redis": {
                "status": redis_status
            },
            "server": {
                "start_time": SERVER_START_TIME,
                "current_time": current_time
            }
        }
        
        # 상태 코드 결정
        status_code = status.HTTP_200_OK if redis_status == "connected" else status.HTTP_503_SERVICE_UNAVAILABLE
        
        return JSONResponse(
            content=response,
            status_code=status_code
        )
        
    except Exception as e:
        logger.error(f"Status check failed: {str(e)}")
        return JSONResponse(
            content={
                "status": "error",
                "message": f"상태 확인 중 오류 발생: {str(e)}"
            },
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@router.get("/redis")
async def check_redis_status():
    """
    Redis 상태 확인 API
    Redis 연결 상태와 세부 정보를 제공합니다.
    """
    try:
        # Redis 연결 상태 확인 - 직접 ping으로 확인
        redis_status = "disconnected"
        
        try:
            # Redis ping 보내기
            start_time = time.time()
            await redis_service.ping()
            ping_time = time.time() - start_time
            
            # Redis 정보 수집
            response = {
                "status": "connected",
                "ping_time_ms": round(ping_time * 1000, 2),
                "details": {
                    "connection_pool": {
                        "max_connections": redis_service._pool.max_connections if redis_service._pool else None,
                    }
                }
            }
            status_code = status.HTTP_200_OK
        except Exception as e:
            logger.error(f"Redis check failed: {str(e)}")
            response = {
                "status": "error",
                "message": f"Redis 연결 오류: {str(e)}"
            }
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            
        return JSONResponse(
            content=response,
            status_code=status_code
        )
        
    except Exception as e:
        logger.error(f"Redis status check failed: {str(e)}")
        return JSONResponse(
            content={
                "status": "error",
                "message": f"Redis 상태 확인 중 오류 발생: {str(e)}"
            },
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        ) 