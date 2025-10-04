# 🔧 GRID와 HYPERRSI 공통 파일 통합 가이드

> **작성일**: 2025-10-05
> **목적**: GRID와 HYPERRSI 프로젝트의 중복 코드를 `shared` 디렉토리로 통합하여 코드 재사용성과 유지보수성을 향상시킵니다.

---
---

## 🎯 개요

### 프로젝트 구조
```
TradingBoost-Strategy/
├── GRID/                 # 그리드 트레이딩 봇
├── HYPERRSI/            # RSI 기반 트레이딩 봇
└── shared/              # 공통 모듈 (목표)
```

### 통합 목표
- ✅ **코드 중복 제거**: 30-40% 중복 코드 감소
- ✅ **유지보수성 향상**: 공통 로직 한 곳에서 관리
- ✅ **일관성 보장**: 동일한 DTO/Schema 사용
- ✅ **개발 효율성**: 공통 모듈 재사용

---

## 📊 현재 상태 분석

### GRID 프로젝트 구조
```
GRID/
├── dtos/                    # 데이터 전송 객체
│   ├── ai_search.py        # AI 검색 DTO
│   ├── auth.py             # 인증 DTO ⭐️
│   ├── bot_state.py        # 봇 상태 DTO
│   ├── exchange.py         # 거래소 DTO
│   ├── feature.py          # 기능 DTO
│   ├── response.py         # 응답 DTO ⭐️
│   ├── symbol.py           # 심볼 DTO
│   ├── telegram.py         # 텔레그램 DTO ⭐️
│   ├── trading_data.py     # 트레이딩 데이터 DTO
│   └── user.py             # 사용자 DTO ⭐️
├── helpers/                 # 헬퍼 유틸리티
│   ├── cache_helper.py     # 캐시 헬퍼 ⭐️
│   └── path_helper.py      # 경로 헬퍼 (중복)
└── [기타 파일들...]

⭐️ = shared로 이동 가능
```

### HYPERRSI 프로젝트 구조
```
HYPERRSI/
├── schema/                  # 스키마 정의
│   └── trading.py          # 트레이딩 스키마 ⭐️
├── src/helpers/            # 헬퍼 유틸리티
│   ├── order_helper.py     # 주문 헬퍼 🔄
│   └── user_id_helper.py   # 사용자 ID 헬퍼 🔄
└── [기타 파일들...]

⭐️ = shared로 이동 가능
🔄 = 통합 검토 필요
```

### shared 현재 구조
```
shared/
├── __init__.py
├── config.py               # 공통 설정
├── constants/              # 상수 정의
│   ├── default_settings.py
│   ├── enterstrategy.py
│   ├── error.py
│   ├── exchange.py
│   ├── message.py
│   └── redis_pattern.py
├── database/               # 데이터베이스 파일
│   ├── binance_spot_users.db
│   ├── binance_users.db
│   ├── bitget_spot_users.db
│   ├── bitget_users.db
│   ├── okx_spot_users.db
│   ├── okx_users.db
│   ├── upbit_users.db
│   └── local_db.sqlite
├── exchange_apis/          # 거래소 API
│   └── exchange_store.py
└── utils/                  # 유틸리티
    └── path_helper.py
```

---

## 🚀 통합 계획

### Phase 1: 즉시 이동 가능 (우선순위: 높음)

#### 1.1 DTOs 이동
| 파일 | 현재 위치 | 목표 위치 | 이유 |
|------|----------|----------|------|
| `response.py` | `GRID/dtos/` | `shared/dtos/` | 공통 응답 포맷 |
| `auth.py` | `GRID/dtos/` | `shared/dtos/` | 공통 인증 로직 |
| `telegram.py` | `GRID/dtos/` | `shared/dtos/` | 공통 텔레그램 연동 |
| `user.py` | `GRID/dtos/` | `shared/dtos/` | 공통 사용자 모델 |

#### 1.2 Helpers 이동
| 파일 | 현재 위치 | 목표 위치 | 이유 |
|------|----------|----------|------|
| `cache_helper.py` | `GRID/helpers/` | `shared/helpers/` | 공통 캐시 유틸 |
| `path_helper.py` | `GRID/helpers/` | 제거 | `shared/utils/`에 이미 존재 |

### Phase 2: 통합 및 확장 (우선순위: 중간)

#### 2.1 Trading Schema 통합
- `HYPERRSI/schema/trading.py` → `shared/dtos/trading.py`
- GRID에서도 사용 가능하도록 확장

#### 2.2 Exchange DTO 통합
- `GRID/dtos/exchange.py` → `shared/dtos/exchange.py`
- API 키, 지갑 정보 등 공통화

#### 2.3 Bot State DTO 통합
- `GRID/dtos/bot_state.py` → `shared/dtos/bot_state.py`
- 봇 상태 관리 표준화

### Phase 3: 고급 통합 (우선순위: 낮음)

#### 3.1 Helpers 통합
- `HYPERRSI/src/helpers/order_helper.py` → `shared/helpers/order_helper.py`
- `HYPERRSI/src/helpers/user_id_helper.py` → `shared/helpers/user_id_helper.py`

#### 3.2 Config 통합
- GRID와 HYPERRSI의 config 파일 병합
- 환경별 설정 분리

---

## 📝 상세 이동 가이드

### 1. DTOs 이동 가이드

#### 1.1 `response.py` 이동

**📍 현재 파일**: `GRID/dtos/response.py`

```python
# GRID/dtos/response.py
from typing import Generic, Optional, TypeVar
from pydantic import BaseModel as GenericModel

DataType = TypeVar("DataType")

class ResponseDto(GenericModel, Generic[DataType]):
    success: bool
    message: str = ""
    meta: dict = {}
    data: Optional[DataType] = None
```

**✅ 이동 절차**:

1. **파일 복사**:
```bash
mkdir -p shared/dtos
cp GRID/dtos/response.py shared/dtos/response.py
```

2. **GRID 파일 수정** (import 경로 변경):
```bash
# GRID 프로젝트 내 모든 파일에서 import 변경
# 변경 전:
from dtos.response import ResponseDto

# 변경 후:
from shared.dtos.response import ResponseDto
```

