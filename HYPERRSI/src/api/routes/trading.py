import asyncio
import datetime as dt
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from HYPERRSI.src.api.routes.settings import ApiKeyService, get_api_keys_from_timescale
from HYPERRSI.src.bot.telegram_message import send_telegram_message
from HYPERRSI.src.core.celery_task import celery_app
from HYPERRSI.src.core.error_handler import ErrorCategory, handle_critical_error
from HYPERRSI.src.services.timescale_service import TimescaleUserService
from HYPERRSI.src.trading.trading_service import TradingService, get_okx_client
from shared.database.redis_helper import get_redis_client
from shared.helpers.user_id_resolver import get_okx_uid_from_telegram, get_telegram_id_from_okx_uid
from shared.logging import get_logger

# 로거 설정
logger = get_logger(__name__)

router = APIRouter(prefix="/trading", tags=["trading"])

allowed_uid = ["518796558012178692", "549641376070615063", "587662504768345929", "510436564820701267"]

# okx_uid를 사용하도록 모델 변경
class TradingTaskRequest(BaseModel):
    user_id: str
    symbol: Optional[str] = "SOL-USDT-SWAP"
    timeframe: str = "1m"

    model_config = {
        "json_schema_extra": {
            "example": {
                "user_id": "1709556958", # user_id -> okx_uid
                "symbol": "SOL-USDT-SWAP",
                "timeframe": "1m",
            }
        }
    }

