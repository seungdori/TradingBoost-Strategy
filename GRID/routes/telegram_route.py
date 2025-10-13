from fastapi import APIRouter

from GRID.services import telegram_service
from shared.dtos.response import ResponseDto
from shared.dtos.telegram import TelegramTokenDto

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.get(
    "/id",
    response_model=ResponseDto,
    summary="텔레그램 ID 조회",
    description="""
# 텔레그램 ID 조회

저장된 텔레그램 사용자 ID를 조회합니다.

## 반환 정보

- **data** (string): 텔레그램 사용자 ID
  - 형식: 숫자 문자열 (예: "123456789", "987654321")
  - 텔레그램 봇과 사용자 간 통신에 사용

## 사용 시나리오

-  **알림 설정 확인**: 알림을 받을 텔레그램 계정 확인
- 🔗 **텔레그램 연동 상태 확인**: 봇과 사용자 계정 연동 여부 확인
- ⚙️ **설정 초기화**: 데스크탑 앱 실행 시 텔레그램 ID 자동 로드
-  **디버깅**: 알림 미수신 시 ID 올바른지 확인

## 텔레그램 ID 확인 방법

1. 텔레그램 봇 `@userinfobot`에게 메시지 전송
2. 봇이 답장으로 사용자 ID 제공
3. 또는 `/start` 명령어로 봇과 대화 시작

## 예시 URL

```
GET /telegram/id
```
""",
    responses={
        200: {
            "description": " 텔레그램 ID 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "id_configured": {
                            "summary": "텔레그램 ID 설정됨",
                            "value": {
                                "success": True,
                                "message": "Telegram ID fetch success.",
                                "meta": {"configured": True},
                                "data": "123456789"
                            }
                        },
                        "id_not_configured": {
                            "summary": "텔레그램 ID 미설정",
                            "value": {
                                "success": True,
                                "message": "Telegram ID fetch success.",
                                "meta": {"configured": False, "note": "No telegram ID configured"},
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 텔레그램 ID 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "not_found": {
                            "summary": "텔레그램 ID가 설정되지 않음",
                            "value": {
                                "success": False,
                                "message": "Telegram ID not found",
                                "meta": {
                                    "error": "No telegram ID configured",
                                    "hint": "Use PATCH /telegram/id/{telegram_id} to set ID"
                                },
                                "data": None
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
                        "service_error": {
                            "summary": "텔레그램 서비스 오류",
                            "value": {
                                "success": False,
                                "message": "Failed to fetch telegram ID",
                                "meta": {
                                    "error": "Telegram service unavailable",
                                    "hint": "Retry after a moment"
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
async def get_telegram_id() -> ResponseDto[str]:
    telegram_id = telegram_service.get_telegram_id()
    return ResponseDto[str](
        success=True,
        message=f"Telegram ID fetch success.",
        data=telegram_id
    )


@router.get(
    "/token/{exchange_name}",
    response_model=ResponseDto,
    summary="텔레그램 토큰 조회",
    description="""
# 텔레그램 토큰 조회

특정 거래소의 텔레그램 봇 토큰을 조회합니다.

## URL 파라미터

- **exchange_name** (string, required): 거래소 이름
  - 지원: `okx`, `binance`, `upbit`, `bitget`, `okx_spot`, `binance_spot`, `bitget_spot`, `bybit`, `bybit_spot`

## 반환 정보 (TelegramTokenDto)

```json
{
  "exchange_name": "okx",
  "token": "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
}
```

- **exchange_name** (string): 거래소 이름
- **token** (string): 텔레그램 봇 토큰
  - 형식: "{bot_id}:{auth_token}"
  - @BotFather에서 발급

## 사용 시나리오

- 🤖 **봇 연동 확인**: 거래소별 봇 토큰 설정 상태 확인
-  **토큰 유효성 검증**: 저장된 토큰이 올바른지 확인
-  **디버깅**: 알림 미작동 시 토큰 설정 확인
- ⚙️ **설정 초기화**: 데스크탑 앱 실행 시 토큰 자동 로드
-  **다중 봇 관리**: 거래소별 다른 봇 사용 시

## 텔레그램 봇 토큰 발급 방법

1. 텔레그램에서 `@BotFather` 검색
2. `/newbot` 명령어로 새 봇 생성
3. 봇 이름과 사용자명 설정
4. BotFather가 제공하는 토큰 복사

## 예시 URL

```
GET /telegram/token/okx
GET /telegram/token/binance
GET /telegram/token/upbit
```
""",
    responses={
        200: {
            "description": " 텔레그램 토큰 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "token_configured": {
                            "summary": "토큰 설정됨",
                            "value": {
                                "success": True,
                                "message": "okx telegram token fetch success.",
                                "meta": {"configured": True},
                                "data": {
                                    "exchange_name": "okx",
                                    "token": "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
                                }
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": " 잘못된 요청",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_exchange": {
                            "summary": "지원하지 않는 거래소",
                            "value": {
                                "success": False,
                                "message": "invalid_exchange telegram token fetch failed",
                                "meta": {
                                    "error": "Exchange 'invalid_exchange' not supported",
                                    "hint": "Use okx, binance, upbit, bitget, etc."
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 토큰 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "token_not_found": {
                            "summary": "거래소 토큰이 설정되지 않음",
                            "value": {
                                "success": False,
                                "message": "okx telegram token not found",
                                "meta": {
                                    "error": "No token configured for okx",
                                    "hint": "Use PATCH /telegram/token to set token"
                                },
                                "data": None
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
                        "service_error": {
                            "summary": "텔레그램 서비스 오류",
                            "value": {
                                "success": False,
                                "message": "okx telegram token fetch failed",
                                "meta": {
                                    "error": "Telegram service unavailable",
                                    "hint": "Retry after a moment"
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
async def get_telegram_token(exchange_name: str) -> ResponseDto[TelegramTokenDto]:
    dto: TelegramTokenDto = TelegramTokenDto(
        exchange_name=exchange_name,
        token=telegram_service.get_telegram_token(exchange_name)
    )

    return ResponseDto[TelegramTokenDto](
        success=True,
        message=f"{exchange_name} telegram token fetch success.",
        data=dto
    )


@router.patch(
    '/id/{telegram_id}',
    response_model=ResponseDto,
    summary="텔레그램 ID 업데이트",
    description="""
# 텔레그램 ID 업데이트

텔레그램 사용자 ID를 업데이트합니다.

## URL 파라미터

- **telegram_id** (string, required): 새로운 텔레그램 사용자 ID
  - 형식: 숫자 문자열 (예: "123456789", "987654321")
  - @userinfobot에서 확인 가능

## 동작 방식

1. **ID 검증**: 입력된 ID 형식 확인
2. **저장소 업데이트**: Redis/데이터베이스에 새 ID 저장
3. **알림 설정 갱신**: 새 사용자에게 알림 전송되도록 설정
4. **업데이트 확인**: 저장된 ID 반환

## 반환 정보

- **data** (string): 업데이트된 텔레그램 사용자 ID

## 사용 시나리오

-  **최초 설정**: 데스크탑 앱 최초 실행 시 텔레그램 ID 등록
-  **계정 변경**: 텔레그램 계정 변경 시 ID 업데이트
- 👤 **알림 수신자 변경**: 다른 사용자에게 알림 전송
-  **문제 해결**: 알림 미수신 시 ID 재설정
-  **다중 디바이스**: 여러 디바이스에서 동일한 알림 수신

## 텔레그램 ID 확인 방법

1. 텔레그램에서 `@userinfobot` 검색
2. 봇에게 아무 메시지나 전송
3. 봇이 답장으로 사용자 ID 제공

## 예시 URL

```
PATCH /telegram/id/123456789
PATCH /telegram/id/987654321
```
""",
    responses={
        200: {
            "description": " 텔레그램 ID 업데이트 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "id_updated": {
                            "summary": "ID 업데이트 성공",
                            "value": {
                                "success": True,
                                "message": "Telegram ID update success.",
                                "meta": {
                                    "previous_id": "111111111",
                                    "new_id": "123456789",
                                    "updated_at": "2025-01-12T10:30:00Z"
                                },
                                "data": "123456789"
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": " 잘못된 요청",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_id_format": {
                            "summary": "잘못된 ID 형식",
                            "value": {
                                "success": False,
                                "message": "Telegram ID update failed",
                                "meta": {
                                    "error": "Invalid telegram ID format",
                                    "hint": "ID must be numeric string"
                                },
                                "data": None
                            }
                        },
                        "empty_id": {
                            "summary": "빈 ID",
                            "value": {
                                "success": False,
                                "message": "Telegram ID update failed",
                                "meta": {
                                    "error": "Telegram ID cannot be empty",
                                    "hint": "Provide valid telegram ID"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        422: {
            "description": "🚫 유효성 검증 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "validation_error": {
                            "summary": "ID 유효성 검증 실패",
                            "value": {
                                "success": False,
                                "message": "Telegram ID validation failed",
                                "meta": {
                                    "error": "Telegram ID must be positive integer",
                                    "hint": "Get ID from @userinfobot"
                                },
                                "data": None
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
                        "save_error": {
                            "summary": "저장 실패",
                            "value": {
                                "success": False,
                                "message": "Telegram ID update failed",
                                "meta": {
                                    "error": "Failed to save telegram ID",
                                    "hint": "Retry after a moment"
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
async def update_telegram_id(telegram_id: str) -> ResponseDto[str]:
    telegram_service.set_telegram_id(telegram_id)

    updated_id = telegram_service.get_telegram_id()

    return ResponseDto[str](
        success=True,
        message=f"Telegram ID update success.",
        data=updated_id
    )


@router.patch(
    '/token',
    response_model=ResponseDto,
    summary="텔레그램 토큰 업데이트",
    description="""
# 텔레그램 토큰 업데이트

특정 거래소의 텔레그램 봇 토큰을 업데이트합니다.

## 요청 본문 (TelegramTokenDto)

```json
{
  "exchange_name": "okx",
  "token": "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
}
```

### 필드 설명

- **exchange_name** (string, required): 거래소 이름
  - 지원: `okx`, `binance`, `upbit`, `bitget`, `okx_spot`, `binance_spot`, `bitget_spot`
- **token** (string, required): 텔레그램 봇 토큰
  - 형식: "{bot_id}:{auth_token}"
  - @BotFather에서 발급

## 동작 방식

1. **토큰 형식 검증**: {bot_id}:{auth_token} 형식 확인
2. **거래소별 저장**: 각 거래소에 대해 독립적으로 토큰 저장
3. **봇 연결 갱신**: 새 토큰으로 텔레그램 봇 API 연결
4. **업데이트 확인**: 저장된 토큰 반환

## 반환 정보

- **data** (TelegramTokenDto): 업데이트된 토큰 정보
  - exchange_name: 거래소 이름
  - token: 저장된 봇 토큰

## 사용 시나리오

-  **최초 설정**: 데스크탑 앱 최초 실행 시 봇 토큰 등록
-  **봇 변경**: 새로운 봇 사용 시 토큰 업데이트
-  **거래소별 알림 설정**: 각 거래소마다 다른 봇 사용
-  **문제 해결**: 알림 미작동 시 토큰 재설정
- 🔐 **보안 강화**: 주기적인 토큰 갱신

## 텔레그램 봇 토큰 발급 방법

1. 텔레그램에서 `@BotFather` 검색
2. `/newbot` 명령어로 새 봇 생성
3. 봇 이름과 사용자명 설정
4. BotFather가 제공하는 토큰 복사
5. 이 엔드포인트로 토큰 저장

## 주의사항

- 토큰은 **절대 공개하지 마세요** (GitHub 등)
- 거래소별로 **다른 봇**을 사용할 수 있습니다
- 토큰 형식이 올바른지 확인하세요

## 예시 요청

```json
// OKX 거래소 봇 토큰 설정
{
  "exchange_name": "okx",
  "token": "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
}

// Binance 거래소 봇 토큰 설정
{
  "exchange_name": "binance",
  "token": "987654321:ZYXwvuTSRqponMLKjih"
}
```
""",
    responses={
        200: {
            "description": " 텔레그램 토큰 업데이트 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "token_updated": {
                            "summary": "토큰 업데이트 성공",
                            "value": {
                                "success": True,
                                "message": "okx telegram token update success",
                                "meta": {
                                    "exchange": "okx",
                                    "token_length": 46,
                                    "updated_at": "2025-01-12T10:30:00Z"
                                },
                                "data": {
                                    "exchange_name": "okx",
                                    "token": "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
                                }
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": " 잘못된 요청",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_token_format": {
                            "summary": "잘못된 토큰 형식",
                            "value": {
                                "success": False,
                                "message": "okx telegram token update fail",
                                "meta": {
                                    "error": "Invalid token format",
                                    "hint": "Token must be in format: bot_id:auth_token"
                                },
                                "data": None
                            }
                        },
                        "invalid_exchange": {
                            "summary": "지원하지 않는 거래소",
                            "value": {
                                "success": False,
                                "message": "invalid_exchange telegram token update fail",
                                "meta": {
                                    "error": "Exchange 'invalid_exchange' not supported",
                                    "hint": "Use okx, binance, upbit, bitget, etc."
                                },
                                "data": None
                            }
                        },
                        "empty_token": {
                            "summary": "빈 토큰",
                            "value": {
                                "success": False,
                                "message": "okx telegram token update fail",
                                "meta": {
                                    "error": "Token cannot be empty",
                                    "hint": "Provide valid bot token from @BotFather"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        422: {
            "description": "🚫 유효성 검증 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "validation_error": {
                            "summary": "토큰 유효성 검증 실패",
                            "value": {
                                "success": False,
                                "message": "okx telegram token update fail",
                                "meta": {
                                    "error": "Token validation failed",
                                    "hint": "Check token format from @BotFather"
                                },
                                "data": None
                            }
                        },
                        "missing_fields": {
                            "summary": "필수 필드 누락",
                            "value": {
                                "success": False,
                                "message": "Telegram token update fail",
                                "meta": {
                                    "error": "Missing required fields: exchange_name, token",
                                    "hint": "Provide both exchange_name and token"
                                },
                                "data": None
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
                        "save_error": {
                            "summary": "저장 실패",
                            "value": {
                                "success": False,
                                "message": "okx telegram token update fail",
                                "meta": {
                                    "error": "Failed to save telegram token",
                                    "hint": "Retry after a moment"
                                },
                                "data": None
                            }
                        },
                        "telegram_api_error": {
                            "summary": "텔레그램 API 연결 실패",
                            "value": {
                                "success": False,
                                "message": "okx telegram token update fail",
                                "meta": {
                                    "error": "Failed to connect to Telegram API",
                                    "hint": "Check if token is valid"
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
async def update_telegram_token(dto: TelegramTokenDto) -> ResponseDto[TelegramTokenDto | None]:
    print('[UPDATE TELEGRAM TOKEN]', dto)

    try:
        telegram_service.set_telegram_token(dto)  # type: ignore[arg-type]
        updated_token = telegram_service.get_telegram_token(dto.exchange_name)
        updated_token_dto: TelegramTokenDto = TelegramTokenDto(
            exchange_name=dto.exchange_name,
            token=updated_token
        )

        return ResponseDto[TelegramTokenDto | None](
            success=True,
            message=f"{dto.exchange_name} telegram token update success",
            data=updated_token_dto
        )
    except Exception as e:
        print('[TELEGRAM TOKEN UPDATE EXCEPTION]', e)
        return ResponseDto[TelegramTokenDto | None](
            success=False,
            message=f"{dto.exchange_name} telegram token update fail",
            meta={'error': str(e)},
            data=None
        )
