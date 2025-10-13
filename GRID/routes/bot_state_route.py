from fastapi import APIRouter, Request

from GRID.services import bot_state_service
from shared.docs import error_example
from shared.dtos.bot_state import BotStateDto, BotStateKeyDto
from shared.dtos.response import ResponseDto

router = APIRouter(prefix="/state", tags=["state"])


## 전역 상태 사용 예시
#@router.get("/")
#async def get_bot_states(request: Request) -> ResponseDto[list[BotStateDto] | None]:
#    try:
#        bot_states: list[BotStateDto] = await bot_state_service.get_all_bot_state(request.app)
#
#        return ResponseDto[list[BotStateDto]](
#            success=True,
#            message="All bot state",
#            data=bot_states
#        )
#    except Exception as e:
#        return ResponseDto[None](
#            success=False,
#            message=f"Get bot states fail",
#            meta={"error": str(e)},
#            data=None
#        )


@router.get(
    "/{exchange_name}/{enter_strategy}/{user_id}",
    summary="봇 상태 조회",
    description="""
# 봇 상태 조회

특정 사용자의 그리드 트레이딩 봇 실행 상태를 실시간으로 조회합니다.

## URL 파라미터

- **exchange_name** (string): 거래소 이름
  - 지원: `okx`, `binance`, `upbit`, `bitget`, `okx_spot`, `binance_spot`, `bitget_spot`, `bybit`, `bybit_spot`
- **enter_strategy** (string): 진입 전략
  - `long`: 롱 포지션 전략
  - `short`: 숏 포지션 전략
  - `long-short`: 양방향 포지션 전략
- **user_id** (integer): 사용자 고유 ID

## 반환 정보

**BotStateDto 객체:**
- **key** (string): 봇 고유 식별자 (형식: `{exchange_name}_{enter_strategy}_{user_id}`)
- **exchange_name** (string): 거래소 이름
- **enter_strategy** (string): 진입 전략
- **user_id** (string): 사용자 ID
- **is_running** (boolean): 봇 실행 상태
  - `true`: 현재 실행 중
  - `false`: 중지됨
- **error** (object | null): 에러 정보 (에러 발생 시에만)
  - `code` (string): 에러 코드
  - `message` (string): 에러 메시지
  - `severity` (string): 심각도 (INFO, WARNING, ERROR, CRITICAL)
  - `timestamp` (string): 에러 발생 시간 (ISO 8601)
  - `details` (object): 추가 상세 정보

## 사용 시나리오

-  **대시보드 표시**: 봇 상태를 실시간으로 UI에 표시
-  **헬스 체크**: 주기적으로 봇 상태 모니터링
-  **에러 감지**: 봇 에러 발생 확인 및 알림
-  **자동화 워크플로우**: 봇 상태에 따른 자동 작업 트리거

## 예시 URL

```
GET /state/okx/long/12345
GET /state/binance/short/67890
GET /state/upbit/long-short/11111
```
""",
    responses={
        200: {
            "description": " 봇 상태 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "running": {
                            "summary": "실행 중인 봇 (정상)",
                            "value": {
                                "success": True,
                                "message": "All bot state",
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
                        },
                        "stopped": {
                            "summary": "중지된 봇",
                            "value": {
                                "success": True,
                                "message": "All bot state",
                                "meta": {},
                                "data": {
                                    "key": "okx_long_12345",
                                    "exchange_name": "okx",
                                    "enter_strategy": "long",
                                    "user_id": "12345",
                                    "is_running": False,
                                    "error": None
                                }
                            }
                        },
                        "error_state": {
                            "summary": "에러 상태의 봇",
                            "value": {
                                "success": True,
                                "message": "All bot state",
                                "meta": {},
                                "data": {
                                    "key": "okx_long_12345",
                                    "exchange_name": "okx",
                                    "enter_strategy": "long",
                                    "user_id": "12345",
                                    "is_running": False,
                                    "error": {
                                        "code": "EXCHANGE_API_ERROR",
                                        "message": "Failed to place order: Insufficient balance",
                                        "severity": "ERROR",
                                        "timestamp": "2025-01-12T15:30:00+09:00",
                                        "details": {
                                            "order_id": "123456",
                                            "symbol": "BTC/USDT",
                                            "required_balance": 100.0,
                                            "available_balance": 50.0
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": " 조회 실패 - 잘못된 요청",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_exchange": {
                            "summary": "잘못된 거래소 이름",
                            "value": error_example(
                                message="Get bot state fail.",
                                path="/state/{exchange_name}/{enter_strategy}/{user_id}",
                                method="GET",
                                status_code=400,
                                details={"exchange_name": "unknown_exchange"},
                                extra_meta={"error": "Invalid exchange_name: unknown_exchange"},
                            ),
                        },
                        "invalid_strategy": {
                            "summary": "잘못된 전략 이름",
                            "value": error_example(
                                message="Get bot state fail.",
                                path="/state/{exchange_name}/{enter_strategy}/{user_id}",
                                method="GET",
                                status_code=400,
                                details={"enter_strategy": "invalid_strategy"},
                                extra_meta={"error": "Invalid enter_strategy: invalid_strategy"},
                            ),
                        },
                        "invalid_user_id": {
                            "summary": "잘못된 user_id 형식",
                            "value": error_example(
                                message="Get bot state fail.",
                                path="/state/{exchange_name}/{enter_strategy}/{user_id}",
                                method="GET",
                                status_code=400,
                                details={"user_id": "abc"},
                                extra_meta={"error": "user_id must be a valid integer"},
                            ),
                        },
                    }
                }
            }
        },
        404: {
            "description": " 봇 상태를 찾을 수 없음",
            "content": {
                "application/json": {
                    "example": error_example(
                        message="Bot state not found",
                        path="/state/{exchange_name}/{enter_strategy}/{user_id}",
                        method="GET",
                        status_code=404,
                        extra_meta={"hint": "Bot may have never been started or data expired"},
                    )
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
                            "value": error_example(
                                message="Get bot state fail.",
                                path="/state/{exchange_name}/{enter_strategy}/{user_id}",
                                method="GET",
                                status_code=500,
                                extra_meta={
                                    "error": "Cannot connect to Redis",
                                    "hint": "Check Redis server status",
                                },
                            ),
                        },
                        "unexpected_error": {
                            "summary": "예기치 않은 오류",
                            "value": error_example(
                                message="Get bot state fail.",
                                path="/state/{exchange_name}/{enter_strategy}/{user_id}",
                                method="GET",
                                status_code=500,
                                extra_meta={
                                    "error": "Unexpected error occurred",
                                    "hint": "Check server logs for details",
                                },
                            ),
                        },
                    }
                }
            }
        },
        503: {
            "description": " 서비스 이용 불가",
            "content": {
                "application/json": {
                    "example": error_example(
                        message="Get bot state fail.",
                        path="/state/{exchange_name}/{enter_strategy}/{user_id}",
                        method="GET",
                        status_code=503,
                        extra_meta={
                            "error": "Redis service unavailable",
                            "retry_after": 30,
                        },
                    )
                }
            }
        }
    }
)
async def get_bot_state(exchange_name: str, enter_strategy: str, user_id:int, request: Request) \
        -> ResponseDto[BotStateDto | None]:
    try:
        bot_state: BotStateDto | None = await bot_state_service.get_bot_state(
            dto=BotStateKeyDto(
                exchange_name=exchange_name,
                enter_strategy=enter_strategy,
                user_id = str(user_id)
            )
        )
        
        return ResponseDto[BotStateDto | None](
            success=True,
            message="All bot state",
            data=bot_state
        )

    except Exception as e:
        print('[GET BOT STATE EXCEPTION]', e)
        return ResponseDto[BotStateDto | None](
            success=False,
            message="Get bot state fail.",
            meta={"error": str(e)},
            data=None
        )


