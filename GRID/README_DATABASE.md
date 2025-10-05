# GRID Database Architecture

GRID 전략의 데이터베이스 아키텍처 문서입니다.

## 데이터베이스 계층 구조

```
┌─────────────────────────────────────────────────────────────┐
│                     Application Layer                        │
│  (routes, services, trading logic)                           │
└────────────┬────────────────────────────────┬────────────────┘
             │                                │
             ▼                                ▼
┌────────────────────────┐      ┌──────────────────────────────┐
│   PostgreSQL Layer     │      │      Redis Layer             │
│  (Persistent Storage)  │      │  (Real-time Cache)           │
├────────────────────────┤      ├──────────────────────────────┤
│ • User Management      │      │ • Active Grid State          │
│ • Job Tracking         │      │ • Order Placement Status     │
│ • Symbol Lists         │      │ • Position Data              │
│ • Telegram IDs         │      │ • Take Profit Orders         │
└────────────────────────┘      │ • Real-time Trading Cache    │
                                └──────────────────────────────┘
```

## PostgreSQL Tables

### grid_users
사용자 정보 및 거래 설정

```sql
CREATE TABLE grid_users (
    user_id INTEGER,
    exchange_name VARCHAR(50),
    api_key TEXT,
    api_secret TEXT,
    password TEXT,
    initial_capital FLOAT DEFAULT 10.0,
    direction VARCHAR(10) DEFAULT 'long',
    numbers_to_entry INTEGER DEFAULT 5,
    leverage FLOAT DEFAULT 10.0,
    stop_loss FLOAT,
    grid_num INTEGER DEFAULT 20,
    is_running BOOLEAN DEFAULT FALSE,
    tasks TEXT DEFAULT '[]',
    running_symbols TEXT DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (user_id, exchange_name)
);
```

**Indexes**:
- `idx_grid_users_exchange`: `(exchange_name)`
- `idx_grid_users_running`: `(is_running)`

### grid_telegram_ids
Telegram 알림 설정

```sql
CREATE TABLE grid_telegram_ids (
    user_id INTEGER,
    exchange_name VARCHAR(50),
    telegram_id VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (user_id, exchange_name),
    FOREIGN KEY (user_id, exchange_name)
        REFERENCES grid_users(user_id, exchange_name) ON DELETE CASCADE
);
```

**Indexes**:
- `idx_grid_telegram_ids_telegram`: `(telegram_id)`

### grid_jobs
Celery 작업 추적

```sql
CREATE TABLE grid_jobs (
    user_id INTEGER,
    exchange_name VARCHAR(50),
    job_id VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL,
    start_time TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (user_id, exchange_name),
    FOREIGN KEY (user_id, exchange_name)
        REFERENCES grid_users(user_id, exchange_name) ON DELETE CASCADE
);
```

**Indexes**:
- `idx_grid_jobs_job_id`: `(job_id)`
- `idx_grid_jobs_status`: `(status)`

**Status Values**:
- `running`: Job is currently executing
- `stopped`: Job has been stopped
- `error`: Job encountered an error

### grid_blacklist
심볼 거래 제한 목록

```sql
CREATE TABLE grid_blacklist (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    exchange_name VARCHAR(50) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (user_id, exchange_name)
        REFERENCES grid_users(user_id, exchange_name) ON DELETE CASCADE,
    UNIQUE (user_id, exchange_name, symbol)
);
```

**Indexes**:
- `idx_grid_blacklist_user`: `(user_id)`
- `idx_grid_blacklist_symbol`: `(symbol)`

### grid_whitelist
허용된 심볼 목록

```sql
CREATE TABLE grid_whitelist (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    exchange_name VARCHAR(50) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (user_id, exchange_name)
        REFERENCES grid_users(user_id, exchange_name) ON DELETE CASCADE,
    UNIQUE (user_id, exchange_name, symbol)
);
```

**Indexes**:
- `idx_grid_whitelist_user`: `(user_id)`
- `idx_grid_whitelist_symbol`: `(symbol)`

## Redis Data Structures

### Active Grid State
```
Key: {exchange_name}:user:{user_id}:symbol:{symbol}:active_grid:{level}
Type: Hash
Fields:
  - entry_price: float
  - position_size: float
  - grid_count: int
  - pnl: float
  - execution_time: ISO datetime string
```

### Order Placement Status
```
Key: {exchange_name}:user:{user_id}:symbol:{symbol}:order_placed
Type: Hash
Fields: {level: 0|1}  # 0=not placed, 1=placed
```

### Take Profit Orders
```
Key: {exchange_name}:user:{user_id}:symbol:{symbol}
Type: Hash
Field: take_profit_orders_info
Value: JSON object
{
  "0": {
    "order_id": "string",
    "target_price": float,
    "quantity": float,
    "active": boolean,
    "side": "buy|sell"
  },
  ...
}
```

### User Cache
```
Key: {exchange_name}:user:{user_id}
Type: Hash
Fields: (Mirrors PostgreSQL user data for fast access)
  - api_key
  - api_secret
  - password
  - initial_capital (JSON)
  - direction
  - numbers_to_entry
  - leverage
  - is_running
  - stop_loss
  - tasks (JSON array)
  - running_symbols (JSON array)
  - grid_num
```

## Repository Pattern

