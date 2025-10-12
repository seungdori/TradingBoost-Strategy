# Position & Order Management Microservice

실시간 포지션/주문 추적 및 관리 마이크로서비스

## 🎯 개요

WebSocket 기반 실시간 포지션/주문 추적, Pub/Sub 이벤트 시스템, Trailing Stop, 조건부 주문 취소 등을 제공하는 마이크로서비스입니다.

### 주요 기능

1. **실시간 WebSocket 추적**
   - 포지션 업데이트 실시간 모니터링
   - 주문 체결/취소 실시간 추적
   - 가격 업데이트 실시간 수신

2. **Redis Pub/Sub 이벤트 시스템**
   - `positions:{user_id}:{exchange}:{symbol}` 채널
   - `orders:{user_id}:{exchange}` 채널
   - `prices:{exchange}:{symbol}` 채널
   - `trailing_stops:{user_id}` 채널
   - `conditional_rules:{user_id}` 채널

3. **Trailing Stop 관리**
   - 가격 기반 자동 활성화
   - 동적 Stop Price 조정
   - 트리거 시 자동 주문 실행

4. **조건부 주문 취소**
   - Order A 체결 시 Order B 자동 취소
   - 다중 주문 연계 취소
   - 조건 기반 자동 실행

5. **HYPERRSI/GRID 통합**
   - HYPERRSI: DCA, Hedge, TP/SL, 쿨다운, Redis 설정 관리
   - GRID: Grid Level 관리 (0-20 levels), 거래소별 분기 처리

---

## 🏗️ 아키텍처

**⚠️ 독립 마이크로서비스** - TradingBoost-Strategy 모노레포의 최상위 디렉토리에 위치

```
position-order-service/           # 독립 마이크로서비스
├── core/
│   ├── event_types.py           # 이벤트 타입 정의 (Pydantic models)
│   ├── websocket_manager.py     # WebSocket 연결 관리
│   └── pubsub_manager.py        # Redis Pub/Sub 브로커
├── managers/
│   ├── position_tracker.py      # 실시간 포지션 추적
│   ├── order_tracker.py         # 실시간 주문 추적
│   ├── trailing_stop_manager.py # Trailing stop 로직
│   └── conditional_cancellation.py # 조건부 주문 취소
├── workers/
│   ├── active_user_manager.py   # 🆕 봇 활성 사용자 자동 추적
│   └── user_tracker.py          # 구형 포지션 기반 추적 (deprecated)
├── api/
│   ├── schemas.py               # Request/Response 스키마
│   └── routes.py                # FastAPI 엔드포인트
├── integrations/
│   ├── hyperrsi_adapter.py      # HYPERRSI 로직 통합
│   └── grid_adapter.py          # GRID 로직 통합
├── main.py                      # 서비스 진입점
└── requirements.txt             # 독립 의존성 목록
```

**공유 모듈 의존성**: `shared/` 디렉토리의 공통 모듈 활용 (config, logging, exchange APIs 등)

---

## 🚀 설치 및 실행

### 1. 빠른 시작 (Setup Script)

```bash
cd position-order-service

# 자동 설치 (권장)
chmod +x scripts/setup.sh
./scripts/setup.sh

# .env 파일 설정
vim .env  # DATABASE_URL, REDIS_HOST 등 설정

# PostgreSQL 사용 시 (옵션)
chmod +x scripts/init_db.sh
./scripts/init_db.sh

# 서비스 시작
chmod +x scripts/start.sh
./scripts/start.sh
```

### 2. 수동 설치

```bash
cd position-order-service

# 1. 의존성 설치
pip install -r requirements.txt

# 2. 환경 설정
cp .env.example .env
vim .env  # 설정 편집

# 3. PostgreSQL 초기화 (옵션)
python -c "from database.connection import init_database; import asyncio; asyncio.run(init_database())"

# 4. 서비스 실행
python main.py --port 8020
```

### 3. Health Check

```bash
curl http://localhost:8020/health
```

### 3. API 사용 예제

#### A. 주문 취소

```bash
curl -X POST http://localhost:8020/api/v1/orders/cancel \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user123",
    "exchange": "okx",
    "symbol": "BTC-USDT-SWAP",
    "order_id": "12345",
    "order_type": "stop_loss",
    "side": "buy"
  }'
```

#### B. Trailing Stop 설정

```bash
curl -X POST http://localhost:8020/api/v1/trailing-stops \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user123",
    "exchange": "okx",
    "symbol": "BTC-USDT-SWAP",
    "side": "long",
    "activation_price": 50000,
    "callback_rate": 0.02,
    "size": 0.1
  }'
```

