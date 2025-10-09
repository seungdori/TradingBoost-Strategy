# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TradingBoost-Strategy is a cryptocurrency automated trading system monorepo implementing multiple trading strategies (HYPERRSI and GRID) with shared infrastructure components.

**Tech Stack**: Python 3.12+, FastAPI, Celery, Redis, WebSockets, CCXT

**Supported Exchanges**: OKX (primary), Binance, Bitget, Upbit, Bybit

## Monorepo Structure & Import Rules

This is a monorepo with three top-level packages that must be imported using absolute paths:

```
TradingBoost-Strategy/
├── HYPERRSI/          # RSI + trend-based strategy (port 8000)
├── GRID/              # Price grid-based strategy (port 8012)
└── shared/            # Common modules (config, exchange APIs, utilities)
```

### PYTHONPATH - 자동 설정됨! ✅

**모든 파일이 자동으로 경로를 설정합니다.** PYTHONPATH 설정 불필요!

각 실행 파일(main.py, app.py, celery_task.py 등)에 다음 코드가 포함되어 있습니다:

```python
import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
```

**그냥 실행하면 됩니다:**

```bash
cd HYPERRSI && python main.py
cd GRID && python main.py

# 또는 프로젝트 루트에서
./run_hyperrsi.sh
./run_grid.sh
```

**추가 옵션 (선택사항):** 더 깔끔한 설정을 원하면 editable install:
```bash
pip install -e .
```

### Import Patterns

**GRID Strategy** (see GRID/IMPORT_GUIDE.md for full details):
```python
# ✅ Correct - absolute imports with GRID prefix
from GRID.strategies import strategy, grid
from GRID.database import redis_database
from GRID.services import bot_state_service
from GRID.core.redis import get_redis_connection

# ❌ Wrong - relative imports or missing GRID prefix
from strategy import some_function
from ..database import redis_database
from services import bot_state_service
```

**HYPERRSI Strategy**:
```python
# ✅ Correct - absolute imports with HYPERRSI prefix
from HYPERRSI.src.api.routes import trading, account
from HYPERRSI.src.core.logger import get_logger
from HYPERRSI.src.services.redis_service import init_redis

# ❌ Wrong - relative imports
from src.api.routes import trading
```

**Shared Modules**:
```python
# ✅ Correct - absolute imports with shared prefix
from shared.config import get_settings
from shared.exchange_apis.exchange_store import ExchangeStore
from shared.utils.retry import retry_async
```

## Running the Strategies

### HYPERRSI Strategy

```bash
# Development (with auto-reload)
cd HYPERRSI
python main.py

# Production (same command)
cd HYPERRSI
python main.py
```

**With Celery workers** (required for background tasks):
```bash
cd HYPERRSI
./start_celery_worker.sh  # Starts Celery workers with proper macOS config
./stop_celery_worker.sh   # Gracefully stops all Celery workers
```

### GRID Strategy

```bash
cd GRID
python main.py --port 8012
```

**Worker Management**:
- GRID uses multiprocessing workers managed by `worker_manager.py`
- Workers are automatically started/stopped with the main process
- Default: 2 workers (configurable in main.py)

## Environment Configuration

Both strategies use shared environment variables from `.env` in the project root:

```bash
# Copy example file
cp HYPERRSI/.env.example .env

# Required variables:
# - OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE
# - TELEGRAM_BOT_TOKEN, OWNER_ID
# - REDIS_HOST, REDIS_PORT (default: localhost:6379)
# - DATABASE_URL (optional for PostgreSQL)
```

**Configuration Loading**:
- Shared config: `shared/config.py` (Settings class with pydantic-settings)
- Access via: `from shared.config import get_settings; settings = get_settings()`
- Both HYPERRSI and GRID extend this base configuration

## Architecture Patterns

### Shared Infrastructure Layer

The `shared/` directory provides common functionality:

- **Config**: Centralized settings management with environment variable loading
- **Exchange APIs**: CCXT-based exchange API wrappers
- **Constants**: Shared trading constants and enumerations
- **Database**: Common database utilities
- **Utils**: Retry logic, validation helpers, logging utilities
- **Notifications**: Telegram notification system

### Strategy-Specific Patterns

