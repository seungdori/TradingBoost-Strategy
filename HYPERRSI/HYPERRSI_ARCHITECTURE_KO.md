# HYPERRSI 트레이딩 전략 - 아키텍처 문서

## 목차
1. [프로젝트 개요](#프로젝트-개요)
2. [기술 스택](#기술-스택)
3. [디렉토리 구조](#디렉토리-구조)
4. [아키텍처 레이어](#아키텍처-레이어)
5. [비동기 패턴 및 설계](#비동기-패턴-및-설계)
6. [데이터 흐름](#데이터-흐름)
7. [핵심 컴포넌트](#핵심-컴포넌트)
8. [통합 패턴](#통합-패턴)
9. [모범 사례](#모범-사례)
10. [개선 가능한 부분](#개선-가능한-부분)

---

## 프로젝트 개요

HYPERRSI는 RSI(Relative Strength Index) 지표와 추세 분석을 결합하여 여러 암호화폐 거래소에서 자동 거래를 실행하는 시스템입니다. FastAPI, Celery, Redis, WebSocket 기반 실시간 데이터 수집을 사용하는 최신 비동기 Python 아키텍처로 구축되었습니다.

**주요 기능:**
- CCXT를 통한 다중 거래소 지원 (OKX, Binance, Bitget, Upbit, Bybit)
- WebSocket 피드를 통한 실시간 시장 데이터 수집
- TP/SL 관리를 포함한 자동 거래 실행
- 포지션 모니터링 및 리스크 관리
- 사용자 상호작용을 위한 텔레그램 봇 통합
- 격리된 거래 컨텍스트를 가진 다중 사용자 지원
- 포괄적인 로깅 및 에러 처리

**배포:**
- 포트 8000에서 FastAPI 서버
- 백그라운드 작업 처리를 위한 Celery 워커
- 캐싱, 세션 관리, Celery 브로커/백엔드를 위한 Redis
- 영구 데이터 저장을 위한 PostgreSQL
- 실시간 가격 피드를 위한 WebSocket 연결

---

## 기술 스택

### 핵심 프레임워크
- **Python 3.9+**: 타입 힌트를 사용하는 최신 async/await 패턴
- **FastAPI 0.115.6**: API 엔드포인트를 위한 비동기 웹 프레임워크
- **Celery 5.4.0**: 백그라운드 작업을 위한 분산 태스크 큐
- **Redis 5.2.1**: 캐싱 및 메시지 브로커를 위한 인메모리 데이터 스토어
- **SQLAlchemy 2.0.37**: PostgreSQL/SQLite 지원을 포함한 비동기 ORM
- **CCXT 4.4.50**: 통합 거래소 API 라이브러리

### 비동기 인프라
- **aiohttp 3.10.11**: 비동기 HTTP 클라이언트
- **asyncpg 0.30.0**: 고성능 비동기 PostgreSQL 드라이버
- **redis.asyncio**: 비동기 Redis 클라이언트

### 트레이딩 및 데이터
- **pandas 2.2.3**: 데이터 조작 및 지표 계산
- **numpy 2.2.2**: 수치 계산
- **aiogram 3.17.0**: 비동기 텔레그램 봇 프레임워크

### 모니터링 및 관찰성
- **prometheus_client 0.21.1**: 메트릭 수집
- **구조화된 로깅**: 컨텍스트를 포함한 JSON 형식 로그

### 의존성 관리
```python
# 주요 의존성
fastapi==0.115.6
celery==5.4.0
redis==5.2.1
ccxt==4.4.50
SQLAlchemy==2.0.37
aiogram==3.17.0
pandas==2.2.3
pydantic==2.10.5
```

---

## 디렉토리 구조

```
HYPERRSI/
├── main.py                          # FastAPI 애플리케이션 진입점
├── src/
│   ├── __init__.py
│   │
│   ├── api/                         # API 레이어
│   │   ├── dependencies.py          # FastAPI 의존성 (거래소 풀, API 키)
│   │   ├── middleware.py            # 요청 미들웨어 (CORS, 로깅)
│   │   ├── routes/                  # API 엔드포인트
│   │   │   ├── trading.py          # 거래 작업 (시작/중지)
│   │   │   ├── order.py            # 주문 관리
│   │   │   ├── position.py         # 포지션 조회
│   │   │   ├── account.py          # 계정 정보
│   │   │   ├── settings.py         # 사용자 설정
│   │   │   ├── stats.py            # 거래 통계
│   │   │   ├── status.py           # 시스템 상태
│   │   │   ├── telegram.py         # 텔레그램 통합
│   │   │   ├── user.py             # 사용자 관리
│   │   │   └── okx.py              # OKX 전용 엔드포인트
│   │   ├── exchange/               # 거래소 통합
│   │   │   ├── base.py             # 추상 거래소 인터페이스
│   │   │   └── okx/                # OKX 구현
│   │   │       ├── client.py       # OKX REST API 클라이언트
│   │   │       ├── websocket.py    # OKX WebSocket 클라이언트
│   │   │       └── exceptions.py   # OKX 전용 에러
│   │   └── trading/                # 거래 API 유틸리티
│   │
│   ├── core/                        # 핵심 인프라
│   │   ├── celery_task.py          # Celery 앱 설정
│   │   ├── config.py               # 설정 관리 (pydantic)
│   │   ├── database.py             # 데이터베이스 엔진, Redis 클라이언트
│   │   ├── logger.py               # 구조화된 로깅 설정
│   │   ├── error_handler.py        # 전역 에러 처리
│   │   ├── shutdown.py             # 우아한 종료 핸들러
│   │   ├── models/                 # 데이터 모델
│   │   │   ├── user.py             # 사용자 모델
│   │   │   ├── bot_state.py        # 봇 상태 모델
│   │   │   └── trading_data.py     # 거래 데이터 모델
│   │   └── database_dir/           # 데이터베이스 마이그레이션
│   │       └── migrations/
│   │
│   ├── services/                    # 비즈니스 로직 레이어
│   │   ├── redis_service.py        # Redis 작업 (설정, API 키)
│   │   ├── timescale_service.py    # TimescaleDB 작업
│   │   └── websocket_service.py    # WebSocket 연결 관리
│   │
│   ├── trading/                     # 거래 실행 레이어
│   │   ├── trading_service.py      # Facade 패턴 - 메인 거래 서비스
│   │   ├── execute_trading_logic.py # 핵심 거래 로직 실행
│   │   ├── dual_side_entry.py      # 양방향 포지션 관리
│   │   ├── position_manager.py     # 포지션 라이프사이클 관리
│   │   ├── stats.py                # 거래 통계 추적
│   │   ├── models.py               # 거래 모델 (Position, Order)
│   │   ├── modules/                # 모듈화된 거래 컴포넌트
│   │   │   ├── market_data_service.py      # 시장 데이터 가져오기
│   │   │   ├── tp_sl_calculator.py         # TP/SL 계산
│   │   │   ├── okx_position_fetcher.py     # 포지션 가져오기
│   │   │   ├── order_manager.py            # 주문 실행
│   │   │   ├── tp_sl_order_creator.py      # TP/SL 주문 생성
│   │   │   ├── position_manager.py         # 포지션 작업
│   │   │   └── trading_utils.py            # 유틸리티 함수
│   │   ├── services/               # 거래 유틸리티
│   │   │   ├── get_current_price.py # 가격 가져오기
│   │   │   ├── order_utils.py      # 주문 유틸리티
│   │   │   ├── position_utils.py   # 포지션 유틸리티
│   │   │   └── calc_utils.py       # 계산 유틸리티
│   │   ├── monitoring/             # 포지션 모니터링
│   │   │   ├── core.py             # 모니터링 핵심 로직
│   │   │   ├── order_monitor.py    # 주문 상태 모니터링
│   │   │   ├── position_validator.py # 포지션 검증
│   │   │   ├── break_even_handler.py # 손익분기 로직
│   │   │   ├── trailing_stop_handler.py # 트레일링 스톱
│   │   │   ├── redis_manager.py    # Redis 작업
│   │   │   ├── telegram_service.py # 알림
│   │   │   └── utils.py            # 유틸리티
│   │   └── utils/                  # 거래 헬퍼
│   │       ├── trading_utils.py    # 거래 유틸리티
│   │       └── position_handler.py # 포지션 핸들러
│   │
│   ├── tasks/                       # Celery 태스크
│   │   ├── trading_tasks.py        # 거래 실행 태스크
│   │   ├── grid_trading_tasks.py   # 그리드 거래 태스크
│   │   └── websocket_tasks.py      # WebSocket 관리 태스크
│   │
│   ├── data_collector/              # 시장 데이터 수집
│   │   ├── integrated_data_collector.py # 메인 데이터 수집기
│   │   ├── data_collector_v2.py    # 데이터 수집 로직
│   │   ├── websocket.py            # WebSocket 데이터 피드
│   │   ├── indicators.py           # 기술 지표
│   │   └── tasks.py                # 데이터 수집 Celery 태스크
│   │
│   ├── bot/                         # 텔레그램 봇 통합
│   │   ├── handlers.py             # 봇 설정 및 라우팅
│   │   ├── command/                # 명령 핸들러
│   │   │   ├── basic.py            # 기본 명령 (/start, /help)
│   │   │   ├── trading.py          # 거래 명령
│   │   │   ├── settings.py         # 설정 관리
│   │   │   ├── account.py          # 계정 작업
│   │   │   └── register.py         # 사용자 등록
│   │   ├── keyboards/              # 인라인 키보드
│   │   ├── states/                 # FSM 상태
│   │   └── utils/                  # 봇 유틸리티
│   │
│   └── utils/                       # 공유 유틸리티
│       ├── redis_model.py          # Redis 데이터 모델
│       ├── indicators.py           # 기술 지표
│       ├── status_utils.py         # 상태 유틸리티
│       └── uid_manager.py          # UID 관리
│
├── configs/                         # 설정
│   └── exchange_configs.py         # 거래소별 설정
│
├── scripts/                         # 유틸리티 스크립트
│   └── update_okx_uid_for_existing_users.py
│
├── start_celery_worker.sh          # 워커 시작 스크립트
├── stop_celery_worker.sh           # 워커 중지 스크립트
└── requirements.txt                # Python 의존성
```

---

## 아키텍처 레이어

### 1. API 레이어 (FastAPI)
**위치:** `src/api/`

**목적:** 클라이언트 상호작용을 위한 HTTP 인터페이스

**핵심 컴포넌트:**
- **라우트 핸들러:** 도메인별로 구성된 엔드포인트 (trading, order, position 등)
- **의존성:** 거래소 클라이언트, 인증, 세션 관리를 위한 의존성 주입
- **미들웨어:** CORS, 요청 로깅, 에러 처리, 요청 ID 추적
- **거래소 추상화:** 다중 거래소를 위한 통합 인터페이스

**디자인 패턴:**
- 리소스 관리를 위한 의존성 주입
- 데이터 접근을 위한 리포지토리 패턴
- 거래소 클라이언트 생성을 위한 팩토리 패턴
- 거래소 클라이언트를 위한 커넥션 풀링

**예시 - 거래 라우트:**
```python
@router.post("/start")
async def start_trading(request: TradingTaskRequest, restart: bool = False):
    # 1. 사용자 검증 및 OKX UID 추출
    # 2. Redis 연결 확인
    # 3. 사용자 설정 및 API 키 가져오기
    # 4. Celery 태스크 큐에 추가
    # 5. 태스크 ID 반환
```

### 2. 서비스 레이어
**위치:** `src/services/`

**목적:** 비즈니스 로직 추상화

**핵심 서비스:**
- **RedisService:** 사용자 설정, API 키, 로컬 + Redis 2단계 캐시를 사용한 캐싱
- **TimescaleService:** 거래 이력을 위한 시계열 데이터 작업
- **WebSocketService:** WebSocket 연결 라이프사이클 관리

**디자인 패턴:**
- 서비스 인스턴스를 위한 싱글톤 패턴
- 복원력을 위한 재시도 데코레이터
- 2단계 캐싱 (로컬 메모리 + Redis)
- Prometheus 메트릭 통합

### 3. 거래 실행 레이어
**위치:** `src/trading/`

**목적:** 핵심 거래 로직 및 주문 실행

**아키텍처:**
```
TradingService (Facade)
    ├── MarketDataService          # 가격 가져오기, 시장 정보
    ├── TPSLCalculator             # TP/SL 가격 계산
    ├── OKXPositionFetcher         # 포지션 조회
    ├── OrderManager               # 주문 배치/취소
    ├── TPSLOrderCreator           # TP/SL 주문 생성
    └── PositionManager            # 포지션 라이프사이클
```

**주요 책임:**
- **TradingService:** 모든 거래 작업을 조정하는 Facade
- **모듈 클래스:** SRP를 따르는 전문화된 책임
- **포지션 관리:** 포지션 열기, 닫기, 업데이트
- **주문 관리:** 시장가, 지정가, TP/SL 주문
- **리스크 관리:** 포지션 크기 조정, 레버리지 검증

**디자인 패턴:**
- Facade 패턴 (TradingService)
- 관심사 분리를 위한 모듈 패턴
- 리소스 정리를 위한 컨텍스트 매니저
- 포지션 안전성을 위한 비동기 락

### 4. 데이터 수집 레이어
**위치:** `src/data_collector/`

**목적:** 실시간 및 과거 시장 데이터

**컴포넌트:**
- **IntegratedDataCollector:** 폴링 기반 OHLCV 데이터 수집
- **WebSocket 수집기:** 실시간 틱 데이터
- **지표 계산:** 공유 모듈을 사용한 RSI, MA, 추세 지표

**데이터 흐름:**
1. 거래소에서 OHLCV 가져오기 (REST 또는 WebSocket)
2. symbol:timeframe 키로 Redis에 저장
3. 지표 계산 (RSI, 이동평균)
4. 계산된 지표 캐시
5. 새로운 캔들 완료 시 거래 로직 트리거

### 5. 태스크 큐 레이어 (Celery)
**위치:** `src/tasks/`

**목적:** 비동기 백그라운드 처리

**태스크 유형:**
- **trading_tasks:** 거래 실행 (`check_and_execute_trading`)
- **grid_trading_tasks:** 그리드 전략 실행
- **websocket_tasks:** WebSocket 연결 관리

**설정:**
```python
celery_app = Celery(
    "trading_bot",
    broker=REDIS_URL,      # DB 1
    backend=REDIS_URL,     # DB 1
    include=['src.tasks.trading_tasks', 'src.tasks.grid_trading_tasks']
)
```

**기능:**
- 워커당 이벤트 루프 관리
- 정리를 포함한 우아한 종료
- 타임아웃 관리를 위한 시그널 핸들러
- macOS fork 안전성 (OBJC_DISABLE_INITIALIZE_FORK_SAFETY)

### 6. 핵심 인프라
**위치:** `src/core/`

**컴포넌트:**
- **데이터베이스 엔진:** SQLAlchemy 비동기 엔진 (싱글톤)
- **Redis 클라이언트:** 커넥션 풀링을 사용하는 이중 클라이언트 (텍스트/바이너리)
- **Celery 앱:** 태스크 큐 설정
- **로거:** 구조화된 JSON 로깅
- **에러 핸들러:** 사용자 컨텍스트를 포함한 전역 예외 처리
- **설정:** Pydantic 기반 설정 관리

---

## 비동기 패턴 및 설계

### 1. FastAPI 라이프스팬 관리

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """인프라 초기화를 포함한 애플리케이션 라이프스팬"""
    try:
        # 시작
        handle_signals()
        await init_new_db()         # 새 인프라 DB
        await init_new_redis()      # 새 인프라 Redis
        await init_db()             # 레거시 DB
        await init_redis()          # 레거시 Redis
        await init_global_redis_clients()  # 전역 클라이언트 캐시

        yield
    finally:
        # 종료
        await close_db()
        await close_redis()
```

**패턴의 이점:**
- 중앙 집중식 시작/종료 로직
- 적절한 리소스 정리
- 에러 발생 시 우아한 성능 저하
- 시그널 핸들러 통합

### 2. 거래소 클라이언트 커넥션 풀링

```python
class ExchangeConnectionPool:
    """
    거래소 클라이언트를 위한 커넥션 풀:
    - 사용자당 최대 풀 크기
    - 클라이언트 수명 만료 (기본 3600초)
    - 헬스 체크
    - 자동 재연결
    """

    async def get_client(self, user_id: str) -> ccxt.okx:
        # 1. 풀에서 사용 가능한 클라이언트 확인
        # 2. 클라이언트 헬스 검증
        # 3. 필요시 새로 생성
        # 4. 사용 중인 클라이언트 추적
        # 5. 컨텍스트 매니저로 반환
```

**컨텍스트 매니저 사용:**
```python
async with get_exchange_context(user_id) as client:
    # 종료 시 클라이언트 자동으로 풀에 반환
    positions = await client.fetch_positions()
```

### 3. Redis 2단계 캐싱

```python
class RedisService:
    async def get(self, key: str) -> Optional[Any]:
        # 1. 로컬 메모리 캐시 확인 (TTL 포함)
        if key in self._local_cache and time.time() < self._cache_ttl[key]:
            return self._local_cache[key]

        # 2. Redis로 폴백
        data = await redis_client.get(key)

        # 3. 로컬 캐시 업데이트
        self._local_cache[key] = data
        return data
```

**이점:**
- 서브 밀리초 캐시 히트 (로컬 메모리)
- Redis 부하 감소
- 자동 TTL 관리

### 4. 포지션 안전성을 위한 비동기 락 패턴

```python
class TradingService:
    @contextlib.asynccontextmanager
    async def position_lock(self, user_id: str, symbol: str):
        """동시 포지션 수정 방지"""
        lock_key = f"position:{user_id}:{symbol}"

        if lock_key not in self._locks:
            self._locks[lock_key] = asyncio.Lock()

        lock = self._locks[lock_key]

        try:
            await lock.acquire()
            yield
        finally:
            lock.release()
```

**사용:**
```python
async with self.position_lock(user_id, symbol):
    # 포지션 수정 안전
    await self.open_position(...)
```

### 5. Celery 이벤트 루프 관리

```python
def init_worker():
    """전용 이벤트 루프로 워커 초기화"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
```

**시그널 처리:**
```python
def signal_handler(signum, frame):
    """타임아웃/종료 시 태스크 취소"""
    if _current_task and not _current_task.done():
        _loop.call_soon_threadsafe(_current_task.cancel)
    cancel_all_child_tasks()
```

### 6. 컨텍스트 매니저를 사용한 태스크 추적

```python
@asynccontextmanager
async def trading_context(okx_uid: str, symbol: str):
    """거래 작업을 위한 리소스 관리"""
    task = asyncio.current_task()
    local_resources = []

    try:
        yield
    except asyncio.CancelledError:
        logger.warning(f"Trading context cancelled: {symbol}")
        raise
    finally:
        # 리소스 정리
        await redis_client.delete(REDIS_KEY_TASK_RUNNING.format(okx_uid=okx_uid))
```

### 7. Prometheus 메트릭 통합

```python
class Cache:
    cache_hits = Counter('cache_hits_total', 'Cache hit count')
    cache_misses = Counter('cache_misses_total', 'Cache miss count')
    cache_operation_duration = Histogram('cache_operation_seconds', 'Duration')

    async def get(self, key: str):
        with self.cache_operation_duration.time():
            # 작업 로직
            if found:
                self.cache_hits.inc()
            else:
                self.cache_misses.inc()
```

---

## 데이터 흐름

### 1. 거래 실행 흐름

```
사용자 요청 (HTTP)
    ↓
FastAPI 라우트 핸들러 (/api/trading/start)
    ↓
사용자 및 설정 검증 (Redis)
    ↓
Celery 태스크 큐에 추가 (trading_tasks.check_and_execute_trading)
    ↓
Celery 워커가 태스크 수행
    ↓
거래 로직 실행
    ├── 시장 데이터 가져오기 (CCXT)
    ├── 지표 계산 (RSI, MA)
    ├── 거래 시그널 생성
    ├── 기존 포지션 확인 (Redis/거래소)
    ├── 리스크 파라미터 검증
    └── 주문 실행 (시그널 있을 경우)
        ↓
    TradingService.open_position()
        ├── 포지션 크기 계산
        ├── 마진 검증
        ├── 시장가 주문 배치
        ├── TP/SL 주문 생성
        ├── Redis에 포지션 저장
        └── 텔레그램 알림 전송
```

### 2. 시장 데이터 수집 흐름

```
Celery Beat 스케줄러 (5초 간격)
    ↓
데이터 수집기 태스크
    ↓
각 (심볼, 타임프레임)에 대해:
    ├── 최신 캔들 가져오기 (CCXT/WebSocket)
    ├── 새 캔들 마감 확인
    ├── 지표 계산
    │   ├── RSI (14, 21, 28)
    │   ├── 이동평균 (9, 21, 50, 100, 200)
    │   ├── 추세 상태
    │   └── 거래량 분석
    ├── Redis에 저장
    │   ├── 키: "candles:{symbol}:{timeframe}"
    │   ├── 값: OHLCV + 지표의 JSON 배열
    │   └── TTL: 타임프레임 기반
    └── 거래 로직 트리거 (활성화된 경우)
```

### 3. 주문 라이프사이클 흐름

```
주문 배치
    ↓
Redis에 주문 저장 ("order:{order_id}")
    ↓
주문 모니터링 태스크 시작 (Celery)
    ↓
주문 상태 폴링 (30초 간격)
    ├── 체결 상태 확인
    ├── 체결 시 포지션 업데이트
    ├── 부분 체결 처리
    └── 실패 시 재시도
        ↓
주문 체결
    ├── Redis에서 포지션 업데이트
    ├── 거래 이력 기록
    ├── 텔레그램 알림 전송
    └── 주문 캐시 정리
```

### 4. 포지션 모니터링 흐름

```
활성 포지션 감지
    ↓
모니터링 태스크 시작 (Celery)
    ↓
30-60초마다:
    ├── 현재 포지션 가져오기 (거래소 API)
    ├── 미실현 손익 확인
    ├── TP/SL 주문 존재 확인
    ├── 손익분기 조건 확인
    ├── 트레일링 스톱 조건 확인
    └── Redis에서 포지션 업데이트
        ↓
포지션 청산
    ├── 거래 이력에 청산 기록
    ├── 최종 손익 계산
    ├── 요약 알림 전송
    └── 포지션 캐시 정리
```

### 5. WebSocket 데이터 흐름

```
WebSocket 연결 수립
    ↓
채널 구독 (trades, candles)
    ↓
실시간 틱 데이터 수신
    ↓
각 틱에 대해:
    ├── Redis에서 현재 가격 업데이트
    ├── 캔들로 집계 (필요시)
    ├── 거래 로직 트리거 (캔들 마감 시)
    └── UI 업데이트 (Server-Sent Events를 통해)
        ↓
연결 끊김
    ├── 자동 재연결 (지수 백오프)
    ├── 채널 재구독
    └── 데이터 흐름 재개
```

---

## 핵심 컴포넌트

### 1. TradingService (Facade 패턴)

**파일:** `src/trading/trading_service.py`

**책임:**
- 모든 거래 작업 조정
- 전문화된 모듈에 위임
- 사용자별 거래소 클라이언트 관리
- 거래 로직을 위한 통합 인터페이스 제공

**모듈 아키텍처:**
```python
class TradingService:
    # 초기화된 모듈
    market_data: MarketDataService
    tp_sl_calc: TPSLCalculator
    okx_fetcher: OKXPositionFetcher
    order_manager: OrderManager
    tp_sl_creator: TPSLOrderCreator
    position_mgr: PositionManager

    @classmethod
    async def create_for_user(cls, user_id: str):
        """사용자별 인스턴스를 위한 팩토리 메서드"""
        instance = cls(user_id)

        async with get_exchange_context(user_id) as client:
            instance.client = client
            # 모든 모듈 초기화
            instance.market_data = MarketDataService(instance)
            instance.tp_sl_calc = TPSLCalculator(instance)
            # ...

        return instance
```

**주요 메서드:**
- `open_position()`: TP/SL을 포함한 새 포지션 열기
- `close_position()`: 기존 포지션 닫기
- `update_stop_loss()`: 스톱로스 주문 수정
- `get_current_position()`: 포지션 데이터 가져오기

### 2. 거래소 커넥션 풀

**파일:** `src/api/dependencies.py`

**기능:**
- 사용자당 커넥션 풀링
- 자동 정리를 포함한 헬스 체크
- 클라이언트 수명 만료 (기본 1시간)
- 지수 백오프를 사용한 재시도 로직

```python
class ExchangeConnectionPool:
    def __init__(self, max_size=10, max_age=3600):
        self.pools = {}  # user_id -> {'clients': [], 'in_use': set()}
        self._client_metadata = {}  # 생성 시간 추적

    async def get_client(self, user_id: str) -> ccxt.okx:
        # 1. 오래된 클라이언트 제거
        # 2. 사용 가능한 클라이언트 찾기
        # 3. 풀이 가득 차지 않으면 새로 생성
        # 4. 풀이 가득 찬 경우 대기 및 재시도

    async def release_client(self, user_id: str, client):
        # 클라이언트를 사용 가능으로 표시
```

### 3. 2단계 캐싱을 사용하는 Redis 서비스

**파일:** `src/services/redis_service.py`

**캐싱 전략:**
- **L1 캐시:** TTL을 포함한 인메모리 딕셔너리 (30-300초)
- **L2 캐시:** 더 긴 TTL을 가진 Redis (3600초+)

**주요 작업:**
- `get_user_settings()`: 기본값 폴백으로 가져오기
- `set_user_settings()`: 두 캐시 레벨 모두 업데이트
- `get_multiple_user_settings()`: 파이프라인을 사용한 배치 작업

**메트릭:**
- 캐시 히트/미스 카운터
- 작업 지속 시간 히스토그램

### 4. Celery 태스크 관리

**파일:** `src/core/celery_task.py`

**설정:**
```python
celery_app = Celery(
    "trading_bot",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=['src.tasks.trading_tasks', 'src.tasks.grid_trading_tasks']
)

celery_app.conf.update(
    timezone="Asia/Seoul",
    worker_prefetch_multiplier=1,  # 태스크 독점 방지
    result_expires=3600,
    task_serializer='json',
    accept_content=['json'],
)
```

**워커 초기화:**
- 이벤트 루프 설정
- 시그널 핸들러 (SIGINT, SIGTERM, SIGALRM)
- macOS를 위한 fork 안전성 설정

### 5. 데이터 수집기

**파일:** `src/data_collector/integrated_data_collector.py`

**기능:**
- 다중 심볼, 다중 타임프레임 수집
- 폴링 간격 최적화 (캔들 마감에 맞춤)
- API 에러 시 지수 백오프
- 지표 계산 통합

**폴링 전략:**
```python
def calculate_update_interval(timeframe_minutes: int) -> int:
    """
    최적 폴링 간격 계산:
    - 1m: 30s
    - 3m: 60s
    - 5m: 90s
    - 15m+: 120s
    """
```

### 6. 텔레그램 봇 통합

**파일:** `src/bot/handlers.py`

**아키텍처:**
- **라우터 기반 명령 처리**
- **다단계 워크플로우를 위한 FSM (Finite State Machine)**
- **대화형 UI를 위한 인라인 키보드**

**명령 모듈:**
- `basic.py`: /start, /help, /status
- `trading.py`: /trade_start, /trade_stop
- `settings.py`: 파라미터 설정
- `account.py`: API 키 관리
- `register.py`: 사용자 온보딩

---

## 통합 패턴

### 1. 공유 모듈 통합

**패턴:** 공유 인프라에서 절대 임포트

```python
# HYPERRSI가 shared/에서 임포트
from shared.config import get_settings
from shared.logging import get_logger
from shared.utils import retry_decorator, round_to_tick_size
from shared.database import RedisConnectionManager
from shared.errors import DatabaseException, ValidationException
```

**이점:**
- HYPERRSI와 GRID 전략 간 코드 재사용
- 중앙 집중식 설정 관리
- 일관된 에러 처리
- 통일된 로깅 형식

### 2. PYTHONPATH 자동 설정

**파일:** 모든 진입점 (main.py, celery_task.py 등)

```python
# 모노레포 구조를 위한 PYTHONPATH 자동 설정
from shared.utils.path_config import configure_pythonpath
configure_pythonpath()
```

**효과:** 수동 PYTHONPATH 설정 없이 절대 임포트 가능

### 3. 레거시와 새 인프라 공존

**패턴:** 점진적 마이그레이션 전략

```python
# 새 인프라 (shared/)
from shared.database.session import init_db as init_new_db, close_db
from shared.database.redis import init_redis as init_new_redis, close_redis
from shared.logging import setup_json_logger

# 레거시 인프라 (HYPERRSI.src.core)
from HYPERRSI.src.core.database import init_db, init_global_redis_clients
from HYPERRSI.src.services.redis_service import init_redis
```

**마이그레이션 전략:**
1. 새 코드는 공유 모듈 사용
2. 레거시 코드는 점진적으로 리팩토링
3. 전환 기간 동안 두 시스템 병행 운영
4. 하위 호환성 유지

### 4. 동적 Redis 클라이언트 접근

**패턴:** 임포트 시간 초기화 에러 방지

```python
# 모듈 레벨 지연 초기화
def _get_redis_client():
    """임포트 시간 에러를 피하기 위해 redis_client를 동적으로 가져오기"""
    from HYPERRSI.src.core import database as db_module
    return db_module.redis_client

# 모듈 레벨 속성을 위한 __getattr__를 통한 접근
def __getattr__(name):
    if name == 'redis_client':
        return _database_module.redis_client
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
```

**이점:**
- 순환 의존성 방지
- 적절한 초기화 순서
- 우아한 에러 메시지

---

## 모범 사례

### 1. 비동기 리소스 관리

**패턴:** 모든 리소스에 대한 컨텍스트 매니저

```python
# 데이터베이스 세션
async with get_async_session() as session:
    # 작업
    await session.commit()

# 거래소 클라이언트
async with get_exchange_context(user_id) as client:
    # API 호출

# 포지션 락
async with self.position_lock(user_id, symbol):
    # 포지션 수정
```

### 2. 에러 처리 계층 구조

**레벨:**
1. **요청 레벨:** FastAPI 예외 핸들러
2. **서비스 레벨:** 컨텍스트 로깅을 포함한 Try/except
3. **태스크 레벨:** Celery 재시도 데코레이터
4. **전역 레벨:** 처리되지 않은 예외 로거

**예시:**
```python
@router.post("/endpoint")
async def endpoint(request: Request):
    try:
        result = await service.operation()
        return {"status": "success", "data": result}
    except ValidationException as e:
        logger.warning("Validation failed", extra={"error": str(e)})
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Operation failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error")
```

### 3. 구조화된 로깅

**패턴:** 컨텍스트를 포함한 JSON 로그

```python
logger.info(
    "Order placed successfully",
    extra={
        "user_id": user_id,
        "symbol": symbol,
        "order_id": order_id,
        "side": side,
        "quantity": quantity,
        "price": price
    }
)
```

**이점:**
- 쉬운 로그 집계
- 쿼리 가능한 로그 데이터
- 컨텍스트 보존
- 요청 전반에 걸친 사용자 추적

### 4. 타입 힌트 및 Pydantic 모델

**패턴:** 완전한 타입 커버리지

```python
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

class TradingTaskRequest(BaseModel):
    user_id: str
    symbol: Optional[str] = "SOL-USDT-SWAP"
    timeframe: str = "1m"

async def start_trading(request: TradingTaskRequest) -> Dict[str, Any]:
    # 타입 안전 작업
```

### 5. 복원력을 위한 재시도 데코레이터

**패턴:** 최대 재시도 횟수를 가진 지수 백오프

```python
@retry_decorator(max_retries=3, delay=4.0, backoff=2.0)
async def fetch_user_settings(user_id: str) -> Optional[Dict]:
    # 일시적으로 실패할 수 있는 작업
```

**재시도 스케줄:**
- 시도 1: 즉시
- 시도 2: 4초 지연
- 시도 3: 8초 지연
- 시도 4: 16초 지연

### 6. 서비스를 위한 싱글톤 패턴

**패턴:** 중복 인스턴스 방지

```python
class RedisService:
    _instance = None
    _lock = Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance
```

### 7. 우아한 종료를 위한 시그널 핸들러

**패턴:** SIGINT/SIGTERM 시 정리

```python
async def shutdown(signal_name: str):
    global _is_shutting_down
    if _is_shutting_down:
        return

    _is_shutting_down = True

    # 태스크 취소
    await task_tracker.cancel_all(timeout=10.0)

    # 연결 닫기
    await close_db()
    await close_redis()

    # 이벤트 루프 중지
    loop.stop()
```

---

## 개선 가능한 부분

### 1. 최신 Python 3.12+ 기능

**현재:** Python 3.9+ 호환성
**개선:** Python 3.12+ 기능 활용

**기회:**
- **PEP 695 타입 파라미터 구문:**
  ```python
  # 현재
  T = TypeVar('T')
  def get_position[T](user_id: str) -> Optional[T]:

  # Python 3.12+
  def get_position[T](user_id: str) -> Optional[T]:
  ```

- **PEP 692 TypedDict Unpack:**
  ```python
  class UserSettings(TypedDict):
      leverage: int
      direction: str

  def configure(**settings: Unpack[UserSettings]):
      # 타입 안전 kwargs
  ```

- **개선된 asyncio.TaskGroup:**
  ```python
  async with asyncio.TaskGroup() as tg:
      task1 = tg.create_task(fetch_position())
      task2 = tg.create_task(fetch_orders())
      # 에러 시 자동 취소
  ```

### 2. Redis 최적화

**현재:** 2단계 전략을 사용한 기본 캐싱
**개선:** 고급 Redis 패턴

**기회:**
- **이벤트 소싱을 위한 Redis Streams:**
  ```python
  # 포지션 상태 변경을 스트림으로
  await redis.xadd(
      f"position_events:{user_id}",
      {"event": "opened", "symbol": symbol, "size": size}
  )
  ```

- **실시간 업데이트를 위한 Redis Pub/Sub:**
  ```python
  # 연결된 모든 클라이언트에 포지션 업데이트 브로드캐스트
  await redis.publish(f"user:{user_id}:positions", json.dumps(position))
  ```

- **원자적 작업을 위한 Redis 트랜잭션:**
  ```python
  async with redis.pipeline(transaction=True) as pipe:
      await pipe.watch(position_key)
      # 포지션을 원자적으로 수정
      await pipe.multi()
      await pipe.set(position_key, new_data)
      await pipe.execute()
  ```

### 3. Celery 태스크 최적화

**현재:** 폴링을 사용한 기본 태스크 큐
**개선:** 고급 Celery 패턴

**기회:**
- **복잡한 워크플로우를 위한 태스크 체인:**
  ```python
  from celery import chain

  workflow = chain(
      fetch_market_data.s(symbol),
      calculate_signal.s(),
      execute_order.s(user_id)
  )
  workflow.apply_async()
  ```

- **병렬 처리를 위한 태스크 그룹:**
  ```python
  from celery import group

  tasks = group(
      check_position.s(user_id, symbol)
      for symbol in user_symbols
  )
  results = tasks.apply_async()
  ```

- **우선순위 큐:**
  ```python
  # 중요한 작업에 높은 우선순위
  celery_app.conf.task_routes = {
      'tasks.close_position': {'queue': 'high_priority'},
      'tasks.fetch_data': {'queue': 'low_priority'},
  }
  ```

### 4. PostgreSQL + TimescaleDB로 데이터베이스 마이그레이션

**현재:** 개발을 위한 SQLite, 혼합 사용
**개선:** 시계열을 위한 TimescaleDB를 포함한 완전한 PostgreSQL

**이점:**
- 더 나은 동시 액세스
- 고급 인덱싱
- OHLCV 데이터를 위한 시계열 최적화
- 지표 계산을 위한 연속 집계

**예시:**
```sql
-- 캔들 데이터를 위한 하이퍼테이블 생성
CREATE TABLE candles (
    time TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC,
    volume NUMERIC
);

SELECT create_hypertable('candles', 'time');

-- 시간별 데이터를 위한 연속 집계
CREATE MATERIALIZED VIEW candles_hourly
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 hour', time) AS bucket,
       symbol,
       FIRST(open, time) as open,
       MAX(high) as high,
       MIN(low) as low,
       LAST(close, time) as close,
       SUM(volume) as volume
FROM candles
GROUP BY bucket, symbol;
```

### 5. WebSocket 개선

**현재:** 일부 WebSocket 사용을 포함한 폴링 기반
**개선:** 재연결을 포함한 완전한 WebSocket 통합

**기회:**
- **중앙 집중식 WebSocket 관리자:**
  ```python
  class WebSocketManager:
      async def subscribe(self, user_id: str, channels: List[str]):
          """실시간 업데이트 구독"""

      async def broadcast(self, event: str, data: dict):
          """연결된 모든 클라이언트에 브로드캐스트"""
  ```

- **UI 업데이트를 위한 Server-Sent Events (SSE):**
  ```python
  @router.get("/stream/positions")
  async def stream_positions(user_id: str):
      async def event_generator():
          while True:
              position = await get_position(user_id)
              yield f"data: {json.dumps(position)}\n\n"
              await asyncio.sleep(1)

      return EventSourceResponse(event_generator())
  ```

### 6. 테스팅 인프라

**현재:** 수동 테스트 스크립트
**개선:** 포괄적인 테스트 스위트

**기회:**
- **비동기 지원을 포함한 Pytest:**
  ```python
  @pytest.mark.asyncio
  async def test_open_position():
      service = await TradingService.create_for_user("test_user")

      with patch('ccxt.okx.create_order') as mock_order:
          mock_order.return_value = {'id': '12345'}

          result = await service.open_position(
              user_id="test_user",
              symbol="BTC-USDT-SWAP",
              direction="long",
              size=100
          )

          assert result['status'] == 'success'
  ```

- **Docker Compose를 사용한 통합 테스트:**
  ```yaml
  # docker-compose.test.yml
  services:
    redis:
      image: redis:7-alpine
    postgres:
      image: timescale/timescaledb:latest-pg15
    test:
      build: .
      depends_on:
        - redis
        - postgres
      command: pytest tests/
  ```

### 7. 관찰성 향상

**현재:** 기본 Prometheus 메트릭
**개선:** 완전한 관찰성 스택

**기회:**
- **OpenTelemetry 통합:**
  ```python
  from opentelemetry import trace
  from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

  tracer = trace.get_tracer(__name__)

  @router.post("/trading/start")
  async def start_trading():
      with tracer.start_as_current_span("start_trading"):
          # 작업 자동 추적
  ```

- **구조화된 에러 추적 (Sentry):**
  ```python
  import sentry_sdk
  from sentry_sdk.integrations.fastapi import FastAPIIntegration

  sentry_sdk.init(
      dsn=settings.SENTRY_DSN,
      integrations=[FastAPIIntegration()],
      traces_sample_rate=0.1,
  )
  ```

- **로그 집계 (ELK/Grafana Loki):**
  - 중앙 집중식 로그 저장
  - 고급 쿼리
  - 실시간 알림

### 8. API 개선

**현재:** 기본 REST API
**개선:** 최신 API 패턴

**기회:**
- **유연한 쿼리를 위한 GraphQL:**
  ```python
  import strawberry
  from strawberry.fastapi import GraphQLRouter

  @strawberry.type
  class Position:
      symbol: str
      size: float
      pnl: float

  @strawberry.type
  class Query:
      @strawberry.field
      async def positions(self, user_id: str) -> List[Position]:
          return await fetch_positions(user_id)
  ```

- **API 버전 관리:**
  ```python
  app.include_router(trading_v1.router, prefix="/api/v1")
  app.include_router(trading_v2.router, prefix="/api/v2")
  ```

- **Rate Limiting:**
  ```python
  from slowapi import Limiter
  from slowapi.util import get_remote_address

  limiter = Limiter(key_func=get_remote_address)
  app.state.limiter = limiter

  @router.get("/", dependencies=[Depends(RateLimiter(times=10, seconds=60))])
  ```

### 9. 성능 최적화

**현재:** 적절한 성능
**개선:** 고급 최적화

**기회:**
- **커넥션 풀 튜닝:**
  ```python
  # 부하에 따라 풀 크기 최적화
  ExchangeConnectionPool(
      max_size=20,  # 높은 동시성을 위해 증가
      max_age=1800,  # 빈번한 API 변경을 위해 감소
  )
  ```

- **배치 작업:**
  ```python
  # 한 번의 호출로 여러 포지션 가져오기
  async def get_all_positions(user_ids: List[str]):
      async with asyncio.TaskGroup() as tg:
          tasks = [
              tg.create_task(fetch_position(uid))
              for uid in user_ids
          ]
      return [task.result() for task in tasks]
  ```

- **캐싱 전략 개선:**
  ```python
  # 데이터 변동성에 따라 다른 TTL
  CACHE_TTL = {
      'user_settings': 300,      # 5분
      'api_keys': 3600,          # 1시간
      'market_info': 86400,      # 24시간
      'current_price': 5,        # 5초
  }
  ```

### 10. 보안 강화

**현재:** 기본 인증
**개선:** 엔터프라이즈급 보안

**기회:**
- **API 키 암호화:**
  ```python
  from cryptography.fernet import Fernet

  class SecureKeyStorage:
      def __init__(self, encryption_key: bytes):
          self.cipher = Fernet(encryption_key)

      async def store_api_key(self, user_id: str, api_key: str):
          encrypted = self.cipher.encrypt(api_key.encode())
          await redis.hset(f"user:{user_id}:keys", "api_key", encrypted)
  ```

- **JWT를 사용한 OAuth2:**
  ```python
  from fastapi.security import OAuth2PasswordBearer
  from jose import jwt

  oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

  async def get_current_user(token: str = Depends(oauth2_scheme)):
      payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
      return payload.get("sub")
  ```

- **요청 서명:**
  ```python
  # 요청 무결성 확인
  def verify_signature(request: Request, signature: str):
      payload = await request.body()
      expected = hmac.new(SECRET_KEY, payload, hashlib.sha256).hexdigest()
      return hmac.compare_digest(expected, signature)
  ```

---

## 결론

HYPERRSI는 최신 Python 패턴을 사용하여 잘 설계된 비동기 거래 시스템을 보여줍니다:

**강점:**
- 계층화된 아키텍처로 관심사의 명확한 분리
- 강력한 비동기 패턴 (라이프스팬 관리, 커넥션 풀링, 컨텍스트 매니저)
- 포괄적인 에러 처리 및 로깅
- Celery를 사용한 확장 가능한 태스크 큐 통합
- 사용자별 리소스를 사용한 다중 사용자 격리
- 실시간 데이터 수집 및 처리
- SRP를 따르는 모듈화된 거래 컴포넌트

**개선 영역:**
- 고급 타입 기능을 위한 Python 3.12+로 마이그레이션
- pytest를 사용한 향상된 테스팅 인프라
- 추적 및 메트릭을 포함한 완전한 관찰성
- 고급 Redis 패턴 (streams, pub/sub)
- TimescaleDB를 사용한 데이터베이스 최적화
- 보안 강화 (암호화, OAuth2)

이 아키텍처는 미래의 개선 및 확장 요구 사항에 대한 유연성을 유지하면서 암호화폐 거래 자동화를 위한 견고한 기반을 제공합니다.
