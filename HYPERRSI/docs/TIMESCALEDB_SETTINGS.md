# TimescaleDB 사용자 설정 저장소 구현

## 📋 개요

사용자 설정을 **Redis** (빠른 조회)와 **TimescaleDB** (영구 저장) 양쪽에 저장하는 이중 저장소 시스템입니다.

## 🏗️ 아키텍처

### 데이터 흐름

```
사용자 등록 (/setapi)
    ↓
┌─────────────────────────────────┐
│   register.py                   │
│   (src/bot/command/register.py) │
└─────────────────────────────────┘
    ↓                    ↓
┌──────────┐      ┌──────────────┐
│  Redis   │      │ TimescaleDB  │
│  (빠름)   │      │  (영구 저장)  │
└──────────┘      └──────────────┘
```

### 저장 위치 비교

| 데이터 유형 | Redis | TimescaleDB | 용도 |
|------------|-------|-------------|------|
| **API 키** | ✅ `user:{okx_uid}:api:keys` | ✅ `okx_api_info` 테이블 | 인증 |
| **Preferences** | ✅ `user:{okx_uid}:preferences` | ✅ `user_settings` (type='preferences') | 기본 설정 |
| **Params** | ✅ `user:{okx_uid}:settings` | ✅ `user_settings` (type='params') | 트레이딩 파라미터 |
| **Dual Side** | ✅ `user:{okx_uid}:dual_side` | ✅ `user_settings` (type='dual_side') | 양방향 매매 설정 |
| **거래 내역** | ❌ | ✅ `trades` 테이블 | 히스토리 |
| **가격 데이터** | ❌ | ✅ `ohlcv_*` 테이블 | 시계열 분석 |

## 📊 데이터베이스 스키마

### `user_settings` 테이블

```sql
CREATE TABLE user_settings (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,           -- FK to app_users
    okx_uid TEXT NOT NULL,            -- OKX 사용자 ID
    telegram_id TEXT,                 -- Telegram 사용자 ID

    setting_type TEXT NOT NULL,       -- 'preferences', 'params', 'dual_side'
    settings JSONB NOT NULL,          -- 설정 데이터 (유연한 구조)

    version INTEGER NOT NULL,         -- 버전 관리
    is_active BOOLEAN NOT NULL,       -- 활성 상태

    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ            -- Soft delete
);
```

### 인덱스

- `idx_user_settings_user_id`: 사용자 ID 조회
- `idx_user_settings_okx_uid`: OKX UID 조회
- `idx_user_settings_telegram_id`: Telegram ID 조회
- `idx_user_settings_type`: 설정 타입별 조회
- `idx_user_settings_jsonb`: JSONB 내부 검색 (GIN)
- `idx_user_settings_unique_active`: 사용자당 타입별 하나의 활성 설정만 허용

## 🔧 사용 방법

### 1. 신규 사용자 등록

텔레그램 봇에서 `/setapi` 실행 시:

```python
# HYPERRSI/src/bot/command/register.py

# 1. Redis에 저장
await redis.hmset(f"user:{okx_uid}:api:keys", {...})
await redis.hmset(f"user:{okx_uid}:preferences", {...})
await redis.set(f"user:{okx_uid}:settings", json.dumps(...))
await redis.hmset(f"user:{okx_uid}:dual_side", {...})

# 2. TimescaleDB에도 저장
await TimescaleUserService.ensure_user_exists(okx_uid, telegram_id, ...)
await TimescaleUserService.upsert_api_credentials(okx_uid, api_key, ...)
await TimescaleUserService.save_all_user_settings(okx_uid, preferences, params, dual_side)
```

### 2. 설정 조회

```python
from HYPERRSI.src.services.timescale_service import TimescaleUserService

# 모든 설정 조회
settings = await TimescaleUserService.get_user_settings("587662504768345929")

# 특정 타입만 조회
params = await TimescaleUserService.get_setting_by_type("587662504768345929", "params")
dual_side = await TimescaleUserService.get_setting_by_type("587662504768345929", "dual_side")
```

### 3. 설정 업데이트

```python
# 개별 설정 업데이트
await TimescaleUserService.upsert_user_settings(
    user_id="user-uuid",
    okx_uid="587662504768345929",
    telegram_id="1709556958",
    setting_type="params",
    settings={"leverage": 10, "rsi_length": 14, ...}
)

# 여러 설정 동시 업데이트
await TimescaleUserService.save_all_user_settings(
    identifier="587662504768345929",
    preferences={"timeframe": "5m", "symbol": "ETH-USDT-SWAP"},
    params={...},
    dual_side={...}
)
```

## 🔄 Redis → TimescaleDB 동기화

### 기존 Redis 데이터 마이그레이션

```bash
cd /Users/seunghyun/TradingBoost-Strategy/HYPERRSI

# 미리보기 (실제 저장 안 함)
python scripts/sync_redis_to_timescale.py --dry-run

# 모든 사용자 동기화
python scripts/sync_redis_to_timescale.py

# 특정 사용자만 동기화
python scripts/sync_redis_to_timescale.py --okx-uid 587662504768345929
```

## 🎯 조회 우선순위

