# TradingBoost-Strategy Documentation Index

**Version**: 2.0
**Last Updated**: 2025-11-26

---

## Quick Navigation

| Category | Document | Description |
|----------|----------|-------------|
| **Getting Started** | [README.md](../README.md) | 프로젝트 소개 및 빠른 시작 가이드 |
| **Architecture** | [ARCHITECTURE.md](../ARCHITECTURE.md) | 전체 시스템 아키텍처 |
| **Claude Code** | [CLAUDE.md](../CLAUDE.md) | AI 코딩 어시스턴트 가이드 |

---

## Project Structure

```
TradingBoost-Strategy/
├── HYPERRSI/          # RSI + Trend 기반 자동 매매 전략 (Port 8000)
├── GRID/              # 그리드 트레이딩 전략 (Port 8012)
├── BACKTEST/          # 백테스팅 및 최적화 시스템 (Port 8013)
├── shared/            # 공통 인프라 모듈
└── docs/              # 문서화
```

---

## 1. Core Documentation

### 1.1 Project Root

| File | Description |
|------|-------------|
| [README.md](../README.md) | 프로젝트 개요, 설치 가이드, 빠른 시작 |
| [CLAUDE.md](../CLAUDE.md) | Claude Code 가이드: Import 규칙, 실행 방법, 트러블슈팅 |
| [ARCHITECTURE.md](../ARCHITECTURE.md) | 전체 시스템 아키텍처 및 데이터 흐름 |

### 1.2 Strategy Documentation

#### HYPERRSI Strategy
| File | Description |
|------|-------------|
| [HYPERRSI/HYPERRSI_ARCHITECTURE.md](../HYPERRSI/HYPERRSI_ARCHITECTURE.md) | 상세 아키텍처 문서 |
| [HYPERRSI/README.md](../HYPERRSI/README.md) | HYPERRSI 전략 개요 |

**Key Components:**
- **FastAPI Server**: Port 8000
- **Celery Workers**: 백그라운드 태스크 처리
- **Features**: RSI 지표, 트렌드 분석, TP/SL 관리, 텔레그램 봇

#### GRID Strategy
| File | Description |
|------|-------------|
| [GRID/README_DATABASE.md](../GRID/README_DATABASE.md) | 데이터베이스 아키텍처 |
| [GRID/IMPORT_GUIDE.md](../GRID/IMPORT_GUIDE.md) | Import 규칙 가이드 |
| [GRID/POSTGRESQL_MIGRATION.md](../GRID/POSTGRESQL_MIGRATION.md) | PostgreSQL 마이그레이션 가이드 |

**Key Components:**
- **FastAPI Server**: Port 8012
- **Multiprocessing Workers**: 병렬 처리
- **Features**: 그리드 레벨 계산, 자동 재균형, 수익 실현

#### BACKTEST System
| File | Description |
|------|-------------|
| [BACKTEST/README.md](../BACKTEST/README.md) | 백테스팅 시스템 가이드 |
| [BACKTEST_SYSTEM_DESIGN.md](../BACKTEST_SYSTEM_DESIGN.md) | 시스템 설계 문서 |
| [BACKTEST_DATA_ANALYSIS.md](../BACKTEST_DATA_ANALYSIS.md) | 데이터 분석 문서 |

**Key Components:**
- **FastAPI Server**: Port 8013
- **TimescaleDB**: 시계열 데이터 저장
- **Features**: 전략 시뮬레이션, 파라미터 최적화, 성능 지표

---

## 2. Infrastructure Documentation

### 2.1 Shared Modules

| Directory | Purpose |
|-----------|---------|
| `shared/config.py` | 중앙화된 설정 관리 (pydantic-settings) |
| `shared/database/` | DB 세션, Redis 연결, 커넥션 풀링 |
| `shared/exchange_apis/` | CCXT 기반 거래소 API 래퍼 |
| `shared/cache/` | 캐싱 유틸리티 |
| `shared/utils/` | 공통 유틸리티 함수 |
| `shared/constants.py` | 상수 정의 |
| `shared/indicators/` | 기술적 지표 계산 모듈 |

### 2.2 Database & Caching

| File | Description |
|------|-------------|
| [docs/REDIS_PATTERNS.md](./REDIS_PATTERNS.md) | Redis 사용 패턴 및 베스트 프랙티스 |
| [GRID/README_DATABASE.md](../GRID/README_DATABASE.md) | PostgreSQL + Redis 아키텍처 |