@router.post(
    "/",
    summary="봇 상태 설정",
    description="""
# 봇 상태 설정

봇의 전체 상태를 업데이트하거나 새로운 봇 상태를 생성합니다.

## 요청 본문 (BotStateDto)

```json
{
  "key": "okx_long_12345",
  "exchange_name": "okx",
  "enter_strategy": "long",
  "user_id": "12345",
  "is_running": true,
  "error": null
}
```

### 필수 필드

- **key** (string): 봇 고유 식별자
  - 형식: `{exchange_name}_{enter_strategy}_{user_id}`
  - 예시: `okx_long_12345`, `binance_short_67890`
- **exchange_name** (string): 거래소 이름
- **enter_strategy** (string): 진입 전략 (`long`, `short`, `long-short`)
- **user_id** (string): 사용자 ID (문자열)
- **is_running** (boolean): 봇 실행 상태

### 선택 필드

- **error** (object | null): 에러 정보
  - `code` (string): 에러 코드
  - `message` (string): 에러 메시지
  - `severity` (string): 심각도 (INFO, WARNING, ERROR, CRITICAL)
  - `timestamp` (string): ISO 8601 형식
  - `details` (object): 추가 상세 정보

## 사용 시나리오

**일반 사용:**
-  **봇 시작 시**: `is_running=true`, `error=null`로 설정
-  **봇 중지 시**: `is_running=false`, `error=null`로 설정
-  **에러 발생 시**: `is_running=false`, `error=<에러 정보>`로 설정
-  **상태 복구**: 에러 해결 후 정상 상태로 복구

**내부 사용:**
- `/start` 엔드포인트에서 봇 시작 시 호출
- `/stop` 엔드포인트에서 봇 중지 시 호출
- 에러 핸들러에서 에러 상태 기록

##  주의사항

- 이 엔드포인트는 주로 **내부 서비스**에서 사용됩니다
- 직접 호출 시 봇의 실제 프로세스 상태와 불일치 가능
- 상태와 실제 프로세스를 동기화하려면 `/feature/start` 또는 `/feature/stop` 사용 권장
""",
    responses={
        200: {
            "description": " 상태 설정 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "start_bot": {
                            "summary": "봇 시작 상태로 설정",
                            "value": {
                                "success": True,
                                "message": "All bot state",
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
                        },
                        "stop_bot": {
                            "summary": "봇 중지 상태로 설정",
                            "value": {
                                "success": True,
                                "message": "All bot state",
                                "meta": {},
                                "data": {
                                    "key": "okx_long_12345",
                                    "exchange_name": "okx",
                                    "enter_strategy": "long",
                                    "user_id": "12345",
                                    "is_running": False,
                                    "error": None
                                }
                            }
                        },
                        "set_error": {
                            "summary": "에러 상태로 설정",
                            "value": {
                                "success": True,
                                "message": "All bot state",
                                "meta": {},
                                "data": {
                                    "key": "okx_long_12345",
                                    "exchange_name": "okx",
                                    "enter_strategy": "long",
                                    "user_id": "12345",
                                    "is_running": False,
                                    "error": {
                                        "code": "EXCHANGE_API_ERROR",
                                        "message": "Failed to place order: Insufficient balance",
                                        "severity": "ERROR",
                                        "timestamp": "2025-01-12T15:30:00+09:00",
                                        "details": {"symbol": "BTC/USDT"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": " 설정 실패 - 잘못된 요청",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_key_format": {
                            "summary": "잘못된 key 형식",
                            "value": error_example(
                                message="Set bot state fail.",
                                path="/state",
                                method="POST",
                                status_code=400,
                                details={"key": "invalid_format"},
                                extra_meta={
                                    "error": "Invalid key format",
                                    "expected_format": "{exchange_name}_{enter_strategy}_{user_id}",
                                },
                            ),
                        },
                        "missing_required_field": {
                            "summary": "필수 필드 누락",
                            "value": error_example(
                                message="Set bot state fail.",
                                path="/state",
                                method="POST",
                                status_code=400,
                                details={"missing_field": "is_running"},
                                extra_meta={
                                    "error": "Missing required field: is_running",
                                    "required_fields": [
                                        "key",
                                        "exchange_name",
                                        "enter_strategy",
                                        "user_id",
                                        "is_running",
                                    ],
                                },
                            ),
                        },
                        "invalid_error_structure": {
                            "summary": "잘못된 에러 객체 구조",
                            "value": error_example(
                                message="Set bot state fail.",
                                path="/state",
                                method="POST",
                                status_code=400,
                                details={"field": "error"},
                                extra_meta={
                                    "error": "Invalid error object structure",
                                    "required_fields": [
                                        "code",
                                        "message",
                                        "severity",
                                        "timestamp",
                                    ],
                                },
                            ),
                        },
                    }
                }
            }
        },
        422: {
            "description": " 처리 불가 - 검증 오류",
            "content": {
                "application/json": {
                    "example": error_example(
                        message="Set bot state fail.",
                        path="/state",
                        method="POST",
                        status_code=422,
                        details={
                            "validation_errors": [
                                {
                                    "field": "is_running",
                                    "error": "value is not a valid boolean",
                                }
                            ]
                        },
                        extra_meta={"error": "Validation error"},
                    )
                }
            }
        },
        500: {
            "description": " 서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_error": {
                            "summary": "Redis 쓰기 실패",
                            "value": error_example(
                                message="Set bot state fail.",
                                path="/state",
                                method="POST",
                                status_code=500,
                                extra_meta={
                                    "error": "Failed to write to Redis",
                                    "hint": "Check Redis server status and permissions",
                                },
                            ),
                        },
                        "serialization_error": {
                            "summary": "직렬화 오류",
                            "value": error_example(
                                message="Set bot state fail.",
                                path="/state",
                                method="POST",
                                status_code=500,
                                extra_meta={
                                    "error": "Failed to serialize bot state",
                                    "hint": "Check data format and encoding",
                                },
                            ),
                        },
                    }
                }
            }
        },
        503: {
            "description": " 서비스 이용 불가",
            "content": {
                "application/json": {
                    "example": error_example(
                        message="Set bot state fail.",
                        path="/state",
                        method="POST",
                        status_code=503,
                        extra_meta={
                            "error": "Redis service unavailable",
                            "retry_after": 30,
                        },
                    )
                }
            }
        }
    }
)
async def set_bot_state(bot_state: BotStateDto, request: Request) -> ResponseDto[BotStateDto | None]:
    try:
        new_state = await bot_state_service.set_bot_state(new_state=bot_state)
        return ResponseDto[BotStateDto | None](
            success=True,
            message="All bot state",
            data=new_state
        )

    except Exception as e:
        print('[SET BOT STATE EXCEPTION]')
        return ResponseDto[BotStateDto | None](
            success=False,
            message="Set bot state fail.",
            meta={"error": str(e)},
            data=None
        )