3. **영향 받는 파일들**:
```
GRID/routes/exchange_route.py
GRID/routes/telegram_route.py
GRID/routes/feature_route.py
GRID/routes/trading_route.py
GRID/routes/auth_route.py
GRID/dtos/user.py (중복 정의 제거 필요)
```

4. **검증**:
```bash
cd GRID
python -c "from shared.dtos.response import ResponseDto; print('✅ Import 성공')"
```

---

#### 1.2 `auth.py` 이동

**📍 현재 파일**: `GRID/dtos/auth.py`

```python
# GRID/dtos/auth.py
import secrets
from pydantic import BaseModel, Field
from typing import Optional

class SignupDto(BaseModel):
    user_id: str = Field(examples=["user_id"])
    exchange_name: str = Field(examples=["Exchange name"])
    api_key: str = Field(examples=["api_key"])
    secret_key: str = Field(examples=["secret_key"])
    password: Optional[str] = Field(examples=["password"])

class LoginDto(SignupDto):
    username: str = Field(examples=["sample user name"])
    password: str = Field(examples=["sample password"])
```

**✅ 이동 절차**:

1. **파일 복사**:
```bash
cp GRID/dtos/auth.py shared/dtos/auth.py
```

2. **GRID import 변경**:
```bash
# 변경 전:
from dtos.auth import LoginDto, SignupDto

# 변경 후:
from shared.dtos.auth import LoginDto, SignupDto
```

3. **영향 받는 파일**:
```
GRID/routes/auth_route.py
```

4. **HYPERRSI 적용** (선택적):
```python
# HYPERRSI에서 인증 로직 추가 시
from shared.dtos.auth import LoginDto, SignupDto
```

---

#### 1.3 `telegram.py` 이동

**📍 현재 파일**: `GRID/dtos/telegram.py`

```python
# GRID/dtos/telegram.py
from pydantic import BaseModel, Field

class TelegramTokenDto(BaseModel):
    exchange_name: str = Field(examples=["okx","binance", "upbit", "bitget", "binance_spot", "bitget_spot", "okx_spot"])
    token: str = Field(examples=["sample telegram token"])
```

**✅ 이동 절차**:

1. **파일 복사**:
```bash
cp GRID/dtos/telegram.py shared/dtos/telegram.py
```

2. **GRID import 변경**:
```bash
# 변경 전:
from dtos.telegram import TelegramTokenDto

# 변경 후:
from shared.dtos.telegram import TelegramTokenDto
```

3. **영향 받는 파일**:
```
GRID/routes/telegram_route.py
```

4. **HYPERRSI 확장** (추가):
```python
# shared/dtos/telegram.py에 추가
class TelegramMessageDto(BaseModel):
    chat_id: int
    message: str
    parse_mode: Optional[str] = "HTML"
```

---

#### 1.4 `user.py` 이동 및 통합

**📍 현재 파일**: `GRID/dtos/user.py`

```python
# GRID/dtos/user.py
from pydantic import BaseModel, Field
from typing import List, Optional, Generic, TypeVar

DataType = TypeVar("DataType")

class UserExistDto(BaseModel):
    user_exist: bool
    user_ids: Optional[List[int]] = None

class UserDto(BaseModel):
    id: int = Field(examples=[0])
    username: int = Field(examples=["sample user name"])
    password: str = Field(examples=["sample password"])

class UserCreateDto(BaseModel):
    username: str
    password: str

class UserWithoutPasswordDto(BaseModel):
    user_id: str

    @classmethod
    def from_user_dto(cls, user_dto: dict):
        return cls(user_id=user_dto['user_id'])
```

**⚠️ 주의사항**:
- `ResponseDto`가 중복 정의되어 있음 → 제거 필요
- `username` 필드가 `int` 타입으로 잘못 정의됨 → 수정 필요

**✅ 개선된 버전** (`shared/dtos/user.py`):

```python
# shared/dtos/user.py
from pydantic import BaseModel, Field
from typing import List, Optional

class UserExistDto(BaseModel):
    """사용자 존재 여부 확인 DTO"""
    user_exist: bool
    user_ids: Optional[List[int]] = None

class UserDto(BaseModel):
    """사용자 전체 정보 DTO"""
    id: int = Field(examples=[0])
    username: str = Field(examples=["sample_user"])  # int → str 수정
    password: str = Field(examples=["sample_password"])

class UserCreateDto(BaseModel):
    """사용자 생성 요청 DTO"""
    username: str
    password: str

class UserWithoutPasswordDto(BaseModel):
    """비밀번호 제외 사용자 정보 DTO"""
    user_id: str

    @classmethod
    def from_user_dto(cls, user_dto: dict):
        return cls(user_id=user_dto['user_id'])

class UserResponseDto(BaseModel):
    """사용자 응답 DTO (HYPERRSI 호환)"""
    telegram_id: str
    okx_uid: Optional[str] = None
    api_key: Optional[str] = None
    secret_key: Optional[str] = None
    passphrase: Optional[str] = None
```

**이동 절차**:

1. **개선된 파일 생성**:
```bash
# 위의 개선된 버전을 shared/dtos/user.py로 저장
```

2. **GRID import 변경**:
```bash
# 변경 전:
from dtos.user import UserWithoutPasswordDto

# 변경 후:
from shared.dtos.user import UserWithoutPasswordDto
```

3. **중복 제거**:
```python
# GRID/dtos/user.py에서 ResponseDto 정의 제거
# (이미 shared/dtos/response.py에 존재)
```

---

#### 1.5 `trading.py` 생성 및 통합

**📍 기존 파일**: `HYPERRSI/schema/trading.py`

