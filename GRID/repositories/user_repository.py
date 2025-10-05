import aiosqlite
import os

import redis
from shared.utils import path_helper
from shared.dtos.user import UserDto, UserExistDto, UserCreateDto
from GRID.database import redis_database
from GRID.database import user_database
from GRID.trading.shared_state import user_keys
db_path = str(path_helper.logs_dir / 'users.db')
#print('USER_DB_ABS_PATH', db_path)
from typing import Optional, List

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
    user_keys = await redis_database.get_user_keys(exchange_name)
    user_exist = len(user_keys) > 0
    user_ids = list(user_keys.keys()) if user_exist else []
    return UserExistDto(user_exist=user_exist, user_ids=user_ids)


async def find_user_by_id(user_id: str) -> UserDto | None:
    sql = '''
        SELECT * FROM users 
        WHERE id = ?
    '''
    params = (user_id,)

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(sql, params)
        user = await cursor.fetchone()
        await cursor.close()

        if user:
            return UserDto(
                id=user[0],
                username=user[1],
                password=user[2]
            )
        else:
            return None


async def find_user_by_username(exchange_name: str, username: str) -> Optional[dict]:
    user_keys = await redis_database.get_user_keys(exchange_name)
    for user_id, user_data in user_keys.items():
        if user_data.get('username') == username:
            return user_data
    return None

async def get_user_by_id(exchange_name: str, user_id: str) -> Optional[dict]:
    user_keys = await redis_database.get_user_keys(exchange_name)
    print('[USER KEYS]', user_keys)
    return user_keys.get(user_id)