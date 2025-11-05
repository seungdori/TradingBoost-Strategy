# FastAPI Prometheus 통합 가이드

HYPERRSI 및 GRID FastAPI 애플리케이션에 Prometheus 메트릭을 통합하는 가이드입니다.

## 개요

이 가이드는 FastAPI 애플리케이션에서 `/metrics` 엔드포인트를 노출하여 Prometheus 수집을 활성화하는 방법을 설명합니다.

## 설치

HYPERRSI 및 GRID 애플리케이션 모두 `prometheus-client` 패키지가 필요합니다:

```bash
pip install prometheus-client
```

## 기본 통합

### 1단계: FastAPI에 메트릭 엔드포인트 추가

`main.py` 또는 애플리케이션 진입점을 편집합니다:

```python
from fastapi import FastAPI
from prometheus_client import make_asgi_app

app = FastAPI(
    title="HYPERRSI Trading Strategy",
    version="1.0.0"
)

# 기존 라우트
app.include_router(trading_router, prefix="/api/trading", tags=["trading"])
app.include_router(health_router, prefix="/health", tags=["health"])

# Prometheus 메트릭 엔드포인트 추가
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
```

### 2단계: 메트릭 엔드포인트 확인

애플리케이션을 시작하고 엔드포인트를 확인합니다:

```bash
curl http://localhost:8000/metrics
```

예상 출력:
```
# HELP python_gc_objects_collected_total Objects collected during gc
# TYPE python_gc_objects_collected_total counter
python_gc_objects_collected_total{generation="0"} 1234.0
...
# HELP redis_pool_utilization_percent Redis pool utilization as a percentage (0-100)
# TYPE redis_pool_utilization_percent gauge
redis_pool_utilization_percent 15.5
```

## Redis 메트릭 통합

### RedisPoolMonitor를 통한 자동 메트릭

`RedisPoolMonitor` 클래스는 호출 시 자동으로 Prometheus 메트릭을 업데이트합니다:

```python
from shared.database.redis import RedisConnectionPool

# 모니터 인스턴스 가져오기
monitor = RedisConnectionPool.get_monitor()

# 다음 Prometheus 메트릭을 자동으로 업데이트합니다:
# - redis_pool_max_connections
# - redis_pool_active_connections
# - redis_pool_utilization_percent
pool_stats = monitor.get_pool_stats()

# 다음을 업데이트합니다:
# - redis_connection_latency_ms
# - redis_operation_duration_seconds
# - redis_operation_errors_total
health = await monitor.health_check()
```

### 헬스 엔드포인트를 통한 통합

`shared/api/health.py`를 사용하는 경우, 헬스 엔드포인트가 호출될 때 메트릭이 자동으로 업데이트됩니다:

```python
from shared.api.health import router as health_router

app.include_router(health_router, prefix="/health", tags=["health"])
```

다음 엔드포인트가 메트릭을 업데이트합니다:
- `GET /health/redis` - 모든 Redis 메트릭 업데이트
- `GET /health/redis/pool/stats` - 풀 메트릭 업데이트

**권장사항**: 메트릭을 최신 상태로 유지하기 위해 cron 작업 또는 백그라운드 태스크를 설정하여 헬스 엔드포인트를 주기적으로 호출하세요:

```python
from fastapi_utils.tasks import repeat_every

@app.on_event("startup")
@repeat_every(seconds=30)  # 30초마다 업데이트
async def update_metrics():
    """Prometheus 메트릭을 업데이트하는 백그라운드 태스크"""
    try:
        monitor = RedisConnectionPool.get_monitor()
        await monitor.health_check()
        monitor.get_pool_stats()
    except Exception as e:
        logger.error(f"Failed to update metrics: {e}")
```

## 커스텀 메트릭

### 애플리케이션 전용 메트릭 추가

트레이딩 로직을 위한 커스텀 메트릭을 추가할 수 있습니다:

```python
from prometheus_client import Counter, Gauge, Histogram

# 주문 실행 메트릭
orders_executed_total = Counter(
    'trading_orders_executed_total',
    'Total number of orders executed',
    ['strategy', 'side', 'result']
)

# 포지션 메트릭
current_positions = Gauge(
    'trading_current_positions',
    'Number of current open positions',
    ['strategy', 'symbol']
)

# 거래 실행 시간
trade_execution_duration_seconds = Histogram(
    'trading_execution_duration_seconds',
    'Time to execute trades',
    ['strategy', 'exchange'],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0)
)

# 코드에서 사용
@router.post("/execute_trade")
async def execute_trade(order: OrderRequest):
    start_time = time.time()

    try:
        result = await trading_service.execute_order(order)

        # 메트릭 업데이트
        orders_executed_total.labels(
            strategy="hyperrsi",
            side=order.side,
            result="success"
        ).inc()

        current_positions.labels(
            strategy="hyperrsi",
            symbol=order.symbol
        ).set(await get_position_count())

        duration = time.time() - start_time
        trade_execution_duration_seconds.labels(
            strategy="hyperrsi",
            exchange="okx"
        ).observe(duration)

        return result

    except Exception as e:
        orders_executed_total.labels(
            strategy="hyperrsi",
            side=order.side,
            result="error"
        ).inc()
        raise
```

