import aiosqlite
import os
import time

from shared.utils import path_helper


# logs/db 폴더 생성 (없으면)
# logs_db_path = 'logs/db'
# if not os.path.exists(logs_db_path):
#     os.makedirs(logs_db_path)


# 데이터베이스 연결 및 사용자 테이블 생성 (없으면)
async def create_user_table_if_not_exists():
    start = time.time()
    user_db_path = str(path_helper.logs_dir / 'users.db')

    if os.path.exists(user_db_path):
        return

    try:
        sql: str = '''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL
            )
        '''
        async with aiosqlite.connect(user_db_path) as db:
            await db.execute(sql)
            await db.commit()
    except Exception as e:
        print(f"Database error: {e}")
        raise e

    end = time.time()
    time_taken_sec = (end - start)
    print(f'[USER Database creation time]', '{:.5f}.'.format(round(time_taken_sec, 5)))


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


async def create_database(db_path):
    if "entry_data" in db_path:
        async with aiosqlite.connect(db_path) as db:
            sql: str = '''
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
            '''
            await db.execute(sql)
            await db.commit()

    elif "tp_data" in db_path:
        async with aiosqlite.connect(db_path) as db:
            sql: str = '''
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
            '''
            await db.execute(sql)
            await db.commit()

    elif "sl_data" in db_path:
        async with aiosqlite.connect(db_path) as db:
            sql: str = '''
                CREATE TABLE IF NOT EXISTS sl (
                    symbol TEXT PRIMARY KEY,
                    sl_order_id TEXT,
                    sl_price REAL,
                    sl_status TEXT
                )
            '''
            await db.execute(sql)
            await db.commit()

    elif "win_rate" in db_path:
        async with aiosqlite.connect(db_path) as db:
            sql: str = '''
                CREATE TABLE IF NOT EXISTS win_rates (
                    symbol TEXT PRIMARY KEY,
                    long_win_rate REAL,
                    short_win_rate REAL,
                    total_win_rate REAL,
                    long_entry_count INTEGER,
                    short_entry_count INTEGER,
                    long_stop_loss_count INTEGER,
                    long_take_profit_count INTEGER,
                    short_stop_loss_count INTEGER,
                    short_take_profit_count INTEGER,
                    first_timestamp TEXT,
                    last_timestamp TEXT,
                    total_win_rate_length INTEGER
                )
            '''
            await db.execute(sql)
            await db.commit()


async def ensure_database_exists(db_name):
    start = time.time()

    #print('[ensure_database_exists]')
    db_path = str(path_helper.logs_dir / 'New_Trading_Data' / f'{db_name}.db')
    #print('[DB PATH]', db_path)

    # Ensure database file located directory
    db_located_dir = os.path.dirname(db_path)
    os.makedirs(db_located_dir, exist_ok=True)
    #print('[DB FILE LOCATED DIRECTORY]', db_located_dir)

    if not os.path.exists(db_path):
        await create_database(db_path)

    end = time.time()
    time_taken_sec = end - start
    print('[ENSURE DATABASE EXISTS TIME SEC]', '{:.5f}.'.format(round(time_taken_sec, 5)))
    return db_path


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
    db_path = await ensure_database_exists(f"{exchange_name}_sl_data")
    async with aiosqlite.connect(db_path) as db:
        await db.execute('''
            INSERT INTO sl (symbol, sl_order_id, sl_price, sl_status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                sl_order_id=excluded.sl_order_id,
                sl_price=excluded.sl_price,
                sl_status=excluded.sl_status
        ''', (symbol, sl_order_id, sl_price, sl_status))
        await db.commit()


async def save_win_rates_to_db(exchange_id, symbol, df):
    try:
        db_path = await ensure_database_exists(f"{exchange_id}_win_rate")

        #print('[WIN RATE DATABASE PATH]', db_path)

        async with aiosqlite.connect(db_path) as db:
            # 기존 total_win_rate_length 값을 확인
            cur = await db.execute('SELECT total_win_rate_length FROM win_rates WHERE symbol = ?', (symbol,))
            existing_length = await cur.fetchone()

            # DataFrame에서 total_win_rate의 길이 계산
            new_length = len(df['total_win_rate'].dropna())

            # 새로운 길이가 기존 길이보다 길거나 같은 경우에만 업데이트 진행
            try:
                first_timestamp = df.index[0].isoformat()
                last_timestamp = df.index[-1].isoformat()
                if existing_length is None or new_length >= existing_length[0]:
                    await db.execute('''
                    INSERT INTO win_rates (
                        symbol, long_win_rate, short_win_rate, total_win_rate,
                        long_entry_count, short_entry_count, long_stop_loss_count, long_take_profit_count,
                        short_stop_loss_count, short_take_profit_count, first_timestamp, last_timestamp, total_win_rate_length
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(symbol) DO UPDATE SET
                        long_win_rate=excluded.long_win_rate,
                        short_win_rate=excluded.short_win_rate,
                        total_win_rate=excluded.total_win_rate,
                        long_entry_count=excluded.long_entry_count,
                        short_entry_count=excluded.short_entry_count,
                        long_stop_loss_count=excluded.long_stop_loss_count,
                        long_take_profit_count=excluded.long_take_profit_count,
                        short_stop_loss_count=excluded.short_stop_loss_count,
                        short_take_profit_count=excluded.short_take_profit_count,
                        first_timestamp=excluded.first_timestamp,
                        last_timestamp=excluded.last_timestamp,
                        total_win_rate_length=excluded.total_win_rate_length
                    ''', (
                        symbol,
                        df['long_win_rate'].iloc[-1],
                        df['short_win_rate'].iloc[-1],
                        df['total_win_rate'].iloc[-1],
                        df['long_entry_count'].iloc[-1],
                        df['short_entry_count'].iloc[-1],
                        df['long_stop_loss_count'].iloc[-1],
                        df['long_take_profit_count'].iloc[-1],
                        df['short_stop_loss_count'].iloc[-1],
                        df['short_take_profit_count'].iloc[-1],
                        first_timestamp,
                        last_timestamp,
                        new_length
                    ))
                    await db.commit()
            except Exception as e:
                print(f"Error: {e}")
    except aiosqlite.Error as e:
        print(f"Database error: {e}")
        raise e
    except Exception as e:
        print(f"General error: {e}")
        raise e