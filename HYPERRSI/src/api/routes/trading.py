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
from HYPERRSI.src.services.multi_symbol_service import (
    multi_symbol_service,
    MaxSymbolsReachedError,
)
from HYPERRSI.src.services.timescale_service import TimescaleUserService
from HYPERRSI.src.trading.trading_service import TradingService, get_okx_client
from shared.config import settings as app_settings
from shared.database.redis_helper import get_redis_client
from shared.database.redis_patterns import scan_keys_pattern, redis_context, RedisTimeout
from shared.database.redis_helpers import safe_ping
from shared.helpers.user_id_resolver import (
    get_okx_uid_from_telegram,
    get_telegram_id_from_okx_uid,
    is_telegram_id,
    resolve_user_identifier,
)
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
    preset_id: Optional[str] = None  # 멀티심볼 모드에서 프리셋 지정

    model_config = {
        "json_schema_extra": {
            "example": {
                "user_id": "1709556958", # user_id -> okx_uid
                "symbol": "SOL-USDT-SWAP",
                "timeframe": "1m",
                "preset_id": "a1b2c3d4"  # optional
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
        

        # Redis 연결 확인 (standardized helper with timeout protection)
        try:
            redis_client = await get_redis_client()
            if not await safe_ping(redis_client):
                raise HTTPException(status_code=500, detail="Redis 연결 실패")
        except Exception as redis_error:
            logger.error(f"Redis 연결 오류: {str(redis_error)}")
            await handle_critical_error(
                error=redis_error,
                category=ErrorCategory.REDIS_CONNECTION,
                context={"endpoint": "start_trading", "okx_uid": okx_uid},
                okx_uid=okx_uid
            )
            raise HTTPException(status_code=500, detail=f"Redis 연결 오류: {str(redis_error)}")

        # 통합 resolver를 사용하여 okx_uid로 변환
        original_id = okx_uid
        okx_uid = await resolve_user_identifier(okx_uid)

        # telegram_id 조회 (알림 발송용)
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
        #    # 심볼별 상태를 'stopped'로 설정해야 함 (레거시 코드 - 사용 안함)
        #    # await redis_client.set(f"user:{okx_uid}:symbol:{symbol}:status", "stopped")
        #    raise HTTPException(status_code=403, detail="권한이 없는 사용자입니다.")
            
        
        # 심볼과 타임프레임 가져오기
        symbol = request.symbol
        timeframe = request.timeframe
        preset_id = request.preset_id

        # === 멀티심볼 모드: 심볼 추가 가능 여부 확인 ===
        if app_settings.MULTI_SYMBOL_ENABLED:
            can_add, error_msg = await multi_symbol_service.can_add_symbol(okx_uid, symbol)
            if not can_add:
                if error_msg and error_msg.startswith("MAX_SYMBOLS_REACHED:"):
                    # 최대 심볼 수 도달 - 409 Conflict 반환
                    active_symbols_str = error_msg.split(":", 1)[1]
                    active_symbols = active_symbols_str.split(",") if active_symbols_str else []
                    logger.warning(f"[{okx_uid}] 최대 심볼 수 도달. 활성 심볼: {active_symbols}")
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": "MAX_SYMBOLS_REACHED",
                            "message": f"최대 {app_settings.MAX_SYMBOLS_PER_USER}개 심볼까지 동시 트레이딩 가능합니다.",
                            "active_symbols": active_symbols,
                            "requested_symbol": symbol,
                            "hint": "기존 심볼 중 하나를 중지한 후 다시 시도해주세요."
                        }
                    )
                else:
                    raise HTTPException(status_code=400, detail=error_msg or "심볼 추가 불가")

        # 멀티심볼 모드: 심볼별 상태 확인
        # can_add_symbol()에서 이미 symbol-level 체크 완료했으므로 여기서는 추가 검증 없음
        # 심볼별 running 상태 확인
        from HYPERRSI.src.utils.status_utils import get_symbol_status
        symbol_status = await get_symbol_status(okx_uid, symbol)
        is_running = symbol_status == "running"

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
                # 심볼별 상태 관리로 전환 - user-level status 제거
                # await redis_client.set(f"user:{telegram_id}:symbol:{symbol}:status", "running")
                await get_redis_client().hset(
                    f"user:{telegram_id}:preferences",
                    mapping={"symbol": request.symbol, "timeframe": request.timeframe}
                )

            symbol = request.symbol
            timeframe = request.timeframe

            # 심볼별 상태를 'running'으로 설정
            symbol_status_key = f"user:{okx_uid}:symbol:{symbol}:status"
            await get_redis_client().set(symbol_status_key, "running")

            # preferences 저장
            await get_redis_client().hset(
                f"user:{okx_uid}:preferences",
                mapping={"symbol": symbol, "timeframe": timeframe}
            )

            # Celery 태스크 실행 (okx_uid 전달)
            # 🔧 FIX: API를 통한 시작은 항상 restart=True로 전달
            # Race condition 방지: Task가 Redis 상태 확인을 건너뛰고 즉시 실행
            task = celery_app.send_task(
                'trading_tasks.execute_trading_cycle',
                args=[okx_uid, symbol, timeframe, True]  # 항상 True로 전달
            )
            logger.info(f"[{okx_uid}] 새 트레이딩 태스크 시작: {task.id} (symbol: {symbol}, timeframe: {timeframe})")

            # task_id 저장 (telegram_id와 okx_uid 모두)
            if telegram_id:
                await get_redis_client().set(f"user:{telegram_id}:task_id", task.id)
            await get_redis_client().set(f"user:{okx_uid}:task_id", task.id)

            # === 멀티심볼 모드: 심볼 등록 ===
            if app_settings.MULTI_SYMBOL_ENABLED:
                try:
                    await multi_symbol_service.add_symbol(
                        okx_uid=okx_uid,
                        symbol=symbol,
                        timeframe=timeframe,
                        preset_id=preset_id,
                        task_id=task.id
                    )
                    logger.info(f"[{okx_uid}] 멀티심볼 등록 완료: {symbol}")
                except MaxSymbolsReachedError as e:
                    # 동시성 이슈로 등록 실패 시 태스크 취소
                    logger.error(f"[{okx_uid}] 멀티심볼 등록 실패 (race condition): {e}")
                    celery_app.control.revoke(task.id, terminate=True)
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": "MAX_SYMBOLS_REACHED",
                            "message": str(e),
                            "active_symbols": e.active_symbols,
                            "requested_symbol": symbol
                        }
                    )

            # 응답 구성
            response_data = {
                "status": "success",
                "message": "트레이딩 태스크가 시작되었습니다.",
                "task_id": task.id,
                "symbol": symbol,
                "timeframe": timeframe
            }

            # 멀티심볼 모드에서 추가 정보 제공
            if app_settings.MULTI_SYMBOL_ENABLED:
                active_symbols = await multi_symbol_service.get_active_symbols(okx_uid)
                response_data["multi_symbol_mode"] = True
                response_data["active_symbols"] = active_symbols
                response_data["remaining_slots"] = app_settings.MAX_SYMBOLS_PER_USER - len(active_symbols)

            return response_data
        except Exception as task_error:
            logger.error(f"태스크 시작 오류 (okx_uid: {okx_uid}): {str(task_error)}", exc_info=True)
            await handle_critical_error(
                error=task_error,
                category=ErrorCategory.CELERY_TASK,
                context={"endpoint": "start_trading", "okx_uid": okx_uid, "symbol": symbol, "timeframe": timeframe},
                okx_uid=okx_uid
            )
            # Redis 심볼별 상태 초기화
            if telegram_id:
                await get_redis_client().set(f"user:{telegram_id}:symbol:{symbol}:status", "error")
            # okx_status_key는 이미 symbol-level로 설정됨 (line 405-407)
            await get_redis_client().set(okx_status_key, "error")
            raise HTTPException(status_code=500, detail=f"트레이딩 태스크 시작 실패: {str(task_error)}")
            
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"트레이딩 시작 중 오류 (okx_uid: {okx_uid}): {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"트레이딩 시작 실패: {str(e)}")



