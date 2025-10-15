# Redis Key Migration Guide

**최종 업데이트**: 2025-10-14
**상태**: Phase 1 완료 ✅ | Phase 2 준비 완료 🔧

---

## 개요

이 문서는 TradingBoost-Strategy 프로젝트의 Redis 키 패턴 표준화 마이그레이션 가이드입니다.

### 마이그레이션 단계

- ✅ **Phase 1**: 코드 패턴 수정 (완료)
- ✅ **Phase 1.5**: 레거시 키 정리 (완료)
- 🔧 **Phase 2**: GRID Position 데이터 구조 마이그레이션 (선택사항)

---

## Phase 1: 코드 패턴 수정 (완료 ✅)

### 변경 사항

#### 1. Position Cache Keys (`shared/cache/trading_cache.py`)

**변경 전**:
```python
position:{user_id}:{symbol}
user:{user_id}:position:{symbol}:{side}  # remove_position only
```

**변경 후**:
```python
position:{user_id}:{exchange}:{symbol}:{side}
```

**API 변경**:
```python
# 이전
await trading_cache.set_position(user_id, symbol, data)
await trading_cache.get_position(user_id, symbol)
await trading_cache.remove_position(user_id, symbol, side)

# 현재 (하위 호환성 유지)
await trading_cache.set_position(user_id, symbol, side, data, exchange="okx")
await trading_cache.get_position(user_id, symbol, side, exchange="okx")
await trading_cache.remove_position(user_id, symbol, side, exchange="okx")
```

#### 2. Order Placed Keys (`GRID/database/redis_database.py`)

**변경 전**:
```python
{exchange}:user:{user_id}:symbol:{symbol}:order_placed
```

**변경 후**:
```python
orders:{exchange}:user:{user_id}:symbol:{symbol}:order_placed
```

**함수 변경**:
- `get_order_placed()` (line 232)
- `set_order_placed()` (line 237)
- `upload_order_placed()` (line 358)

### 배포 방법

```bash
# 1. 변경사항 확인
git diff shared/cache/trading_cache.py GRID/database/redis_database.py

# 2. 코드 검증
python -m py_compile shared/cache/trading_cache.py GRID/database/redis_database.py

# 3. 패턴 검증
python scripts/validate_redis_key_patterns.py

# 4. 서비스 재시작
./run_hyperrsi.sh
./run_grid.sh

# 5. 모니터링 (24-48시간)
# - Redis 키 패턴 확인: redis-cli KEYS "position:*"
# - 로그 확인: tail -f logs/*.log
# - 에러 모니터링
```

---

## Phase 1.5: 레거시 키 정리 (완료 ✅)

### 정리된 키

1. **Legacy Position Cache**: `user:549641376070615063:position:BTC-USDT-SWAP:short`
   - 이유: 새로운 패턴으로 마이그레이션됨
   - 영향: 없음 (캐시는 자동으로 재생성됨)

### 실행 방법

```bash
# Dry-run으로 확인
python scripts/cleanup_legacy_keys.py --dry-run

# 실제 정리
python scripts/cleanup_legacy_keys.py --force

# 검증
python scripts/validate_redis_key_patterns.py
```

### 결과

```
✅ Deleted: user:549641376070615063:position:BTC-USDT-SWAP:short
   (user=549641376070615063, symbol=BTC-USDT-SWAP, side=short)

CLEANUP COMPLETE
  Processed: 1 keys
```

---

## Phase 2: GRID Position 데이터 구조 마이그레이션 (선택사항 🔧)

### 현재 구조의 문제점

**현재 패턴**:
```python
{exchange}:positions:{user_id}  # JSON 배열로 모든 포지션 저장
```

**문제점**:
- ❌ 개별 포지션 접근 비효율적 (전체 배열 로드 필요)
- ❌ 동시성 문제 (race condition 가능성)
- ❌ 메모리 낭비 (불필요한 데이터 로드)

### 권장 구조

**새 패턴**:
```python
# 개별 Hash
positions:{user_id}:{exchange}:{symbol}:{side}

# 인덱스 Set
positions:index:{user_id}:{exchange}
```

**장점**:
- ✅ 빠른 개별 접근
- ✅ 동시성 안전
- ✅ 메모리 효율적

### 마이그레이션 실행

⚠️ **주의사항**:
- 이 마이그레이션은 **선택사항**입니다
- 프로덕션 환경에서는 신중하게 계획하세요
- 트레이딩 중단 시간이 필요할 수 있습니다

```bash
# 1. Dry-run으로 테스트
python scripts/migrate_grid_positions.py --dry-run

# 2. 특정 거래소만 테스트
python scripts/migrate_grid_positions.py --dry-run --exchange okx

# 3. 실제 마이그레이션 (모든 거래소)
python scripts/migrate_grid_positions.py --force

# 4. 검증
python scripts/validate_redis_key_patterns.py
redis-cli KEYS "positions:*"
redis-cli KEYS "*:positions:*:backup:*"  # 백업 확인
```

### 마이그레이션 프로세스

스크립트는 다음을 자동으로 수행합니다:

1. **백업 생성**:
   ```
   {exchange}:positions:{user_id}:backup:20251014_153000
   ```
   - 7일간 보관

2. **개별 Hash 생성**:
   ```python
   positions:{user_id}:{exchange}:{symbol}:{side}
   ```

3. **인덱스 생성**:
   ```python
   positions:index:{user_id}:{exchange}
   ```

4. **메타데이터 추가**:
   - `migrated_at`: 마이그레이션 시각
   - `migrated_from`: 원본 키

5. **원본 삭제**: 백업 후 안전하게 삭제

