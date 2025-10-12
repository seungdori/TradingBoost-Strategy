# TradingBoost-Strategy 마이크로서비스 아키텍처 분석 및 설계

**작성일**: 2025-10-08
**대상 시스템**: TradingBoost-Strategy (Python 3.9+ 암호화폐 자동매매 시스템)
**현재 상태**: 모노레포 (HYPERRSI + GRID 전략, shared 모듈)

---

## 목차

1. [현재 아키텍처 분석](#1-현재-아키텍처-분석)
2. [제안된 마이크로서비스 구조](#2-제안된-마이크로서비스-구조)
3. [서비스 간 통신 패턴](#3-서비스-간-통신-패턴)
4. [데이터 관리 전략](#4-데이터-관리-전략)
5. [마이그레이션 로드맵](#5-마이그레이션-로드맵)
6. [비동기 아키텍처 패턴](#6-비동기-아키텍처-패턴)
7. [운영 고려사항](#7-운영-고려사항)
8. [최종 권장사항](#8-최종-권장사항)

---

## 1. 현재 아키텍처 분석

### 1.1 모노레포 구조

```
TradingBoost-Strategy/
├── HYPERRSI/              # RSI + 트렌드 기반 전략 (포트 8000)
│   ├── main.py           # FastAPI 앱
│   ├── src/
│   │   ├── api/routes/   # 도메인별 라우터 (trading, order, position, account...)
│   │   ├── core/         # 데이터베이스, 에러 핸들러, Celery 설정
│   │   ├── services/     # 비즈니스 로직 (redis_service, trading_service)
│   │   ├── tasks/        # Celery 백그라운드 작업 (trading_tasks, websocket_tasks)
│   │   ├── data_collector/ # 시장 데이터 수집
│   │   └── trading/      # 거래 실행 로직
│   └── start_celery_worker.sh
│
├── GRID/                  # 그리드 트레이딩 전략 (포트 8012)
│   ├── main.py           # FastAPI 앱
│   ├── strategies/       # 그리드 알고리즘
│   ├── routes/           # API 엔드포인트
│   ├── jobs/             # Celery 작업 + worker_manager (multiprocessing)
│   ├── websocket/        # 실시간 가격 피드
│   ├── handlers/         # 거래소별 핸들러 (Upbit, OKX...)
│   └── services/         # bot_state_service, trading_service
│
└── shared/               # 공통 모듈
    ├── config.py         # 통합 설정 (pydantic-settings)
    ├── exchange_apis/    # CCXT 래퍼 (ExchangeStore)
    ├── database/         # Redis/PostgreSQL 연결 관리
    ├── notifications/    # Telegram 알림
    ├── utils/            # 재시도 로직, 검증 헬퍼
    ├── constants/        # 공유 상수
    └── indicators/       # 기술적 지표
```

### 1.2 기술 스택

- **API 프레임워크**: FastAPI (Python 3.9+)
- **백그라운드 작업**:
  - HYPERRSI: Celery (Redis broker/backend, DB 1)
  - GRID: multiprocessing (spawn/fork)
- **데이터 저장소**:
  - Redis (DB 0: 앱 데이터, DB 1: Celery)
  - PostgreSQL (선택적, 현재 최소 사용)
- **실시간 통신**: WebSockets (OKX, Binance 등)
- **거래소 API**: CCXT (OKX, Binance, Bitget, Upbit, Bybit)

### 1.3 결합도(Coupling) 분석

#### 높은 결합도 영역

**A. Shared 모듈 의존성**

```python
# HYPERRSI/main.py
from shared.config import settings
from shared.logging import get_logger, setup_json_logger
from shared.database.session import init_db, close_db
from shared.database.redis import init_redis, close_redis
from shared.errors import register_exception_handlers
from shared.utils.task_tracker import TaskTracker

# GRID/strategies/grid.py
from shared.utils import parse_bool, parse_timeframe
from shared.validation.trading_validators import check_order_validity
from shared.utils.exchange_precision import round_to_precision
from shared.utils.async_helpers import async_debounce, custom_sleep
```

**결합도 점수**: ⚠️ **높음** (9/10)
- **문제점**:
  - 모든 전략이 shared 모듈에 강하게 의존
  - shared 모듈 변경 시 모든 전략 재배포 필요
  - 독립적인 스케일링 불가능

**B. Redis 상태 공유**

```python
# HYPERRSI/src/tasks/trading_tasks.py
REDIS_KEY_TRADING_STATUS = "user:{okx_uid}:trading:status"
REDIS_KEY_TASK_RUNNING = "user:{okx_uid}:task_running"
REDIS_KEY_SYMBOL_STATUS = "user:{okx_uid}:symbol:{symbol}:status"

# GRID/database/redis_database.py
# 유사한 키 패턴 사용, 중앙 정의 없음
```

**결합도 점수**: ⚠️ **중상** (7/10)
- **문제점**:
  - Redis 키 스키마가 코드에 분산
  - 키 충돌 가능성
  - 트랜잭션 경계 불명확

**C. WebSocket 연결 관리**

```python
# HYPERRSI/src/tasks/websocket_tasks.py
ws_manager = OKXWebsocketManager()  # 싱글톤

# GRID/websocket/okx_ws.py
class OKXWebsocket:
    def __init__(self, api_key, secret_key, passphrase, user_id, exchange_name):
        self.ws_url = "wss://ws.okx.com:8443/ws/v5/private"
```

**결합도 점수**: ⚠️ **중** (5/10)
- **문제점**:
  - WebSocket 연결이 전략별로 중복
  - 실시간 데이터 분배 메커니즘 없음
  - 연결 수 최적화 불가

**D. 거래소 API 클라이언트**

```python
# shared/exchange_apis/exchange_store.py
class ExchangeStore:
    # CCXT 인스턴스 관리
```

**결합도 점수**: ✅ **낮음** (3/10)
- **장점**: 이미 어느 정도 추상화됨
- **개선 여지**: 별도 서비스로 분리 가능

#### 낮은 결합도 영역

**A. 전략 로직**

```python
# HYPERRSI/src/trading/execute_trading_logic.py
# GRID/strategies/grid.py
```

**결합도 점수**: ✅ **매우 낮음** (2/10)
- **장점**: 전략별 비즈니스 로직이 독립적

**B. Telegram 알림**

```python
# shared/notifications/telegram.py
```

**결합도 점수**: ✅ **낮음** (3/10)
- **장점**: 이미 모듈화됨, 서비스로 쉽게 분리 가능

### 1.4 데이터 흐름 분석

```mermaid
graph TD
    A[사용자 요청] -->|HTTP| B[FastAPI HYPERRSI:8000]
    A -->|HTTP| C[FastAPI GRID:8012]

    B --> D[Redis DB 0]
    C --> D

    B --> E[Celery Worker]
    E --> F[Redis DB 1 Broker/Backend]

    C --> G[Multiprocessing Workers]

    E --> H[WebSocket Manager HYPERRSI]
    G --> I[WebSocket Manager GRID]

    H --> J[OKX WebSocket]
    I --> J

    B --> K[CCXT Exchange API]
    C --> K

    B --> L[PostgreSQL Optional]
    C --> L

    E --> M[Telegram Bot]
    G --> M
```

**병목 현상**:
1. **Redis DB 0**: 모든 전략의 상태 데이터 집중
2. **WebSocket 연결**: 전략별 중복 연결
3. **CCXT API 호출**: Rate limit 공유 관리 부재

### 1.5 현재 아키텍처의 강점

✅ **강점**:
1. **모노레포 이점**: 코드 재사용, 일관된 도구 체인
2. **shared 모듈**: DRY 원칙 준수
3. **FastAPI**: 고성능 비동기 API
4. **Redis**: 빠른 상태 관리
5. **Celery/Multiprocessing**: 백그라운드 작업 처리

### 1.6 현재 아키텍처의 약점

❌ **약점**:
1. **스케일링 한계**: 전략별 독립적 스케일링 불가
2. **배포 복잡도**: 한 전략 변경 시 전체 재배포
3. **장애 격리**: 한 전략 장애가 전체 영향 가능
4. **리소스 경쟁**: Redis/WebSocket 리소스 경쟁
5. **테스트 복잡도**: 통합 테스트 시 전체 시스템 필요
6. **기술 스택 고정**: 모든 전략이 동일한 기술 스택 사용

---

## 2. 제안된 마이크로서비스 구조

### 2.1 서비스 분해 원칙

**도메인 주도 설계(DDD) 원칙**:
- **Bounded Context**: 비즈니스 도메인 경계로 분리
- **Single Responsibility**: 각 서비스는 하나의 책임
- **Data Ownership**: 각 서비스는 자신의 데이터 소유
- **Independent Deployment**: 독립적 배포 가능

**암호화폐 트레이딩 도메인 특수성**:
- **저지연 요구사항**: 주문 실행 지연 최소화
- **고가용성**: 24/7 운영 필수
- **데이터 일관성**: 주문/포지션 상태 정합성 보장
- **실시간성**: 시장 데이터 실시간 처리

### 2.2 제안된 서비스 목록

#### 핵심 서비스 (Core Services)

##### 1. **Strategy Execution Service - HYPERRSI** 🎯

**책임**:
- HYPERRSI 전략 실행 로직
- RSI + 트렌드 분석
- 신호 생성 및 검증

**API 엔드포인트**:
```
POST   /api/strategy/hyperrsi/activate
POST   /api/strategy/hyperrsi/deactivate
GET    /api/strategy/hyperrsi/status/{user_id}
GET    /api/strategy/hyperrsi/signals/{user_id}
POST   /api/strategy/hyperrsi/backtest
```

**데이터 소유**:
- Redis: `hyperrsi:{user_id}:*` 키 패턴
- PostgreSQL: `hyperrsi_signals`, `hyperrsi_state` 테이블

**백그라운드 작업**:
- Celery 워커 (전용 큐: `hyperrsi_queue`)

**배포**:
- Docker 컨테이너
- 수평 스케일링: 유저 수에 비례

**포트**: 8001

---

##### 2. **Strategy Execution Service - GRID** 🎯

**책임**:
- GRID 트레이딩 전략 실행
- 그리드 레벨 계산
- 주문 생성 및 모니터링

**API 엔드포인트**:
```
POST   /api/strategy/grid/activate
POST   /api/strategy/grid/deactivate
GET    /api/strategy/grid/status/{user_id}
GET    /api/strategy/grid/levels/{user_id}
POST   /api/strategy/grid/adjust
```

**데이터 소유**:
- Redis: `grid:{user_id}:*` 키 패턴
- PostgreSQL: `grid_levels`, `grid_state` 테이블

**백그라운드 작업**:
- 전용 Celery 워커 또는 asyncio TaskGroup

**배포**:
- Docker 컨테이너
- 수평 스케일링: 유저 수에 비례

**포트**: 8002

---

##### 3. **Market Data Service** 📊

**책임**:
- WebSocket 연결 관리 (통합)
- 실시간 가격 데이터 수집
- 시장 데이터 정규화 및 분배
- 캔들스틱 데이터 생성

**API 엔드포인트**:
```
GET    /api/market/ticker/{exchange}/{symbol}
GET    /api/market/orderbook/{exchange}/{symbol}
GET    /api/market/candles/{exchange}/{symbol}/{timeframe}
WS     /ws/market/subscribe
```

**데이터 소유**:
- Redis: `market:{exchange}:{symbol}:*` (실시간 데이터)
- Redis Streams: 가격 업데이트 이벤트 발행
- PostgreSQL: `market_candles` (히스토리)

**백그라운드 작업**:
- WebSocket 연결 관리자 (asyncio)
- 캔들스틱 집계 작업 (Celery Beat)

**배포**:
- Stateful 서비스 (WebSocket 연결 유지)
- 거래소별 인스턴스 (예: okx-marketdata, binance-marketdata)

**포트**: 8003

---

##### 4. **Order Management Service (OMS)** 📝

**책임**:
- 주문 생성/취소/수정
- 주문 상태 추적
- 체결 내역 기록
- 주문 검증 로직

**API 엔드포인트**:
```
POST   /api/orders/create
POST   /api/orders/cancel/{order_id}
GET    /api/orders/status/{order_id}
GET    /api/orders/list/{user_id}
GET    /api/orders/fills/{order_id}
POST   /api/orders/batch
```

**데이터 소유**:
- Redis: `order:{order_id}:*` (실시간 상태)
- PostgreSQL: `orders`, `order_fills` (영구 저장)

**백그라운드 작업**:
- 주문 체결 모니터링 (WebSocket 이벤트 소비)
- 주문 상태 동기화 (Celery 작업)

**배포**:
- 수평 스케일링 (주문 볼륨에 비례)
- 데이터베이스 샤딩 (user_id 기준)

**포트**: 8004

---

##### 5. **Exchange Gateway Service** 🌐

**책임**:
- CCXT API 추상화 계층
- 거래소별 API 호출 관리
- Rate limiting 및 에러 핸들링
- API 키 관리 (암호화)

**API 엔드포인트**:
```
POST   /api/exchange/execute
GET    /api/exchange/balance/{user_id}/{exchange}
GET    /api/exchange/positions/{user_id}/{exchange}
GET    /api/exchange/markets/{exchange}
POST   /api/exchange/withdraw
```

**데이터 소유**:
- Redis: `exchange:ratelimit:{exchange}:{endpoint}` (Rate limit 카운터)
- PostgreSQL: `exchange_credentials` (암호화된 API 키)
- 메모리 캐시: CCXT 인스턴스 풀

**백그라운드 작업**:
- Rate limit 리셋 (Redis TTL 기반)
- 잔고 동기화 (주기적 폴링)

**배포**:
- 거래소별 전용 인스턴스 (예: okx-gateway, binance-gateway)
- 수평 스케일링 (API 호출 볼륨에 비례)

**포트**: 8005

---

##### 6. **Position Management Service** 📈

**책임**:
- 포지션 상태 추적
- 손익 계산 (PnL)
- 포지션 리스크 모니터링
- 청산가 계산

**API 엔드포인트**:
```
GET    /api/positions/{user_id}
GET    /api/positions/{user_id}/{symbol}
GET    /api/positions/pnl/{user_id}
POST   /api/positions/close/{position_id}
GET    /api/positions/risk/{user_id}
```

**데이터 소유**:
- Redis: `position:{user_id}:{symbol}:*` (실시간)
- PostgreSQL: `positions`, `position_history`

**백그라운드 작업**:
- 실시간 PnL 계산 (Market Data 이벤트 소비)
- 리스크 알림 (Celery Beat)

**배포**:
- Stateful 서비스 (포지션 상태 유지)
- 수평 스케일링 (유저 샤딩)

**포트**: 8006

---

#### 지원 서비스 (Supporting Services)

##### 7. **Notification Service** 📬

**책임**:
- Telegram 봇 관리
- 알림 큐 관리
- 알림 템플릿 렌더링
- 알림 히스토리

**API 엔드포인트**:
```
POST   /api/notifications/send
POST   /api/notifications/broadcast
GET    /api/notifications/history/{user_id}
POST   /api/notifications/subscribe
```

**데이터 소유**:
- Redis: `notification:queue:*` (메시지 큐)
- PostgreSQL: `notification_history`, `notification_preferences`

**백그라운드 작업**:
- Telegram 메시지 발송 (Celery 워커)
- 알림 재시도 로직

**배포**:
- 단일 인스턴스 또는 액티브-스탠바이

**포트**: 8007

---

##### 8. **User & Account Service** 👤

**책임**:
- 사용자 인증/인가
- 거래소 API 키 관리
- 사용자 설정 관리
- 권한 관리

**API 엔드포인트**:
```
POST   /api/users/register
POST   /api/users/login
GET    /api/users/profile/{user_id}
POST   /api/users/credentials
GET    /api/users/settings/{user_id}
PUT    /api/users/settings/{user_id}
```

**데이터 소유**:
- PostgreSQL: `users`, `user_credentials`, `user_settings`
- Redis: `session:{session_id}` (세션)

**백그라운드 작업**:
- 세션 클리닝 (Celery Beat)

**배포**:
- 수평 스케일링 (읽기 복제본)

**포트**: 8008

---

##### 9. **Configuration Service** ⚙️

**책임**:
- 중앙 설정 관리
- Feature flags
- 동적 설정 업데이트
- 설정 버전 관리

**API 엔드포인트**:
```
GET    /api/config/{service}/{key}
POST   /api/config/{service}/{key}
GET    /api/config/features
POST   /api/config/features/{flag}
```

**데이터 소유**:
- PostgreSQL: `service_config`, `feature_flags`
- Redis: 설정 캐시

**배포**:
- 고가용성 (3+ 인스턴스)

**포트**: 8009

---

##### 10. **Analytics & Logging Service** 📊

**책임**:
- 중앙 로그 수집
- 메트릭 집계
- 대시보드 API
- 거래 성과 분석

**API 엔드포인트**:
```
POST   /api/logs/ingest
GET    /api/analytics/performance/{user_id}
GET    /api/analytics/metrics/{service}
GET    /api/analytics/dashboard
```

**데이터 소유**:
- Elasticsearch/Loki: 로그 저장
- InfluxDB/TimescaleDB: 시계열 메트릭
- PostgreSQL: 집계된 분석 데이터

**배포**:
- 별도 인프라 (ELK 스택 또는 Grafana Loki)

**포트**: 8010

---

### 2.3 서비스 다이어그램

```mermaid
graph TB
    subgraph "Client Layer"
        WEB[Web Frontend]
        MOB[Mobile App]
        TG[Telegram Bot]
    end

    subgraph "API Gateway"
        GW[Kong/Traefik/NGINX]
    end

    subgraph "Core Trading Services"
        HYPER[HYPERRSI Service:8001]
        GRID[GRID Service:8002]
        MARKET[Market Data:8003]
        OMS[Order Management:8004]
        EXCH[Exchange Gateway:8005]
        POS[Position Management:8006]
    end

    subgraph "Supporting Services"
        NOTIF[Notification:8007]
        USER[User & Account:8008]
        CONFIG[Configuration:8009]
        ANALYTICS[Analytics:8010]
    end

    subgraph "Infrastructure"
        REDIS[(Redis Cluster)]
        PG[(PostgreSQL)]
        KAFKA[Kafka/Redis Streams]
        ELASTIC[(Elasticsearch)]
    end

    WEB --> GW
    MOB --> GW
    TG --> NOTIF

    GW --> HYPER
    GW --> GRID
    GW --> OMS
    GW --> POS
    GW --> USER

    HYPER --> MARKET
    HYPER --> OMS
    HYPER --> CONFIG

    GRID --> MARKET
    GRID --> OMS
    GRID --> CONFIG

    OMS --> EXCH
    OMS --> POS
    OMS --> KAFKA

    MARKET --> KAFKA
    MARKET --> REDIS

    EXCH --> REDIS
    EXCH --> PG

    POS --> REDIS
    POS --> PG

    HYPER --> REDIS
    GRID --> REDIS

    HYPER --> PG
    GRID --> PG

    NOTIF --> PG
    USER --> PG
    CONFIG --> PG

    ANALYTICS --> ELASTIC
    ANALYTICS --> PG

    All --> KAFKA
```

---

## 3. 서비스 간 통신 패턴

### 3.1 통신 프로토콜 선택

#### A. REST API (동기 통신)

**사용 사례**:
- 사용자 요청 처리 (CRUD 작업)
- 서비스 간 직접 호출 (간단한 쿼리)

**구현**:
```python
# httpx를 사용한 비동기 HTTP 클라이언트
from httpx import AsyncClient
from typing import Any

class ServiceClient:
    def __init__(self, base_url: str, timeout: float = 30.0):
        self.client = AsyncClient(
            base_url=base_url,
            timeout=timeout,
            limits=httpx.Limits(max_connections=100)
        )

    async def get(self, endpoint: str, **kwargs) -> Any:
        response = await self.client.get(endpoint, **kwargs)
        response.raise_for_status()
        return response.json()

    async def post(self, endpoint: str, **kwargs) -> Any:
        response = await self.client.post(endpoint, **kwargs)
        response.raise_for_status()
        return response.json()

# 사용 예시
market_client = ServiceClient("http://market-data-service:8003")
ticker = await market_client.get("/api/market/ticker/okx/BTC-USDT-SWAP")
```

**장점**:
- 간단하고 직관적
- 디버깅 용이
- HTTP 표준 활용

**단점**:
- 동기적 결합
- 서비스 장애 전파
- 네트워크 지연

---

#### B. gRPC (고성능 동기 통신)

**사용 사례**:
- 서비스 간 고빈도 호출 (내부 통신)
- 저지연 요구사항 (주문 실행)

**구현**:
```python
# order_service.proto
syntax = "proto3";

service OrderService {
  rpc CreateOrder(CreateOrderRequest) returns (CreateOrderResponse);
  rpc CancelOrder(CancelOrderRequest) returns (CancelOrderResponse);
  rpc GetOrderStatus(GetOrderStatusRequest) returns (Order);
}

message CreateOrderRequest {
  string user_id = 1;
  string symbol = 2;
  string side = 3;
  double quantity = 4;
  double price = 5;
}

message CreateOrderResponse {
  string order_id = 1;
  string status = 2;
}

# order_client.py
import grpc
from proto import order_service_pb2, order_service_pb2_grpc

async def create_order(user_id: str, symbol: str, side: str, qty: float, price: float):
    async with grpc.aio.insecure_channel('order-service:50051') as channel:
        stub = order_service_pb2_grpc.OrderServiceStub(channel)
        request = order_service_pb2.CreateOrderRequest(
            user_id=user_id, symbol=symbol, side=side,
            quantity=qty, price=price
        )
        response = await stub.CreateOrder(request)
        return response.order_id
```

**장점**:
- 고성능 (Protocol Buffers)
- 타입 안전성
- 양방향 스트리밍 지원

**단점**:
- 학습 곡선
- HTTP/2 인프라 필요
- 디버깅 복잡도

---

#### C. 메시지 큐 (비동기 통신)

**사용 사례**:
- 이벤트 기반 아키텍처
- 느슨한 결합 필요
- 작업 큐

**옵션 1: Redis Streams**

```python
# 이벤트 발행자 (OMS)
import redis.asyncio as aioredis

async def publish_order_filled_event(order_id: str, fill_data: dict):
    redis_client = await aioredis.from_url("redis://localhost:6379")

    event = {
        "order_id": order_id,
        "user_id": fill_data["user_id"],
        "symbol": fill_data["symbol"],
        "filled_qty": fill_data["filled_qty"],
        "fill_price": fill_data["fill_price"],
        "timestamp": time.time()
    }

    await redis_client.xadd(
        "events:order_filled",
        event,
        maxlen=10000  # 최대 10K 이벤트 유지
    )

# 이벤트 소비자 (Position Service)
async def consume_order_events():
    redis_client = await aioredis.from_url("redis://localhost:6379")
    last_id = '0-0'

    while True:
        events = await redis_client.xread(
            {"events:order_filled": last_id},
            count=10,
            block=1000  # 1초 대기
        )

        for stream, messages in events:
            for message_id, data in messages:
                await process_fill_event(data)
                last_id = message_id
```

**장점**:
- Redis 기존 인프라 활용
- 간단한 구현
- 낮은 지연

**단점**:
- 메시지 보증 수준 낮음
- 복잡한 라우팅 어려움

**옵션 2: Apache Kafka**

```python
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
import json

# 프로듀서
async def publish_to_kafka(topic: str, event: dict):
    producer = AIOKafkaProducer(
        bootstrap_servers='kafka:9092',
        value_serializer=lambda v: json.dumps(v).encode('utf-8')
    )
    await producer.start()
    try:
        await producer.send_and_wait(topic, event)
    finally:
        await producer.stop()

# 컨슈머
async def consume_from_kafka(topic: str, group_id: str):
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers='kafka:9092',
        group_id=group_id,
        value_deserializer=lambda m: json.loads(m.decode('utf-8'))
    )
    await consumer.start()
    try:
        async for msg in consumer:
            await process_message(msg.value)
    finally:
        await consumer.stop()
```

**장점**:
- 높은 처리량
- 메시지 영속성
- 복잡한 이벤트 처리

**단점**:
- 운영 복잡도 높음
- 추가 인프라 필요
- 오버킬 가능성

---

### 3.2 통신 패턴 권장사항

| 시나리오 | 권장 프로토콜 | 이유 |
|---------|-------------|------|
| 사용자 API 호출 → 서비스 | REST (FastAPI) | 표준, 간단함 |
| Strategy → OMS 주문 생성 | gRPC | 저지연, 고빈도 |
| OMS → Position 상태 업데이트 | Redis Streams | 비동기, 빠름 |
| Market Data → Strategies 가격 푸시 | Redis Streams | 실시간, 다수 구독자 |
| Notification 알림 큐 | Celery (Redis) | 기존 인프라 |
| 서비스 간 설정 조회 | REST (캐시) | 읽기 중심 |

---

### 3.3 API 계약 예시

#### OMS API 계약 (OpenAPI/Swagger)

```yaml
openapi: 3.0.0
info:
  title: Order Management Service
  version: 1.0.0

paths:
  /api/orders/create:
    post:
      summary: Create a new order
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                user_id:
                  type: string
                symbol:
                  type: string
                side:
                  type: string
                  enum: [buy, sell]
                order_type:
                  type: string
                  enum: [market, limit, stop]
                quantity:
                  type: number
                price:
                  type: number
                  nullable: true
      responses:
        '201':
          description: Order created
          content:
            application/json:
              schema:
                type: object
                properties:
                  order_id:
                    type: string
                  status:
                    type: string
                  created_at:
                    type: string
                    format: date-time
```

#### 이벤트 스키마 (Redis Streams)

```python
from pydantic import BaseModel
from datetime import datetime

class OrderFilledEvent(BaseModel):
    event_type: str = "order.filled"
    order_id: str
    user_id: str
    symbol: str
    side: str
    filled_qty: float
    fill_price: float
    commission: float
    timestamp: datetime
```

---

## 4. 데이터 관리 전략

### 4.1 Database per Service 패턴

**원칙**: 각 서비스는 자신의 데이터베이스를 소유하며, 다른 서비스는 API를 통해서만 접근

#### PostgreSQL 스키마 분리

```sql
-- HYPERRSI Service 전용 스키마
CREATE SCHEMA hyperrsi;

CREATE TABLE hyperrsi.signals (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    signal_type VARCHAR(10),  -- buy, sell
    rsi_value DECIMAL(5,2),
    trend_direction VARCHAR(10),
    created_at TIMESTAMP DEFAULT NOW(),
    INDEX idx_user_symbol (user_id, symbol)
);

CREATE TABLE hyperrsi.state (
    user_id VARCHAR(50) PRIMARY KEY,
    symbol VARCHAR(20),
    is_active BOOLEAN DEFAULT FALSE,
    last_execution TIMESTAMP,
    settings JSONB
);

-- GRID Service 전용 스키마
CREATE SCHEMA grid;

CREATE TABLE grid.levels (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    grid_index INT NOT NULL,
    price DECIMAL(18,8) NOT NULL,
    order_id VARCHAR(50),
    status VARCHAR(20),  -- pending, filled, cancelled
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, symbol, grid_index)
);

-- OMS 전용 스키마
CREATE SCHEMA oms;

CREATE TABLE oms.orders (
    order_id VARCHAR(50) PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL,
    order_type VARCHAR(20),
    quantity DECIMAL(18,8),
    price DECIMAL(18,8),
    filled_qty DECIMAL(18,8) DEFAULT 0,
    status VARCHAR(20),  -- pending, filled, cancelled, failed
    exchange VARCHAR(20),
    exchange_order_id VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    INDEX idx_user_orders (user_id, created_at DESC)
);

CREATE TABLE oms.order_fills (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR(50) REFERENCES oms.orders(order_id),
    fill_qty DECIMAL(18,8),
    fill_price DECIMAL(18,8),
    commission DECIMAL(18,8),
    fill_time TIMESTAMP,
    exchange_fill_id VARCHAR(100)
);
```

---

### 4.2 Redis 키 네임스페이스 전략

**패턴**: `{service}:{domain}:{identifier}:{attribute}`

```python
# Redis 키 스키마 정의 (각 서비스별)

# HYPERRSI Service
HYPERRSI_KEYS = {
    "status": "hyperrsi:status:{user_id}:{symbol}",
    "signal": "hyperrsi:signal:{user_id}:{symbol}:latest",
    "lock": "hyperrsi:lock:{user_id}:{symbol}:{timeframe}",
}

# GRID Service
GRID_KEYS = {
    "levels": "grid:levels:{user_id}:{symbol}",
    "state": "grid:state:{user_id}:{symbol}",
    "orders": "grid:orders:{user_id}:{symbol}",
}

# OMS
OMS_KEYS = {
    "order": "oms:order:{order_id}",
    "user_orders": "oms:user:{user_id}:orders",  # Sorted Set
    "pending": "oms:pending:{exchange}",  # List
}

# Market Data
MARKET_KEYS = {
    "ticker": "market:ticker:{exchange}:{symbol}",
    "orderbook": "market:orderbook:{exchange}:{symbol}",
    "candle": "market:candle:{exchange}:{symbol}:{timeframe}",
}

# Position Management
POSITION_KEYS = {
    "position": "position:{user_id}:{symbol}",
    "pnl": "position:pnl:{user_id}:{symbol}",
}
```

**구현 예시**:
```python
from typing import Optional
import redis.asyncio as aioredis

class RedisKeyManager:
    def __init__(self, service_name: str):
        self.service_name = service_name
        self.redis = aioredis.from_url("redis://localhost:6379")

    def key(self, pattern: str, **kwargs) -> str:
        """네임스페이스를 포함한 키 생성"""
        return f"{self.service_name}:{pattern.format(**kwargs)}"

    async def set_with_ttl(self, pattern: str, value: str, ttl: int, **kwargs):
        key = self.key(pattern, **kwargs)
        await self.redis.setex(key, ttl, value)

    async def get(self, pattern: str, **kwargs) -> Optional[str]:
        key = self.key(pattern, **kwargs)
        return await self.redis.get(key)

# 사용 예시
hyperrsi_redis = RedisKeyManager("hyperrsi")
await hyperrsi_redis.set_with_ttl(
    "status:{user_id}:{symbol}",
    "active",
    ttl=3600,
    user_id="user123",
    symbol="BTC-USDT-SWAP"
)
```

---

### 4.3 공유 데이터 처리

#### 문제: 여러 서비스가 동일한 데이터 필요 (예: 사용자 정보)

**안티패턴**: 직접 데이터베이스 공유 ❌

```python
# 나쁜 예: 여러 서비스가 users 테이블 직접 접근
# HYPERRSI Service
user = db.query("SELECT * FROM users WHERE user_id = ?", user_id)

# GRID Service
user = db.query("SELECT * FROM users WHERE user_id = ?", user_id)
```

**패턴 1: API 호출로 데이터 조회** ✅

```python
# HYPERRSI Service
async def get_user_info(user_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.get(f"http://user-service:8008/api/users/{user_id}")
        return response.json()

# 캐싱 추가
from functools import lru_cache
from cachetools import TTLCache
import asyncio

user_cache = TTLCache(maxsize=1000, ttl=300)  # 5분 캐시

async def get_user_info_cached(user_id: str) -> dict:
    if user_id in user_cache:
        return user_cache[user_id]

    user_info = await get_user_info(user_id)
    user_cache[user_id] = user_info
    return user_info
```

**패턴 2: 이벤트 기반 데이터 복제** ✅

```python
# User Service: 사용자 정보 변경 시 이벤트 발행
async def update_user_settings(user_id: str, settings: dict):
    # DB 업데이트
    await db.execute("UPDATE users SET settings = ? WHERE user_id = ?", settings, user_id)

    # 이벤트 발행
    event = {
        "event_type": "user.settings_updated",
        "user_id": user_id,
        "settings": settings,
        "timestamp": time.time()
    }
    await redis_client.xadd("events:user_updates", event)

# HYPERRSI Service: 이벤트 소비하여 로컬 캐시 업데이트
async def sync_user_settings():
    async for event in consume_user_events():
        if event["event_type"] == "user.settings_updated":
            user_cache[event["user_id"]] = event["settings"]
```

---

### 4.4 분산 트랜잭션 처리

#### 문제: 여러 서비스에 걸친 일관성 보장 (예: 주문 생성 + 포지션 업데이트)

**패턴: Saga 패턴** (Orchestration 방식)

```python
# OMS에서 주문 생성 Saga 오케스트레이터
from enum import Enum
from typing import List, Callable, Any

class SagaStep:
    def __init__(
        self,
        name: str,
        action: Callable,
        compensation: Callable
    ):
        self.name = name
        self.action = action
        self.compensation = compensation

class SagaOrchestrator:
    def __init__(self):
        self.steps: List[SagaStep] = []
        self.executed_steps: List[str] = []

    def add_step(self, step: SagaStep):
        self.steps.append(step)

    async def execute(self) -> bool:
        try:
            for step in self.steps:
                logger.info(f"Executing saga step: {step.name}")
                await step.action()
                self.executed_steps.append(step.name)
            return True
        except Exception as e:
            logger.error(f"Saga failed at step {step.name}: {e}")
            await self.compensate()
            return False

    async def compensate(self):
        """실패 시 보상 트랜잭션 실행 (역순)"""
        for step_name in reversed(self.executed_steps):
            step = next(s for s in self.steps if s.name == step_name)
            try:
                logger.info(f"Compensating: {step.name}")
                await step.compensation()
            except Exception as e:
                logger.error(f"Compensation failed for {step.name}: {e}")

# 주문 생성 Saga 예시
async def create_order_saga(user_id: str, symbol: str, side: str, qty: float, price: float):
    order_id = None

    async def reserve_balance():
        nonlocal order_id
        # 1. 잔고 확인 및 예약
        response = await exchange_gateway_client.post(
            "/api/exchange/reserve_balance",
            json={"user_id": user_id, "amount": qty * price}
        )
        if not response.get("success"):
            raise Exception("Insufficient balance")

    async def unreserve_balance():
        await exchange_gateway_client.post(
            "/api/exchange/unreserve_balance",
            json={"user_id": user_id, "amount": qty * price}
        )

    async def create_order_record():
        nonlocal order_id
        # 2. OMS에 주문 기록 생성
        order_id = await db.execute(
            "INSERT INTO orders (...) VALUES (...)",
            user_id, symbol, side, qty, price
        )

    async def delete_order_record():
        await db.execute("DELETE FROM orders WHERE order_id = ?", order_id)

    async def submit_to_exchange():
        # 3. 거래소에 실제 주문 제출
        response = await exchange_gateway_client.post(
            "/api/exchange/execute",
            json={
                "user_id": user_id,
                "exchange": "okx",
                "action": "create_order",
                "params": {"symbol": symbol, "side": side, "qty": qty, "price": price}
            }
        )
        if not response.get("success"):
            raise Exception("Exchange order failed")

    async def cancel_exchange_order():
        await exchange_gateway_client.post(
            "/api/exchange/execute",
            json={
                "action": "cancel_order",
                "order_id": order_id
            }
        )

    async def update_position():
        # 4. 포지션 서비스에 알림
        await position_client.post(
            "/api/positions/update_pending",
            json={"order_id": order_id, "user_id": user_id, "symbol": symbol}
        )

    async def rollback_position():
        await position_client.post(
            "/api/positions/rollback_pending",
            json={"order_id": order_id}
        )

    # Saga 구성
    saga = SagaOrchestrator()
    saga.add_step(SagaStep("reserve_balance", reserve_balance, unreserve_balance))
    saga.add_step(SagaStep("create_order", create_order_record, delete_order_record))
    saga.add_step(SagaStep("submit_exchange", submit_to_exchange, cancel_exchange_order))
    saga.add_step(SagaStep("update_position", update_position, rollback_position))

    success = await saga.execute()
    return {"success": success, "order_id": order_id if success else None}
```

**장점**:
- 분산 트랜잭션 일관성 보장
- 실패 시 자동 롤백
- 명시적인 보상 로직

**단점**:
- 복잡도 증가
- 보상 트랜잭션 설계 어려움
- 최종 일관성 (Eventual Consistency)

---

### 4.5 캐싱 전략

**다층 캐시 아키텍처**:

```
[Application Memory Cache] → [Redis Cache] → [PostgreSQL]
     (L1: 1초 TTL)         (L2: 60초 TTL)    (영구 저장)
```

**구현**:
```python
from cachetools import TTLCache
import redis.asyncio as aioredis
from typing import Optional, Any
import json
import asyncio

class MultiLevelCache:
    def __init__(self):
        # L1: 메모리 캐시 (매우 빠름, 작은 용량)
        self.l1_cache = TTLCache(maxsize=1000, ttl=1)

        # L2: Redis 캐시 (빠름, 중간 용량)
        self.l2_cache = aioredis.from_url("redis://localhost:6379")
        self.l2_ttl = 60

    async def get(self, key: str) -> Optional[Any]:
        # L1 캐시 확인
        if key in self.l1_cache:
            return self.l1_cache[key]

        # L2 캐시 확인
        value = await self.l2_cache.get(key)
        if value:
            deserialized = json.loads(value)
            self.l1_cache[key] = deserialized  # L1에 저장
            return deserialized

        return None

    async def set(self, key: str, value: Any):
        # L1, L2 동시 저장
        self.l1_cache[key] = value
        await self.l2_cache.setex(key, self.l2_ttl, json.dumps(value))

    async def invalidate(self, key: str):
        # 모든 레벨에서 삭제
        self.l1_cache.pop(key, None)
        await self.l2_cache.delete(key)

# 사용 예시: 마켓 데이터 조회
cache = MultiLevelCache()

async def get_ticker(exchange: str, symbol: str) -> dict:
    cache_key = f"ticker:{exchange}:{symbol}"

    # 캐시 확인
    cached = await cache.get(cache_key)
    if cached:
        return cached

    # DB에서 조회
    ticker = await db.fetch_one(
        "SELECT * FROM market_tickers WHERE exchange = ? AND symbol = ?",
        exchange, symbol
    )

    # 캐시에 저장
    await cache.set(cache_key, ticker)
    return ticker
```

---

## 5. 마이그레이션 로드맵

### 5.1 단계별 마이그레이션 전략 (Strangler Fig Pattern)

**원칙**: 기존 모노리스를 유지하면서 점진적으로 서비스 분리

```mermaid
gantt
    title 마이크로서비스 마이그레이션 로드맵
    dateFormat  YYYY-MM-DD
    section Phase 1: 인프라 준비
    API Gateway 구축           :p1-1, 2025-11-01, 14d
    Redis Cluster 구축         :p1-2, 2025-11-08, 7d
    PostgreSQL 샤딩 설계       :p1-3, 2025-11-15, 7d
    CI/CD 파이프라인 구축      :p1-4, 2025-11-22, 14d

    section Phase 2: 첫 번째 서비스 분리
    Notification Service 분리  :p2-1, 2025-12-01, 14d
    User Service 분리          :p2-2, 2025-12-15, 21d

    section Phase 3: 핵심 서비스 분리
    Market Data Service 분리   :p3-1, 2026-01-05, 28d
    Exchange Gateway 분리      :p3-2, 2026-02-02, 28d

    section Phase 4: 거래 서비스 분리
    OMS 분리                   :p4-1, 2026-03-01, 35d
    Position Service 분리      :p4-2, 2026-04-05, 28d

    section Phase 5: 전략 서비스 분리
    HYPERRSI Service 분리      :p5-1, 2026-05-01, 42d
    GRID Service 분리          :p5-2, 2026-06-12, 42d

    section Phase 6: 최적화 및 안정화
    성능 최적화                :p6-1, 2026-07-24, 21d
    모니터링 강화              :p6-2, 2026-08-14, 14d
    모노리스 폐기              :p6-3, 2026-08-28, 7d
```

---

### 5.2 Phase 1: 인프라 준비 (2주)

**목표**: 마이크로서비스 운영에 필요한 기반 인프라 구축

#### 1.1 API Gateway 구축

**도구 선택**: Kong, Traefik, 또는 NGINX + Lua

**Kong 기반 예시**:
```yaml
# docker-compose.yml
services:
  kong-database:
    image: postgres:15
    environment:
      POSTGRES_DB: kong
      POSTGRES_USER: kong
      POSTGRES_PASSWORD: kong
    volumes:
      - kong-db:/var/lib/postgresql/data

  kong-migration:
    image: kong:3.4
    command: kong migrations bootstrap
    environment:
      KONG_DATABASE: postgres
      KONG_PG_HOST: kong-database
    depends_on:
      - kong-database

  kong:
    image: kong:3.4
    environment:
      KONG_DATABASE: postgres
      KONG_PG_HOST: kong-database
      KONG_PROXY_ACCESS_LOG: /dev/stdout
      KONG_ADMIN_ACCESS_LOG: /dev/stdout
      KONG_PROXY_ERROR_LOG: /dev/stderr
      KONG_ADMIN_ERROR_LOG: /dev/stderr
      KONG_ADMIN_LISTEN: 0.0.0.0:8001
    ports:
      - "8000:8000"   # Proxy HTTP
      - "8443:8443"   # Proxy HTTPS
      - "8001:8001"   # Admin API
    depends_on:
      - kong-migration
```

**라우팅 설정**:
```bash
# HYPERRSI 서비스 등록
curl -i -X POST http://localhost:8001/services/ \
  --data "name=hyperrsi-service" \
  --data "url=http://hyperrsi:8001"

# 라우트 추가
curl -i -X POST http://localhost:8001/services/hyperrsi-service/routes \
  --data "paths[]=/api/strategy/hyperrsi"

# Rate limiting 플러그인
curl -i -X POST http://localhost:8001/services/hyperrsi-service/plugins \
  --data "name=rate-limiting" \
  --data "config.minute=100"
```

#### 1.2 Redis Cluster 구축

**Redis Sentinel 구성** (고가용성):
```yaml
# docker-compose.yml
services:
  redis-master:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis-master-data:/data

  redis-replica-1:
    image: redis:7-alpine
    command: redis-server --appendonly yes --slaveof redis-master 6379
    depends_on:
      - redis-master

  redis-replica-2:
    image: redis:7-alpine
    command: redis-server --appendonly yes --slaveof redis-master 6379
    depends_on:
      - redis-master

  redis-sentinel-1:
    image: redis:7-alpine
    command: >
      redis-server /etc/redis/sentinel.conf --sentinel
    volumes:
      - ./sentinel.conf:/etc/redis/sentinel.conf

  redis-sentinel-2:
    image: redis:7-alpine
    command: >
      redis-server /etc/redis/sentinel.conf --sentinel
    volumes:
      - ./sentinel.conf:/etc/redis/sentinel.conf

  redis-sentinel-3:
    image: redis:7-alpine
    command: >
      redis-server /etc/redis/sentinel.conf --sentinel
    volumes:
      - ./sentinel.conf:/etc/redis/sentinel.conf
```

**sentinel.conf**:
```
port 26379
sentinel monitor mymaster redis-master 6379 2
sentinel down-after-milliseconds mymaster 5000
sentinel parallel-syncs mymaster 1
sentinel failover-timeout mymaster 10000
```

#### 1.3 CI/CD 파이프라인

**GitHub Actions 예시**:
```yaml
# .github/workflows/deploy-service.yml
name: Deploy Microservice

on:
  push:
    branches: [main]
    paths:
      - 'services/hyperrsi/**'

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Build Docker image
        run: |
          docker build -t hyperrsi-service:${{ github.sha }} \
            -f services/hyperrsi/Dockerfile .

      - name: Push to registry
        run: |
          echo ${{ secrets.DOCKER_PASSWORD }} | docker login -u ${{ secrets.DOCKER_USERNAME }} --password-stdin
          docker push hyperrsi-service:${{ github.sha }}

      - name: Deploy to Kubernetes
        run: |
          kubectl set image deployment/hyperrsi-service \
            hyperrsi=hyperrsi-service:${{ github.sha }}
```

---

### 5.3 Phase 2: 첫 번째 서비스 분리 (3주)

**목표**: 의존성이 낮은 서비스부터 분리하여 경험 축적

#### 2.1 Notification Service 분리 (2주)

**왜 먼저?**:
- 다른 서비스에 의존성 거의 없음 (단방향)
- 실패해도 핵심 거래에 영향 없음
- 테스트 용이

**단계**:

1. **새 저장소 생성**
```bash
mkdir services/notification-service
cd services/notification-service
```

2. **기존 코드 복사 및 리팩터링**
```python
# services/notification-service/main.py
from fastapi import FastAPI
from pydantic import BaseModel
from telegram import Bot
import redis.asyncio as aioredis

app = FastAPI(title="Notification Service")

class NotificationRequest(BaseModel):
    user_id: str
    message: str
    priority: str = "normal"

telegram_bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
redis_client = None

@app.on_event("startup")
async def startup():
    global redis_client
    redis_client = await aioredis.from_url("redis://redis:6379")

@app.post("/api/notifications/send")
async def send_notification(req: NotificationRequest):
    # Redis 큐에 추가
    await redis_client.lpush(
        f"notification:queue:{req.priority}",
        json.dumps(req.dict())
    )
    return {"status": "queued"}

# Celery 워커 (별도 프로세스)
from celery import Celery
celery_app = Celery('notification', broker='redis://redis:6379/1')

@celery_app.task
def process_notification_queue():
    # 큐에서 메시지 가져와서 발송
    pass
```

3. **Dockerfile 작성**
```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8007"]
```

4. **기존 코드에서 호출 변경**
```python
# Before (HYPERRSI/src/bot/telegram_message.py)
from shared.notifications.telegram import send_telegram_message

await send_telegram_message(user_id, message)

# After
import httpx

async def send_telegram_message(user_id: str, message: str):
    async with httpx.AsyncClient() as client:
        await client.post(
            "http://notification-service:8007/api/notifications/send",
            json={"user_id": user_id, "message": message}
        )
```

5. **배포 및 검증**
```bash
docker-compose up -d notification-service
curl http://localhost:8007/api/notifications/send \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "message": "Hello"}'
```

#### 2.2 User Service 분리 (3주)

**복잡도**: 중간 (많은 서비스가 사용자 정보 필요)

**전략**: API 게이트웨이에서 인증 처리 + 캐싱

```python
# services/user-service/main.py
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from passlib.hash import bcrypt

app = FastAPI(title="User & Account Service")

@app.post("/api/users/login")
async def login(username: str, password: str, db: AsyncSession = Depends(get_db)):
    user = await db.execute(
        "SELECT * FROM users WHERE username = ?", username
    )
    if not user or not bcrypt.verify(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # JWT 토큰 생성
    token = create_jwt_token(user.user_id)
    return {"access_token": token, "user_id": user.user_id}

@app.get("/api/users/{user_id}")
async def get_user(user_id: str, db: AsyncSession = Depends(get_db)):
    user = await db.execute(
        "SELECT user_id, username, email, created_at FROM users WHERE user_id = ?",
        user_id
    )
    if not user:
        raise HTTPException(status_code=404)
    return user
```

**API Gateway에서 인증 처리**:
```lua
-- Kong Lua 플러그인
local jwt = require "kong.plugins.jwt.jwt_parser"

function kong.access()
  local token = kong.request.get_header("Authorization")
  local jwt_token = jwt:new(token)

  if not jwt_token:verify() then
    kong.response.exit(401, {message = "Unauthorized"})
  end

  -- 사용자 정보를 헤더에 추가 (다운스트림 서비스 전달)
  kong.service.request.set_header("X-User-ID", jwt_token.claims.user_id)
end
```

---

### 5.4 Phase 3-5: 핵심 서비스 분리 (5개월)

각 서비스별 마이그레이션 체크리스트:

```markdown
## Market Data Service 마이그레이션 체크리스트

- [ ] WebSocket 연결 관리 코드 추출
- [ ] Redis Streams 이벤트 발행 구현
- [ ] REST API 엔드포인트 구현 (ticker, orderbook, candles)
- [ ] Dockerfile 및 Kubernetes 매니페스트 작성
- [ ] 기존 코드에서 API 호출로 변경
- [ ] 통합 테스트 작성
- [ ] 성능 테스트 (지연 시간 측정)
- [ ] 카나리 배포 (10% → 50% → 100%)
- [ ] 모니터링 대시보드 구축
- [ ] 기존 코드 제거

## OMS 마이그레이션 체크리스트

- [ ] 주문 CRUD API 구현
- [ ] Saga 패턴 구현 (분산 트랜잭션)
- [ ] Exchange Gateway 통합
- [ ] Position Service 통합
- [ ] WebSocket 이벤트 소비 (체결 알림)
- [ ] PostgreSQL 스키마 마이그레이션
- [ ] Redis 키 네임스페이스 분리
- [ ] 통합 테스트 (주문 전체 플로우)
- [ ] 부하 테스트 (TPS 측정)
- [ ] 배포 및 검증
```

---

### 5.5 리스크 완화 전략

#### A. Feature Flags

```python
from typing import Any
import redis.asyncio as aioredis

class FeatureFlagManager:
    def __init__(self):
        self.redis = aioredis.from_url("redis://localhost:6379")

    async def is_enabled(self, flag_name: str, user_id: str = None) -> bool:
        # 글로벌 플래그 확인
        global_flag = await self.redis.get(f"feature:{flag_name}:enabled")
        if global_flag == "false":
            return False

        # 사용자별 플래그 확인 (A/B 테스트)
        if user_id:
            user_flag = await self.redis.get(f"feature:{flag_name}:user:{user_id}")
            if user_flag is not None:
                return user_flag == "true"

        # 롤아웃 비율 확인
        rollout = await self.redis.get(f"feature:{flag_name}:rollout")
        if rollout:
            return hash(user_id or "") % 100 < int(rollout)

        return True

# 사용 예시
ff = FeatureFlagManager()

async def create_order(user_id: str, ...):
    if await ff.is_enabled("use_new_oms", user_id):
        # 새 OMS 서비스 호출
        return await new_oms_client.create_order(...)
    else:
        # 기존 모노리스 로직
        return await legacy_create_order(...)
```

#### B. Canary Deployment

```yaml
# Kubernetes Canary Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: oms-service-stable
spec:
  replicas: 9  # 90% 트래픽
  selector:
    matchLabels:
      app: oms-service
      version: stable
  template:
    metadata:
      labels:
        app: oms-service
        version: stable
    spec:
      containers:
      - name: oms
        image: oms-service:v1.0.0
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: oms-service-canary
spec:
  replicas: 1  # 10% 트래픽
  selector:
    matchLabels:
      app: oms-service
      version: canary
  template:
    metadata:
      labels:
        app: oms-service
        version: canary
    spec:
      containers:
      - name: oms
        image: oms-service:v2.0.0-canary
```

#### C. 데이터베이스 마이그레이션 (Dual Write)

```python
# Phase 1: Dual Write (모노리스 + 새 서비스 모두 쓰기)
async def create_order_dual_write(user_id: str, ...):
    # 기존 DB에 쓰기
    legacy_order_id = await legacy_db.execute("INSERT INTO orders ...")

    # 새 서비스 DB에도 쓰기
    try:
        new_order_id = await new_oms_db.execute("INSERT INTO oms.orders ...")
    except Exception as e:
        logger.error(f"New OMS write failed: {e}")
        # 계속 진행 (기존 DB가 source of truth)

    return legacy_order_id

# Phase 2: Read from New (새 서비스에서 읽기, 없으면 fallback)
async def get_order(order_id: str):
    order = await new_oms_db.fetch_one("SELECT * FROM oms.orders WHERE order_id = ?", order_id)
    if not order:
        # Fallback to legacy
        order = await legacy_db.fetch_one("SELECT * FROM orders WHERE order_id = ?", order_id)
    return order

# Phase 3: Switch (새 서비스가 source of truth)
# Phase 4: Remove Legacy (기존 코드 제거)
```

---

### 5.6 테스트 전략

#### A. Contract Testing (Pact)

```python
# OMS Service Contract (Provider)
from pact import Provider

provider = Provider('oms-service')

@provider.given('an order exists')
async def order_exists():
    # 테스트 데이터 준비
    await db.execute("INSERT INTO orders VALUES ('test-order-123', ...)")

@provider.upon_receiving('a request to get order')
async def get_order_contract():
    # 실제 API 호출
    response = await client.get('/api/orders/test-order-123')
    assert response.status_code == 200
    assert response.json()['order_id'] == 'test-order-123'

# HYPERRSI Service (Consumer)
from pact import Consumer

consumer = Consumer('hyperrsi-service')
pact = consumer.has_pact_with(Provider('oms-service'))

@pact.given('an order exists')
@pact.upon_receiving('a request to get order')
async def test_get_order():
    # Contract 정의
    pact.with_request(
        method='GET',
        path='/api/orders/test-order-123'
    ).will_respond_with(
        status=200,
        body={'order_id': 'test-order-123', 'status': 'filled'}
    )

    # 실제 코드 테스트
    order = await oms_client.get_order('test-order-123')
    assert order['status'] == 'filled'
```

#### B. Integration Testing

```python
import pytest
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

@pytest.fixture(scope="session")
async def test_infrastructure():
    # PostgreSQL 컨테이너
    postgres = PostgresContainer("postgres:15")
    postgres.start()

    # Redis 컨테이너
    redis = RedisContainer("redis:7")
    redis.start()

    yield {
        "postgres_url": postgres.get_connection_url(),
        "redis_url": redis.get_connection_url()
    }

    postgres.stop()
    redis.stop()

@pytest.mark.asyncio
async def test_order_creation_flow(test_infrastructure):
    # 전체 플로우 테스트: HYPERRSI → OMS → Exchange Gateway → Position

    # 1. 전략에서 주문 생성 요청
    response = await hyperrsi_client.post("/api/strategy/hyperrsi/create_order", json={
        "user_id": "test-user",
        "symbol": "BTC-USDT-SWAP",
        "side": "buy",
        "quantity": 0.1
    })
    assert response.status_code == 201
    order_id = response.json()["order_id"]

    # 2. OMS에서 주문 상태 확인
    order = await oms_client.get(f"/api/orders/{order_id}")
    assert order["status"] == "pending"

    # 3. 체결 이벤트 발행 (시뮬레이션)
    await redis_client.xadd("events:order_filled", {
        "order_id": order_id,
        "filled_qty": 0.1,
        "fill_price": 50000
    })

    # 4. Position Service에서 포지션 업데이트 확인
    await asyncio.sleep(1)  # 이벤트 처리 대기
    position = await position_client.get(f"/api/positions/test-user/BTC-USDT-SWAP")
    assert position["quantity"] == 0.1
```

---

## 6. 비동기 아키텍처 패턴

### 6.1 Python 3.12+ 비동기 베스트 프랙티스

#### A. asyncio.TaskGroup (Python 3.11+)

```python
import asyncio
from typing import List

# Before: asyncio.gather (에러 처리 어려움)
async def fetch_all_tickers_old(symbols: List[str]):
    tasks = [fetch_ticker(symbol) for symbol in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    # 에러 개별 처리 복잡
    return results

# After: TaskGroup (구조화된 에러 처리)
async def fetch_all_tickers(symbols: List[str]):
    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(fetch_ticker(symbol)) for symbol in symbols]

    # 모든 태스크 성공 또는 하나라도 실패 시 ExceptionGroup 발생
    results = [task.result() for task in tasks]
    return results

# ExceptionGroup 처리
try:
    tickers = await fetch_all_tickers(["BTC-USDT", "ETH-USDT"])
except* asyncio.CancelledError as eg:
    # 취소된 태스크만 처리
    logger.warning(f"Cancelled tasks: {eg.exceptions}")
except* Exception as eg:
    # 기타 에러 처리
    logger.error(f"Errors: {eg.exceptions}")
```

#### B. Async Context Managers

```python
from contextlib import asynccontextmanager
from typing import AsyncGenerator
import redis.asyncio as aioredis

@asynccontextmanager
async def get_redis_connection() -> AsyncGenerator[aioredis.Redis, None]:
    """Redis 연결 자동 관리"""
    client = await aioredis.from_url("redis://localhost:6379")
    try:
        yield client
    finally:
        await client.close()

# 사용
async def set_user_status(user_id: str, status: str):
    async with get_redis_connection() as redis:
        await redis.setex(f"user:{user_id}:status", 3600, status)
```

#### C. Async Generators & Streaming

```python
from typing import AsyncGenerator

async def stream_market_data(symbol: str) -> AsyncGenerator[dict, None]:
    """실시간 시장 데이터 스트리밍"""
    async with aioredis.from_url("redis://localhost:6379") as redis:
        last_id = '0-0'

        while True:
            # Redis Streams에서 읽기
            events = await redis.xread(
                {f"market:{symbol}:ticks": last_id},
                count=10,
                block=1000
            )

            for stream, messages in events:
                for message_id, data in messages:
                    yield data
                    last_id = message_id

# FastAPI에서 사용 (Server-Sent Events)
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()

@app.get("/api/market/stream/{symbol}")
async def stream_ticker(symbol: str):
    async def event_generator():
        async for data in stream_market_data(symbol):
            yield f"data: {json.dumps(data)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

---

### 6.2 FastAPI 비동기 패턴

#### A. 의존성 주입 (Async Dependencies)

```python
from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis

app = FastAPI()

# 데이터베이스 세션 의존성
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

# Redis 클라이언트 의존성
async def get_redis() -> aioredis.Redis:
    return await aioredis.from_url("redis://localhost:6379")

# 사용자 인증 의존성
async def get_current_user(
    user_id: str = Header(...),
    db: AsyncSession = Depends(get_db)
) -> User:
    user = await db.execute(
        select(User).where(User.user_id == user_id)
    )
    if not user:
        raise HTTPException(status_code=401)
    return user

# 엔드포인트에서 사용
@app.post("/api/orders/create")
async def create_order(
    order: OrderCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis)
):
    # 의존성 자동 주입
    pass
```

#### B. Background Tasks

```python
from fastapi import BackgroundTasks

async def send_notification_async(user_id: str, message: str):
    """비동기 알림 전송 (FastAPI 백그라운드 태스크)"""
    async with httpx.AsyncClient() as client:
        await client.post(
            "http://notification-service:8007/api/notifications/send",
            json={"user_id": user_id, "message": message}
        )

@app.post("/api/orders/create")
async def create_order(
    order: OrderCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user)
):
    # 주문 생성
    order_id = await oms_client.create_order(...)

    # 백그라운드에서 알림 전송 (응답 지연 없음)
    background_tasks.add_task(
        send_notification_async,
        user.user_id,
        f"주문 생성: {order_id}"
    )

    return {"order_id": order_id}
```

#### C. Lifespan Events

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 시작 시
    await init_db()
    await init_redis()
    await start_websocket_manager()

    yield

    # 종료 시
    await close_db()
    await close_redis()
    await stop_websocket_manager()

app = FastAPI(lifespan=lifespan)
```

---

### 6.3 Redis 비동기 패턴

#### A. Connection Pooling

```python
from redis.asyncio import ConnectionPool, Redis
from typing import Optional

class RedisManager:
    _pool: Optional[ConnectionPool] = None

    @classmethod
    async def get_pool(cls) -> ConnectionPool:
        if cls._pool is None:
            cls._pool = ConnectionPool.from_url(
                "redis://localhost:6379",
                max_connections=100,
                decode_responses=True
            )
        return cls._pool

    @classmethod
    async def get_client(cls) -> Redis:
        pool = await cls.get_pool()
        return Redis(connection_pool=pool)

# 사용
async def set_value(key: str, value: str):
    redis = await RedisManager.get_client()
    await redis.set(key, value)
```

#### B. Pipeline (배치 작업)

```python
async def update_multiple_positions(positions: List[Position]):
    redis = await RedisManager.get_client()

    async with redis.pipeline(transaction=True) as pipe:
        for pos in positions:
            key = f"position:{pos.user_id}:{pos.symbol}"
            pipe.hset(key, mapping={
                "quantity": pos.quantity,
                "avg_price": pos.avg_price,
                "pnl": pos.pnl
            })
            pipe.expire(key, 3600)

        # 한 번에 실행 (네트워크 왕복 최소화)
        await pipe.execute()
```

#### C. Pub/Sub 패턴

```python
import asyncio

async def publish_price_update(symbol: str, price: float):
    redis = await RedisManager.get_client()
    await redis.publish(f"price:{symbol}", json.dumps({"price": price}))

async def subscribe_to_prices(symbols: List[str]):
    redis = await RedisManager.get_client()
    pubsub = redis.pubsub()

    # 채널 구독
    await pubsub.subscribe(*[f"price:{s}" for s in symbols])

    try:
        async for message in pubsub.listen():
            if message['type'] == 'message':
                data = json.loads(message['data'])
                await handle_price_update(message['channel'], data)
    finally:
        await pubsub.unsubscribe()
```

---

### 6.4 Celery 대안: Dramatiq + asyncio

**문제**: Celery는 asyncio 네이티브 지원 약함

**대안**: Dramatiq (async 작업 큐)

```python
import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import AsyncIO

# Broker 설정
redis_broker = RedisBroker(url="redis://localhost:6379")
redis_broker.add_middleware(AsyncIO())
dramatiq.set_broker(redis_broker)

# 비동기 작업 정의
@dramatiq.actor(max_retries=3, time_limit=60000)
async def process_order_async(order_id: str):
    async with get_db() as db:
        order = await db.fetch_one("SELECT * FROM orders WHERE order_id = ?", order_id)

        # 거래소에 주문 제출
        result = await exchange_client.submit_order(order)

        # 결과 저장
        await db.execute(
            "UPDATE orders SET status = ?, exchange_order_id = ? WHERE order_id = ?",
            result['status'], result['exchange_order_id'], order_id
        )

# 작업 큐에 추가
await process_order_async.send(order_id="order-123")
```

**장점**:
- 네이티브 asyncio 지원
- 간단한 API
- 빠른 성능

**단점**:
- Celery 대비 생태계 작음
- 마이그레이션 비용

---

### 6.5 이벤트 기반 아키텍처

#### Event Bus 구현 (Redis Streams 기반)

```python
from typing import Callable, Dict, List
import asyncio

class EventBus:
    def __init__(self):
        self.redis = None
        self.handlers: Dict[str, List[Callable]] = {}

    async def connect(self):
        self.redis = await aioredis.from_url("redis://localhost:6379")

    async def publish(self, event_type: str, data: dict):
        """이벤트 발행"""
        await self.redis.xadd(
            f"events:{event_type}",
            {"data": json.dumps(data), "timestamp": time.time()}
        )

    def subscribe(self, event_type: str, handler: Callable):
        """이벤트 핸들러 등록"""
        if event_type not in self.handlers:
            self.handlers[event_type] = []
        self.handlers[event_type].append(handler)

    async def start_consuming(self):
        """이벤트 소비 시작"""
        last_ids = {f"events:{et}": '0-0' for et in self.handlers.keys()}

        while True:
            events = await self.redis.xread(last_ids, count=10, block=1000)

            for stream, messages in events:
                event_type = stream.decode().split(':')[1]

                for message_id, fields in messages:
                    data = json.loads(fields[b'data'])

                    # 모든 핸들러 실행
                    for handler in self.handlers.get(event_type, []):
                        try:
                            await handler(data)
                        except Exception as e:
                            logger.error(f"Handler error: {e}")

                    last_ids[stream] = message_id

# 사용 예시
event_bus = EventBus()
await event_bus.connect()

# 핸들러 등록
@event_bus.subscribe("order.filled")
async def handle_order_filled(data: dict):
    # 포지션 업데이트
    await position_service.update_position(data['user_id'], data['symbol'], data['filled_qty'])

@event_bus.subscribe("order.filled")
async def send_fill_notification(data: dict):
    # 알림 전송
    await notification_service.send(data['user_id'], f"주문 체결: {data['order_id']}")

# 이벤트 발행
await event_bus.publish("order.filled", {
    "order_id": "order-123",
    "user_id": "user-456",
    "symbol": "BTC-USDT-SWAP",
    "filled_qty": 0.1,
    "fill_price": 50000
})

# 이벤트 소비 시작 (백그라운드)
asyncio.create_task(event_bus.start_consuming())
```

---

## 7. 운영 고려사항

### 7.1 모니터링 및 Observability

#### A. 메트릭 수집 (Prometheus)

```python
from prometheus_client import Counter, Histogram, Gauge
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI()

# 메트릭 정의
order_created_counter = Counter(
    'orders_created_total',
    'Total number of orders created',
    ['exchange', 'symbol', 'side']
)

order_latency_histogram = Histogram(
    'order_creation_latency_seconds',
    'Order creation latency',
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0]
)

active_positions_gauge = Gauge(
    'active_positions',
    'Number of active positions',
    ['exchange', 'symbol']
)

# FastAPI 자동 계측
Instrumentator().instrument(app).expose(app)

# 수동 메트릭 기록
@app.post("/api/orders/create")
async def create_order(order: OrderCreate):
    with order_latency_histogram.time():
        result = await oms_client.create_order(...)

        order_created_counter.labels(
            exchange=order.exchange,
            symbol=order.symbol,
            side=order.side
        ).inc()

    return result
```

#### B. 분산 추적 (OpenTelemetry)

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

# Tracer 설정
tracer_provider = TracerProvider()
jaeger_exporter = JaegerExporter(
    agent_host_name="jaeger",
    agent_port=6831,
)
tracer_provider.add_span_processor(BatchSpanProcessor(jaeger_exporter))
trace.set_tracer_provider(tracer_provider)

# FastAPI 자동 계측
FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()

# 수동 span 생성
tracer = trace.get_tracer(__name__)

@app.post("/api/orders/create")
async def create_order(order: OrderCreate):
    with tracer.start_as_current_span("create_order") as span:
        span.set_attribute("order.symbol", order.symbol)
        span.set_attribute("order.side", order.side)

        # 1. 잔고 확인
        with tracer.start_as_current_span("check_balance"):
            balance = await exchange_gateway.get_balance(order.user_id)

        # 2. 주문 생성
        with tracer.start_as_current_span("submit_order"):
            result = await oms_client.create_order(...)

        return result
```

#### C. 구조화된 로깅 (JSON Logs)

```python
import logging
import json
from datetime import datetime

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "service": "hyperrsi-service",
            "message": record.getMessage(),
            "logger": record.name,
        }

        # 컨텍스트 정보 추가
        if hasattr(record, 'user_id'):
            log_data['user_id'] = record.user_id
        if hasattr(record, 'order_id'):
            log_data['order_id'] = record.order_id
        if hasattr(record, 'trace_id'):
            log_data['trace_id'] = record.trace_id

        return json.dumps(log_data)

# 로거 설정
logger = logging.getLogger("hyperrsi")
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)

# 사용
logger.info(
    "Order created",
    extra={"user_id": "user-123", "order_id": "order-456", "symbol": "BTC-USDT"}
)
```

---

### 7.2 배포 전략 (Kubernetes)

#### A. Deployment 매니페스트

```yaml
# services/hyperrsi/k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hyperrsi-service
  labels:
    app: hyperrsi-service
spec:
  replicas: 3
  selector:
    matchLabels:
      app: hyperrsi-service
  template:
    metadata:
      labels:
        app: hyperrsi-service
    spec:
      containers:
      - name: hyperrsi
        image: hyperrsi-service:v1.0.0
        ports:
        - containerPort: 8001
        env:
        - name: REDIS_HOST
          value: "redis-cluster"
        - name: REDIS_PORT
          value: "6379"
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: db-credentials
              key: url
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8001
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8001
          initialDelaySeconds: 10
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: hyperrsi-service
spec:
  selector:
    app: hyperrsi-service
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8001
  type: ClusterIP
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: hyperrsi-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: hyperrsi-service
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

#### B. ConfigMap & Secrets

```yaml
# ConfigMap (환경변수)
apiVersion: v1
kind: ConfigMap
metadata:
  name: hyperrsi-config
data:
  ENVIRONMENT: "production"
  LOG_LEVEL: "INFO"
  REDIS_HOST: "redis-cluster"
  REDIS_PORT: "6379"
---
# Secret (민감 정보)
apiVersion: v1
kind: Secret
metadata:
  name: hyperrsi-secrets
type: Opaque
stringData:
  OKX_API_KEY: "your-api-key"
  OKX_SECRET_KEY: "your-secret-key"
  OKX_PASSPHRASE: "your-passphrase"
  DATABASE_URL: "postgresql://user:pass@postgres:5432/tradingboost"
```

#### C. Helm Chart 구조

```
charts/hyperrsi-service/
├── Chart.yaml
├── values.yaml
├── templates/
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── hpa.yaml
│   ├── configmap.yaml
│   └── secret.yaml
└── values/
    ├── production.yaml
    └── staging.yaml
```

---

### 7.3 보안 고려사항

#### A. API 키 암호화 저장

```python
from cryptography.fernet import Fernet
import base64
import os

class CredentialManager:
    def __init__(self):
        # 환경변수에서 암호화 키 로드
        key = os.getenv("ENCRYPTION_KEY").encode()
        self.cipher = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        """API 키 암호화"""
        encrypted = self.cipher.encrypt(plaintext.encode())
        return base64.b64encode(encrypted).decode()

    def decrypt(self, encrypted: str) -> str:
        """API 키 복호화"""
        decoded = base64.b64decode(encrypted.encode())
        decrypted = self.cipher.decrypt(decoded)
        return decrypted.decode()

# DB에 암호화된 키 저장
cm = CredentialManager()
encrypted_api_key = cm.encrypt(user_api_key)
await db.execute(
    "INSERT INTO user_credentials (user_id, api_key_encrypted) VALUES (?, ?)",
    user_id, encrypted_api_key
)

# 사용 시 복호화
encrypted = await db.fetch_one("SELECT api_key_encrypted FROM user_credentials WHERE user_id = ?", user_id)
api_key = cm.decrypt(encrypted['api_key_encrypted'])
```

#### B. Rate Limiting (API Gateway)

```python
# Kong Rate Limiting 플러그인
curl -X POST http://kong:8001/services/hyperrsi-service/plugins \
  --data "name=rate-limiting" \
  --data "config.second=10" \
  --data "config.minute=100" \
  --data "config.hour=1000" \
  --data "config.policy=redis" \
  --data "config.redis_host=redis" \
  --data "config.redis_port=6379"
```

#### C. 네트워크 격리 (Service Mesh)

```yaml
# Istio VirtualService (서비스 간 통신 제어)
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: oms-service
spec:
  hosts:
  - oms-service
  http:
  - match:
    - sourceLabels:
        app: hyperrsi-service
    - sourceLabels:
        app: grid-service
    route:
    - destination:
        host: oms-service
        port:
          number: 8004
  - route:
    - destination:
        host: access-denied  # 다른 서비스는 접근 거부
```

---

### 7.4 성능 최적화

#### A. Connection Pooling

```python
# PostgreSQL 연결 풀 설정
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

engine = create_async_engine(
    DATABASE_URL,
    pool_size=20,           # 기본 연결 수
    max_overflow=10,        # 추가 연결 수
    pool_timeout=30,        # 연결 대기 시간
    pool_recycle=3600,      # 연결 재활용 주기
    pool_pre_ping=True,     # 연결 유효성 검사
    echo=False
)

async_session_maker = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)
```

#### B. 캐시 전략

```python
from functools import wraps
import hashlib

def cache_result(ttl: int = 60):
    """함수 결과 캐싱 데코레이터"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 캐시 키 생성
            cache_key = f"{func.__name__}:{hashlib.md5(str(args).encode() + str(kwargs).encode()).hexdigest()}"

            # 캐시 확인
            redis = await RedisManager.get_client()
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached)

            # 함수 실행
            result = await func(*args, **kwargs)

            # 결과 캐싱
            await redis.setex(cache_key, ttl, json.dumps(result))
            return result

        return wrapper
    return decorator

# 사용
@cache_result(ttl=300)  # 5분 캐싱
async def get_market_info(exchange: str, symbol: str):
    # 거래소 API 호출 (느림)
    return await exchange_client.get_market_info(exchange, symbol)
```

#### C. 배치 처리

```python
from typing import List

async def batch_create_orders(orders: List[OrderCreate]) -> List[str]:
    """여러 주문 배치 생성"""
    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(create_order(order)) for order in orders]

    return [task.result()['order_id'] for task in tasks]

# 거래소 API 배치 호출
async def batch_get_balances(user_ids: List[str]) -> Dict[str, dict]:
    """여러 사용자 잔고 배치 조회"""
    async with httpx.AsyncClient() as client:
        # 동시 요청 (최대 10개)
        semaphore = asyncio.Semaphore(10)

        async def get_balance(user_id: str):
            async with semaphore:
                response = await client.get(f"/api/exchange/balance/{user_id}")
                return user_id, response.json()

        results = await asyncio.gather(*[get_balance(uid) for uid in user_ids])
        return dict(results)
```

---

## 8. 최종 권장사항

### 8.1 Go/No-Go 의사결정 매트릭스

| 기준 | 현재 상태 | 마이크로서비스 필요성 | 점수 (1-5) |
|------|----------|---------------------|-----------|
| **팀 규모** | 2-5명 | 10명+ 시 최적 | 2/5 |
| **서비스 복잡도** | 중간 (2개 전략) | 5개+ 전략 시 최적 | 3/5 |
| **배포 빈도** | 주 1회 | 일 1회+ 시 최적 | 2/5 |
| **스케일링 요구** | 유저 100명 이하 | 1000명+ 시 필요 | 2/5 |
| **기술 다양성** | Python 단일 | 다중 언어 시 유리 | 1/5 |
| **장애 격리** | 중요 (거래 시스템) | 매우 중요 | 5/5 |
| **운영 역량** | 기본 (Docker) | 고급 (K8s) 필요 | 2/5 |

**총점**: 17/35 (48%)

---

### 8.2 권장사항

#### 🟢 **단기 (3-6개월): Modular Monolith 접근**

**현 상태에서는 완전한 마이크로서비스 전환이 오버엔지니어링입니다.**

**대신 다음을 추천**:

1. **Shared 모듈 개선**
   - 명확한 인터페이스 정의
   - 의존성 역전 원칙 적용
   - 버전 관리 도입

2. **서비스 경계 설계**
   - 각 전략을 독립적인 모듈로 구조화
   - API 계약 명시 (OpenAPI)
   - 데이터베이스 스키마 분리 (스키마 레벨)

3. **이벤트 기반 통신 도입**
   - Redis Streams로 느슨한 결합
   - 주문/포지션 업데이트 이벤트화

4. **인프라 개선**
   - Redis Sentinel 고가용성
   - PostgreSQL Read Replica
   - Docker Compose 기반 로컬 개발 환경

**예시 구조**:
```
TradingBoost-Strategy/
├── services/
│   ├── hyperrsi/        # 독립적 모듈 (아직 모노리스 내)
│   ├── grid/
│   ├── market_data/
│   └── notification/
├── shared/
│   ├── interfaces/      # 추상 인터페이스
│   ├── events/          # 이벤트 스키마
│   └── utils/
└── main.py              # 단일 진입점 유지
```

---

#### 🟡 **중기 (6-12개월): Strangler Fig 시작**

**조건**: 사용자 500명+ 또는 전략 5개+ 시

1. **첫 번째 서비스 분리**
   - Notification Service (위험 낮음)
   - Market Data Service (독립성 높음)

2. **API Gateway 도입**
   - Kong 또는 Traefik
   - Rate limiting, 인증

3. **모니터링 강화**
   - Prometheus + Grafana
   - 분산 추적 (Jaeger)

---

#### 🔴 **장기 (12개월+): 완전한 마이크로서비스**

**조건**: 사용자 1000명+, 팀 10명+, 전략 10개+

1. **모든 서비스 분리**
   - 10개 독립 서비스
   - Kubernetes 배포
   - Service Mesh (Istio)

2. **고급 패턴 적용**
   - CQRS (Command Query Responsibility Segregation)
   - Event Sourcing
   - Circuit Breaker

---

### 8.3 실용적 첫 단계 (지금 당장 시작)

#### 1주차: 분석 및 설계

```bash
# 1. 서비스 경계 정의 문서 작성
touch docs/SERVICE_BOUNDARIES.md

# 2. API 계약 정의 (OpenAPI)
mkdir -p api-contracts
touch api-contracts/hyperrsi.yaml
touch api-contracts/grid.yaml
touch api-contracts/market-data.yaml
```

#### 2주차: Shared 모듈 리팩터링

```python
# shared/interfaces/strategy.py
from abc import ABC, abstractmethod

class StrategyInterface(ABC):
    @abstractmethod
    async def activate(self, user_id: str, symbol: str, params: dict):
        """전략 활성화"""
        pass

    @abstractmethod
    async def deactivate(self, user_id: str, symbol: str):
        """전략 비활성화"""
        pass

    @abstractmethod
    async def get_status(self, user_id: str, symbol: str) -> dict:
        """전략 상태 조회"""
        pass

# services/hyperrsi/strategy.py
from shared.interfaces.strategy import StrategyInterface

class HyperRSIStrategy(StrategyInterface):
    async def activate(self, user_id: str, symbol: str, params: dict):
        # 구현
        pass
```

#### 3-4주차: 이벤트 시스템 구축

```python
# shared/events/schema.py
from pydantic import BaseModel

class OrderFilledEvent(BaseModel):
    event_type: str = "order.filled"
    order_id: str
    user_id: str
    symbol: str
    filled_qty: float
    fill_price: float

# shared/events/bus.py
# (앞서 정의한 EventBus 구현)
```

---

### 8.4 비용/이익 분석

| 항목 | 모노리스 유지 | Modular Monolith | 마이크로서비스 |
|------|-------------|------------------|---------------|
| **개발 속도** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ |
| **배포 복잡도** | ⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| **운영 비용** | $ | $$ | $$$$$ |
| **스케일링** | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **장애 격리** | ⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **팀 자율성** | ⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **학습 곡선** | ⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ |

**추천**: **Modular Monolith** (중간 지점)

---

## 9. 결론

### 핵심 메시지

1. **지금 당장 완전한 마이크로서비스는 필요 없습니다.**
2. **하지만 미래를 위한 준비는 지금 시작해야 합니다.**
3. **Modular Monolith로 시작하여 점진적으로 전환하세요.**

### 실행 계획 요약

```mermaid
graph LR
    A[현재: 모노리스] --> B[3개월: Modular Monolith]
    B --> C[6개월: API Gateway + 첫 서비스 분리]
    C --> D[12개월: 핵심 서비스 분리]
    D --> E[18개월+: 완전한 마이크로서비스]

    style A fill:#ff6b6b
    style B fill:#ffd93d
    style C fill:#6bcf7f
    style D fill:#4d96ff
    style E fill:#a78bfa
```

### 다음 액션 아이템

- [ ] 팀 미팅: 마이크로서비스 전환 논의
- [ ] API 계약 정의 시작
- [ ] shared 모듈 인터페이스 설계
- [ ] Redis Streams 이벤트 시스템 PoC
- [ ] Docker Compose 환경 개선
- [ ] 모니터링 기본 구축 (Prometheus)

---

**문서 작성자**: Claude (Anthropic)
**검토 필요**: 아키텍처 팀, DevOps 팀
**다음 업데이트**: 3개월 후 (진행 상황 리뷰)
