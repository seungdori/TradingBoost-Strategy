"""
User Routes - Migrated to New Infrastructure

User-related API endpoints with input validation and exception handling.
"""

from fastapi import APIRouter, Query, Path
from typing import Optional, Union

from shared.dtos.response import ResponseDto
from shared.dtos.user import UserExistDto, UserWithoutPasswordDto
from shared.logging import get_logger
from shared.errors import ValidationException, DatabaseException

from GRID.services import user_service

logger = get_logger(__name__)
router = APIRouter(prefix="/user", tags=["user"])


@router.get("/exist", response_model=ResponseDto[UserExistDto])
async def check_user_exist_route(
    exchange_name: str = Query(..., description="Exchange name (okx, binance, etc.)")
) -> ResponseDto[UserExistDto]:
    """
    Check if users exist for given exchange.

    Args:
        exchange_name: Exchange identifier

    Returns:
        ResponseDto with user existence status and IDs

    Raises:
        ValidationException: Invalid exchange name
        DatabaseException: Redis operation failed

    Example:
        ```bash
        curl "http://localhost:8012/user/exist?exchange_name=okx"
        ```
    """
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
                "user_count": len(user_exist_dto.user_ids)
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


@router.get("/{user_id}", response_model=ResponseDto[Optional[UserWithoutPasswordDto]])
async def get_user_by_id_route(
    user_id: str = Path(..., description="User ID"),
    exchange_name: str = Query(..., description="Exchange name (okx, binance, etc.)")
) -> ResponseDto[Optional[UserWithoutPasswordDto]]:
    """
    Get user by ID.

    Args:
        user_id: User ID (path parameter)
        exchange_name: Exchange identifier (query parameter)

    Returns:
        ResponseDto with user data (without password) or None if not found

    Raises:
        ValidationException: Invalid user ID or exchange name
        DatabaseException: Redis operation failed

    Example:
        ```bash
        curl "http://localhost:8012/user/user_123?exchange_name=okx"
        ```
    """
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

            return ResponseDto[UserWithoutPasswordDto](
                success=True,
                message=f"User ID [{user_id}] found",
                data=UserWithoutPasswordDto.from_user_dto(user_dto=user),
            )
        else:
            logger.info(
                "User not found by ID",
                extra={"exchange": exchange_name, "user_id": user_id}
            )

            return ResponseDto[None](
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