```python
# HYPERRSI/schema/trading.py
from typing import Optional, List
from pydantic import BaseModel

class OpenPositionRequest(BaseModel):
    """포지션 오픈 요청"""
    user_id: str
    symbol: str
    direction: str   # "long" or "short"
    size: float
    leverage: float = 10.0
    stop_loss: Optional[float] = None
    take_profit: Optional[List[float]] = None
    is_DCA: bool = False

class ClosePositionRequest(BaseModel):
    """포지션 청산 요청"""
    user_id: str
    symbol: str
    percent: Optional[float] = 100.0
    size: Optional[float] = 0.0
    comment: str = "포지션 청산"
    side: Optional[str] = None

class PositionResponse(BaseModel):
    """포지션 응답"""
    symbol: str
    side: str
    size: float
    entry_price: float
    leverage: float
    sl_price: Optional[float]
    tp_prices: Optional[List[float]] = None
    order_id: Optional[str] = None
```

**✅ 확장된 버전** (`shared/dtos/trading.py`):

```python
# shared/dtos/trading.py
"""
트레이딩 공통 DTO/Schema

GRID와 HYPERRSI 프로젝트에서 공통으로 사용하는 트레이딩 관련 데이터 모델
"""
from typing import Optional, List
from pydantic import BaseModel, Field
from enum import Enum

class PositionSide(str, Enum):
    """포지션 방향"""
    LONG = "long"
    SHORT = "short"
    BOTH = "both"

class OrderType(str, Enum):
    """주문 타입"""
    MARKET = "market"
    LIMIT = "limit"
    STOP_MARKET = "stop_market"
    STOP_LIMIT = "stop_limit"

class OpenPositionRequest(BaseModel):
    """포지션 오픈 요청"""
    user_id: str = Field(..., description="사용자 ID")
    symbol: str = Field(..., description="심볼 (예: BTC-USDT-SWAP)")
    direction: PositionSide = Field(..., description="포지션 방향")
    size: float = Field(..., gt=0, description="포지션 크기")
    leverage: float = Field(10.0, ge=1, le=125, description="레버리지")
    stop_loss: Optional[float] = Field(None, description="손절가")
    take_profit: Optional[List[float]] = Field(None, description="익절가 리스트")
    is_DCA: bool = Field(False, description="DCA 여부")
    order_type: OrderType = Field(OrderType.MARKET, description="주문 타입")

class ClosePositionRequest(BaseModel):
    """포지션 청산 요청"""
    user_id: str = Field(..., description="사용자 ID")
    symbol: str = Field(..., description="심볼")
    percent: Optional[float] = Field(100.0, ge=0, le=100, description="청산 비율 (%)")
    size: Optional[float] = Field(0.0, ge=0, description="청산 수량")
    comment: str = Field("포지션 청산", description="청산 사유")
    side: Optional[PositionSide] = Field(None, description="청산할 포지션 방향")

class PositionResponse(BaseModel):
    """포지션 응답"""
    symbol: str
    side: PositionSide
    size: float
    entry_price: float
    leverage: float
    sl_price: Optional[float] = None
    tp_prices: Optional[List[float]] = None
    order_id: Optional[str] = None
    unrealized_pnl: Optional[float] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "symbol": "BTC-USDT-SWAP",
                "side": "long",
                "size": 0.05,
                "entry_price": 18765.2,
                "leverage": 10.0,
                "sl_price": 18500.0,
                "tp_prices": [19000.0, 19200.0],
                "order_id": "1234567890",
                "unrealized_pnl": 125.50
            }
        }
    }

# GRID 호환을 위한 추가 DTO
class GridTradingData(BaseModel):
    """그리드 트레이딩 데이터"""
    symbol: str
    long_tp1_price: float
    long_tp2_price: float
    long_tp3_price: float
    long_sl_price: float
    short_tp1_price: Optional[float] = None
    short_tp2_price: Optional[float] = None
    short_tp3_price: Optional[float] = None
    short_sl_price: Optional[float] = None

class WinrateDto(BaseModel):
    """승률 통계"""
    name: str
    long_win_rate: Optional[float] = None
    short_win_rate: Optional[float] = None
    total_win_rate: Optional[float] = None
```

**이동 절차**:

1. **파일 생성**:
```bash
# 위의 확장된 버전을 shared/dtos/trading.py로 저장
```

2. **HYPERRSI import 변경**:
```bash
# 변경 전:
from schema.trading import OpenPositionRequest, ClosePositionRequest

# 변경 후:
from shared.dtos.trading import OpenPositionRequest, ClosePositionRequest
```

3. **GRID import 추가**:
```python
# GRID 프로젝트에서 트레이딩 DTO 사용
from shared.dtos.trading import (
    OpenPositionRequest,
    ClosePositionRequest,
    PositionResponse,
    GridTradingData,
    WinrateDto
)
```

4. **기존 DTO 대체**:
```python
# GRID/dtos/trading_data.py 대체
# 더 이상 필요 없음 → shared/dtos/trading.py 사용
```

---

### 2. Helpers 이동 가이드

#### 2.1 `cache_helper.py` 이동

**📍 현재 파일**: `GRID/helpers/cache_helper.py`

```python
# GRID/helpers/cache_helper.py
from datetime import datetime

def cache_expired(cache_expiry) -> bool:
    return datetime.now() > cache_expiry if cache_expiry else True
```

**✅ 이동 절차**:

1. **파일 복사**:
```bash
mkdir -p shared/helpers
cp GRID/helpers/cache_helper.py shared/helpers/cache_helper.py
```

2. **GRID import 변경**:
```bash
# 변경 전:
from helpers.cache_helper import cache_expired

# 변경 후:
from shared.helpers.cache_helper import cache_expired
```

3. **영향 받는 파일 확인**:
```bash
grep -r "from helpers.cache_helper" GRID/ --include="*.py"
grep -r "from .cache_helper" GRID/helpers/ --include="*.py"
```

4. **HYPERRSI 적용**:
```python
# HYPERRSI에서 캐시 헬퍼 사용
from shared.helpers.cache_helper import cache_expired
```

---

#### 2.2 `path_helper.py` 중복 제거

**⚠️ 문제**: `GRID/helpers/path_helper.py`와 `shared/utils/path_helper.py`가 동일한 내용

**✅ 해결 방법**:

1. **파일 비교**:
```bash
diff GRID/helpers/path_helper.py shared/utils/path_helper.py
# 결과: 거의 동일 (docstring만 차이)
```