## HYPERRSI 통합 예시

### 완전한 main.py 설정

```python
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app
from contextlib import asynccontextmanager

from HYPERRSI.src.api.routes import trading, account, position
from shared.api.health import router as health_router
from shared.database.redis import init_redis, close_redis
from shared.database.session import init_db, close_db
from shared.logging import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 라이프사이클 이벤트"""
    # 시작
    logger.info("Starting HYPERRSI application...")
    await init_db()
    await init_redis()

    yield

    # 종료
    logger.info("Shutting down HYPERRSI application...")
    await close_redis()
    await close_db()


app = FastAPI(
    title="HYPERRSI Trading Strategy",
    description="RSI + Trend-based cryptocurrency trading strategy",
    version="1.0.0",
    lifespan=lifespan
)

# CORS 미들웨어
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 라우트
app.include_router(trading.router, prefix="/api/trading", tags=["trading"])
app.include_router(account.router, prefix="/api/account", tags=["account"])
app.include_router(position.router, prefix="/api/position", tags=["position"])

# 헬스 엔드포인트 (자동으로 Redis 메트릭 업데이트)
app.include_router(health_router, prefix="/health", tags=["health"])

# Prometheus 메트릭 엔드포인트
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.get("/")
async def root():
    return {
        "service": "HYPERRSI",
        "status": "running",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "metrics": "/metrics",
            "docs": "/docs"
        }
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
```

## GRID 통합 예시

### GRID main.py 설정

```python
import uvicorn
from fastapi import FastAPI
from prometheus_client import make_asgi_app

from GRID.api.app import create_app
from shared.api.health import router as health_router

app = create_app()

# 헬스 엔드포인트 추가
app.include_router(health_router, prefix="/health", tags=["health"])

# Prometheus 메트릭 추가
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8012,
        reload=False,
        workers=1
    )
```

## 메트릭 테스트

### 수동 테스트

```bash
# HYPERRSI 메트릭 테스트
curl http://localhost:8000/metrics | grep redis

# GRID 메트릭 테스트
curl http://localhost:8012/metrics | grep redis

# 특정 메트릭 확인
curl -s http://localhost:8000/metrics | grep redis_pool_utilization_percent
```

### 자동화된 테스트

```python
import pytest
from fastapi.testclient import TestClient

def test_metrics_endpoint(client: TestClient):
    """메트릭 엔드포인트가 노출되는지 테스트"""
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "redis_pool_utilization_percent" in response.text
    assert "redis_connection_latency_ms" in response.text
```

## 모범 사례

### 1. 메트릭 명명 규칙

Prometheus 명명 규칙을 따르세요:
- snake_case 사용: `redis_pool_utilization_percent`
- 단위 접미사 포함: `_seconds`, `_bytes`, `_total`, `_percent`
- 카운터에는 `_total` 사용: `orders_executed_total`

### 2. 레이블 카디널리티

메모리 문제를 피하기 위해 레이블 카디널리티를 낮게 유지하세요:

```python
# ❌ 나쁨 - 높은 카디널리티 (고유한 사용자 ID)
orders_total.labels(user_id="user_12345", symbol="BTC-USDT").inc()

# ✅ 좋음 - 낮은 카디널리티 (전략, 방향)
orders_total.labels(strategy="hyperrsi", side="buy").inc()
```

### 3. 메트릭 수집 빈도

적절한 간격으로 메트릭을 업데이트하세요:
- 빠르게 변하는 메트릭 (연결): 15-30초마다
- 느리게 변하는 메트릭 (설정): 5분마다
- 이벤트 기반 메트릭 (주문): 각 이벤트마다

### 4. 에러 처리

애플리케이션 장애를 방지하기 위해 항상 메트릭 업데이트를 try-except로 감싸세요:

```python
try:
    orders_executed_total.labels(strategy="hyperrsi", side="buy").inc()
except Exception as e:
    logger.error(f"Failed to update metric: {e}")
    # 애플리케이션 흐름 계속 진행
```

## 문제 해결

### 메트릭이 업데이트되지 않음

1. 헬스 엔드포인트가 호출되는지 확인
2. RedisPoolMonitor가 초기화되었는지 확인
3. 애플리케이션 로그에서 오류 확인

### Prometheus가 수집할 수 없음

1. `/metrics` 엔드포인트에 접근 가능한지 확인:
   ```bash
   curl http://localhost:8000/metrics
   ```
2. 방화벽 규칙 확인
3. Prometheus 설정 확인

### 중복 메트릭

"Duplicated timeseries" 오류가 표시되는 경우:
- 메트릭이 모듈 레벨에서 한 번만 정의되는지 확인
- 함수 내에서 메트릭을 재생성하지 마세요
- `.labels()`를 사용하여 메트릭 인스턴스를 구분하세요

## 참고 자료

- [Prometheus Python Client](https://github.com/prometheus/client_python)
- [FastAPI 문서](https://fastapi.tiangolo.com/)
- [Prometheus 모범 사례](https://prometheus.io/docs/practices/naming/)
