"""
Auth Service - Migrated to New Infrastructure

Manages password hashing and authentication with structured logging.
"""

import bcrypt

from GRID.dtos.auth import LoginDto, SignupDto
from GRID.dtos.user import UserCreateDto, UserWithoutPasswordDto
from GRID.services import user_service
from shared.errors import ValidationException
from shared.logging import get_logger

logger = get_logger(__name__)


def hash_password(raw_password: str) -> bytes:
    """
    Hash a password using bcrypt.

    Args:
        raw_password: Plain text password

    Returns:
        Hashed password bytes

    Raises:
        ValidationException: Invalid password format

    Example:
        >>> hashed = hash_password("myPassword123")
        >>> print(type(hashed))  # <class 'bytes'>
    """
    if not raw_password or not isinstance(raw_password, str):
        raise ValidationException(
            "Password cannot be empty",
            details={"password_provided": bool(raw_password)}
        )

    if len(raw_password) < 8:
        raise ValidationException(
            "Password must be at least 8 characters",
            details={"length": len(raw_password)}
        )

    try:
        logger.debug("Hashing password")

        pwd_bytes = raw_password.encode('utf-8')
        salt = bcrypt.gensalt()
        hashed_password = bcrypt.hashpw(password=pwd_bytes, salt=salt)

        logger.debug("Password hashed successfully")
        return hashed_password

    except Exception as e:
        logger.error(
            "Failed to hash password",
            exc_info=True
        )
        raise ValidationException(
            f"Password hashing failed: {str(e)}",
            details={"error": str(e)}
        )


## Check if the provided password matches the stored password (hashed)
#def verify_password(raw_password, hashed_password):
#    password_byte_enc = raw_password.encode('utf-8')
#    hashed_password_byte_enc = hashed_password.encode('utf-8')
#    return bcrypt.checkpw(password=password_byte_enc, hashed_password=hashed_password_byte_enc)


#async def login(dto: LoginDto) -> UserWithoutPasswordDto | None:
#    exist_user = await user_service.find_user_by_username(username=dto.username)
#    if exist_user:
#        is_password_correct = verify_password(raw_password=dto.password, hashed_password=exist_user.password)
#        print("IS PASSWORD CORRECT", is_password_correct)
#
#        if is_password_correct:
#            return UserWithoutPasswordDto.from_user_dto(user_dto=exist_user)
#
#        else:
#            return None


#async def signup(dto: SignupDto) -> UserWithoutPasswordDto:
#    exist_user = await user_service.find_user_by_username(username=dto.username)
#    if exist_user:
#        return UserWithoutPasswordDto.from_user_dto(user_dto=exist_user)
#
#    else:
#        hashed_password = hash_password(raw_password=dto.password)
#        created_user = await user_service.create_user(
#            dto=UserCreateDto(username=dto.username, password=hashed_password)
#        )
#        print("[CREATED USER]", created_user)
#        return UserWithoutPasswordDto.from_user_dto(user_dto=created_user)