2. **GRID에서 shared 버전 사용**:
```bash
# GRID 프로젝트 내 모든 파일에서 import 변경

# 변경 전:
from helpers.path_helper import logs_dir, grid_dir

# 변경 후:
from shared.utils.path_helper import logs_dir, grid_dir
```

3. **영향 받는 파일들**:
```
GRID/main_loop.py
GRID/grid.py
GRID/infra/database.py
GRID/database.py
GRID/plot_chart.py
GRID/repositories/trading_data_repository.py
```

4. **GRID helpers 파일 제거**:
```bash
rm GRID/helpers/path_helper.py
```

5. **검증**:
```bash
cd GRID
python -c "from shared.utils.path_helper import logs_dir; print(logs_dir)"
```

---

#### 2.3 `order_helper.py` 통합 (선택적)

**📍 현재 파일**: `HYPERRSI/src/helpers/order_helper.py`

**주요 기능**:
- Redis 데이터 저장/조회
- Perpetual 종목 정보 조회
- 계약 수량 계산 및 분할

**✅ 통합 방법**:

1. **공통 함수 추출**:
```python
# shared/helpers/order_helper.py
import json
import math
import aiohttp
from typing import Optional, Tuple

async def set_redis_data(redis_client, key: str, data: dict, expiry: int = 144000):
    """Redis 데이터 저장"""
    await redis_client.set(key, json.dumps(data), ex=expiry)

async def get_redis_data(redis_client, key: str) -> Optional[dict]:
    """Redis 데이터 조회"""
    data = await redis_client.get(key)
    return json.loads(data) if data else None

async def get_perpetual_instruments(redis_client, exchange: str = "okx"):
    """Perpetual 종목 정보 조회 (캐시 우선)"""
    cached_data = await get_redis_data(redis_client, f'{exchange}_perpetual_instruments')
    if cached_data:
        return cached_data

    # API 호출 (거래소별 분기)
    if exchange == "okx":
        base_url = "https://www.okx.com"
        url = f"{base_url}/api/v5/public/instruments?instType=SWAP"
    # 다른 거래소 추가 가능

    conn = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=conn) as session:
        async with session.get(url) as response:
            data = await response.json()

    if data and 'data' in data:
        await set_redis_data(redis_client, f'{exchange}_perpetual_instruments', data['data'])
        return data['data']

    return None

def get_lot_sizes(instruments: list) -> dict:
    """종목별 계약 단위 정보 정리"""
    lot_sizes = {}
    for instrument in instruments:
        symbol = instrument['instId']
        lot_size = float(instrument['lotSz'])
        contract_value = float(instrument['ctVal'])
        base_currency = symbol.split('-')[0]
        lot_sizes[symbol] = (lot_size, contract_value, base_currency)
    return lot_sizes

async def round_to_qty(symbol: str, qty: float, lot_sizes: dict) -> int:
    """수량을 계약 수로 변환 (내림)"""
    if symbol not in lot_sizes:
        raise ValueError(f"{symbol} is not a valid instrument.")

    lot_size, contract_value, _ = lot_sizes[symbol]
    contracts = qty / contract_value
    return math.floor(contracts)

def split_contracts(total_contracts: int, ratios: Tuple[float, ...] = (0.3, 0.3, 0.4)) -> Tuple[int, ...]:
    """계약 수를 비율로 분할"""
    result = []
    remaining = total_contracts

    for i, ratio in enumerate(ratios[:-1]):
        qty = math.floor(total_contracts * ratio)
        result.append(qty)
        remaining -= qty

    result.append(remaining)  # 마지막은 나머지 전부
    return tuple(result)
```

2. **프로젝트별 래퍼 유지**:
```python
# HYPERRSI/src/helpers/order_helper.py
from shared.helpers.order_helper import *
from HYPERRSI.src.api.dependencies import redis_client

# 프로젝트 특화 함수만 유지
async def get_symbol_info(symbol: str) -> dict:
    """HYPERRSI 전용: Redis에서 심볼 정보 조회"""
    all_info_key = f"symbol_info:contract_specifications"
    all_info = await redis_client.get(all_info_key)
    if not all_info:
        return None
    # ...
```

---

#### 2.4 `user_id_helper.py` 통합 (선택적)

**📍 현재 파일**: `HYPERRSI/src/helpers/user_id_helper.py` (350+ 줄)

**주요 기능**:
- Telegram ID ↔ OKX UID 변환
- Redis 패턴 매칭
- Supabase DB 조회

**✅ 통합 방법**:

1. **핵심 로직만 공통화**:
```python
# shared/helpers/user_id_helper.py
import logging
from typing import Optional

logger = logging.getLogger(__name__)

async def get_uid_from_telegram_id(
    redis_client,
    telegram_id: str,
    uid_key_pattern: str = "user:{telegram_id}:okx_uid"
) -> Optional[str]:
    """텔레그램 ID → UID 변환 (Redis)"""
    try:
        key = uid_key_pattern.format(telegram_id=telegram_id)
        uid = await redis_client.get(key)

        if uid:
            return uid.decode('utf-8') if isinstance(uid, bytes) else uid
        return None

    except Exception as e:
        logger.error(f"Error converting telegram_id {telegram_id}: {str(e)}")
        return None

async def get_telegram_id_from_uid(
    redis_client,
    uid: str,
    scan_pattern: str = "user:*:okx_uid"
) -> Optional[str]:
    """UID → 텔레그램 ID 변환 (Redis 스캔)"""
    if not uid:
        return None

    uid_str = str(uid)

    try:
        keys = await redis_client.keys(scan_pattern)

        for key in keys:
            key_str = key.decode() if isinstance(key, bytes) else str(key)
            stored_uid = await redis_client.get(key)

            if not stored_uid:
                continue

            stored_uid_str = stored_uid.decode() if isinstance(stored_uid, bytes) else str(stored_uid)

            if stored_uid_str == uid_str:
                parts = key_str.split(':')
                if len(parts) >= 3 and parts[0] == 'user':
                    telegram_id = parts[1]
                    if telegram_id.isdigit() and 6 <= len(telegram_id) < 15:
                        return telegram_id

        return None

    except Exception as e:
        logger.error(f"Error converting uid {uid}: {str(e)}")
        return None
```