#### C. 조건부 주문 취소 규칙

```bash
curl -X POST http://localhost:8020/api/v1/conditional-rules \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user123",
    "exchange": "okx",
    "trigger_order_id": "order_A",
    "cancel_order_ids": ["order_B", "order_C"],
    "condition": "filled"
  }'
```

#### D. 현재 포지션 조회

```bash
curl http://localhost:8020/api/v1/positions/user123/okx?symbol=BTC-USDT-SWAP
```

#### E. 미체결 주문 조회

```bash
curl http://localhost:8020/api/v1/orders/user123/okx/open?symbol=BTC-USDT-SWAP
```

---

## 📊 Redis 스키마

### 실시간 상태 저장

```
# 포지션
positions:realtime:{user_id}:{exchange}:{symbol}:{side}
  - position_id, size, entry_price, current_price, unrealized_pnl, leverage, grid_level, etc.

# 주문
orders:realtime:{user_id}:{exchange}:{order_id}
  - order_id, symbol, side, order_type, quantity, price, filled_qty, status, etc.

# 미체결 주문 인덱스
orders:open:{user_id}:{exchange}
  - Set of open order IDs

# 완료 주문 히스토리
orders:closed:{user_id}:{exchange}
  - List of closed order data (최근 1000개)

# Trailing Stop
trailing_stops:{user_id}:{symbol}:{side}
  - activation_price, callback_rate, current_highest/lowest, stop_price, etc.

# 조건부 규칙
conditional_rules:{user_id}:{rule_id}
  - trigger_order_id, cancel_order_ids, condition, etc.
```

### Pub/Sub 채널

```
SUBSCRIBE positions:{user_id}:{exchange}:{symbol}
SUBSCRIBE orders:{user_id}:{exchange}
SUBSCRIBE prices:{exchange}:{symbol}
SUBSCRIBE trailing_stops:{user_id}
SUBSCRIBE conditional_rules:{user_id}
```

---

## 🔌 프로그래밍 방식 사용

### Python 클라이언트 예제

```python
import asyncio
from redis.asyncio import Redis
from shared.services.position_order_service.core.pubsub_manager import PubSubManager
from shared.services.position_order_service.core.event_types import PositionEvent

async def main():
    # Redis 연결
    redis_client = Redis.from_url("redis://localhost:6379/0")

    # PubSub Manager 초기화
    pubsub_manager = PubSubManager(redis_client)
    await pubsub_manager.start()

    # 포지션 이벤트 구독
    async def handle_position_event(event: PositionEvent):
        print(f"Position Update: {event.symbol} {event.side}")
        print(f"  Size: {event.size}")
        print(f"  Entry: {event.entry_price}")
        print(f"  Current: {event.current_price}")
        print(f"  P&L: {event.unrealized_pnl}")

    await pubsub_manager.subscribe_to_positions(
        user_id="user123",
        exchange="okx",
        symbol="BTC-USDT-SWAP",
        callback=handle_position_event
    )

    # 이벤트 대기
    await asyncio.sleep(3600)  # 1시간 대기

    # 정리
    await pubsub_manager.stop()
    await redis_client.close()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 🧩 HYPERRSI/GRID 통합

### HYPERRSI Adapter 사용

```python
from shared.services.position_order_service.integrations.hyperrsi_adapter import HYPERRSIAdapter

# Adapter 초기화
adapter = HYPERRSIAdapter(redis_client)

# 주문 취소 (Algo 주문 자동 감지)
await adapter.cancel_order(
    user_id="user123",
    symbol="BTC-USDT-SWAP",
    order_id="12345",
    order_type="stop_loss"
)

# 포지션 오픈 (DCA, Hedge, TP/SL 지원)
position = await adapter.open_position(
    user_id="user123",
    symbol="BTC-USDT-SWAP",
    direction="long",
    size=0.1,
    leverage=10.0,
    stop_loss=44000.0,
    take_profit=46000.0,
    is_DCA=True,
    is_hedge=False
)

# 포지션 클로즈
await adapter.close_position(
    user_id="user123",
    symbol="BTC-USDT-SWAP",
    direction="long",
    reason="Take profit"
)
```

### GRID Adapter 사용

```python
from shared.services.position_order_service.integrations.grid_adapter import GRIDAdapter

# Adapter 초기화
adapter = GRIDAdapter(redis_client)

# Grid 포지션 초기화 (레벨 5)
await adapter.initialize_grid_position(
    user_id=123,
    exchange="okx",
    symbol="BTC-USDT-SWAP",
    level=5,
    price=45000.0,
    qty=0.05,
    order_id="grid_order_5"
)

