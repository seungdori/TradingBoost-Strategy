
import re
import trace
import traceback
from typing import Any, List

import redis
import uvicorn
from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, Request

import GRID.database.redis_database as redis_database
import GRID.strategies.grid as grid
import GRID.strategies.strategy as strategy
from GRID.database.redis_database import get_user_key, reset_user_data, save_running_symbols
from GRID.dtos.feature import (
    CoinDto,
    CoinSellAllFeatureDto,
    CoinSellFeatureDto,
    StartFeatureDto,
    StopFeatureDto,
    TestFeatureDto,
)
from GRID.services import bot_state_service
from GRID.strategies.grid_process import (
    get_running_users,
    start_grid_main_in_process,
    stop_grid_main_process,
    update_user_data,
)
from shared.dtos.bot_state import BotStateDto, BotStateKeyDto
from shared.dtos.response import ResponseDto

router = APIRouter(prefix="/feature", tags=["feature"])
import asyncio
import json
import os
import socket
from datetime import datetime
from zoneinfo import ZoneInfo

import redis.asyncio as aioredis

from GRID.trading.shared_state import user_keys
from shared.config import settings

REDIS_PASSWORD = settings.REDIS_PASSWORD
DEFAULT_PORT = int(os.environ.get('PORT', 8000))

async def get_redis_connection() -> aioredis.Redis:
    try:
        if REDIS_PASSWORD:
            redis = aioredis.from_url(settings.REDIS_URL, encoding='utf-8', decode_responses=True, password=REDIS_PASSWORD)
        else:
            redis = aioredis.from_url(settings.REDIS_URL, encoding='utf-8', decode_responses=True)
        return redis
    except Exception as e:
        print(f"Error connecting to Redis: {str(e)}")
        traceback.print_exc()
        raise