2. **프로젝트별 확장**:
```python
# HYPERRSI/src/helpers/user_id_helper.py
from shared.helpers.user_id_helper import (
    get_uid_from_telegram_id,
    get_telegram_id_from_uid
)
from HYPERRSI.src.core.database import redis_client

# HYPERRSI 특화 함수 (Supabase 연동 등)
async def get_telegram_id_from_uid_with_db(uid: str) -> Optional[str]:
    """UID → 텔레그램 ID (Redis + Supabase)"""
    # Redis 먼저 시도
    telegram_id = await get_telegram_id_from_uid(redis_client, uid)
    if telegram_id:
        return telegram_id

    # Supabase 조회
    # ...
```

---

### 3. Exchange DTO 통합 (Phase 2)

#### 3.1 `exchange.py` 통합

**📍 현재 파일**: `GRID/dtos/exchange.py`

```python
# GRID/dtos/exchange.py
from typing import Optional
from pydantic import BaseModel, Field

class ApiKeyDto(BaseModel):
    api_key: str = Field(examples=["Exchange api key"])
    secret_key: str = Field(examples=["Exchange secret key"])
    password: Optional[str] = Field(None, examples=["Exchange password"])

class ApiKeys(BaseModel):
    okx: ApiKeyDto
    binance: ApiKeyDto
    upbit: ApiKeyDto
    bitget: ApiKeyDto
    binance_spot: ApiKeyDto
    bitget_spot: ApiKeyDto
    okx_spot: ApiKeyDto

class ExchangeApiKeyDto(BaseModel):
    exchange_name: str = Field(examples=["okx","binance", "upbit", "bitget", ...])
    api_key: str
    secret_key: str
    password: Optional[str] = None

class WalletDto(BaseModel):
    exchange_name: str
    total_balance: float
    wallet_balance: Optional[float] = None
    total_unrealized_profit: Optional[float] = None
```

**✅ 개선 및 확장**:

```python
# shared/dtos/exchange.py
"""
거래소 공통 DTO

거래소 API 키, 지갑 정보 등 공통 데이터 모델
"""
from typing import Optional, Dict
from pydantic import BaseModel, Field
from enum import Enum

class ExchangeName(str, Enum):
    """지원 거래소 목록"""
    OKX = "okx"
    BINANCE = "binance"
    UPBIT = "upbit"
    BITGET = "bitget"
    OKX_SPOT = "okx_spot"
    BINANCE_SPOT = "binance_spot"
    BITGET_SPOT = "bitget_spot"

class ApiKeyDto(BaseModel):
    """API 키 정보"""
    api_key: str = Field(..., description="API Key")
    secret_key: str = Field(..., description="Secret Key")
    password: Optional[str] = Field(None, description="Passphrase (OKX 등)")

    class Config:
        json_schema_extra = {
            "example": {
                "api_key": "your-api-key",
                "secret_key": "your-secret-key",
                "password": "your-passphrase"
            }
        }

class ExchangeApiKeyDto(BaseModel):
    """거래소별 API 키"""
    exchange_name: ExchangeName = Field(..., description="거래소 이름")
    api_key: str = Field(..., description="API Key")
    secret_key: str = Field(..., description="Secret Key")
    password: Optional[str] = Field(None, description="Passphrase")
    user_id: Optional[str] = Field(None, description="사용자 ID")

class AllApiKeys(BaseModel):
    """모든 거래소 API 키 (선택적)"""
    okx: Optional[ApiKeyDto] = None
    binance: Optional[ApiKeyDto] = None
    upbit: Optional[ApiKeyDto] = None
    bitget: Optional[ApiKeyDto] = None
    okx_spot: Optional[ApiKeyDto] = None
    binance_spot: Optional[ApiKeyDto] = None
    bitget_spot: Optional[ApiKeyDto] = None

class WalletDto(BaseModel):
    """지갑 정보"""
    exchange_name: ExchangeName = Field(..., description="거래소 이름")
    total_balance: float = Field(..., description="총 잔고")
    available_balance: Optional[float] = Field(None, description="사용 가능 잔고")
    wallet_balance: Optional[float] = Field(None, description="지갑 잔고")
    total_unrealized_profit: Optional[float] = Field(None, description="미실현 손익")
    margin_ratio: Optional[float] = Field(None, description="증거금 비율")

class BalanceDto(BaseModel):
    """거래소 잔고 상세"""
    currency: str = Field(..., description="통화")
    total: float = Field(..., description="총량")
    available: float = Field(..., description="사용 가능")
    frozen: float = Field(0.0, description="동결")
    usd_value: Optional[float] = Field(None, description="USD 환산 가치")
```

**이동 절차**:

1. **파일 생성**:
```bash
# 개선된 버전을 shared/dtos/exchange.py로 저장
```

2. **GRID import 변경**:
```bash
# 변경 전:
from dtos.exchange import ExchangeApiKeyDto, WalletDto, ApiKeys

# 변경 후:
from shared.dtos.exchange import (
    ExchangeApiKeyDto,
    WalletDto,
    AllApiKeys,
    ExchangeName
)
```

3. **영향 받는 파일**:
```
GRID/routes/exchange_route.py
GRID/services/exchange_service.py
```

---

### 4. Bot State DTO 통합 (Phase 2)

#### 4.1 `bot_state.py` 통합

**📍 현재 파일**: `GRID/dtos/bot_state.py`

```python
# GRID/dtos/bot_state.py
from pydantic import BaseModel, Field
from typing import Optional

class BotStateError(BaseModel):
    name: str
    message: str
    meta: Optional[dict] = Field(None, examples=[{}])

class BotStateDto(BaseModel):
    key: str  # {exchange_name}_{enter_strategy}
    exchange_name: str
    user_id: str
    enter_strategy: Optional[str] = 'long'
    is_running: bool
    error: Optional[BotStateError] = None

class BotStateKeyDto(BaseModel):
    exchange_name: str
    enter_strategy: Optional[str] = 'long'
    user_id: str
```

