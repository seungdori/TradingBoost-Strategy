"""
Symbol Repository Module

Handles database operations for symbol blacklist and whitelist.
Extracted from grid_original.py for better maintainability.
"""

import os
import aiosqlite
from typing import List


# ==================== Blacklist & Whitelist Operations ====================

async def get_ban_list_from_db(user_id, exchange_name) -> List[str]:
    """
    Get banned symbols list from database.

    Args:
        user_id: User ID
        exchange_name: Exchange name

    Returns:
        List of banned symbol names
    """
    db_path = f'{exchange_name}_users.db'
    # 데이터베이스 파일 존재 여부 확인
    if not os.path.exists(db_path):
        print(f"Database file not found: {db_path}")
        return []
    async with aiosqlite.connect(db_path) as db:
        async with db.execute('SELECT symbol FROM blacklist WHERE user_id = ?', (user_id,)) as cursor:
            ban_list = [row[0] for row in await cursor.fetchall()]
    return ban_list


async def get_white_list_from_db(user_id, exchange_name) -> List[str]:
    """
    Get whitelisted symbols from database.

    Args:
        user_id: User ID
        exchange_name: Exchange name

    Returns:
        List of whitelisted symbol names
    """
    db_path = f'{exchange_name}_users.db'
    async with aiosqlite.connect(db_path) as db:
        async with db.execute('SELECT symbol FROM whitelist WHERE user_id = ?', (user_id,)) as cursor:
            white_list = [row[0] for row in await cursor.fetchall()]
    return white_list


async def clear_blacklist(user_id, exchange_name):
    """
    Clear all blacklisted symbols for a user.

    Args:
        user_id: User ID
        exchange_name: Exchange name
    """
    db_path = f'{exchange_name}_users.db'
    async with aiosqlite.connect(db_path) as db:
        await db.execute('DELETE FROM blacklist WHERE user_id = ?', (user_id,))
        await db.commit()


async def clear_whitelist(user_id, exchange_name):
    """
    Clear all whitelisted symbols for a user.

    Args:
        user_id: User ID
        exchange_name: Exchange name
    """
    db_path = f'{exchange_name}_users.db'
    async with aiosqlite.connect(db_path) as db:
        await db.execute('DELETE FROM whitelist WHERE user_id = ?', (user_id,))
        await db.commit()


async def add_symbols(user_id, exchange_name, symbols: List[str], setting_type: str):
    """
    Add symbols to blacklist or whitelist.

    Args:
        user_id: User ID
        exchange_name: Exchange name
        symbols: List of symbols to add
        setting_type: 'blacklist' or 'whitelist'
    """
    db_path = f'{exchange_name}_users.db'
    table = setting_type
    async with aiosqlite.connect(db_path) as db:
        for symbol in symbols:
            await db.execute(f'INSERT INTO {table} (user_id, symbol) VALUES (?, ?)', (user_id, symbol))
        await db.commit()
