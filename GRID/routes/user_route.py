"""
User Routes - Migrated to New Infrastructure

User-related API endpoints with input validation and exception handling.
"""

from typing import Optional, Union

from fastapi import APIRouter, Path, Query

from GRID.services import user_service
from shared.docs import error_example
from shared.dtos.response import ResponseDto
from shared.dtos.user import UserExistDto, UserWithoutPasswordDto
from shared.errors import DatabaseException, ValidationException
from shared.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/user", tags=["user"])


@router.get(
    "/exist",
    response_model=ResponseDto[UserExistDto],
    summary="거래소별 사용자 존재 여부 확인",
    description="""
# 거래소별 사용자 존재 여부 확인

특정 거래소에 등록된 사용자가 있는지 확인하고, 존재하는 경우 사용자 ID 목록을 반환합니다.

## 쿼리 파라미터

- **exchange_name** (string, required): 거래소 이름
  - 지원 거래소: okx, binance, upbit, bitget, binance_spot, bitget_spot, okx_spot, bybit, bybit_spot
  - 대소문자 구분 없음

## 반환 정보

- **user_exist** (boolean): 사용자 존재 여부
  - `true`: 최소 1명 이상의 사용자가 거래소에 등록됨
  - `false`: 등록된 사용자가 없음
- **user_ids** (array of string): 등록된 사용자 ID 목록
  - 존재하지 않는 경우 빈 배열 또는 null 반환

## 사용 시나리오

- 🏢 **관리자 대시보드**: 거래소별 사용자 현황 파악
- 🔍 **마이그레이션 확인**: 거래소 데이터 마이그레이션 후 사용자 존재 검증
- 📊 **통계 수집**: 거래소별 활성 사용자 수 집계
- 🚀 **배포 검증**: 새 거래소 추가 후 사용자 등록 상태 확인
- 🔧 **디버깅**: 거래소 연동 문제 발생 시 사용자 데이터 존재 여부 확인

## 워크플로우

```
사용자 → API 요청 (exchange_name) → Redis 조회 → 사용자 ID 목록 반환 → 통계/검증
```

## 예시 URL

```
GET /user/exist?exchange_name=okx
GET /user/exist?exchange_name=binance
GET /user/exist?exchange_name=upbit
```
""",
    responses={
        200: {
            "description": "✅ 사용자 존재 여부 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "users_exist": {
                            "summary": "사용자 존재함",
                            "value": {
                                "success": True,
                                "message": "User exists",
                                "data": {
                                    "user_exist": True,
                                    "user_ids": ["user_12345", "user_67890", "user_11111"]
                                }
                            }
                        },
                        "no_users": {
                            "summary": "사용자 없음",
                            "value": {
                                "success": True,
                                "message": "User does not exist",
                                "data": {
                                    "user_exist": False,
                                    "user_ids": []
                                }
                            }
                        },
                        "single_user": {
                            "summary": "단일 사용자",
                            "value": {
                                "success": True,
                                "message": "User exists",
                                "data": {
                                    "user_exist": True,
                                    "user_ids": ["user_12345"]
                                }
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": "❌ 잘못된 요청 - 유효하지 않은 거래소 이름",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_exchange": {
                            "summary": "지원하지 않는 거래소",
                            "value": error_example(
                                message="Invalid exchange name: unknown_exchange",
                                error_code="VALIDATION_ERROR",
                                path="/user/exist",
                                method="GET",
                                details={"exchange_name": "unknown_exchange"},
                            ),
                        },
                        "empty_exchange": {
                            "summary": "빈 거래소 이름",
                            "value": error_example(
                                message="Exchange name cannot be empty",
                                error_code="VALIDATION_ERROR",
                                path="/user/exist",
                                method="GET",
                            ),
                        }
                    }
                }
            }
        },
        422: {
            "description": "🚫 유효성 검증 실패 - 필수 파라미터 누락",
            "content": {
                "application/json": {
                    "examples": {
                        "missing_exchange": {
                            "summary": "거래소 이름 누락",
                            "value": error_example(
                                message="Field required: exchange_name",
                                error_code="VALIDATION_ERROR",
                                path="/user/exist",
                                method="GET",
                            ),
                        }
                    }
                }
            }
        },
        500: {
            "description": "💥 서버 오류 - Redis 연결 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_error": {
                            "summary": "Redis 연결 오류",
                            "value": error_example(
                                message="Database connection failed",
                                error_code="REDIS_ERROR",
                                path="/user/exist",
                                method="GET",
                            ),
                        },
                        "query_error": {
                            "summary": "데이터 조회 실패",
                            "value": error_example(
                                message="Failed to query user data",
                                error_code="DATABASE_ERROR",
                                path="/user/exist",
                                method="GET",
                            ),
                        }
                    }
                }
            }
        }
    }
)
async def check_user_exist_route(
    exchange_name: str = Query(..., description="Exchange name (okx, binance, etc.)")
) -> ResponseDto[UserExistDto]:
    logger.info(
        "Checking user existence",
        extra={"exchange": exchange_name}
    )

    try:
        user_exist_dto = await user_service.check_user_exist(exchange_name)

        logger.info(
            "User existence checked",
            extra={
                "exchange": exchange_name,
                "user_exist": user_exist_dto.user_exist,
                "user_count": len(user_exist_dto.user_ids or [])
            }
        )

        return ResponseDto[UserExistDto](
            success=True,
            message="User exists" if user_exist_dto.user_exist else "User does not exist",
            data=user_exist_dto
        )

    except Exception as e:
        logger.error(
            "Failed to check user existence",
            exc_info=True,
            extra={"exchange": exchange_name}
        )
        # Exception automatically handled by exception handlers
        raise



