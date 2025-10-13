import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from HYPERRSI.src.services.redis_service import RedisService, redis_service
from shared.database.redis_helper import get_redis_client
from shared.logging import get_logger

logger = get_logger(__name__)

# Dynamic redis_client access
router = APIRouter(prefix="/status", tags=["status"])

# 서버 시작 시간 저장
SERVER_START_TIME = datetime.now().isoformat()

@router.get(
    "/",
    summary="시스템 종합 상태 확인",
    description="""
# 시스템 종합 상태 확인

HYPERRSI 봇 시스템의 전반적인 상태를 확인합니다. Redis 연결 상태와 서버 가동 시간을 제공하여 시스템 건강도를 모니터링할 수 있습니다.

## 동작 방식

1. **Redis 연결 확인**: redis_service.ping()으로 Redis 연결 테스트
2. **상태 판별**:
   - connected: Redis 정상 연결
   - error: Redis 연결 실패
   - disconnected: Redis 미연결
3. **서버 정보 수집**:
   - start_time: 서버 시작 시각 (SERVER_START_TIME 전역 변수)
   - current_time: 현재 시각
4. **종합 상태 결정**:
   - running: Redis 정상 연결 (200)
   - degraded: Redis 미연결/오류 (503)
   - error: 상태 확인 실패 (500)
5. **응답 반환**: 상태 정보 + HTTP 상태 코드

## 상태 코드 매핑

- **200 OK**: Redis 정상 연결 (status: "running")
- **503 Service Unavailable**: Redis 미연결/오류 (status: "degraded")
- **500 Internal Server Error**: 상태 확인 실패 (status: "error")

## 반환 데이터 구조

- **status** (string): 시스템 종합 상태
  - "running": 모든 서비스 정상
  - "degraded": Redis 문제로 기능 제한
  - "error": 시스템 오류
- **redis** (object): Redis 상태 정보
  - **status** (string): "connected", "error", "disconnected"
- **server** (object): 서버 정보
  - **start_time** (string): 서버 시작 시각 (ISO 8601)
  - **current_time** (string): 현재 시각 (ISO 8601)

## 업타임 계산

```python
from datetime import datetime
start = datetime.fromisoformat(start_time)
current = datetime.fromisoformat(current_time)
uptime = current - start
```

## 사용 시나리오

-  **헬스체크**: 로드밸런서/모니터링 시스템 연동
-  **대시보드**: 시스템 상태 실시간 표시
-  **알림**: 상태가 "degraded"면 알림 발송
-  **문제 진단**: Redis 연결 문제 조기 감지
-  **업타임 추적**: 서버 재시작 시간 확인

## 예시 요청

```bash
# 기본 상태 확인
curl "http://localhost:8000/status/"

# 헬스체크용 (상태 코드만 확인)
curl -I "http://localhost:8000/status/"

# jq로 파싱
curl "http://localhost:8000/status/" | jq '.status'
```
""",
    responses={
        200: {
            "description": " 시스템 정상 (Redis 연결됨)",
            "content": {
                "application/json": {
                    "examples": {
                        "healthy_system": {
                            "summary": "정상 시스템",
                            "value": {
                                "status": "running",
                                "redis": {
                                    "status": "connected"
                                },
                                "server": {
                                    "start_time": "2025-01-15T10:00:00",
                                    "current_time": "2025-01-15T15:30:00"
                                }
                            }
                        }
                    }
                }
            }
        },
        503: {
            "description": " 서비스 제한 (Redis 미연결/오류)",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_disconnected": {
                            "summary": "Redis 미연결",
                            "value": {
                                "status": "degraded",
                                "redis": {
                                    "status": "disconnected"
                                },
                                "server": {
                                    "start_time": "2025-01-15T10:00:00",
                                    "current_time": "2025-01-15T15:30:00"
                                }
                            }
                        },
                        "redis_error": {
                            "summary": "Redis 오류",
                            "value": {
                                "status": "degraded",
                                "redis": {
                                    "status": "error"
                                },
                                "server": {
                                    "start_time": "2025-01-15T10:00:00",
                                    "current_time": "2025-01-15T15:30:00"
                                }
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 내부 오류 - 상태 확인 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "status_check_failed": {
                            "summary": "상태 확인 실패",
                            "value": {
                                "status": "error",
                                "message": "상태 확인 중 오류 발생: Internal error"
                            }
                        }
                    }
                }
            }
        }
    }
)
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

