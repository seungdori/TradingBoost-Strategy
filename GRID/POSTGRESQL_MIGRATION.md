# GRID PostgreSQL Migration Guide

GRID 전략의 데이터베이스를 SQLite에서 PostgreSQL로 통합하는 가이드입니다.

## 변경 사항 요약

### Before (기존)
```
GRID/
├── database/
│   ├── database.py        # SQLite (aiosqlite) - entry/tp/sl 테이블
│   ├── user_database.py   # SQLite (aiosqlite) - users, jobs 등
│   └── redis_database.py  # Redis - 실시간 거래 데이터
```

### After (마이그레이션 후)
```
GRID/
├── models/                # PostgreSQL 모델
│   ├── base.py
│   └── user.py           # User, Job, TelegramID, Blacklist, Whitelist
├── infra/
│   └── database_pg.py    # PostgreSQL 연결 관리
└── database/
    └── redis_database.py  # Redis (유지) - 실시간 거래 데이터
```

### 데이터 저장소 역할

**PostgreSQL**:
- 사용자 정보 (credentials, trading settings)
- Job 정보 (Celery task tracking)
- Blacklist/Whitelist (symbol filtering)
- Telegram ID 매핑

**Redis** (유지):
- 실시간 거래 데이터
- Grid 상태 (active_grid, order_placed)
- Position 정보
- Take profit orders
- 캐시 데이터

## 마이그레이션 단계

### 1. 환경 설정 확인

`.env` 파일에 PostgreSQL 설정이 있는지 확인:

```bash
# PostgreSQL 설정
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/tradingboost

# 또는 개별 설정
DB_USER=your_username
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432
DB_NAME=tradingboost
```

### 2. PostgreSQL 테이블 생성

```bash
cd GRID
python scripts/init_db.py
```

**생성되는 테이블**:
- `grid_users` - 사용자 정보
- `grid_telegram_ids` - Telegram ID 매핑
- `grid_jobs` - Celery job 추적
- `grid_blacklist` - 심볼 블랙리스트
- `grid_whitelist` - 심볼 화이트리스트

### 3. 기존 SQLite 데이터 마이그레이션

**⚠️ 주의**: 마이그레이션 전에 백업을 권장합니다!

```bash
# SQLite 백업
cp *.db backups/

# 마이그레이션 실행
cd GRID
python scripts/migrate_sqlite_to_pg.py
```

**마이그레이션 대상**:
- `okx_users.db` → PostgreSQL
- `binance_users.db` → PostgreSQL
- `upbit_users.db` → PostgreSQL
- `bitget_users.db` → PostgreSQL
- 기타 exchange_users.db 파일들

### 4. 데이터 검증

PostgreSQL에 데이터가 올바르게 이동되었는지 확인:

```bash
# PostgreSQL에 접속
psql -U your_username -d tradingboost

# 데이터 확인
SELECT COUNT(*) FROM grid_users;
SELECT COUNT(*) FROM grid_jobs;
SELECT COUNT(*) FROM grid_telegram_ids;
SELECT COUNT(*) FROM grid_blacklist;
SELECT COUNT(*) FROM grid_whitelist;

# 특정 exchange 확인
SELECT * FROM grid_users WHERE exchange_name = 'okx' LIMIT 5;
```

## 새로운 Repository 사용법

마이그레이션 후 PostgreSQL을 사용하는 새로운 repository를 사용할 수 있습니다:

```python
from GRID.infra.database_pg import get_grid_db
from GRID.repositories import UserRepository, JobRepository, SymbolListRepository

# 사용 예시
async def get_user_example():
    async with get_grid_db() as session:
        user_repo = UserRepository(session)

        # 사용자 조회
        user = await user_repo.get_by_id(user_id=1, exchange_name="okx")

        # 실행 중인 사용자 조회
        running_users = await user_repo.get_running_users(exchange_name="okx")

        # 사용자 업데이트
        await user_repo.update_running_status(
            user_id=1,
            exchange_name="okx",
            is_running=True
        )

async def manage_jobs():
    async with get_grid_db() as session:
        job_repo = JobRepository(session)

        # Job 저장
        await job_repo.save_job(
            user_id=1,
            exchange_name="okx",
            job_id="task-123",
            status="running"
        )

        # Job 상태 조회
        status, job_id = await job_repo.get_job_status(
            user_id=1,
            exchange_name="okx"
        )

async def manage_symbols():
    async with get_grid_db() as session:
        symbol_repo = SymbolListRepository(session)

        # Blacklist에 추가
        await symbol_repo.add_to_blacklist(
            user_id=1,
            exchange_name="okx",
            symbol="BTC-USDT-SWAP"
        )

        # Whitelist 조회
        symbols = await symbol_repo.get_whitelist(
            user_id=1,
            exchange_name="okx"
        )
```

## Redis는 그대로 유지

Redis는 실시간 데이터용으로 계속 사용됩니다:

```python
from GRID.database import redis_database

# Redis 사용 (기존과 동일)
async def redis_operations():
    # Grid 상태 조회
    active_grid = await redis_database.get_active_grid(
        redis, exchange_name, user_id, symbol
    )

    # Grid 레벨 업데이트
    await redis_database.update_active_grid(
        redis, exchange_name, user_id, symbol, grid_level,
        entry_price=price, position_size=size
    )

    # Take profit orders 업데이트
    await redis_database.update_take_profit_orders_info(
        redis, exchange_name, user_id, symbol, level,
        order_id=order_id, new_price=price, quantity=qty, active=True
    )
```

## 장점

### 1. 통합된 데이터베이스
- HYPERRSI와 GRID가 동일한 PostgreSQL 사용
- 일관된 데이터 관리 및 백업

### 2. 확장성
- SQLite의 동시성 제한 해결
- 대용량 데이터 처리 가능
- 복잡한 쿼리 및 인덱싱 최적화

### 3. 트랜잭션 안정성
- ACID 보장
- Foreign key constraints
- Cascade delete 지원

### 4. 운영 편의성
- 표준 SQL 도구 사용 가능
- 백업 및 복구 용이
- 모니터링 및 분석 도구 활용

## 롤백 방법

마이그레이션 후 문제가 발생하면 SQLite로 롤백 가능:

```bash
# 백업된 SQLite 파일 복원
cp backups/*.db .

# 기존 코드로 되돌리기 (필요시)
git checkout HEAD -- GRID/database/user_database.py
git checkout HEAD -- GRID/database/database.py
```

## 트러블슈팅

### PostgreSQL 연결 오류
```bash
# PostgreSQL 서비스 확인
pg_ctl status

# PostgreSQL 시작
pg_ctl start

# 연결 테스트
psql -U your_username -d tradingboost -c "SELECT 1;"
```

### 마이그레이션 실패
```bash
# 로그 확인
tail -f logs/grid_migration.log

# PostgreSQL 테이블 초기화
python scripts/init_db.py

# 마이그레이션 재실행
python scripts/migrate_sqlite_to_pg.py
```

### 데이터 불일치
```bash
# SQLite 데이터 확인
sqlite3 okx_users.db "SELECT COUNT(*) FROM users;"

# PostgreSQL 데이터 확인
psql -U your_username -d tradingboost -c "SELECT COUNT(*) FROM grid_users WHERE exchange_name='okx';"
```

## 다음 단계

마이그레이션 완료 후:

1. ✅ 데이터 검증 완료
2. ✅ 애플리케이션 테스트
3. ✅ SQLite 파일 백업 보관
4. ⚠️ SQLite 코드 제거 (선택사항, 안정화 후)

## 문의

마이그레이션 관련 문제가 있으면 로그를 확인하거나 이슈를 등록해주세요.