@router.patch(
    "/error",
    summary="봇 에러 상태 초기화",
    description="""
# 봇 에러 상태 초기화

봇의 에러 상태를 제거하고 정상 상태로 복구합니다.

## 요청 본문 (BotStateKeyDto)

```json
{
  "exchange_name": "okx",
  "enter_strategy": "long",
  "user_id": "12345"
}
```

### 필수 필드

- **exchange_name** (string): 거래소 이름
- **enter_strategy** (string): 진입 전략 (기본값: 'long')
- **user_id** (string): 사용자 ID

## 동작 방식

**3단계 초기화 프로세스:**
1. **현재 상태 조회**: Redis에서 봇의 현재 상태 가져오기
2. **에러 필드 제거**: `error` 필드를 `null`로 설정
3. **상태 저장**: 업데이트된 상태를 Redis에 저장

**주요 특징:**
-  `error` 필드만 `null`로 변경
-  `is_running`, `key` 등 다른 필드는 그대로 유지
-  봇의 실제 프로세스 상태는 변경하지 않음

## 사용 시나리오

**에러 복구 워크플로우:**
```
1. 에러 발생 → 봇 중지 및 에러 상태 기록
2. 문제 해결 (API 키 갱신, 잔고 충전 등)
3. PATCH /error → 에러 상태 초기화
4. POST /feature/start → 봇 재시작
```

**자동화 시나리오:**
-  **자동 복구**: 일시적 에러 해결 후 자동으로 에러 상태 제거
-  **모니터링**: 에러 해결 여부 추적
-  **알림**: 에러 초기화 시 텔레그램 알림 발송

##  주의사항

- 봇의 **실제 프로세스는 영향받지 않습니다**
- 에러의 **근본 원인이 해결되었는지 확인** 필요
- 에러 초기화 후에도 봇이 **자동으로 재시작되지 않습니다**
- 재시작하려면 `/feature/start` 엔드포인트 호출 필요
""",
    responses={
        200: {
            "description": " 에러 초기화 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "error_cleared": {
                            "summary": "에러 상태 제거됨",
                            "value": {
                                "success": True,
                                "message": "All bot state",
                                "meta": {"cleared_error": "EXCHANGE_API_ERROR"},
                                "data": {
                                    "key": "okx_long_12345",
                                    "exchange_name": "okx",
                                    "enter_strategy": "long",
                                    "user_id": "12345",
                                    "is_running": False,
                                    "error": None
                                }
                            }
                        },
                        "no_error": {
                            "summary": "이미 에러 없음 (정상 상태)",
                            "value": {
                                "success": True,
                                "message": "All bot state",
                                "meta": {"note": "No error to clear"},
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
                }
            }
        },
        400: {
            "description": " 요청 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "missing_field": {
                            "summary": "필수 필드 누락",
                            "value": error_example(
                                message="Set bot state fail.",
                                path="/state/error",
                                method="PATCH",
                                status_code=400,
                                details={"missing_fields": ["exchange_name", "enter_strategy", "user_id"]},
                                extra_meta={
                                    "error": "Missing required field",
                                    "required_fields": [
                                        "exchange_name",
                                        "enter_strategy",
                                        "user_id",
                                    ],
                                },
                            ),
                        },
                        "invalid_key": {
                            "summary": "잘못된 키 정보",
                            "value": error_example(
                                message="Set bot state fail.",
                                path="/state/error",
                                method="PATCH",
                                status_code=400,
                                details={"exchange_name": "invalid_exchange"},
                                extra_meta={
                                    "error": "Invalid exchange_name or enter_strategy",
                                    "provided": {"exchange_name": "invalid_exchange"},
                                },
                            ),
                        },
                    }
                }
            }
        },
        404: {
            "description": " 봇 상태를 찾을 수 없음",
            "content": {
                "application/json": {
                    "example": error_example(
                        message="Bot state not found",
                        path="/state/error",
                        method="PATCH",
                        status_code=404,
                        extra_meta={
                            "hint": "Bot may have never been started or data expired",
                            "key": "okx_long_12345",
                        },
                    )
                }
            }
        },
        500: {
            "description": " 서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_read_error": {
                            "summary": "Redis 읽기 실패",
                            "value": error_example(
                                message="Set bot state fail.",
                                path="/state/error",
                                method="PATCH",
                                status_code=500,
                                extra_meta={
                                    "error": "Failed to read current state from Redis",
                                    "hint": "Check Redis connection",
                                },
                            ),
                        },
                        "redis_write_error": {
                            "summary": "Redis 쓰기 실패",
                            "value": error_example(
                                message="Set bot state fail.",
                                path="/state/error",
                                method="PATCH",
                                status_code=500,
                                extra_meta={
                                    "error": "Failed to write updated state to Redis",
                                    "hint": "Error cleared in memory but not persisted",
                                },
                            ),
                        },
                    }
                }
            }
        },
        503: {
            "description": " 서비스 이용 불가",
            "content": {
                "application/json": {
                    "example": error_example(
                        message="Set bot state fail.",
                        path="/state/error",
                        method="PATCH",
                        status_code=503,
                        extra_meta={
                            "error": "Redis service unavailable",
                            "retry_after": 30,
                        },
                    )
                }
            }
        }
    }
)
async def clear_bot_state_error(dto: BotStateKeyDto) -> ResponseDto[BotStateDto | None]:
    print('[CLEAR BOT STATE ERROR API]', dto)
    try:
        current_state = await bot_state_service.get_bot_state(dto)
        if current_state is None:
            return ResponseDto[BotStateDto | None](
                success=False,
                message="Bot state not found",
                data=None
            )

        new_state = BotStateDto(
            key=current_state.key,
            exchange_name=current_state.exchange_name,
            enter_strategy=current_state.enter_strategy,
            user_id=current_state.user_id,
            is_running=current_state.is_running,
            error=None
        )
        updated = await bot_state_service.set_bot_state(new_state)

        return ResponseDto[BotStateDto | None](
            success=True,
            message="All bot state",
            data=updated
        )

    except Exception as e:
        print('[SET BOT STATE EXCEPTION]')
        return ResponseDto[BotStateDto | None](
            success=False,
            message="Set bot state fail.",
            meta={"error": str(e)},
            data=None
        )
