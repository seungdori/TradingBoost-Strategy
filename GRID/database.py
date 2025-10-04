import time

import aiosqlite
import os
from pathlib import Path
import infra

from shared.utils import path_helper


# logs/db 폴더 생성 (없으면)
# logs_db_path = 'logs/db'
# if not os.path.exists(logs_db_path):
#     os.makedirs(logs_db_path)


async def add_missing_columns(db):
    # 테이블의 현재 구조를 가져옵니다.
    cursor = await db.execute("PRAGMA table_info(entry);")
    columns = await cursor.fetchall()
    existing_columns = {col[1] for col in columns}  # 컬럼 이름을 셋으로 저장합니다.

    # 필요한 컬럼들을 정의합니다.
    required_columns = {
        "tp1_order_id": "TEXT",
        "tp2_order_id": "TEXT",
        "tp3_order_id": "TEXT",
        "tp1_price": "REAL",
        "tp2_price": "REAL",
        "tp3_price": "REAL",
        "sl_price": "REAL"
    }

    # 필요한 컬럼이 존재하지 않는 경우, 해당 컬럼을 추가합니다.
    for column, data_type in required_columns.items():
        if column not in existing_columns:
            alter_table_query = f"ALTER TABLE entry ADD COLUMN {column} {data_type};"
            await db.execute(alter_table_query)

    await db.commit()


async def create_database(db_path: Path):
    db_path.mkdir(exist_ok=True)
    print('[create_database]', db_path)
    # os.makedirs(os.path.dirname(db_path), exist_ok=True)

    async with aiosqlite.connect(db_path) as db:
        if "entry_data" in db_path:
            await db.execute('''
            CREATE TABLE IF NOT EXISTS entry (
                symbol TEXT PRIMARY KEY,
                direction TEXT,
                entry_time TEXT,
                entry_order_id TEXT,
                tp1_price REAL,
                tp2_price REAL,
                tp3_price REAL,
                tp1_order_id TEXT,
                tp2_order_id TEXT,
                tp3_order_id TEXT,
                sl_price REAL
            )
            ''')
        if "tp_data" in db_path:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS tp (
                    symbol TEXT PRIMARY KEY,
                    tp1_order_id TEXT,
                    tp2_order_id TEXT,
                    tp3_order_id TEXT,
                    tp1_price REAL,
                    tp2_price REAL,
                    tp3_price REAL,
                    tp1_status TEXT,
                    tp2_status TEXT,
                    tp3_status TEXT
                )
            ''')
        if "sl_data" in db_path:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS sl (
                    symbol TEXT PRIMARY KEY,
                    sl_order_id TEXT,
                    sl_price REAL,
                    sl_status TEXT
                )
            ''')
        # await add_missing_columns(db)
        await db.commit()


async def ensure_database_exists(db_name):
    return await infra.database.ensure_database_exists(db_name)


async def update_entry_data(exchange_name, symbol, direction=None, entry_time=None, entry_order_id=None, tp1_price=None,
                            tp2_price=None, tp3_price=None, tp1_order_id=None, tp2_order_id=None, tp3_order_id=None,
                            sl_price=None):
    db_path = await ensure_database_exists(f"{exchange_name}_entry_data")
    async with aiosqlite.connect(db_path) as db:
        await db.execute('''
            INSERT INTO entry (symbol, direction, entry_time, entry_order_id, tp1_price, tp2_price, tp3_price, tp1_order_id, tp2_order_id, tp3_order_id, sl_price)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
            direction=COALESCE(excluded.direction, direction),
            entry_time=COALESCE(excluded.entry_time, entry_time),
            entry_order_id=COALESCE(excluded.entry_order_id, entry_order_id),
            tp1_price=COALESCE(excluded.tp1_price, tp1_price),
            tp2_price=COALESCE(excluded.tp2_price, tp2_price),
            tp3_price=COALESCE(excluded.tp3_price, tp3_price),
            tp1_order_id=COALESCE(excluded.tp1_order_id, tp1_order_id),
            tp2_order_id=COALESCE(excluded.tp2_order_id, tp2_order_id),
            tp3_order_id=COALESCE(excluded.tp3_order_id, tp3_order_id),
            sl_price=COALESCE(excluded.sl_price, sl_price)
        ''', (
            symbol, direction, entry_time, entry_order_id, tp1_price, tp2_price, tp3_price, tp1_order_id, tp2_order_id,
            tp3_order_id, sl_price))
        await db.commit()


# TODO : 배치 사용 고려
async def update_tp_data(exchange_name, symbol, **kwargs):
    db_path = await ensure_database_exists(f"{exchange_name}_tp_data")
    async with aiosqlite.connect(db_path) as db:
        # 컬럼 순서를 명시적으로 지정
        columns = ['symbol', 'tp1_order_id', 'tp2_order_id', 'tp3_order_id', 'tp1_price', 'tp2_price', 'tp3_price',
                   'tp1_status', 'tp2_status', 'tp3_status']
        placeholders = ', '.join(['?' for _ in columns])
        # 입력된 kwargs에 따라 값을 정렬
        values = [kwargs.get(column) for column in columns if column != 'symbol']
        # symbol을 맨 앞에 추가
        values = [symbol] + values

        # 명시적으로 지정된 컬럼 순서에 따라 쿼리 실행
        await db.execute(f"INSERT OR REPLACE INTO tp ({', '.join(columns)}) VALUES ({placeholders})", values)
        await db.commit()


async def update_sl_data(exchange_name, symbol, sl_order_id, sl_price, sl_status):
    await infra.database.update_sl_data(exchange_name, symbol, sl_order_id, sl_price, sl_status)


async def save_win_rates_to_db(exchange_id, symbol, df):
    start = time.time()
    await infra.database.save_win_rates_to_db(exchange_id, symbol, df)
    end = time.time()
    time_taken_sec = end - start
    print('[SAVE WIN RATES TO DB TIME SEC]', '{:.5f}.'.format(round(time_taken_sec, 5)))