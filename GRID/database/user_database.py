import trace
from tracemalloc import stop
import aiosqlite
from cryptography.fernet import Fernet, InvalidToken
import base64
import json
import os

from pyparsing import col
from typing import List
import datetime
import traceback


db_connections = {}
# 데이터베이스 연결 및 테이블 생성 함수
# Load the key
# Generate and save the key if it does not exist
key_file_path = "secret.key"
if not os.path.exists(key_file_path):
    key = Fernet.generate_key()
    with open(key_file_path, "wb") as key_file:
        key_file.write(key)
else:
    with open(key_file_path, "rb") as key_file:
        key = key_file.read()

cipher = Fernet(key)
# Function to encrypt data
def encrypt_data(data):
    return cipher.encrypt(data.encode()).decode()

def decrypt_data(data):
    try:
        return cipher.decrypt(data.encode()).decode()
    except InvalidToken:
        print(f"Invalid Token: The data could not be decrypted. Data: {data}")
        raise

async def insert_user(user_id, exchange_name, api_key, api_secret, password=None):
    db_name = f'{exchange_name}_users.db'

    async with aiosqlite.connect(db_name) as db:
        await db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            api_key TEXT,
            api_secret TEXT,
            password TEXT,
            initial_capital REAL DEFAULT 10,
            direction TEXT DEFAULT 'long',
            numbers_to_entry INTEGER DEFAULT 5,
            leverage REAL DEFAULT 1,
            is_running INTEGER,
            stop_loss REAL
            tasks TEXT DEFAULT '[]',
        )
        ''')
        await db.execute('''
        INSERT INTO users (user_id, api_key, api_secret, password, initial_capital, direction, numbers_to_entry, leverage, is_running, stop_loss, tasks)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, api_key, api_secret, password, 10, 'long', 5, 10, None, None))
        await db.commit()
    return user_id

def get_db_name(exchange_name):
    #print(exchange_name)
    exchange_dbs = {
        'binance': 'binance_users.db',
        'binance_spot': 'binance_spot_users.db',
        'okx': 'okx_users.db',
        'okx_spot': 'okx_spot_users.db',
        'bitget': 'bitget_users.db',
        'bitget_spot': 'bitget_spot_users.db',
        'upbit': 'upbit_users.db',
        'bybit': 'bybit_users.db',
        'bybit_spot': 'bybit_spot_users.db'
    }
    #print(exchange_dbs)
    return exchange_dbs.get(exchange_name)

async def init_job_table(exchange_name: str):
    db_name = get_db_name(exchange_name)
    print(f"Initializing job table for exchange: {exchange_name}")

    async with aiosqlite.connect(db_name) as db:
        try:
            # BEGIN TRANSACTION
            await db.execute('BEGIN')

            # Create jobs table if not exists
            await db.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    user_id INTEGER PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    start_time TEXT NOT NULL
                )
            ''')

            # Create index on job_id for faster lookups
            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_jobs_job_id ON jobs(job_id)
            ''')

            # Commit the transaction
            await db.commit()
            print(f"Job table initialized successfully for {exchange_name}")

        except Exception as e:
            # Rollback in case of error
            await db.rollback()
            print(f"Error initializing job table for {exchange_name}: {e}")
            raise

    # Verify table creation
    #async with aiosqlite.connect(db_name) as db:
    #    cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'")
    #    if await cursor.fetchone():
    #        print(f"Verified: 'jobs' table exists in {db_name}")
    #    else:
    #        print(f"Warning: 'jobs' table not found in {db_name} after initialization attempt")
        

async def save_job_id(exchange_name, user_id: int, job_id: str):
    db_name = get_db_name(exchange_name)
    print('type of jobID : ',type(job_id))
    start_time = datetime.datetime.now().isoformat()
    try:
        async with aiosqlite.connect(db_name) as db:
            await db.execute('''
                INSERT OR REPLACE INTO jobs (user_id, job_id, status, start_time)
                VALUES (?, ?, ?, ?)
            ''', (user_id, job_id, 'running', start_time))
            await db.commit()
        print(f"Job ID saved for user {user_id} in {exchange_name}: {job_id}")
    except Exception as e:
        print(f"Error saving job ID: {e}")




