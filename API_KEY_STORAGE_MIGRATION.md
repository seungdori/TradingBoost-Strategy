# API 키 저장소 아키텍처 변경

## 📋 개요

API 키 저장소를 **Redis 단일 저장**에서 **TimescaleDB (primary) + Redis (cache)** 이중 저장소로 전환했습니다.

## 🎯 변경 목적

### 기존 문제점
- **Redis만 사용**: 메모리 기반 캐시로 휘발성 위험
- **데이터 손실 가능**: Redis 장애 시 모든 API 키 손실
- **영구 저장소 미활용**: TimescaleDB가 있지만 사용하지 않음

### 해결 방안
- **TimescaleDB**: Primary storage (영구 저장)
- **Redis**: Cache layer (빠른 조회)
- **Fallback 지원**: TimescaleDB 실패 시 Redis 사용

## 🏗️ 새로운 아키텍처

### 저장 흐름 (Write)

```
사용자 API 키 등록
    ↓
┌─────────────────────────────────┐
│ ApiKeyService.set_user_api_keys │
│ (redis_service.py)              │
└─────────────────────────────────┘
    ↓                    ↓
┌──────────────┐    ┌──────────────┐
│ TimescaleDB  │    │    Redis     │
│ (Primary)    │    │   (Cache)    │
│ 영구 저장     │    │   빠른 조회   │
└──────────────┘    └──────────────┘
```

### 조회 흐름 (Read)

```
API 키 조회 요청
    ↓
┌─────────────────────────────────┐
│ get_user_api_keys               │
│ (dependencies.py)               │
└─────────────────────────────────┘
    ↓
1️⃣ TimescaleDB 조회 (Primary)
    ├─ 성공 → Redis 캐싱 후 반환
    └─ 실패 → 2️⃣ Redis fallback 조회
```

## 📝 변경된 파일

### 1. `HYPERRSI/src/api/dependencies.py`

**함수**: `get_user_api_keys(user_id, raise_on_missing)`

**변경 내용**:
- TimescaleDB 우선 조회 추가
- Redis fallback 로직 추가
- 조회 성공 시 자동 Redis 캐싱

**조회 우선순위**:
```python
# 1️⃣ TimescaleDB (Primary Storage)
api_keys = await TimescaleUserService.get_api_keys(resolved_user_id)
if api_keys:
    # 복호화 후 Redis 캐싱
    return decrypted_keys

# 2️⃣ Redis (Fallback)
api_keys = await redis_client.hgetall(f"user:{resolved_user_id}:api:keys")
return decoded_keys
```

### 2. `HYPERRSI/src/services/redis_service.py`

**클래스**: `ApiKeyService`
**함수**: `set_user_api_keys(user_id, api_key, api_secret, passphrase)`

**변경 내용**:
- TimescaleDB 저장 로직 추가
- Redis 저장 유지 (캐시)
- 암호화된 상태로 양쪽 저장

**저장 순서**:
```python
# 1️⃣ TimescaleDB 저장 (Primary)
await TimescaleUserService.upsert_api_credentials(
    identifier=user_id,
    api_key=encrypted_data['api_key'],
    api_secret=encrypted_data['api_secret'],
    passphrase=encrypted_data['passphrase']
)

# 2️⃣ Redis 저장 (Cache)
await redis.hmset(f"user:{user_id}:api:keys", encrypted_data)
```

### 3. `HYPERRSI/scripts/migrate_redis_api_keys_to_timescale.py` (신규)

**목적**: 기존 Redis API 키를 TimescaleDB로 일괄 마이그레이션

**사용법**:
```bash
# 미리보기 (실제 저장 안 함)
python HYPERRSI/scripts/migrate_redis_api_keys_to_timescale.py --dry-run

# 모든 사용자 마이그레이션
python HYPERRSI/scripts/migrate_redis_api_keys_to_timescale.py

# 특정 사용자만 마이그레이션
python HYPERRSI/scripts/migrate_redis_api_keys_to_timescale.py --okx-uid 587662504768345929
```

## 🧪 테스트

### 테스트 스크립트 실행

```bash
cd /Users/seunghyun/TradingBoost-Strategy
python test_api_key_migration.py
```

**테스트 항목**:
1. ✅ API 키 저장 (TimescaleDB + Redis)
2. ✅ TimescaleDB 직접 조회
3. ✅ Redis 직접 조회
4. ✅ 통합 조회 (TimescaleDB 우선)
5. ✅ Redis Fallback 시나리오
6. ✅ 데이터 정리

## 📊 데이터베이스 스키마

### TimescaleDB: `okx_api_info` 테이블

```sql
CREATE TABLE okx_api_info (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,           -- FK to app_users
    api_key TEXT,                     -- 암호화된 API 키
    api_secret TEXT,                  -- 암호화된 API 시크릿
    passphrase TEXT,                  -- 암호화된 패스프레이즈
    telegram_id TEXT,                 -- Telegram ID
    telegram_linked BOOLEAN,          -- Telegram 연동 여부
    okx_uid TEXT,                     -- OKX UID
    okx_linked BOOLEAN,               -- OKX 연동 여부
    exchange TEXT DEFAULT 'okx',      -- 거래소 (OKX)
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ            -- Soft delete
);
```

### Redis 키 패턴

```
user:{okx_uid}:api:keys
    ├─ api_key: {encrypted_value}
    ├─ api_secret: {encrypted_value}
    └─ passphrase: {encrypted_value}
```