@router.get(
    "/redis",
    summary="Redis 연결 상태 확인 (상세)",
    description="""
# Redis 연결 상태 확인 (상세)

Redis 서버의 연결 상태와 성능 지표를 상세하게 확인합니다. Ping 시간과 연결 풀 정보를 제공하여 Redis 성능을 모니터링할 수 있습니다.

## 동작 방식

1. **Ping 측정 시작**: 현재 시각 기록 (start_time)
2. **Redis Ping 전송**: redis_service.ping() 호출
3. **Ping 시간 계산**: (end_time - start_time) * 1000 (밀리초)
4. **연결 풀 정보 조회**:
   - max_connections: 최대 연결 수
   - (추가 풀 정보는 redis_service._pool에서 가져옴)
5. **상태 판별**:
   - connected: Ping 성공 (200)
   - error: Ping 실패 (500)
6. **응답 반환**: 상태 + Ping 시간 + 연결 풀 정보

## 반환 데이터 구조

### 성공 시 (200)
- **status** (string): "connected"
- **ping_time_ms** (float): Redis ping 응답 시간 (밀리초, 소수점 2자리)
- **details** (object): 세부 정보
  - **connection_pool** (object): 연결 풀 정보
    - **max_connections** (integer): 최대 연결 수

### 실패 시 (500)
- **status** (string): "error"
- **message** (string): 에러 메시지 (예: "Redis 연결 오류: Connection refused")

## Ping 시간 기준

- **< 5ms**: 매우 좋음 (로컬 Redis)
- **5-20ms**: 좋음 (로컬 네트워크)
- **20-50ms**: 보통 (원격 서버)
- **50-100ms**: 느림 (네트워크 지연)
- **> 100ms**: 매우 느림 (문제 조사 필요)

## 사용 시나리오

-  **성능 모니터링**: Ping 시간으로 Redis 응답 속도 추적
-  **문제 진단**: 느린 Ping 시간으로 네트워크 이슈 감지
-  **대시보드**: 실시간 Redis 연결 상태 표시
-  **헬스체크**: Redis 전용 헬스체크 엔드포인트
-  **연결 풀 모니터링**: max_connections 확인

## 예시 요청

```bash
# 기본 조회
curl "http://localhost:8000/status/redis"

# Ping 시간만 추출
curl "http://localhost:8000/status/redis" | jq '.ping_time_ms'

# 연결 풀 정보 확인
curl "http://localhost:8000/status/redis" | jq '.details.connection_pool'

# 헬스체크용 (상태 코드 확인)
curl -I "http://localhost:8000/status/redis"
```
""",
    responses={
        200: {
            "description": " Redis 정상 연결",
            "content": {
                "application/json": {
                    "examples": {
                        "fast_connection": {
                            "summary": "빠른 연결 (< 5ms)",
                            "value": {
                                "status": "connected",
                                "ping_time_ms": 2.35,
                                "details": {
                                    "connection_pool": {
                                        "max_connections": 50
                                    }
                                }
                            }
                        },
                        "normal_connection": {
                            "summary": "보통 연결 (20-50ms)",
                            "value": {
                                "status": "connected",
                                "ping_time_ms": 32.78,
                                "details": {
                                    "connection_pool": {
                                        "max_connections": 50
                                    }
                                }
                            }
                        },
                        "slow_connection": {
                            "summary": "느린 연결 (> 100ms)",
                            "value": {
                                "status": "connected",
                                "ping_time_ms": 125.42,
                                "details": {
                                    "connection_pool": {
                                        "max_connections": 50
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " Redis 연결 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "connection_refused": {
                            "summary": "연결 거부",
                            "value": {
                                "status": "error",
                                "message": "Redis 연결 오류: Connection refused"
                            }
                        },
                        "timeout": {
                            "summary": "타임아웃",
                            "value": {
                                "status": "error",
                                "message": "Redis 연결 오류: Connection timeout"
                            }
                        },
                        "authentication_failed": {
                            "summary": "인증 실패",
                            "value": {
                                "status": "error",
                                "message": "Redis 연결 오류: Authentication failed"
                            }
                        },
                        "status_check_failed": {
                            "summary": "상태 확인 실패",
                            "value": {
                                "status": "error",
                                "message": "Redis 상태 확인 중 오류 발생: Internal error"
                            }
                        }
                    }
                }
            }
        }
    }
)
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