**✅ 확장 버전**:

```python
# shared/dtos/bot_state.py
"""
봇 상태 관리 DTO

트레이딩 봇의 실행 상태, 에러 정보 등을 관리
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum

class BotStatus(str, Enum):
    """봇 상태"""
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    STARTING = "starting"
    STOPPING = "stopping"

class ErrorSeverity(str, Enum):
    """에러 심각도"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class BotStateError(BaseModel):
    """봇 에러 정보"""
    name: str = Field(..., description="에러 이름")
    message: str = Field(..., description="에러 메시지")
    severity: ErrorSeverity = Field(ErrorSeverity.MEDIUM, description="심각도")
    timestamp: Optional[datetime] = Field(None, description="발생 시각")
    meta: Optional[dict] = Field(None, description="추가 메타데이터")
    traceback: Optional[str] = Field(None, description="스택 트레이스")

class BotStateDto(BaseModel):
    """봇 상태 정보"""
    key: str = Field(..., description="상태 키 (예: binance_long_user123)")
    exchange_name: str = Field(..., description="거래소 이름")
    user_id: str = Field(..., description="사용자 ID")
    enter_strategy: Optional[str] = Field('long', description="진입 전략")
    status: BotStatus = Field(BotStatus.STOPPED, description="봇 상태")
    is_running: bool = Field(False, description="실행 여부")
    error: Optional[BotStateError] = Field(None, description="에러 정보")
    started_at: Optional[datetime] = Field(None, description="시작 시각")
    stopped_at: Optional[datetime] = Field(None, description="종료 시각")
    total_trades: int = Field(0, description="총 거래 횟수")

    @property
    def uptime_seconds(self) -> Optional[int]:
        """가동 시간 (초)"""
        if self.started_at and self.is_running:
            return int((datetime.now() - self.started_at).total_seconds())
        return None

class BotStateKeyDto(BaseModel):
    """봇 상태 키"""
    exchange_name: str
    enter_strategy: Optional[str] = 'long'
    user_id: str

    def generate_key(self) -> str:
        """상태 키 생성"""
        return f"{self.exchange_name}_{self.enter_strategy}_{self.user_id}"

class BotStatesResponse(BaseModel):
    """여러 봇 상태 응답"""
    states: List[BotStateDto]
    total: int
    running_count: int
    error_count: int
```

**이동 절차**:

1. **파일 생성**:
```bash
# 확장된 버전을 shared/dtos/bot_state.py로 저장
```

2. **GRID import 변경**:
```bash
# 변경 전:
from dtos.bot_state import BotStateDto, BotStateKeyDto

# 변경 후:
from shared.dtos.bot_state import (
    BotStateDto,
    BotStateKeyDto,
    BotStatus,
    BotStateError
)
```

3. **영향 받는 파일**:
```
GRID/routes/bot_state_route.py
GRID/routes/feature_route.py
GRID/services/bot_state_service.py
```

---

## 🤖 마이그레이션 스크립트

### 자동 Import 변경 스크립트

```bash
#!/bin/bash
# migrate_imports.sh

# Phase 1: DTOs 마이그레이션

echo "=== Phase 1: DTOs 마이그레이션 시작 ==="

# 1. response.py import 변경
echo "1. response.py import 변경 중..."
find GRID -type f -name "*.py" -exec sed -i '' 's/from dtos\.response import/from shared.dtos.response import/g' {} +

# 2. auth.py import 변경
echo "2. auth.py import 변경 중..."
find GRID -type f -name "*.py" -exec sed -i '' 's/from dtos\.auth import/from shared.dtos.auth import/g' {} +

# 3. telegram.py import 변경
echo "3. telegram.py import 변경 중..."
find GRID -type f -name "*.py" -exec sed -i '' 's/from dtos\.telegram import/from shared.dtos.telegram import/g' {} +

# 4. user.py import 변경
echo "4. user.py import 변경 중..."
find GRID -type f -name "*.py" -exec sed -i '' 's/from dtos\.user import/from shared.dtos.user import/g' {} +

# HYPERRSI schema 변경
echo "5. HYPERRSI schema import 변경 중..."
find HYPERRSI -type f -name "*.py" -exec sed -i '' 's/from schema\.trading import/from shared.dtos.trading import/g' {} +

# Phase 2: Helpers 마이그레이션
echo ""
echo "=== Phase 2: Helpers 마이그레이션 시작 ==="

# 1. cache_helper.py import 변경
echo "1. cache_helper.py import 변경 중..."
find GRID -type f -name "*.py" -exec sed -i '' 's/from helpers\.cache_helper import/from shared.helpers.cache_helper import/g' {} +

# 2. path_helper.py import 변경
echo "2. path_helper.py import 변경 중..."
find GRID -type f -name "*.py" -exec sed -i '' 's/from helpers\.path_helper import/from shared.utils.path_helper import/g' {} +
find GRID -type f -name "*.py" -exec sed -i '' 's/from shared\.utils import path_helper/from shared.utils.path_helper import logs_dir, grid_dir/g' {} +

echo ""
echo "✅ Import 변경 완료!"
echo ""
echo "다음 단계:"
echo "1. 변경 사항 검토: git diff"
echo "2. 테스트 실행: pytest"
echo "3. 문제 없으면 커밋"
```

### 파일 복사 스크립트

```bash
#!/bin/bash
# copy_shared_files.sh

echo "=== 공통 파일 복사 시작 ==="

# shared/dtos 디렉토리 생성
mkdir -p shared/dtos
mkdir -p shared/helpers

# DTOs 복사
echo "1. DTOs 복사 중..."
cp GRID/dtos/response.py shared/dtos/response.py
cp GRID/dtos/auth.py shared/dtos/auth.py
cp GRID/dtos/telegram.py shared/dtos/telegram.py

# user.py는 개선된 버전 사용 (수동 작업 필요)
echo "⚠️  user.py는 수동으로 개선된 버전을 작성하세요."

# trading.py는 HYPERRSI 기반으로 확장 (수동 작업 필요)
echo "⚠️  trading.py는 수동으로 확장된 버전을 작성하세요."

# Helpers 복사
echo "2. Helpers 복사 중..."
cp GRID/helpers/cache_helper.py shared/helpers/cache_helper.py

# path_helper.py는 이미 존재하므로 스킵
echo "✓ path_helper.py는 이미 shared/utils/에 존재합니다."

echo ""
echo "✅ 파일 복사 완료!"
echo ""
echo "다음 단계:"
echo "1. user.py 수동 작성"
echo "2. trading.py 수동 작성"
echo "3. exchange.py 수동 작성"
echo "4. bot_state.py 수동 작성"
```

