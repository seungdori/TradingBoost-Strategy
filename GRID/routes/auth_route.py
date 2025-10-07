"""
Auth Routes - Migrated to New Infrastructure

Authentication-related API endpoints with input validation and exception handling.
"""

from fastapi import APIRouter, HTTPException

from shared.dtos.auth import LoginDto, SignupDto
from shared.dtos.response import ResponseDto
from shared.dtos.user import UserWithoutPasswordDto
from shared.logging import get_logger
from shared.errors import ValidationException, DatabaseException

from GRID.services import auth_service
from GRID.services import user_service_pg as user_database

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


@router.post("/signup", response_model=ResponseDto[dict])
async def signup(dto: SignupDto) -> ResponseDto[dict | None]:
    """
    Register a new user with API credentials.

    Args:
        dto: Signup data with user_id, exchange, API keys, password

    Returns:
        ResponseDto with registered user data

    Raises:
        ValidationException: Invalid signup data or duplicate user ID
        DatabaseException: Database operation failed

    Example:
        ```bash
        curl -X POST "http://localhost:8012/auth/signup" \\
             -H "Content-Type: application/json" \\
             -d '{
                   "user_id": "trader123",
                   "exchange_name": "okx",
                   "api_key": "your_api_key",
                   "secret_key": "your_secret_key",
                   "password": "securePassword123"
                 }'
        ```
    """
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