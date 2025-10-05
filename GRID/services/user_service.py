from GRID.dtos.user import UserDto, UserExistDto, UserCreateDto
from GRID.repositories import user_repository
from GRID.database import redis_database
from typing import Optional, List
#async def create_user(dto: UserCreateDto) -> UserDto:
#    return await user_repository.create_user(dto)


async def check_user_exist(exchange_name: str) -> UserExistDto:
    user_keys = await redis_database.get_user_keys(exchange_name)
    user_exist = len(user_keys) > 0
    user_ids = list(user_keys.keys()) if user_exist else []
    return UserExistDto(user_exist=user_exist, user_ids=user_ids)  # 이 줄이 변경됨



async def get_user_by_id(exchange_name: str, user_id: str) -> Optional[dict]:
    user_keys = await redis_database.get_user_keys(exchange_name)
    print('[USER KEYS]', user_keys)
    return user_keys.get(user_id)


async def find_user_by_username(exchange_name: str, username: str) -> Optional[dict]:
    user_keys = await redis_database.get_user_keys(exchange_name)
    for user_id, user_data in user_keys.items():
        if user_data.get('username') == username:
            return user_data
    return None
