# TradingBoost-Strategy 아키텍처

암호화폐 거래 플랫폼 TradingBoost-Strategy의 종합 기술 아키텍처 문서입니다.

## 목차

1. [시스템 개요](#시스템-개요)
2. [아키텍처 패턴](#아키텍처-패턴)
3. [컴포넌트 분석](#컴포넌트-분석)
4. [데이터 흐름](#데이터-흐름)
5. [기술 스택](#기술-스택)
6. [설계 결정](#설계-결정)
7. [개선 권장사항](#개선-권장사항)

---

## 시스템 개요

TradingBoost-Strategy는 명확한 관심사 분리를 갖춘 계층형 아키텍처를 구현하는 모노레포 기반 알고리즘 트레이딩 플랫폼입니다. 이 시스템은 통합된 `shared` 모듈을 통해 공통 인프라를 공유하는 두 개의 독립적인 트레이딩 전략(HYPERRSI 및 GRID)으로 구성됩니다.

### 상위 수준 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│                         클라이언트 계층                           │
│  (웹 UI, 모바일 앱, API 클라이언트, 텔레그램 봇)                   │
└─────────────────────────────────────────────────────────────────┘
                              ↓ HTTP/WebSocket
┌─────────────────────────────────────────────────────────────────┐
│                      API 게이트웨이 계층                          │
│         FastAPI (HYPERRSI:8000 | GRID:8012)                     │
│  - 요청 검증 (Pydantic)                                          │
│  - 인증 및 권한 부여                                              │
│  - CORS 및 보안 미들웨어                                          │
│  - 요청 ID 추적                                                  │
│  - 구조화된 에러 처리                                             │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                      서비스 계층                                  │
│  - 트레이딩 서비스 (주문 실행, 포지션 관리)                         │
│  - 거래소 서비스 (다중 거래소 추상화)                               │
│  - 사용자 관리                                                    │
│  - 리스크 관리                                                    │
│  - 알림 서비스 (텔레그램)                                          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    전략 실행 계층                                  │
│  ┌──────────────────┐              ┌──────────────────┐         │
│  │   HYPERRSI       │              │      GRID        │         │
│  │  - RSI 분석      │              │  - 그리드 설정    │         │
│  │  - 추세 감지     │              │  - 리밸런싱       │         │
│  │  - 신호 생성     │              │  - 익절          │         │
│  └──────────────────┘              └──────────────────┘         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                   데이터 및 통합 계층                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  리포지토리   │  │   거래소     │  │  WebSocket   │          │
│  │    계층      │  │   핸들러     │  │   클라이언트  │          │
│  │ (DB 접근)    │  │  (ccxt API)  │  │  (실시간)    │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    인프라 계층                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  PostgreSQL  │  │    Redis     │  │    Celery    │          │
│  │  (프로덕션)   │  │  (캐시/큐)   │  │  (HYPERRSI)  │          │
│  │   SQLite     │  │              │  │ Multiprocess │          │
│  │   (개발)     │  │              │  │    (GRID)    │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

### 주요 특성

- **모노레포 구조**: 공통 코드를 공유하는 여러 독립 애플리케이션을 담은 단일 저장소
- **공유 인프라**: 중앙화된 데이터베이스, 로깅, 에러 처리 및 거래소 통합
- **비동기 우선**: 고성능을 위한 스택 전반의 논블로킹 I/O
- **이벤트 드리븐**: 비동기 작업 처리를 위한 Celery 작업 큐(HYPERRSI) 및 멀티프로세싱(GRID)
- **실시간**: 실시간 시장 데이터 및 상태 업데이트를 위한 WebSocket 연결
- **다중 거래소**: 다양한 암호화폐 거래소를 위한 통합 인터페이스(OKX, 바이낸스, 업비트, 비트겟, 바이비트)
- **프로덕션 준비**: 구조화된 로깅, 종합적인 에러 처리, 연결 풀링 및 모니터링

---

## 아키텍처 패턴

### 1. 계층형 아키텍처

시스템은 명확한 관심사 분리를 갖춘 엄격한 계층형 아키텍처를 따릅니다:

```
┌─────────────────────────────────────────┐
│        프레젠테이션 계층                  │  라우트, WebSocket 핸들러
│        (라우트/API 엔드포인트)            │
├─────────────────────────────────────────┤
│        비즈니스 로직 계층                 │  서비스, 전략 구현
│        (서비스)                          │
├─────────────────────────────────────────┤
│        데이터 접근 계층                   │  리포지토리, ORM
│        (리포지토리)                       │
├─────────────────────────────────────────┤
│        통합 계층                         │  거래소 API, 외부 서비스
│        (핸들러/클라이언트)                │
├─────────────────────────────────────────┤
│        인프라 계층                        │  데이터베이스, 캐시, 메시지 큐
│        (Database/Redis/Celery)          │
└─────────────────────────────────────────┘
```

**장점**:
- 명확한 관심사 분리
- 개별 계층 테스트 용이
- 유지보수 및 확장 가능
- 팀 협업 촉진

**현재 구현 상태**:
- ✅ 두 모듈 전반에 걸쳐 잘 정의된 계층 경계
- ✅ 공통 기능을 위한 공유 인프라 계층
- ✅ 모듈 간 일관된 서비스 계층 패턴

### 2. 리포지토리 패턴

데이터 접근은 리포지토리를 통해 추상화됩니다:

```python
# 예시: 사용자 리포지토리
class UserRepository:
    async def get_user_by_id(self, user_id: int) -> User | None
    async def create_user(self, user_data: UserDto) -> User
    async def update_user(self, user_id: int, updates: dict) -> User
    async def delete_user(self, user_id: int) -> bool
```

**장점**:
- 비즈니스 로직과 데이터 영속성 분리
- 테스트를 위한 목 객체 생성 용이
- 다중 데이터 소스 지원
- 중앙화된 쿼리 로직

**현재 상태**:
- ✅ GRID 및 HYPERRSI 모두에 구현됨
- ✅ PostgreSQL(프로덕션) 및 SQLite(개발) 지원
- ✅ 적절한 연결 풀링을 갖춘 비동기 세션 관리

### 3. 의존성 주입

FastAPI의 의존성 주입 시스템이 전반적으로 사용됩니다:

```python
async def get_trading_service(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis)
) -> TradingService:
    return TradingService(user_id, db, redis)

@router.post("/trading/start")
async def start_trading(
    service: TradingService = Depends(get_trading_service)
):
    return await service.start()
```

**장점**:
- 컴포넌트 간 느슨한 결합
- 목 의존성을 사용한 테스트 용이
- 명확한 의존성 그래프
- 미들웨어 및 라이프사이클 관리 지원

**현재 상태**:
- ✅ 라우트 핸들러에서 잘 활용됨
- ✅ 일관된 의존성 주입 패턴
- ✅ 시작/종료를 위한 Lifespan 컨텍스트 매니저

### 4. 전략 패턴

트레이딩 전략은 플러그인 가능한 컴포넌트로 구현됩니다:

```python
class TradingStrategy(ABC):
    @abstractmethod
    async def analyze(self, market_data: MarketData) -> Signal

    @abstractmethod
    async def execute(self, signal: Signal) -> Order

# 구현체
class HyperRSIStrategy(TradingStrategy): ...
class GridStrategy(TradingStrategy): ...
```

**현재 상태**:
- ✅ 명확한 분리를 갖춘 전략 패턴 구현
- ✅ 새로운 전략 추가가 용이한 모듈식 설계
- ✅ 공유 기술 지표 및 유틸리티

### 5. Async/Await 아키텍처

코드베이스 전반의 현대적인 비동기 패턴:

```python
# 지수 백오프를 갖춘 비동기 재시도
async def retry_async(
    func: Callable[..., Awaitable[T]],
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,)
) -> T:
    # 적절한 에러 처리를 갖춘 구현
    ...

# 리소스를 위한 비동기 컨텍스트 매니저
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 시작
    await init_db()
    await init_redis()
    yield
    # 종료
    await close_db()
    await close_redis()
```

**현재 상태**:
- ✅ AsyncIO를 사용한 비동기 우선 접근
- ✅ SQLAlchemy 2.0을 사용한 비동기 데이터베이스 세션
- ✅ 비동기 Redis 작업
- ✅ 지수 백오프를 갖춘 재시도 로직
- ✅ 작업 추적 및 우아한 종료

### 6. 공유 인프라 패턴

중앙화된 인프라 관리:

```python
# 중앙화된 설정
from shared.config import get_settings
settings = get_settings()

# 중앙화된 데이터베이스 세션
from shared.database.session import get_db, transactional

# 중앙화된 에러 처리
from shared.errors import TradingException, ErrorCode

# 중앙화된 로깅
from shared.logging import get_logger, setup_json_logger
```

**장점**:
- 공통 기능을 위한 단일 진실 공급원
- 전략 간 일관된 동작
- 유지보수 및 업데이트 용이
- 더 나은 코드 재사용성

---

## 컴포넌트 분석

### HYPERRSI 전략 모듈

추세 분석 및 모멘텀 지표를 갖춘 RSI 기반 트레이딩 전략.

#### 디렉토리 구조

```
HYPERRSI/
├── src/
│   ├── api/                    # API 계층
│   │   ├── routes/            # FastAPI 엔드포인트
│   │   │   ├── trading.py     # 트레이딩 작업
│   │   │   ├── account.py     # 계정 관리
│   │   │   ├── order/         # 모듈화된 주문 라우트
│   │   │   ├── position.py    # 포지션 관리
│   │   │   ├── settings.py    # 사용자 설정
│   │   │   └── stats.py       # 통계 및 분석
│   │   ├── exchange/          # 거래소 통합
│   │   │   └── okx/          # OKX 특화 구현
│   │   └── middleware.py      # 요청/응답 미들웨어
│   │
│   ├── bot/                    # 텔레그램 봇
│   │   ├── command/           # 명령 핸들러
│   │   ├── handlers.py        # 메시지 핸들러
│   │   └── keyboards/         # 인라인 키보드
│   │
│   ├── core/                   # 핵심 기능
│   │   ├── database.py        # 데이터베이스 초기화 (레거시)
│   │   ├── logger.py          # 로깅 설정 (레거시)
│   │   └── models/            # SQLAlchemy 모델
│   │
│   ├── trading/                # 트레이딩 로직
│   │   ├── services/          # 트레이딩 서비스
│   │   ├── strategy/          # 전략 구현
│   │   ├── monitoring/        # 주문 및 포지션 모니터링
│   │   ├── modules/           # 모듈화된 트레이딩 컴포넌트
│   │   └── utils/             # 트레이딩 유틸리티
│   │
│   ├── tasks/                  # Celery 작업
│   │   ├── trading_tasks.py   # 트레이딩 백그라운드 작업
│   │   └── websocket_tasks.py # WebSocket 관리
│   │
│   ├── data_collector/         # 시장 데이터 수집
│   │   └── integrated_data_collector_save.py
│   │
│   ├── services/               # 비즈니스 서비스
│   │   └── redis_service.py   # Redis 서비스 (레거시)
│   │
│   └── utils/                  # 유틸리티
│       ├── async_helpers.py   # 비동기 유틸리티
│       ├── types.py           # 타입 정의
│       └── indicators.py      # 기술 지표
│
├── websocket/                  # WebSocket 서버
│   ├── main.py                # WebSocket 진입점
│   └── position_monitor.py    # 포지션 모니터링
│
├── scripts/                    # 유틸리티 스크립트
│   ├── init_db.py            # 데이터베이스 초기화
│   └── test_postgresql.py     # 데이터베이스 테스팅
│
├── main.py                     # FastAPI 앱 초기화
└── requirements.txt            # Python 의존성
```

#### 주요 컴포넌트

**1. API 라우트** (`src/api/routes/`)
- 트레이딩 작업을 위한 RESTful 엔드포인트
- Pydantic 모델을 사용한 요청 검증
- 응답 포맷팅 및 에러 처리
- 실시간 업데이트를 위한 WebSocket 엔드포인트
- 모듈화된 구성 (주문 라우트를 서비스로 분할)

**2. 트레이딩 서비스** (`src/trading/services/`)
- 주문 실행 로직
- 포지션 관리
- 리스크 계산
- P&L 추적
- 진입/청산/피라미딩을 갖춘 모듈화된 포지션 핸들러

**3. Celery 작업** (`src/tasks/`)
- 비동기 주문 처리
- 예약된 시장 분석
- 포지션 모니터링
- 데이터 수집 작업
- WebSocket 연결 관리

**4. 텔레그램 봇** (`src/bot/`)
- 사용자 등록 및 인증
- 채팅 인터페이스를 통한 트레이딩 제어
- 실시간 알림
- 계정 관리 명령
- 양방향 트레이딩 설정

**5. 거래소 통합** (`src/api/exchange/okx/`)
- OKX 특화 클라이언트 구현
- WebSocket 관리
- 에러 처리 및 재시도 로직
- 공유 거래소 인프라 사용

#### 트레이딩 흐름

```
1. 사용자 입력 → API 엔드포인트
                    ↓
2. 요청 검증 (Pydantic)
                    ↓
3. 서비스 계층 처리
                    ↓
4. 전략 분석 (RSI + 추세)
                    ↓
5. 신호 생성
                    ↓
6. 리스크 관리 체크
                    ↓
7. 주문 실행 (거래소 API)
                    ↓
8. 포지션 업데이트 (데이터베이스)
                    ↓
9. 알림 (텔레그램)
                    ↓
10. 사용자에게 응답
```

### GRID 전략 모듈

자동 리밸런싱을 갖춘 그리드 기반 트레이딩 전략.

#### 디렉토리 구조

```
GRID/
├── api/                        # FastAPI 애플리케이션
│   ├── app.py                 # 메인 애플리케이션
│   └── apilist.py             # API 목록 관리
│
├── core/                       # 핵심 기능
│   ├── redis.py               # Redis 클라이언트
│   └── exceptions.py          # 커스텀 예외
│
├── database/                   # 데이터베이스 계층
│   ├── database.py            # SQLAlchemy 설정
│   ├── user_database.py       # 사용자 데이터 작업
│   └── redis_database.py      # Redis 작업
│
├── handlers/                   # 거래소 핸들러
│   ├── okx.py                 # OKX 거래소
│   ├── upbit.py               # 업비트 거래소
│   └── common.py              # 공통 핸들러 로직
│
├── jobs/                       # 작업 관리
│   ├── celery_app.py          # Celery 설정 (사용 중단)
│   └── worker_manager.py      # 멀티프로세싱 워커 라이프사이클
│
├── routes/                     # API 라우트
│   ├── trading_route.py       # 트레이딩 엔드포인트
│   ├── exchange_route.py      # 거래소 작업
│   ├── bot_state_route.py     # 봇 상태 관리
│   └── ...
│
├── services/                   # 비즈니스 서비스
│   ├── trading_service.py     # 트레이딩 오케스트레이션
│   ├── okx_service.py         # OKX 특화 로직
│   ├── upbit_service.py       # 업비트 특화 로직
│   ├── binance_service.py     # 바이낸스 특화 로직
│   └── user_service.py        # 사용자 관리
│
├── strategies/                 # 트레이딩 전략
│   ├── grid_process.py        # 그리드 프로세스 관리
│   └── trading_strategy.py    # 전략 구현
│
├── trading/                    # 트레이딩 실행
│   ├── instance.py            # 트레이딩 인스턴스
│   ├── instance_manager.py    # 인스턴스 라이프사이클
│   └── get_okx_positions.py   # 포지션 조회
│
├── repositories/               # 데이터 접근
│   ├── user_repository.py     # 사용자 데이터
│   └── trading_log_repository.py
│
├── utils/                      # 유틸리티
│   ├── precision.py           # 가격/수량 정밀도
│   ├── async_helpers.py       # 비동기 유틸리티
│   └── ...
│
├── dtos/                       # 데이터 전송 객체
│   ├── auth.py                # 인증 DTO
│   ├── trading.py             # 트레이딩 DTO
│   └── ...
│
├── websocket/                  # WebSocket 서버
│   ├── price_publisher.py     # 가격 브로드캐스팅
│   └── price_subscriber.py    # 가격 구독
│
├── infra/                      # 인프라
│   └── database.py            # 데이터베이스 초기화
│
├── monitoring/                 # 모니터링
│   └── order_monitor.py       # 주문 모니터링
│
└── main.py                     # 애플리케이션 진입점
```

#### 주요 컴포넌트

**1. 그리드 프로세스 관리** (`strategies/grid_process.py`)
- 다중 프로세스 그리드 실행
- Redis 기반 상태 관리
- 워커 라이프사이클 관리 (멀티프로세싱)
- 우아한 종료 처리

**2. 거래소 핸들러** (`handlers/`)
- 거래소별 API 래퍼 (공유 인프라 사용)
- 주문 배치 및 취소
- 잔고 조회
- 포지션 관리
- 시장 데이터 가져오기

**3. 트레이딩 서비스** (`services/`)
- 그리드 설정 및 구성
- 리밸런싱 로직
- 익절 관리
- 리스크 평가
- 공유 지갑 및 잔고 헬퍼 사용

**4. 인스턴스 관리** (`trading/instance_manager.py`)
- 트레이딩 인스턴스 라이프사이클
- 프로세스 모니터링
- 우아한 종료
- 복구 메커니즘

**5. 리포지토리 계층** (`repositories/`)
- 데이터베이스 추상화
- 사용자 데이터 영속성
- 트레이딩 로그 저장

#### 그리드 트레이딩 흐름

```
1. 사용자 설정 → 기능 시작 엔드포인트
                              ↓
2. 그리드 파라미터 검증
                              ↓
3. Redis에 요청 저장
                              ↓
4. 워커 프로세스 생성 (멀티프로세싱)
                              ↓
5. 그리드 레벨 초기화
                              ↓
6. 그리드 주문 배치 (거래소 API)
                              ↓
7. 가격 변동 모니터링 (WebSocket)
                              ↓
8. 그리드 크로싱 감지
                              ↓
9. 리밸런싱 실행
                              ↓
10. 포지션 업데이트 (데이터베이스)
                              ↓
11. 익절 조건 확인
                              ↓
12. 알림 전송 (텔레그램)
```

### Shared 모듈

두 전략 간 공유되는 공통 기능.

#### 디렉토리 구조

```
shared/
├── config/                     # 설정
│   ├── __init__.py
│   ├── settings.py            # 설정 관리
│   ├── constants.py           # 공유 상수
│   └── logging.py             # 로깅 설정
│
├── config.py                   # 공유 설정 (메인)
│
├── constants/                  # 상수 정의
│   ├── exchange.py            # 거래소 식별자
│   ├── error.py               # 에러 코드
│   ├── message.py             # 메시지 템플릿
│   └── redis_pattern.py       # Redis 키 패턴
│
├── database/                   # 데이터베이스 유틸리티
│   ├── session.py             # 비동기 세션 관리
│   ├── transactions.py        # 트랜잭션 지원
│   ├── redis.py               # Redis 클라이언트
│   ├── pool_monitor.py        # 연결 풀 모니터링
│   └── __init__.py
│
├── dtos/                       # 데이터 전송 객체
│   ├── auth.py                # 인증
│   ├── user.py                # 사용자 데이터
│   ├── trading.py             # 트레이딩 데이터
│   ├── exchange.py            # 거래소 데이터
│   └── bot_state.py           # 봇 상태
│
├── errors/                     # 에러 처리
│   ├── exceptions.py          # 구조화된 예외
│   ├── handlers.py            # 예외 핸들러
│   ├── middleware.py          # 요청 ID 추적
│   ├── categories.py          # 에러 카테고리 (레거시)
│   └── models.py              # 에러 모델 (레거시)
│
├── exchange/                   # 거래소 통합
│   ├── base.py                # 기본 거래소 인터페이스
│   ├── helpers/               # 거래소 헬퍼 유틸리티
│   │   ├── position_helper.py # 포지션 처리
│   │   ├── balance_helper.py  # 잔고 처리
│   │   ├── wallet_helper.py   # 지갑 처리
│   │   └── cache_helper.py    # 캐싱 유틸리티
│   └── okx/                   # OKX 특화 구현
│       ├── client.py          # OKX 클라이언트
│       ├── constants.py       # OKX 상수
│       ├── exceptions.py      # OKX 예외
│       └── websocket.py       # OKX WebSocket
│
├── exchange_apis/              # 거래소 API 래퍼
│   ├── exchange_store.py      # 거래소 팩토리
│   └── __init__.py
│
├── helpers/                    # 헬퍼 함수
│   ├── cache_helper.py        # 캐싱 유틸리티
│   └── __init__.py
│
├── indicators/                 # 기술 지표
│   ├── _core.py               # 핵심 함수
│   ├── _rsi.py                # RSI 계산
│   ├── _atr.py                # ATR 계산
│   ├── _bollinger.py          # 볼린저 밴드
│   ├── _moving_averages.py    # MA/EMA/JMA
│   ├── _trend.py              # 추세 분석
│   ├── _all_indicators.py     # 복합 계산
│   └── __init__.py
│
├── logging/                    # 로깅 인프라
│   ├── json_logger.py         # JSON 구조화 로깅
│   ├── specialized_loggers.py # 주문/알림/디버그 로거
│   └── __init__.py
│
├── models/                     # 데이터 모델
│   └── exchange.py            # 거래소 모델
│
├── notifications/              # 알림 서비스
│   ├── telegram.py            # 텔레그램 통합
│   └── __init__.py
│
├── utils/                      # 유틸리티 함수
│   ├── async_helpers.py       # 비동기 유틸리티 (재시도 로직)
│   ├── task_tracker.py        # 백그라운드 작업 추적
│   ├── path_config.py         # PYTHONPATH 설정
│   ├── redis_utils.py         # Redis 헬퍼
│   ├── trading_helpers.py     # 트레이딩 유틸리티
│   ├── symbol_helpers.py      # 심볼 변환
│   ├── type_converters.py     # 타입 변환
│   ├── time_helpers.py        # 시간 유틸리티
│   ├── file_helpers.py        # 파일 작업
│   ├── exchange_precision.py  # 거래소 정밀도 처리
│   └── __init__.py
│
├── validation/                 # 검증 유틸리티
│   ├── sanitizers.py          # 입력 정제
│   ├── trading_validators.py  # 트레이딩 검증
│   └── __init__.py
│
└── api/                        # 공유 API 유틸리티
    └── ...
```

#### 주요 컴포넌트

**1. 설정 관리** (`config.py`, `config/`)
- Pydantic Settings를 사용한 환경 기반 설정
- 데이터베이스 URL 구성 (PostgreSQL/SQLite)
- Redis 연결 관리
- `get_settings()`를 통한 중앙화된 설정 접근
- 다중 환경 지원

**2. 데이터베이스 인프라** (`database/`)
- **세션 관리**: 적절한 연결 풀링을 갖춘 비동기 세션
- **트랜잭션 지원**: 트랜잭션 컨텍스트 매니저
- **연결 풀링**: 환경별 풀 설정
- **풀 모니터링**: 실시간 연결 풀 메트릭
- **Redis 클라이언트**: 헬스 체크를 갖춘 비동기 Redis 작업

**3. 에러 처리** (`errors/`)
- **구조화된 예외**: 에러 코드를 갖춘 계층적 예외 클래스
- **예외 핸들러**: FastAPI 예외 핸들러
- **요청 ID 미들웨어**: 스택 전반의 요청 추적
- **에러 카테고리**: 심각도 기반 에러 분류
- **레거시 지원**: 기존 에러 시스템과의 하위 호환성

**4. 로깅 인프라** (`logging/`)
- **JSON 구조화 로깅**: 기계 판독 가능한 로그 형식
- **요청 컨텍스트 필터링**: 자동 요청 ID 주입
- **전문 로거**: 주문, 알림, 디버그 로거
- **사용자별 로깅**: 사용자별 로그 파일

**5. 거래소 통합** (`exchange/`, `exchange_apis/`)
- **통합 거래소 인터페이스**: 추상 기본 클래스
- **거래소 헬퍼**: 포지션, 잔고, 지갑, 캐시 헬퍼
- **OKX 클라이언트**: 완전한 OKX 구현
- **거래소 팩토리**: 다중 거래소 지원을 위한 ExchangeStore
- **WebSocket 관리**: 거래소별 WebSocket 클라이언트

**6. 기술 지표** (`indicators/`)
- 모듈화된 지표 구현
- RSI, ATR, 볼린저 밴드, 이동평균
- 추세 감지 알고리즘
- NumPy를 사용한 성능 최적화

**7. 유틸리티 함수** (`utils/`)
- **비동기 헬퍼**: 지수 백오프를 갖춘 재시도 로직
- **작업 추적기**: 백그라운드 작업 라이프사이클 관리
- **경로 설정**: 모노레포를 위한 자동 PYTHONPATH 설정
- **타입 변환기**: 안전한 타입 변환 유틸리티
- **심볼 정규화**: 거래소 심볼 표준화
- **트레이딩 계산**: 공통 트레이딩 수학 함수

**8. 검증 및 정제** (`validation/`)
- 보안을 위한 입력 정제
- 트레이딩 특화 검증기
- 심볼 검증
- 데이터 정제 유틸리티

---

## 데이터 흐름

### 실시간 시장 데이터 흐름

```
거래소 WebSocket
       ↓
[WebSocket 클라이언트]
       ↓
가격 업데이트 이벤트
       ↓
Redis Pub/Sub 채널
       ↓
┌──────────────┬──────────────┐
↓              ↓              ↓
전략 1        전략 2         UI 클라이언트
분석          분석         (WebSocket을 통해)
```

**구현**:
- 거래소 피드로의 WebSocket 연결
- 여러 소비자로의 팬아웃을 위한 Redis Pub/Sub
- 큐 제한을 갖춘 백프레셔 처리
- 지수 백오프를 갖춘 자동 재연결
- 우아한 종료를 위한 작업 추적

### 주문 실행 흐름

```
사용자 요청
    ↓
API 엔드포인트
    ↓
요청 검증 (Pydantic)
    ↓
서비스 계층
    ↓
리스크 관리 체크
    ↓
전략 신호 생성
    ↓
주문 준비
    ↓
┌────────────────────┐
│  거래소 핸들러      │
│  - 속도 제한       │
│  - 재시도 로직     │
│  - 에러 처리       │
└────────────────────┘
    ↓
거래소 API (ccxt)
    ↓
주문 확인
    ↓
┌──────────────────────────┐
│  실행 후 작업             │
│  - 데이터베이스 업데이트  │
│  - Redis 캐시 업데이트   │
│  - 알림 전송            │
│  - 포지션 업데이트       │
│  - P&L 계산            │
└──────────────────────────┘
```

### 백그라운드 작업 흐름

**HYPERRSI (Celery 기반)**:
```
예약된 이벤트 (Celery Beat)
         ↓
Celery 워커 풀
         ↓
작업 실행
         ↓
┌────────────────────┐
│  작업 카테고리      │
│  - 시장 분석       │
│  - 포지션 모니터   │
│  - 리스크 체크     │
│  - 데이터 수집     │
└────────────────────┘
         ↓
애플리케이션 상태 업데이트
         ↓
결과 저장 (Redis/데이터베이스)
         ↓
필요시 알림 트리거
```

**GRID (멀티프로세싱 기반)**:
```
API 요청 → 워커 매니저
                   ↓
         워커 프로세스 생성
                   ↓
         그리드 전략 초기화
                   ↓
         그리드 트레이딩 실행
                   ↓
         Redis 상태로 모니터링
                   ↓
         신호 시 우아한 종료
```

### 상태 관리 흐름

```
애플리케이션 상태
       ↓
┌──────────────────────────────┐
│  다층 상태 저장소             │
│                              │
│  1. Redis (핫 데이터)         │
│     - 활성 포지션            │
│     - 실시간 가격            │
│     - 사용자 세션            │
│     - 작업 상태              │
│     - 워커 상태 (GRID)       │
│                              │
│  2. PostgreSQL (웜 데이터)    │
│     - 사용자 계정            │
│     - 트레이딩 이력          │
│     - 설정                   │
│     - 감사 로그              │
│                              │
│  3. 로그 (콜드 데이터)        │
│     - 에러 로그              │
│     - 주문 로그 (JSON)       │
│     - 디버그 정보            │
│     - 알림 로그              │
└──────────────────────────────┘
```

**상태 일관성**:
- 캐시 어사이드 패턴으로서의 Redis
- 중요 데이터에 대한 라이트 스루
- 분석을 위한 최종 일관성
- 컨텍스트 매니저를 통한 트랜잭션 지원
- 연결 풀 모니터링

---

## 기술 스택

### 언어 및 런타임
- **Python 3.12**: 최신 성능 개선을 갖춘 현대적인 Python
- **AsyncIO**: 논블로킹 I/O를 위한 네이티브 async/await
- **타입 힌트**: 타입 안전성을 위한 종합적인 타입 주석

### 웹 프레임워크
- **FastAPI 0.115.6**: 현대적인 비동기 웹 프레임워크
  - 자동 OpenAPI 문서화
  - 검증을 위한 Pydantic V2 통합
  - WebSocket 지원
  - 의존성 주입 시스템
  - Lifespan 컨텍스트 매니저
- **Uvicorn 0.34.0**: 고성능 ASGI 서버
- **Starlette**: 기본 ASGI 프레임워크

### 데이터베이스 계층
- **SQLAlchemy 2.0.37**: 비동기 지원을 갖춘 ORM
  - 선언적 모델
  - 비동기 세션
  - 모니터링을 갖춘 연결 풀링
  - 트랜잭션 관리
- **PostgreSQL**: 프로덕션 데이터베이스 (asyncpg 0.30.0 사용)
- **SQLite**: 개발 데이터베이스
- **Redis 5.2.1**: 캐싱 및 메시지 브로커
  - 실시간 이벤트를 위한 Pub/Sub
  - 세션 저장
  - 작업 큐 백엔드 (Celery)
  - 워커 상태 관리 (GRID)

### 작업 큐 및 백그라운드 처리
- **Celery 5.4.0**: 분산 작업 큐 (HYPERRSI)
  - 브로커 및 결과 백엔드로서의 Redis
  - Celery Beat를 사용한 예약 작업
  - Flower를 사용한 작업 모니터링
- **Multiprocessing**: 네이티브 Python 멀티프로세싱 (GRID)
  - 플랫폼별 시작 메서드 (spawn/fork)
  - 신호 기반 우아한 종료
  - 워커 라이프사이클 관리

### 거래소 통합
- **ccxt 4.4.50**: 통합 암호화폐 거래소 API
  - 100개 이상의 거래소 지원
  - 표준화된 API 인터페이스
  - 비동기 지원
- **WebSockets 13.1**: WebSocket 클라이언트 라이브러리
- **aiohttp 3.10.11**: 비동기 HTTP 클라이언트

### 데이터 처리
- **pandas 2.2.3**: 데이터 조작 및 분석
- **numpy 2.2.2**: 수치 계산
- **scipy 1.15.1**: 과학 계산

### 검증 및 설정
- **Pydantic 2.10.5**: Python 타입 힌트를 사용한 데이터 검증
- **pydantic-settings 2.7.1**: 환경에서의 설정 관리
- **python-dotenv 1.0.1**: 환경 변수 로딩

### 알림
- **python-telegram-bot 21.10**: 텔레그램 봇 API 래퍼
  - 비동기 지원
  - 웹훅 및 폴링 모드
  - 풍부한 키보드 지원

### 로깅 및 모니터링
- **구조화된 JSON 로깅**: 기계 판독 가능한 로그를 위한 커스텀 JSON 포맷터
- **요청 컨텍스트 추적**: 분산 추적을 위한 요청 ID 미들웨어
- **연결 풀 모니터링**: 실시간 풀 메트릭 및 누수 감지
- **작업 추적**: 백그라운드 작업 라이프사이클 관리

### 개발 도구
- **mypy**: 정적 타입 체킹 (GRID에 설정됨)
- **pytest**: 테스팅 프레임워크 (확장 예정)
- **black**: 코드 포맷팅 (추가 예정)
- **ruff**: 빠른 린팅 (추가 예정)

---

## 설계 결정

### 1. 모노레포 vs 마이크로서비스

**결정**: 공유 인프라와 마이크로서비스 추출 가능성을 갖춘 모노레포

**근거**:
- 공유 코드가 중복 감소 (~40% 감소 달성)
- 더 쉬운 개발 및 테스팅
- 간소화된 의존성 관리
- 명확한 모듈 경계로 향후 분리 가능
- 중앙화된 설정 및 유틸리티

**트레이드오프**:
- ✅ 더 빠른 개발 반복
- ✅ 일관된 버전 관리
- ✅ 더 쉬운 리팩토링
- ✅ 공통 기능을 위한 단일 진실 공급원
- ⚠️ 더 큰 코드베이스
- ⚠️ 경계 유지를 위한 규율 필요

### 2. Async/Await 아키텍처

**결정**: AsyncIO를 사용한 비동기 우선 접근

**근거**:
- 더 나은 리소스 활용을 위한 논블로킹 I/O
- FastAPI 및 현대 라이브러리의 네이티브 지원
- WebSocket 및 동시 API 호출에 필수적
- I/O 바운드 작업에 대해 잘 확장됨
- 우아한 종료를 위한 적절한 작업 추적

**트레이드오프**:
- ✅ 높은 동시성
- ✅ I/O 작업에 대한 더 나은 성능
- ✅ 작업 취소를 갖춘 우아한 종료
- ⚠️ 더 복잡한 에러 처리
- ⚠️ 디버깅이 어려울 수 있음
- ✅ 지수 백오프를 갖춘 재시도 로직 구현됨

### 3. 백그라운드 처리: Celery vs 멀티프로세싱

**결정**: HYPERRSI는 Celery, GRID는 멀티프로세싱

**HYPERRSI (Celery)**:
- 성숙하고 검증된 솔루션
- 풍부한 기능 세트 (스케줄링, 재시도, 모니터링)
- 좋은 모니터링 도구 (Flower)
- 수평 확장
- 포크 안전성을 갖춘 macOS 호환성

**GRID (멀티프로세싱)**:
- 플랫폼별 최적화 (macOS/Windows용 spawn, Linux용 fork)
- 직접 워커 관리
- 더 간단한 배포
- 신호 기반 우아한 종료

**트레이드오프**:
- ✅ 작업에 적합한 기술 선택
- ✅ 각 전략의 필요에 최적화됨
- ⚠️ 관리할 다른 운영 패턴

### 4. 검증을 위한 Pydantic

**결정**: 모든 데이터 검증을 위한 Pydantic V2 모델

**근거**:
- 타입 안전한 데이터 구조
- 자동 검증
- JSON 직렬화/역직렬화
- 훌륭한 IDE 지원
- FastAPI 통합
- pydantic-settings를 사용한 설정 관리

**트레이드오프**:
- ✅ 유효하지 않은 데이터 방지
- ✅ 자체 문서화 코드
- ✅ 자동 API 문서화
- ✅ 환경 변수 검증
- ⚠️ 대용량 데이터셋에 대한 성능 오버헤드
- ⚠️ 복잡한 스키마에 대한 학습 곡선

### 5. 중앙화된 설정 관리

**결정**: 환경 기반 설정을 갖춘 통합 공유 설정

**구현**:
```python
# shared/config.py
class Settings(BaseSettings):
    # 데이터베이스 설정
    DATABASE_URL: str  # 프로퍼티 기반 구성
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10

    # Redis 설정
    REDIS_URL: str

    # 환경
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

@lru_cache()
def get_settings():
    return Settings()
```

**장점**:
- ✅ 단일 진실 공급원
- ✅ 타입 안전한 설정
- ✅ 환경별 설정
- ✅ 하드코딩된 자격 증명 없음
- ✅ 프로퍼티 기반 URL 구성

### 6. 프로덕션용 PostgreSQL, 개발용 SQLite

**결정**: 환경별 다른 데이터베이스

**근거**:
- SQLite가 로컬 개발을 간소화 (서버 불필요)
- PostgreSQL이 프로덕션급 기능 제공
- SQLAlchemy가 차이를 추상화
- 환경별 최적화된 연결 풀링

**구현**:
- 테스트/개발용 NullPool (SQLite)
- 프로덕션용 QueuePool (PostgreSQL)
- 풀 모니터링 및 누수 감지
- 연결 헬스 체크를 위한 프리핑

**트레이드오프**:
- ✅ 쉬운 로컬 설정
- ✅ 프로덕션 준비 확장성
- ✅ 연결 풀 최적화
- ⚠️ 프로덕션 전에 PostgreSQL에서 테스트 필요

### 7. 구조화된 에러 처리

**결정**: 표준화된 핸들러를 갖춘 계층적 예외 시스템

**구현**:
```python
# 구조화된 예외
class TradingException(Exception):
    def __init__(self, code: ErrorCode, message: str, details: dict = None)

# 예외 핸들러
@app.exception_handler(TradingException)
async def trading_exception_handler(request, exc):
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
                "request_id": request.state.request_id
            }
        }
    )
```

**장점**:
- ✅ 일관된 에러 응답
- ✅ 요청 ID 추적
- ✅ 구조화된 에러 코드
- ✅ 상세한 에러 컨텍스트
- ✅ 레거시 시스템과의 하위 호환성

### 8. 중앙화된 거래소 인프라

**결정**: 공유 거래소 핸들러 및 헬퍼

**구현**:
```python
# shared/exchange/helpers/
- position_helper.py  # 포지션 처리
- balance_helper.py   # 잔고 처리
- wallet_helper.py    # 지갑 처리
- cache_helper.py     # 캐싱 유틸리티

# shared/exchange/okx/
- client.py           # OKX 클라이언트
- websocket.py        # OKX WebSocket
- constants.py        # OKX 상수
- exceptions.py       # OKX 예외
```

**장점**:
- ✅ ~40% 코드 감소
- ✅ 일관된 에러 처리
- ✅ 통합 캐싱 전략
- ✅ 새로운 거래소 추가 용이
- ✅ 더 나은 유지보수성

### 9. PYTHONPATH 자동 설정

**결정**: 진입점에서의 자동 PYTHONPATH 설정

**구현**:
```python
# shared/utils/path_config.py
@lru_cache(maxsize=1)
def configure_pythonpath() -> Path:
    """프로젝트 루트 자동 감지 및 설정"""
    # 프로젝트 루트를 찾기 위해 디렉토리 트리를 올라감
    # 존재하지 않으면 sys.path에 추가
    return project_root

# main.py에서 사용
from shared.utils.path_config import configure_pythonpath
configure_pythonpath()
```

**장점**:
- ✅ 수동 PYTHONPATH 설정 불필요
- ✅ 모든 진입점에서 작동
- ✅ 모노레포 친화적
- ✅ 일관된 임포트 패턴

### 10. 우아한 종료를 위한 작업 추적

**결정**: 적절한 취소를 갖춘 중앙화된 작업 추적

**구현**:
```python
# shared/utils/task_tracker.py
class TaskTracker:
    async def create_task(self, coro, name=None):
        """백그라운드 작업 생성 및 추적"""

    async def cancel_all(self, timeout=10.0):
        """타임아웃을 갖춘 모든 추적 작업 취소"""

# 사용법
task_tracker = TaskTracker(name="hyperrsi-main")
task_tracker.create_task(background_job(), name="data-collector")

# 종료
await task_tracker.cancel_all(timeout=10.0)
```

**장점**:
- ✅ 우아한 종료
- ✅ 고아 작업 없음
- ✅ 적절한 리소스 정리
- ✅ 작업 라이프사이클 가시성

---

## 개선 권장사항

### 우선순위 1: 테스팅 및 품질 보증

#### 1.1 종합적인 테스팅 추가

**현재 상태**: 제한적인 테스트 커버리지

**권장사항**:
```python
# tests/conftest.py
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from httpx import AsyncClient

@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("postgresql+asyncpg://test:test@localhost/test")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine) as session:
        yield session

    await engine.dispose()

@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    from HYPERRSI.main import app
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

# tests/services/test_trading_service.py
@pytest.mark.asyncio
async def test_execute_order_success(db_session):
    service = TradingService(exchange, user_id=1, db=db_session)
    order = await service.execute_order(
        symbol="BTC/USDT",
        side="buy",
        amount=0.1
    )
    assert order.status == "filled"
```

**실행 항목**:
- 비동기 지원을 갖춘 pytest 설정
- 데이터베이스 및 API 클라이언트용 테스트 픽스처 생성
- 서비스 및 유틸리티용 단위 테스트 추가
- API 엔드포인트용 통합 테스트 추가
- 테스트 커버리지 보고 구현 (목표: 80%+)
- 자동화된 테스팅을 위한 CI/CD 파이프라인 설정

### 우선순위 2: 성능 최적화

#### 2.1 캐싱 전략 구현

**현재 상태**: 기본 캐싱, 체계적인 전략 없음

**권장사항**:
```python
# shared/cache/decorator.py
from functools import wraps
from typing import Callable, Any
import json
import hashlib

def cache_result(ttl: int = 300, key_prefix: str = ""):
    """Redis에 함수 결과 캐싱"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            # 캐시 키 생성
            cache_key = f"{key_prefix}:{func.__module__}:{func.__name__}:"
            cache_key += hashlib.md5(
                json.dumps([args, kwargs], sort_keys=True).encode()
            ).hexdigest()

            # 캐시 시도
            redis = await get_redis()
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

# 사용법
@cache_result(ttl=60, key_prefix="market_data")
async def get_ticker(symbol: str) -> dict:
    return await exchange.fetch_ticker(symbol)
```

**실행 항목**:
- 비용이 많이 드는 작업용 캐시 데코레이터 구현
- 자주 접근하는 데이터용 캐시 워밍 추가
- 캐시 무효화 전략 구현
- 캐시 적중률 모니터링

#### 2.2 데이터베이스 쿼리 최적화

**현재 상태**: 기본 쿼리 최적화

**권장사항**:
```python
# N+1 쿼리를 방지하기 위해 이거 로딩 사용
from sqlalchemy.orm import selectinload, joinedload

async def get_user_with_orders(user_id: int) -> User:
    query = (
        select(User)
        .options(
            selectinload(User.orders),
            joinedload(User.settings)
        )
        .where(User.id == user_id)
    )
    result = await session.execute(query)
    return result.scalar_one()

# 복합 인덱스 추가
class Order(Base):
    __tablename__ = "orders"

    __table_args__ = (
        Index('idx_user_symbol_status', 'user_id', 'symbol', 'status'),
        Index('idx_created_at', 'created_at'),
    )
```

**실행 항목**:
- 데이터베이스 프로파일링으로 느린 쿼리 분석
- 적절한 인덱스 추가
- 관련 엔티티에 이거 로딩 사용
- 쿼리 결과 페이지네이션 구현
- 쿼리 성능 모니터링

#### 2.3 속도 제한 추가

**현재 상태**: 체계적인 속도 제한 없음

**권장사항**:
```python
# shared/middleware/rate_limit.py
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

# 라우트에서
@router.post("/trading/order")
@limiter.limit("5/minute")
async def create_order(request: Request, ...):
    ...

# 거래소 속도 제한
class RateLimiter:
    def __init__(self, max_calls: int, period: timedelta):
        self.max_calls = max_calls
        self.period = period
        self.calls: list[datetime] = []
        self.semaphore = Semaphore(max_calls)

    async def acquire(self):
        async with self.semaphore:
            now = datetime.now()
            self.calls = [
                call for call in self.calls
                if now - call < self.period
            ]

            if len(self.calls) >= self.max_calls:
                sleep_time = (self.calls[0] + self.period - now).total_seconds()
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

            self.calls.append(now)
```

**실행 항목**:
- 사용자/IP별 API 속도 제한 추가
- 거래소별 속도 제한 구현
- 응답에 속도 제한 헤더 추가
- 속도 제한 위반 모니터링

### 우선순위 3: 모니터링 및 관찰성

#### 3.1 메트릭 수집 추가

**현재 상태**: 기본 로깅, 메트릭 없음

**권장사항**:
```python
# shared/metrics/collector.py
from prometheus_client import Counter, Histogram, Gauge

# 메트릭 정의
order_counter = Counter(
    'orders_total',
    '총 주문 수',
    ['exchange', 'symbol', 'side', 'status']
)

order_duration = Histogram(
    'order_duration_seconds',
    '주문 실행 시간',
    ['exchange', 'symbol']
)

active_positions = Gauge(
    'active_positions',
    '활성 포지션 수',
    ['exchange', 'strategy']
)

# 사용법
async def place_order(exchange, symbol, side, amount):
    start_time = time.time()
    try:
        order = await exchange.create_order(symbol, side, amount)
        order_counter.labels(
            exchange=exchange.name,
            symbol=symbol,
            side=side,
            status='success'
        ).inc()
        return order
    except Exception as e:
        order_counter.labels(
            exchange=exchange.name,
            symbol=symbol,
            side=side,
            status='failed'
        ).inc()
        raise
    finally:
        duration = time.time() - start_time
        order_duration.labels(
            exchange=exchange.name,
            symbol=symbol
        ).observe(duration)
```

**실행 항목**:
- 메트릭 수집을 위한 Prometheus 설정
- 비즈니스 메트릭 추가 (주문, 포지션, P&L)
- 시스템 메트릭 추가 (응답 시간, 에러율)
- Grafana 대시보드 생성
- 중요 메트릭에 대한 알림 설정

#### 3.2 향상된 헬스 체크

**현재 상태**: 기본 헬스 엔드포인트

**권장사항**:
```python
# shared/health/checks.py
class HealthCheck:
    async def check_database(self) -> dict[str, Any]:
        try:
            async with get_db() as db:
                await db.execute(text("SELECT 1"))
            return {"status": "healthy", "latency_ms": 0}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    async def check_redis(self) -> dict[str, Any]:
        try:
            redis = await get_redis()
            start = time.time()
            await redis.ping()
            latency = (time.time() - start) * 1000
            return {"status": "healthy", "latency_ms": latency}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

# 엔드포인트
@router.get("/health/detailed")
async def health_check():
    checker = HealthCheck()
    results = {
        "timestamp": datetime.utcnow().isoformat(),
        "status": "healthy",
        "checks": {
            "database": await checker.check_database(),
            "redis": await checker.check_redis(),
        }
    }

    if any(check["status"] == "unhealthy" for check in results["checks"].values()):
        results["status"] = "unhealthy"

    return results
```

**실행 항목**:
- 모든 의존성에 대한 상세 헬스 체크 구현
- 준비성 및 활성성 프로브 추가
- 헬스 체크 엔드포인트 모니터링
- 헬스 체크 실패에 대한 알림 설정

### 우선순위 4: 보안 강화

#### 4.1 API 인증 구현

**현재 상태**: 기본 인증

**권장사항**:
```python
# shared/auth/jwt.py
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=30)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401)
    except JWTError:
        raise HTTPException(status_code=401)

    user = await get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=401)
    return user
```

**실행 항목**:
- JWT 기반 인증 구현
- 외부 서비스용 API 키 인증 추가
- 역할 기반 접근 제어(RBAC) 구현
- API 키 로테이션 추가
- 써드파티 통합을 위한 OAuth2 구현

#### 4.2 향상된 입력 정제

**현재 상태**: Pydantic을 사용한 기본 검증

**권장사항**:
```python
# 기존 shared/validation/sanitizers.py 활용
from shared.validation.sanitizers import (
    sanitize_symbol,
    sanitize_log_data,
    sanitize_sql_input,
)

# 라우트에서 사용
@router.post("/order")
async def create_order(symbol: str, ...):
    symbol = sanitize_symbol(symbol)  # 잠재적으로 해로운 문자 제거
    # 주문 처리...
```

**실행 항목**:
- 공유 모듈에서 정제 함수 확장
- SQL 인젝션 방지 추가
- XSS 보호 구현
- 웹 엔드포인트용 CSRF 보호 추가
- 로깅 전에 모든 사용자 입력 정제

### 우선순위 5: 문서화 및 개발자 경험

#### 5.1 API 문서화 강화

**현재 상태**: 기본 OpenAPI 문서화

**권장사항**:
- 상세한 엔드포인트 설명 추가
- 요청/응답 예시 포함
- 에러 응답 문서화
- 인증 흐름 추가
- API 사용 가이드 생성
- SDK 문서 생성

#### 5.2 아키텍처 문서화

**현재 상태**: 양호한 문서화 (본 파일)

**권장사항**:
- 변경 사항에 맞춰 ARCHITECTURE.md 최신 상태 유지
- 복잡한 흐름에 대한 시퀀스 다이어그램 추가
- 디자인 패턴 및 근거 문서화
- 신규 개발자를 위한 온보딩 가이드 생성
- 배포 절차 문서화

### 개선 우선순위 요약

| 우선순위 | 카테고리 | 노력 | 영향 | 일정 |
|----------|----------|--------|--------|----------|
| P1 | 테스팅 스위트 | 높음 | 높음 | 2-4주차 |
| P1 | CI/CD 파이프라인 | 중간 | 높음 | 1-2주차 |
| P2 | 캐싱 전략 | 중간 | 높음 | 2-3주차 |
| P2 | 쿼리 최적화 | 중간 | 중간 | 2-3주차 |
| P2 | 속도 제한 | 낮음 | 높음 | 1주차 |
| P3 | 메트릭 수집 | 중간 | 높음 | 2-3주차 |
| P3 | 헬스 체크 | 낮음 | 중간 | 1주차 |
| P3 | 모니터링 대시보드 | 중간 | 높음 | 3-4주차 |
| P4 | API 인증 | 중간 | 높음 | 2주차 |
| P4 | 보안 강화 | 중간 | 높음 | 2-3주차 |
| P5 | 문서화 | 낮음 | 중간 | 지속적 |

---

## 결론

TradingBoost-Strategy 플랫폼은 현대적인 Python 기술과 명확한 아키텍처 패턴을 갖춘 견고하고 프로덕션 준비된 기반을 보여줍니다. 공유 인프라를 갖춘 모노레포 구조는 전략 독립성을 유지하면서 코드 중복을 ~40% 성공적으로 감소시켰습니다. 비동기 우선 접근 방식과 적절한 백그라운드 처리(HYPERRSI용 Celery, GRID용 멀티프로세싱)를 결합하여 암호화폐 거래 작업을 위한 확장 가능한 기반을 제공합니다.

### 주요 강점

**아키텍처 및 설계**:
- ✅ 명확한 관심사 분리를 갖춘 깔끔한 계층형 아키텍처
- ✅ 코드 중복을 줄이는 중앙화된 공유 인프라
- ✅ 코드베이스 전반의 현대적인 async/await 패턴
- ✅ 적절한 의존성 주입 및 라이프사이클 관리

**인프라 및 안정성**:
- ✅ 연결 풀링 및 모니터링을 갖춘 프로덕션 준비 데이터베이스 계층
- ✅ 요청 추적을 갖춘 구조화된 에러 처리
- ✅ 관찰성을 위한 JSON 구조화 로깅
- ✅ 작업 추적을 갖춘 우아한 종료
- ✅ 모노레포를 위한 자동 PYTHONPATH 설정

**통합 및 거래소 지원**:
- ✅ 통합 인터페이스를 통한 다중 거래소 지원
- ✅ 일관성을 위한 공유 거래소 헬퍼
- ✅ WebSocket을 사용한 실시간 기능
- ✅ 지수 백오프를 갖춘 재시도 로직

**코드 품질**:
- ✅ 더 나은 IDE 지원 및 타입 안전성을 위한 타입 힌트
- ✅ 단일 책임 원칙을 갖춘 모듈식 설계
- ✅ Pydantic V2를 사용한 종합적인 검증
- ✅ 환경 기반 설정을 갖춘 설정 관리

### 개선이 필요한 영역

**테스팅 및 품질 보증** (우선순위 1):
- 종합적인 테스트 스위트 추가 (단위, 통합, E2E)
- 테스트 커버리지 보고 구현 (목표: 80%+)
- 자동화된 테스팅을 위한 CI/CD 파이프라인 설정

**성능 및 확장성** (우선순위 2):
- 체계적인 캐싱 전략 구현
- 적절한 인덱싱으로 데이터베이스 쿼리 최적화
- API 및 거래소 속도 제한 추가

**모니터링 및 관찰성** (우선순위 3):
- 메트릭 수집 추가 (Prometheus)
- 모니터링 대시보드 생성 (Grafana)
- 모든 의존성에 대한 헬스 체크 강화
- 중요 메트릭에 대한 알림 설정

**보안** (우선순위 4):
- API 인증 강화 (JWT, API 키)
- 접근 제어를 위한 RBAC 구현
- 입력 정제 및 검증 강화

**문서화** (우선순위 5):
- 아키텍처 문서 유지
- API 사용 가이드 추가
- 개발자 온보딩 자료 생성

권장된 개선 사항을 구현하면 플랫폼의 안정성, 유지보수성 및 확장성이 크게 향상되어 진지한 트레이딩 작업을 위한 프로덕션 준비 상태가 확고해질 것입니다.

---

**문서 버전**: 2.0
**마지막 업데이트**: 2025-10-08
**관리자**: 아키텍처 팀

**최근 아키텍처 변경사항**:
- 공유 인프라 계층으로 마이그레이션 (에러 처리, 로깅, 데이터베이스)
- 요청 추적을 갖춘 구조화된 예외 시스템 구현
- 연결 풀 모니터링 및 헬스 체크 추가
- Pydantic Settings를 사용한 중앙화된 설정 관리
- 코드 중복을 ~40% 감소시킨 공유 거래소 헬퍼 생성
- 모노레포를 위한 자동 PYTHONPATH 설정 구현
- 우아한 종료를 위한 작업 추적 추가
- HYPERRSI 주문 라우트를 도메인별 서비스로 모듈화