### 검증 스크립트

```bash
#!/bin/bash
# verify_migration.sh

echo "=== 마이그레이션 검증 시작 ==="

# Python import 테스트
echo "1. Python import 테스트..."

python3 << EOF
try:
    # DTOs
    from shared.dtos.response import ResponseDto
    from shared.dtos.auth import LoginDto, SignupDto
    from shared.dtos.telegram import TelegramTokenDto
    from shared.dtos.user import UserDto, UserCreateDto

    # Helpers
    from shared.helpers.cache_helper import cache_expired
    from shared.utils.path_helper import logs_dir, grid_dir

    print("✅ 모든 import 성공!")

except ImportError as e:
    print(f"❌ Import 실패: {e}")
    exit(1)
EOF

# 중복 정의 확인
echo ""
echo "2. 중복 정의 확인..."

# ResponseDto 중복 체크
grep -r "class ResponseDto" GRID/dtos/ HYPERRSI/ 2>/dev/null | grep -v __pycache__
if [ $? -eq 0 ]; then
    echo "⚠️  ResponseDto 중복 정의 발견! 제거가 필요합니다."
else
    echo "✅ ResponseDto 중복 없음"
fi

# path_helper 중복 체크
if [ -f "GRID/helpers/path_helper.py" ]; then
    echo "⚠️  GRID/helpers/path_helper.py가 아직 존재합니다. 제거하세요."
else
    echo "✅ path_helper.py 중복 없음"
fi

echo ""
echo "3. Import 패턴 확인..."

# 잘못된 import 패턴 찾기
echo "잘못된 import 패턴 검색 중..."
grep -r "from dtos\." GRID/ --include="*.py" | grep -v __pycache__ | grep -v "\.pyc"
grep -r "from helpers\." GRID/ --include="*.py" | grep -v __pycache__ | grep -v "\.pyc"
grep -r "from schema\." HYPERRSI/ --include="*.py" | grep -v __pycache__ | grep -v "\.pyc"

if [ $? -eq 0 ]; then
    echo "⚠️  변경되지 않은 import가 있습니다!"
else
    echo "✅ 모든 import가 올바르게 변경됨"
fi

echo ""
echo "=== 검증 완료 ==="
```

---

## ✅ 테스트 체크리스트

### Phase 1 테스트

#### DTOs 테스트
```python
# test_shared_dtos.py
import pytest
from shared.dtos.response import ResponseDto
from shared.dtos.auth import LoginDto, SignupDto
from shared.dtos.telegram import TelegramTokenDto
from shared.dtos.user import UserDto, UserCreateDto

def test_response_dto():
    """ResponseDto 테스트"""
    response = ResponseDto[dict](
        success=True,
        message="성공",
        data={"key": "value"}
    )
    assert response.success == True
    assert response.data["key"] == "value"

def test_auth_dto():
    """Auth DTO 테스트"""
    signup = SignupDto(
        user_id="test_user",
        exchange_name="okx",
        api_key="test_key",
        secret_key="test_secret"
    )
    assert signup.user_id == "test_user"

def test_telegram_dto():
    """Telegram DTO 테스트"""
    telegram = TelegramTokenDto(
        exchange_name="binance",
        token="test_token"
    )
    assert telegram.exchange_name == "binance"

def test_user_dto():
    """User DTO 테스트"""
    user = UserCreateDto(
        username="testuser",
        password="testpass"
    )
    assert user.username == "testuser"
```

#### Helpers 테스트
```python
# test_shared_helpers.py
import pytest
from datetime import datetime, timedelta
from shared.helpers.cache_helper import cache_expired
from shared.utils.path_helper import logs_dir, grid_dir

def test_cache_expired():
    """캐시 만료 테스트"""
    # 만료된 시간
    past_time = datetime.now() - timedelta(hours=1)
    assert cache_expired(past_time) == True

    # 유효한 시간
    future_time = datetime.now() + timedelta(hours=1)
    assert cache_expired(future_time) == False

    # None (항상 만료)
    assert cache_expired(None) == True

def test_path_helper():
    """경로 헬퍼 테스트"""
    assert logs_dir.exists()
    assert grid_dir.exists()
    print(f"Logs dir: {logs_dir}")
    print(f"Grid dir: {grid_dir}")
```

### Phase 2 테스트

#### Trading DTO 테스트
```python
# test_trading_dtos.py
import pytest
from shared.dtos.trading import (
    OpenPositionRequest,
    ClosePositionRequest,
    PositionResponse,
    PositionSide
)

def test_open_position_request():
    """포지션 오픈 요청 테스트"""
    request = OpenPositionRequest(
        user_id="user123",
        symbol="BTC-USDT-SWAP",
        direction=PositionSide.LONG,
        size=0.1,
        leverage=10.0,
        stop_loss=40000.0,
        take_profit=[45000.0, 50000.0]
    )
    assert request.symbol == "BTC-USDT-SWAP"
    assert request.direction == PositionSide.LONG

def test_close_position_request():
    """포지션 청산 요청 테스트"""
    request = ClosePositionRequest(
        user_id="user123",
        symbol="BTC-USDT-SWAP",
        percent=50.0,
        side=PositionSide.LONG
    )
    assert request.percent == 50.0

def test_position_response():
    """포지션 응답 테스트"""
    response = PositionResponse(
        symbol="BTC-USDT-SWAP",
        side=PositionSide.LONG,
        size=0.1,
        entry_price=42000.0,
        leverage=10.0,
        sl_price=40000.0,
        tp_prices=[45000.0, 50000.0],
        order_id="12345"
    )
    assert response.symbol == "BTC-USDT-SWAP"
    assert response.leverage == 10.0
```