# 기타 필요한 함수들...

async def get_job_id(exchange_name, user_id: int) -> str:
    db_name = get_db_name(exchange_name)
    async with aiosqlite.connect(db_name) as db:
        async with db.execute('SELECT job_id FROM jobs WHERE user_id = ?', (user_id,)) as cursor:
            result = await cursor.fetchone()
            return result[0] if result else None

async def update_job_status(exchange_name: str, user_id: int, status: str, job_id: str = None):
    db_name = get_db_name(exchange_name)
    print(f'Updating job status: exchange={exchange_name}, user_id={user_id}, status={status}, job_id={job_id}')
    
    async with aiosqlite.connect(db_name) as db:
        try:
            await db.execute('BEGIN TRANSACTION')
            
            # 테이블 생성 (이미 존재하면 무시됨)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    user_id INTEGER PRIMARY KEY,
                    job_id TEXT,
                    status TEXT,
                    start_time TEXT
                )
            ''')
            
            current_time = datetime.datetime.now().isoformat()
            
            # 기존 job 정보 조회
            cursor = await db.execute('SELECT job_id, start_time FROM jobs WHERE user_id = ?', (user_id,))
            existing_job = await cursor.fetchone()
            
            if existing_job:
                existing_job_id, existing_start_time = existing_job
                print(f"Existing job found: job_id={existing_job_id}, start_time={existing_start_time}")
                
                # job_id가 None이고 기존 job_id가 있으면 기존 것을 사용
                if job_id is None:
                    job_id = existing_job_id
                    print(f"Using existing job_id: {job_id}")
                
                if status == 'running' and existing_job_id is None:
                    start_time = current_time
                else:
                    start_time = existing_start_time
                
                await db.execute('''
                    UPDATE jobs
                    SET job_id = ?, status = ?, start_time = ?
                    WHERE user_id = ?
                ''', (job_id, status, start_time, user_id))
            else:
                print("No existing job found, inserting new job")
                if job_id is None:
                    raise ValueError("job_id cannot be None for new job insertion")
                
                await db.execute('''
                    INSERT OR REPLACE INTO jobs (user_id, job_id, status, start_time)
                    VALUES (?, ?, ?, ?)
                ''', (user_id, job_id, status, current_time))
            
            # users 테이블의 is_running 상태 업데이트
            await db.execute('''
                UPDATE users
                SET is_running = ?
                WHERE user_id = ?
            ''', (1 if status == 'running' else 0, user_id))
            
            await db.commit()
            print(f"Job status updated successfully: user_id={user_id}, job_id={job_id}, status={status}")
        
        except Exception as e:
            await db.rollback()
            print(f"Error updating job status: {e}")
            raise
    
    # 저장 확인
    async with aiosqlite.connect(db_name) as db:
        cursor = await db.execute('SELECT job_id, status FROM jobs WHERE user_id = ?', (user_id,))
        saved_job = await cursor.fetchone()
        if saved_job:
            print(f"Verified saved job for user {user_id}: job_id = {saved_job[0]}, status = {saved_job[1]}")
        else:
            print(f"No job found for user {user_id} after update attempt")

async def update_user_info(user_id, user_keys,  exchange_name, running_status):

    db_name = get_db_name(exchange_name)
    leverage = user_keys[user_id]['leverage']
    numbers_to_entry = user_keys[user_id]['numbers_to_entry']
    stop_loss = user_keys[user_id]['stop_loss']
    initial_capital = user_keys[user_id]['initial_capital']
    user_keys[user_id]['is_running'] = running_status
    running_status = 1 if running_status else 0
    initial_capital = json.dumps(initial_capital)
    running_symbols = json.dumps(list(user_keys[user_id]['running_symbols']))
    direction =user_keys[user_id]['direction']
    tasks = user_keys[user_id]['tasks']
    
    async with aiosqlite.connect(db_name) as db:
        try:
            # tasks를 JSON 문자열로 변환
            tasks_json = json.dumps(tasks)
            await db.execute('''
                UPDATE users
                SET is_running = ?, initial_capital = ?, direction = ?, leverage = ?, numbers_to_entry = ?, running_symbols = ?, stop_loss = ?, tasks = ?
                WHERE user_id = ?
            ''', (running_status, initial_capital, direction, leverage, numbers_to_entry, running_symbols, stop_loss, tasks_json, user_id))
            await db.commit()
            print(f"User info updated for user {user_id} in {exchange_name}")
        except Exception as e:
            print(f"Error updating user info: {e}")
            raise
    # 저장 확인
    async with aiosqlite.connect(db_name) as db:
        cursor = await db.execute('SELECT is_running, initial_capital, direction, leverage, numbers_to_entry,running_symbols,  stop_loss, tasks FROM users WHERE user_id = ?', (user_id,))
        saved_info = await cursor.fetchone()
        if saved_info:
            is_running, initial_capital, direction, leverage, numbers_to_entry, running_symbols ,stop_loss, tasks_json = saved_info
            tasks = json.loads(tasks_json)
            print(f"Saved info for user {user_id}: is_running = {is_running}, initial_capital = {initial_capital}, direction = {direction}, leverage = {leverage}, numbers_to_entry = {numbers_to_entry},running_symbols = {running_symbols} stop_loss = {stop_loss}, tasks = {tasks}")
        else:
            print(f"No info found for user {user_id}")
    return user_keys

async def get_job_status(exchange_name, user_id):
    try:
        db_name = get_db_name(exchange_name)
        async with aiosqlite.connect(db_name) as db:
            async with db.execute('SELECT status, job_id FROM jobs WHERE user_id = ?', (user_id,)) as cursor:
                result = await cursor.fetchone()
                return result if result else None
    except Exception as e :
        print(f"Error getting job status16: {e}")
async def update_user_running_status(exchange_name, user_id, is_running):
    db_name = get_db_name(exchange_name)
    time = datetime.datetime.now().isoformat()
    
    print(f"Updating user status: exchange={exchange_name}, user_id={user_id}, is_running={is_running}")
    
    async with aiosqlite.connect(db_name) as db:
        try:
            # 먼저 현재 job 정보를 조회합니다.
            cursor = await db.execute('SELECT job_id FROM jobs WHERE user_id = ?', (user_id,))
            existing_job = await cursor.fetchone()
            
            if existing_job:
                job_id = existing_job[0]
                #print(f"Found existing job_id: {job_id}")
            else:
                job_id = None
                print("No existing job_id found")

            await db.execute('''
                UPDATE users
                SET is_running = ?
                WHERE user_id = ?
            ''', (1 if is_running else 0, user_id))
            
            status = 'running' if is_running else 'stopped'
            
            if is_running:
                if job_id:
                    await db.execute('''
                        UPDATE jobs
                        SET status = ?, start_time = ?
                        WHERE user_id = ?
                    ''', (status, time, user_id))
                else:
                    print("Warning: Attempting to set status to running but no job_id found")
            else:
                if job_id:
                    await db.execute('''
                        DELETE FROM jobs WHERE user_id = ?
                    ''', (user_id,))
                
            await db.commit()
            print(f"User running status updated for {user_id} in {exchange_name}: {is_running}, job_id: {job_id}")
        except Exception as e:
            print(f"Error updating user running status: {e}")
            await db.rollback()
            raise

    # 변경 사항 확인
    async with aiosqlite.connect(db_name) as db:
        cursor = await db.execute('SELECT job_id, status FROM jobs WHERE user_id = ?', (user_id,))
        job = await cursor.fetchone()
        if job:
            print(f"Verified job for user {user_id}: job_id = {job[0]}, status = {job[1]}")
        else:
            print(f"No job found for user {user_id} after update")

async def update_telegram_id(exchange_name, user_id, telegram_id):
    db_name = get_db_name(exchange_name)
    try:
        async with aiosqlite.connect(db_name) as db:
            await db.execute('''
            UPDATE telegram_ids
            SET telegram_id = ?
            WHERE user_id = ?
            ''', (telegram_id, user_id))
            if db.total_changes == 0:
                await db.execute('''
                INSERT INTO telegram_ids (user_id, telegram_id)
                VALUES (?, ?)
                ''', (user_id, telegram_id))
            await db.commit()
        print(f"Telegram ID updated for user {user_id} in the database for {exchange_name}.")
    except Exception as e:
        print(f"Error updating Telegram ID for user {user_id} in the database for {exchange_name}: {e}")
        
async def get_telegram_id(exchange_name, user_id):
    db_name = get_db_name(exchange_name)
    try:
        async with aiosqlite.connect(db_name) as db:
            async with db.execute('''
            SELECT telegram_id
            FROM telegram_ids
            WHERE user_id = ?
            ''', (user_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return row[0]  # telegram_id
                else:
                    return None
    except Exception as e:
        print(f"Error fetching Telegram ID for user {user_id} in the database for {exchange_name}: {e}")
        return None

async def initialize_database(exchange_name):
    db_name = get_db_name(exchange_name)
    #print(f'Initializing database for {exchange_name}...')
    try:
        async with aiosqlite.connect(db_name) as db:
            await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                api_key TEXT,
                api_secret TEXT,
                password TEXT,
                initial_capital REAL DEFAULT 10,
                direction TEXT DEFAULT 'long',
                numbers_to_entry INTEGER DEFAULT 5,
                leverage REAL DEFAULT 10,
                is_running INTEGER,
                stop_loss REAL,
                tasks TEXT DEFAULT '[]',
                running_symbols TEXT DEFAULT '[]',
                grid_num INTEGER DEFAULT 20
            )
            ''')
            await db.execute('''
            CREATE TABLE IF NOT EXISTS blacklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                symbol TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
            ''')
            await db.execute('''
            CREATE TABLE IF NOT EXISTS whitelist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                symbol TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
            ''')
            await db.commit()
            await db.execute('''
            CREATE TABLE IF NOT EXISTS telegram_ids (
                user_id INTEGER PRIMARY KEY,
                telegram_id TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
            ''')
            await db.commit()
        await init_job_table(exchange_name)
        
        print(f"Database for {exchange_name} initialized successfully.")
        
    except Exception as e:
        print(f"Error initializing database for {exchange_name}: {e}")


