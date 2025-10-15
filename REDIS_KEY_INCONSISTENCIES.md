# Redis Key Inconsistencies & Standardization Plan

**발견 날짜**: 2025-10-14

**목적**: 프로젝트 전반에 걸쳐 혼재된 Redis 키 패턴을 찾아내고 표준화 방안을 제시

---

## 🚨 Critical Issues (즉시 수정 필요)

### 1. Position Key 패턴 불일치

#### 문제 상황

**3가지 다른 패턴이 혼재**:

1. **Legacy Pattern (HYPERRSI)**: `user:{user_id}:position:{symbol}:{side}`
2. **Cache Pattern (HYPERRSI)**: `position:{user_id}:{symbol}` (side 없음)
3. **GRID Pattern**: `{exchange}:positions:{user_id}` (JSON 배열)
4. **Shared Standard**: `positions:{user_id}:{exchange}:{symbol}:{side}`
5. **Realtime Pattern**: `positions:realtime:{user_id}:{exchange}:{symbol}:{side}`

#### 영향을 받는 파일

```
shared/cache/trading_cache.py:
  - Line 133: key = f"position:{user_id}:{symbol}"  ❌ side 누락
  - Line 143: key = f"position:{user_id}:{symbol}"  ❌ side 누락
  - Line 148: key = f"position:{user_id}:{symbol}"  ❌ side 누락
  - Line 174: key = f"user:{user_id}:position:{symbol}:{side}"  ❌ Legacy 패턴

GRID/database/redis_database.py:
  - Line 1038: position_key = f'{exchange_name}:positions:{user_id}'  ❌ JSON 배열로 저장

GRID/services/balance_service.py:
  - Line 99: cache_key = f"okx:positions:{user_id}"  ❌ GRID 패턴
  - Line 104: cache_key = f"{exchange.id.lower()}:positions:{user_id}:{symbol}"  ❌ 혼합 패턴

GRID/trading/cancel_limit.py:
  - Line 61: position_key = f'{exchange_name}:positions:{user_id}'  ❌ GRID 패턴

GRID/services/order_service.py:
  - Line 143: position_key = f'{exchange_name}:positions:{user_id}'  ❌ GRID 패턴

GRID/monitoring/position_monitor.py:
  - Line 66: cache_key = f'{exchange_name}:positions:{user_id}'  ❌ GRID 패턴
```

#### 표준화 방안

**✅ 채택할 표준 패턴**:
```python
# 영구 저장 (Shared 표준)
positions:{user_id}:{exchange}:{symbol}:{side}

# 실시간 추적 (Position Service)
positions:realtime:{user_id}:{exchange}:{symbol}:{side}

# 캐시 (단기 저장, HYPERRSI 전용)
position:{user_id}:{symbol}  # exchange와 side는 메타데이터에 포함
```

#### 마이그레이션 단계

1. **Phase 1**: `shared/cache/trading_cache.py` 수정
   - `set_position`, `get_position`, `bulk_get_positions`에 `exchange`, `side` 파라미터 추가
   - `remove_position`의 키 패턴을 표준 패턴으로 변경

2. **Phase 2**: GRID 모듈의 position 저장 방식 변경
   - JSON 배열 저장 방식에서 개별 Hash 저장으로 전환
   - 마이그레이션 스크립트 작성

3. **Phase 3**: 레거시 키 정리
   - `user:{user_id}:position:*` 패턴 사용 중단
   - 데이터 마이그레이션 후 삭제

---

### 2. Order Placed 패턴 중복

#### 문제 상황

**2가지 다른 패턴이 공존**:

1. **Old Pattern**: `{exchange}:user:{user_id}:symbol:{symbol}:order_placed`
2. **New Pattern**: `orders:{exchange}:user:{user_id}:symbol:{symbol}:order_placed`
3. **Index Pattern**: `orders:{exchange}:user:{user_id}:symbol:{symbol}:order_placed_index`

#### 영향을 받는 파일

