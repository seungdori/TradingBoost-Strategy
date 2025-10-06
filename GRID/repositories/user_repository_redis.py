"""
User Repository - Migrated to New Infrastructure

Manages user data retrieval from Redis with structured logging and error handling.
"""

from typing import Optional, Dict, Any

from shared.logging import get_logger
from shared.errors import DatabaseException, ValidationException
from shared.dtos.user import UserDto, UserExistDto, UserCreateDto

from GRID.database import redis_database

logger = get_logger(__name__)

#async def create_user(dto: UserCreateDto) -> UserDto:
#    exist_user = await find_user_by_username(dto.username)
#    if exist_user:
#        return exist_user
#
#    sql = '''
#    INSERT INTO users (
#        username, password
#    )
#    VALUES (?, ?)
#    '''
#    params = (dto.username, dto.password)
#
#    try:
#        async with aiosqlite.connect(db_path) as db:
#            await db.execute(sql, params)
#            await db.commit()
#    except Exception as e:
#        print(f"Database error: {e}")
#        raise e
#
#    return await find_user_by_username(dto.username)


async def check_user_exist(exchange_name: str) -> UserExistDto:
    """
    Check if users exist for given exchange.

    Args:
        exchange_name: Exchange identifier

    Returns:
        UserExistDto with existence status and user IDs

    Raises:
        DatabaseException: Redis operation failed

    Example:
        >>> result = await check_user_exist("okx")
        >>> print(result.user_exist)  # True
        >>> print(result.user_ids)  # ['user_123', 'user_456']
    """
    try:
        logger.info(
            "Checking user existence",
            extra={"exchange": exchange_name}
        )

        user_keys = await redis_database.get_user_keys(exchange_name)
        user_exist = len(user_keys) > 0
        user_ids = list(user_keys.keys()) if user_exist else []

        logger.info(
            "User existence checked",
            extra={
                "exchange": exchange_name,
                "user_exist": user_exist,
                "user_count": len(user_ids)
            }
        )

        return UserExistDto(user_exist=user_exist, user_ids=user_ids)

    except Exception as e:
        logger.error(
            "Failed to check user existence",
            exc_info=True,
            extra={"exchange": exchange_name}
        )
        raise DatabaseException(
            f"Failed to check user existence for exchange {exchange_name}",
            details={"exchange": exchange_name, "error": str(e)}
        )


async def find_user_by_id(user_id: str) -> Optional[UserDto]:
    """
    Find user by ID from SQLite database (DEPRECATED).

    DEPRECATED: This function is for backward compatibility only.
    New code should use Redis-based user retrieval.

    Args:
        user_id: User ID

    Returns:
        UserDto if found, None otherwise

    Note:
        This function uses the old SQLite database.
        Consider migrating to Redis-based user management.
    """
    logger.warning(
        "Using deprecated SQLite user lookup",
        extra={"user_id": user_id, "function": "find_user_by_id"}
    )

    # TODO: Migrate to Redis or PostgreSQL
    # This is a placeholder for backward compatibility
    # Current implementation commented out to avoid aiosqlite dependency

    return None


async def find_user_by_username(
    exchange_name: str,
    username: str
) -> Optional[Dict[str, Any]]:
    """
    Find user by username in Redis.

    Args:
        exchange_name: Exchange identifier
        username: Username to search for

    Returns:
        User data dict if found, None otherwise

    Raises:
        DatabaseException: Redis operation failed
        ValidationException: Invalid username format

    Example:
        >>> user = await find_user_by_username("okx", "trader123")
        >>> print(user)  # {'username': 'trader123', 'api_key': '...', ...}
    """
    if not username or not isinstance(username, str):
        raise ValidationException(
            "Username cannot be empty",
            details={"username": username}
        )

    try:
        logger.info(
            "Finding user by username",
            extra={"exchange": exchange_name, "username": username}
        )

        user_keys = await redis_database.get_user_keys(exchange_name)

        for user_id, user_data in user_keys.items():
            if user_data.get('username') == username:
                logger.info(
                    "User found by username",
                    extra={
                        "exchange": exchange_name,
                        "username": username,
                        "user_id": user_id
                    }
                )
                result: dict[str, Any] = user_data
                return result

        logger.info(
            "User not found by username",
            extra={"exchange": exchange_name, "username": username}
        )
        return None

    except Exception as e:
        logger.error(
            "Failed to find user by username",
            exc_info=True,
            extra={"exchange": exchange_name, "username": username}
        )
        raise DatabaseException(
            f"Failed to find user by username: {username}",
            details={
                "exchange": exchange_name,
                "username": username,
                "error": str(e)
            }
        )


async def get_user_by_id(
    exchange_name: str,
    user_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get user data by ID from Redis.

    Args:
        exchange_name: Exchange identifier
        user_id: User ID

    Returns:
        User data dict if found, None otherwise

    Raises:
        DatabaseException: Redis operation failed
        ValidationException: Invalid user ID format

    Example:
        >>> user = await get_user_by_id("okx", "user_123")
        >>> print(user)  # {'username': 'trader123', 'api_key': '...', ...}
    """
    if not user_id or not isinstance(user_id, str):
        raise ValidationException(
            "User ID cannot be empty",
            details={"user_id": user_id}
        )

    try:
        logger.info(
            "Getting user by ID",
            extra={"exchange": exchange_name, "user_id": user_id}
        )

        user_keys = await redis_database.get_user_keys(exchange_name)
        user_data: dict[str, Any] | None = user_keys.get(user_id)

        if user_data:
            logger.info(
                "User found by ID",
                extra={"exchange": exchange_name, "user_id": user_id}
            )
        else:
            logger.info(
                "User not found by ID",
                extra={"exchange": exchange_name, "user_id": user_id}
            )

        return user_data

    except Exception as e:
        logger.error(
            "Failed to get user by ID",
            exc_info=True,
            extra={"exchange": exchange_name, "user_id": user_id}
        )
        raise DatabaseException(
            f"Failed to get user by ID: {user_id}",
            details={
                "exchange": exchange_name,
                "user_id": user_id,
                "error": str(e)
            }
        )