# Query param.
# e.g. URL/user/?username=sample
#@router.get("/")
#async def get_user_by_username_route(exchange_name: str, username: str) -> ResponseDto[Union[UserWithoutPasswordDto, None]]:
#    print('[USERNAME]', username)
#    user = await user_service.find_user_by_username(exchange_name, username)
#
#    if user:
#        return ResponseDto[UserWithoutPasswordDto](
#            success=True,
#            message=f"User [{username}] found",
#            data=UserWithoutPasswordDto.from_user_dto(user_dto=user)
#        )
#    else:
#        return ResponseDto[None](
#            success=False,
#            message=f"User [{username}] not found",
#            data=None
#        )


@router.get(
    "/{user_id}",
    response_model=ResponseDto[Optional[UserWithoutPasswordDto]],
    summary="사용자 ID로 사용자 정보 조회",
    description="""
# 사용자 ID로 사용자 정보 조회

특정 사용자 ID와 거래소를 기반으로 사용자 정보를 조회합니다. 보안을 위해 비밀번호는 제외된 정보를 반환합니다.

## URL 파라미터

- **user_id** (string, required): 사용자 고유 ID
  - 형식: 영숫자 조합 (예: "user_12345", "abc123xyz")
  - 대소문자 구분

## 쿼리 파라미터

- **exchange_name** (string, required): 거래소 이름
  - 지원 거래소: okx, binance, upbit, bitget, binance_spot, bitget_spot, okx_spot, bybit, bybit_spot
  - 대소문자 구분 없음

## 반환 정보 (UserWithoutPasswordDto)

- **user_id** (string): 사용자 고유 ID
- **username** (string): 사용자 이름
- **exchange_name** (string): 등록된 거래소 이름
- **api_key** (string): 거래소 API 키 (암호화됨)
- **api_secret** (string): 거래소 API 시크릿 (암호화됨)
- **passphrase** (string, optional): OKX용 패스프레이즈 (암호화됨)
- **created_at** (datetime): 계정 생성 시간
- **updated_at** (datetime): 마지막 업데이트 시간

**보안**: 비밀번호(password) 필드는 응답에서 제외됩니다.

## 사용 시나리오

- 👤 **프로필 조회**: 사용자 자신의 계정 정보 확인
- 🔑 **API 키 확인**: 등록된 거래소 API 키 상태 검증
- 🔧 **관리자 도구**: 특정 사용자 정보 확인 및 문제 해결
- 📊 **데이터 동기화**: 사용자 정보 기반 거래 설정 로드
- 🚨 **감사 로그**: 사용자 활동 추적 시 정보 조회

## 워크플로우

```
사용자 → API 요청 (user_id + exchange_name) → Redis 조회 → 사용자 정보 반환 (비밀번호 제외)
```

## 예시 URL

```
GET /user/user_12345?exchange_name=okx
GET /user/abc123xyz?exchange_name=binance
GET /user/test_user?exchange_name=upbit
```

## 보안 고려사항

- 🔐 **인증 필요**: 실제 운영 환경에서는 JWT 토큰 등 인증 메커니즘 필수
- 🛡️ **권한 검증**: 본인 또는 관리자만 조회 가능하도록 권한 체크 필요
- 🔒 **API 키 암호화**: API 키와 시크릿은 AES-256으로 암호화되어 저장
- 📝 **감사 로깅**: 사용자 정보 조회 시 로그 기록으로 추적 가능
""",
    responses={
        200: {
            "description": "✅ 사용자 정보 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "user_found": {
                            "summary": "사용자 존재",
                            "value": {
                                "success": True,
                                "message": "User ID [user_12345] found",
                                "data": {
                                    "user_id": "user_12345",
                                    "username": "trader_john",
                                    "exchange_name": "okx",
                                    "api_key": "encrypted_api_key_xxx",
                                    "api_secret": "encrypted_secret_xxx",
                                    "passphrase": "encrypted_passphrase_xxx",
                                    "created_at": "2025-01-10T12:00:00Z",
                                    "updated_at": "2025-01-12T15:30:00Z"
                                }
                            }
                        },
                        "binance_user": {
                            "summary": "바이낸스 사용자",
                            "value": {
                                "success": True,
                                "message": "User ID [binance_trader] found",
                                "data": {
                                    "user_id": "binance_trader",
                                    "username": "crypto_master",
                                    "exchange_name": "binance",
                                    "api_key": "encrypted_binance_key",
                                    "api_secret": "encrypted_binance_secret",
                                    "passphrase": None,
                                    "created_at": "2025-01-05T08:00:00Z",
                                    "updated_at": "2025-01-12T10:00:00Z"
                                }
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": "❌ 잘못된 요청 - 유효하지 않은 파라미터",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_exchange": {
                            "summary": "지원하지 않는 거래소",
                            "value": error_example(
                                message="Invalid exchange name: unknown_exchange",
                                error_code="VALIDATION_ERROR",
                                path="/user/{user_id}",
                                method="GET",
                                details={"exchange_name": "unknown_exchange"},
                            ),
                        },
                        "invalid_user_id": {
                            "summary": "잘못된 사용자 ID 형식",
                            "value": error_example(
                                message="Invalid user ID format",
                                error_code="VALIDATION_ERROR",
                                path="/user/{user_id}",
                                method="GET",
                            ),
                        },
                        "empty_user_id": {
                            "summary": "빈 사용자 ID",
                            "value": error_example(
                                message="User ID cannot be empty",
                                error_code="VALIDATION_ERROR",
                                path="/user/{user_id}",
                                method="GET",
                            ),
                        }
                    }
                }
            }
        },
        404: {
            "description": "🔍 사용자를 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "user_not_found": {
                            "summary": "존재하지 않는 사용자",
                            "value": error_example(
                                message="User ID [nonexistent_user] not found",
                                error_code="RECORD_NOT_FOUND",
                                path="/user/{user_id}",
                                method="GET",
                                details={"user_id": "nonexistent_user"},
                            ),
                        },
                        "exchange_mismatch": {
                            "summary": "거래소 불일치",
                            "value": error_example(
                                message="User exists but not registered for exchange [binance]",
                                error_code="RECORD_NOT_FOUND",
                                path="/user/{user_id}",
                                method="GET",
                                details={"exchange_name": "binance"},
                            ),
                        }
                    }
                }
            }
        },
        422: {
            "description": "🚫 유효성 검증 실패 - 필수 파라미터 누락",
            "content": {
                "application/json": {
                    "examples": {
                        "missing_exchange": {
                            "summary": "거래소 이름 누락",
                            "value": error_example(
                                message="Field required: exchange_name",
                                error_code="VALIDATION_ERROR",
                                path="/user/{user_id}",
                                method="GET",
                            ),
                        },
                        "missing_user_id": {
                            "summary": "사용자 ID 누락",
                            "value": error_example(
                                message="Field required: user_id",
                                error_code="VALIDATION_ERROR",
                                path="/user/{user_id}",
                                method="GET",
                            ),
                        }
                    }
                }
            }
        },
        500: {
            "description": "💥 서버 오류 - Redis 연결 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_error": {
                            "summary": "Redis 연결 오류",
                            "value": error_example(
                                message="Database connection failed",
                                error_code="REDIS_ERROR",
                                path="/user/{user_id}",
                                method="GET",
                            ),
                        },
                        "query_error": {
                            "summary": "데이터 조회 실패",
                            "value": error_example(
                                message="Failed to retrieve user data",
                                error_code="DATABASE_ERROR",
                                path="/user/{user_id}",
                                method="GET",
                            ),
                        },
                        "decryption_error": {
                            "summary": "복호화 실패",
                            "value": error_example(
                                message="Failed to decrypt API credentials",
                                error_code="INTERNAL_ERROR",
                                path="/user/{user_id}",
                                method="GET",
                            ),
                        }
                    }
                }
            }
        }
    }
)
async def get_user_by_id_route(
    user_id: str = Path(..., description="User ID"),
    exchange_name: str = Query(..., description="Exchange name (okx, binance, etc.)")
) -> ResponseDto[Optional[UserWithoutPasswordDto]]:
    logger.info(
        "Getting user by ID",
        extra={"exchange": exchange_name, "user_id": user_id}
    )

    try:
        user = await user_service.get_user_by_id(exchange_name, user_id)

        if user:
            logger.info(
                "User found by ID",
                extra={"exchange": exchange_name, "user_id": user_id}
            )

            return ResponseDto[Optional[UserWithoutPasswordDto]](
                success=True,
                message=f"User ID [{user_id}] found",
                data=UserWithoutPasswordDto.from_user_dto(user_dto=user),
            )
        else:
            logger.info(
                "User not found by ID",
                extra={"exchange": exchange_name, "user_id": user_id}
            )

            return ResponseDto[Optional[UserWithoutPasswordDto]](
                success=False,
                message=f"User ID [{user_id}] not found",
                data=None
            )

    except Exception as e:
        logger.error(
            "Failed to get user by ID",
            exc_info=True,
            extra={"exchange": exchange_name, "user_id": user_id}
        )
        # Exception automatically handled by exception handlers
        raise