### UserRepository
```python
class UserRepository:
    async def get_by_id(user_id, exchange_name) -> Optional[User]
    async def get_all_by_exchange(exchange_name) -> List[User]
    async def get_running_users(exchange_name) -> List[User]
    async def create(user_data) -> User
    async def update(user_id, exchange_name, updates) -> Optional[User]
    async def update_running_status(user_id, exchange_name, is_running) -> Optional[User]
    async def add_task(user_id, exchange_name, task) -> Optional[User]
    async def remove_task(user_id, exchange_name, task) -> Optional[User]
    async def add_running_symbol(user_id, exchange_name, symbols) -> Optional[User]
    async def remove_running_symbol(user_id, exchange_name, symbol) -> Optional[User]
    async def reset_user_data(user_id, exchange_name) -> Optional[User]
    async def delete(user_id, exchange_name) -> bool
    async def get_telegram_id(user_id, exchange_name) -> Optional[str]
    async def update_telegram_id(user_id, exchange_name, telegram_id) -> TelegramID
```

### JobRepository
```python
class JobRepository:
    async def get_by_user(user_id, exchange_name) -> Optional[Job]
    async def get_job_id(user_id, exchange_name) -> Optional[str]
    async def get_job_status(user_id, exchange_name) -> Optional[Tuple[str, str]]
    async def save_job(user_id, exchange_name, job_id, status) -> Job
    async def update_job_status(user_id, exchange_name, status, job_id) -> Optional[Job]
    async def delete_job(user_id, exchange_name) -> bool
```

### SymbolListRepository
```python
class SymbolListRepository:
    async def get_blacklist(user_id, exchange_name) -> List[str]
    async def add_to_blacklist(user_id, exchange_name, symbol) -> Blacklist
    async def remove_from_blacklist(user_id, exchange_name, symbol) -> bool
    async def get_whitelist(user_id, exchange_name) -> List[str]
    async def add_to_whitelist(user_id, exchange_name, symbol) -> Whitelist
    async def remove_from_whitelist(user_id, exchange_name, symbol) -> bool
```

## Usage Examples

### Basic CRUD Operations

```python
from GRID.infra.database_pg import get_grid_db
from GRID.repositories import UserRepository

async def create_user_example():
    async with get_grid_db() as session:
        repo = UserRepository(session)

        user = await repo.create({
            "user_id": 1,
            "exchange_name": "okx",
            "api_key": "your_api_key",
            "api_secret": "your_secret",
            "password": "your_password",
            "initial_capital": 100.0,
            "direction": "long",
            "leverage": 10.0,
            "grid_num": 20
        })

        print(f"Created user: {user.user_id}")

async def update_user_status():
    async with get_grid_db() as session:
        repo = UserRepository(session)

        await repo.update_running_status(
            user_id=1,
            exchange_name="okx",
            is_running=True
        )
```

### Job Management

```python
from GRID.repositories import JobRepository

async def manage_trading_job():
    async with get_grid_db() as session:
        job_repo = JobRepository(session)

        # Start job
        await job_repo.save_job(
            user_id=1,
            exchange_name="okx",
            job_id="celery-task-abc123",
            status="running"
        )

        # Check status
        status, job_id = await job_repo.get_job_status(1, "okx")
        print(f"Job {job_id} status: {status}")

        # Stop job
        await job_repo.update_job_status(
            user_id=1,
            exchange_name="okx",
            status="stopped"
        )
```

### Symbol List Management

```python
from GRID.repositories import SymbolListRepository

async def manage_symbols():
    async with get_grid_db() as session:
        symbol_repo = SymbolListRepository(session)

        # Add to blacklist
        await symbol_repo.add_to_blacklist(
            user_id=1,
            exchange_name="okx",
            symbol="DOGE-USDT-SWAP"
        )

        # Get blacklist
        blacklist = await symbol_repo.get_blacklist(1, "okx")
        print(f"Blacklisted symbols: {blacklist}")

        # Remove from blacklist
        await symbol_repo.remove_from_blacklist(
            user_id=1,
            exchange_name="okx",
            symbol="DOGE-USDT-SWAP"
        )
```

## Performance Considerations

### Connection Pooling
```python
# Configured in shared/database/session.py
DB_POOL_SIZE = 20  # Max connections in pool
DB_MAX_OVERFLOW = 10  # Max overflow connections
DB_POOL_RECYCLE = 3600  # Recycle connections after 1 hour
```

### Indexing Strategy
- Primary keys: `(user_id, exchange_name)` composite
- Foreign keys: Indexed automatically
- Query optimization: Exchange name, running status, job status

### Redis Caching
- User data cached in Redis for fast access
- Active grid state stored only in Redis (real-time)
- Cache invalidation on user updates

## Monitoring

### Database Metrics
```sql
-- Active users by exchange
SELECT exchange_name, COUNT(*)
FROM grid_users
WHERE is_running = TRUE
GROUP BY exchange_name;

-- Job status distribution
SELECT status, COUNT(*)
FROM grid_jobs
GROUP BY status;

-- Blacklist/Whitelist stats
SELECT exchange_name, COUNT(*) as blacklist_count
FROM grid_blacklist
GROUP BY exchange_name;
```

### Redis Monitoring
```bash
# Check Redis memory usage
redis-cli INFO memory

# Monitor commands
redis-cli MONITOR

# Check key count
redis-cli DBSIZE
```

## Backup and Recovery

### PostgreSQL Backup
```bash
# Daily backup
pg_dump -U username tradingboost > backups/grid_$(date +%Y%m%d).sql

# Restore
psql -U username tradingboost < backups/grid_20241005.sql
```

### Redis Persistence
Redis is configured with RDB and AOF for durability:
```
save 900 1       # Save if 1 key changed in 900s
save 300 10      # Save if 10 keys changed in 300s
save 60 10000    # Save if 10000 keys changed in 60s
appendonly yes   # Enable AOF
```

## Migration from SQLite

See [POSTGRESQL_MIGRATION.md](./POSTGRESQL_MIGRATION.md) for detailed migration guide.

## References

- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [Redis Documentation](https://redis.io/documentation)
- [Shared Database Module](../shared/database/README.md)