### 롤백 방법

문제 발생 시:

```bash
# 1. 백업에서 복원
redis-cli --eval restore_from_backup.lua

# 또는 수동 복원
redis-cli
> GET okx:positions:123:backup:20251014_153000
> SET okx:positions:123 "{...json...}"

# 2. 새 키 삭제
redis-cli KEYS "positions:*:okx:*" | xargs redis-cli DEL

# 3. 코드 롤백
git checkout HEAD~1 -- GRID/services/balance_service.py
./run_grid.sh
```

---

## 검증 도구

### 1. 패턴 검증 스크립트

```bash
python scripts/validate_redis_key_patterns.py
```

**출력**:
- ✅ Valid Keys: 표준 패턴을 따르는 키
- ⚠️ Legacy Keys: 레거시 패턴 (마이그레이션 필요)
- ❓ Unknown Keys: 검토 필요

### 2. Redis 직접 확인

```bash
# Position cache keys (HYPERRSI)
redis-cli KEYS "position:*"

# Order placed keys (GRID)
redis-cli KEYS "orders:*:order_placed"

# Position storage (GRID - 현재 구조)
redis-cli KEYS "*:positions:*"

# Position storage (GRID - 새 구조, Phase 2 후)
redis-cli KEYS "positions:*"

# 백업 키
redis-cli KEYS "*:backup:*"
```

### 3. 성능 모니터링

```python
# 응답 시간 확인
import time
import asyncio
from shared.cache import trading_cache

async def test_performance():
    start = time.time()
    pos = await trading_cache.get_position("user123", "BTC-USDT-SWAP", "long")
    elapsed = time.time() - start
    print(f"Position fetch: {elapsed*1000:.2f}ms")

asyncio.run(test_performance())
```

---

## 트러블슈팅

### 문제 1: Position cache가 비어있음

**증상**: `get_position()` 호출 시 None 반환

**해결**:
```bash
# 캐시는 자동으로 재생성됨
# 다음 API 호출 시 자동으로 채워짐
# 문제 없음 - 정상 동작
```

### 문제 2: Order placed 상태 불일치

**증상**: 주문이 이미 배치되었다고 표시되지 않음

**해결**:
```python
# Redis 확인
redis-cli HGETALL "orders:okx:user:123:symbol:BTC-USDT-SWAP:order_placed"

# 수동 리셋 (필요시)
from GRID.services.order_service import reset_order_placed
await reset_order_placed("okx", 123, "BTC-USDT-SWAP", 20)
```

### 문제 3: GRID position 조회 실패 (Phase 2 마이그레이션 후)

**증상**: `get_position_size()` 호출 시 0 반환

**해결**:
```bash
# 1. 백업에서 복원
redis-cli GET "okx:positions:123:backup:YYYYMMDD_HHMMSS"

# 2. 또는 웹소켓으로 재동기화
# (자동으로 새 키 형식으로 저장됨)
```

### 문제 4: 마이그레이션 중 에러

**해결**:
```bash
# 1. 마이그레이션 중단
# Ctrl+C

# 2. 백업 확인
redis-cli KEYS "*:backup:*"

# 3. 부분 마이그레이션 정리
python scripts/cleanup_migration.py

# 4. 다시 시도
python scripts/migrate_grid_positions.py --dry-run
```

---

## 체크리스트

### Phase 1 배포 전

- [x] `shared/cache/trading_cache.py` 변경사항 검토
- [x] `GRID/database/redis_database.py` 변경사항 검토
- [x] 코드 컴파일 확인
- [x] 패턴 검증 스크립트 실행
- [x] 기존 코드 호환성 확인
- [ ] 스테이징 환경 테스트
- [ ] 팀 리뷰 완료

### Phase 1 배포 후

- [ ] 서비스 정상 작동 확인
- [ ] Redis 키 패턴 확인
- [ ] 로그 에러 확인
- [ ] 24-48시간 모니터링
- [ ] 성능 메트릭 확인

### Phase 1.5 레거시 정리

- [x] Dry-run 실행
- [x] 레거시 키 정리
- [x] 검증 스크립트 실행
- [x] 정리 결과 확인

### Phase 2 마이그레이션 (선택사항)

- [x] 마이그레이션 스크립트 작성
- [ ] Dry-run 테스트
- [ ] 스테이징 환경 테스트
- [ ] 프로덕션 백업 생성
- [ ] 트레이딩 중단 시간 스케줄링
- [ ] 팀 공지
- [ ] 마이그레이션 실행
- [ ] 검증 및 모니터링
- [ ] 백업 정리 (7일 후)

---

## 추가 리소스

### 관련 문서

- [REDIS_KEY_INCONSISTENCIES.md](./REDIS_KEY_INCONSISTENCIES.md) - 문제 분석
- [REDIS_KEY_STANDARDIZATION_SUMMARY.md](./REDIS_KEY_STANDARDIZATION_SUMMARY.md) - 구현 요약
- [REDIS_KEYS_DOCUMENTATION.md](./REDIS_KEYS_DOCUMENTATION.md) - 전체 키 목록

### 스크립트

- `scripts/validate_redis_key_patterns.py` - 패턴 검증
- `scripts/cleanup_legacy_keys.py` - 레거시 키 정리
- `scripts/migrate_grid_positions.py` - GRID position 마이그레이션

### 연락처

문제 발생 시:
1. 로그 확인: `logs/*.log`
2. Redis 상태 확인: `redis-cli INFO`
3. 백업 위치 확인: `redis-cli KEYS "*:backup:*"`

---

**마이그레이션 가이드 끝**