**Database Stack:**
- **PostgreSQL**: 영구 데이터 저장 (사용자, 거래 기록)
- **TimescaleDB**: 시계열 데이터 (캔들, 백테스트 결과)
- **Redis**: 실시간 캐싱 (포지션, 주문 상태, 세션)

### 2.3 Redis Usage

**TTL Constants:**
```python
RedisTTL.USER_DATA        # 30 days
RedisTTL.USER_SESSION     # 1 day
RedisTTL.PRICE_DATA       # 1 hour
RedisTTL.ORDER_DATA       # 7 days
RedisTTL.POSITION_DATA    # 30 days
RedisTTL.CACHE_SHORT      # 5 minutes
RedisTTL.CACHE_MEDIUM     # 30 minutes
RedisTTL.CACHE_LONG       # 2 hours
```

---

## 3. API Documentation

### 3.1 HYPERRSI API Endpoints

| Endpoint Category | Base Path | Description |
|-------------------|-----------|-------------|
| Trading | `/api/trading/` | 트레이딩 시작/중지 |
| Order | `/api/order/` | 주문 관리 |
| Position | `/api/position/` | 포지션 조회/관리 |
| Account | `/api/account/` | 계정 정보 |
| Settings | `/api/settings/` | 사용자 설정 |
| Stats | `/api/stats/` | 거래 통계 |
| Status | `/api/status/` | 시스템 상태 |
| Telegram | `/api/telegram/` | 텔레그램 연동 |

### 3.2 GRID API Endpoints

| Endpoint Category | Base Path | Description |
|-------------------|-----------|-------------|
| User | `/api/user/` | 사용자 관리 |
| Trading | `/api/trading/` | 그리드 트레이딩 제어 |
| Settings | `/api/settings/` | 그리드 설정 |
| Blacklist | `/api/blacklist/` | 심볼 블랙리스트 |

### 3.3 BACKTEST API Endpoints

| Endpoint Category | Base Path | Description |
|-------------------|-----------|-------------|
| Backtest | `/backtest/` | 백테스트 실행/결과 조회 |
| Candles | `/candles/` | 캔들 데이터 조회 |

---

## 4. Development Guide

### 4.1 Environment Setup

```bash
# 1. Clone repository
git clone <repository-url>
cd TradingBoost-Strategy

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # macOS/Linux

# 3. Install dependencies (required)
pip install -e .

# 4. Configure environment
cp HYPERRSI/.env.example .env
# Edit .env with your API keys
```

### 4.2 Import Rules

**Monorepo Absolute Imports:**
```python
# HYPERRSI
from HYPERRSI.src.api.routes import trading
from HYPERRSI.src.services import redis_service

# GRID
from GRID.strategies import strategy
from GRID.services import bot_state_service

# BACKTEST
from BACKTEST.engine import BacktestEngine
from BACKTEST.data import TimescaleProvider

# Shared
from shared.config import get_settings
from shared.database.redis import get_redis
```

### 4.3 Running Services

```bash
# HYPERRSI (Port 8000)
cd HYPERRSI
python main.py
./start_celery_worker.sh  # Celery workers

# GRID (Port 8012)
cd GRID
python main.py --port 8012

# BACKTEST (Port 8013)
cd BACKTEST
python main.py
```

### 4.4 Testing

```bash
# Run specific tests
python test_telegram_integration_light.py
python test_logging_integration.py

# HYPERRSI tests
cd HYPERRSI && python src/api/routes/okx_test.py

# BACKTEST tests
cd BACKTEST && pytest tests/
```

---

## 5. Architecture Deep Dive

### 5.1 Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| Web Framework | FastAPI 0.115+ | Async REST API |
| Task Queue | Celery 5.4+ | Background processing |
| Cache/Broker | Redis 5.2+ | Caching, message broker |
| Database | PostgreSQL + TimescaleDB | Persistent storage |
| Exchange API | CCXT 4.4+ | Multi-exchange support |
| Bot Framework | aiogram 3.17+ | Telegram integration |
| Data Processing | pandas 2.2+, numpy 2.2+ | Indicator calculation |

### 5.2 Architecture Patterns

