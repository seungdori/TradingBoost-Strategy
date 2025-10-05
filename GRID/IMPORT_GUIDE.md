# GRID 모듈 Import 가이드

## 디렉토리 구조

```
GRID/
├── api/              # API 엔트리포인트
├── config/           # 설정 파일
├── core/             # 핵심 기능 (redis, websocket, exceptions)
├── database/         # 데이터베이스 (redis_database, user_database, database)
├── dtos/             # 데이터 전송 객체
├── handlers/         # 거래소별 핸들러
├── infra/            # 인프라스트럭처
├── jobs/             # 백그라운드 작업 (Celery)
├── main/             # 메인 로직
├── monitoring/       # 모니터링
├── repositories/     # 데이터 저장소
├── routes/           # API 라우트
├── services/         # 비즈니스 로직
├── strategies/       # 트레이딩 전략
├── trading/          # 트레이딩 유틸리티
├── utils/            # 유틸리티 함수
└── websocket/        # WebSocket
```

## Import 규칙

### ✅ 올바른 Import 예시

```python
# 전략 모듈
from GRID.strategies import strategy
from GRID.strategies import grid
from GRID.strategies.grid_process import start_grid_main_in_process

# 데이터베이스
from GRID.database import redis_database
from GRID.database import user_database
from GRID.database.redis_database import get_user_key

# 서비스
from GRID.services import bot_state_service
from GRID.services import trading_service

# 라우트
from GRID.routes import auth_route
from GRID.routes.connection_manager import ConnectionManager

# Core
from GRID.core.redis import get_redis_connection
from GRID.core.exceptions import QuitException

# Utils
from GRID.utils.price import round_to_upbit_tick_size
from GRID.utils.validators import parse_bool

# Trading
from GRID.trading.instance import get_exchange_instance
from GRID.trading.shared_state import user_keys

# Jobs
from GRID.jobs.celery_app import app
from GRID.jobs.celery_tasks import run_grid_trading

# DTOs
from GRID.dtos.feature import StartFeatureDto
from GRID.dtos.user import UserDto

# Repositories
from GRID.repositories import user_repository
from GRID.repositories.trading_data_repository import fetch_db_prices

# Handlers
from GRID.handlers.upbit import process_upbit_balance
from GRID.handlers.okx import process_okx_position_data

# Main
from GRID.main import periodic_analysis
from GRID.main.central_schedule import central_schedule_function

# Monitoring
from GRID.monitoring.monitor_tp_orders import monitor_tp_orders_websockets

# WebSocket
from GRID.websocket.okx_ws import okx_ws_function

# Infra
from GRID.infra import bot_state_store
from GRID.infra.database import initialize_database

# API
from GRID.api.apilist import telegram_store

# Version
from GRID.version import __version__
```

### ❌ 잘못된 Import 예시

```python
# 상대 import (GRID 내부에서는 절대 import 사용)
from strategy import some_function  # ❌
import grid  # ❌
from ..database import redis_database  # ❌

# 디렉토리를 직접 import (모듈 파일을 명시해야 함)
import GRID.database  # ❌ - from GRID.database import redis_database
import GRID.strategy  # ❌ - from GRID.strategies import strategy
import GRID.grid  # ❌ - from GRID.strategies import grid

# GRID 없이 import (GRID 외부에서는 가능하지만 내부에서는 절대 경로 사용)
from services import bot_state_service  # ❌ - from GRID.services import bot_state_service
from routes import auth_route  # ❌ - from GRID.routes import auth_route
from dtos.feature import StartFeatureDto  # ❌ - from GRID.dtos.feature import StartFeatureDto
```

## 주요 모듈별 Import 패턴

### 전략 (Strategies)
```python
from GRID.strategies import strategy  # strategy.py 모듈
from GRID.strategies import grid  # grid.py 모듈
from GRID.strategies.grid_process import start_grid_main_in_process
```

### 데이터베이스 (Database)
```python
from GRID.database import redis_database
from GRID.database import user_database
from GRID.database.redis_database import get_redis_connection, save_user
```

### 서비스 (Services)
```python
from GRID.services import bot_state_service
from GRID.services import trading_service
from GRID.services.auth_service import login, signup
```

### Celery 작업 (Jobs)
```python
from GRID.jobs.celery_app import app
from GRID.jobs.celery_tasks import run_grid_trading, cancel_grid_tasks
```

### 트레이딩 (Trading)
```python
from GRID.trading.instance import get_exchange_instance
from GRID.trading.shared_state import user_keys, cancel_state
from GRID.trading.get_minimum_qty import round_to_qty
```

## 문제 해결

### Import 오류가 발생하는 경우

1. **모듈을 찾을 수 없는 경우**
   - `GRID.` 접두사가 있는지 확인
   - 올바른 하위 디렉토리를 사용하는지 확인
   - 예: `strategy` → `GRID.strategies.strategy`

2. **순환 import 오류**
   - 가능한 한 하위 모듈에서 상위 모듈로만 import
   - 필요시 함수 내부에서 import

3. **IDE에서 인식 못하는 경우**
   - 프로젝트 루트가 `/Users/seunghyun/TradingBoost-Strategy`인지 확인
   - Python path 설정 확인
   - IDE 재시작

## 변경 이력

- 2025-10-05: GRID 디렉토리 구조 재정리 및 import 경로 수정
  - 모든 상대 import를 절대 import로 변경
  - 디렉토리별 모듈 분리 완료