@router.post(
    "/save_running_symbols",
    summary="실행 중인 심볼 정보 저장",
    description="""
# 실행 중인 심볼 정보 저장

모든 실행 중인 봇의 거래 심볼 정보를 Redis에 백업합니다.

## 동작 프로세스

**3단계 저장 프로세스:**
1. **사용자 조회**: 모든 지원 거래소에서 실행 중인 사용자 목록 조회
2. **심볼 저장**: 각 사용자의 활성 거래 심볼 목록을 Redis에 저장
3. **복구 준비**: 서버 재시작 또는 복구 모드 시 자동 복원에 사용

## 저장되는 정보

각 사용자별로 저장되는 데이터:
- **running_symbols**: 현재 거래 중인 심볼 리스트
- **completed_trading_symbols**: 거래 완료된 심볼 리스트
- **user_data**: 사용자 설정 (그리드 설정, 레버리지 등)

## 사용 시나리오

**권장 사용 케이스:**
- 🔄 **복구 모드와 함께 사용**: `/recovery_mode` 호출 전에 실행
- 📋 **서버 점검 전**: 데이터 손실 방지를 위한 백업
- ⏰ **정기적인 백업**: 크론잡으로 주기적 실행 (예: 매 10분)
- 🛠️ **수동 백업**: 중요한 작업 전 수동으로 실행

## 지원 거래소

모든 설정된 거래소의 심볼 정보 저장:
- `binance`, `binance_spot`
- `upbit`
- `bitget`, `bitget_spot`
- `okx`, `okx_spot`
- `bybit`, `bybit_spot`

## 워크플로우 예시

**점검 전 안전 백업:**
```
1. POST /save_running_symbols     # 현재 상태 저장
2. POST /recovery_mode?ttl=600    # 복구 모드 활성화
3. 서버 점검/재시작 수행
4. 자동 복구
```

**정기 백업 크론잡:**
```bash
# 매 10분마다 심볼 정보 백업
*/10 * * * * curl -X POST http://localhost:8012/feature/save_running_symbols
```
""",
    responses={
        200: {
            "description": "✅ 심볼 정보 저장 성공",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "All running symbols saved.",
                        "meta": {
                            "total_exchanges": 9,
                            "total_users": 25,
                            "total_symbols": 150,
                            "timestamp": "2025-01-12T15:30:00+09:00"
                        },
                        "data": None
                    }
                }
            }
        },
        500: {
            "description": "💥 서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_error": {
                            "summary": "Redis 연결 실패",
                            "value": {
                                "success": False,
                                "message": "Failed to save running symbols",
                                "meta": {
                                    "error": "Cannot connect to Redis",
                                    "hint": "Check Redis server status"
                                },
                                "data": None
                            }
                        },
                        "partial_failure": {
                            "summary": "일부 저장 실패",
                            "value": {
                                "success": False,
                                "message": "Failed to save some running symbols",
                                "meta": {
                                    "saved_users": 23,
                                    "failed_users": 2,
                                    "error": "Timeout on some operations"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        503: {
            "description": "🔧 서비스 이용 불가",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_unavailable": {
                            "summary": "Redis 서버 이용 불가",
                            "value": {
                                "success": False,
                                "message": "Redis service unavailable",
                                "meta": {
                                    "error": "Redis server is down or unreachable",
                                    "retry_after": 30
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        }
    }
)
async def save_running_symbols_router():
    for exchange_id in ['binance', 'upbit', 'bitget', 'binance_spot', 'bitget_spot', 'okx', 'okx_spot', 'bybit', 'bybit_spot']:
        running_users = await get_running_users(exchange_id)
        for user_id in running_users:
            await save_running_symbols(exchange_id, user_id)
    return ResponseDto[None](
        success=True,
        message=f"All running symbols saved.",
        data=None
    )

async def get_request_body(redis: aioredis.Redis, key: str) -> str | None:
    """Redis에서 request_body를 가져옴"""
    value = await redis.get(key)
    return value


def get_request_port(request: Request) -> int:
    """
    요청의 원래 포트를 반환합니다.
    로드밸런서를 통한 요청인 경우 X-Forwarded-Port를 사용하고,
    그렇지 않은 경우 서버의 실제 포트를 사용합니다.
    """
    forwarded_port = request.headers.get("X-Forwarded-Port")
    if forwarded_port:
        return int(forwarded_port)
    return DEFAULT_PORT

def get_app_port(app: FastAPI) -> int:
    """현재 FastAPI 앱이 실행 중인 포트를 반환합니다."""
    config = uvicorn.Config(app)
    server = uvicorn.Server(config)
    return server.config.port

@router.post("/save_request_body")
async def save_all_running_request_body(request: Request) -> ResponseDto[None]:
    redis = await get_redis_connection()
    running_users = await get_running_users('okx', redis)
    for user_id in running_users:
        redis_key = f"okx:request_body:{user_id}"
        request_body_str = await get_request_body(redis, redis_key)
        try:
            if request_body_str is None:
            #if request_body_str is not None:
                user_key = f'okx:user:{user_id}'
                user_data = await redis.hgetall(user_key)
                initial_capital = user_data.get('initial_capital', '[]')
                if isinstance(initial_capital, str):
                    initial_capital = json.loads(initial_capital)
                request_body = {
                    "exchange_name": "okx",
                    "enter_strategy": user_data.get('direction', ''),
                    "enter_symbol_count": int(user_data.get('numbers_to_entry', 0)),
                    "enter_symbol_amount_list": initial_capital,
                    "grid_num": int(user_data.get('grid_num', 0)),
                    "leverage": int(user_data.get('leverage', 0)),
                    "stop_loss": float(user_data.get('stop_loss', 0)),
                    "custom_stop": int(user_data.get('custom_stop', 0)),
                    "telegram_id": int(user_data.get('telegram_id', 0)),
                    "user_id": int(user_id),
                    "api_key": user_data.get('api_key', ''),
                    "api_secret": user_data.get('api_secret', ''),
                    "password": user_data.get('password', '')
                }
                #print("request_body:", request_body)
                
                # Convert the dictionary to a JSON string
                request_body_json = json.dumps(request_body)
                
                # Save the JSON string to Redis
                await redis.set(f"okx:request_body:{user_id}:backup", request_body_json)
        except Exception as e:
            print(f"Error saving request body for user {user_id}: {str(e)}")
            traceback.print_exc()
    print(f"All running user({len(running_users)}) request bodies saved.")
    return ResponseDto[None](
        success=True,
        message=f"All running user({len(running_users)}) request bodies saved.",
        data=None
    )


async def restart_single_user(exchange_id: str, user_id: int, request_body_str: str) -> None:
    if request_body_str:
        try:
            request_dict = json.loads(request_body_str)
            dto = StartFeatureDto(**request_dict)
            print(f"Restarting bot for user {user_id}")
            # 가짜 Request 객체 생성
            fake_scope = {
                "type": "http",
                "client": ("127.0.0.1", 0),
                "method": "POST",
                "path": "/start_bot",
                "headers": []
            }
            # 가짜 Request 객체에 json 메서드 추가
            async def fake_json() -> dict[str, Any]:
                return dto.model_dump()
            fake_request = Request(scope=fake_scope)
            fake_request.json = fake_json  # type: ignore[method-assign]
            
            background_tasks = BackgroundTasks()
            await update_user_data(exchange_id, user_id)
            await start_bot(dto, fake_request, background_tasks, force_restart=True)
        except Exception as e:
            print(f"Error restarting bot for user {user_id}: {str(e)}")          
            
            
            
@router.post(
    "/force_restart",
    summary="실행 중인 봇 강제 재시작",
    description="""
# 실행 중인 봇 강제 재시작

서버 재시작, 업데이트 배포, 또는 오류 복구 시 사용하는 관리자 전용 엔드포인트입니다.

## 동작 프로세스

**5단계 재시작 절차:**
1. **사용자 조회**: Redis에서 실행 중인 모든 사용자 목록 조회 (모든 거래소)
2. **설정 복원**: 각 사용자의 저장된 요청 데이터 (`request_body`) 복원
3. **심볼 저장**: 현재 거래 중인 심볼 정보 백업
4. **봇 재시작**: `force_restart=True` 플래그로 각 봇 재시작
5. **상태 업데이트**: Redis에 새로운 상태 저장

## 사용 시나리오

**운영 시나리오:**
- ✅ **서버 다운 후 복구**: 예상치 못한 서버 다운 후 모든 봇 일괄 복원
- ✅ **업데이트 배포**: 코드 업데이트 후 모든 봇 재시작 필요 시
- ✅ **오류 복구**: 시스템 오류로 일부 봇이 멈춘 경우 일괄 복구
- ✅ **설정 변경 적용**: Redis 설정 변경 후 즉시 반영 필요 시
- ✅ **WebSocket 재연결**: WebSocket 연결 문제 발생 시

## ⚠️ 중요 경고

**관리자 전용 작업:**
- 🚨 **모든 사용자에게 영향**: 실행 중인 모든 봇이 재시작됩니다
- 🚨 **포지션 유지**: 기존 포지션은 그대로 유지되며 거래 계속됩니다
- 🚨 **일시적 중단**: 재시작 중 3-10초간 거래 중단됩니다
- 🚨 **관리자 권한 필요**: 프로덕션 환경에서는 인증 필수

**권장 사용 시간:**
- 한국 시간 기준 새벽 3-4시 (거래량 낮은 시간)
- 주요 거래 시간대(9-24시) 피하기
- 급격한 시장 변동 시 피하기

## 지원 거래소

모든 설정된 거래소의 봇을 일괄 재시작:
- `binance`, `binance_spot`
- `upbit`
- `bitget`, `bitget_spot`
- `okx`, `okx_spot`
- `bybit`, `bybit_spot`

## 재시작 간격

각 봇은 3초 간격으로 순차 재시작되어 거래소 API 부하 방지
""",
    responses={
        200: {
            "description": "✅ 재시작 성공",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "All running bots restarted successfully.",
                        "meta": {
                            "total_bots": 15,
                            "restarted_bots": 15,
                            "failed_bots": 0,
                            "elapsed_time_seconds": 45
                        },
                        "data": None
                    }
                }
            }
        },
        207: {
            "description": "⚠️ 부분 성공 - 일부 봇 재시작 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "partial_success": {
                            "summary": "일부 봇만 재시작 성공",
                            "value": {
                                "success": True,
                                "message": "All running bots restarted successfully.",
                                "meta": {
                                    "total_bots": 15,
                                    "restarted_bots": 12,
                                    "failed_bots": 3,
                                    "failed_users": [
                                        {"exchange": "okx", "user_id": 12345, "error": "API key expired"},
                                        {"exchange": "binance", "user_id": 67890, "error": "Insufficient balance"}
                                    ]
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": "❌ 요청 실패 - 설정 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "no_running_bots": {
                            "summary": "실행 중인 봇 없음",
                            "value": {
                                "success": False,
                                "message": "No running bots found",
                                "meta": {"hint": "Start bots before attempting restart"},
                                "data": None
                            }
                        },
                        "missing_request_body": {
                            "summary": "저장된 요청 데이터 없음",
                            "value": {
                                "success": False,
                                "message": "Cannot restart: request_body not found",
                                "meta": {
                                    "error": "Missing request_body in Redis",
                                    "user_id": 12345,
                                    "hint": "Bot may need to be started manually"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": "💥 서버 오류 - 재시작 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_error": {
                            "summary": "Redis 연결 실패",
                            "value": {
                                "success": False,
                                "message": "Failed to restart bots",
                                "meta": {
                                    "error": "Redis connection failed",
                                    "hint": "Check Redis server status"
                                },
                                "data": None
                            }
                        },
                        "process_spawn_error": {
                            "summary": "프로세스 생성 실패",
                            "value": {
                                "success": False,
                                "message": "Failed to restart bots",
                                "meta": {
                                    "error": "Failed to spawn worker processes",
                                    "hint": "Check system resources (CPU, memory)"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        503: {
            "description": "🔧 서비스 이용 불가",
            "content": {
                "application/json": {
                    "examples": {
                        "system_overload": {
                            "summary": "시스템 과부하",
                            "value": {
                                "success": False,
                                "message": "System is overloaded",
                                "meta": {
                                    "error": "Too many concurrent operations",
                                    "retry_after": 60,
                                    "hint": "Wait and retry"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        }
    }
)
async def restart_running_bots(request: Request) -> ResponseDto[None]:
    redis = await get_redis_connection()
    #current_port = get_request_port(request)  # Request 객체에서 포트 정보 가져오기
    print("Restarting running bots")
    for exchange_id in ['binance', 'upbit', 'bitget', 'binance_spot', 'bitget_spot', 'okx', 'okx_spot', 'bybit', 'bybit_spot']:
        running_users = await get_running_users(exchange_id)
        for user_id in running_users:
            redis_key = f"{exchange_id}:request_body:{user_id}"
            request_body_str = await get_request_body(redis, redis_key)
            print(f"Checking for request body in {redis_key}")
            if not request_body_str:
                all_keys = await redis.keys(f"{exchange_id}:request_body:{user_id}:*")
                if not all_keys:
                    # 포트 정보가 없는 경우
                    redis_key = f"{exchange_id}:request_body:{user_id}"
                    request_body_str = await get_request_body(redis, redis_key)
                #else:
                #    # 다른 포트에 데이터가 있는 경우, 해당 봇은 건너뜁니다.
                #    print(f"Bot for user {user_id} is running on a different port, skipping")
                #    continue
            if request_body_str:
                await asyncio.sleep(3)
                try:
                    request_dict = json.loads(request_body_str)
                    dto = StartFeatureDto(**request_dict)
                    print(f"Restarting bot for user {user_id}")
                    
                    # 가짜 Request 객체 생성
                    fake_scope = {
                        "type": "http",
                        "client": ("127.0.0.1", 0),
                        "method": "POST",
                        "path": "/start_bot",
                        "headers": []
                    }
                    fake_request = Request(scope=fake_scope)

                    # 가짜 Request 객체에 json 메서드 추가
                    async def fake_json() -> dict[str, Any]:
                        return dto.model_dump()
                    fake_request.json = fake_json  # type: ignore[method-assign]
                    
                    background_tasks = BackgroundTasks()
                    await save_running_symbols(exchange_id, user_id)
                    await update_user_data(exchange_id, user_id)
                    await start_bot(dto, fake_request, background_tasks, force_restart=True)
                    
                    # 필요한 경우 background_tasks를 실행
                    await background_tasks()
                    new_redis_key = f"{exchange_id}:request_body:{user_id}"
                    await redis.set(new_redis_key, request_body_str)
                    if redis_key != new_redis_key:
                        await redis.delete(redis_key)
                except Exception as e:
                    print(f"Error restarting bot for user {user_id}: {str(e)}")
    return ResponseDto[None](
        success=True,
        message="All running bots restarted successfully.",
        data=None
    )


@router.post(
    "/start",
    summary="그리드 트레이딩 봇 시작",
    description="""
# 그리드 트레이딩 봇 시작

그리드 트레이딩 전략으로 자동매매 봇을 시작합니다.

## 동작 원리

그리드 트레이딩은 가격 범위를 여러 레벨로 나누어 각 레벨에서 자동으로 매수/매도를 수행하는 전략입니다.

**5단계 실행 프로세스:**
1. **설정 검증**: 파라미터 유효성 검사 및 API 키 확인
2. **상태 저장**: Redis에 사용자 설정 및 초기 자본 저장
3. **프로세스 시작**: 그리드 트레이딩 워커 프로세스 생성
4. **봇 상태 업데이트**: 봇 상태를 'running'으로 전환
5. **모니터링 시작**: WebSocket 연결 및 실시간 모니터링 활성화

## 주요 파라미터

### 필수 파라미터
- **exchange_name** (string): 거래소 이름
  - 지원: `okx`, `binance`, `upbit`, `bitget`, `okx_spot`, `binance_spot`, `bitget_spot`, `bybit`, `bybit_spot`
- **enter_strategy** (string): 진입 전략
  - `long`: 롱 포지션만
  - `short`: 숏 포지션만
  - `long-short`: 양방향 포지션
- **enter_symbol_count** (integer): 동시 거래 심볼 개수 (1-20)
- **user_id** (integer): 사용자 고유 ID

### 선택 파라미터
- **grid_num** (integer): 그리드 레벨 개수 (기본값: 20, 범위: 1-40)
- **leverage** (integer): 레버리지 배수 (범위: 1-125, 선물 거래 시 사용)
- **stop_loss** (float): 손절매 비율 (%, 범위: 0.1-50.0)
- **custom_stop** (integer): 자동 중지 시간 (분)
- **enter_symbol_amount_list** (array): 각 그리드 레벨별 투자 금액 (USDT)
- **api_key**, **api_secret**, **password**: 거래소 API 인증 정보
- **telegram_id** (integer): 텔레그램 알림 수신 ID

## 그리드 설정 예시

**보수적 전략 (낮은 리스크):**
```json
{
  "grid_num": 30,
  "leverage": 5,
  "stop_loss": 3.0,
  "enter_symbol_amount_list": [10, 10, 10, ...]
}
```

**공격적 전략 (높은 리스크):**
```json
{
  "grid_num": 15,
  "leverage": 20,
  "stop_loss": 10.0,
  "enter_symbol_amount_list": [20, 25, 30, ...]
}
```

## ⚠️ 주의사항

- 봇 시작 전 API 키 권한 확인 필수 (거래, 읽기 권한 필요)
- 레버리지가 높을수록 청산 리스크 증가
- `enter_symbol_amount_list` 길이는 `grid_num`과 일치해야 함
- 봇이 이미 실행 중인 경우 시작 불가 (먼저 중지 필요)
- Redis 연결 필수 (봇 상태 관리용)
""",
    responses={
        200: {
            "description": "✅ 봇 시작 성공",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "okx long start feature success.",
                        "meta": {},
                        "data": {
                            "key": "okx_long_12345",
                            "exchange_name": "okx",
                            "enter_strategy": "long",
                            "user_id": "12345",
                            "is_running": True,
                            "error": None
                        }
                    }
                }
            }
        },
        400: {
            "description": "❌ 잘못된 요청 - 파라미터 오류 또는 봇 이미 실행 중",
            "content": {
                "application/json": {
                    "examples": {
                        "bot_already_running": {
                            "summary": "봇이 이미 실행 중",
                            "value": {
                                "success": False,
                                "message": "okx long already running.",
                                "meta": {},
                                "data": None
                            }
                        },
                        "missing_user_id": {
                            "summary": "user_id 누락",
                            "value": {
                                "success": False,
                                "message": "okx long start feature fail",
                                "meta": {"error": "user_id is required"},
                                "data": None
                            }
                        },
                        "invalid_grid_num": {
                            "summary": "grid_num 범위 초과 (1-40)",
                            "value": {
                                "success": False,
                                "message": "okx long start feature fail",
                                "meta": {"error": "grid_num must be between 1 and 40"},
                                "data": None
                            }
                        },
                        "invalid_leverage": {
                            "summary": "레버리지 범위 초과 (1-125)",
                            "value": {
                                "success": False,
                                "message": "okx long start feature fail",
                                "meta": {"error": "leverage must be between 1 and 125"},
                                "data": None
                            }
                        },
                        "amount_list_mismatch": {
                            "summary": "투자 금액 리스트 길이 불일치",
                            "value": {
                                "success": False,
                                "message": "okx long start feature fail",
                                "meta": {"error": "enter_symbol_amount_list length must match grid_num"},
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        401: {
            "description": "🔒 인증 실패 - API 키 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_api_credentials": {
                            "summary": "잘못된 API 인증 정보",
                            "value": {
                                "success": False,
                                "message": "okx long start feature fail",
                                "meta": {
                                    "error": "Authentication failed: Invalid API credentials",
                                    "exchange_error_code": "50113"
                                },
                                "data": None
                            }
                        },
                        "expired_api_key": {
                            "summary": "만료된 API 키",
                            "value": {
                                "success": False,
                                "message": "okx long start feature fail",
                                "meta": {
                                    "error": "API key expired or revoked",
                                    "hint": "Regenerate API key in exchange settings"
                                },
                                "data": None
                            }
                        },
                        "wrong_passphrase": {
                            "summary": "잘못된 API passphrase (OKX 전용)",
                            "value": {
                                "success": False,
                                "message": "okx long start feature fail",
                                "meta": {
                                    "error": "Invalid passphrase",
                                    "exchange_error_code": "50111"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        403: {
            "description": "🚫 권한 없음 - API 키 권한 부족",
            "content": {
                "application/json": {
                    "examples": {
                        "insufficient_permissions": {
                            "summary": "거래 권한 없음",
                            "value": {
                                "success": False,
                                "message": "okx long start feature fail",
                                "meta": {
                                    "error": "Insufficient API permissions",
                                    "required_permissions": ["trade", "read"],
                                    "hint": "Enable 'Trade' permission in API settings"
                                },
                                "data": None
                            }
                        },
                        "ip_restriction": {
                            "summary": "IP 화이트리스트 제한",
                            "value": {
                                "success": False,
                                "message": "okx long start feature fail",
                                "meta": {
                                    "error": "IP address not whitelisted",
                                    "hint": "Add server IP to API whitelist or disable IP restriction"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        422: {
            "description": "❌ 처리 불가 - 잔고 부족 또는 시장 조건 부적합",
            "content": {
                "application/json": {
                    "examples": {
                        "insufficient_balance": {
                            "summary": "잔고 부족",
                            "value": {
                                "success": False,
                                "message": "okx long start feature fail",
                                "meta": {
                                    "error": "Insufficient balance",
                                    "required_balance": 500.0,
                                    "available_balance": 250.0,
                                    "currency": "USDT"
                                },
                                "data": None
                            }
                        },
                        "symbol_not_tradable": {
                            "summary": "심볼 거래 불가",
                            "value": {
                                "success": False,
                                "message": "okx long start feature fail",
                                "meta": {
                                    "error": "Symbol BTC/USDT is not tradable",
                                    "reason": "Market suspended or delisted"
                                },
                                "data": None
                            }
                        },
                        "margin_mode_error": {
                            "summary": "마진 모드 설정 오류",
                            "value": {
                                "success": False,
                                "message": "okx long start feature fail",
                                "meta": {
                                    "error": "Failed to set margin mode",
                                    "hint": "Check leverage settings and account type"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": "💥 서버 오류 - 내부 처리 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_connection_error": {
                            "summary": "Redis 연결 실패",
                            "value": {
                                "success": False,
                                "message": "okx long start feature fail",
                                "meta": {
                                    "error": "Failed to connect to Redis",
                                    "hint": "Check Redis server status"
                                },
                                "data": None
                            }
                        },
                        "process_spawn_error": {
                            "summary": "워커 프로세스 생성 실패",
                            "value": {
                                "success": False,
                                "message": "okx long start feature fail",
                                "meta": {
                                    "error": "Failed to spawn worker process",
                                    "hint": "Check system resources (CPU, memory)"
                                },
                                "data": None
                            }
                        },
                        "state_update_error": {
                            "summary": "봇 상태 업데이트 실패",
                            "value": {
                                "success": False,
                                "message": "okx long start feature fail",
                                "meta": {
                                    "error": "Failed to update bot state in Redis",
                                    "hint": "Redis may be overloaded or out of memory"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        503: {
            "description": "🔧 서비스 이용 불가 - 거래소 또는 시스템 점검 중",
            "content": {
                "application/json": {
                    "examples": {
                        "exchange_maintenance": {
                            "summary": "거래소 점검 중",
                            "value": {
                                "success": False,
                                "message": "okx long start feature fail",
                                "meta": {
                                    "error": "Exchange is under maintenance",
                                    "retry_after": 3600,
                                    "hint": "Try again after maintenance period"
                                },
                                "data": None
                            }
                        },
                        "api_temporarily_unavailable": {
                            "summary": "거래소 API 일시적 오류",
                            "value": {
                                "success": False,
                                "message": "okx long start feature fail",
                                "meta": {
                                    "error": "Exchange API temporarily unavailable",
                                    "retry_after": 60,
                                    "exchange_status": "degraded"
                                },
                                "data": None
                            }
                        },
                        "max_bots_reached": {
                            "summary": "최대 봇 실행 개수 초과",
                            "value": {
                                "success": False,
                                "message": "okx long start feature fail",
                                "meta": {
                                    "error": "Maximum concurrent bots limit reached",
                                    "current_bots": 10,
                                    "max_allowed": 10,
                                    "hint": "Stop an existing bot before starting a new one"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        }
    }
)
async def start(dto: StartFeatureDto, request: Request, background_tasks: BackgroundTasks) -> ResponseDto[BotStateDto | None]:
    """
    그리드 트레이딩 봇을 시작하는 API 엔드포인트

    Args:
        dto: 봇 시작 설정 정보
        request: FastAPI Request 객체
        background_tasks: 백그라운드 태스크

    Returns:
        ResponseDto: 봇 상태 정보
    """
    return await start_bot(dto, request, background_tasks)


async def start_bot(dto: StartFeatureDto, request: Request, background_tasks: BackgroundTasks, force_restart: bool = False) -> ResponseDto[BotStateDto | None]:
    request_body = await request.json()
    exchange_name = dto.exchange_name
    #try:
    #    server_port = request.headers.get("X-Forwarded-Port")
    #    if server_port is None:
    #        server_port = request.url.port
    #    client_host = request.client.host
    #    print(f"Request received from {client_host} on port {server_port}")
    #except:
    #    print(traceback.format_exc())
    print("Request body:", request_body)  # 요청 본문을 출력합니다
    try:
        # Redis 연결 생성
        redis = await get_redis_connection()

        # user_id 확인 및 변환
        if dto.user_id is None:
            raise ValueError("user_id is required")
        user_id = int(dto.user_id) if isinstance(dto.user_id, str) else dto.user_id

        # 요청 본문을 Redis에 저장
        redis_key = f"{exchange_name}:request_body:{user_id}"
        await redis.set(redis_key, json.dumps(request_body), ex=1440000)
        print(f"Request body saved to Redis for {redis_key}")
        korea_tz = ZoneInfo("Asia/Seoul")
        current_time = datetime.now(korea_tz).isoformat()
        await redis.hset(f"{exchange_name}:user:{user_id}", 'last_started', current_time)
        enter_strategy = dto.enter_strategy
        enter_symbol_count = dto.enter_symbol_count
        enter_symbol_amount_list = dto.enter_symbol_amount_list
        grid_num = dto.grid_num
        leverage = dto.leverage
        stop_loss = dto.stop_loss
        api_keys = dto.api_key
        api_secret = dto.api_secret
        password = dto.password
        custom_stop = dto.custom_stop
        telegram_id = dto.telegram_id
        
        # enter_symbol_amount_list 처리 로직 (변경 없음)
        if enter_symbol_amount_list is None or len(enter_symbol_amount_list) == 0:
            enter_symbol_amount_list = [0.0 for i in range(grid_num)]
        elif len(enter_symbol_amount_list) < grid_num:
            diff = grid_num - len(enter_symbol_amount_list)
            last_value = max(enter_symbol_amount_list[-1], 0)
            if len(enter_symbol_amount_list) > 1:
                increment = enter_symbol_amount_list[-1] - enter_symbol_amount_list[-2]
            else:
                increment = 0
            
            for i in range(diff):
                last_value += increment
                enter_symbol_amount_list.append(max(last_value,0))
        elif len(enter_symbol_amount_list) > grid_num:
            enter_symbol_amount_list = enter_symbol_amount_list[:grid_num]
        
        initial_capital = enter_symbol_amount_list
        await redis_database.save_user(user_id, api_key= api_keys, api_secret= api_secret, password = password ,initial_capital=initial_capital, direction = enter_strategy, numbers_to_entry = enter_symbol_count,grid_num = grid_num,leverage=leverage, stop_loss=stop_loss, exchange_name=exchange_name)  # type: ignore[arg-type]

        print(f'{user_id} : [START FEATURE]')
        print(dto)

        current_bot_state = await bot_state_service.get_bot_state(dto=BotStateKeyDto(
            exchange_name=exchange_name,
            enter_strategy=enter_strategy,
            user_id=str(user_id)
        ))

        if current_bot_state is None:
            # 봇 상태가 없으면 새로 생성
            current_bot_state = BotStateDto(
                key=f"{exchange_name}_{enter_strategy}_{user_id}",
                exchange_name=exchange_name,
                enter_strategy=enter_strategy,
                user_id=str(user_id),
                is_running=False,
                error=None
            )

        if not force_restart and current_bot_state.is_running:
            return ResponseDto[BotStateDto | None](
                success=False,
                message=f"{exchange_name} {enter_strategy} already running.",
                data=None
            )   
        
        job_id = await start_grid_main_in_process(
            exchange_name, enter_strategy, enter_symbol_count, enter_symbol_amount_list,
            grid_num, leverage, stop_loss, user_id, custom_stop, telegram_id,force_restart
        )
        await redis.hset(f"{exchange_name}:user:{user_id}", 'is_stopped', '0')
        print('🍏🔹😇👆',job_id)

        updated_state: BotStateDto = await bot_state_service.set_bot_state(
            new_state=BotStateDto(
                key=current_bot_state.key,
                exchange_name=exchange_name,
                enter_strategy=enter_strategy,
                user_id=str(user_id),
                is_running=True,
                error=None
            )
        )

        return ResponseDto[BotStateDto | None](
            success=True,
            message=f"{exchange_name} {enter_strategy} start feature success.",
            data=updated_state
        )
    except Exception as e:
        print('[CATCH START EXCEPTION]', e)
        print(traceback.format_exc())
        bot_state_key_dto = BotStateKeyDto(
            exchange_name=dto.exchange_name,
            enter_strategy=dto.enter_strategy,
            user_id=str(dto.user_id) if dto.user_id is not None else "unknown"
        )
        current_bot_state = await bot_state_service.get_bot_state(dto=bot_state_key_dto)

        if current_bot_state and current_bot_state.is_running:
            updated_fail_state: BotStateDto = await bot_state_service.set_bot_state(
                new_state=BotStateDto(
                    key=current_bot_state.key,
                    exchange_name=current_bot_state.exchange_name,
                    enter_strategy=current_bot_state.enter_strategy,
                    user_id=current_bot_state.user_id,
                    is_running=False,
                    error=None
                )
            )
            print('[START EXCEPTION UPDATED BOT STATE]', updated_fail_state)
            await grid.cancel_tasks(user_id, exchange_name)
            await redis.hset(f"{exchange_name}:user:{user_id}", 'is_stopped', '1')
            await redis.hset(f"{exchange_name}:user:{user_id}", 'is_running', '0')
            print('[START EXCEPTION UPDATED BOT STATE]', updated_fail_state)

        return ResponseDto[BotStateDto | None](
            success=False,
            message=f"{dto.exchange_name} {dto.enter_strategy} start feature fail",
            meta={"error": str(e)},
            data=None,
        )
    finally:
        # Redis 연결 닫기
        await redis.close()

@router.post(
    "/cancel_all_limit_orders",
    summary="모든 지정가 주문 취소",
    description="""
# 모든 지정가 주문 취소

사용자의 모든 대기 중인 지정가 주문을 일괄 취소합니다.

## 동작 방식

**2가지 모드:**
1. **단일 사용자 모드**: `user_id`가 지정된 경우
   - 해당 사용자의 모든 지정가 주문만 취소
2. **전체 사용자 모드**: `user_id`가 `0000` 또는 `None`인 경우
   - 해당 거래소에서 실행 중인 모든 사용자의 주문 취소
   - 관리자 전용 기능

## 파라미터

- **exchange_name** (string, optional): 거래소 이름 (기본값: 'okx')
- **user_id** (integer, optional): 사용자 ID (기본값: 0000 - 전체 사용자)

## 주문 취소 범위

**취소되는 주문:**
- ✅ 대기 중인 지정가 주문 (limit orders)
- ✅ 부분 체결된 주문의 미체결 부분

**취소되지 않는 주문:**
- ❌ 이미 체결 완료된 주문
- ❌ 시장가 주문 (즉시 체결됨)
- ❌ 다른 거래소의 주문

## ⚠️ 주의사항

**Best-Effort 방식:**
- 취소 실패 시에도 `True` 반환 (best-effort)
- 일부 주문 취소 실패해도 계속 진행
- 실제 취소 여부는 거래소에서 확인 필요

**사용 시나리오:**
- 봇 중지 전 대기 주문 정리
- 전략 변경 시 기존 주문 제거
- 긴급 상황에서 모든 주문 취소
- 그리드 재설정 전 주문 정리

## 사용 예시

**특정 사용자 주문 취소:**
```python
POST /cancel_all_limit_orders?exchange_name=okx&user_id=12345
```

**모든 사용자 주문 취소 (관리자):**
```python
POST /cancel_all_limit_orders?exchange_name=okx&user_id=0000
```
""",
    responses={
        200: {
            "description": "✅ 주문 취소 시도 완료",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "취소 성공",
                            "value": True
                        },
                        "partial_success": {
                            "summary": "일부 취소 (best-effort)",
                            "value": True
                        }
                    }
                }
            }
        },
        400: {
            "description": "❌ 요청 오류",
            "content": {
                "application/json": {
                    "example": False
                }
            }
        },
        500: {
            "description": "💥 서버 오류",
            "content": {
                "application/json": {
                    "example": False
                }
            }
        }
    }
)
async def cancel_all_limit_orders(exchange_name='okx' ,user_id=0000) :
    if (user_id is None) or user_id == 0000:
        try:
            running_user = await get_running_users(exchange_name)
            for user_id in running_user:
                await grid.cancel_user_limit_orders(user_id, exchange_name)
        except Exception as e:
            print('[CANCEL ALL LIMIT ORDERS]', str(e))
            
    try:
        await grid.cancel_user_limit_orders(user_id, exchange_name)
        return True
    except Exception as e:
        return False
    

#@router.post("/cancel_specific_symbol_limit_orders")
#async def cancel_specific_symbol_limit_orders(exchange_name='okx', user_id=0000, symbol='BTC/USDT'):
#    if (user_id is None) or user_id == 0000:
#        try:
#            running_user = await get_running_users(exchange_name)
#            for user_id in running_user:
#                await grid.cancel_specific_symbol_limit_orders(user_id, exchange_name, symbol)
#        except Exception as e:
#            print('[CANCEL SPECIFIC SYMBOL LIMIT ORDERS]', str(e))
#            
#    try:
#        await grid.cancel_specific_symbol_limit_orders(user_id, exchange_name, symbol)
#        return True
#    except Exception as e:
#        return False
    
@router.post(
    "/recovery_mode",
    summary="복구 모드 활성화",
    description="""
# 복구 모드 활성화

서버 재시작, 점검, 또는 긴급 상황에서 데이터 손실을 방지하기 위한 복구 모드를 활성화합니다.

## 동작 원리

**3단계 복구 프로세스:**
1. **복구 플래그 설정**: Redis에 `recovery_state` 플래그를 `True`로 설정 (TTL 적용)
2. **심볼 정보 저장**: 모든 실행 중인 봇의 거래 심볼 정보를 Redis에 백업
3. **자동 복구 대기**: TTL 시간 내 서버 재시작 시 자동으로 봇 복원

## 파라미터

- **exchange_name** (string, optional): 거래소 이름 (기본값: 'okx')
  - 현재는 모든 거래소에 대해 일괄 적용됩니다
- **ttl** (integer, optional): 복구 모드 유지 시간 (초, 기본값: 600)
  - 범위: 60-3600 (1분-1시간)
  - 추천: 점검 시간 + 여유 시간 10분

## 사용 시나리오

**권장 사용 케이스:**
- 📋 **계획된 서버 점검**: 점검 시작 전 데이터 백업
- 🔄 **업데이트 배포**: 새 버전 배포 전 상태 저장
- ⚡ **긴급 재시작**: 예기치 않은 문제로 재시작 필요 시
- 🛠️ **인프라 작업**: Redis 또는 데이터베이스 유지보수 전

## 복구 플래그와 TTL

**TTL (Time-To-Live):**
- 설정된 시간(초) 후 자동으로 복구 모드 해제
- TTL 내 재시작 시 자동으로 모든 봇 복원
- TTL 초과 시 수동으로 `/force_restart` 호출 필요

**추천 TTL 값:**
- 빠른 재시작 (1-5분): TTL=300 (5분)
- 일반 점검 (10-20분): TTL=1200 (20분)
- 긴 점검 (30-60분): TTL=3600 (1시간)

## 워크플로우 예시

**점검 전 워크플로우:**
```
1. POST /recovery_mode?ttl=1200  # 20분 복구 모드 활성화
2. 서버 점검/재시작 수행
3. 서버 시작 시 자동으로 recovery_state 감지
4. 저장된 심볼 정보로 모든 봇 자동 복원
```
""",
    responses={
        200: {
            "description": "✅ 복구 모드 활성화 성공",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Recovery state activated for 600 seconds",
                        "meta": {
                            "ttl_seconds": 600,
                            "expires_at": "2025-01-12T15:40:00+09:00",
                            "backed_up_bots": 15
                        }
                    }
                }
            }
        },
        400: {
            "description": "❌ 활성화 실패 - 파라미터 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_ttl": {
                            "summary": "잘못된 TTL 값",
                            "value": {
                                "success": False,
                                "message": "Failed to activate recovery state: Invalid TTL value",
                                "meta": {
                                    "error": "TTL must be between 60 and 3600 seconds",
                                    "provided_ttl": 5000
                                }
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": "💥 서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_error": {
                            "summary": "Redis 연결 오류",
                            "value": {
                                "success": False,
                                "message": "Failed to activate recovery state: Redis 연결 오류",
                                "meta": {
                                    "error": "Cannot connect to Redis",
                                    "hint": "Check Redis server status"
                                }
                            }
                        }
                    }
                }
            }
        }
    }
)
async def recovery_mode(exchange_name='okx', ttl = 600):
    try:
        redis = await get_redis_connection()
        # 'recovery_mode' 키를 'true'로 설정하고 600초(10분) 후 만료되도록 설정
        await redis.set("recovery_state", 'True', ex=ttl)
        for exchange_id in ['binance', 'upbit', 'bitget', 'binance_spot', 'bitget_spot', 'okx', 'okx_spot', 'bybit', 'bybit_spot']:
            running_users = await get_running_users(exchange_id)
            for user_id in running_users:
                await save_running_symbols(exchange_id, user_id)
        return {"success": True, "message": "Recovery state activated for 600 seconds"}
    except Exception as e:
        return {"success": False, "message": f"Failed to activate recovery state: {str(e)}"}
    
# Stop 버튼 클릭시 호출
# Todo: Check required param
@router.post(
    "/stop",
    summary="그리드 트레이딩 봇 중지",
    description="""
# 그리드 트레이딩 봇 중지

실행 중인 그리드 트레이딩 봇을 안전하게 중지합니다.

## 동작 프로세스

**4단계 중지 절차:**
1. **프로세스 종료**: 그리드 트레이딩 워커 프로세스 graceful shutdown
2. **데이터 정리**: Redis의 사용자 임시 데이터 초기화
3. **상태 업데이트**: 봇 상태를 'stopped'로 변경
4. **시간 기록**: 마지막 중지 시간을 Redis에 저장 (Asia/Seoul 시간대)

## 필수 파라미터

- **exchange_name** (string): 거래소 이름
  - 지원: `okx`, `binance`, `upbit`, `bitget`, `okx_spot`, `binance_spot`, `bitget_spot`, `bybit`, `bybit_spot`
- **enter_strategy** (string): 진입 전략 (`long`, `short`, `long-short`)
- **user_id** (integer): 사용자 ID

## ⚠️ 중요 주의사항

**포지션 처리:**
- ⚠️ **봇 중지 시 보유 포지션은 유지됩니다**
- 포지션을 정리하려면 먼저 `/sell/all` 또는 `/sell` 엔드포인트 호출 필요
- 미청산 포지션은 시장 변동에 따라 손실 위험 존재

**주문 처리:**
- 대기 중인 지정가 주문은 자동으로 취소되지 않습니다
- 수동으로 취소하려면 `/cancel_all_limit_orders` 사용

**권장 중지 순서:**
1. `/sell/all` - 모든 포지션 청산
2. `/cancel_all_limit_orders` - 대기 주문 취소
3. `/stop` - 봇 중지
""",
    responses={
        200: {
            "description": "✅ 봇 중지 성공",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "12345의 okx 스탑 요청 성공",
                        "meta": {},
                        "data": None
                    }
                }
            }
        },
        400: {
            "description": "❌ 중지 실패 - 봇을 찾을 수 없거나 이미 종료됨",
            "content": {
                "application/json": {
                    "examples": {
                        "bot_not_found": {
                            "summary": "봇을 찾을 수 없음",
                            "value": {
                                "success": False,
                                "message": "12345의 okx 테스크를 찾을 수 없거나 이미 종료되었습니다.",
                                "meta": {},
                                "data": None
                            }
                        },
                        "already_stopped": {
                            "summary": "이미 중지된 봇",
                            "value": {
                                "success": False,
                                "message": "12345의 okx 테스크를 찾을 수 없거나 이미 종료되었습니다.",
                                "meta": {
                                    "hint": "Bot is already in stopped state",
                                    "last_stopped": "2025-01-12T15:30:00+09:00"
                                },
                                "data": None
                            }
                        },
                        "invalid_user_id": {
                            "summary": "잘못된 user_id",
                            "value": {
                                "success": False,
                                "message": "okx 스탑 요청 실패",
                                "meta": {"error": "Invalid user_id format"},
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": "🔍 봇 상태를 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "bot_state_not_found": {
                            "summary": "Redis에 봇 상태 없음",
                            "value": {
                                "success": False,
                                "message": "okx 스탑 요청 실패",
                                "meta": {
                                    "error": "Bot state not found in Redis",
                                    "hint": "Bot may have never been started or data expired"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        409: {
            "description": "⚠️ 충돌 - 봇이 다른 작업 중",
            "content": {
                "application/json": {
                    "examples": {
                        "bot_is_starting": {
                            "summary": "봇이 시작 중",
                            "value": {
                                "success": False,
                                "message": "okx 스탑 요청 실패",
                                "meta": {
                                    "error": "Bot is currently starting",
                                    "hint": "Wait for bot to fully start before stopping"
                                },
                                "data": None
                            }
                        },
                        "stop_in_progress": {
                            "summary": "이미 중지 작업 진행 중",
                            "value": {
                                "success": False,
                                "message": "okx 스탑 요청 실패",
                                "meta": {
                                    "error": "Stop operation already in progress",
                                    "hint": "Wait for current stop operation to complete"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": "💥 서버 오류 - 중지 프로세스 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "process_kill_error": {
                            "summary": "프로세스 종료 실패",
                            "value": {
                                "success": False,
                                "message": "okx 스탑 요청 실패",
                                "meta": {
                                    "error": "Failed to terminate worker process",
                                    "hint": "Process may be in zombie state, check system logs"
                                },
                                "data": None
                            }
                        },
                        "redis_update_error": {
                            "summary": "Redis 상태 업데이트 실패",
                            "value": {
                                "success": False,
                                "message": "okx 스탑 요청 실패",
                                "meta": {
                                    "error": "Failed to update bot state in Redis",
                                    "hint": "Bot stopped but state may not be persisted"
                                },
                                "data": None
                            }
                        },
                        "cleanup_error": {
                            "summary": "데이터 정리 실패",
                            "value": {
                                "success": False,
                                "message": "okx 스탑 요청 실패",
                                "meta": {
                                    "error": "Failed to cleanup user data",
                                    "hint": "Manual cleanup may be required"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        503: {
            "description": "🔧 서비스 이용 불가 - Redis 연결 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_unavailable": {
                            "summary": "Redis 서버 연결 불가",
                            "value": {
                                "success": False,
                                "message": "okx 스탑 요청 실패",
                                "meta": {
                                    "error": "Cannot connect to Redis server",
                                    "retry_after": 30,
                                    "hint": "Check Redis server status"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        }
    }
)
async def stop(dto: StopFeatureDto, request: Request) -> ResponseDto[BotStateDto | None]:
    redis = await get_redis_connection()
    try:
        exchange_name = dto.exchange_name
        korea_tz = ZoneInfo("Asia/Seoul")
        current_time = datetime.now(korea_tz).isoformat()
        user_id = int(dto.user_id)
        print(f'{user_id} : [STOP FEATURE]')
        print('[STOP]', dto)

        #await redis.hset(f"{exchange_name}:user:{user_id}", 'is_running', '0')
        #await redis.hset(f"{exchange_name}:user:{user_id}", 'is_stopped', '1')
        #await redis.hset(f"{exchange_name}:user:{user_id}", 'stop_task_only', '1')
        success = await stop_grid_main_process(exchange_name, user_id)
        await reset_user_data(user_id, exchange_name)
        
        print('[STOP]', dto)
        
        if success:
            print('[STOP]', dto)
            return ResponseDto[BotStateDto | None](
                success=True,
                message=f"{user_id}의 {exchange_name} 스탑 요청 성공",
                data=None
            )
        else:
            return ResponseDto[BotStateDto | None](
                success=False,
                message=f"{user_id}의 {exchange_name} 테스크를 찾을 수 없거나 이미 종료되었습니다.",
                data=None
            )
    except Exception as e:
        print('[CATCH STOP FEATURE ROUTE]', e)
        return ResponseDto[BotStateDto | None](
            success=False,
            message=f"{dto.exchange_name} 스탑 요청 실패",
            meta={'error': str(e)},
            data=None
        )
    finally : 
        await redis.hset(f"{exchange_name}:user:{user_id}", 'is_running', 0)
        await redis.hset(f"{exchange_name}:user:{user_id}", 'is_stopped', '1')
        await redis.hset(f"{exchange_name}:user:{user_id}", 'last_stopped', current_time)

@router.post("/stop_task_only")
async def stop_task_only(dto: StopFeatureDto, request: Request) -> ResponseDto[BotStateDto | None]:
    redis = await get_redis_connection()
    try:
        await redis.set("recovery_state", 'True', ex=20)
        

        exchange_name = dto.exchange_name
        korea_tz = ZoneInfo("Asia/Seoul")
        current_time = datetime.now(korea_tz).isoformat()
        user_id = int(dto.user_id)
        print(f'{user_id} : [STOP ONLY TASK FEATURE]')
        print('[STOP TASK ONLY]', dto)
        #await redis.hset(f"{exchange_name}:user:{user_id}", 'is_running', '0')
        #await redis.hset(f"{exchange_name}:user:{user_id}", 'is_stopped', '1')
        await redis.hset(f'{exchange_name}:user:{user_id}', 'stop_task_only', '1')
        
        success = await stop_grid_main_process(exchange_name, user_id)
     
        if success:
            print('[STOP]', dto)
            return ResponseDto[BotStateDto | None](
                success=True,
                message=f"{user_id}의 {exchange_name} 스탑 요청 성공",
                data=None
            )
        else:
            return ResponseDto[BotStateDto | None](
                success=False,
                message=f"{user_id}의 {exchange_name} 테스크를 찾을 수 없거나 이미 종료되었습니다.",
                data=None
            )
    except Exception as e:
        print('[CATCH STOP FEATURE ROUTE]', e)
        return ResponseDto[BotStateDto | None](
            success=False,
            message=f"{dto.exchange_name} 스탑 요청 실패",
            meta={'error': str(e)},
            data=None
        )
    finally : 
        await redis.hset(f"{exchange_name}:user:{user_id}", 'is_running', 0)
        await redis.hset(f"{exchange_name}:user:{user_id}", 'last_stopped', current_time)


# 전체 매도 버튼 클릭시 호출
@router.post(
    "/sell/all",
    summary="전체 코인 매도",
    description="""
# 전체 코인 매도

현재 보유 중인 모든 코인 포지션을 시장가로 즉시 매도합니다.

## 동작 방식

**3단계 매도 프로세스:**
1. **포지션 조회**: 거래소에서 사용자의 모든 활성 포지션 조회
2. **시장가 매도**: 각 포지션을 현재 시장 가격으로 즉시 매도
3. **상태 업데이트**: Redis의 `running_symbols`에서 매도 완료된 심볼 제거

## 필수 파라미터

- **exchange_name** (string): 거래소 이름
- **user_id** (integer): 사용자 ID

## ⚠️ 중요 경고

**되돌릴 수 없는 작업:**
- ❌ **이 작업은 취소하거나 되돌릴 수 없습니다**
- 실행 즉시 모든 포지션이 시장가로 청산됩니다
- 확인 없이 즉시 실행되므로 신중하게 사용하세요

**슬리피지 위험:**
- 시장가 주문이므로 예상 가격과 실제 체결 가격에 차이 발생 가능
- 유동성이 낮은 코인의 경우 큰 슬리피지 발생 가능
- 변동성이 높은 시장에서는 손실이 확대될 수 있음

**권장 사용 시점:**
- 긴급 청산이 필요한 경우
- 시장 상황이 급격히 악화되는 경우
- 봇을 완전히 중지하기 전
- 손절매가 자동으로 작동하지 않은 경우

## 대안

**부분 매도:**
- 전체 매도 대신 `/sell` 엔드포인트로 특정 코인만 선택 매도 가능
- `qty_percent` 파라미터로 비율 조절 가능 (예: 50% 매도)
""",
    responses={
        200: {
            "description": "✅ 전체 매도 성공",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "12345 , okx sell all coins success.",
                        "meta": {
                            "positions_closed": 5,
                            "total_pnl": 123.45,
                            "currency": "USDT"
                        },
                        "data": {}
                    }
                }
            }
        },
        400: {
            "description": "❌ 매도 실패 - 요청 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "no_positions": {
                            "summary": "보유 포지션 없음",
                            "value": {
                                "success": False,
                                "message": "12345 sell_all_coins fail",
                                "meta": {
                                    "error": "No positions to close",
                                    "hint": "User has no active positions"
                                },
                                "data": None
                            }
                        },
                        "invalid_user_id": {
                            "summary": "잘못된 사용자 ID",
                            "value": {
                                "success": False,
                                "message": "12345 sell_all_coins fail",
                                "meta": {"error": "Invalid user_id"},
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        401: {
            "description": "🔒 인증 실패 - API 키 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "api_key_error": {
                            "summary": "API 키 인증 실패",
                            "value": {
                                "success": False,
                                "message": "12345 sell_all_coins fail",
                                "meta": {
                                    "error": "Authentication failed",
                                    "hint": "Check API key validity"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        422: {
            "description": "❌ 처리 불가 - 거래 조건 불만족",
            "content": {
                "application/json": {
                    "examples": {
                        "partial_failure": {
                            "summary": "일부 포지션 매도 실패",
                            "value": {
                                "success": False,
                                "message": "12345 sell_all_coins fail",
                                "meta": {
                                    "error": "Failed to close some positions",
                                    "closed_positions": 3,
                                    "failed_positions": 2,
                                    "failed_symbols": ["ETH/USDT", "SOL/USDT"],
                                    "reason": "Insufficient liquidity or market suspended"
                                },
                                "data": None
                            }
                        },
                        "position_reduce_only": {
                            "summary": "포지션 모드 오류 (reduce-only 위반)",
                            "value": {
                                "success": False,
                                "message": "12345 sell_all_coins fail",
                                "meta": {
                                    "error": "Cannot close position: reduce-only mode active",
                                    "hint": "Check position mode settings"
                                },
                                "data": None
                            }
                        },
                        "minimum_order_size": {
                            "summary": "최소 주문 크기 미달",
                            "value": {
                                "success": False,
                                "message": "12345 sell_all_coins fail",
                                "meta": {
                                    "error": "Position size below minimum order size",
                                    "hint": "Some positions too small to close"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        429: {
            "description": "⏱️ 요청 한도 초과 - 속도 제한",
            "content": {
                "application/json": {
                    "examples": {
                        "rate_limit": {
                            "summary": "거래소 API 속도 제한",
                            "value": {
                                "success": False,
                                "message": "12345 sell_all_coins fail",
                                "meta": {
                                    "error": "Rate limit exceeded",
                                    "retry_after": 10,
                                    "hint": "Too many orders in short time"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": "💥 서버 오류 - 내부 처리 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "exchange_error": {
                            "summary": "거래소 오류",
                            "value": {
                                "success": False,
                                "message": "12345 sell_all_coins fail",
                                "meta": {
                                    "error": "Exchange internal error",
                                    "exchange_error_code": "50000",
                                    "hint": "Retry after a few seconds"
                                },
                                "data": None
                            }
                        },
                        "network_timeout": {
                            "summary": "네트워크 타임아웃",
                            "value": {
                                "success": False,
                                "message": "12345 sell_all_coins fail",
                                "meta": {
                                    "error": "Request timeout",
                                    "hint": "Check network connection and retry"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        503: {
            "description": "🔧 서비스 이용 불가 - 거래소 점검",
            "content": {
                "application/json": {
                    "examples": {
                        "exchange_maintenance": {
                            "summary": "거래소 점검 중",
                            "value": {
                                "success": False,
                                "message": "12345 sell_all_coins fail",
                                "meta": {
                                    "error": "Exchange under maintenance",
                                    "retry_after": 1800,
                                    "hint": "Try again after maintenance"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        }
    }
)
async def sell_all_coins(dto: CoinSellAllFeatureDto) -> ResponseDto[Any | None]:
    try:
        exchange_name = dto.exchange_name
        user_id = dto.user_id
        print(f'[{exchange_name} SELL ALL COINS]')
        await grid.sell_all_coins(exchange_name, user_id)

        ##################################
        # Todo: Impl '전체 매도 버튼' feature
        ##################################

        return ResponseDto[Any](
            success=True,
            message=f"{user_id} , {exchange_name} sell all coins success.",
            data={}
        )

    except Exception as e:
        return ResponseDto[None](
            success=False,
            message=f"{user_id} sell_all_coins fail",
            meta={'error': str(e)},
            data=None
        )


# 해당 코인 매도 버튼 클릭시 호출.
# Body - 선택한 코인들 DTO 배열.
@router.post(
    "/sell",
    summary="선택 코인 매도",
    description="""
# 선택 코인 매도

선택한 특정 코인들의 포지션을 전체 또는 부분 매도합니다.

## 매도 방식

**전체 매도 (100%):**
- `qty_percent` 파라미터를 `100` 또는 생략
- 해당 코인의 전체 포지션 청산
- Redis의 `running_symbols`에서 제거되고 `completed_trading_symbols`에 추가

**부분 매도 (1-99%):**
- `qty_percent`를 1-99 사이 값으로 설정
- 포지션의 일부만 매도하고 나머지는 유지
- `running_symbols`에 그대로 유지

## 동작 프로세스

**4단계 매도 절차:**
1. **심볼 검증**: 선택한 코인들이 실제로 거래 중인지 확인
2. **시장가 매도**: 각 코인을 지정된 비율만큼 시장가로 매도
3. **상태 업데이트**: Redis의 심볼 목록 업데이트 (전체 매도 시에만)
4. **응답 반환**: 매도 완료된 코인 리스트 반환

## 필수 파라미터

- **exchange_name** (string): 거래소 이름
- **user_id** (integer): 사용자 ID
- **coins** (array): 매도할 코인 리스트
  - **symbol** (string): 코인 심볼 (예: "BTC/USDT", "ETH/USDT")

## 선택 파라미터

- **qty_percent** (integer): 매도 비율 (1-100, 기본값: 100)
  - `100`: 전체 매도
  - `50`: 50% 부분 매도
  - `25`: 25% 부분 매도

## 사용 예시

**전체 매도 예시:**
```json
{
  "exchange_name": "okx",
  "user_id": 12345,
  "coins": [
    {"symbol": "BTC/USDT"},
    {"symbol": "ETH/USDT"}
  ]
}
```

**부분 매도 예시 (50%):**
```json
{
  "exchange_name": "okx",
  "user_id": 12345,
  "coins": [
    {"symbol": "BTC/USDT"}
  ],
  "qty_percent": 50
}
```

## 전체 매도와의 차이점

| 특징 | /sell | /sell/all |
|------|-------|-----------|
| 대상 | 선택한 코인만 | 모든 코인 |
| 제어 | 세밀한 제어 가능 | 일괄 청산 |
| 부분 매도 | 가능 | 불가능 |
| 위험도 | 낮음 | 높음 |
""",
    responses={
        200: {
            "description": "✅ 선택 코인 매도 성공",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "okx sell coins request success",
                        "meta": {
                            "qty_percent": 100,
                            "coins_processed": 2
                        },
                        "data": [
                            {"symbol": "BTC/USDT"},
                            {"symbol": "ETH/USDT"}
                        ]
                    }
                }
            }
        },
        400: {
            "description": "❌ 매도 실패 - 요청 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_symbol": {
                            "summary": "잘못된 심볼 형식",
                            "value": {
                                "success": False,
                                "message": "sell coins request fail",
                                "meta": {
                                    "error": "Invalid symbol format",
                                    "invalid_symbols": ["BTCUSDT", "ETH-USDT"],
                                    "expected_format": "BTC/USDT"
                                },
                                "data": None
                            }
                        },
                        "symbol_not_running": {
                            "summary": "거래 중이 아닌 심볼",
                            "value": {
                                "success": False,
                                "message": "sell coins request fail",
                                "meta": {
                                    "error": "Symbol not in running_symbols",
                                    "symbol": "SOL/USDT",
                                    "hint": "Symbol is not currently being traded by the bot"
                                },
                                "data": None
                            }
                        },
                        "invalid_qty_percent": {
                            "summary": "잘못된 qty_percent 값",
                            "value": {
                                "success": False,
                                "message": "sell coins request fail",
                                "meta": {
                                    "error": "qty_percent must be between 1 and 100",
                                    "provided_value": 150
                                },
                                "data": None
                            }
                        },
                        "empty_coins_list": {
                            "summary": "빈 코인 리스트",
                            "value": {
                                "success": False,
                                "message": "sell coins request fail",
                                "meta": {"error": "coins list cannot be empty"},
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        401: {
            "description": "🔒 인증 실패 - API 키 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "api_key_error": {
                            "summary": "API 키 인증 실패",
                            "value": {
                                "success": False,
                                "message": "sell coins request fail",
                                "meta": {
                                    "error": "Authentication failed",
                                    "hint": "Check API key validity"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": "🔍 포지션을 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "position_not_found": {
                            "summary": "포지션 없음",
                            "value": {
                                "success": False,
                                "message": "sell coins request fail",
                                "meta": {
                                    "error": "No position found for symbol",
                                    "symbol": "BTC/USDT",
                                    "hint": "Position may have been already closed"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        422: {
            "description": "❌ 처리 불가 - 거래 조건 불만족",
            "content": {
                "application/json": {
                    "examples": {
                        "position_too_small": {
                            "summary": "포지션 크기 너무 작음",
                            "value": {
                                "success": False,
                                "message": "sell coins request fail",
                                "meta": {
                                    "error": "Position size too small to sell",
                                    "symbol": "BTC/USDT",
                                    "current_size": 0.0005,
                                    "minimum_size": 0.001,
                                    "hint": "Close entire position instead of partial sell"
                                },
                                "data": None
                            }
                        },
                        "partial_sell_restricted": {
                            "summary": "부분 매도 제한됨",
                            "value": {
                                "success": False,
                                "message": "sell coins request fail",
                                "meta": {
                                    "error": "Partial sell not allowed for this position type",
                                    "hint": "Use 100% qty_percent for full close"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": "💥 서버 오류 - 내부 처리 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_error": {
                            "summary": "Redis 업데이트 실패",
                            "value": {
                                "success": False,
                                "message": "sell coins request fail",
                                "meta": {
                                    "error": "Failed to update running_symbols in Redis",
                                    "hint": "Sell may have succeeded but state not updated"
                                },
                                "data": None
                            }
                        },
                        "exchange_error": {
                            "summary": "거래소 오류",
                            "value": {
                                "success": False,
                                "message": "sell coins request fail",
                                "meta": {
                                    "error": "Exchange internal error",
                                    "exchange_error_code": "50000"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        503: {
            "description": "🔧 서비스 이용 불가",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_unavailable": {
                            "summary": "Redis 연결 불가",
                            "value": {
                                "success": False,
                                "message": "sell coins request fail",
                                "meta": {
                                    "error": "Cannot connect to Redis",
                                    "retry_after": 30
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        }
    }
)
async def sell_coins(dto: CoinSellFeatureDto, redis: aioredis.Redis = Depends(get_redis_connection)) -> ResponseDto[List[CoinDto] | None]:
    try:
        exchange_name = dto.exchange_name
        user_id = dto.user_id
        coins = dto.coins
        if dto.qty_percent is not None:
            qty_percent = dto.qty_percent
        else:
            qty_percent = None
        user_key = f'{exchange_name}:user:{user_id}'

        print(f'[{exchange_name} SELL COINS]', coins)

        for coin in coins:
            user_data = await redis.hgetall(user_key)
            #user_data = json.loads(await redis.hget(user_key, 'data') or '{}')
            running_symbols_json = await redis.hget(user_key, 'running_symbols')
            completed_symbols_json = await redis.hget(user_key, 'completed_trading_symbols')
            is_running = user_data.get('is_running', '0')
            print('is_running:', is_running)
            #running_symbols = set(user_data.get('running_symbols', []))
            running_symbols = set(json.loads(running_symbols_json)) if running_symbols_json else set()
            print('running_symbols:', running_symbols)
            await strategy.close(exchange=exchange_name, symbol=coin.symbol, qty_perc=qty_percent if qty_percent is not None else 100, user_id=str(user_id))

            # Redis에서 사용자 데이터 가져오기
            print('user_data:', user_data)
            # running_symbols 및 completed_trading_symbols 업데이트
            print('currnet running_symbols:', running_symbols)
            completed_trading_symbols = set(json.loads(completed_symbols_json)) if completed_symbols_json else set()

            if coin.symbol in running_symbols:
                #await redis.srem(f"{user_key}:running_symbols", coin.symbol) #<-- 단일로 읽어오는 방식 
                running_symbols.remove(coin.symbol)
                print('removed running_symbols:', running_symbols)
            if coin.symbol not in completed_trading_symbols:
                #await redis.sadd(f"{user_key}:completed_trading_symbols", coin.symbol)
                completed_trading_symbols.add(coin.symbol)

            # 업데이트된 데이터를 Redis에 저장
            #print('before updated running_symbols:', running_symbols)
            await redis.hset(user_key, 'running_symbols', json.dumps(list(running_symbols)))
            #print('updated running_symbols:', running_symbols)
            await redis.hset(user_key, 'completed_trading_symbols', json.dumps(list(completed_trading_symbols)))

        return ResponseDto[List[CoinDto] | None](
            success=True,
            message=f"{exchange_name} sell coins request success",
            data=coins
        )
    except Exception as e:
        return ResponseDto[List[CoinDto] | None](
            success=False,
            message="sell coins request fail",
            meta={'error': str(e)},
            data=None
        )
    finally:
        await redis.close()