@router.post(
    "/start",
    summary="트레이딩 태스크 시작 (OKX UID 기준)",
    description="""
# 트레이딩 태스크 시작

특정 사용자의 자동 트레이딩을 시작합니다. OKX UID 또는 텔레그램 ID를 사용하여 사용자를 식별합니다.

## 요청 본문 (TradingTaskRequest)

- **user_id** (string, required): 사용자 식별자
  - OKX UID (18자리 숫자) 또는 텔레그램 ID
  - 텔레그램 ID인 경우 자동으로 OKX UID로 변환 시도
- **symbol** (string, optional): 거래 심볼
  - 형식: "SOL-USDT-SWAP", "BTC-USDT-SWAP" 등
  - 기본값: "SOL-USDT-SWAP"
- **timeframe** (string, optional): 차트 시간 프레임
  - 지원: "1m", "5m", "15m", "1h", "4h"
  - 기본값: "1m"

## 쿼리 파라미터

- **restart** (boolean, optional): 재시작 모드
  - `true`: 실행 중인 태스크가 있어도 강제로 재시작
  - `false`: 이미 실행 중이면 오류 반환 (기본값)

## 동작 방식

1. **사용자 식별**: OKX UID 또는 텔레그램 ID 확인 및 변환
2. **Redis 연결 확인**: Redis 연결 상태 검증 (2초 타임아웃)
3. **API 키 확인**: Redis에서 API 키 조회, 없으면 TimescaleDB에서 가져오기
4. **상태 확인**: 현재 실행 중인 트레이딩 태스크 확인
5. **기존 태스크 처리**: restart=true인 경우 기존 태스크 종료
6. **락/쿨다운 정리**: 트레이딩 관련 Redis 키 초기화
7. **Celery 태스크 시작**: 새로운 트레이딩 사이클 실행
8. **상태 저장**: Redis에 실행 상태 및 태스크 ID 저장

## 반환 정보

- **status** (string): 요청 처리 상태 ("success")
- **message** (string): 결과 메시지
- **task_id** (string): Celery 태스크 ID
  - 형식: UUID 형식의 고유 식별자
  - 태스크 추적 및 취소에 사용

## 사용 시나리오

-  **최초 트레이딩 시작**: 사용자의 첫 트레이딩 봇 가동
-  **재시작**: 서버 재시작 후 트레이딩 봇 복구
- ⚙️ **설정 변경**: 심볼 또는 타임프레임 변경 시 재시작
-  **문제 해결**: 오류 상태에서 정상 상태로 복구

## 보안 및 검증

- **Redis 연결 확인**: 2초 타임아웃으로 연결 상태 검증
- **API 키 암호화**: AES-256으로 암호화된 API 키 사용
- **중복 실행 방지**: 이미 실행 중이면 오류 반환 (restart=false)
- **에러 핸들링**: 모든 단계에서 에러 로깅 및 텔레그램 알림

## 예시 요청

```bash
curl -X POST "http://localhost:8000/trading/start?restart=false" \\
     -H "Content-Type: application/json" \\
     -d '{
           "user_id": "518796558012178692",
           "symbol": "SOL-USDT-SWAP",
           "timeframe": "1m"
         }'
```
""",
    responses={
        200: {
            "description": " 트레이딩 태스크 시작 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "트레이딩 시작 성공",
                            "value": {
                                "status": "success",
                                "message": "트레이딩 태스크가 시작되었습니다.",
                                "task_id": "abc123-def456-ghi789-jkl012"
                            }
                        },
                        "restart_success": {
                            "summary": "재시작 성공",
                            "value": {
                                "status": "success",
                                "message": "트레이딩 태스크가 시작되었습니다.",
                                "task_id": "xyz789-uvw456-rst123-opq098"
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": " 잘못된 요청 - 이미 실행 중",
            "content": {
                "application/json": {
                    "examples": {
                        "already_running": {
                            "summary": "이미 실행 중",
                            "value": {
                                "detail": "이미 트레이딩 태스크가 실행 중입니다."
                            }
                        },
                        "invalid_symbol": {
                            "summary": "잘못된 심볼",
                            "value": {
                                "detail": "Invalid symbol format"
                            }
                        }
                    }
                }
            }
        },
        403: {
            "description": " 권한 없음 - 허용되지 않은 사용자",
            "content": {
                "application/json": {
                    "examples": {
                        "unauthorized": {
                            "summary": "권한 없음",
                            "value": {
                                "detail": "권한이 없는 사용자입니다."
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_error": {
                            "summary": "Redis 연결 실패",
                            "value": {
                                "detail": "Redis 연결 오류: Connection refused"
                            }
                        },
                        "redis_timeout": {
                            "summary": "Redis 타임아웃",
                            "value": {
                                "detail": "Redis 연결 시간 초과"
                            }
                        },
                        "task_start_error": {
                            "summary": "태스크 시작 실패",
                            "value": {
                                "detail": "트레이딩 태스크 시작 실패: Celery worker not available"
                            }
                        },
                        "api_key_error": {
                            "summary": "API 키 오류",
                            "value": {
                                "detail": "트레이딩 시작 실패: API key not found"
                            }
                        }
                    }
                }
            }
        }
    }
)
async def start_trading(request: TradingTaskRequest, restart: bool = False):
    try:
        okx_uid = request.user_id # okx_uid 사용
        telegram_id = None
        

        # Redis 연결 확인
        try:
            ping_result = await asyncio.wait_for(get_redis_client().ping(), timeout=2.0)
            if not ping_result:
                raise HTTPException(status_code=500, detail="Redis 연결 실패")
        except asyncio.TimeoutError:
            logger.error("Redis ping timeout (2s)")
            raise HTTPException(status_code=500, detail="Redis 연결 시간 초과")
        except Exception as redis_error:
            logger.error(f"Redis 연결 오류: {str(redis_error)}")
            await handle_critical_error(
                error=redis_error,
                category=ErrorCategory.REDIS_CONNECTION,
                context={"endpoint": "start_trading", "okx_uid": okx_uid},
                okx_uid=okx_uid
            )
            raise HTTPException(status_code=500, detail=f"Redis 연결 오류: {str(redis_error)}")

        # telegram_id인지 okx_uid인지 확인
        is_telegram_id = not okx_uid.isdigit() or len(okx_uid) < 13
        telegram_id = okx_uid if is_telegram_id else None

        # telegram_id인 경우 okx_uid로 변환 시도
        if is_telegram_id:
            okx_uid_from_telegram = await get_okx_uid_from_telegram(okx_uid)
            if okx_uid_from_telegram:
                okx_uid = okx_uid_from_telegram
                is_telegram_id = False

    
        telegram_id = await get_telegram_id_from_okx_uid(okx_uid, TimescaleUserService)

        # API 키 확인 및 업데이트
        api_keys = await get_redis_client().hgetall(f"user:{okx_uid}:api:keys")
        
        # API 키가 기본값인지 확인
        is_default_api_key = False
        if api_keys:
            api_key = api_keys.get('api_key', '')
            api_secret = api_keys.get('api_secret', '')
            passphrase = api_keys.get('passphrase', '')
            
            # 기본값 확인
            if api_key == "default_api_key" or api_secret == "default_api_secret" or passphrase == "default_passphrase":
                is_default_api_key = True
                logger.info(f"사용자 {okx_uid}의 API 키가 기본값으로 설정되어 있습니다. TimescaleDB에서 정보 조회를 시도합니다.")

        # API 키가 없거나 기본값인 경우 TimescaleDB에서 정보 가져오기
        if not api_keys or is_default_api_key:
            # TimescaleDB에서 API 키 정보 가져오기
            timescale_api_keys = await get_api_keys_from_timescale(int(okx_uid))
            
            if timescale_api_keys:
                # TimescaleDB에서 가져온 API 키로 사용자 생성/업데이트
                await ApiKeyService.set_user_api_keys(
                    str(okx_uid), 
                    timescale_api_keys['api_key'], 
                    timescale_api_keys['api_secret'], 
                    timescale_api_keys['passphrase']
                )
                logger.info(f"사용자 {okx_uid}의 API 키를 TimescaleDB 정보로 업데이트했습니다.")
        
        #if okx_uid not in allowed_uid:
        #    await send_telegram_message(f"[{okx_uid}] 권한이 없는 사용자입니다.", okx_uid, debug=True)
        #    await send_telegram_message(f"[{okx_uid}] 권한이 없는 사용자입니다. \n관리자에게 문의해주세요.", okx_uid)
        #    await redis_client.set(f"user:{okx_uid}:trading:status", "stopped")
        #    raise HTTPException(status_code=403, detail="권한이 없는 사용자입니다.")
            
        
        # 심볼과 타임프레임 가져오기
        symbol = request.symbol
        timeframe = request.timeframe
        
        # 현재 실행 중인 task 확인 (telegram_id와 okx_uid 모두 확인)
        is_running = False
        telegram_status = None
        okx_status = None

        # Redis pipeline으로 배치 조회
        if telegram_id:
            telegram_status_key = f"user:{telegram_id}:trading:status"
            okx_status_key = f"user:{okx_uid}:trading:status"

            # Pipeline으로 두 키를 한 번에 조회
            async with get_redis_client().pipeline() as pipe:
                pipe.get(telegram_status_key)
                pipe.get(okx_status_key)
                results = await pipe.execute()
                telegram_status, okx_status = results
        else:
            # telegram_id가 없으면 okx_uid만 조회
            okx_status_key = f"user:{okx_uid}:trading:status"
            okx_status = await get_redis_client().get(okx_status_key)

        # telegram_id 상태 처리
        if telegram_status:
            # 바이트 문자열을 디코딩
            if isinstance(telegram_status, bytes):
                print(f"원본 telegram_status는 바이트 문자열입니다: {repr(telegram_status)}")
                telegram_status = telegram_status.decode('utf-8')

            # 문자열 정규화 (공백 제거 및 따옴표 제거)
            telegram_status = telegram_status.strip().strip('"\'')

            if telegram_status == "running":
                is_running = True
                logger.info(f"텔레그램 ID {telegram_id}의 트레이딩이 실행 중입니다.")

        # okx_uid 상태 처리
        print(f"okx_status_key: {okx_status_key}")
        print(f"okx_status: {okx_status}")
        
        # 바이트 문자열을 디코딩
        if isinstance(okx_status, bytes):
            print(f"원본 okx_status는 바이트 문자열입니다: {repr(okx_status)}")
            okx_status = okx_status.decode('utf-8')
            
        # 문자열 정규화 (공백 제거 및 따옴표 제거)
        if okx_status:
            okx_status = okx_status.strip().strip('"\'')
            
        if okx_status == "running":
            is_running = True
            logger.info(f"OKX UID {okx_uid}의 트레이딩이 실행 중입니다.")

        # 실행 중인 상태에서 restart=False이면 오류 반환 (기존 로직 복원)
        if is_running and not restart:
            logger.warning(f"[{okx_uid}] 이미 실행 중인 트레이딩이 있고 restart=False임. 시작 거부.")
            raise HTTPException(status_code=400, detail="이미 트레이딩 태스크가 실행 중입니다.")

        # 태스크 ID 파악 (재시작 시에만 필요)
        task_id = None
        
        # 재시작 모드거나 실행 중인 태스크가 있는 경우에만 기존 태스크 정리
        if restart or is_running:
            # telegram_id의 task_id 확인
            
            if telegram_id and telegram_id != "":
                telegram_task_id_key = f"user:{telegram_id}:task_id"
                task_id = await get_redis_client().get(telegram_task_id_key)
            
            # okx_uid의 task_id 확인
            if not task_id:
                okx_task_id_key = f"user:{okx_uid}:task_id"
                task_id = await get_redis_client().get(okx_task_id_key)
            
            # 기존 태스크 종료 시도
            if task_id:
                logger.info(f"기존 태스크 종료 시도: {task_id} (okx_uid: {okx_uid}, telegram_id: {telegram_id})")
                try:
                    celery_app.control.revoke(task_id, terminate=True)
                    
                    # telegram_id의 task_id 키 삭제
                    if telegram_id:
                        await get_redis_client().delete(f"user:{telegram_id}:task_id")
                    
                    # okx_uid의 task_id 키 삭제
                    await get_redis_client().delete(f"user:{okx_uid}:task_id")
                    
                    # 태스크가 완전히 종료될 때까지 짧은 지연 추가
                    await asyncio.sleep(2)
                except Exception as revoke_error:
                    logger.error(f"태스크 취소 오류: {str(revoke_error)}")
        
        # 락 및 쿨다운 정리 (항상 실행)
        # 1. 트레이딩 시작 전 사용자 락(lock) 삭제
        if okx_uid:
            lock_key = f"lock:user:{okx_uid}:{symbol}:{timeframe}"
            try:
            # 락 존재 확인 후 삭제
                lock_exists = await get_redis_client().exists(lock_key)
                if lock_exists:
                    logger.info(f"[{okx_uid}] 기존 락 삭제: {symbol}/{timeframe}")
                    await get_redis_client().delete(lock_key)
            except Exception as lock_err:
                logger.warning(f"[{okx_uid}] 락 삭제 중 오류 (무시됨): {str(lock_err)}")
        
        # 2. 쿨다운 제한 해제 (long/short 모두)
        for direction in ["long", "short"]:
            cooldown_key = f"user:{okx_uid}:cooldown:{symbol}:{direction}"
            try:
                cooldown_exists = await get_redis_client().exists(cooldown_key)
                if cooldown_exists:
                    logger.info(f"[{okx_uid}] 기존 쿨다운 삭제: {symbol}/{direction}")
                    await get_redis_client().delete(cooldown_key)
            except Exception as cooldown_err:
                logger.warning(f"[{okx_uid}] 쿨다운 삭제 중 오류 (무시됨): {str(cooldown_err)}")
                
        # 3. 태스크 실행 상태 초기화 (이전에 비정상 종료된 태스크가 있을 경우)
        task_running_key = f"user:{okx_uid}:task_running"
        try:
            task_running_exists = await get_redis_client().exists(task_running_key)
            if task_running_exists:
                logger.info(f"[{okx_uid}] 기존 태스크 실행 상태 초기화")
                await get_redis_client().delete(task_running_key)
        except Exception as task_err:
            logger.warning(f"[{okx_uid}] 태스크 상태 초기화 중 오류 (무시됨): {str(task_err)}")

        try:
            # Redis 상태 저장 (telegram_id와 okx_uid 모두)
            if telegram_id:
                #await redis_client.set(f"user:{telegram_id}:trading:status", "running")
                await get_redis_client().hset(
                    f"user:{telegram_id}:preferences",
                    mapping={"symbol": request.symbol, "timeframe": request.timeframe}
                )

            # 상태를 'running'으로 명시적 설정
            await get_redis_client().set(okx_status_key, "running")
            await get_redis_client().hset(
                f"user:{okx_uid}:preferences",
                mapping={"symbol": request.symbol, "timeframe": request.timeframe}
            )

            symbol = request.symbol
            timeframe = request.timeframe

            # Celery 태스크 실행 (okx_uid 전달)
            task = celery_app.send_task(
                'trading_tasks.execute_trading_cycle',
                args=[okx_uid, symbol, timeframe, restart]
            )
            logger.info(f"[{okx_uid}] 새 트레이딩 태스크 시작: {task.id} (symbol: {symbol}, timeframe: {timeframe})")

            # task_id 저장 (telegram_id와 okx_uid 모두)
            if telegram_id:
                await get_redis_client().set(f"user:{telegram_id}:task_id", task.id)
            await get_redis_client().set(f"user:{okx_uid}:task_id", task.id)

            return {
                "status": "success",
                "message": "트레이딩 태스크가 시작되었습니다.",
                "task_id": task.id
            }
        except Exception as task_error:
            logger.error(f"태스크 시작 오류 (okx_uid: {okx_uid}): {str(task_error)}", exc_info=True)
            await handle_critical_error(
                error=task_error,
                category=ErrorCategory.CELERY_TASK,
                context={"endpoint": "start_trading", "okx_uid": okx_uid, "symbol": symbol, "timeframe": timeframe},
                okx_uid=okx_uid
            )
            # Redis 상태 초기화
            if telegram_id:
                await get_redis_client().set(f"user:{telegram_id}:trading:status", "error")
            await get_redis_client().set(okx_status_key, "error")
            raise HTTPException(status_code=500, detail=f"트레이딩 태스크 시작 실패: {str(task_error)}")
            
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"트레이딩 시작 중 오류 (okx_uid: {okx_uid}): {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"트레이딩 시작 실패: {str(e)}")



@router.post("/start_all_users",
    summary="모든 실행 중인 트레이딩 태스크 재시작 (OKX UID 기준)",
    description="서버 재시작 등으로 다운 후, 기존에 실행 중이던 모든 사용자의 트레이딩 태스크를 재시작합니다 (OKX UID 기준).",
    responses={
        200: {
            "description": "모든 실행 중인 트레이딩 태스크 재시작 성공",
            "content": {
                "application/json": {
                    "example": {
                        "status": "success",
                        "message": "모든 실행 중인 트레이딩 태스크에 재시작 명령을 보냈습니다.",
                        "restarted_users": [
                            {"okx_uid": "UID1", "task_id": "new_task_id_1"},
                            {"okx_uid": "UID2", "task_id": "new_task_id_2"}
                        ]
                    }
                }
            }
        },
        500: {"description": "트레이딩 태스크 재시작 실패"}
    })
async def start_all_users():
    try:
        # Redis 연결 확인
        if not await get_redis_client().ping():
            await handle_critical_error(
                error=Exception("Redis ping 실패"),
                category=ErrorCategory.REDIS_CONNECTION,
                context={"endpoint": "start_all_users"},
                okx_uid="system"
            )
            raise HTTPException(status_code=500, detail="Redis 연결 실패")
            
        # 패턴 변경: user:*:trading:status
        status_keys = await get_redis_client().keys("user:*:trading:status")
        restarted_users = []
        errors = []
        
        logger.debug(f"총 {len(status_keys)}개의 트레이딩 상태 키 발견")
        
        for key in status_keys:
            okx_uid = None # 루프 시작 시 초기화
            status = await get_redis_client().get(key)
            
            # 바이트 문자열을 디코딩
            if isinstance(status, bytes):
                status = status.decode('utf-8')
                
            # status가 'running'인 경우만 재시작 처리
            if status == "running":
                try:
                    # key 구조: user:{okx_uid}:trading:status
                    parts = key.split(":")
                    if len(parts) >= 2 and parts[0] == 'user':
                        okx_uid = parts[1]
                    else:
                        logger.warning(f"잘못된 키 형식 발견: {key}")
                        continue
                    
                    logger.info(f"사용자 {okx_uid} 재시작 시도 중")
                    
                    task_id_key = f"user:{okx_uid}:task_id"
                    current_task_id = await get_redis_client().get(task_id_key)
                    
                    # 기존 태스크가 존재하면 종료
                    if current_task_id:
                        logger.info(f"기존 태스크 종료: {current_task_id} (okx_uid: {okx_uid})")
                        celery_app.control.revoke(current_task_id, terminate=True)
                        await get_redis_client().delete(task_id_key)
                        # 상태는 임시로 'restarting'으로 설정
                        await get_redis_client().set(key, "restarting")
                        
                        # 태스크가 완전히 종료될 때까지 짧은 지연 추가
                        await asyncio.sleep(1)
                    
                    try:
                        preference_key = f"user:{okx_uid}:preferences"
                        symbol = await get_redis_client().hget(preference_key, "symbol")
                        timeframe = await get_redis_client().hget(preference_key, "timeframe")
                        # restart 옵션을 True로 해서 새 태스크 실행 (okx_uid 전달)
                        task = celery_app.send_task(
                            'trading_tasks.execute_trading_cycle',
                            args=[okx_uid, symbol, timeframe, True]
                        )
                        
                        logger.info(f"[{okx_uid}] 새 트레이딩 태스크 시작: {task.id} (symbol: {symbol}, timeframe: {timeframe})")
                        
                        # Redis에 새 태스크 정보 업데이트
                        await get_redis_client().set(key, "running") # 상태 키 사용
                        await get_redis_client().set(task_id_key, task.id) # 태스크 ID 키 사용
                        
                        restarted_users.append({"okx_uid": okx_uid, "task_id": task.id}) # user_id -> okx_uid
                    except Exception as task_error:
                        logger.error(f"태스크 시작 오류 (okx_uid: {okx_uid}): {str(task_error)}", exc_info=True)
                        await handle_critical_error(
                            error=task_error,
                            category=ErrorCategory.CELERY_TASK,
                            context={"endpoint": "start_all_users", "okx_uid": okx_uid, "symbol": symbol, "timeframe": timeframe},
                            okx_uid=okx_uid
                        )
                        errors.append({"okx_uid": okx_uid, "error": f"태스크 시작 실패: {str(task_error)}"}) # user_id -> okx_uid
                        # 상태를 'error'로 설정
                        await get_redis_client().set(key, "error") # 상태 키 사용
                        
                except Exception as user_err:
                    error_id = okx_uid if okx_uid else key # okx_uid 추출 실패 시 키 자체를 ID로 사용
                    logger.error(f"사용자 {error_id} 재시작 중 에러: {str(user_err)}", exc_info=True)
                    await handle_critical_error(
                        error=user_err,
                        category=ErrorCategory.MASS_OPERATION,
                        context={"endpoint": "start_all_users", "error_id": error_id, "operation": "restart"},
                        okx_uid=okx_uid if okx_uid else "system"
                    )
                    errors.append({"identifier": error_id, "error": str(user_err)})
                    
        logger.info(f"재시작 완료: {len(restarted_users)}개 성공, {len(errors)}개 실패")
                    
        response = {
            "status": "success",
            "message": "모든 실행 중인 트레이딩 태스크에 재시작 명령을 보냈습니다.",
            "restarted_users": restarted_users
        }
        if errors:
            response["errors"] = errors
        
        return response

    except Exception as e:
        logger.error(f"start_all_users 실패: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"start_all_users 실패: {str(e)}")


@router.post(
    "/stop",
    summary="트레이딩 태스크 중지 (OKX UID 기준)",
    description="""
# 트레이딩 태스크 중지

특정 사용자의 자동 트레이딩을 안전하게 중지합니다. 실행 중인 Celery 태스크를 종료하고 관련 Redis 상태를 정리합니다.

## 요청 방식

**쿼리 파라미터** 또는 **JSON 본문** 중 하나를 사용:

### 방법 1: 쿼리 파라미터
- **user_id** (string, required): 사용자 식별자
  - OKX UID (18자리 숫자) 또는 텔레그램 ID

### 방법 2: JSON 본문
- **okx_uid** (string, required): OKX UID

## 동작 방식

1. **사용자 식별**: OKX UID 또는 텔레그램 ID 확인 및 변환
2. **상태 확인**: 현재 트레이딩 상태 조회 (running 여부)
3. **종료 신호 설정**: Redis에 stop_signal 설정
4. **Celery 태스크 취소**: 실행 중인 태스크 종료 (SIGTERM)
5. **락/쿨다운 해제**: 트레이딩 관련 Redis 키 삭제
6. **열린 주문 취소** (선택): 활성 주문 취소 시도
7. **상태 정리**: Redis 상태를 'stopped'로 변경
8. **텔레그램 알림**: 사용자에게 중지 메시지 전송

## 정리되는 Redis 키

- `user:{okx_uid}:trading:status` → "stopped"
- `user:{okx_uid}:task_id` → 삭제
- `user:{okx_uid}:stop_signal` → 삭제
- `user:{okx_uid}:task_running` → 삭제
- `user:{okx_uid}:cooldown:{symbol}:long` → 삭제
- `user:{okx_uid}:cooldown:{symbol}:short` → 삭제
- `lock:user:{okx_uid}:{symbol}:{timeframe}` → 삭제

## 반환 정보

- **status** (string): 요청 처리 상태 ("success")
- **message** (string): 결과 메시지
  - "트레이딩 중지 신호가 보내졌습니다. 잠시 후 중지됩니다."
  - "트레이딩이 이미 중지되어 있습니다."

## 사용 시나리오

-  **수동 중지**: 사용자가 트레이딩을 직접 중지
-  **비상 중지**: 시장 급변 시 긴급 중지
-  **유지보수**: 설정 변경 또는 업데이트를 위한 중지
-  **전략 변경**: 새로운 전략 적용을 위한 중지
-  **손실 제한**: 일정 손실 도달 시 자동 중지

## 예시 요청

### 쿼리 파라미터 방식
```bash
curl -X POST "http://localhost:8000/trading/stop?user_id=518796558012178692"
```

### JSON 본문 방식
```bash
curl -X POST "http://localhost:8000/trading/stop" \\
     -H "Content-Type: application/json" \\
     -d '{"okx_uid": "518796558012178692"}'
```
""",
    responses={
        200: {
            "description": " 트레이딩 태스크 중지 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "stop_success": {
                            "summary": "중지 성공",
                            "value": {
                                "status": "success",
                                "message": "트레이딩 중지 신호가 보내졌습니다. 잠시 후 중지됩니다."
                            }
                        },
                        "already_stopped": {
                            "summary": "이미 중지됨",
                            "value": {
                                "status": "success",
                                "message": "트레이딩이 이미 중지되어 있습니다."
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": " 잘못된 요청 - 필수 파라미터 누락",
            "content": {
                "application/json": {
                    "examples": {
                        "missing_user_id": {
                            "summary": "사용자 ID 누락",
                            "value": {
                                "detail": "user_id 또는 okx_uid가 필요합니다."
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 사용자를 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "user_not_found": {
                            "summary": "존재하지 않는 사용자",
                            "value": {
                                "detail": "User not found"
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_error": {
                            "summary": "Redis 연결 실패",
                            "value": {
                                "detail": "Redis 연결 오류: Connection refused"
                            }
                        },
                        "task_cancel_error": {
                            "summary": "태스크 취소 실패",
                            "value": {
                                "detail": "트레이딩 중지 실패: Failed to cancel task"
                            }
                        },
                        "cleanup_error": {
                            "summary": "상태 정리 실패",
                            "value": {
                                "detail": "트레이딩 중지 실패: Cleanup operation failed"
                            }
                        }
                    }
                }
            }
        }
    }
)
async def stop_trading(request: Request, user_id: Optional[str] = Query(None, description="사용자 ID (OKX UID 또는 텔레그램 ID)")):
    try:
        symbol = None
        okx_uid = None
        
        # 1. 쿼리 파라미터에서 user_id 확인
        if user_id:
            okx_uid = user_id
        else:
            # 2. JSON 본문에서 okx_uid 확인 (기존 방식)
            try:
                request_body = await request.json()
                if "okx_uid" in request_body:
                    okx_uid = request_body["okx_uid"]
            except (json.JSONDecodeError, ValueError, AttributeError):
                pass
        
        # 3. 필수 파라미터 확인
        if not okx_uid:
            raise HTTPException(status_code=400, detail="user_id 또는 okx_uid가 필요합니다.")
            
        logger.info(f"사용자 {okx_uid}의 트레이딩 태스크 중지 시도")
        
        # 텔레그램 ID인지 OKX UID인지 확인
        is_telegram_id = not okx_uid.isdigit() or len(okx_uid) < 13

        # 텔레그램 ID인 경우 OKX UID로 변환 시도
        telegram_id = okx_uid if is_telegram_id else None
        if is_telegram_id:
            okx_uid_from_telegram = await get_okx_uid_from_telegram(okx_uid)
            if okx_uid_from_telegram:
                okx_uid = okx_uid_from_telegram
                is_telegram_id = False
        else:
            # OKX UID인 경우 텔레그램 ID 찾기 (선택 사항)
            try:
                telegram_id = await get_telegram_id_from_okx_uid(okx_uid, TimescaleUserService)
            except Exception as e:
                logger.debug(f"텔레그램 ID 조회 실패 (무시됨): {str(e)}")
        
        # 텔레그램 ID로 된 키 확인 (원래 ID가 텔레그램 ID인 경우)
        if telegram_id:
            telegram_status_key = f"user:{telegram_id}:trading:status"
            telegram_status = await get_redis_client().get(telegram_status_key)
            
            # 바이트 문자열을 디코딩
            if isinstance(telegram_status, bytes):
                telegram_status = telegram_status.decode('utf-8')
                
            # 문자열 정규화 (공백 제거 및 따옴표 제거)
            if telegram_status:
                telegram_status = telegram_status.strip().strip('"\'')
                
            if telegram_status == "running":
                await get_redis_client().set(telegram_status_key, "stopped")
                logger.info(f"텔레그램 ID {telegram_id}의 트레이딩 상태를 stopped로 변경했습니다.")
        
        # OKX UID로 된 키 확인
        okx_status_key = f"user:{okx_uid}:trading:status"
        okx_status = await get_redis_client().get(okx_status_key)
        
        # 바이트 문자열을 디코딩
        if isinstance(okx_status, bytes):
            okx_status = okx_status.decode('utf-8')
            
        # 문자열 정규화 (공백 제거 및 따옴표 제거)
        if okx_status:
            okx_status = okx_status.strip().strip('"\'')
            
        if okx_status == "running":
            await get_redis_client().set(okx_status_key, "stopped")
            logger.info(f"OKX UID {okx_uid}의 트레이딩 상태를 stopped로 변경했습니다.")
        
        # 둘 다 running이 아닌 경우
        if (not telegram_id or telegram_status != "running") and okx_status != "running":
            logger.warning(f"사용자 {okx_uid}의 트레이딩 상태가 'running'이 아닙니다.")
            # 이미 멈춰있는 경우 바로 성공 반환
            if (telegram_id and telegram_status == "stopped") or okx_status == "stopped":
                return {
                    "status": "success",
                    "message": "트레이딩이 이미 중지되어 있습니다."
                }
        
        # 종료 신호 설정
        if telegram_id:
            await get_redis_client().set(f"user:{telegram_id}:stop_signal", "true")
        await get_redis_client().set(f"user:{okx_uid}:stop_signal", "true")
            
        logger.info(f"사용자 {okx_uid}에게 종료 신호를 설정했습니다.")
        
        # 태스크 ID 확인
        task_id = None
        if telegram_id:
            task_id_key = f"user:{telegram_id}:task_id"
            task_id = await get_redis_client().get(task_id_key)
        
        if not task_id:
            task_id_key = f"user:{okx_uid}:task_id"
            task_id = await get_redis_client().get(task_id_key)
            
        # 현재 실행 중인 태스크 취소 시도
        if task_id:
            try:
                logger.info(f"Celery 태스크 취소 시도 (task_id: {task_id}, user_id: {okx_uid})")
                celery_app.control.revoke(task_id, terminate=True)
                logger.info(f"Celery 태스크 취소 명령 전송 완료 (task_id: {task_id})")
                
                # Celery 태스크 종료를 기다리는 시간 증가 (2초)
                await asyncio.sleep(2)
            except Exception as revoke_err:
                logger.error(f"태스크 취소 중 오류 발생 (task_id: {task_id}): {str(revoke_err)}", exc_info=True)
        else:
            logger.warning(f"태스크 ID를 찾을 수 없습니다 (user_id: {okx_uid})")
            
        # 선호도 정보에서 심볼과 타임프레임 가져오기
        try:
            if telegram_id:
                preference_key = f"user:{telegram_id}:preferences"
                symbol = await get_redis_client().hget(preference_key, "symbol")
                timeframe = await get_redis_client().hget(preference_key, "timeframe")
                
            if not symbol or not timeframe:
                preference_key = f"user:{okx_uid}:preferences"
                symbol = await get_redis_client().hget(preference_key, "symbol")
                timeframe = await get_redis_client().hget(preference_key, "timeframe")
                
            # 1. 사용자 락(lock) 해제
            if symbol and timeframe:
                lock_key = f"lock:user:{okx_uid}:{symbol}:{timeframe}"
                try:
                    lock_exists = await get_redis_client().exists(lock_key)
                    if lock_exists:
                        logger.info(f"[{okx_uid}] 락 해제: {symbol}/{timeframe}")
                        await get_redis_client().delete(lock_key)
                except Exception as lock_err:
                    logger.warning(f"[{okx_uid}] 락 삭제 중 오류 (무시됨): {str(lock_err)}")
                
            # 2. 쿨다운 키 해제 (long/short 모두)
            if symbol:
                for direction in ["long", "short"]:
                    cooldown_key = f"user:{okx_uid}:cooldown:{symbol}:{direction}"
                    try:
                        cooldown_exists = await get_redis_client().exists(cooldown_key)
                        if cooldown_exists:
                            logger.info(f"[{okx_uid}] 쿨다운 해제: {symbol}/{direction}")
                            await get_redis_client().delete(cooldown_key)
                    except Exception as cooldown_err:
                        logger.warning(f"[{okx_uid}] 쿨다운 삭제 중 오류 (무시됨): {str(cooldown_err)}")
        except Exception as pref_err:
            logger.warning(f"선호도 정보 조회 중 오류 (무시됨): {str(pref_err)}")
            
        # 사용자에게 트레이딩 중지 메시지 전송
        try:
            # telegram_id가 있으면 우선 사용, 없으면 okx_uid 사용
            recipient_id = telegram_id if telegram_id else okx_uid
            await send_telegram_message(
                f" 트레이딩이 중지되었습니다.\n\n"
                f"심볼: {symbol if symbol else '알 수 없음'}\n"
                f"타임프레임: {timeframe if timeframe else '알 수 없음'}", 
                recipient_id
            )
            logger.info(f"사용자 {okx_uid}에게 트레이딩 중지 메시지 전송 완료")
        except Exception as msg_err:
            logger.error(f"트레이딩 중지 메시지 전송 실패: {str(msg_err)}", exc_info=True)
            
        # 3. 태스크 실행 상태 정리
        task_running_key = f"user:{okx_uid}:task_running"
        try:
            task_running_exists = await get_redis_client().exists(task_running_key)
            if task_running_exists:
                logger.info(f"[{okx_uid}] 태스크 실행 상태 정리")
                await get_redis_client().delete(task_running_key)
        except Exception as task_err:
            logger.warning(f"[{okx_uid}] 태스크 상태 정리 중 오류 (무시됨): {str(task_err)}")
            
        # TradingService 초기화 및 활성 주문 취소 시도
        trading_service = None
        try:
            trading_service = TradingService(user_id=okx_uid)
            
            # 기존 exchange 클라이언트가 없으면 생성
            if not trading_service.client:
                trading_service.client = await get_okx_client(user_id=okx_uid)
                
            #if trading_service.client and symbol:
            #    logger.info(f"사용자 {okx_uid}의 열린 주문 취소 시도 (심볼: {symbol})")
            #    try:
            #        await trading_service.cancel_all_open_orders(trading_service.client, symbol, okx_uid)
            #        logger.info(f"모든 열린 주문이 취소되었습니다. user_id: {okx_uid}, symbol: {symbol}")
            #    except Exception as cancel_err:
            #        logger.error(f"주문 취소 중 오류 발생 (user_id: {okx_uid}): {str(cancel_err)}", exc_info=True)
        except Exception as service_err:
            logger.error(f"TradingService 초기화 중 오류 발생 (user_id: {okx_uid}): {str(service_err)}", exc_info=True)
        
        # Redis 상태 초기화 - 핵심 키만 삭제
        try:
            logger.info(f"사용자 {okx_uid}의 Redis 상태 초기화 중")

            # 핵심 키 목록 (텔레그램 ID와 OKX UID 모두)
            keys_to_delete = []
            
            # 태스크 ID, 중지 신호, 태스크 실행 상태 키 삭제
            if telegram_id:
                keys_to_delete.extend([
                    f"user:{telegram_id}:task_id",
                    f"user:{telegram_id}:stop_signal"
                ])
                
            keys_to_delete.extend([
                f"user:{okx_uid}:task_id",
                f"user:{okx_uid}:stop_signal",
                f"user:{okx_uid}:task_running"
            ])
            
            # 포지션 관련 키는 심볼이 있는 경우에만 삭제
            if symbol:
                for direction in ["long", "short"]:
                    cooldown_key = f"user:{okx_uid}:cooldown:{symbol}:{direction}"
                    keys_to_delete.append(cooldown_key)
                    
                if timeframe:
                    lock_key = f"lock:user:{okx_uid}:{symbol}:{timeframe}"
                    keys_to_delete.append(lock_key)
            
            # 삭제 실행
            for key in keys_to_delete:
                try:
                    await get_redis_client().delete(key)
                except Exception as del_err:
                    logger.warning(f"키 삭제 중 오류 발생 (key: {key}): {str(del_err)}")
            
            logger.debug(f"사용자 {okx_uid}의 Redis 상태 초기화 완료")
        except Exception as redis_err:
            logger.error(f"Redis 상태 초기화 중 오류 발생 (user_id: {okx_uid}): {str(redis_err)}", exc_info=True)
        
        # TradingService cleanup
        try:
            if trading_service:
                await trading_service.cleanup()
                logger.info(f"TradingService cleanup 완료 (user_id: {okx_uid})")
        except Exception as cleanup_err:
            logger.error(f"TradingService cleanup 중 오류 발생 (user_id: {okx_uid}): {str(cleanup_err)}", exc_info=True)
            
        return {
            "status": "success",
            "message": "트레이딩 중지 신호가 보내졌습니다. 잠시 후 중지됩니다."
        }
    except Exception as e:
        logger.error(f"트레이딩 중지 중 오류 발생 (user_id: {okx_uid}): {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"트레이딩 중지 실패: {str(e)}"
        )
        
@router.get(
    "/running_users",
    summary="실행 중인 모든 사용자 조회 (OKX UID 기준)",
    description="""
# 실행 중인 모든 사용자 조회

Redis에서 트레이딩 상태가 'running'인 모든 사용자의 OKX UID 목록을 조회합니다.

## 동작 방식

1. **Redis 패턴 매칭**: `user:*:trading:status` 패턴으로 모든 상태 키 조회
2. **상태 필터링**: 값이 'running'인 키만 선택
3. **UID 추출**: 키에서 OKX UID 파싱
4. **목록 반환**: 실행 중인 사용자 UID 배열 반환

## 반환 정보

- **status** (string): 요청 처리 상태 ("success")
- **running_users** (array of string): 실행 중인 사용자 OKX UID 목록
  - 빈 배열: 실행 중인 사용자 없음
  - 각 요소: 18자리 OKX UID

## 사용 시나리오

-  **시스템 모니터링**: 전체 활성 사용자 수 파악
-  **일괄 재시작**: 서버 재시작 시 복구할 사용자 목록 확인
-  **일괄 중지**: 긴급 상황 시 중지할 사용자 식별
-  **통계 분석**: 활성 사용자 통계 집계
-  **관리자 도구**: 관리자 대시보드에 활성 사용자 표시

## 예시 URL

```
GET /trading/running_users
```
""",
    responses={
        200: {
            "description": " 실행 중인 사용자 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "multiple_users": {
                            "summary": "여러 사용자 실행 중",
                            "value": {
                                "status": "success",
                                "running_users": [
                                    "518796558012178692",
                                    "549641376070615063",
                                    "587662504768345929"
                                ]
                            }
                        },
                        "single_user": {
                            "summary": "단일 사용자 실행 중",
                            "value": {
                                "status": "success",
                                "running_users": [
                                    "518796558012178692"
                                ]
                            }
                        },
                        "no_users": {
                            "summary": "실행 중인 사용자 없음",
                            "value": {
                                "status": "success",
                                "running_users": []
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_error": {
                            "summary": "Redis 연결 실패",
                            "value": {
                                "detail": "Redis 연결 실패"
                            }
                        },
                        "query_error": {
                            "summary": "데이터 조회 실패",
                            "value": {
                                "detail": "running_users 조회 실패: Query failed"
                            }
                        }
                    }
                }
            }
        }
    }
)
async def get_all_running_users():
    """
    현재 'running' 상태인 모든 OKX UID를 조회
    """
    try:
        if not await get_redis_client().ping():
            raise HTTPException(status_code=500, detail="Redis 연결 실패")
        
        status_keys = await get_redis_client().keys("user:*:trading:status") # 패턴 변경
        running_users = []
        
        for key in status_keys:
            status = await get_redis_client().get(key)
            
            # 바이트 문자열을 디코딩
            if isinstance(status, bytes):
                status = status.decode('utf-8')
                
            if status == "running":
                # key 구조: user:{okx_uid}:trading:status
                parts = key.split(":")
                if len(parts) >= 2 and parts[0] == 'user':
                    okx_uid = parts[1]
                    running_users.append(okx_uid) # user_id -> okx_uid
                else:
                    logger.warning(f"잘못된 키 형식 발견: {key}")
        
        return {
            "status": "success",
            "running_users": running_users
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"running_users 조회 실패: {str(e)}")


@router.post("/stop_all_running_users",
    summary="실행 중(trading status=running)인 모든 사용자 중지 (OKX UID 기준)",
    description="Redis에서 'running' 상태인 모든 OKX UID의 트레이딩을 중지합니다."
)
async def stop_all_running_users():
    """
    모든 'running' 상태 사용자에 대해 일괄 중지.
    stop_trading 로직을 반복해서 수행 (OKX UID 기준).
    """
    try:
        if not await get_redis_client().ping():
            raise HTTPException(status_code=500, detail="Redis 연결 실패")
        
        status_keys = await get_redis_client().keys("user:*:trading:status") # 패턴 변경
        stopped_users = []
        errors = []
        
        logger.info(f"총 {len(status_keys)}개의 트레이딩 상태 키 발견")

        for key in status_keys:
            okx_uid = None # 루프 시작 시 초기화
            status = await get_redis_client().get(key)
            
            # 바이트 문자열을 디코딩
            if isinstance(status, bytes):
                status = status.decode('utf-8')
                
            if status == "running":
                parts = key.split(":")
                if len(parts) >= 2 and parts[0] == 'user':
                    okx_uid = parts[1]
                else:
                    logger.warning(f"잘못된 키 형식 발견: {key}")
                    continue
                
                logger.info(f"사용자 {okx_uid} 중지 시도 중")
                
                try:
                    # 종료 신호 설정 (okx_uid 사용)
                    await get_redis_client().set(f"user:{okx_uid}:stop_signal", "true")
                    await get_redis_client().set(f"user:{okx_uid}:trading:status", "stopped")
                    # await send_telegram_message(f"[{okx_uid}] User의 상태를 Stopped로 강제 변경.6", okx_uid, debug=True)
                    logger.info(f"사용자 {okx_uid}에게 종료 신호를 설정했습니다.")
                    
                    # TradingService 초기화 및 활성 주문 취소 (okx_uid 사용 가정)
                    trading_service = None
                    symbol = None # 심볼 초기화
                    try:
                        trading_service = TradingService(user_id=okx_uid)
                        if not trading_service.client:
                            trading_service.client = await get_okx_client(user_id=okx_uid)
                        
                        symbol = await get_redis_client().hget(f"user:{okx_uid}:preferences", "symbol")
                        if symbol:
                            logger.info(f"사용자 {okx_uid}의 열린 주문 취소 시도 (심볼: {symbol})")
                            try:
                                await trading_service.cancel_all_open_orders(trading_service.client, symbol, okx_uid)
                                logger.info(f"모든 열린 주문이 취소되었습니다. okx_uid: {okx_uid}, symbol: {symbol}")
                            except Exception as cancel_err:
                                logger.error(f"주문 취소 중 오류 발생 (user_id: {okx_uid}): {str(cancel_err)}", exc_info=True)
                    except Exception as service_err:
                        logger.error(f"TradingService 초기화 중 오류 발생 (user_id: {okx_uid}): {str(service_err)}", exc_info=True)
                    
                    # Celery task 취소 (okx_uid 사용)
                    task_id_key = f"user:{okx_uid}:task_id"
                    task_id = await get_redis_client().get(task_id_key)
                    if task_id:
                        try:
                            logger.info(f"Celery 태스크 취소 시도 (task_id: {task_id}, okx_uid: {okx_uid})")
                            celery_app.control.revoke(task_id, terminate=True, signal='SIGTERM')
                            logger.info(f"Celery 태스크 취소 명령 전송 완료 (task_id: {task_id})")
                        except Exception as revoke_err:
                            logger.error(f"태스크 취소 중 오류 발생 (task_id: {task_id}): {str(revoke_err)}", exc_info=True)
                    
                    # Redis 상태 초기화 (okx_uid 사용)
                    try:
                        logger.info(f"사용자 {okx_uid}의 Redis 상태 초기화 중")
                        await get_redis_client().set(f"user:{okx_uid}:trading:status", "stopped") # 이미 위에서 설정함
                        #await send_telegram_message(f"[{okx_uid}] User의 상태를 Stopped로 강제 변경.8", okx_uid, debug=True)
                        
                        # 관련 키 삭제 (키 형식 변경)
                        keys_to_delete = [
                            f"user:{okx_uid}:symbol",
                            f"user:{okx_uid}:timeframe",
                            f"user:{okx_uid}:task_id",
                            f"user:{okx_uid}:stop_signal",
                            f"user:{okx_uid}:trading:status"
                        ]
                        
                        if symbol: # 심볼 정보가 있을 때만 포지션 키 삭제
                            position_keys = [
                                f"user:{okx_uid}:position:{symbol}:main_direction_direction",
                                f"user:{okx_uid}:position:{symbol}:position_state",
                                f"user:{okx_uid}:position:{symbol}:long",
                                f"user:{okx_uid}:position:{symbol}:short",
                                f"user:{okx_uid}:position:{symbol}:long_dca_levels",
                                f"user:{okx_uid}:position:{symbol}:short_dca_levels"
                            ]
                            keys_to_delete.extend(position_keys)
                        
                        for key_to_del in keys_to_delete: # 변수명 변경 (key 중복 방지)
                            try:
                                await get_redis_client().delete(key_to_del)
                            except Exception as del_err:
                                logger.warning(f"키 삭제 중 오류 발생 (key: {key_to_del}): {str(del_err)}")
                        
                        logger.debug(f"사용자 {okx_uid}의 Redis 상태 초기화 완료1")
                    except Exception as redis_err:
                        logger.error(f"Redis 상태 초기화 중 오류 발생 (user_id: {okx_uid}): {str(redis_err)}", exc_info=True)
                    
                    # TradingService cleanup
                    if trading_service:
                        try:
                            await trading_service.cleanup()
                            logger.info(f"TradingService cleanup 완료 (user_id: {okx_uid})")
                        except Exception as cleanup_err:
                            logger.error(f"TradingService cleanup 중 오류 발생 (user_id: {okx_uid}): {str(cleanup_err)}", exc_info=True)
                    
                    stopped_users.append(okx_uid) # user_id -> okx_uid
                    logger.info(f"사용자 {okx_uid} 중지 신호 전송 완료")
                    
                    # 다음 사용자 처리 전 짧은 지연 추가
                    await asyncio.sleep(0.5)
                    
                except Exception as user_err:
                    errors.append({"okx_uid": okx_uid, "error": str(user_err)}) # user_id -> okx_uid
                    logger.error(f"{okx_uid} 중지 실패: {str(user_err)}", exc_info=True)
                    await handle_critical_error(
                        error=user_err,
                        category=ErrorCategory.MASS_OPERATION,
                        context={"endpoint": "stop_all_running_users", "okx_uid": okx_uid, "operation": "stop"},
                        okx_uid=okx_uid
                    )

        logger.info(f"중지 완료: {len(stopped_users)}개 성공, {len(errors)}개 실패")
        
        response = {
            "status": "success",
            "message": "running 상태인 모든 사용자에 대해 중지 신호를 전송했습니다. 잠시 후 모두 중지됩니다.",
            "stopped_users": stopped_users
        }
        if errors:
            response["errors"] = errors
        return response

    except Exception as e:
        logger.error(f"stop_all_running_users 실패: {str(e)}", exc_info=True)
        await handle_critical_error(
            error=e,
            category=ErrorCategory.MASS_OPERATION,
            context={"endpoint": "stop_all_running_users", "operation": "mass_stop"},
            okx_uid="system"
        )
        raise HTTPException(status_code=500, detail=f"stop_all_running_users 실패: {str(e)}")


@router.post("/restart_all_running_users",
    summary="실행 중인 유저들을 모두 restart=true로 재시작 (OKX UID 기준)",
    description="Redis에서 'running' 상태인 모든 OKX UID를 찾아, 기존 태스크 종료 후 restart=true로 다시 시작시킵니다."
)
async def restart_all_running_users():
    """
    모든 'running' 상태 사용자에 대해 일괄 재시작(restart=True).
    기존 태스크는 revoke 후, 새 태스크를 생성 (OKX UID 기준).
    """
    try:
        if not await get_redis_client().ping():
            raise HTTPException(status_code=500, detail="Redis 연결 실패")
            
        status_keys = await get_redis_client().keys("user:*:trading:status") # 패턴 변경
        restarted_users = []
        errors = []
        
        for key in status_keys:
            okx_uid = None # 루프 시작 시 초기화
            status = await get_redis_client().get(key)
            
            # 바이트 문자열을 디코딩
            if isinstance(status, bytes):
                status = status.decode('utf-8')
                
            if status == "running":
                parts = key.split(":")
                if len(parts) >= 2 and parts[0] == 'user':
                    okx_uid = parts[1]
                else:
                    logger.warning(f"잘못된 키 형식 발견: {key}")
                    continue
                try:
                    # 사용자 preference 정보 가져오기 (okx_uid 사용)
                    preference_key = f"user:{okx_uid}:preferences"
                    symbol = await get_redis_client().hget(preference_key, "symbol")
                    timeframe = await get_redis_client().hget(preference_key, "timeframe")
                    
                    task_id_key = f"user:{okx_uid}:task_id"
                    current_task_id = await get_redis_client().get(task_id_key)
                    
                    if current_task_id:
                        logger.info(f"기존 태스크 종료: {current_task_id} (okx_uid: {okx_uid})")
                        celery_app.control.revoke(current_task_id, terminate=True)
                        await get_redis_client().delete(task_id_key)
                        await get_redis_client().set(key, "restarting") # 상태 키 사용
                        await asyncio.sleep(0.5)
                    
                    # 기존 방식으로 태스크 실행 (okx_uid 전달)
                    task = celery_app.send_task(
                        'trading_tasks.execute_trading_cycle',  # 새 태스크 함수 이름
                        args=[okx_uid, symbol, timeframe , True]  # restart=True
                    )
                    # Redis 상태 업데이트 (okx_uid 사용)
                    await get_redis_client().set(key, "running") # 상태 키 사용
                    await get_redis_client().set(task_id_key, task.id) # 태스크 ID 키 사용
                    
                    # preference 정보 확인 및 업데이트 (okx_uid 사용)
                    if symbol and timeframe:
                        await get_redis_client().hset(
                            preference_key,
                            mapping={"symbol": symbol, "timeframe": timeframe}
                        )
                    
                    restarted_users.append({
                        "okx_uid": okx_uid, # user_id -> okx_uid
                        "task_id": task.id,
                        "symbol": symbol,
                        "timeframe": timeframe
                    })
                    
                    
                    logger.info(f"사용자 {okx_uid} 재시작 성공 (태스크: {task.id})")
                    
                except Exception as user_err:
                    logger.error(f"okx_uid {okx_uid} 재시작 중 에러: {str(user_err)}", exc_info=True)
                    errors.append({"okx_uid": okx_uid, "error": str(user_err)}) # user_id -> okx_uid
                    # 오류 발생 시 상태를 'error'로 설정 (okx_uid 사용)
                    await get_redis_client().set(key, "error") # 상태 키 사용
        
        response = {
            "status": "success",
            "message": "running 상태인 모든 사용자에 대해 재시작(restart=True) 명령을 보냈습니다.",
            "restarted_users": restarted_users
        }
        
        if errors:
            response["errors"] = errors
            
        return response
        
    except Exception as e:
        logger.error(f"restart_all_running_users 실패: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"restart_all_running_users 실패: {str(e)}")

@router.get(
    "/status/{okx_uid}",
    summary="특정 사용자의 트레이딩 상태 조회 (OKX UID 기준)",
    description="""
# 특정 사용자의 트레이딩 상태 조회

특정 사용자의 트레이딩 상태 및 관련 정보를 종합적으로 조회합니다.

## URL 파라미터

- **okx_uid** (string, required): OKX UID
  - 형식: 18자리 숫자 (예: "518796558012178692")

## 반환 정보

### 기본 정보
- **trading_status** (string): 트레이딩 상태
  - `running`: 실행 중
  - `stopped`: 중지됨
  - `error`: 오류 발생
  - `restarting`: 재시작 중
  - `not_found`: 정보 없음

### 태스크 정보
- **task_id** (string, optional): Celery 태스크 ID
  - 형식: UUID 형식
  - 실행 중인 태스크의 고유 식별자

### 사용자 설정 (preferences)
- **symbol** (string): 거래 심볼
- **timeframe** (string): 차트 시간 프레임

### 포지션 정보 (position_info)
- **main_direction** (string): 주 포지션 방향
  - `long`: 롱 포지션
  - `short`: 숏 포지션
- **position_state** (string): 포지션 상태
  - `in_position`: 포지션 보유 중
  - `no_position`: 포지션 없음
  - `closing`: 청산 중

### 기타 정보
- **stop_signal** (string, optional): 중지 신호 여부
  - `true`: 중지 신호 활성

## 사용 시나리오

-  **상태 모니터링**: 실시간 트레이딩 상태 확인
-  **디버깅**: 트레이딩 문제 분석 및 해결
-  **대시보드**: 사용자 대시보드에 상태 표시
- ⚙️ **설정 확인**: 현재 적용된 심볼/타임프레임 확인
- 💼 **포지션 추적**: 현재 보유 포지션 현황 파악

## 예시 URL

```
GET /trading/status/518796558012178692
```
""",
    responses={
        200: {
            "description": " 트레이딩 상태 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "running_with_position": {
                            "summary": "실행 중 (포지션 보유)",
                            "value": {
                                "status": "success",
                                "data": {
                                    "trading_status": "running",
                                    "symbol": "SOL-USDT-SWAP",
                                    "timeframe": "1m",
                                    "task_id": "abc123-def456-ghi789-jkl012",
                                    "preferences": {
                                        "symbol": "SOL-USDT-SWAP",
                                        "timeframe": "1m"
                                    },
                                    "position_info": {
                                        "main_direction": "long",
                                        "position_state": "in_position"
                                    }
                                }
                            }
                        },
                        "stopped": {
                            "summary": "중지됨",
                            "value": {
                                "status": "success",
                                "data": {
                                    "trading_status": "stopped",
                                    "symbol": "BTC-USDT-SWAP",
                                    "timeframe": "5m",
                                    "preferences": {
                                        "symbol": "BTC-USDT-SWAP",
                                        "timeframe": "5m"
                                    }
                                }
                            }
                        },
                        "not_found": {
                            "summary": "정보 없음",
                            "value": {
                                "status": "success",
                                "data": {
                                    "trading_status": "not_found",
                                    "message": "사용자의 트레이딩 정보가 없습니다."
                                }
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 사용자 정보를 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "user_not_found": {
                            "summary": "존재하지 않는 사용자",
                            "value": {
                                "detail": "User not found"
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_error": {
                            "summary": "Redis 연결 실패",
                            "value": {
                                "detail": "Redis 연결 실패"
                            }
                        },
                        "query_error": {
                            "summary": "데이터 조회 실패",
                            "value": {
                                "detail": "트레이딩 상태 조회 실패: Query failed"
                            }
                        }
                    }
                }
            }
        }
    }
)
async def get_user_trading_status(okx_uid: str): # user_id -> okx_uid
    """
    특정 사용자의 트레이딩 상태 조회 (OKX UID 기준)

    Args:
        okx_uid (str): 조회할 OKX UID

    Returns:
        Dict: 트레이딩 상태 정보
    """
    try:
        # Redis 연결 확인
        if not await get_redis_client().ping():
            await handle_critical_error(
                error=Exception("Redis ping 실패"),
                category=ErrorCategory.REDIS_CONNECTION,
                context={"endpoint": "start_all_users"},
                okx_uid="system"
            )
            raise HTTPException(status_code=500, detail="Redis 연결 실패")
        
        # 기본 상태 키 (okx_uid 사용)
        status_key = f"user:{okx_uid}:trading:status" # 키 변경
        trading_status = await get_redis_client().get(status_key)
        
        # 바이트 문자열을 디코딩
        if isinstance(trading_status, bytes):
            trading_status = trading_status.decode('utf-8')
        
        if trading_status is None:
            return {
                "status": "success",
                "data": {
                    "trading_status": "not_found",
                    "message": "사용자의 트레이딩 정보가 없습니다."
                }
            }
        
        # 기본 응답 데이터 구성
        response_data = {
            "trading_status": trading_status,
        }
        
        # 관련 정보 수집 (okx_uid 사용)
        task_id_key = f"user:{okx_uid}:task_id" # 키 변경
        task_id = await get_redis_client().get(task_id_key)
        if task_id:
            response_data["task_id"] = task_id
        
        # 사용자 설정 정보 (okx_uid 사용)
        preferences_key = f"user:{okx_uid}:preferences" # 키 변경
        preferences = await get_redis_client().hgetall(preferences_key)
        if preferences:
            response_data["preferences"] = preferences
            
            # 심볼 정보가 있으면 포지션 상태도 확인
            if "symbol" in preferences:
                symbol = preferences["symbol"]
                response_data["symbol"] = symbol
                
                # 포지션 상태 정보 (okx_uid 사용)
                position_info = {}
                main_direction_key = f"user:{okx_uid}:position:{symbol}:main_direction_direction" # 키 변경
                position_state_key = f"user:{okx_uid}:position:{symbol}:position_state" # 키 변경
                
                main_direction = await get_redis_client().get(main_direction_key)
                position_state = await get_redis_client().get(position_state_key)
                
                if main_direction:
                    position_info["main_direction"] = main_direction
                if position_state:
                    position_info["position_state"] = position_state
                
                if position_info:
                    response_data["position_info"] = position_info
            
            if "timeframe" in preferences:
                response_data["timeframe"] = preferences["timeframe"]
        
        # 정지 신호 확인 (okx_uid 사용)
        stop_signal_key = f"user:{okx_uid}:stop_signal" # 키 변경
        stop_signal = await get_redis_client().get(stop_signal_key)
        if stop_signal:
            response_data["stop_signal"] = stop_signal
        
        return {
            "status": "success",
            "data": response_data
        }
        
    except Exception as e:
        logger.error(f"사용자 트레이딩 상태 조회 실패 (okx_uid: {okx_uid}): {str(e)}", exc_info=True) # 로그 변경
        raise HTTPException(
            status_code=500,
            detail=f"트레이딩 상태 조회 실패: {str(e)}"
        )

@router.get("/status/{okx_uid}/{symbol}", # user_id -> okx_uid
    summary="특정 사용자의 특정 심볼에 대한 트레이딩 상태 조회 (OKX UID 기준)",
    description="특정 사용자의 특정 심볼에 대한 트레이딩 상태 및 관련 정보를 상세하게 조회합니다 (OKX UID 기준).",
    responses={
        200: {
            "description": "심볼별 트레이딩 상태 조회 성공",
            "content": {
                "application/json": {
                    "example": {
                        "status": "success",
                        "data": {
                            "symbol": "SOL-USDT-SWAP",
                            "position_info": {
                                "main_direction": "long",
                                "position_state": "in_position",
                                "long": {
                                    "entry_price": "124.56",
                                    "size": "0.5"
                                },
                                "short": None,
                                "dca_levels": {
                                    "long": ["level1", "level2"],
                                    "short": []
                                }
                            }
                        }
                    }
                }
            }
        },
        404: {"description": "사용자 또는 심볼 정보를 찾을 수 없음"},
        500: {"description": "서버 오류"}
    })
async def get_user_symbol_status(okx_uid: str, symbol: str): # user_id -> okx_uid
    """
    특정 사용자의 특정 심볼에 대한 트레이딩 상태 상세 조회 (OKX UID 기준)

    Args:
        okx_uid (str): 조회할 OKX UID
        symbol (str): 조회할 심볼 (예: SOL-USDT-SWAP)

    Returns:
        Dict: 심볼별 트레이딩 상태 정보
    """
    try:
        # Redis 연결 확인
        if not await get_redis_client().ping():
            await handle_critical_error(
                error=Exception("Redis ping 실패"),
                category=ErrorCategory.REDIS_CONNECTION,
                context={"endpoint": "start_all_users"},
                okx_uid="system"
            )
            raise HTTPException(status_code=500, detail="Redis 연결 실패")
        
        # 사용자 트레이딩 상태 확인 (okx_uid 사용)
        status_key = f"user:{okx_uid}:trading:status" # 키 변경
        trading_status = await get_redis_client().get(status_key)
        
        # 심볼 정보 확인 (okx_uid 사용)
        symbol_status_key = f"user:{okx_uid}:position:{symbol}:position_state" # 키 변경
        symbol_status = await get_redis_client().get(symbol_status_key)
        
        # 기본 응답 구조
        response_data = {
            "symbol": symbol,
            "trading_status": trading_status,
        }
        
        # 포지션 정보 수집 (okx_uid 사용)
        position_info = {}
        
        # 메인 방향 정보
        main_direction_key = f"user:{okx_uid}:position:{symbol}:main_direction_direction" # 키 변경
        main_direction = await get_redis_client().get(main_direction_key)
        if main_direction:
            position_info["main_direction"] = main_direction
        
        # 포지션 상태
        if symbol_status:
            position_info["position_state"] = symbol_status
        
        # 롱 포지션 정보
        long_position_key = f"user:{okx_uid}:position:{symbol}:long" # 키 변경
        long_position = await get_redis_client().get(long_position_key)
        if long_position:
            try:
                position_info["long"] = json.loads(long_position)
            except:
                position_info["long"] = long_position
        
        # 숏 포지션 정보
        short_position_key = f"user:{okx_uid}:position:{symbol}:short" # 키 변경
        short_position = await get_redis_client().get(short_position_key)
        if short_position:
            try:
                position_info["short"] = json.loads(short_position)
            except:
                position_info["short"] = short_position
        
        # DCA 레벨 정보
        dca_levels = {}
        long_dca_key = f"user:{okx_uid}:position:{symbol}:long_dca_levels" # 키 변경
        short_dca_key = f"user:{okx_uid}:position:{symbol}:short_dca_levels" # 키 변경
        
        long_dca = await get_redis_client().get(long_dca_key)
        short_dca = await get_redis_client().get(short_dca_key)
        
        if long_dca or short_dca:
            if long_dca:
                try:
                    dca_levels["long"] = json.loads(long_dca)
                except:
                    dca_levels["long"] = long_dca
            
            if short_dca:
                try:
                    dca_levels["short"] = json.loads(short_dca)
                except:
                    dca_levels["short"] = short_dca
            
            position_info["dca_levels"] = dca_levels
        
        response_data["position_info"] = position_info
        
        # 심볼에 대한 설정 정보 추가 (있다면) (okx_uid 사용)
        symbol_settings_key = f"user:{okx_uid}:preferences" # 키 변경
        symbol_settings = await get_redis_client().hgetall(symbol_settings_key)
        if symbol_settings:
            response_data["preferences"] = symbol_settings
        
        return {
            "status": "success",
            "data": response_data
        }
        
    except Exception as e:
        logger.error(f"사용자 심볼별 상태 조회 실패 (okx_uid: {okx_uid}, symbol: {symbol}): {str(e)}", exc_info=True) # 로그 변경
        raise HTTPException(
            status_code=500,
            detail=f"심볼별 상태 조회 실패: {str(e)}"
        )
