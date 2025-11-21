# Multiplier 2.0 버그 분석 보고서

## 🚨 문제 요약

**ETH-USDT-SWAP SHORT 포지션**에서 DCA 진입 시 `entry_multiplier`가 **2.0으로 실행**되었으나, 현재 설정은 **1.1**로 되어 있음.

### 실제 거래 데이터 (check_order_history.py 실행 결과)

**Cycle 2 (Entry #8-14)**: Perfect 2.0x 배율
```
Entry #8:  0.38 계약 (첫 진입)
Entry #9:  0.76 계약 (0.38 × 2.0¹)
Entry #10: 1.52 계약 (0.38 × 2.0²)
Entry #11: 3.04 계약 (0.38 × 2.0³)
Entry #12: 6.08 계약 (0.38 × 2.0⁴)
Entry #13: 12.16 계약 (0.38 × 2.0⁵)
Entry #14: 24.32 계약 (0.38 × 2.0⁶)
```

**Cycle 5 (Entry #24-27)**: Perfect 2.0x 배율
```
Entry #24: 2.02 계약 (첫 진입)
Entry #25: 4.04 계약 (2.02 × 2.0¹)
Entry #26: 8.08 계약 (2.02 × 2.0²)
Entry #27: 16.16 계약 (2.02 × 2.0³)
```

### 현재 설정 확인

**Redis Settings**:
```json
{
  "entry_multiplier": 1.1,
  "eth_investment": 5.0,
  "leverage": 20
}
```

**기본값 (DEFAULT_PARAMS_SETTINGS)**:
- `entry_multiplier: 1.0`

---

## 🔍 코드 분석

### 1. Settings 로드 경로 추적

**전체 호출 체인**:
```
execute_trading_logic.py:209
  ↓ redis_service.get_user_settings(user_id)
  ↓
execute_trading_logic.py:620
  ↓ handle_existing_position(user_settings, ...)
  ↓
position_handler/__init__.py:218
  ↓ handle_pyramiding(settings, ...)
  ↓
pyramiding.py:362
  ↓ scale = settings.get('entry_multiplier', 0.5)
```

### 2. Settings 로드 메커니즘

**redis_service.py:171-209** - `get_user_settings()`
```python
# 1단계: 로컬 캐시 확인 (TTL: 30초 또는 300초)
if cache_key in self._local_cache:
    if time.time() < self._cache_ttl.get(cache_key, 0):
        return cached_value  # ← 캐시된 값 반환

# 2단계: Redis에서 조회
settings = await redis.get(cache_key)
user_settings = json.loads(settings)

# 3단계: 기본값으로 채우기
for k, v in DEFAULT_PARAMS_SETTINGS.items():
    if k not in user_settings:
        user_settings[k] = v

# 4단계: 로컬 캐시 업데이트
self._cache_ttl[cache_key] = time.time() + 30  # 30초 캐시
```

**캐시 TTL 2가지**:
- `get_user_settings()` 호출 시: **30초**
- `set_user_settings()` 호출 시: **300초 (5분)**

### 3. DCA 계산 로직

**pyramiding.py:329-420** - `_calculate_dca_entry_size()`
```python
scale = settings.get('entry_multiplier', 0.5)  # Line 362

try:
    # Primary calculation
    investment = get_investment_amount(settings, symbol)  # 5.0 USDT
    new_investment = float(investment) * (scale ** dca_order_count)
    contract_info = await trading_service.get_contract_info(...)
    return contract_info['contracts_amount']

except Exception as e:
    # Fallback calculation
    manual_calculated_initial_size = ...
    new_entry_contracts_amount = float(manual_calculated_initial_size) * (float(scale) ** float(dca_order_count))
    return new_entry_contracts_amount
```

---

## 🐛 가능한 원인 (우선순위순)

### 🔴 원인 1: 로컬 캐시의 Stale Data
**가능성: 높음**

**시나리오**:
1. 과거 어느 시점에 `entry_multiplier: 2.0`으로 설정
2. `set_user_settings()` 호출 → 로컬 캐시에 **300초(5분) TTL**로 저장
3. 사용자가 설정을 1.1로 변경 (텔레그램 또는 API를 통해)
4. 하지만 **로컬 캐시는 아직 만료되지 않음** (최대 5분간 유지)
5. DCA 실행 시 `get_user_settings()`가 캐시에서 **2.0 반환**

**증거**:
- Cycle 2와 Cycle 5에서만 2.0 사용
- 다른 사이클(1, 3, 4)에서는 다른 배율 사용
- Redis에 현재 1.1로 저장되어 있음

**검증 방법**:
- Telegram fallback 메시지 로그 확인
- Redis settings 변경 이력 확인 (있다면)

### 🟡 원인 2: Exception → Fallback 실행 중 버그
**가능성: 중간**

**잠재적 버그 위치**: `pyramiding.py:391-404`
```python
if dca_order_count > 1:
    if manual_calculated_initial_size_raw is None or \
       manual_calculated_initial_size_raw == "None" or \
       manual_calculated_initial_size_raw == "0":
        # position_size를 dca_order_count로 나눔
        manual_calculated_initial_size = float(position_size) / float(dca_order_count)
```

**문제점**:
- `position_size`는 **누적된 전체 포지션 크기**
- `initial_size` Redis 키가 없으면 `position_size / dca_order_count`로 계산
- 이미 누적된 값을 나누면 **잘못된 initial_size** 도출
- 하지만 이것만으로는 2.0x 배율을 설명할 수 없음

### 🟢 원인 3: settings 객체 자체가 None 또는 비어있음
**가능성: 낮음**

**시나리오**:
- settings가 None이면 `settings.get()`에서 AttributeError 발생
- Exception → fallback 실행
- 하지만 fallback에서도 Line 362에서 정의된 `scale` 사용
- settings가 비어있다면 default 0.5 사용 (2.0이 아님)

---

## 🔬 추가 조사 필요

### 1. Telegram Debug 메시지 확인
**pyramiding.py:409-418**의 fallback 메시지가 있는지 확인:
```
[DEBUG : {user_id}] Fallback DCA 계산
초기진입크기: ...
배율: ...
DCA회차: ...
```

이 메시지가 있다면:
- Fallback이 실행되었다는 증거
- 메시지에 명시된 `배율` 값이 2.0인지 확인

### 2. Redis Settings History
Redis에 설정 변경 로그나 백업이 있다면:
- 과거에 `entry_multiplier: 2.0`으로 설정한 적이 있는지 확인
- 언제 1.1로 변경되었는지 타임스탬프 확인

### 3. Exception 로그 확인
**Primary calculation이 실패한 이유** 확인:
- `trading_service.get_contract_info()` 호출 실패 원인
- 어떤 exception이 발생했는지

### 4. 코드에서 scale override 여부
`pyramiding.py` 전체 파일에서:
```bash
grep -n "scale\s*=" pyramiding.py
```
Line 362 이후에 scale을 다시 할당하는 코드가 있는지 확인

---

## 📊 데이터 불일치 문제

### Position Size 동기화 실패
- **Redis**: 32.32 계약 (dca_count: 4)
- **실제 OKX**: 92.47 계약 (27개 진입)
- **차이**: 60.15 계약

**원인**:
`position_manager.update_position_state()` 호출 후 Redis가 업데이트되지 않음

**영향**:
- Fallback 계산 시 잘못된 `position_size` 사용
- 추가 DCA 진입 시 잘못된 크기 계산

---

## 💡 결론 및 권장사항

### 즉시 조치
1. **로컬 캐시 TTL 단축**: 300초 → 30초 또는 비활성화
2. **Settings 변경 시 캐시 무효화**: Pub/Sub으로 모든 인스턴스에 알림
3. **Fallback 로직 개선**:
   - `initial_size` Redis 키 강제 저장
   - Fallback 실행 시 명확한 로그 및 알림

### 버그 수정
1. **position_size 동기화 수정**:
   - DCA 실행 후 Redis position 업데이트 검증
   - OKX API와 주기적 동기화

2. **Fallback 계산 로직 재검토**:
   - Line 397의 `position_size / dca_order_count` 로직 개선
   - `initial_size`가 없을 때 대체 방법 마련

### 모니터링 강화
1. **Settings 값 로깅**: 각 DCA 실행 시 사용된 `entry_multiplier` 로그
2. **캐시 hit/miss 추적**: 캐시 사용 패턴 모니터링
3. **Exception 추적**: Primary calculation 실패 빈도 및 원인 분석

---

## 🔄 재현 시나리오

**Cycle 2 재현 (추정)**:
```
1. 사용자가 과거에 entry_multiplier를 2.0으로 설정 (또는 시스템 오류)
2. Settings 캐시에 2.0 저장 (TTL: 300초)
3. Entry #8 실행 (첫 진입): 0.38 계약
4. 5분 이내에 Entry #9-14 실행
5. 각 실행마다 캐시에서 2.0 읽어옴
6. 결과: Perfect 2.0x 배율로 진입
7. 5분 후 캐시 만료 → 새로운 설정(1.1) 로드
```

**검증 방법**:
- Entry #8과 Entry #14의 타임스탬프 차이 확인
- 5분 이내라면 캐시 이슈일 가능성 높음
