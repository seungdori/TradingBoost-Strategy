# TimescaleDB 마이그레이션 가이드

## 📋 개요

이 디렉토리에는 TimescaleDB 데이터베이스 마이그레이션 스크립트가 포함되어 있습니다.

## 🚀 마이그레이션 실행

### 1. 마이그레이션 적용

```bash
# TimescaleDB 연결 정보 확인
cat ../.env | grep TIMESCALE

# psql로 마이그레이션 실행
psql -h <TIMESCALE_HOST> -U <TIMESCALE_USER> -d <TIMESCALE_DATABASE> -f 001_create_user_settings_tables.sql
```

### 2. 마이그레이션 확인

```bash
# Python으로 확인
cd /Users/seunghyun/TradingBoost-Strategy/HYPERRSI
python << 'EOF'
import asyncio
from src.services.timescale_service import TimescaleUserService

async def check():
    # 테이블 존재 확인
    pool = await TimescaleUserService._pool_class.get_pool()
    async with pool.acquire() as conn:
        result = await conn.fetchval("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_name = 'user_settings'
        """)
        print(f"✅ user_settings 테이블 존재: {result == 1}")

        # 함수 존재 확인
        result = await conn.fetchval("""
            SELECT COUNT(*) FROM pg_proc
            WHERE proname IN ('get_user_settings', 'upsert_user_settings')
        """)
        print(f"✅ Helper 함수 존재: {result >= 2}")

asyncio.run(check())
EOF
```

## 📊 생성되는 테이블

### `user_settings` 테이블

사용자의 모든 트레이딩 설정을 JSONB 형식으로 저장합니다.

**컬럼 구조:**
- `id`: UUID (Primary Key)
- `user_id`: UUID (Foreign Key → app_users)
- `okx_uid`: TEXT (OKX 사용자 ID)
- `telegram_id`: TEXT (Telegram 사용자 ID)
- `setting_type`: TEXT ('preferences', 'params', 'dual_side')
- `settings`: JSONB (설정 데이터)
- `version`: INTEGER (버전 관리)
- `is_active`: BOOLEAN (활성 상태)
- `created_at`: TIMESTAMPTZ
- `updated_at`: TIMESTAMPTZ
- `deleted_at`: TIMESTAMPTZ (Soft Delete)

**인덱스:**
- `idx_user_settings_user_id`: 사용자 ID 조회 최적화
- `idx_user_settings_okx_uid`: OKX UID 조회 최적화
- `idx_user_settings_telegram_id`: Telegram ID 조회 최적화
- `idx_user_settings_type`: 설정 타입별 조회 최적화
- `idx_user_settings_jsonb`: JSONB 내부 검색 최적화 (GIN)
- `idx_user_settings_unique_active`: 사용자당 타입별 하나의 활성 설정만 허용

## 🔧 Helper 함수

### `get_user_settings(identifier, setting_type)`

사용자 설정을 조회합니다.

```sql
-- 모든 설정 조회
SELECT * FROM get_user_settings('587662504768345929', NULL);

-- preferences만 조회
SELECT * FROM get_user_settings('587662504768345929', 'preferences');
```

### `upsert_user_settings(user_id, okx_uid, telegram_id, setting_type, settings)`

사용자 설정을 생성하거나 업데이트합니다.

```sql
-- 설정 저장
SELECT upsert_user_settings(
    'user-uuid-here'::uuid,
    '587662504768345929',
    '1709556958',
    'preferences',
    '{"timeframe": "1m", "symbol": "BTC-USDT-SWAP"}'::jsonb
);
```

## 🔄 Redis → TimescaleDB 동기화

기존 Redis 데이터를 TimescaleDB로 마이그레이션:

```bash
cd /Users/seunghyun/TradingBoost-Strategy/HYPERRSI

# 미리보기 (실제 저장 안 함)
python scripts/sync_redis_to_timescale.py --dry-run

# 모든 사용자 동기화
python scripts/sync_redis_to_timescale.py

# 특정 사용자만 동기화
python scripts/sync_redis_to_timescale.py --okx-uid 587662504768345929
```

## 📝 데이터 흐름

### 신규 사용자 등록 시

```
텔레그램 /setapi 명령
    ↓
register.py
    ↓
    ├─→ Redis 저장
    │   - user:{okx_uid}:api:keys
    │   - user:{okx_uid}:preferences
    │   - user:{okx_uid}:settings
    │   - user:{okx_uid}:dual_side
    │
    └─→ TimescaleDB 저장
        - app_users (사용자 기본 정보)
        - okx_api_info (API 키)
        - user_settings (모든 설정)
```

### 설정 조회 우선순위

1. **Primary**: Redis (빠른 조회)
2. **Fallback**: TimescaleDB (Redis 실패 시)
3. **Sync**: 주기적으로 Redis ↔ TimescaleDB 동기화

## 🗂️ 마이그레이션 목록

| 파일 | 설명 | 상태 |
|------|------|------|
| `001_create_user_settings_tables.sql` | user_settings 테이블 및 헬퍼 함수 생성 | ✅ Ready |

## ⚠️ 주의사항

1. **백업 필수**: 마이그레이션 전 데이터베이스 백업
2. **테스트 환경**: 프로덕션 적용 전 테스트 환경에서 검증
3. **동시성**: user_settings 테이블은 사용자당 타입별로 하나의 활성 설정만 허용
4. **Soft Delete**: deleted_at 컬럼으로 소프트 삭제 지원

## 🔍 트러블슈팅

### 마이그레이션 실패 시

```sql
-- 테이블 존재 확인
SELECT tablename FROM pg_tables WHERE tablename = 'user_settings';

-- 인덱스 존재 확인
SELECT indexname FROM pg_indexes WHERE tablename = 'user_settings';

-- 함수 존재 확인
SELECT proname FROM pg_proc WHERE proname LIKE '%user_settings%';
```

### 데이터 동기화 확인

```python
import asyncio
from HYPERRSI.src.services.timescale_service import TimescaleUserService

async def verify():
    # Redis 사용자 확인
    from shared.database.redis_helper import get_redis_client
    redis = await get_redis_client()
    keys = await redis.keys("user:*:api:keys")
    print(f"Redis users: {len(keys)}")

    # TimescaleDB 사용자 확인
    settings = await TimescaleUserService.get_user_settings("587662504768345929")
    print(f"TimescaleDB settings: {len(settings)}")

asyncio.run(verify())
```
