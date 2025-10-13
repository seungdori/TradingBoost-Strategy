# UID 검증 시스템

## 📋 개요

OKX UID와 Telegram ID를 자동으로 구분하고 검증하는 시스템입니다. 잘못된 UID 사용을 방지하여 데이터 무결성을 보장합니다.

## 🎯 목적

### 문제점

- **OKX UID**: 18-19자리 숫자 (예: `587662504768345929`)
- **Telegram ID**: 9-10자리 숫자 (예: `1709556958`)

길이가 다르지만 모두 숫자라서 혼동하기 쉽습니다. 특히:
- Telegram ID를 OKX UID로 저장
- OKX UID를 Telegram ID로 저장
- 잘못된 매핑으로 인한 데이터 조회 실패

### 해결책

자동 UID 타입 감지 및 검증 시스템 구현

## 🏗️ 아키텍처

### UIDValidator 클래스

```python
from shared.utils.uid_validator import UIDValidator, UIDType

# UID 타입 감지
uid_type = UIDValidator.detect_uid_type("587662504768345929")
# → "okx_uid"

# 검증
try:
    okx_uid = UIDValidator.ensure_okx_uid("587662504768345929")
    print(f"✅ 유효한 OKX UID: {okx_uid}")
except ValueError as e:
    print(f"❌ 검증 실패: {e}")
```

## 🔍 UID 타입 판별 규칙

### 길이 기준

| 타입 | 최소 길이 | 최대 길이 | 예시 |
|------|----------|----------|------|
| **OKX UID** | 18자리 | 19자리 | `587662504768345929` |
| **Telegram ID** | 9자리 | 15자리 | `1709556958` |
| **Unknown** | 기타 | 기타 | `12345` (너무 짧음) |

### 검증 조건

1. **숫자만 포함**: 문자가 섞이면 `unknown`
2. **길이 범위**: 위 표의 범위 내에 있어야 함
3. **빈 값 체크**: None 또는 빈 문자열은 `unknown`

## 🚀 사용 방법

### 1. UID 타입 감지

```python
from shared.utils.uid_validator import detect_uid_type, UIDType

uid = "587662504768345929"
uid_type = detect_uid_type(uid)

if uid_type == UIDType.OKX_UID:
    print("OKX UID입니다")
elif uid_type == UIDType.TELEGRAM_ID:
    print("Telegram ID입니다")
else:
    print("알 수 없는 형식입니다")
```

### 2. OKX UID 검증

```python
from shared.utils.uid_validator import ensure_okx_uid

try:
    okx_uid = ensure_okx_uid("587662504768345929")
    # ✅ 검증 통과: 18자리 OKX UID
except ValueError as e:
    # ❌ 검증 실패
    print(f"오류: {e}")
```

**검증 실패 예시**:
```python
# Telegram ID를 OKX UID로 검증 시도
ensure_okx_uid("1709556958")
# → ValueError: OKX UID 검증 실패: 예상 타입 (okx_uid)과 다릅니다. 감지된 타입: telegram_id
```

### 3. Telegram ID 검증

```python
from shared.utils.uid_validator import ensure_telegram_id

try:
    telegram_id = ensure_telegram_id("1709556958")
    # ✅ 검증 통과: 10자리 Telegram ID
except ValueError as e:
    # ❌ 검증 실패
    print(f"오류: {e}")
```

### 4. 타입 감지 및 로깅

```python
from shared.utils.uid_validator import UIDValidator

UIDValidator.log_uid_info("587662504768345929", context="사용자 등록")
# → [사용자 등록] UID: 587662504768345929, 길이: 18, 타입: okx_uid
```

## 📝 적용된 코드

### 1. TimescaleDB 서비스 (timescale_service.py)

```python
@classmethod
async def ensure_user_exists(cls, okx_uid: str, telegram_id: Optional[str] = None, ...):
    # UID 검증
    try:
        okx_uid = UIDValidator.ensure_okx_uid(okx_uid)
        logger.info(f"✅ OKX UID 검증 성공: {okx_uid} (길이: {len(okx_uid)})")
    except ValueError as e:
        logger.error(f"❌ OKX UID 검증 실패: {e}")
        detected_type = UIDValidator.detect_uid_type(okx_uid)
        if detected_type == UIDType.TELEGRAM_ID:
            logger.warning(f"⚠️ Telegram ID가 OKX UID로 전달되었습니다: {okx_uid}")
        raise
```

### 2. 사용자 등록 (register.py)

```python
# 새 사용자 등록 시
okx_uid = str(uid)

# UID 검증
try:
    okx_uid = UIDValidator.ensure_okx_uid(okx_uid)
    telegram_id_str = UIDValidator.ensure_telegram_id(str(telegram_id))
    logger.info(f"✅ UID 검증 성공 - OKX: {okx_uid}, Telegram: {telegram_id_str}")
except ValueError as e:
    await message.reply(f"⚠️ UID 검증 실패: {str(e)}\n관리자에게 문의하세요.")
    return
```

### 3. 동기화 스크립트 (sync_redis_to_timescale.py)

```python
# UID 검증
try:
    okx_uid = UIDValidator.ensure_okx_uid(okx_uid)
    logger.info(f"✅ OKX UID 검증: {okx_uid} (길이: {len(okx_uid)})")
except ValueError as e:
    logger.error(f"❌ OKX UID 검증 실패: {e}")
    detected_type = UIDValidator.detect_uid_type(okx_uid)
    if detected_type == UIDType.TELEGRAM_ID:
        logger.error(f"⚠️ Telegram ID가 OKX UID로 전달됨: {okx_uid}")
        logger.error(f"   스킵합니다. 데이터를 확인하세요!")
    return False
```