```
┌─────────────────────────────────────────────────────────┐
│                    API Layer (FastAPI)                   │
│  - Route Handlers, Dependency Injection, Middleware      │
└─────────────────────────────────────────────────────────┘
                           │
┌─────────────────────────────────────────────────────────┐
│                   Service Layer                          │
│  - Business Logic, Redis Service, Trading Service        │
└─────────────────────────────────────────────────────────┘
                           │
┌─────────────────────────────────────────────────────────┐
│                   Trading Layer                          │
│  - Position Manager, Order Manager, TP/SL Calculator     │
└─────────────────────────────────────────────────────────┘
                           │
┌─────────────────────────────────────────────────────────┐
│                   Data Layer                             │
│  - Market Data, Indicators, WebSocket Feeds              │
└─────────────────────────────────────────────────────────┘
                           │
┌─────────────────────────────────────────────────────────┐
│                Infrastructure Layer                       │
│  - Redis, PostgreSQL, TimescaleDB, Celery                │
└─────────────────────────────────────────────────────────┘
```

### 5.3 Key Design Patterns

| Pattern | Usage | Location |
|---------|-------|----------|
| **Facade** | TradingService coordinates all trading ops | `src/trading/trading_service.py` |
| **Singleton** | Redis service, DB connections | `src/services/redis_service.py` |
| **Factory** | Exchange client creation | `src/api/dependencies.py` |
| **Repository** | Data access abstraction | `repositories/` |
| **Context Manager** | Resource cleanup | Throughout codebase |
| **Connection Pool** | Exchange client reuse | `src/api/dependencies.py` |

---

## 6. Deployment & Operations

### 6.1 Process Management

| Strategy | Tool | Config |
|----------|------|--------|
| HYPERRSI | Celery + FastAPI | `start_celery_worker.sh` |
| GRID | Multiprocessing + FastAPI | `worker_manager.py` |
| BACKTEST | FastAPI | `main.py` |

### 6.2 Health Checks

```bash
# Health endpoints
curl http://localhost:8000/health
curl http://localhost:8000/health/redis
curl http://localhost:8000/health/redis/pool
```

### 6.3 Monitoring

**Redis Monitoring:**
```bash
redis-cli INFO memory
redis-cli MONITOR
redis-cli DBSIZE
```

**Database Monitoring:**
```sql
-- Active users
SELECT exchange_name, COUNT(*) FROM grid_users WHERE is_running = TRUE GROUP BY exchange_name;

-- Job status
SELECT status, COUNT(*) FROM grid_jobs GROUP BY status;
```

---

## 7. Troubleshooting

### 7.1 Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| `ModuleNotFoundError` | PYTHONPATH not set | Run `pip install -e .` |
| Import errors | Relative imports | Use absolute imports |
| Redis connection | Redis not running | `redis-cli ping` |
| Celery issues | Workers not started | `./start_celery_worker.sh` |
| macOS fork warnings | Fork safety | Set `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` |

### 7.2 Debug Commands

```bash
# Check Redis
redis-cli ping

# Check Celery workers
celery -A HYPERRSI.src.tasks.trading_tasks inspect active

# Check database
psql -h localhost -U your_user -d tradingboost -c "SELECT 1"
```

---

## 8. Document Changelog

| Version | Date | Changes |
|---------|------|---------|
| 2.0 | 2025-11-26 | Complete documentation restructure, added INDEX.md |
| 1.5 | 2025-10-19 | Redis patterns documentation update |
| 1.0 | 2025-01-01 | Initial documentation |

---

## 9. Related Documents

### External Resources
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Celery Documentation](https://docs.celeryq.dev/)
- [CCXT Documentation](https://docs.ccxt.com/)
- [Redis Documentation](https://redis.io/documentation)
- [TimescaleDB Documentation](https://docs.timescale.com/)

### Internal Documents
- [Import Guide](../GRID/IMPORT_GUIDE.md)
- [Redis Patterns](./REDIS_PATTERNS.md)
- [Database Architecture](../GRID/README_DATABASE.md)
- [HYPERRSI Architecture](../HYPERRSI/HYPERRSI_ARCHITECTURE.md)
- [Backtest System Design](../BACKTEST_SYSTEM_DESIGN.md)

---

**Note**: This index is auto-generated and should be updated when new documentation is added.