```
GRID/database/redis_database.py:
  - Line 232-234: key = f"{exchange_name}:user:{user_id}:symbol:{symbol_name}:order_placed"  ❌ Old
  - Line 236-238: key = f"{exchange_name}:user:{user_id}:symbol:{symbol_name}:order_placed"  ❌ Old
  - Line 358: order_placed_key = f'{exchange_name}:user:{user_id}:symbol:{symbol}:order_placed'  ❌ Old

GRID/services/order_service.py:
  - Line 19: key = f"orders:{exchange_name}:user:{user_id}:symbol:{symbol_name}:orders"  ✅ New
  - Line 30: key = f"orders:{exchange_name}:user:{user_id}:symbol:{symbol_name}:orders"  ✅ New
  - Line 40: key = f'orders:{exchange_name}:user:{user_id}:symbol:{symbol_name}:order_placed_index'  ✅ New
  - Line 46: order_placed_key = f'orders:{exchange_name}:user:{user_id}:symbol:{symbol}:order_placed'  ✅ New
```

#### 표준화 방안

**✅ 채택할 표준 패턴**:
```python
# 주문 가격 추적 (Sorted Set)
orders:{exchange}:user:{user_id}:symbol:{symbol}:orders

# 주문 배치 상태 (Hash: level → "0"|"1")
orders:{exchange}:user:{user_id}:symbol:{symbol}:order_placed

# 주문 ID 인덱스 (Set)
orders:{exchange}:user:{user_id}:symbol:{symbol}:order_placed_index
```

**❌ 제거할 레거시 패턴**:
```python
{exchange}:user:{user_id}:symbol:{symbol}:order_placed
```

#### 마이그레이션 단계

1. **Phase 1**: GRID/database/redis_database.py 수정
   - `get_order_placed`, `set_order_placed`, `upload_order_placed` 함수의 키 패턴 변경

2. **Phase 2**: 데이터 마이그레이션
   - 기존 `{exchange}:user:*:symbol:*:order_placed` 데이터를 새 패턴으로 이동
   - 마이그레이션 스크립트 작성

3. **Phase 3**: 레거시 키 삭제
   - 마이그레이션 완료 후 구 패턴 키 일괄 삭제

---

## ⚠️ Medium Priority Issues (점진적 개선)

### 3. User Data 키 패턴 혼재

#### 문제 상황

**2가지 패턴이 혼재**:

1. **HYPERRSI Pattern**: `user:{user_id}:*`
2. **GRID Pattern**: `{exchange}:user:{user_id}`

#### 현재 상태

이 패턴 차이는 **의도적 설계**:
- HYPERRSI는 단일 거래소(OKX) 중심 → exchange prefix 불필요
- GRID는 다중 거래소 지원 → exchange prefix 필수

#### 권장 사항

**현재 상태 유지** (변경 불필요)

**단, 신규 개발 시 가이드라인**:
- HYPERRSI 모듈: `user:{user_id}:*` 사용
- GRID 모듈: `{exchange}:user:{user_id}` 사용
- Shared 모듈: exchange 파라미터를 받아 유연하게 처리

---

### 4. Job Status 키 중복

#### 문제 상황

**2가지 패턴 공존**:

1. **Job Pattern**: `{exchange}:job:{user_id}` (Celery 작업 추적)
2. **Bot Status Pattern**: `user:{user_id}:bot:status` (봇 상태)

#### 현재 상태

이들은 **서로 다른 목적**:
- `{exchange}:job:{user_id}`: Celery 작업 ID와 상태 (running/stopped)
- `user:{user_id}:bot:status`: 봇 활성화 여부 (enabled/disabled)

#### 권장 사항

**현재 상태 유지** (기능적으로 분리됨)

---

## 📋 Best Practices 위반 사례

### 5. Position 데이터를 JSON 배열로 저장 (GRID)

#### 문제