# Grid 포지션 조회
grid_data = await adapter.get_grid_position(
    user_id=123,
    exchange="okx",
    symbol="BTC-USDT-SWAP",
    level=5
)

# Grid 포지션 클로즈
await adapter.close_grid_position(
    user_id=123,
    exchange="okx",
    symbol="BTC-USDT-SWAP",
    level=5
)

# 전체 Grid 레벨 조회 (0-20)
all_grids = await adapter.get_all_grid_positions(
    user_id=123,
    exchange="okx",
    symbol="BTC-USDT-SWAP"
)
```

---

## 🤖 Active User Manager (봇 활성 사용자 자동 추적)

### 개요

**핵심 개념**: 포지션이 있는 사용자가 아닌, **봇을 활성화한 사용자**를 지속적으로 모니터링합니다.

- ✅ 새로운 포지션이 생성되면 즉시 감지
- ✅ 포지션이 없어도 계속 추적 (봇 활성화 상태 기준)
- ✅ 자동 사용자 발견 (5분 간격)
- ✅ 자동 심볼 발견 (1분 간격)

### 작동 방식

#### 1. 서비스 시작 시 자동 사용자 로드
```python
# 4가지 Redis 패턴 검사:
# 1. active_users:position_order_service
# 2. user:*:bot:status = "enabled"
# 3. user:*:settings (bot_enabled 필드)
# 4. {exchange}:user:* (API 키 존재 여부)
```

#### 2. Background Workers
```python
# 사용자 스캔 루프 (5분 간격)
- 새로 활성화된 사용자 자동 감지
- WebSocket 연결 자동 시작

# 심볼 발견 루프 (1분 간격)
- 기존 추적 중인 사용자의 새 심볼 감지
- 새 심볼 자동 구독
```

#### 3. API 엔드포인트

**사용자 활성화**:
```bash
curl -X POST http://localhost:8020/api/v1/users/user123/activate \
  -H "Content-Type: application/json" \
  -d '{"exchanges": ["okx", "binance"]}'
```

**사용자 비활성화**:
```bash
curl -X POST http://localhost:8020/api/v1/users/user123/deactivate
```

**활성 사용자 조회**:
```bash
curl http://localhost:8020/api/v1/users/active
```

### Redis 스키마

```
# 활성 사용자 목록
active_users:position_order_service → Set of user IDs

# 봇 상태
user:{user_id}:bot:status → "enabled" | "disabled"

# 거래소 설정
user:{user_id}:bot:exchanges → Set of exchange names

# 감시 목록 (옵션)
user:{user_id}:watchlist:{exchange} → Set of symbols
```

---

## ❓ 자주 묻는 질문 (FAQ)

### Q1: 사용자의 포지션을 계속 감시하나요?
**A**: ✅ **네, 계속 감시합니다!**

- **봇 활성화된 사용자**: 5분마다 자동 스캔, 즉시 추적 시작
- **실시간 WebSocket**: CCXT를 통해 거래소와 실시간 연결
- **Position Tracker**: 포지션 오픈/클로즈/업데이트 모두 실시간 감지
- **Order Tracker**: 주문 생성/체결/취소 모두 실시간 추적
- **자동 심볼 발견**: 1분마다 새 포지션 감지

### Q2: 주문도 계속 감시하나요?
**A**: ✅ **네, 모두 감시합니다!**

- **실시간 주문 추적**: WebSocket으로 주문 상태 변화 즉시 감지
- **자동 업데이트**: 주문 체결/부분 체결/취소 모두 실시간 Redis 저장
- **PostgreSQL 영구 저장**: 모든 주문 히스토리 데이터베이스에 기록
- **Conditional Rules**: 조건부 주문 취소 자동 실행

### Q3: DB 저장은 어떻게 되나요?
**A**: ✅ **2단계 저장 구조**

#### 1단계: Redis (실시간 상태)
```
positions:realtime:{user_id}:{exchange}:{symbol}:{side}
orders:realtime:{user_id}:{exchange}:{order_id}
trailing_stops:{user_id}:{symbol}:{side}
```
- **목적**: 초고속 실시간 조회
- **TTL**: 24시간 (자동 만료)

#### 2단계: PostgreSQL (영구 보관)
```sql
position_history  -- 모든 포지션 히스토리
order_history     -- 모든 주문 히스토리
trailing_stop_history  -- Trailing stop 기록
conditional_rule_history  -- 조건부 규칙 실행 기록
```
- **목적**: 히스토리 분석, 통계, 감사
- **영구 보관**: 삭제되지 않음
- **선택 사항**: PostgreSQL 없이도 작동 (Redis만 사용)

### Q4: HYPERRSI와 어떻게 다른가요?
**A**:

| 기능 | HYPERRSI | position-order-service |
|------|----------|------------------------|
| **포지션 추적** | 주문 실행 시에만 | 지속적 실시간 감시 |
| **사용자 발견** | 수동 설정 | 자동 스캔 (5분마다) |
| **DB 저장** | Redis만 | Redis + PostgreSQL |
| **심볼 발견** | 수동 구독 | 자동 발견 (1분마다) |
| **독립 실행** | HYPERRSI에 의존 | 완전 독립 마이크로서비스 |

### Q5: 봇 없이도 실행 가능한가요?
**A**: ✅ **완전히 독립 실행 가능!**

```bash
# 필수 조건
- Python 3.9+
- Redis (실시간 상태)
- PostgreSQL (선택사항 - 영구 저장)

