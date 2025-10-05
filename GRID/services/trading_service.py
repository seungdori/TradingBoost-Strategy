import json
from typing import List

from GRID.dtos.symbol import AccessListDto
from shared.utils import path_helper
import aiosqlite

def get_list_from_file(file_name: str):
    file_path = file_name
    try:
        with open(file_path, 'r') as file:
            white_list = json.load(file)
            #print('[ LIST]', white_list)
            return white_list
    except FileNotFoundError:
        print(f"No such file: {file_name}")
        return []  # 파일이 없는 경우 빈 리스트 반환


def get_ban_list_from_file(file_name: str):
    return get_list_from_file(file_name)


def get_white_list_from_file(file_name: str):
    return get_list_from_file(file_name)


async def get_black_list(exchange_name, user_id):
    return await get_list_from_db(exchange_name, user_id, 'blacklist')

async def get_white_list(exchange_name, user_id):
    return await get_list_from_db(exchange_name, user_id, 'whitelist')

async def get_list_from_db(exchange_name: str, user_id: int, list_type: str):
    db_path = f'{exchange_name}_users.db'
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(f'SELECT symbol FROM {list_type} WHERE user_id = ?', (user_id,))
        symbols = await cursor.fetchall()
        await cursor.close()
    return [symbol[0] for symbol in symbols] if symbols else []

# def update_file(file_name: str, items: List[str]):
#     file_path = str(path_helper.packaged_binary_dir / file_name)
#     print('[UPDATE FILE PATH]', file_path)
#     try:
#         with open(file_path, 'w') as file:
#             json.dump(items, file)
#     except Exception as e:
#         raise e


# def remove_items_from_file(file_name: str, items_to_remove: List[str]):
#     try:
#         items = get_list_from_file(file_name)
#         # Remove each item in items_to_remove if it exists in items
#         updated_items = [item for item in items if item not in items_to_remove]
#         update_file(file_name, updated_items)
#     except FileNotFoundError:
#         print(f"No such file: {file_name}")


def get_access_list(exchange_name, user_id, type) -> AccessListDto:
    if type == 'blacklist':
        return AccessListDto(type=type, symbols=get_black_list(exchange_name, user_id))
    if type == 'whitelist':
        return AccessListDto(type=type, symbols=get_white_list(exchange_name, user_id))
    else:
        raise ValueError(f"Invalid access type: {type}")

async def get_black_list(exchange_name, user_id):
    db_path = f'{exchange_name}_users.db'
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute('SELECT symbol FROM blacklist WHERE user_id = ?', (user_id,))
        symbols = await cursor.fetchall()
        await cursor.close()

async def get_white_list(exchange_name, user_id):
    db_path = f'{exchange_name}_users.db'
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute('SELECT symbol FROM whitelist WHERE user_id = ?', (user_id,))
        symbols = await cursor.fetchall()
        await cursor.close()


#

def update_file(file_name: str, new_items: List[str], append: bool = False):
    file_path = file_name
    items = get_list_from_file(file_name) if append else []
    # Combine existing items with new_items, ensuring no duplicates
    updated_items = list(set(items + new_items))
    try:
        with open(file_path, 'w') as file:
            json.dump(updated_items, file)
    except Exception as e:
        raise e


def remove_items_from_file(file_name: str, items_to_remove: List[str]):
    items = get_list_from_file(file_name)
    updated_items = [item for item in items if item not in items_to_remove]
    update_file(file_name, updated_items, append=False)


def update_access_list(dto: AccessListDto, append: bool = False):
    file_name = 'ban_list.json' if dto.type == 'blacklist' else 'white_list.json'
    update_file(file_name=file_name, new_items=dto.symbols, append=append)


def add_access_list(dto: AccessListDto):
    update_access_list(dto=dto, append=True)


def delete_access_list(dto: AccessListDto):
    file_name = 'ban_list.json' if dto.type == 'blacklist' else 'white_list.json'
    remove_items_from_file(file_name, dto.symbols)