async def get_running_user_ids(exchange_name: str) -> List[str]:
    running_user_ids = []
    db_name = f'{exchange_name}_users.db'
    async with aiosqlite.connect(db_name) as db:
        async with db.execute('''
            SELECT user_id
            FROM users
            WHERE is_running = 1
        ''') as cursor:
            users = await cursor.fetchall()
            running_user_ids = [(user[0]) for user in users]
    return running_user_ids

async def get_all_running_user_ids() -> List[str]:
    all_running_user_ids = []
    for exchange_name in ['binance', 'upbit', 'bitget', 'binance_spot', 'bitget_spot', 'okx', 'okx_spot', 'bybit', 'bybit_spot']:
        running_user_ids = await get_running_user_ids(exchange_name)
        all_running_user_ids.extend(running_user_ids)
    return all_running_user_ids

async def save_user(user_id, api_key=None, api_secret=None, password=None, initial_capital=None, direction=None, numbers_to_entry=None, leverage=None, is_running=None, stop_loss=None, tasks = None, running_symbols=None, grid_num=None, exchange_name='okx'):
    db_name = get_db_name(exchange_name)
    async with aiosqlite.connect(db_name) as db:
        await db.execute('''
        INSERT OR REPLACE INTO users (user_id, api_key, api_secret, password, initial_capital, direction, numbers_to_entry, leverage, is_running, stop_loss, tasks, running_symbols, grid_num)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ? , ?, ?)
        ''', (user_id, api_key, api_secret, password, initial_capital, direction, numbers_to_entry, leverage, is_running, stop_loss, tasks, json.dumps(running_symbols) if running_symbols is not None else '[]', grid_num))
        await db.commit()
    
    global user_keys
    if user_id in user_keys:
        user_keys[user_id].update({
            "api_key": api_key,
            "api_secret": api_secret,
            "password": password,
            "initial_capital": initial_capital,
            "direction": direction,
            "numbers_to_entry": numbers_to_entry,
            "leverage": leverage,
            "is_running": bool(is_running),
            "stop_loss": stop_loss,
            "tasks": tasks,
            "running_symbols": set(running_symbols) if running_symbols is not None else set(),
            "grid_num": grid_num
        })
    else:
        user_keys[user_id] = {
            "api_key": api_key,
            "api_secret": api_secret,
            "password": password,
            "initial_capital": initial_capital,
            "direction": direction,
            "numbers_to_entry": numbers_to_entry,
            "leverage": leverage,
            "is_running": bool(is_running),
            "stop_loss": stop_loss,
            "tasks": [],
            "running_symbols": set(running_symbols) if running_symbols is not None else set(),
            "grid_num": grid_num
        }