## 🔍 검증 로그 예시

### 성공 케이스

```
✅ OKX UID 검증 성공: 587662504768345929 (길이: 18)
✅ Telegram ID 검증 성공: 1709556958 (길이: 10)
```

### 실패 케이스

```
❌ OKX UID 검증 실패: OKX UID 검증 실패: 예상 타입 (okx_uid)과 다릅니다. 감지된 타입: telegram_id (입력: 1709556958, 길이: 10)
⚠️ Telegram ID가 OKX UID로 전달되었습니다: 1709556958
```

### 경고 케이스

```
⚠️ 심각한 오류: Telegram ID가 OKX UID로 저장되어 있습니다: 1709556958
   데이터베이스 수정이 필요합니다!
```

## 🧪 테스트

### 유닛 테스트

```python
# shared/utils/uid_validator.py 파일 내장 테스트
python shared/utils/uid_validator.py

# 출력:
# ============================================================
# UID 검증 테스트
# ============================================================
# ✅ UID: 587662504768345929 (길이: 18)
#    예상: okx_uid, 감지: okx_uid
#
# ✅ UID: 1709556958 (길이: 10)
#    예상: telegram_id, 감지: telegram_id
# ...
```

### 통합 테스트

```bash
cd /Users/seunghyun/TradingBoost-Strategy/HYPERRSI

# 동기화 스크립트로 검증 테스트
python scripts/sync_redis_to_timescale.py --dry-run --okx-uid 587662504768345929

# 예상 출력:
# ✅ OKX UID 검증: 587662504768345929 (길이: 18)
# ✅ Telegram ID 검증: 1709556958 (길이: 10)
```

## 🎯 예방하는 오류들

### 1. Telegram ID를 OKX UID로 저장

**Before** (검증 없이):
```python
okx_uid = "1709556958"  # 실제로는 Telegram ID
await redis.set(f"user:{okx_uid}:api:keys", ...)
# → user:1709556958:api:keys로 저장 (잘못됨!)
```

**After** (검증 있음):
```python
try:
    okx_uid = UIDValidator.ensure_okx_uid("1709556958")
except ValueError as e:
    # ❌ 검증 실패: Telegram ID가 전달됨
    # 저장하지 않고 오류 처리
```

### 2. 데이터베이스 불일치

**Before**:
- Redis: `user:587662504768345929:*`
- TimescaleDB: `okx_uid = '1709556958'` (잘못된 값!)

**After**:
- Redis: `user:587662504768345929:*`
- TimescaleDB: `okx_uid = '587662504768345929'` (올바른 값!)
- 검증 로그로 즉시 감지 및 차단

### 3. 조회 실패

**Before**:
```python
# OKX UID로 조회해야 하는데 Telegram ID로 조회
data = await get_user_data("1709556958")  # 데이터 없음!
```

**After**:
```python
# 타입을 자동으로 감지하고 올바르게 처리
uid_type = UIDValidator.detect_uid_type("1709556958")
if uid_type == UIDType.TELEGRAM_ID:
    # Telegram ID → OKX UID 매핑 조회 후 데이터 가져오기
```

## 📊 검증 통계 (예시)

```
총 검증 횟수: 150
✅ 성공: 145 (96.7%)
❌ 실패: 5 (3.3%)
   - Telegram ID를 OKX UID로 전달: 3건
   - OKX UID를 Telegram ID로 전달: 1건
   - 잘못된 형식: 1건
```

## ⚠️ 주의사항

1. **길이 기준은 경험적**: OKX UID는 대부분 18-19자리지만 미래에 변경될 수 있음
2. **Telegram ID 범위 확장**: 최대 15자리까지 허용 (미래 대비)
3. **검증 실패 시 즉시 중단**: 잘못된 데이터 저장 방지
4. **로그 확인 필수**: 검증 실패 로그를 정기적으로 확인

## 🔧 확장성

### 새로운 UID 타입 추가

```python
class UIDType:
    OKX_UID = "okx_uid"
    TELEGRAM_ID = "telegram_id"
    BINANCE_UID = "binance_uid"  # 새로운 타입 추가
    UNKNOWN = "unknown"

class UIDValidator:
    BINANCE_UID_MIN_LENGTH = 15
    BINANCE_UID_MAX_LENGTH = 17

    @classmethod
    def detect_uid_type(cls, uid: str) -> str:
        # ... 기존 로직 ...

        # Binance UID 판별
        if cls.BINANCE_UID_MIN_LENGTH <= length <= cls.BINANCE_UID_MAX_LENGTH:
            return UIDType.BINANCE_UID
```

## 🎉 이점

1. **✅ 데이터 무결성**: 잘못된 UID 저장 방지
2. **✅ 디버깅 용이**: 명확한 로그로 문제 즉시 파악
3. **✅ 유지보수성**: 중앙화된 검증 로직
4. **✅ 확장성**: 새로운 UID 타입 쉽게 추가
5. **✅ 자동 감지**: 타입을 자동으로 판별하여 코드 간소화

## 📚 관련 파일

- `shared/utils/uid_validator.py` - UID 검증 유틸리티
- `HYPERRSI/src/services/timescale_service.py` - TimescaleDB 서비스 (검증 적용)
- `HYPERRSI/src/bot/command/register.py` - 사용자 등록 (검증 적용)
- `HYPERRSI/scripts/sync_redis_to_timescale.py` - 동기화 스크립트 (검증 적용)