## 🔐 보안

### 암호화
- **저장**: 평문 → 암호화 → TimescaleDB + Redis
- **조회**: TimescaleDB/Redis → 복호화 → 평문 반환
- **암호화 키**: 환경변수 `ENCRYPTION_KEY` (shared/security)

### 암호화 흐름
```python
# 저장 시
encrypted_data = {
    'api_key': encrypt_api_key(api_key),      # AES-256-GCM
    'api_secret': encrypt_api_key(api_secret),
    'passphrase': encrypt_api_key(passphrase)
}

# 조회 시
decrypted_keys = {
    'api_key': decrypt_api_key(encrypted_value),
    'api_secret': decrypt_api_key(encrypted_value),
    'passphrase': decrypt_api_key(encrypted_value)
}
```

## 🚀 마이그레이션 가이드

### 1단계: 기존 데이터 마이그레이션

```bash
# 미리보기 (dry-run)
cd /Users/seunghyun/TradingBoost-Strategy
python HYPERRSI/scripts/migrate_redis_api_keys_to_timescale.py --dry-run

# 실제 마이그레이션
python HYPERRSI/scripts/migrate_redis_api_keys_to_timescale.py
```

### 2단계: 검증

```bash
# 테스트 스크립트 실행
python test_api_key_migration.py

# TimescaleDB 데이터 확인 (psql)
psql -h localhost -U your_user -d tradingboost
SELECT id, user_id, okx_uid, telegram_id,
       LEFT(api_key, 10) as api_key_preview,
       created_at
FROM okx_api_info
WHERE deleted_at IS NULL
ORDER BY updated_at DESC
LIMIT 10;
```

### 3단계: 모니터링

**로그 확인**:
```bash
# API 키 조회 로그
tail -f logs/hyperrsi.log | grep "API 키 조회"

# 저장 로그
tail -f logs/hyperrsi.log | grep "API 키.*저장"
```

## 📈 성능 영향

### 조회 성능
- **TimescaleDB 조회**: ~10-50ms (인덱스 활용)
- **Redis 캐시 히트**: ~1-5ms (메모리)
- **전체 조회**: 첫 조회 후 Redis 캐싱으로 성능 향상

### 저장 성능
- **이중 저장**: TimescaleDB + Redis (순차)
- **예상 지연**: +20-50ms (비동기 처리로 최소화)

## 🎉 이점

### 1. 데이터 안정성
- ✅ TimescaleDB 영구 저장 (디스크)
- ✅ Redis 장애 시에도 데이터 유지
- ✅ 백업 및 복구 용이

### 2. 성능
- ✅ Redis 캐시로 빠른 조회 (1-5ms)
- ✅ 조회 실패 시 자동 fallback

### 3. 확장성
- ✅ TimescaleDB 시계열 쿼리 지원
- ✅ API 키 변경 이력 추적 가능
- ✅ 사용자별 API 키 관리 용이

## ⚠️ 주의사항

### 1. 환경변수 필수
```bash
# .env 파일
ENCRYPTION_KEY=your-32-byte-encryption-key
TIMESCALE_HOST=localhost
TIMESCALE_PORT=5432
TIMESCALE_DATABASE=tradingboost
TIMESCALE_USER=your_user
TIMESCALE_PASSWORD=your_password
```

### 2. TimescaleDB 테이블 생성
```bash
psql -h localhost -U your_user -d tradingboost -f HYPERRSI/migrations/001_create_user_settings_tables.sql
```

### 3. 마이그레이션 순서
1. 먼저 dry-run으로 검증
2. 실제 마이그레이션 실행
3. 테스트 스크립트로 확인
4. 프로덕션 배포

## 📚 관련 문서

- [TimescaleDB 설정 가이드](HYPERRSI/docs/TIMESCALEDB_SETTINGS.md)
- [사용자 설정 저장소](HYPERRSI/docs/TIMESCALEDB_SETTINGS.md)
- [Redis 패턴 가이드](REDIS_GUIDE.md)
- [보안 설정](shared/security/README.md)

## 🔄 롤백 가이드

만약 문제가 발생하면 Redis만 사용하도록 롤백 가능:

### 코드 롤백
```bash
git revert <commit-hash>  # 이 변경사항 커밋 해시
```

### 임시 조치 (코드 수정 없이)
`dependencies.py`의 `get_user_api_keys` 함수에서:
```python
# TimescaleDB 조회 부분 주석 처리
# try:
#     api_keys = await TimescaleUserService.get_api_keys(resolved_user_id)
#     ...
# except Exception as ts_error:
#     logger.warning(...)

# Redis 조회만 사용
redis_client = await get_redis_binary()
...
```

## ✅ 체크리스트

배포 전 확인사항:

- [ ] TimescaleDB 연결 설정 완료
- [ ] `okx_api_info` 테이블 생성 완료
- [ ] `ENCRYPTION_KEY` 환경변수 설정
- [ ] 마이그레이션 스크립트 dry-run 성공
- [ ] 실제 마이그레이션 완료
- [ ] 테스트 스크립트 통과
- [ ] 로그 모니터링 설정
- [ ] 백업 전략 수립

## 🚀 향후 개선 사항

- [ ] API 키 변경 이력 추적 (audit trail)
- [ ] API 키 만료 관리
- [ ] API 키 로테이션 자동화
- [ ] 다중 거래소 지원 확장
- [ ] Redis 캐시 무효화 전략 개선
