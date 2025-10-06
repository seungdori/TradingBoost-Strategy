"""
User Service - Migrated to New Infrastructure

Manages user operations with repository pattern and exception handling.
"""

from typing import Optional, Dict, Any

from shared.logging import get_logger
from shared.errors import DatabaseException, ValidationException

from GRID.dtos.user import UserDto, UserExistDto, UserCreateDto
from GRID.repositories import user_repository
from GRID.database import redis_database

logger = get_logger(__name__)


async def check_user_exist(exchange_name: str) -> UserExistDto:
    """
    Check if users exist for exchange.

    Args:
        exchange_name: Exchange identifier

    Returns:
        UserExistDto with existence status and user IDs

    Raises:
        DatabaseException: Redis operation failed
        ValidationException: Invalid exchange name

    Example:
        >>> result = await check_user_exist("okx")
        >>> print(result.user_exist)  # True
    """
    if not exchange_name or not isinstance(exchange_name, str):
        raise ValidationException(
            "Exchange name cannot be empty",
            details={"exchange_name": exchange_name}
        )

    try:
        logger.info(
            "Checking user existence via service",
            extra={"exchange": exchange_name}
        )

        # Delegate to repository
        result = await user_repository.check_user_exist(exchange_name)

        logger.info(
            "User existence check completed",
            extra={
                "exchange": exchange_name,
                "user_exist": result.user_exist,
                "user_count": len(result.user_ids)
            }
        )

        return result

    except (DatabaseException, ValidationException):
        # Re-raise expected exceptions
        raise
    except Exception as e:
        logger.error(
            "Unexpected error checking user existence",
            exc_info=True,
            extra={"exchange": exchange_name}
        )
        raise DatabaseException(
            f"Failed to check user existence",
            details={"exchange": exchange_name, "error": str(e)}
        )


async def get_user_by_id(
    exchange_name: str,
    user_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get user by ID.

    Args:
        exchange_name: Exchange identifier
        user_id: User ID

    Returns:
        User data dict if found, None otherwise

    Raises:
        DatabaseException: Redis operation failed
        ValidationException: Invalid parameters

    Example:
        >>> user = await get_user_by_id("okx", "user_123")
        >>> print(user.get('username'))  # 'trader123'
    """
    if not exchange_name or not isinstance(exchange_name, str):
        raise ValidationException(
            "Exchange name cannot be empty",
            details={"exchange_name": exchange_name}
        )

    if not user_id or not isinstance(user_id, str):
        raise ValidationException(
            "User ID cannot be empty",
            details={"user_id": user_id}
        )

    try:
        logger.info(
            "Getting user by ID via service",
            extra={"exchange": exchange_name, "user_id": user_id}
        )

        # Delegate to repository
        user: dict[str, Any] | None = await user_repository.get_user_by_id(exchange_name, user_id)

        if user:
            logger.info(
                "User found",
                extra={"exchange": exchange_name, "user_id": user_id}
            )
        else:
            logger.info(
                "User not found",
                extra={"exchange": exchange_name, "user_id": user_id}
            )

        return user

    except (DatabaseException, ValidationException):
        # Re-raise expected exceptions
        raise
    except Exception as e:
        logger.error(
            "Unexpected error getting user by ID",
            exc_info=True,
            extra={"exchange": exchange_name, "user_id": user_id}
        )
        raise DatabaseException(
            f"Failed to get user by ID",
            details={
                "exchange": exchange_name,
                "user_id": user_id,
                "error": str(e)
            }
        )


async def find_user_by_username(
    exchange_name: str,
    username: str
) -> Optional[Dict[str, Any]]:
    """
    Find user by username.

    Args:
        exchange_name: Exchange identifier
        username: Username to search for

    Returns:
        User data dict if found, None otherwise

    Raises:
        DatabaseException: Redis operation failed
        ValidationException: Invalid parameters

    Example:
        >>> user = await find_user_by_username("okx", "trader123")
        >>> print(user.get('user_id'))  # 'user_123'
    """
    if not exchange_name or not isinstance(exchange_name, str):
        raise ValidationException(
            "Exchange name cannot be empty",
            details={"exchange_name": exchange_name}
        )

    if not username or not isinstance(username, str):
        raise ValidationException(
            "Username cannot be empty",
            details={"username": username}
        )

    try:
        logger.info(
            "Finding user by username via service",
            extra={"exchange": exchange_name, "username": username}
        )

        # Delegate to repository
        user: dict[str, Any] | None = await user_repository.find_user_by_username(
            exchange_name,
            username
        )

        if user:
            logger.info(
                "User found by username",
                extra={"exchange": exchange_name, "username": username}
            )
        else:
            logger.info(
                "User not found by username",
                extra={"exchange": exchange_name, "username": username}
            )

        return user

    except (DatabaseException, ValidationException):
        # Re-raise expected exceptions
        raise
    except Exception as e:
        logger.error(
            "Unexpected error finding user by username",
            exc_info=True,
            extra={"exchange": exchange_name, "username": username}
        )
        raise DatabaseException(
            f"Failed to find user by username",
            details={
                "exchange": exchange_name,
                "username": username,
                "error": str(e)
            }
        )