```python
# GRID/database/redis_database.py:1038
position_key = f'{exchange_name}:positions:{user_id}'
position_data = await redis.get(position_key)  # JSON 배열 반환
positions = json.loads(position_data)
```

**문제점**:
- ❌ 개별 포지션 접근이 비효율적 (전체 배열 로드 필요)
- ❌ 동시성 문제 (배열 수정 시 race condition)
- ❌ 메모리 낭비 (모든 포지션을 한 번에 로드)

#### 개선 방안

**✅ Hash 구조로 전환**:
```python
# 각 포지션을 개별 Hash로 저장
position_key = f'positions:{user_id}:{exchange}:{symbol}:{side}'
await redis.hset(position_key, mapping=position_data)

# 인덱스로 조회
index_key = f'positions:index:{user_id}:{exchange}'
await redis.sadd(index_key, f'{symbol}:{side}')
```

**장점**:
- ✅ 개별 포지션 빠른 접근
- ✅ 동시성 안전
- ✅ 메모리 효율적

---

### 6. Cache Key에 side 누락 (HYPERRSI)

#### 문제

```python
# shared/cache/trading_cache.py:133
key = f"position:{user_id}:{symbol}"  # side 정보 없음
```

**문제점**:
- ❌ 양방향 포지션 불가 (long/short 동시 보유 불가)
- ❌ 데이터 덮어쓰기 위험

#### 개선 방안

**✅ side 추가**:
```python
async def set_position(
    self,
    user_id: str,
    symbol: str,
    side: str,  # 추가
    data: Dict[Any, Any]
) -> bool:
    """Cache position data"""
    key = f"position:{user_id}:{symbol}:{side}"
    return await self._cache.set(key, data, expire=300)
```

---

## 🔧 Standardization Recommendations

### 통일된 네이밍 규칙

#### 1. Position Keys

```python
# ✅ 영구 저장 (Shared Standard)
positions:{user_id}:{exchange}:{symbol}:{side}

# ✅ 실시간 추적
positions:realtime:{user_id}:{exchange}:{symbol}:{side}

# ✅ 인덱스
positions:index:{user_id}:{exchange}

# ✅ 전역 활성 포지션
positions:active

# ✅ 히스토리
positions:history:{user_id}:{exchange}
```

#### 2. Order Keys

```python
# ✅ 주문 상세
orders:{order_id}

# ✅ 사용자별 주문 인덱스
orders:user:{user_id}:{exchange}

# ✅ 심볼별 오픈 주문
orders:open:{exchange}:{symbol}

# ✅ GRID 주문 (가격 추적)
orders:{exchange}:user:{user_id}:symbol:{symbol}:orders

# ✅ GRID 주문 배치 상태
orders:{exchange}:user:{user_id}:symbol:{symbol}:order_placed

# ✅ GRID 주문 ID 인덱스
orders:{exchange}:user:{user_id}:symbol:{symbol}:order_placed_index
```

#### 3. User Keys

```python
# ✅ HYPERRSI (단일 거래소)
user:{user_id}:settings
user:{user_id}:api:keys
user:{user_id}:bot:status

# ✅ GRID (다중 거래소)
{exchange}:user:{user_id}
{exchange}:user:{user_id}:symbol:{symbol}:*
```

---

## 📊 Priority Matrix

| 이슈 | 우선순위 | 영향도 | 난이도 | 권장 일정 |
|------|----------|--------|--------|-----------|
| Position 키 불일치 | 🔴 High | High | Medium | 1-2주 |
| Order Placed 중복 | 🔴 High | Medium | Low | 1주 |
| JSON 배열 저장 방식 | 🟡 Medium | High | High | 2-3주 |
| Cache side 누락 | 🟡 Medium | Medium | Low | 1주 |
| User 키 혼재 | 🟢 Low | Low | N/A | 유지 |
| Job Status 중복 | 🟢 Low | Low | N/A | 유지 |

---

## 🚀 Implementation Plan

### Week 1-2: Critical Fixes

**목표**: Position 키 표준화 및 Order Placed 통일