@router.post("/start_all_users",
    summary="모든 실행 중인 트레이딩 태스크 재시작 (OKX UID 기준)",
    description="""
서버 재시작 등으로 다운 후, 기존에 실행 중이던 모든 사용자의 트레이딩 태스크를 재시작합니다 (OKX UID 기준).

멀티심볼 모드에서는 각 사용자의 모든 활성 심볼을 재시작합니다.
    """,
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
                        ],
                        "multi_symbol_mode": True
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

        restarted_users = []
        errors = []

        # === 멀티심볼 모드: active_symbols SET 기반 재시작 ===
        if app_settings.MULTI_SYMBOL_ENABLED:
            logger.info("멀티심볼 모드로 start_all_users 실행")
            async with redis_context(timeout=RedisTimeout.SLOW_OPERATION) as redis:
                # active_symbols 키 스캔
                cursor = 0
                pattern = "user:*:active_symbols"

                while True:
                    cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100)

                    for key in keys:
                        if isinstance(key, bytes):
                            key = key.decode('utf-8')

                        # 키 형식: user:{okx_uid}:active_symbols
                        parts = key.split(':')
                        if len(parts) < 3 or parts[2] != 'active_symbols':
                            continue

                        okx_uid = parts[1]

                        try:
                            # 활성 심볼 목록 조회
                            active_symbols = await redis.smembers(key)

                            for symbol in active_symbols:
                                if isinstance(symbol, bytes):
                                    symbol = symbol.decode('utf-8')

                                # 심볼별 timeframe 조회
                                timeframe_key = f"user:{okx_uid}:symbol:{symbol}:timeframe"
                                timeframe = await redis.get(timeframe_key)
                                if isinstance(timeframe, bytes):
                                    timeframe = timeframe.decode('utf-8')
                                timeframe = timeframe or "1m"

                                # 기존 심볼별 task_id 확인 및 종료
                                symbol_task_id_key = f"user:{okx_uid}:symbol:{symbol}:task_id"
                                current_task_id = await redis.get(symbol_task_id_key)
                                if current_task_id:
                                    if isinstance(current_task_id, bytes):
                                        current_task_id = current_task_id.decode('utf-8')
                                    logger.info(f"[{okx_uid}] 기존 {symbol} 태스크 종료: {current_task_id}")
                                    celery_app.control.revoke(current_task_id, terminate=True)
                                    await redis.delete(symbol_task_id_key)

                                # 새 태스크 시작
                                task = celery_app.send_task(
                                    'trading_tasks.execute_trading_cycle',
                                    args=[okx_uid, symbol, timeframe, True]
                                )

                                # 심볼별 task_id 저장
                                await redis.set(symbol_task_id_key, task.id)
                                await redis.set(f"user:{okx_uid}:symbol:{symbol}:status", "running")

                                logger.info(f"[{okx_uid}] {symbol} 태스크 재시작: {task.id}")
                                restarted_users.append({
                                    "okx_uid": okx_uid,
                                    "symbol": symbol,
                                    "task_id": task.id
                                })

                        except Exception as user_err:
                            logger.error(f"[{okx_uid}] 재시작 중 에러: {str(user_err)}", exc_info=True)
                            errors.append({"okx_uid": okx_uid, "error": str(user_err)})

                    if cursor == 0:
                        break

                # 심볼별 상태는 이미 multi_symbol_service.add_symbol()에서 설정됨
                # 레거시 user-level 상태 업데이트 제거
                # 레거시 모드 제거 - 멀티심볼 모드만 사용

        logger.info(f"재시작 완료: {len(restarted_users)}개 성공, {len(errors)}개 실패")

        response = {
            "status": "success",
            "message": "모든 실행 중인 트레이딩 태스크에 재시작 명령을 보냈습니다.",
            "restarted_users": restarted_users,
            "multi_symbol_mode": app_settings.MULTI_SYMBOL_ENABLED
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

- `user:{okx_uid}:symbol:{symbol}:status` → "stopped" (심볼별 상태)
- `user:{okx_uid}:symbol:{symbol}:task_id` → 삭제
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
async def stop_trading(
    request: Request,
    user_id: Optional[str] = Query(None, description="사용자 ID (OKX UID 또는 텔레그램 ID)"),
    symbol: Optional[str] = Query(None, description="중지할 심볼 (멀티심볼 모드)")
):
    try:
        # symbol은 쿼리 파라미터로 받은 값 사용 (None일 수 있음)
        target_symbol = symbol  # 쿼리 파라미터로 받은 심볼
        okx_uid = None
        print(f"⭐️user_id: {user_id}, symbol: {symbol}")
        # 1. 쿼리 파라미터에서 user_id 확인
        if user_id:
            okx_uid = user_id
            print("⭐️okx_uid222: ", okx_uid)
        else:
            # 2. JSON 본문에서 okx_uid 확인 (기존 방식)
            try:
                request_body = await request.json()
                if "okx_uid" in request_body:
                    okx_uid = request_body["okx_uid"]
                    print("⭐️okx_uid333: ", okx_uid)
            except (json.JSONDecodeError, ValueError, AttributeError):
                pass
        
        # 3. 필수 파라미터 확인
        if not okx_uid:
            raise HTTPException(status_code=400, detail="user_id 또는 okx_uid가 필요합니다.")
        logger.info(f"사용자 {okx_uid}의 트레이딩 태스크 중지 시도")

        # 통합 resolver를 사용하여 okx_uid로 변환
        original_id = okx_uid
        okx_uid = await resolve_user_identifier(okx_uid)

        # telegram_id 조회 (알림 발송용)
        telegram_id = None
        try:
            telegram_id = await get_telegram_id_from_okx_uid(okx_uid, TimescaleUserService)
        except Exception as e:
            logger.debug(f"텔레그램 ID 조회 실패 (무시됨): {str(e)}")
        
        # 멀티심볼 모드: 심볼별 상태 관리
        # target_symbol이 지정되면 해당 심볼만, 아니면 모든 심볼 중지
        from HYPERRSI.src.services.multi_symbol_service import multi_symbol_service
        active_symbols = await multi_symbol_service.get_active_symbols(okx_uid)

        if not active_symbols:
            logger.warning(f"사용자 {okx_uid}의 활성 심볼이 없습니다.")
            return {
                "status": "success",
                "message": "트레이딩이 이미 중지되어 있습니다."
            }

        # 중지할 심볼 결정: target_symbol이 지정되면 해당 심볼만, 아니면 모든 심볼
        if target_symbol:
            # 특정 심볼만 중지
            if target_symbol not in active_symbols:
                logger.warning(f"사용자 {okx_uid}의 심볼 {target_symbol}이 활성 상태가 아닙니다.")
                return {
                    "status": "success",
                    "message": f"{target_symbol}은(는) 이미 중지되어 있습니다."
                }
            symbols_to_stop = [target_symbol]
            logger.info(f"[{okx_uid}] 특정 심볼 중지 요청: {target_symbol}")
        else:
            # 모든 심볼 중지
            symbols_to_stop = active_symbols
            logger.info(f"[{okx_uid}] 전체 심볼 중지 요청: {active_symbols}")

        # 선택된 심볼의 상태를 stopped로 변경
        for sym in symbols_to_stop:
            symbol_status_key = f"user:{okx_uid}:symbol:{sym}:status"
            await get_redis_client().set(symbol_status_key, "stopped")
            logger.info(f"심볼 {sym}의 트레이딩 상태를 stopped로 변경했습니다.")
        
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
            
        # 선호도 정보에서 타임프레임 가져오기 (락 해제용)
        # 심볼은 쿼리 파라미터(target_symbol) 또는 symbols_to_stop 사용
        timeframe = None
        try:
            if telegram_id:
                preference_key = f"user:{telegram_id}:preferences"
                timeframe = await get_redis_client().hget(preference_key, "timeframe")

            if not timeframe:
                preference_key = f"user:{okx_uid}:preferences"
                timeframe = await get_redis_client().hget(preference_key, "timeframe")

            # 1. 중지할 심볼들에 대해 락(lock) 해제
            for sym in symbols_to_stop:
                if timeframe:
                    lock_key = f"lock:user:{okx_uid}:{sym}:{timeframe}"
                    try:
                        lock_exists = await get_redis_client().exists(lock_key)
                        if lock_exists:
                            logger.info(f"[{okx_uid}] 락 해제: {sym}/{timeframe}")
                            await get_redis_client().delete(lock_key)
                    except Exception as lock_err:
                        logger.warning(f"[{okx_uid}] 락 삭제 중 오류 (무시됨): {str(lock_err)}")

                # 2. 쿨다운 키 해제 (long/short 모두)
                for direction in ["long", "short"]:
                    cooldown_key = f"user:{okx_uid}:cooldown:{sym}:{direction}"
                    try:
                        cooldown_exists = await get_redis_client().exists(cooldown_key)
                        if cooldown_exists:
                            logger.info(f"[{okx_uid}] 쿨다운 해제: {sym}/{direction}")
                            await get_redis_client().delete(cooldown_key)
                    except Exception as cooldown_err:
                        logger.warning(f"[{okx_uid}] 쿨다운 삭제 중 오류 (무시됨): {str(cooldown_err)}")
        except Exception as pref_err:
            logger.warning(f"선호도 정보 조회 중 오류 (무시됨): {str(pref_err)}")
            
        # 사용자에게 트레이딩 중지 메시지 전송
        try:
            # telegram_id가 있으면 우선 사용, 없으면 okx_uid 사용
            recipient_id = telegram_id if telegram_id else okx_uid
            stopped_symbols_str = ", ".join(symbols_to_stop)
            await send_telegram_message(
                f" 트레이딩이 중지되었습니다.\n\n"
                f"심볼: {stopped_symbols_str}\n"
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

            # 중지할 심볼들에 대해 쿨다운/락 키 삭제
            for sym in symbols_to_stop:
                for direction in ["long", "short"]:
                    cooldown_key = f"user:{okx_uid}:cooldown:{sym}:{direction}"
                    keys_to_delete.append(cooldown_key)

                if timeframe:
                    lock_key = f"lock:user:{okx_uid}:{sym}:{timeframe}"
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

        # === 멀티심볼 모드: 중지된 심볼들 제거 ===
        if app_settings.MULTI_SYMBOL_ENABLED:
            for sym in symbols_to_stop:
                try:
                    await multi_symbol_service.remove_symbol(okx_uid, sym)
                    logger.info(f"[{okx_uid}] 멀티심볼 제거 완료: {sym}")
                except Exception as ms_err:
                    logger.warning(f"[{okx_uid}] 멀티심볼 제거 중 오류 (무시됨): {sym}, {str(ms_err)}")

        # TradingService cleanup
        try:
            if trading_service:
                await trading_service.cleanup()
                logger.info(f"TradingService cleanup 완료 (user_id: {okx_uid})")
        except Exception as cleanup_err:
            logger.error(f"TradingService cleanup 중 오류 발생 (user_id: {okx_uid}): {str(cleanup_err)}", exc_info=True)
            
        # 응답 구성
        response_data = {
            "status": "success",
            "message": "트레이딩 중지 신호가 보내졌습니다. 잠시 후 중지됩니다.",
            "stopped_symbols": symbols_to_stop
        }

        # 멀티심볼 모드에서 추가 정보 제공
        if app_settings.MULTI_SYMBOL_ENABLED:
            remaining_active_symbols = await multi_symbol_service.get_active_symbols(okx_uid)
            response_data["multi_symbol_mode"] = True
            response_data["remaining_active_symbols"] = remaining_active_symbols
            response_data["remaining_slots"] = app_settings.MAX_SYMBOLS_PER_USER - len(remaining_active_symbols)

        return response_data
    except Exception as e:
        logger.error(f"트레이딩 중지 중 오류 발생 (user_id: {okx_uid}): {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"트레이딩 중지 실패: {str(e)}"
        )


@router.get(
    "/active_symbols/{okx_uid}",
    summary="사용자의 활성 심볼 목록 조회",
    description="""
# 활성 심볼 목록 조회

멀티심볼 모드에서 특정 사용자가 현재 트레이딩 중인 모든 심볼 목록과 상세 정보를 조회합니다.

## 반환 정보

- **okx_uid**: 사용자 OKX UID
- **multi_symbol_enabled**: 멀티심볼 모드 활성화 여부
- **max_symbols**: 최대 동시 트레이딩 가능 심볼 수
- **active_count**: 현재 활성 심볼 수
- **remaining_slots**: 추가 가능한 심볼 슬롯 수
- **symbols**: 활성 심볼 상세 정보 배열
    """,
    responses={
        200: {
            "description": "활성 심볼 목록 조회 성공",
            "content": {
                "application/json": {
                    "example": {
                        "okx_uid": "518796558012178692",
                        "multi_symbol_enabled": True,
                        "max_symbols": 3,
                        "active_count": 2,
                        "remaining_slots": 1,
                        "symbols": [
                            {
                                "symbol": "BTC-USDT-SWAP",
                                "timeframe": "1m",
                                "status": "running",
                                "preset_id": "a1b2c3d4",
                                "started_at": "1700000000.0"
                            },
                            {
                                "symbol": "ETH-USDT-SWAP",
                                "timeframe": "5m",
                                "status": "running",
                                "preset_id": None,
                                "started_at": "1700001000.0"
                            }
                        ]
                    }
                }
            }
        }
    }
)
async def get_active_symbols(okx_uid: str):
    """사용자의 활성 심볼 목록 조회"""
    try:
        # 멀티심볼 모드 (레거시 모드 제거)
        symbols_info = await multi_symbol_service.list_symbols_with_info(okx_uid)

        return {
            "okx_uid": okx_uid,
            "multi_symbol_enabled": True,
            "max_symbols": app_settings.MAX_SYMBOLS_PER_USER,
            "active_count": len(symbols_info),
            "remaining_slots": app_settings.MAX_SYMBOLS_PER_USER - len(symbols_info),
            "symbols": symbols_info
        }

    except Exception as e:
        logger.error(f"활성 심볼 조회 중 오류 (okx_uid: {okx_uid}): {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"활성 심볼 조회 실패: {str(e)}")


@router.get(
    "/running_users",
    summary="실행 중인 모든 사용자 조회 (OKX UID 기준)",
    description="""
# 실행 중인 모든 사용자 조회

Redis에서 트레이딩 상태가 'running'인 모든 사용자의 OKX UID 목록을 조회합니다.

## 동작 방식

1. **Redis 패턴 매칭**: `user:*:symbol:*:status` 패턴으로 모든 심볼별 상태 키 조회
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
    현재 'running' 상태인 모든 OKX UID를 조회 (멀티심볼 모드)
    """
    try:
        # 멀티심볼 모드: 심볼별 상태 확인
        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            if not await safe_ping(redis):
                raise HTTPException(status_code=500, detail="Redis 연결 실패")

            # user:*:symbol:*:status 패턴으로 모든 심볼별 상태 키 조회
            status_keys = await scan_keys_pattern("user:*:symbol:*:status", redis=redis)
            running_users_set = set()  # 중복 제거를 위해 set 사용

            for key in status_keys:
                status = await asyncio.wait_for(
                    redis.get(key),
                    timeout=RedisTimeout.FAST_OPERATION
                )

                # 바이트 문자열을 디코딩
                if isinstance(status, bytes):
                    status = status.decode('utf-8')

                if status == "running":
                    # key 구조: user:{okx_uid}:symbol:{symbol}:status
                    parts = key.split(":")
                    if len(parts) >= 2 and parts[0] == 'user':
                        okx_uid = parts[1]
                        running_users_set.add(okx_uid)
                    else:
                        logger.warning(f"잘못된 키 형식 발견: {key}")

            return {
                "status": "success",
                "running_users": list(running_users_set)
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
        # 멀티심볼 모드: 심볼별 상태 확인 및 일괄 중지
        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            if not await safe_ping(redis):
                raise HTTPException(status_code=500, detail="Redis 연결 실패")

            # user:*:symbol:*:status 패턴으로 모든 심볼별 상태 키 조회
            status_keys = await scan_keys_pattern("user:*:symbol:*:status", redis=redis)
            stopped_users = {}  # {okx_uid: [symbols]} 형식으로 저장
            errors = []

            logger.info(f"총 {len(status_keys)}개의 심볼별 상태 키 발견")

            for key in status_keys:
                status = await asyncio.wait_for(
                    redis.get(key),
                    timeout=RedisTimeout.FAST_OPERATION
                )

                # 바이트 문자열을 디코딩
                if isinstance(status, bytes):
                    status = status.decode('utf-8')

                if status == "running":
                    # key 구조: user:{okx_uid}:symbol:{symbol}:status
                    parts = key.split(":")
                    if len(parts) >= 4 and parts[0] == 'user' and parts[2] == 'symbol':
                        okx_uid = parts[1]
                        symbol = parts[3]
                    else:
                        logger.warning(f"잘못된 키 형식 발견: {key}")
                        continue

                    logger.info(f"사용자 {okx_uid}, 심볼 {symbol} 중지 시도 중")

                    try:
                        # 심볼별 종료 신호 설정
                        await asyncio.wait_for(
                            redis.set(f"user:{okx_uid}:stop_signal", "true"),
                            timeout=RedisTimeout.FAST_OPERATION
                        )
                        # 심볼별 상태를 stopped로 변경
                        await asyncio.wait_for(
                            redis.set(f"user:{okx_uid}:symbol:{symbol}:status", "stopped"),
                            timeout=RedisTimeout.FAST_OPERATION
                        )
                        # await send_telegram_message(f"[{okx_uid}] User의 상태를 Stopped로 강제 변경.6", okx_uid, debug=True)
                        logger.info(f"사용자 {okx_uid}, 심볼 {symbol}에게 종료 신호를 설정했습니다.")

                        # TradingService 초기화 및 활성 주문 취소
                        trading_service = None
                        try:
                            trading_service = TradingService(user_id=okx_uid)
                            if not trading_service.client:
                                trading_service.client = await get_okx_client(user_id=okx_uid)

                            # symbol은 이미 key에서 추출됨
                            logger.info(f"사용자 {okx_uid}의 열린 주문 취소 시도 (심볼: {symbol})")
                            try:
                                await trading_service.cancel_all_open_orders(trading_service.client, symbol, okx_uid)
                                logger.info(f"모든 열린 주문이 취소되었습니다. okx_uid: {okx_uid}, symbol: {symbol}")
                            except Exception as cancel_err:
                                logger.error(f"주문 취소 중 오류 발생 (user_id: {okx_uid}): {str(cancel_err)}", exc_info=True)
                        except Exception as service_err:
                            logger.error(f"TradingService 초기화 중 오류 발생 (user_id: {okx_uid}): {str(service_err)}", exc_info=True)

                        # Celery task 취소 (심볼별 task_id 사용)
                        task_id_key = f"user:{okx_uid}:symbol:{symbol}:task_id"
                        task_id = await asyncio.wait_for(
                            redis.get(task_id_key),
                            timeout=RedisTimeout.FAST_OPERATION
                        )
                        if task_id:
                            try:
                                logger.info(f"Celery 태스크 취소 시도 (task_id: {task_id}, okx_uid: {okx_uid}, symbol: {symbol})")
                                celery_app.control.revoke(task_id, terminate=True, signal='SIGTERM')
                                logger.info(f"Celery 태스크 취소 명령 전송 완료 (task_id: {task_id})")
                            except Exception as revoke_err:
                                logger.error(f"태스크 취소 중 오류 발생 (task_id: {task_id}): {str(revoke_err)}", exc_info=True)

                        # Redis 심볼별 상태 초기화
                        try:
                            logger.info(f"사용자 {okx_uid}, 심볼 {symbol}의 Redis 상태 초기화 중")

                            # 심볼별 키 삭제
                            keys_to_delete = [
                                f"user:{okx_uid}:symbol:{symbol}:task_id",
                                f"user:{okx_uid}:symbol:{symbol}:status",
                                f"user:{okx_uid}:symbol:{symbol}:started_at",
                                f"user:{okx_uid}:symbol:{symbol}:timeframe",
                                f"user:{okx_uid}:symbol:{symbol}:preset_id",
                                f"user:{okx_uid}:symbol:{symbol}:task_running",
                                f"user:{okx_uid}:stop_signal",
                            ]

                            # 포지션 키 삭제
                            position_keys = [
                                f"user:{okx_uid}:position:{symbol}:main_direction_direction",
                                f"user:{okx_uid}:position:{symbol}:position_state",
                                f"user:{okx_uid}:position:{symbol}:long",
                                f"user:{okx_uid}:position:{symbol}:short",
                                f"user:{okx_uid}:position:{symbol}:long_dca_levels",
                                f"user:{okx_uid}:position:{symbol}:short_dca_levels"
                            ]
                            keys_to_delete.extend(position_keys)

                            for key_to_del in keys_to_delete:
                                try:
                                    await asyncio.wait_for(
                                        redis.delete(key_to_del),
                                        timeout=RedisTimeout.FAST_OPERATION
                                    )
                                except Exception as del_err:
                                    logger.warning(f"키 삭제 중 오류 발생 (key: {key_to_del}): {str(del_err)}")

                            # active_symbols에서 제거
                            await redis.srem(f"user:{okx_uid}:active_symbols", symbol)

                            logger.debug(f"사용자 {okx_uid}, 심볼 {symbol}의 Redis 상태 초기화 완료")
                        except Exception as redis_err:
                            logger.error(f"Redis 상태 초기화 중 오류 발생 (user_id: {okx_uid}, symbol: {symbol}): {str(redis_err)}", exc_info=True)

                        # TradingService cleanup
                        if trading_service:
                            try:
                                await trading_service.cleanup()
                                logger.info(f"TradingService cleanup 완료 (user_id: {okx_uid})")
                            except Exception as cleanup_err:
                                logger.error(f"TradingService cleanup 중 오류 발생 (user_id: {okx_uid}): {str(cleanup_err)}", exc_info=True)

                        # stopped_users 딕셔너리에 추가
                        if okx_uid not in stopped_users:
                            stopped_users[okx_uid] = []
                        stopped_users[okx_uid].append(symbol)
                        logger.info(f"사용자 {okx_uid}, 심볼 {symbol} 중지 신호 전송 완료")

                        # 다음 심볼 처리 전 짧은 지연 추가
                        await asyncio.sleep(0.5)

                    except Exception as user_err:
                        errors.append({"okx_uid": okx_uid, "symbol": symbol, "error": str(user_err)})
                        logger.error(f"{okx_uid}, {symbol} 중지 실패: {str(user_err)}", exc_info=True)
                        await handle_critical_error(
                            error=user_err,
                            category=ErrorCategory.MASS_OPERATION,
                            context={"endpoint": "stop_all_running_users", "okx_uid": okx_uid, "symbol": symbol, "operation": "stop"},
                            okx_uid=okx_uid
                        )

            # 중지된 심볼 수 계산
            total_stopped = sum(len(symbols) for symbols in stopped_users.values())
            logger.info(f"중지 완료: {total_stopped}개 심볼 성공, {len(errors)}개 실패")

            response = {
                "status": "success",
                "message": "running 상태인 모든 심볼에 대해 중지 신호를 전송했습니다. 잠시 후 모두 중지됩니다.",
                "stopped_users": stopped_users  # {okx_uid: [symbols]} 형식
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
        # 멀티심볼 모드: 심볼별 상태 확인 및 일괄 재시작
        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            if not await safe_ping(redis):
                raise HTTPException(status_code=500, detail="Redis 연결 실패")

            # user:*:symbol:*:status 패턴으로 모든 심볼별 상태 키 조회
            status_keys = await scan_keys_pattern("user:*:symbol:*:status", redis=redis)
            restarted_users = {}  # {okx_uid: [symbols]} 형식으로 저장
            errors = []

            for key in status_keys:
                status = await asyncio.wait_for(
                    redis.get(key),
                    timeout=RedisTimeout.FAST_OPERATION
                )

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
                        symbol = await asyncio.wait_for(
                            redis.hget(preference_key, "symbol"),
                            timeout=RedisTimeout.FAST_OPERATION
                        )
                        timeframe = await asyncio.wait_for(
                            redis.hget(preference_key, "timeframe"),
                            timeout=RedisTimeout.FAST_OPERATION
                        )

                        task_id_key = f"user:{okx_uid}:task_id"
                        current_task_id = await asyncio.wait_for(
                            redis.get(task_id_key),
                            timeout=RedisTimeout.FAST_OPERATION
                        )

                        if current_task_id:
                            logger.info(f"기존 태스크 종료: {current_task_id} (okx_uid: {okx_uid})")
                            celery_app.control.revoke(current_task_id, terminate=True)
                            await asyncio.wait_for(
                                redis.delete(task_id_key),
                                timeout=RedisTimeout.FAST_OPERATION
                            )
                            await asyncio.wait_for(
                                redis.set(key, "restarting"),
                                timeout=RedisTimeout.FAST_OPERATION
                            ) # 상태 키 사용
                            await asyncio.sleep(0.5)

                        # 기존 방식으로 태스크 실행 (okx_uid 전달)
                        task = celery_app.send_task(
                            'trading_tasks.execute_trading_cycle',  # 새 태스크 함수 이름
                            args=[okx_uid, symbol, timeframe , True]  # restart=True
                        )
                        # Redis 상태 업데이트 (okx_uid 사용)
                        await asyncio.wait_for(
                            redis.set(key, "running"),
                            timeout=RedisTimeout.FAST_OPERATION
                        ) # 상태 키 사용
                        await asyncio.wait_for(
                            redis.set(task_id_key, task.id),
                            timeout=RedisTimeout.FAST_OPERATION
                        ) # 태스크 ID 키 사용

                        # preference 정보 확인 및 업데이트 (okx_uid 사용)
                        if symbol and timeframe:
                            await asyncio.wait_for(
                                redis.hset(
                                    preference_key,
                                    mapping={"symbol": symbol, "timeframe": timeframe}
                                ),
                                timeout=RedisTimeout.FAST_OPERATION
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
                        await asyncio.wait_for(
                            redis.set(key, "error"),
                            timeout=RedisTimeout.FAST_OPERATION
                        ) # 상태 키 사용

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
        
        # 심볼별 상태 키 패턴 조회 (okx_uid 사용)
        redis = await get_redis_client()
        pattern = f"user:{okx_uid}:symbol:*:status"
        status_keys = await redis.keys(pattern)

        # 심볼별 상태 집계
        symbol_statuses = {}
        overall_status = "stopped"  # 기본값

        for key in status_keys:
            key_str = key.decode('utf-8') if isinstance(key, bytes) else key
            # user:{okx_uid}:symbol:{symbol}:status
            parts = key_str.split(':')
            symbol = parts[3]
            status = await redis.get(key)
            if isinstance(status, bytes):
                status = status.decode('utf-8')
            symbol_statuses[symbol] = status
            if status == "running":
                overall_status = "running"

        if not symbol_statuses:
            return {
                "status": "success",
                "data": {
                    "trading_status": "not_found",
                    "message": "사용자의 트레이딩 정보가 없습니다."
                }
            }

        # 기본 응답 데이터 구성
        response_data = {
            "trading_status": overall_status,
            "symbol_statuses": symbol_statuses,
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
        
        # 심볼별 트레이딩 상태 확인 (okx_uid 사용)
        status_key = f"user:{okx_uid}:symbol:{symbol}:status"  # 심볼별 상태 키
        trading_status = await get_redis_client().get(status_key)
        if isinstance(trading_status, bytes):
            trading_status = trading_status.decode('utf-8')
        
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
            except Exception as e:
                position_info["long"] = long_position
        
        # 숏 포지션 정보
        short_position_key = f"user:{okx_uid}:position:{symbol}:short" # 키 변경
        short_position = await get_redis_client().get(short_position_key)
        if short_position:
            try:
                position_info["short"] = json.loads(short_position)
            except Exception as e:
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
                except Exception as e:
                    dca_levels["long"] = long_dca
            
            if short_dca:
                try:
                    dca_levels["short"] = json.loads(short_dca)
                except Exception as e:
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