# 최소 실행
cd position-order-service
./scripts/setup.sh
./scripts/start.sh

# 완료! HYPERRSI 없이 독립 실행
```

---

## 🔧 환경 설정

### 필수 환경 변수 (`.env`)

```bash
# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=

# Exchange API (Redis에 저장됨)
# user:{user_id}:api:keys
# - api_key
# - api_secret
# - passphrase
```

### 의존성

```bash
# FastAPI 및 웹 서버
fastapi
uvicorn[standard]

# Redis
redis
aioredis

# Exchange API
ccxt

# 데이터 검증
pydantic
pydantic-settings

# 기타
python-dotenv
```

---

## 📝 API 엔드포인트 목록

### 주문 관리
- `POST /api/v1/orders/cancel` - 주문 취소

### Trailing Stop
- `POST /api/v1/trailing-stops` - Trailing stop 생성
- `GET /api/v1/trailing-stops/{user_id}` - Trailing stop 조회
- `DELETE /api/v1/trailing-stops/{user_id}/{symbol}/{side}` - Trailing stop 삭제

### 조건부 규칙
- `POST /api/v1/conditional-rules` - 조건부 규칙 생성
- `GET /api/v1/conditional-rules/{user_id}` - 조건부 규칙 조회
- `DELETE /api/v1/conditional-rules/{user_id}/{rule_id}` - 조건부 규칙 삭제

### 포지션 조회
- `GET /api/v1/positions/{user_id}/{exchange}?symbol={symbol}` - 현재 포지션 조회

### 주문 조회
- `GET /api/v1/orders/{user_id}/{exchange}/open?symbol={symbol}` - 미체결 주문 조회
- `GET /api/v1/orders/{user_id}/{exchange}/closed?limit={limit}` - 완료 주문 조회

### 서비스 상태
- `GET /api/v1/status` - 서비스 상태 및 헬스
- `GET /health` - Health check

---

## 🧪 테스트

```bash
# Unit tests (TODO)
pytest shared/services/position_order_service/tests/

# Integration tests (TODO)
pytest shared/services/position_order_service/tests/integration/

# Load tests (TODO)
locust -f shared/services/position_order_service/tests/load_test.py
```

---

## 🛠️ 개발 로드맵

### Phase 1: 인프라 구축 ✅
- WebSocket Manager
- Pub/Sub Manager
- Background worker 구조

### Phase 2: 핵심 기능 ✅
- Position Tracker
- Order Tracker
- API 엔드포인트

### Phase 3: 고급 기능 ✅
- Trailing Stop Manager
- Conditional Cancellation Manager
- HYPERRSI/GRID 어댑터

### Phase 4: 통합 및 테스트 ⏳
- 기존 HYPERRSI/GRID와 통합 테스트
- WebSocket 안정성 테스트
- 부하 테스트

### Phase 5: 프로덕션 준비 (예정)
- PostgreSQL 영속성 추가
- Monitoring & Alerting
- Docker 컨테이너화
- Kubernetes 배포 설정

---

## 📄 라이선스

MIT License (TradingBoost-Strategy 프로젝트 라이선스 참조)

---

## 🤝 기여

1. Feature 브랜치 생성: `git checkout -b feature/my-feature`
2. 변경사항 커밋: `git commit -m "Add my feature"`
3. 브랜치 푸시: `git push origin feature/my-feature`
4. Pull Request 생성

---

## 📞 문의

- GitHub Issues: https://github.com/your-repo/TradingBoost-Strategy/issues
- Email: your-email@example.com