**Tasks**:
1. `shared/cache/trading_cache.py` 수정
   - `exchange`, `side` 파라미터 추가
   - 호출부 모두 수정

2. GRID `order_placed` 키 마이그레이션
   - 마이그레이션 스크립트 작성
   - 프로덕션 적용
   - 레거시 키 삭제

3. 테스트 작성 및 검증

### Week 3-4: Medium Priority

**목표**: GRID position 저장 방식 개선

**Tasks**:
1. Position Hash 구조 설계
2. 마이그레이션 스크립트 작성
3. GRID 모듈 리팩토링
4. 성능 테스트 및 검증

### Week 5+: Documentation & Cleanup

**Tasks**:
1. 업데이트된 문서화
2. 레거시 코드 제거
3. 모니터링 및 최적화

---

## 📝 Migration Scripts

### Script 1: Position Keys Migration

```python
# scripts/migrate_position_keys.py
"""
Migrate legacy position keys to standardized pattern
"""
import asyncio
from shared.database.redis import get_redis

async def migrate_position_keys():
    redis = await get_redis()

    # Find all legacy position keys
    legacy_patterns = [
        "user:*:position:*",
        "position:*",  # Cache keys without side
    ]

    for pattern in legacy_patterns:
        keys = await redis.keys(pattern)
        for key in keys:
            # Parse old key
            # Convert to new pattern: positions:{user_id}:{exchange}:{symbol}:{side}
            # Migrate data
            pass

    print(f"Migrated {len(keys)} position keys")

if __name__ == "__main__":
    asyncio.run(migrate_position_keys())
```

### Script 2: Order Placed Migration

```python
# scripts/migrate_order_placed_keys.py
"""
Migrate GRID order_placed keys to new pattern
"""
import asyncio
from shared.database.redis import get_redis

async def migrate_order_placed_keys():
    redis = await get_redis()

    # Find all old pattern keys
    pattern = "*:user:*:symbol:*:order_placed"
    keys = await redis.keys(pattern)

    for old_key in keys:
        # Parse: {exchange}:user:{user_id}:symbol:{symbol}:order_placed
        parts = old_key.split(':')
        exchange = parts[0]
        user_id = parts[2]
        symbol = parts[4]

        # Create new key
        new_key = f"orders:{exchange}:user:{user_id}:symbol:{symbol}:order_placed"

        # Copy data
        data = await redis.hgetall(old_key)
        if data:
            await redis.hset(new_key, mapping=data)
            await redis.delete(old_key)
            print(f"Migrated: {old_key} → {new_key}")

    print(f"Migrated {len(keys)} order_placed keys")

if __name__ == "__main__":
    asyncio.run(migrate_order_placed_keys())
```

---

## ✅ Validation Checklist

마이그레이션 전 확인사항:

- [ ] 모든 영향받는 파일 식별 완료
- [ ] 마이그레이션 스크립트 작성 및 테스트
- [ ] 롤백 계획 수립
- [ ] 백업 생성
- [ ] 스테이징 환경 테스트 완료
- [ ] 성능 테스트 완료
- [ ] 문서 업데이트
- [ ] 팀 리뷰 완료

마이그레이션 후 확인사항:

- [ ] 데이터 무결성 검증
- [ ] 기능 정상 작동 확인
- [ ] 성능 모니터링
- [ ] 레거시 키 삭제 완료
- [ ] 로그 확인 (에러 없음)
- [ ] 사용자 피드백 수집

---

## 📚 Related Documentation

- [REDIS_KEYS_DOCUMENTATION.md](./REDIS_KEYS_DOCUMENTATION.md) - 전체 키 목록
- [REDIS_MIGRATION_REPORT.md](./REDIS_MIGRATION_REPORT.md) - 이전 마이그레이션 기록
- [shared/database/redis_schemas.py](./shared/database/redis_schemas.py) - 표준 스키마

---

**End of Redis Key Inconsistencies Report**