async def get_user_keys(exchange_name):
    global user_keys
    db_name = get_db_name(exchange_name)
    print(f"Getting user keys for path: {db_name}...")
    async with aiosqlite.connect(db_name) as db:
        async with db.execute('''
            SELECT user_id, api_key, api_secret, password, initial_capital, direction, numbers_to_entry, leverage, is_running, stop_loss, tasks, running_symbols, grid_num
            FROM users
        ''') as cursor:
            users = await cursor.fetchall()
            for user in users:
                user_id, api_key, api_secret, password, initial_capital, direction, numbers_to_entry, leverage, is_running, stop_loss, tasks, running_symbols, grid_num = user
                try:
                    api_key = api_key if api_key else None
                    api_secret = api_secret if api_secret else None
                    password = password if password else None
                except InvalidToken:
                    api_key = api_secret = password = None

                try:
                    initial_capital = json.loads(initial_capital) if isinstance(initial_capital, str) else initial_capital
                    tasks = json.loads(tasks) if tasks else []
                    running_symbols = set(json.loads(running_symbols) if running_symbols else [])
                except json.JSONDecodeError:
                    print(f"Error decoding JSON for user {user_id}")
                    continue

                user_data = {
                    "user_id": user_id,
                    "api_key": api_key,
                    "api_secret": api_secret,
                    "password": password,
                    "initial_capital": initial_capital,
                    "direction": direction,
                    "numbers_to_entry": numbers_to_entry,
                    "leverage": leverage,
                    "is_running": bool(is_running),
                    "stop_loss": stop_loss,
                    "tasks": tasks,
                    "running_symbols": running_symbols,
                    "grid_num": grid_num
                }

                if user_id not in user_keys:
                    user_keys[user_id] = user_data
                else:
                    user_keys[user_id].update(user_data)

    return user_keys