### 통합 테스트

```bash
#!/bin/bash
# run_integration_tests.sh

echo "=== 통합 테스트 시작 ==="

# 1. GRID 프로젝트 테스트
echo "1. GRID 프로젝트 테스트..."
cd GRID
python -m pytest -v || { echo "❌ GRID 테스트 실패"; exit 1; }

# 2. HYPERRSI 프로젝트 테스트
echo ""
echo "2. HYPERRSI 프로젝트 테스트..."
cd ../HYPERRSI
python -m pytest -v || { echo "❌ HYPERRSI 테스트 실패"; exit 1; }

# 3. shared 모듈 테스트
echo ""
echo "3. shared 모듈 테스트..."
cd ..
python -m pytest tests/test_shared_*.py -v || { echo "❌ shared 테스트 실패"; exit 1; }

echo ""
echo "✅ 모든 테스트 통과!"
```

---

## 📈 예상 효과

### 정량적 효과

| 항목 | 현재 | 목표 | 개선율 |
|------|------|------|--------|
| **중복 코드** | ~40% | ~10% | -75% |
| **DTO 파일 수** | 15개 | 8개 | -47% |
| **Helper 파일 수** | 6개 | 4개 | -33% |
| **Import 복잡도** | 높음 | 낮음 | -50% |
| **유지보수 시간** | 기준 | -40% | 40% 단축 |

### 정성적 효과

#### ✅ 개발 효율성
- **코드 재사용**: 새 기능 추가 시 공통 DTO 활용
- **일관성**: 동일한 데이터 구조 사용으로 버그 감소
- **학습 곡선**: 신규 개발자 온보딩 시간 단축

#### ✅ 유지보수성
- **단일 진실 공급원**: 공통 로직 한 곳에서 관리
- **변경 영향 최소화**: 수정 시 한 곳만 변경
- **디버깅 효율**: 문제 발생 시 추적 용이

#### ✅ 확장성
- **새 거래소 추가**: 공통 인터페이스 활용
- **새 봇 타입**: 기존 DTO/Helper 재사용
- **멀티 프로젝트**: 다른 프로젝트에서도 shared 사용 가능

---

## 🔄 롤백 계획

### 문제 발생 시 롤백

```bash
#!/bin/bash
# rollback.sh

echo "=== 마이그레이션 롤백 시작 ==="

# Git을 사용하는 경우
git checkout HEAD -- GRID/
git checkout HEAD -- HYPERRSI/
git checkout HEAD -- shared/

echo "✅ 롤백 완료!"

# 또는 백업에서 복원
# cp -r backup/GRID ./
# cp -r backup/HYPERRSI ./
# cp -r backup/shared ./
```

### 백업 스크립트

```bash
#!/bin/bash
# backup_before_migration.sh

BACKUP_DIR="migration_backup_$(date +%Y%m%d_%H%M%S)"

echo "=== 마이그레이션 전 백업 생성 ==="
echo "백업 위치: $BACKUP_DIR"

mkdir -p $BACKUP_DIR
cp -r GRID $BACKUP_DIR/
cp -r HYPERRSI $BACKUP_DIR/
cp -r shared $BACKUP_DIR/

echo "✅ 백업 완료!"
echo "롤백 필요 시: cp -r $BACKUP_DIR/* ./"
```

---

## 📞 문제 해결 가이드

### 자주 발생하는 문제

#### 1. Import Error 발생
```python
# 에러: ModuleNotFoundError: No module named 'shared'

# 해결: PYTHONPATH 설정
export PYTHONPATH="${PYTHONPATH}:/path/to/TradingBoost-Strategy"

# 또는 프로젝트별 설정
cd GRID
export PYTHONPATH="${PYTHONPATH}:$(pwd)/.."
```

#### 2. 순환 Import 발생
```python
# 에러: ImportError: cannot import name 'X' from partially initialized module

# 해결: import 순서 조정, 지연 import 사용
def some_function():
    from shared.dtos.trading import OpenPositionRequest  # 함수 내부에서 import
    # ...
```

#### 3. Type Hint 오류
```python
# 에러: NameError: name 'PositionSide' is not defined

# 해결: TYPE_CHECKING 사용
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from shared.dtos.trading import PositionSide
```

#### 4. Pydantic 버전 충돌
```bash
# 에러: pydantic.errors.ConfigError

# 해결: Pydantic V2 문법 사용
# Pydantic V1
class Config:
    orm_mode = True

# Pydantic V2
model_config = ConfigDict(from_attributes=True)
```

---

## 🎯 다음 단계

### 단기 (1-2주)
1. ✅ Phase 1 완료: DTOs, Helpers 이동
2. ✅ 테스트 작성 및 검증
3. ✅ 문서 업데이트
1. 🔄 Phase 2 진행: Trading Schema, Exchange DTO 통합
2. 🔄 Bot State 표준화
3. 🔄 Config 통합
3. 📋 모니터링 및 로깅 통합

---

## 📚 참고 자료

### 프로젝트 문서
- [GRID README](../GRID/README.md)
- [HYPERRSI README](../HYPERRSI/README.md)
- [Shared Config](../shared/config.py)

### 기술 문서
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [FastAPI Best Practices](https://fastapi.tiangolo.com/tutorial/)
- [Python Import System](https://docs.python.org/3/reference/import.html)

---

## 📝 변경 이력

| 날짜 | 버전 | 변경 내용 | 작성자 |
|------|------|----------|--------|
| 2025-10-05 | 1.0.0 | 최초 작성 | System |

---

## 👥 기여자

이 문서에 대한 피드백이나 개선 사항이 있다면 이슈를 생성해주세요.

---

**📌 주의사항**:
- 마이그레이션 전 반드시 백업 생성
- 단계별로 진행하며 각 단계마다 테스트
- Git 커밋을 작은 단위로 자주 수행