**HYPERRSI** (src/ directory structure):
- **api/**: FastAPI routes organized by domain (trading, account, order, position, etc.)
- **core/**: Database models, logger, error handlers
- **services/**: Business logic layer (redis_service, trading services)
- **trading/**: Trading execution logic and utilities
- **data_collector/**: Market data collection with Celery tasks
- **bot/**: Telegram bot integration
- **tasks/**: Celery task definitions

**GRID** (flat module structure):
- **strategies/**: Grid trading algorithm implementation
- **services/**: Bot state, trading service logic
- **handlers/**: Exchange-specific handlers (Upbit, OKX, etc.)
- **database/**: Redis and user database management
- **jobs/**: Celery tasks for grid trading
- **websocket/**: Real-time price feeds
- **routes/**: FastAPI endpoints
- **monitoring/**: Order monitoring and tracking

### Process Management

**HYPERRSI**: Uses Celery for background tasks
- Broker/Backend: Redis (DB 1 for Celery, DB 0 for app data)
- Workers handle: data collection, order execution, WebSocket management
- macOS compatibility: Sets `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`

**GRID**: Uses multiprocessing
- Platform-specific start method: `spawn` (macOS/Windows), `fork` (Linux)
- Graceful shutdown with signal handlers
- Worker lifecycle managed by `worker_manager.py`

## Development Commands

### Dependencies

```bash
# Install all dependencies
pip install -r requirements.txt

# Strategy-specific (if different)
pip install -r HYPERRSI/requirements.txt
```

### Testing

```bash
# Run specific test files (from project root)
python test_telegram_integration_light.py
python test_logging_integration.py

# Strategy-specific tests
cd HYPERRSI && python src/api/routes/okx_test.py
cd GRID && python jobs/celery_test.py
```

### Database Management

```bash
# HYPERRSI database initialization
cd HYPERRSI
python -c "from HYPERRSI.src.core.database import init_db; import asyncio; asyncio.run(init_db())"

# GRID database initialization
cd GRID
python -c "from GRID.infra.database import initialize_database; initialize_database()"
```

### Redis Operations

```bash
# Check Redis connection
redis-cli ping

# Monitor Redis commands (useful for debugging)
redis-cli monitor

# Clear specific DB
redis-cli -n 0 FLUSHDB  # App data
redis-cli -n 1 FLUSHDB  # Celery data
```

## Key Implementation Details

### WebSocket Management

Both strategies use WebSockets for real-time data:
- HYPERRSI: `src/tasks/websocket_tasks.py` (Celery-managed)
- GRID: `websocket/okx_ws.py` (multiprocessing-managed)

**Connection patterns**:
- Automatic reconnection on disconnect
- Heartbeat/ping intervals: 30s (configurable)
- Platform-specific handling for macOS fork safety

### Error Handling

**Global exception handling**:
- HYPERRSI: FastAPI global exception handler in `main.py`
- Logging with user context extraction from headers/params
- Error tracking: `src/core/error_handler.py`

**Retry logic**:
- Shared utility: `shared/utils/retry.py`
- Configurable retry count and backoff strategy
- Used for API calls and critical operations

### Trading Execution Flow

**HYPERRSI** (RSI + Trend Strategy):
1. Data collection via Celery tasks
2. Signal generation based on RSI and trend indicators
3. Order execution through trading service
4. Position management and monitoring

**GRID** (Grid Trading Strategy):
1. Grid level calculation based on price range
2. Order placement at each grid level
3. WebSocket monitoring for fills
4. Automatic rebalancing and profit-taking

## Troubleshooting

### Import Errors

If you see `ModuleNotFoundError`:
1. **First try**: Run `pip install -e .` from project root (one-time setup)
2. **Or verify**: main.py files have auto-configuration code at the top
3. Check imports use absolute paths (GRID.*, HYPERRSI.*, shared.*)
4. Ensure you're running from correct directory

### Celery Issues (HYPERRSI)

```bash
# Check running workers
celery -A HYPERRSI.src.tasks.trading_tasks inspect active

# Stop all workers cleanly
cd HYPERRSI && ./stop_celery_worker.sh

# Restart workers
cd HYPERRSI && ./start_celery_worker.sh
```

### Redis Connection Issues

```bash
# Verify Redis is running
redis-cli ping

# Check connection from Python
python -c "from shared.config import get_settings; import redis; r = redis.from_url(get_settings().REDIS_URL); print(r.ping())"
```

### macOS Fork Safety Warnings

Set environment variable before starting processes:
```bash
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
```

This is already configured in `HYPERRSI/start_celery_worker.sh`.