async def get_all_users(exchange):
    db_name = get_db_name(exchange)
    async with aiosqlite.connect(db_name) as db:
        async with db.execute('SELECT user_id FROM users') as cursor:
            users = await cursor.fetchall()
    return users

async def add_running_symbol(user_id, new_symbols, exchange_name):
    db_name = get_db_name(exchange_name)
    async with aiosqlite.connect(db_name) as db:
        async with db.execute('SELECT running_symbols FROM users WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row is None or row[0] is None:
                running_symbols = set()
            else:
                running_symbols = set(json.loads(row[0]))
        
        # new_symbols가 리스트나 셋인 경우 모두 추가
        if isinstance(new_symbols, (list, set)):
            running_symbols.update(new_symbols)
        else:
            running_symbols.add(new_symbols)
        
        await db.execute('''
        UPDATE users
        SET running_symbols = ?
        WHERE user_id = ?
        ''', (json.dumps(list(running_symbols)), user_id))
        await db.commit()
        
async def get_running_symbols(user_id, exchange_name):
    #꺼내서 사용할 땐,  'if  symbol in running_symbols: '이런 식으로 사용.
    db_name = get_db_name(exchange_name)
    async with aiosqlite.connect(db_name) as db:
        async with db.execute('SELECT running_symbols FROM users WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row is None or row[0] is None:
                return []
            else:
                return json.loads(row[0])    
    
        
if __name__ == '__main__':
    import asyncio
    async def test():
        print('test')
        await initialize_database('binance')
        await initialize_database('bybit')
        await initialize_database('binance_spot')
        await initialize_database('okx_spot')
        await initialize_database('bybit_spot')
        await initialize_database('bitget_spot')
        await initialize_database('upbit')
        await initialize_database('bitget')
        await initialize_database('okx')
        print('done')
        #print(await get_user_keys('okx'))
    asyncio.run(test())