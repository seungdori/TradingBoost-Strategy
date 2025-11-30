# TradingBoost-Strategy 마이크로서비스 전환 가이드

## 목차

1. [개요](#개요)
2. [현재 아키텍처 분석](#현재-아키텍처-분석)
3. [마이크로서비스 분해 전략](#마이크로서비스-분해-전략)
4. [서비스 경계 정의](#서비스-경계-정의)
5. [단계별 마이그레이션 로드맵](#단계별-마이그레이션-로드맵)
6. [인프라 및 배포](#인프라-및-배포)
7. [데이터 관리 전략](#데이터-관리-전략)
8. [API 설계 및 통신](#api-설계-및-통신)
9. [모니터링 및 관찰성](#모니터링-및-관찰성)
10. [보안 및 인증](#보안-및-인증)

---

## 1. 개요

### 1.1 마이그레이션 목표

현재 TradingBoost-Strategy는 **모노레포 아키텍처**로 구성되어 있으며, 다음과 같은 이유로 마이크로서비스로 전환을 고려할 수 있습니다:

**마이크로서비스 전환의 장점:**
- ✅ **독립적 배포**: 각 서비스를 독립적으로 배포 및 스케일링
- ✅ **기술 스택 유연성**: 서비스별로 최적의 기술 선택 가능
- ✅ **팀 자율성**: 각 팀이 서비스를 독립적으로 개발
- ✅ **장애 격리**: 한 서비스의 장애가 전체 시스템에 영향 최소화
- ✅ **수평 확장성**: 트래픽이 높은 서비스만 선택적으로 확장

**고려사항:**
- ⚠️ **운영 복잡도 증가**: 여러 서비스 관리 필요
- ⚠️ **분산 시스템 복잡성**: 네트워크 레이턴시, 장애 처리
- ⚠️ **데이터 일관성**: 분산 트랜잭션 처리 필요
- ⚠️ **개발 오버헤드**: 서비스 간 통신 및 계약 관리

### 1.2 권장 접근법

**점진적 마이그레이션 (Strangler Fig Pattern)** 권장:
1. 기존 모노레포 유지하면서 새로운 기능을 마이크로서비스로 개발
2. 점진적으로 기존 기능을 마이크로서비스로 추출
3. 완전히 이전될 때까지 모노레포와 마이크로서비스 병행 운영

### 1.3 기술 요구사항

**핵심 기술 스택:**
- **Python 3.12+**: 최신 성능 개선 및 타입 힌팅 기능
- **FastAPI**: 비동기 REST API 프레임워크
- **PostgreSQL 15+**: 관계형 데이터베이스
- **Redis 7+**: 캐싱 및 메시지 브로커
- **Docker & Docker Compose**: 컨테이너화
- **Kubernetes** (프로덕션): 오케스트레이션

**추가 도구:**
- **Celery**: 백그라운드 작업 처리 (HYPERRSI)
- **CCXT**: 거래소 API 통합
- **WebSocket**: 실시간 데이터 스트리밍
- **Prometheus & Grafana**: 모니터링
- **ELK Stack**: 로그 집계
- **Jaeger**: 분산 추적

---

## 2. 현재 아키텍처 분석

### 2.1 모노레포 구조

```
TradingBoost-Strategy/
├── HYPERRSI/          # RSI 전략 (포트 8000)
├── GRID/              # 그리드 전략 (포트 8012)
└── shared/            # 공유 모듈
```

### 2.2 핵심 의존성 매핑

**Shared 모듈 의존성:**
```
shared/
├── config/           → 모든 서비스가 사용 (설정 관리)
├── exchange_apis/    → 모든 서비스가 사용 (거래소 API)
├── database/         → 데이터베이스 유틸리티
├── logging/          → 로깅 인프라
├── notifications/    → 텔레그램 알림
├── indicators/       → 기술적 지표 (HYPERRSI 주로 사용)
└── utils/            → 공통 유틸리티
```

**HYPERRSI 의존성:**
- shared.config
- shared.exchange_apis (OKX, Binance 등)
- shared.database (PostgreSQL/SQLite)
- shared.notifications (Telegram)
- shared.indicators (RSI, MA, ATR 등)
- Redis (캐싱, Celery 브로커)
- Celery (백그라운드 작업)

**GRID 의존성:**
- shared.config
- shared.exchange_apis (OKX, Upbit 등)
- shared.database
- shared.notifications
- Redis (캐싱)
- Multiprocessing (워커 관리)

### 2.3 공유 리소스

**데이터베이스:**
- PostgreSQL/SQLite (사용자, 설정, 주문 이력)
- Redis DB 0 (애플리케이션 데이터)
- Redis DB 1 (Celery 브로커/백엔드)

**외부 서비스:**
- OKX, Binance, Upbit, Bitget, Bybit APIs
- Telegram Bot API

---

## 3. 마이크로서비스 분해 전략

### 3.1 도메인 주도 설계 (DDD) 접근

**식별된 바운디드 컨텍스트 (Bounded Contexts):**

1. **사용자 관리 (User Management)**
   - 사용자 등록/인증
   - API 키 관리
   - 프로필 설정

2. **전략 실행 (Strategy Execution)**
   - HYPERRSI 전략
   - GRID 전략
   - 향후 추가 전략

3. **거래소 통합 (Exchange Integration)**
   - 거래소 API 추상화
   - 주문 실행
   - 포지션 관리
   - WebSocket 관리

4. **시장 데이터 (Market Data)**
   - 실시간 가격 데이터
   - 기술적 지표 계산
   - 과거 데이터 수집

5. **알림 (Notifications)**
   - 텔레그램 알림
   - 이메일 알림 (향후)
   - 웹훅 (향후)

6. **모니터링 및 분석 (Monitoring & Analytics)**
   - 성과 추적
   - 리스크 분석
   - 감사 로그

### 3.2 서비스 분해 우선순위

**Phase 1: 독립적 서비스 분리**
1. ✅ Notification Service (가장 독립적)
2. ✅ Market Data Service (읽기 전용, 확장 필요)

**Phase 2: 핵심 비즈니스 로직 분리**
3. ✅ User Service
4. ✅ Exchange Integration Service

**Phase 3: 전략 서비스 분리**
5. ✅ HYPERRSI Strategy Service
6. ✅ GRID Strategy Service

**Phase 4: 고급 기능**
7. ✅ Analytics Service
8. ✅ Risk Management Service

---

## 4. 서비스 경계 정의

### 4.1 서비스별 책임

#### 4.1.1 User Service
**포트:** 8001

**책임:**
- 사용자 등록 및 인증
- API 키 암호화 저장
- 사용자 설정 관리
- 사용자 프로필 CRUD

**데이터베이스:**
- PostgreSQL: users, api_keys, user_settings

**API 엔드포인트:**
```
POST   /api/v1/users/register
POST   /api/v1/users/login
GET    /api/v1/users/profile
PUT    /api/v1/users/profile
POST   /api/v1/users/api-keys
GET    /api/v1/users/api-keys
DELETE /api/v1/users/api-keys/{key_id}
```

**기술 스택:**
- FastAPI
- PostgreSQL
- JWT 인증
- bcrypt (비밀번호 해싱)

---

#### 4.1.2 Exchange Integration Service
**포트:** 8002

**책임:**
- 거래소 API 통합 (OKX, Binance, Upbit 등)
- 주문 실행 및 추적
- 포지션 및 잔고 조회
- WebSocket 연결 관리
- 거래소별 에러 처리

**캐시:**
- Redis: 잔고, 포지션, 주문 상태 캐싱

**API 엔드포인트:**
```
POST   /api/v1/orders/create
GET    /api/v1/orders/{order_id}
DELETE /api/v1/orders/{order_id}
GET    /api/v1/positions
GET    /api/v1/balance
GET    /api/v1/exchanges/{exchange}/status
```

**기술 스택:**
- FastAPI
- CCXT
- Redis (캐싱)
- WebSocket

---

#### 4.1.3 Market Data Service
**포트:** 8003

**책임:**
- 실시간 시장 데이터 수집
- 기술적 지표 계산 (RSI, MA, ATR 등)
- 과거 데이터 저장
- 데이터 스트리밍

**데이터베이스:**
- TimescaleDB/InfluxDB (시계열 데이터)
- Redis (실시간 데이터 캐싱)

**API 엔드포인트:**
```
GET    /api/v1/market/price/{symbol}
GET    /api/v1/market/candles/{symbol}
GET    /api/v1/indicators/rsi/{symbol}
GET    /api/v1/indicators/ma/{symbol}
WS     /ws/market/{symbol}
```

**기술 스택:**
- FastAPI
- WebSocket
- TimescaleDB/InfluxDB
- Redis Streams
- Pandas/NumPy

---

#### 4.1.4 HYPERRSI Strategy Service
**포트:** 8004

**책임:**
- RSI 기반 전략 실행
- 트렌드 분석
- 신호 생성
- 포지션 관리
- TP/SL 설정

**데이터베이스:**
- PostgreSQL: 전략 설정, 실행 이력
- Redis: 실행 상태, 임시 데이터

**API 엔드포인트:**
```
POST   /api/v1/strategy/start
POST   /api/v1/strategy/stop
GET    /api/v1/strategy/status
PUT    /api/v1/strategy/settings
GET    /api/v1/strategy/performance
```

**기술 스택:**
- FastAPI
- Celery (백그라운드 작업)
- Redis (브로커)
- PostgreSQL

---

#### 4.1.5 GRID Strategy Service
**포트:** 8005

**책임:**
- 그리드 트레이딩 전략 실행
- 그리드 레벨 계산
- 주문 배치 및 리밸런싱
- 수익 추적

**데이터베이스:**
- PostgreSQL: 그리드 설정, 주문 이력
- Redis: 그리드 상태, 활성 주문

**API 엔드포인트:**
```
POST   /api/v1/grid/start
POST   /api/v1/grid/stop
GET    /api/v1/grid/status
PUT    /api/v1/grid/settings
GET    /api/v1/grid/performance
```

**기술 스택:**
- FastAPI
- Multiprocessing
- Redis
- PostgreSQL

---

#### 4.1.6 Notification Service
**포트:** 8006

**책임:**
- 텔레그램 알림 전송
- 알림 템플릿 관리
- 알림 이력 저장
- 알림 우선순위 처리

**데이터베이스:**
- PostgreSQL: 알림 이력
- Redis: 알림 큐

**API 엔드포인트:**
```
POST   /api/v1/notifications/send
GET    /api/v1/notifications/history
PUT    /api/v1/notifications/settings
```

**기술 스택:**
- FastAPI
- python-telegram-bot
- Redis (메시지 큐)
- PostgreSQL

---

#### 4.1.7 API Gateway
**포트:** 8000

**책임:**
- 단일 진입점
- 라우팅 및 로드 밸런싱
- 인증 및 권한 부여
- 속도 제한 (Rate Limiting)
- 요청/응답 로깅

**기술 스택:**
- Kong / Traefik / FastAPI
- JWT 검증
- Redis (속도 제한)

---

### 4.2 서비스 간 통신 패턴

#### 4.2.1 동기 통신 (Synchronous)
**REST API (HTTP/HTTPS)**
- User Service ↔ Exchange Integration Service
- Strategy Services → Market Data Service
- Strategy Services → Exchange Integration Service
- All Services → Notification Service

**사용 케이스:**
- 실시간 조회 (잔고, 포지션)
- 주문 실행
- 사용자 인증

---

#### 4.2.2 비동기 통신 (Asynchronous)
**메시지 큐 (RabbitMQ / Kafka / Redis Streams)**

**이벤트 타입:**
```
- OrderCreated
- OrderFilled
- OrderCancelled
- PositionOpened
- PositionClosed
- PriceAlert
- StrategyStarted
- StrategyStopped
```

**메시지 흐름 예시:**
```
Exchange Integration Service → OrderFilled Event
                              ↓
                    [Message Broker]
                              ↓
         ┌────────────────────┼────────────────────┐
         ↓                    ↓                    ↓
  Strategy Service    Notification Service   Analytics Service
```

---

### 4.3 데이터 소유권

| 서비스 | 소유 데이터 | 읽기 전용 접근 |
|--------|-------------|----------------|
| User Service | users, api_keys, user_settings | - |
| Exchange Integration | orders, positions | users (via API) |
| Market Data | candles, indicators | - |
| HYPERRSI Strategy | hyperrsi_settings, execution_logs | users, orders |
| GRID Strategy | grid_settings, grid_orders | users, orders |
| Notification | notifications, templates | users |

**원칙:**
- 각 서비스는 자신의 데이터베이스만 직접 접근
- 다른 서비스 데이터는 API를 통해서만 접근
- 공유 데이터는 이벤트를 통해 동기화

---

## 5. 단계별 마이그레이션 로드맵

### Phase 1: 준비 단계 (1-2주)

#### 1.1 인프라 셋업
```bash
# Docker Compose 환경 구성
# Kubernetes 클러스터 설정 (선택사항)
# CI/CD 파이프라인 구축
```

#### 1.2 공유 라이브러리 패키징
```bash
# shared 모듈을 별도 Python 패키지로 분리
# PyPI 프라이빗 저장소 또는 Git 서브모듈로 관리
```

**디렉토리 구조:**
```
tradingboost-common/
├── setup.py
├── tradingboost_common/
│   ├── config/
│   ├── models/
│   ├── utils/
│   └── exceptions/
```

#### 1.3 API 계약 정의
```yaml
# OpenAPI 3.0 스펙 작성
# 각 서비스별 API 문서화
```

---

### Phase 2: Notification Service 분리 (1주)

**가장 독립적인 서비스부터 시작**

#### 2.1 서비스 생성
```bash
mkdir -p services/notification-service
cd services/notification-service

# FastAPI 프로젝트 초기화
poetry init
poetry add fastapi uvicorn python-telegram-bot sqlalchemy redis
```

#### 2.2 코드 이전
```python
# 기존 shared/notifications/ 코드를 notification-service로 이동
# API 엔드포인트 추가
# 독립 실행 가능하도록 설정
```

#### 2.3 통합 테스트
```bash
# 기존 시스템에서 Notification Service API 호출로 변경
# 점진적 롤아웃 (Feature Flag 사용)
```

---

### Phase 3: Market Data Service 분리 (2주)

#### 3.1 TimescaleDB 설정
```sql
-- 시계열 데이터베이스 구성
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE candles (
    time TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC,
    volume NUMERIC
);

SELECT create_hypertable('candles', 'time');
```

#### 3.2 데이터 수집기 이전
```python
# 기존 WebSocket 클라이언트를 Market Data Service로 이동
# 기술적 지표 계산 로직 이전
# Redis Streams를 통한 실시간 데이터 스트리밍
```

#### 3.3 API 구현
```python
@app.get("/api/v1/market/price/{symbol}")
async def get_price(symbol: str):
    # Redis 캐시에서 최신 가격 조회
    pass

@app.get("/api/v1/indicators/rsi/{symbol}")
async def get_rsi(symbol: str, period: int = 14):
    # RSI 계산 및 반환
    pass
```

---

### Phase 4: User Service 분리 (1-2주)

#### 4.1 사용자 데이터 마이그레이션
```python
# 기존 users, api_keys 테이블을 User Service DB로 복사
# JWT 토큰 발급 로직 구현
```

#### 4.2 인증 미들웨어
```python
# API Gateway에 JWT 검증 미들웨어 추가
# 각 서비스에서 사용자 ID를 헤더로 전달받도록 수정
```

---

### Phase 5: Exchange Integration Service 분리 (2-3주)

#### 5.1 거래소 API 통합
```python
# shared/exchange_apis/ 코드를 Exchange Integration Service로 이동
# 주문 실행, 포지션 조회 API 구현
```

#### 5.2 WebSocket 관리
```python
# 거래소 WebSocket 연결을 Exchange Integration Service에서 관리
# 실시간 주문 상태 업데이트를 이벤트로 발행
```

---

### Phase 6: Strategy Services 분리 (각 2주)

#### 6.1 HYPERRSI Strategy Service
```python
# HYPERRSI/ 코드를 독립 서비스로 변환
# Market Data Service와 Exchange Integration Service API 호출
# Celery를 서비스 내부에서만 사용
```

#### 6.2 GRID Strategy Service
```python
# GRID/ 코드를 독립 서비스로 변환
# Multiprocessing 워커 관리 유지
```

---

### Phase 7: API Gateway 구성 (1주)

#### 7.1 Kong 또는 Traefik 설정
```yaml
# Kong 예시
services:
  - name: user-service
    url: http://user-service:8001
    routes:
      - paths:
          - /api/v1/users

  - name: exchange-service
    url: http://exchange-service:8002
    routes:
      - paths:
          - /api/v1/orders
          - /api/v1/positions

# ... 나머지 서비스
```

#### 7.2 인증 플러그인
```yaml
plugins:
  - name: jwt
    config:
      secret_is_base64: false
      key_claim_name: kid
```

---

## 6. 인프라 및 배포

### 6.1 Docker Compose 구성

```yaml
version: '3.8'

services:
  # API Gateway
  api-gateway:
    image: traefik:v2.10
    ports:
      - "8000:80"
      - "8080:8080"  # Dashboard
    volumes:
      - ./traefik.yml:/etc/traefik/traefik.yml
      - /var/run/docker.sock:/var/run/docker.sock

  # User Service
  user-service:
    build: ./services/user-service
    environment:
      - DATABASE_URL=postgresql://user:pass@postgres:5432/users
      - JWT_SECRET=${JWT_SECRET}
    depends_on:
      - postgres
      - redis
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.user.rule=PathPrefix(`/api/v1/users`)"

  # Exchange Integration Service
  exchange-service:
    build: ./services/exchange-service
    environment:
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.exchange.rule=PathPrefix(`/api/v1/orders`, `/api/v1/positions`)"

  # Market Data Service
  market-data-service:
    build: ./services/market-data-service
    environment:
      - TIMESCALE_URL=postgresql://user:pass@timescaledb:5432/marketdata
      - REDIS_URL=redis://redis:6379/1
    depends_on:
      - timescaledb
      - redis

  # HYPERRSI Strategy Service
  hyperrsi-service:
    build: ./services/hyperrsi-service
    environment:
      - DATABASE_URL=postgresql://user:pass@postgres:5432/hyperrsi
      - CELERY_BROKER_URL=redis://redis:6379/2
    depends_on:
      - postgres
      - redis
      - celery-worker-hyperrsi

  # GRID Strategy Service
  grid-service:
    build: ./services/grid-service
    environment:
      - DATABASE_URL=postgresql://user:pass@postgres:5432/grid
      - REDIS_URL=redis://redis:6379/3
    depends_on:
      - postgres
      - redis

  # Notification Service
  notification-service:
    build: ./services/notification-service
    environment:
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - REDIS_URL=redis://redis:6379/4
    depends_on:
      - redis

  # Celery Worker (HYPERRSI)
  celery-worker-hyperrsi:
    build: ./services/hyperrsi-service
    command: celery -A app.celery worker --loglevel=info
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/2
    depends_on:
      - redis

  # Databases
  postgres:
    image: postgres:15
    environment:
      - POSTGRES_PASSWORD=password
    volumes:
      - postgres-data:/var/lib/postgresql/data

  timescaledb:
    image: timescale/timescaledb:latest-pg15
    environment:
      - POSTGRES_PASSWORD=password
    volumes:
      - timescale-data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    volumes:
      - redis-data:/data

  # Message Broker (선택사항)
  rabbitmq:
    image: rabbitmq:3-management
    ports:
      - "15672:15672"
    environment:
      - RABBITMQ_DEFAULT_USER=admin
      - RABBITMQ_DEFAULT_PASS=password

volumes:
  postgres-data:
  timescale-data:
  redis-data:
```

---

### 6.2 Kubernetes 배포 (프로덕션)

#### 6.2.1 Namespace
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: trading-boost
```

#### 6.2.2 User Service Deployment
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: user-service
  namespace: trading-boost
spec:
  replicas: 3
  selector:
    matchLabels:
      app: user-service
  template:
    metadata:
      labels:
        app: user-service
    spec:
      containers:
      - name: user-service
        image: tradingboost/user-service:latest
        ports:
        - containerPort: 8001
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: db-credentials
              key: user-service-url
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
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
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: user-service
  namespace: trading-boost
spec:
  selector:
    app: user-service
  ports:
  - port: 8001
    targetPort: 8001
```

#### 6.2.3 Horizontal Pod Autoscaler
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: user-service-hpa
  namespace: trading-boost
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: user-service
  minReplicas: 2
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

---

## 7. 데이터 관리 전략

### 7.1 데이터베이스별 역할

| 데이터베이스 | 사용 서비스 | 데이터 타입 |
|-------------|------------|------------|
| PostgreSQL (users) | User Service | 사용자, API 키, 설정 |
| PostgreSQL (trading) | Exchange Service | 주문, 포지션 이력 |
| PostgreSQL (strategies) | Strategy Services | 전략 설정, 실행 로그 |
| TimescaleDB | Market Data Service | 시계열 가격 데이터 |
| Redis | All Services | 캐시, 세션, 큐 |

### 7.2 분산 트랜잭션 처리

**Saga 패턴 사용:**

```python
# 예시: 주문 생성 Saga
class CreateOrderSaga:
    async def execute(self, user_id, order_data):
        # Step 1: 잔고 확인 및 예약
        balance_reserved = await self.reserve_balance(user_id, order_data.amount)
        if not balance_reserved:
            return {"status": "failed", "reason": "insufficient balance"}
        
        try:
            # Step 2: 거래소에 주문 전송
            order = await self.exchange_service.create_order(order_data)
            
            # Step 3: 주문 이력 저장
            await self.save_order_history(order)
            
            # Step 4: 잔고 차감 확정
            await self.confirm_balance(user_id, order_data.amount)
            
            return {"status": "success", "order": order}
            
        except Exception as e:
            # 보상 트랜잭션 (Compensating Transaction)
            await self.release_balance(user_id, order_data.amount)
            return {"status": "failed", "reason": str(e)}
```

### 7.3 데이터 동기화

**이벤트 소싱 (Event Sourcing):**

```python
# 주문 이벤트 발행
async def publish_order_event(order):
    event = {
        "event_type": "OrderCreated",
        "timestamp": datetime.utcnow().isoformat(),
        "data": {
            "order_id": order.id,
            "user_id": order.user_id,
            "symbol": order.symbol,
            "side": order.side,
            "amount": order.amount,
            "price": order.price
        }
    }
    
    # Redis Streams 또는 Kafka로 발행
    await redis.xadd("order-events", event)
```

---

## 8. API 설계 및 통신

### 8.1 RESTful API 규칙

**URL 구조:**
```
/api/v1/{service}/{resource}/{id}/{action}
```

**예시:**
```
GET    /api/v1/users/123
PUT    /api/v1/users/123
POST   /api/v1/orders
GET    /api/v1/orders/456/status
POST   /api/v1/strategy/hyperrsi/start
```

**HTTP 메서드:**
- GET: 조회
- POST: 생성
- PUT: 전체 업데이트
- PATCH: 부분 업데이트
- DELETE: 삭제

**상태 코드:**
- 200 OK: 성공
- 201 Created: 생성 성공
- 400 Bad Request: 잘못된 요청
- 401 Unauthorized: 인증 실패
- 403 Forbidden: 권한 없음
- 404 Not Found: 리소스 없음
- 500 Internal Server Error: 서버 오류
- 503 Service Unavailable: 서비스 사용 불가

### 8.2 API 버전 관리

**URL 버전:**
```python
# v1 API
@app.get("/api/v1/users/{user_id}")
async def get_user_v1(user_id: int):
    pass

# v2 API (하위 호환성 없는 변경)
@app.get("/api/v2/users/{user_id}")
async def get_user_v2(user_id: int):
    # 새로운 응답 구조
    pass
```

### 8.3 서비스 간 통신 패턴

#### 8.3.1 동기 HTTP 호출
```python
import httpx

class ExchangeServiceClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=10.0)
    
    async def create_order(self, user_id: str, order_data: dict):
        response = await self.client.post(
            f"{self.base_url}/api/v1/orders",
            json=order_data,
            headers={"X-User-ID": user_id}
        )
        response.raise_for_status()
        return response.json()
    
    async def get_position(self, user_id: str, symbol: str):
        response = await self.client.get(
            f"{self.base_url}/api/v1/positions",
            params={"symbol": symbol},
            headers={"X-User-ID": user_id}
        )
        response.raise_for_status()
        return response.json()
```

#### 8.3.2 비동기 메시지 발행
```python
import aio_pika

class EventPublisher:
    async def publish(self, event_type: str, data: dict):
        connection = await aio_pika.connect_robust("amqp://rabbitmq:5672")
        channel = await connection.channel()
        
        message = aio_pika.Message(
            body=json.dumps({
                "type": event_type,
                "data": data,
                "timestamp": datetime.utcnow().isoformat()
            }).encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT
        )
        
        await channel.default_exchange.publish(
            message,
            routing_key=event_type
        )
        
        await connection.close()
```

#### 8.3.3 이벤트 구독
```python
class EventSubscriber:
    async def subscribe(self, event_types: list[str], callback):
        connection = await aio_pika.connect_robust("amqp://rabbitmq:5672")
        channel = await connection.channel()
        queue = await channel.declare_queue("strategy-service-queue", durable=True)
        
        for event_type in event_types:
            await queue.bind(channel.default_exchange, routing_key=event_type)
        
        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process():
                    data = json.loads(message.body.decode())
                    await callback(data)
```

---

## 9. 모니터링 및 관찰성

### 9.1 로깅

**구조화된 로그 (JSON):**
```python
import structlog

logger = structlog.get_logger()

logger.info(
    "order_created",
    user_id=user_id,
    order_id=order.id,
    symbol=order.symbol,
    side=order.side,
    amount=order.amount,
    service="exchange-service"
)
```

**중앙 집중식 로그 수집 (ELK Stack):**
```yaml
# Filebeat 구성
filebeat.inputs:
- type: container
  paths:
    - '/var/lib/docker/containers/*/*.log'

output.elasticsearch:
  hosts: ["elasticsearch:9200"]

setup.kibana:
  host: "kibana:5601"
```

### 9.2 메트릭

**Prometheus + Grafana:**

```python
from prometheus_client import Counter, Histogram, Gauge
from prometheus_fastapi_instrumentator import Instrumentator

# 메트릭 정의
order_counter = Counter(
    "orders_total",
    "Total number of orders",
    ["service", "status"]
)

order_latency = Histogram(
    "order_latency_seconds",
    "Order execution latency",
    ["service"]
)

active_positions = Gauge(
    "active_positions",
    "Number of active positions",
    ["user_id", "symbol"]
)

# FastAPI에 Prometheus 미들웨어 추가
app = FastAPI()
Instrumentator().instrument(app).expose(app)

# 메트릭 기록
@app.post("/api/v1/orders")
async def create_order(order_data: OrderCreate):
    with order_latency.labels(service="exchange-service").time():
        order = await execute_order(order_data)
        order_counter.labels(service="exchange-service", status="success").inc()
    return order
```

**Grafana 대시보드 예시:**
```json
{
  "dashboard": {
    "title": "TradingBoost Services Overview",
    "panels": [
      {
        "title": "Request Rate",
        "targets": [
          {
            "expr": "rate(http_requests_total[5m])"
          }
        ]
      },
      {
        "title": "Error Rate",
        "targets": [
          {
            "expr": "rate(http_requests_total{status=~\"5..\"}[5m])"
          }
        ]
      },
      {
        "title": "Active Positions",
        "targets": [
          {
            "expr": "sum(active_positions) by (symbol)"
          }
        ]
      }
    ]
  }
}
```

### 9.3 분산 추적

**OpenTelemetry + Jaeger:**

```python
from opentelemetry import trace
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Tracer 설정
trace.set_tracer_provider(TracerProvider())
jaeger_exporter = JaegerExporter(
    agent_host_name="jaeger",
    agent_port=6831,
)
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(jaeger_exporter)
)

# FastAPI 계측
app = FastAPI()
FastAPIInstrumentor.instrument_app(app)

# 커스텀 스팬
tracer = trace.get_tracer(__name__)

async def execute_trade(order_data):
    with tracer.start_as_current_span("execute_trade") as span:
        span.set_attribute("user_id", order_data.user_id)
        span.set_attribute("symbol", order_data.symbol)
        
        # 시장 데이터 조회
        with tracer.start_as_current_span("fetch_market_data"):
            market_data = await market_service.get_price(order_data.symbol)
        
        # 주문 실행
        with tracer.start_as_current_span("create_exchange_order"):
            order = await exchange_service.create_order(order_data)
        
        return order
```

### 9.4 헬스 체크

```python
@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/ready")
async def readiness_check():
    # 의존성 확인
    checks = {
        "database": await check_database(),
        "redis": await check_redis(),
        "exchange_api": await check_exchange_api()
    }
    
    if all(checks.values()):
        return {"status": "ready", "checks": checks}
    else:
        raise HTTPException(status_code=503, detail={"status": "not ready", "checks": checks})
```

---

## 10. 보안 및 인증

### 10.1 JWT 기반 인증

**토큰 발급 (User Service):**
```python
import jwt
from datetime import datetime, timedelta

def create_access_token(user_id: int, expires_delta: timedelta = None):
    if expires_delta is None:
        expires_delta = timedelta(hours=24)
    
    expire = datetime.utcnow() + expires_delta
    payload = {
        "sub": user_id,
        "exp": expire,
        "iat": datetime.utcnow()
    }
    
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")
    return token

@app.post("/api/v1/users/login")
async def login(credentials: LoginRequest):
    user = await authenticate_user(credentials.username, credentials.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    access_token = create_access_token(user.id)
    return {"access_token": access_token, "token_type": "bearer"}
```

**토큰 검증 (API Gateway):**
```python
from fastapi import Depends, HTTPException, Header
import jwt

async def verify_token(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    
    token = authorization.replace("Bearer ", "")
    
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return user_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

@app.get("/api/v1/protected")
async def protected_route(user_id: int = Depends(verify_token)):
    return {"user_id": user_id, "message": "Authenticated"}
```

### 10.2 API 키 암호화

```python
from cryptography.fernet import Fernet

class APIKeyEncryption:
    def __init__(self, encryption_key: str):
        self.fernet = Fernet(encryption_key.encode())
    
    def encrypt(self, api_key: str) -> str:
        return self.fernet.encrypt(api_key.encode()).decode()
    
    def decrypt(self, encrypted_key: str) -> str:
        return self.fernet.decrypt(encrypted_key.encode()).decode()

# 사용 예시
encryptor = APIKeyEncryption(settings.ENCRYPTION_KEY)

async def store_api_key(user_id: int, api_key: str):
    encrypted = encryptor.encrypt(api_key)
    await db.execute(
        "INSERT INTO api_keys (user_id, encrypted_key) VALUES ($1, $2)",
        user_id, encrypted
    )

async def get_api_key(user_id: int) -> str:
    encrypted = await db.fetchval(
        "SELECT encrypted_key FROM api_keys WHERE user_id = $1",
        user_id
    )
    return encryptor.decrypt(encrypted)
```

### 10.3 속도 제한 (Rate Limiting)

```python
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter
import redis.asyncio as aioredis

# 초기화
@app.on_event("startup")
async def startup():
    redis = await aioredis.from_url("redis://localhost:6379", encoding="utf-8")
    await FastAPILimiter.init(redis)

# 라우트에 적용
@app.post("/api/v1/orders", dependencies=[Depends(RateLimiter(times=10, seconds=60))])
async def create_order(order_data: OrderCreate):
    # 1분에 최대 10번 호출 가능
    return await execute_order(order_data)
```

### 10.4 CORS 설정

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://tradingboost.com"],  # 프로덕션에서는 특정 도메인만 허용
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)
```

---

## 11. 배포 및 운영

### 11.1 CI/CD 파이프라인

**GitHub Actions 예시:**
```yaml
name: Build and Deploy

on:
  push:
    branches: [main]
    paths:
      - 'services/user-service/**'

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Build Docker image
        run: |
          docker build -t tradingboost/user-service:${{ github.sha }} \
            -t tradingboost/user-service:latest \
            ./services/user-service
      
      - name: Run tests
        run: |
          docker run tradingboost/user-service:${{ github.sha }} pytest
      
      - name: Push to registry
        run: |
          echo ${{ secrets.DOCKER_PASSWORD }} | docker login -u ${{ secrets.DOCKER_USERNAME }} --password-stdin
          docker push tradingboost/user-service:${{ github.sha }}
          docker push tradingboost/user-service:latest
  
  deploy:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to Kubernetes
        run: |
          kubectl set image deployment/user-service \
            user-service=tradingboost/user-service:${{ github.sha }} \
            -n trading-boost
```

### 11.2 롤링 업데이트

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: user-service
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1        # 업데이트 중 추가 가능한 최대 Pod 수
      maxUnavailable: 0  # 업데이트 중 사용 불가 최대 Pod 수
  template:
    # ... pod spec
```

### 11.3 블루-그린 배포

```bash
# 그린 환경 배포
kubectl apply -f user-service-green.yaml

# 헬스 체크 확인
kubectl wait --for=condition=ready pod -l version=green -n trading-boost

# 트래픽 전환 (Service selector 변경)
kubectl patch service user-service -n trading-boost \
  -p '{"spec":{"selector":{"version":"green"}}}'

# 블루 환경 제거
kubectl delete deployment user-service-blue -n trading-boost
```

### 11.4 카나리 배포

```yaml
# Istio VirtualService를 사용한 카나리 배포
apiVersion: networking.istio.io/v1alpha3
kind: VirtualService
metadata:
  name: user-service
spec:
  hosts:
  - user-service
  http:
  - match:
    - headers:
        canary:
          exact: "true"
    route:
    - destination:
        host: user-service
        subset: v2
  - route:
    - destination:
        host: user-service
        subset: v1
      weight: 90
    - destination:
        host: user-service
        subset: v2
      weight: 10  # 10% 트래픽을 새 버전으로
```

---

## 12. 마이그레이션 체크리스트

### Phase 1: 준비 (1-2주)
- [ ] 팀 교육 (마이크로서비스 개념, Docker, Kubernetes)
- [ ] 개발 환경 셋업 (Docker, Kubernetes 클러스터)
- [ ] CI/CD 파이프라인 구축
- [ ] 모니터링 인프라 구축 (Prometheus, Grafana, ELK)
- [ ] API 문서화 (OpenAPI 스펙)
- [ ] 공유 라이브러리 패키징

### Phase 2: Notification Service (1주)
- [ ] 서비스 디렉토리 구조 생성
- [ ] Dockerfile 작성
- [ ] API 엔드포인트 구현
- [ ] 단위 테스트 작성
- [ ] 통합 테스트 작성
- [ ] Docker Compose에 추가
- [ ] 기존 시스템과 통합

### Phase 3: Market Data Service (2주)
- [ ] TimescaleDB 설정
- [ ] 데이터 수집기 이전
- [ ] 기술적 지표 계산 로직 이전
- [ ] WebSocket 스트리밍 구현
- [ ] Redis Streams 설정
- [ ] 성능 테스트
- [ ] 기존 시스템과 통합

### Phase 4: User Service (1-2주)
- [ ] 사용자 데이터베이스 분리
- [ ] JWT 인증 구현
- [ ] API 엔드포인트 구현
- [ ] 데이터 마이그레이션 스크립트
- [ ] 보안 감사
- [ ] 기존 시스템과 통합

### Phase 5: Exchange Integration Service (2-3주)
- [ ] 거래소 API 통합 이전
- [ ] 주문 실행 로직 이전
- [ ] WebSocket 관리 이전
- [ ] 캐싱 전략 구현
- [ ] 재시도 로직 구현
- [ ] 장애 시나리오 테스트

### Phase 6: Strategy Services (각 2주)
- [ ] HYPERRSI Service 분리
- [ ] GRID Service 분리
- [ ] Celery 설정 이전
- [ ] 전략 로직 테스트
- [ ] 성능 최적화

### Phase 7: API Gateway (1주)
- [ ] Traefik/Kong 설정
- [ ] 라우팅 규칙 구성
- [ ] 인증 미들웨어 설정
- [ ] 속도 제한 설정
- [ ] CORS 설정

### Phase 8: 최종 검증 (1-2주)
- [ ] 전체 시스템 통합 테스트
- [ ] 부하 테스트
- [ ] 장애 복구 테스트
- [ ] 보안 감사
- [ ] 성능 벤치마크
- [ ] 문서 업데이트

---

## 13. 모범 사례 및 권장사항

### 13.1 서비스 설계 원칙

1. **단일 책임 원칙**: 각 서비스는 하나의 비즈니스 기능에 집중
2. **느슨한 결합**: 서비스 간 최소한의 의존성 유지
3. **높은 응집력**: 관련된 기능은 같은 서비스에 배치
4. **API 우선 설계**: API 계약을 먼저 정의
5. **Fail Fast**: 문제를 조기에 발견하고 빠르게 실패

### 13.2 운영 베스트 프랙티스

1. **헬스 체크**: 모든 서비스에 /health, /ready 엔드포인트 구현
2. **구조화된 로깅**: JSON 로그로 중앙 집중식 분석 가능하도록
3. **메트릭 수집**: Prometheus 메트릭 노출
4. **분산 추적**: OpenTelemetry로 요청 흐름 추적
5. **Circuit Breaker**: 장애 격리 및 빠른 실패
6. **Retry with Backoff**: 일시적 장애 대응
7. **Timeout 설정**: 모든 외부 호출에 타임아웃 설정

### 13.3 데이터 관리

1. **Database per Service**: 각 서비스가 자신의 DB 소유
2. **이벤트 소싱**: 중요한 비즈니스 이벤트 저장
3. **CQRS**: 읽기와 쓰기 모델 분리 (필요시)
4. **Saga 패턴**: 분산 트랜잭션 처리
5. **캐싱 전략**: Redis를 활용한 성능 최적화

### 13.4 보안

1. **최소 권한 원칙**: 필요한 권한만 부여
2. **비밀 관리**: Kubernetes Secrets 또는 Vault 사용
3. **네트워크 정책**: 서비스 간 통신 제한
4. **API 인증**: JWT 또는 API 키
5. **TLS/SSL**: 모든 통신 암호화

---

## 14. 문제 해결 가이드

### 14.1 일반적인 문제

**문제: 서비스 간 통신 지연**
- 원인: 동기 호출 체인이 너무 길거나, 네트워크 레이턴시
- 해결:
  - 비동기 메시지 사용
  - 캐싱 전략 도입
  - 서비스 콜로케이션 (같은 데이터센터)
  - API Gateway에서 요청 집계

**문제: 분산 트랜잭션 실패**
- 원인: 서비스 중 하나가 실패했지만 롤백되지 않음
- 해결:
  - Saga 패턴 구현
  - 보상 트랜잭션 (Compensating Transaction)
  - 멱등성 보장
  - 이벤트 소싱으로 상태 추적

**문제: 서비스 디스커버리 실패**
- 원인: DNS 문제, 네트워크 파티션
- 해결:
  - Kubernetes DNS 확인
  - 서비스 메시 (Istio/Linkerd) 사용
  - 헬스 체크 구현
  - Circuit Breaker 패턴

### 14.2 디버깅 팁

```bash
# 서비스 로그 확인
kubectl logs -f deployment/user-service -n trading-boost

# 서비스 상태 확인
kubectl get pods -n trading-boost

# 서비스 디스크립션
kubectl describe pod user-service-xxx -n trading-boost

# 서비스 간 통신 테스트
kubectl exec -it user-service-xxx -n trading-boost -- curl http://exchange-service:8002/health

# Jaeger에서 분산 추적 확인
# http://jaeger-ui:16686
```

---

## 15. 결론

마이크로서비스 아키텍처로의 전환은 큰 프로젝트이지만, 점진적으로 진행하면 리스크를 최소화할 수 있습니다.

**핵심 포인트:**
1. ✅ **점진적 마이그레이션**: Strangler Fig Pattern 사용
2. ✅ **독립적 서비스부터**: Notification Service 같은 독립적 기능부터 시작
3. ✅ **강력한 모니터링**: 초기부터 관찰성 구축
4. ✅ **명확한 API 계약**: OpenAPI 스펙으로 문서화
5. ✅ **자동화**: CI/CD, 테스트, 배포 자동화

**다음 단계:**
1. 팀과 마이그레이션 계획 논의
2. Phase 1 준비 단계 시작
3. Notification Service 분리로 실습
4. 경험을 바탕으로 다음 단계 조정

**참고 자료:**
- [Martin Fowler - Microservices](https://martinfowler.com/articles/microservices.html)
- [Building Microservices (O'Reilly)](https://www.oreilly.com/library/view/building-microservices-2nd/9781492034018/)
- [Kubernetes Documentation](https://kubernetes.io/docs/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)

---

**작성일:** 2024
**버전:** 1.0
**작성자:** TradingBoost-Strategy Team
