"""
Auth Routes - Migrated to New Infrastructure

Authentication-related API endpoints with input validation and exception handling.
"""

from fastapi import APIRouter, HTTPException

from GRID.services import auth_service
from GRID.services import user_service_pg as user_database
from shared.docs import error_example
from shared.dtos.auth import LoginDto, SignupDto
from shared.dtos.response import ResponseDto
from shared.dtos.user import UserWithoutPasswordDto
from shared.errors import DatabaseException, ValidationException
from shared.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

#@router.post("/login")
#async def login(dto: LoginDto) -> ResponseDto[UserWithoutPasswordDto | None]:
#    user = await auth_service.login(dto)
#
#    if user:
#        return ResponseDto[UserWithoutPasswordDto](
#            success=True,
#            message=f"[{dto.username}] 로그인에 성공했습니다.",
#            data=user
#        )
#    else:
#        return ResponseDto[None](
#            success=False,
#            message=f"입력한 [{dto.username}] 사용자 정보가 올바르지 않습니다. 아이디 또는 비밀번호를 확인해주세요.",
#            data=None
#        )


@router.post(
    "/signup",
    response_model=ResponseDto[dict],
    summary="사용자 회원가입 및 API 자격증명 등록",
    description="""
# 사용자 회원가입 및 API 자격증명 등록

새로운 사용자를 등록하고 거래소 API 자격증명을 안전하게 저장합니다. API 키는 AES-256 암호화되어 PostgreSQL에 저장됩니다.

## 요청 본문 (SignupDto)

- **user_id** (string, required): 사용자 고유 ID
  - 형식: 영숫자 조합 (예: "trader123", "user_12345")
  - 중복 불가 (고유값)
  - 3-50자 권장
- **exchange_name** (string, required): 거래소 이름
  - 지원 거래소: okx, binance, upbit, bitget, binance_spot, bitget_spot, okx_spot, bybit, bybit_spot
  - 대소문자 구분 없음
- **api_key** (string, required): 거래소 API 키
  - 거래소에서 발급받은 공개 키
  - 암호화되어 저장됨
- **secret_key** (string, required): 거래소 API 시크릿 키
  - 거래소에서 발급받은 비밀 키
  - 암호화되어 저장됨
- **passphrase** (string, optional): 거래소 패스프레이즈
  - OKX 등 일부 거래소에서 필수
  - 암호화되어 저장됨
- **password** (string, required): 계정 비밀번호
  - 최소 8자 이상
  - 대소문자, 숫자, 특수문자 조합 권장
  - bcrypt로 해시되어 저장됨

## 반환 정보

- **user_id** (string): 등록된 사용자 ID
- **exchange_name** (string): 등록된 거래소 이름
- **created_at** (datetime): 계정 생성 시간
- **username** (string, optional): 사용자 이름 (설정된 경우)

## 보안 메커니즘

### API 키 암호화
- **알고리즘**: AES-256-CBC
- **키 관리**: 환경변수로 관리되는 암호화 키
- **저장**: PostgreSQL 데이터베이스에 암호화된 상태로 저장

### 비밀번호 해싱
- **알고리즘**: bcrypt
- **Salt Rounds**: 12 (기본값)
- **저장**: 해시된 비밀번호만 저장, 원본은 저장하지 않음

## 사용 시나리오

- 👤 **신규 사용자 등록**: 최초 회원가입 시 API 자격증명 등록
- 🔐 **거래소 연동**: 자동 매매를 위한 거래소 API 연결 설정
- 🏢 **다중 거래소 지원**: 여러 거래소 계정 등록 및 관리
- 🔄 **API 키 변경**: 기존 사용자가 새로운 API 키로 재등록
- 📱 **모바일 앱**: 모바일 애플리케이션에서 사용자 계정 생성

## 워크플로우

```
사용자 입력 (user_id + API keys + password)
  → 유효성 검증 (비밀번호 길이, API 키 존재 여부)
  → 중복 확인 (user_id 고유성 체크)
  → API 키 암호화 (AES-256)
  → 비밀번호 해싱 (bcrypt)
  → PostgreSQL 저장
  → 성공 응답 반환
```

## 거래소별 API 키 발급 방법

### OKX
1. okx.com 로그인 → API Management
2. Create API Key → Trading 권한 선택
3. API Key, Secret Key, Passphrase 복사

### Binance
1. binance.com 로그인 → API Management
2. Create API → Enable Spot & Futures Trading
3. API Key, Secret Key 복사

### Upbit
1. upbit.com 로그인 → 내 정보 → Open API 관리
2. Open API Key 발급 → 거래/출금 권한 선택
3. Access Key, Secret Key 복사

## 예시 요청

```bash
curl -X POST "http://localhost:8012/auth/signup" \\
     -H "Content-Type: application/json" \\
     -d '{
           "user_id": "trader123",
           "exchange_name": "okx",
           "api_key": "abcd1234-efgh-5678-ijkl-9012mnop3456",
           "secret_key": "qrstuvwxyzABCDEFGHIJKLMNOPQRSTUVW",
           "passphrase": "MySecurePassphrase123",
           "password": "StrongPassword123!"
         }'
```
""",
    responses={
        200: {
            "description": "✅ 회원가입 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "okx_signup": {
                            "summary": "OKX 계정 등록",
                            "value": {
                                "success": True,
                                "message": "User [trader123] registered successfully",
                                "data": {
                                    "user_id": "trader123",
                                    "exchange_name": "okx",
                                    "username": "trader123",
                                    "created_at": "2025-01-12T16:00:00Z"
                                }
                            }
                        },
                        "binance_signup": {
                            "summary": "바이낸스 계정 등록",
                            "value": {
                                "success": True,
                                "message": "User [crypto_master] registered successfully",
                                "data": {
                                    "user_id": "crypto_master",
                                    "exchange_name": "binance",
                                    "username": "crypto_master",
                                    "created_at": "2025-01-12T16:05:00Z"
                                }
                            }
                        },
                        "upbit_signup": {
                            "summary": "업비트 계정 등록",
                            "value": {
                                "success": True,
                                "message": "User [upbit_trader] registered successfully",
                                "data": {
                                    "user_id": "upbit_trader",
                                    "exchange_name": "upbit",
                                    "username": "upbit_trader",
                                    "created_at": "2025-01-12T16:10:00Z"
                                }
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": "❌ 잘못된 요청 - 유효성 검증 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "password_too_short": {
                            "summary": "비밀번호가 너무 짧음",
                            "value": error_example(
                                message="Password must be at least 8 characters",
                                error_code="VALIDATION_ERROR",
                                path="/auth/signup",
                                method="POST",
                                details={"password_length": 5},
                            ),
                        },
                        "missing_api_keys": {
                            "summary": "API 키 누락",
                            "value": error_example(
                                message="API key and secret key are required",
                                error_code="VALIDATION_ERROR",
                                path="/auth/signup",
                                method="POST",
                                details={
                                    "has_api_key": False,
                                    "has_secret_key": True,
                                },
                            ),
                        },
                        "invalid_exchange": {
                            "summary": "지원하지 않는 거래소",
                            "value": error_example(
                                message="Invalid exchange name: unknown_exchange",
                                error_code="VALIDATION_ERROR",
                                path="/auth/signup",
                                method="POST",
                                details={"exchange_name": "unknown_exchange"},
                            ),
                        },
                        "empty_password": {
                            "summary": "비밀번호 없음",
                            "value": error_example(
                                message="Password must be at least 8 characters",
                                error_code="VALIDATION_ERROR",
                                path="/auth/signup",
                                method="POST",
                                details={"password_length": 0},
                            ),
                        },
                    }
                }
            }
        },
        409: {
            "description": "⚠️ 중복된 사용자 ID",
            "content": {
                "application/json": {
                    "examples": {
                        "duplicate_user_id": {
                            "summary": "이미 존재하는 사용자 ID",
                            "value": error_example(
                                message="User ID 'trader123' already exists",
                                error_code="DUPLICATE_RECORD",
                                path="/auth/signup",
                                method="POST",
                                details={"user_id": "trader123"},
                            ),
                        },
                        "duplicate_api_key": {
                            "summary": "이미 등록된 API 키",
                            "value": error_example(
                                message="API key is already registered to another account",
                                error_code="DUPLICATE_RECORD",
                                path="/auth/signup",
                                method="POST",
                            ),
                        }
                    }
                }
            }
        },
        422: {
            "description": "🚫 유효성 검증 실패 - 필수 필드 누락",
            "content": {
                "application/json": {
                    "examples": {
                        "missing_user_id": {
                            "summary": "사용자 ID 누락",
                            "value": error_example(
                                message="Field required: user_id",
                                error_code="VALIDATION_ERROR",
                                path="/auth/signup",
                                method="POST",
                            ),
                        },
                        "missing_exchange": {
                            "summary": "거래소 이름 누락",
                            "value": error_example(
                                message="Field required: exchange_name",
                                error_code="VALIDATION_ERROR",
                                path="/auth/signup",
                                method="POST",
                            ),
                        },
                        "invalid_format": {
                            "summary": "잘못된 데이터 형식",
                            "value": error_example(
                                message="Invalid JSON format in request body",
                                error_code="VALIDATION_ERROR",
                                path="/auth/signup",
                                method="POST",
                            ),
                        },
                    }
                }
            }
        },
        500: {
            "description": "💥 서버 오류 - 데이터베이스 또는 암호화 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "database_error": {
                            "summary": "데이터베이스 연결 실패",
                            "value": error_example(
                                message="Failed to register user: Database connection failed",
                                error_code="DATABASE_ERROR",
                                path="/auth/signup",
                                method="POST",
                                details={
                                    "user_id": "trader123",
                                    "exchange": "okx",
                                    "error": "Database connection failed",
                                },
                            ),
                        },
                        "encryption_error": {
                            "summary": "API 키 암호화 실패",
                            "value": error_example(
                                message="Failed to encrypt API credentials",
                                error_code="INTERNAL_ERROR",
                                path="/auth/signup",
                                method="POST",
                            ),
                        },
                        "hashing_error": {
                            "summary": "비밀번호 해싱 실패",
                            "value": error_example(
                                message="Failed to hash password",
                                error_code="INTERNAL_ERROR",
                                path="/auth/signup",
                                method="POST",
                            ),
                        },
                        "insert_error": {
                            "summary": "데이터 삽입 실패",
                            "value": error_example(
                                message="Failed to register user: Insert operation failed",
                                error_code="DATABASE_ERROR",
                                path="/auth/signup",
                                method="POST",
                                details={
                                    "user_id": "trader123",
                                    "exchange": "okx",
                                    "error": "Insert operation failed",
                                },
                            ),
                        }
                    }
                }
            }
        },
        503: {
            "description": "🔧 서비스 이용 불가 - PostgreSQL 다운타임",
            "content": {
                "application/json": {
                    "examples": {
                        "db_unavailable": {
                            "summary": "데이터베이스 서비스 중단",
                            "value": error_example(
                                message="Database service is temporarily unavailable",
                                error_code="SERVICE_UNAVAILABLE",
                                path="/auth/signup",
                                method="POST",
                            ),
                        }
                    }
                }
            }
        }
    }
)
async def signup(dto: SignupDto) -> ResponseDto[dict | None]:
    logger.info(
        "User signup attempt",
        extra={
            "user_id": dto.user_id,
            "exchange": dto.exchange_name
        }
    )

    # Validate password
    if not dto.password or len(dto.password) < 8:
        raise ValidationException(
            "Password must be at least 8 characters",
            details={"password_length": len(dto.password) if dto.password else 0}
        )

    # Validate API keys
    if not dto.api_key or not dto.secret_key:
        raise ValidationException(
            "API key and secret key are required",
            details={
                "has_api_key": bool(dto.api_key),
                "has_secret_key": bool(dto.secret_key)
            }
        )

    try:
        user = await user_database.insert_user(
            int(dto.user_id),
            dto.exchange_name,
            dto.api_key,
            dto.secret_key,
            dto.password
        )

        if user:
            logger.info(
                "User registered successfully",
                extra={
                    "user_id": dto.user_id,
                    "exchange": dto.exchange_name
                }
            )

            return ResponseDto[dict | None](
                success=True,
                message=f"User [{dto.user_id}] registered successfully",
                data=user
            )
        else:
            logger.error(
                "User registration failed",
                extra={
                    "user_id": dto.user_id,
                    "exchange": dto.exchange_name
                }
            )

            return ResponseDto[dict | None](
                success=False,
                message="Failed to register user",
                data=None
            )

    except Exception as e:
        error_msg = str(e)

        # Handle duplicate user ID
        if "UNIQUE constraint failed" in error_msg or "already exists" in error_msg.lower():
            logger.warning(
                "Duplicate user ID",
                extra={
                    "user_id": dto.user_id,
                    "exchange": dto.exchange_name
                }
            )
            raise ValidationException(
                f"User ID '{dto.user_id}' already exists",
                details={"user_id": dto.user_id}
            )

        # Handle other errors
        logger.error(
            "User registration failed with error",
            exc_info=True,
            extra={
                "user_id": dto.user_id,
                "exchange": dto.exchange_name
            }
        )

        raise DatabaseException(
            f"Failed to register user: {error_msg}",
            details={
                "user_id": dto.user_id,
                "exchange": dto.exchange_name,
                "error": error_msg
            }
        )