### Primary: Redis (빠른 조회)

```python
# 실시간 조회는 Redis 사용
redis = await get_redis_client()
api_keys = await redis.hgetall(f"user:{okx_uid}:api:keys")
```

### Fallback: TimescaleDB

```python
# Redis 실패 시 TimescaleDB에서 조회
if not api_keys:
    api_keys = await TimescaleUserService.get_api_keys(okx_uid)
```

### 주기적 동기화

- 사용자 등록/업데이트 시 자동으로 양쪽에 저장
- 필요 시 동기화 스크립트로 일괄 동기화

## 📝 설정 타입별 저장 내용

### preferences (기본 설정)

```json
{
  "timeframe": "1m",
  "symbol": "BTC-USDT-SWAP"
}
```

### params (트레이딩 파라미터)

```json
{
  "btc_investment": 20,
  "leverage": 10,
  "direction": "롱숏",
  "rsi_length": 14,
  "rsi_oversold": 30,
  "rsi_overbought": 70,
  "tp1_value": 2.0,
  "tp2_value": 3.0,
  "tp3_value": 4.0,
  "sl_value": 5.0,
  "use_break_even": true,
  "pyramiding_limit": 4,
  "...": "총 50개 파라미터"
}
```

### dual_side (양방향 매매)

```json
{
  "use_dual_side_entry": false,
  "dual_side_entry_trigger": 3,
  "dual_side_entry_ratio_type": "percent_of_position",
  "dual_side_entry_ratio_value": 30,
  "...": "총 13개 파라미터"
}
```

## 🔍 검증 및 확인

### TimescaleDB 데이터 확인

```python
import asyncio
from HYPERRSI.src.services.timescale_service import TimescaleUserService

async def verify():
    okx_uid = "587662504768345929"

    # 사용자 정보
    user_record = await TimescaleUserService.fetch_user(okx_uid)
    print(f"User: {user_record.user}")
    print(f"API: {user_record.api}")

    # 설정 확인
    settings = await TimescaleUserService.get_user_settings(okx_uid)
    for setting in settings:
        print(f"{setting['setting_type']}: {len(setting['settings'])} keys")

asyncio.run(verify())
```

### Redis 데이터 확인

```bash
# API 키 확인
redis-cli -n 0 HGETALL "user:587662504768345929:api:keys"

# 설정 확인
redis-cli -n 0 HGETALL "user:587662504768345929:preferences"
redis-cli -n 0 GET "user:587662504768345929:settings"
redis-cli -n 0 HGETALL "user:587662504768345929:dual_side"
```

## 📂 관련 파일

### 마이그레이션

- `HYPERRSI/migrations/001_create_user_settings_tables.sql` - 테이블 생성 SQL
- `HYPERRSI/migrations/README.md` - 마이그레이션 가이드

### 서비스 레이어

- `HYPERRSI/src/services/timescale_service.py` - TimescaleDB 서비스
  - `get_user_settings()` - 설정 조회
  - `upsert_user_settings()` - 설정 업서트
  - `save_all_user_settings()` - 일괄 저장
  - `get_setting_by_type()` - 타입별 조회

### 등록 로직

- `HYPERRSI/src/bot/command/register.py` - 사용자 등록 및 API 키 설정
  - Redis + TimescaleDB 이중 저장
  - OKX UID 매핑 관리

### 동기화 스크립트

- `HYPERRSI/scripts/sync_redis_to_timescale.py` - Redis → TimescaleDB 동기화

## ⚠️ 주의사항

1. **OKX UID 매핑**: Telegram ID와 OKX UID를 정확히 매핑해야 함
2. **설정 타입**: 'preferences', 'params', 'dual_side' 3가지만 사용
3. **JSONB 구조**: settings 필드는 JSONB로 유연하게 저장
4. **버전 관리**: 설정 업데이트 시 자동으로 version 증가
5. **Soft Delete**: deleted_at으로 소프트 삭제 지원

## 🚀 향후 개선 사항

- [ ] 설정 변경 이력 추적 (version을 이용한 audit trail)
- [ ] Redis 캐시 무효화 전략 개선
- [ ] 설정 백업 및 복구 기능
- [ ] 설정 import/export 기능
- [ ] 사용자별 설정 템플릿 관리

## 📊 성능 최적화

### 인덱스 활용

- OKX UID, Telegram ID로 빠른 조회
- JSONB GIN 인덱스로 설정 내부 검색
- 복합 유니크 인덱스로 중복 방지

### 캐싱 전략

- Redis: 실시간 조회 (< 1ms)
- TimescaleDB: 영구 저장 및 복잡한 쿼리 (< 50ms)

### 연결 풀링

```python
# TimescaleDB 연결 풀
TimescalePool.get_pool()  # 지연 초기화
max_size=max(settings.DB_POOL_SIZE, 5)  # 기본 5개
```

## 🎉 완료!

이제 사용자 설정이 Redis와 TimescaleDB 양쪽에 안전하게 저장됩니다!

- ✅ Redis: 빠른 조회
- ✅ TimescaleDB: 영구 저장
- ✅ 자동 동기화
- ✅ 버전 관리
- ✅ UID 매핑
