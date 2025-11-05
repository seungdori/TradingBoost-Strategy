# BACKTEST_IMPLEMENTATION_ROADMAP.md

백테스팅 시스템 구현을 위한 단계별 로드맵, 우선순위, 일정 및 리스크 관리 전략을 정의합니다.

---

## 목차

1. [구현 전략 개요](#구현-전략-개요)
2. [Phase 1: 기반 구축 (Weeks 1-2)](#phase-1-기반-구축-weeks-1-2)
3. [Phase 2: 코어 엔진 개발 (Weeks 3-4)](#phase-2-코어-엔진-개발-weeks-3-4)
4. [Phase 3: 최적화 & 리포팅 (Weeks 5-6)](#phase-3-최적화--리포팅-weeks-5-6)
5. [Phase 4: 테스트 & 배포 (Weeks 7-8)](#phase-4-테스트--배포-weeks-7-8)
6. [리스크 관리 전략](#리스크-관리-전략)
7. [품질 보증 전략](#품질-보증-전략)
8. [배포 전략](#배포-전략)
9. [모니터링 & 유지보수](#모니터링--유지보수)

---

## 구현 전략 개요

### 전체 일정
- **총 소요 기간**: 8주 (2개월)
- **개발자 인원**: 1-2명
- **일일 작업 시간**: 4-6시간 기준

### 핵심 원칙
1. **점진적 개발**: 각 단계마다 동작하는 시스템 유지
2. **테스트 우선**: 모든 컴포넌트에 단위 테스트 작성
3. **문서화 병행**: 코드와 함께 API 문서 작성
4. **리스크 조기 해결**: 복잡한 작업 우선 처리

### 마일스톤
```mermaid
gantt
    title 백테스팅 시스템 구현 일정
    dateFormat  YYYY-MM-DD

    section Phase 1
    저장소 설정           :p1-1, 2025-01-01, 2d
    공유 라이브러리 추출    :p1-2, after p1-1, 3d
    데이터베이스 스키마     :p1-3, after p1-1, 2d
    기본 API 구조         :p1-4, after p1-3, 3d

    section Phase 2
    DataLoader 개발       :p2-1, after p1-4, 4d
    StrategyRunner 개발   :p2-2, after p2-1, 4d
    PositionTracker 개발  :p2-3, after p2-2, 3d
    기본 백테스트 실행     :p2-4, after p2-3, 3d

    section Phase 3
    PerformanceAnalyzer   :p3-1, after p2-4, 3d
    GridSearch 최적화     :p3-2, after p3-1, 4d
    Genetic 최적화        :p3-3, after p3-2, 4d
    ReportGenerator       :p3-4, after p3-3, 3d

    section Phase 4
    통합 테스트           :p4-1, after p3-4, 4d
    성능 최적화           :p4-2, after p4-1, 3d
    Docker 배포           :p4-3, after p4-2, 3d
    문서 완성             :p4-4, after p4-3, 4d
```

---

## Phase 1: 기반 구축 (Weeks 1-2)

**목표**: 프로젝트 구조 설정, 공유 라이브러리 추출, 데이터베이스 구축

### 1.1 저장소 설정 (2일)

**우선순위**: P0 (최고)

**작업 내용**:
```bash
# 1. 새 저장소 생성
mkdir trading-strategy-core
mkdir trading-backtest-service

# 2. Git 초기화
cd trading-strategy-core
git init
git remote add origin <your-repo-url>

cd ../trading-backtest-service
git init
git remote add origin <your-repo-url>

# 3. 기본 프로젝트 구조 생성
```

**프로젝트 구조**:
```
trading-strategy-core/
├── pyproject.toml
├── README.md
├── src/
│   └── trading_strategy_core/
│       ├── __init__.py
│       ├── models/          # Pydantic models
│       ├── strategies/      # 전략 인터페이스
│       ├── indicators/      # 지표 계산
│       └── utils/           # 유틸리티
├── tests/
└── docs/

trading-backtest-service/
├── pyproject.toml
├── README.md
├── docker-compose.yml
├── Dockerfile
├── src/
│   └── backtest_service/
│       ├── __init__.py
│       ├── api/            # FastAPI routes
│       ├── engine/         # 백테스트 엔진
│       ├── data/           # DataLoader
│       ├── optimizer/      # 최적화 엔진
│       └── reports/        # 리포트 생성
├── tests/
└── docs/
```

**체크리스트**:
- [ ] GitHub/GitLab 저장소 생성
- [ ] pyproject.toml 설정 (Poetry 사용 권장)
- [ ] pre-commit hooks 설정 (black, isort, mypy)
- [ ] CI/CD 파이프라인 기본 설정 (.github/workflows/)
- [ ] README.md 작성

---

### 1.2 공유 라이브러리 추출 (3일)

**우선순위**: P0 (최고)

**Step 1: 지표 계산 모듈 추출**

```python
# trading-strategy-core/src/trading_strategy_core/indicators/__init__.py
from typing import List
import numpy as np
import pandas as pd

def calculate_rsi(prices: List[float], period: int = 14) -> List[float]:
    """
    RSI 계산

    Args:
        prices: 종가 리스트
        period: RSI 기간 (기본 14)

    Returns:
        RSI 값 리스트
    """
    if len(prices) < period + 1:
        return [np.nan] * len(prices)

    df = pd.DataFrame({'close': prices})
    delta = df['close'].diff()

    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))

    return rsi.tolist()

def calculate_atr(high: List[float], low: List[float], close: List[float],
                  period: int = 14) -> List[float]:
    """ATR 계산"""
    df = pd.DataFrame({'high': high, 'low': low, 'close': close})

    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())

    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = true_range.rolling(window=period).mean()

    return atr.tolist()

def calculate_ema(prices: List[float], period: int = 20) -> List[float]:
    """EMA 계산"""
    return pd.Series(prices).ewm(span=period, adjust=False).mean().tolist()
```

**Step 2: 전략 베이스 클래스 추출**

```python
# trading-strategy-core/src/trading_strategy_core/strategies/base.py
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from pydantic import BaseModel
from enum import Enum

class SignalType(str, Enum):
    LONG = "long"
    SHORT = "short"
    CLOSE_LONG = "close_long"
    CLOSE_SHORT = "close_short"
    HOLD = "hold"

class TradingSignal(BaseModel):
    signal_type: SignalType
    confidence: float  # 0.0 ~ 1.0
    reason: str
    metadata: Optional[Dict] = None

class CandleData(BaseModel):
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    # Indicators
    rsi: Optional[float] = None
    atr: Optional[float] = None
    ema: Optional[float] = None
    sma: Optional[float] = None
    upper_band: Optional[float] = None
    lower_band: Optional[float] = None

class TradingStrategy(ABC):
    """모든 전략의 베이스 클래스"""

    def __init__(self, config: BaseModel):
        self.config = config
        self.min_candles = self._get_min_candles()

    @abstractmethod
    def _get_min_candles(self) -> int:
        """전략 실행에 필요한 최소 캔들 수"""
        pass

    @abstractmethod
    def analyze(self, candles: List[CandleData]) -> TradingSignal:
        """
        캔들 데이터를 분석하여 거래 신호 생성

        Args:
            candles: 캔들 데이터 리스트 (오래된 것부터 최신 순)

        Returns:
            TradingSignal 객체
        """
        pass

    def validate_candles(self, candles: List[CandleData]) -> bool:
        """캔들 데이터 유효성 검증"""
        if len(candles) < self.min_candles:
            return False

        # 지표 값이 모두 있는지 확인
        for candle in candles[-self.min_candles:]:
            if candle.rsi is None:
                return False

        return True
```

**Step 3: HYPERRSI 전략 추출**

```python
# trading-strategy-core/src/trading_strategy_core/strategies/hyperrsi.py
from typing import List, Literal
from pydantic import BaseModel, Field
from .base import TradingStrategy, TradingSignal, SignalType, CandleData

class HYPERRSIConfig(BaseModel):
    """HYPERRSI 전략 설정"""

    # RSI 설정
    rsi_period: int = Field(default=14, ge=2, le=50)
    rsi_oversold: float = Field(default=30.0, ge=0, le=50)
    rsi_overbought: float = Field(default=70.0, ge=50, le=100)

    # 엔트리 옵션
    entry_option: Literal["reverse", "follow"] = "reverse"

    # 트렌드 설정
    use_trend_filter: bool = True
    trend_ema_period: int = Field(default=200, ge=50, le=500)

    # 리스크 관리
    leverage: float = Field(default=3.0, ge=1.0, le=20.0)
    stop_loss_percent: float = Field(default=2.0, ge=0.5, le=10.0)

class HYPERRSIStrategy(TradingStrategy):
    """HYPERRSI 전략 구현"""

    def __init__(self, config: HYPERRSIConfig):
        super().__init__(config)
        self.config: HYPERRSIConfig = config

    def _get_min_candles(self) -> int:
        # RSI 계산에 필요한 최소 캔들 수 + 여유분
        return max(self.config.rsi_period * 2, 30)

    def analyze(self, candles: List[CandleData]) -> TradingSignal:
        """
        HYPERRSI 전략 로직 (execute_trading_logic.py:491-520 기반)
        """
        if not self.validate_candles(candles):
            return TradingSignal(
                signal_type=SignalType.HOLD,
                confidence=0.0,
                reason="Insufficient candle data"
            )

        # 최근 캔들 데이터
        current = candles[-1]
        previous = candles[-2]

        current_rsi = current.rsi
        previous_rsi = previous.rsi

        # Reverse 모드
        if self.config.entry_option == "reverse":
            # Long 신호: 과매도 구간에서 반등
            if previous_rsi <= self.config.rsi_oversold and current_rsi > self.config.rsi_oversold:
                # 트렌드 필터 확인
                if self.config.use_trend_filter:
                    if current.close < current.ema:  # 하락 트렌드 확인
                        return TradingSignal(
                            signal_type=SignalType.LONG,
                            confidence=0.8,
                            reason=f"RSI reversal from oversold: {previous_rsi:.2f} -> {current_rsi:.2f}",
                            metadata={"rsi": current_rsi, "price": current.close}
                        )
                else:
                    return TradingSignal(
                        signal_type=SignalType.LONG,
                        confidence=0.8,
                        reason=f"RSI reversal from oversold (no trend filter): {previous_rsi:.2f} -> {current_rsi:.2f}",
                        metadata={"rsi": current_rsi, "price": current.close}
                    )

            # Short 신호: 과매수 구간에서 반락
            if previous_rsi >= self.config.rsi_overbought and current_rsi < self.config.rsi_overbought:
                if self.config.use_trend_filter:
                    if current.close > current.ema:  # 상승 트렌드 확인
                        return TradingSignal(
                            signal_type=SignalType.SHORT,
                            confidence=0.8,
                            reason=f"RSI reversal from overbought: {previous_rsi:.2f} -> {current_rsi:.2f}",
                            metadata={"rsi": current_rsi, "price": current.close}
                        )
                else:
                    return TradingSignal(
                        signal_type=SignalType.SHORT,
                        confidence=0.8,
                        reason=f"RSI reversal from overbought (no trend filter): {previous_rsi:.2f} -> {current_rsi:.2f}",
                        metadata={"rsi": current_rsi, "price": current.close}
                    )

        # Follow 모드
        elif self.config.entry_option == "follow":
            # Long 신호: 과매도 구간 진입
            if current_rsi <= self.config.rsi_oversold:
                return TradingSignal(
                    signal_type=SignalType.LONG,
                    confidence=0.7,
                    reason=f"RSI in oversold zone: {current_rsi:.2f}",
                    metadata={"rsi": current_rsi, "price": current.close}
                )

            # Short 신호: 과매수 구간 진입
            if current_rsi >= self.config.rsi_overbought:
                return TradingSignal(
                    signal_type=SignalType.SHORT,
                    confidence=0.7,
                    reason=f"RSI in overbought zone: {current_rsi:.2f}",
                    metadata={"rsi": current_rsi, "price": current.close}
                )

        return TradingSignal(
            signal_type=SignalType.HOLD,
            confidence=0.0,
            reason="No signal conditions met"
        )
```

**Step 4: PyPI 패키지 설정**

```toml
# trading-strategy-core/pyproject.toml
[tool.poetry]
name = "trading-strategy-core"
version = "0.1.0"
description = "Shared trading strategy library for TradingBoost"
authors = ["Your Name <your.email@example.com>"]
license = "MIT"
readme = "README.md"

[tool.poetry.dependencies]
python = "^3.9"
pydantic = "^2.0"
pandas = "^2.0"
numpy = "^1.24"

[tool.poetry.group.dev.dependencies]
pytest = "^7.4"
black = "^23.0"
isort = "^5.12"
mypy = "^1.5"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

**빌드 & 배포**:
```bash
# 로컬 개발
cd trading-strategy-core
poetry install
poetry build

# PyPI 배포 (선택사항)
poetry publish --build

# 또는 로컬 설치 (개발 중)
pip install -e /path/to/trading-strategy-core
```

**체크리스트**:
- [ ] 지표 계산 함수 추출 및 테스트
- [ ] TradingStrategy 베이스 클래스 작성
- [ ] HYPERRSIStrategy 구현 및 검증
- [ ] 단위 테스트 작성 (pytest)
- [ ] 타입 힌팅 검증 (mypy)
- [ ] 문서화 (docstring, README)
- [ ] 패키지 빌드 및 설치 테스트

**예상 소요 시간**: 3일 (24시간)

---

### 1.3 데이터베이스 스키마 구축 (2일)

**우선순위**: P0 (최고)

**Step 1: TimescaleDB 설치 (Docker)**

```yaml
# trading-backtest-service/docker-compose.yml
version: '3.8'

services:
  timescaledb:
    image: timescale/timescaledb:latest-pg15
    container_name: backtest-timescaledb
    environment:
      POSTGRES_USER: backtest_admin
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: backtest_db
    ports:
      - "5433:5432"
    volumes:
      - timescaledb_data:/var/lib/postgresql/data
      - ./migrations:/docker-entrypoint-initdb.d
    command: postgres -c shared_preload_libraries=timescaledb

volumes:
  timescaledb_data:
```

**Step 2: 마이그레이션 스크립트**

```sql
-- trading-backtest-service/migrations/001_create_candles_history.sql

-- 1. 캔들 히스토리 테이블 생성
CREATE TABLE IF NOT EXISTS candles_history (
    timestamp TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION NOT NULL,

    -- Indicators
    rsi DOUBLE PRECISION,
    atr DOUBLE PRECISION,
    ema DOUBLE PRECISION,
    sma DOUBLE PRECISION,
    upper_band DOUBLE PRECISION,
    lower_band DOUBLE PRECISION,

    PRIMARY KEY (symbol, timeframe, timestamp)
);

-- 2. Hypertable 생성 (시계열 최적화)
SELECT create_hypertable('candles_history', 'timestamp',
                         chunk_time_interval => INTERVAL '1 month',
                         if_not_exists => TRUE);

-- 3. 인덱스 생성
CREATE INDEX idx_candles_symbol_timeframe_time
ON candles_history (symbol, timeframe, timestamp DESC);

CREATE INDEX idx_candles_symbol_time
ON candles_history (symbol, timestamp DESC);

-- 4. 압축 정책 (1개월 이상 데이터)
ALTER TABLE candles_history SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol, timeframe',
    timescaledb.compress_orderby = 'timestamp DESC'
);

SELECT add_compression_policy('candles_history', INTERVAL '1 month');

-- 5. 보존 정책 (2년 후 자동 삭제)
SELECT add_retention_policy('candles_history', INTERVAL '2 years');

-- 6. 연속 집계 뷰 (일별 통계)
CREATE MATERIALIZED VIEW candles_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', timestamp) AS day,
    symbol,
    timeframe,
    first(open, timestamp) AS open,
    max(high) AS high,
    min(low) AS low,
    last(close, timestamp) AS close,
    sum(volume) AS volume,
    avg(rsi) AS avg_rsi,
    avg(atr) AS avg_atr
FROM candles_history
GROUP BY day, symbol, timeframe;

SELECT add_continuous_aggregate_policy('candles_daily',
    start_offset => INTERVAL '3 days',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day');

-- 7. 백테스트 결과 테이블
CREATE TABLE IF NOT EXISTS backtest_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    start_date TIMESTAMPTZ NOT NULL,
    end_date TIMESTAMPTZ NOT NULL,

    -- 파라미터 (JSONB)
    parameters JSONB NOT NULL,

    -- 성능 지표
    total_return DOUBLE PRECISION,
    annual_return DOUBLE PRECISION,
    sharpe_ratio DOUBLE PRECISION,
    sortino_ratio DOUBLE PRECISION,
    max_drawdown DOUBLE PRECISION,
    win_rate DOUBLE PRECISION,
    profit_factor DOUBLE PRECISION,
    total_trades INTEGER,

    -- 메타데이터
    created_at TIMESTAMPTZ DEFAULT NOW(),
    execution_time_seconds DOUBLE PRECISION,

    -- 상세 결과 (JSONB)
    detailed_metrics JSONB,
    equity_curve JSONB,
    trade_log JSONB
);

CREATE INDEX idx_backtest_results_strategy ON backtest_results (strategy_name, symbol, timeframe);
CREATE INDEX idx_backtest_results_created_at ON backtest_results (created_at DESC);

-- 8. 최적화 결과 테이블
CREATE TABLE IF NOT EXISTS optimization_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    backtest_id UUID REFERENCES backtest_results(id),
    optimization_method TEXT NOT NULL,  -- 'grid_search' or 'genetic'

    -- 최적 파라미터
    best_parameters JSONB NOT NULL,
    best_sharpe_ratio DOUBLE PRECISION,
    best_total_return DOUBLE PRECISION,

    -- 탐색 공간
    parameter_space JSONB NOT NULL,
    total_combinations INTEGER,
    evaluated_combinations INTEGER,

    -- 메타데이터
    created_at TIMESTAMPTZ DEFAULT NOW(),
    execution_time_seconds DOUBLE PRECISION,

    -- 전체 결과 (상위 N개)
    top_results JSONB  -- [{params: {...}, metrics: {...}}, ...]
);

CREATE INDEX idx_optimization_backtest_id ON optimization_results (backtest_id);
CREATE INDEX idx_optimization_method ON optimization_results (optimization_method);
```

**Step 3: 초기 데이터 마이그레이션 스크립트**

```python
# trading-backtest-service/scripts/migrate_redis_to_timescale.py
"""
Redis의 캔들 데이터를 TimescaleDB로 마이그레이션
"""
import asyncio
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import json

async def migrate_candles(symbol: str, timeframe: str):
    """특정 심볼/타임프레임의 캔들 데이터 마이그레이션"""

    # Redis 연결
    redis_client = await aioredis.from_url("redis://localhost:6379/0")

    # TimescaleDB 연결
    engine = create_async_engine("postgresql+asyncpg://backtest_admin:password@localhost:5433/backtest_db")
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        # Redis에서 캔들 데이터 가져오기
        key = f"candles_with_indicators:{symbol}:{timeframe}"
        candles_json = await redis_client.get(key)

        if not candles_json:
            print(f"No data found for {symbol} {timeframe}")
            return

        candles = json.loads(candles_json)
        print(f"Found {len(candles)} candles for {symbol} {timeframe}")

        # TimescaleDB에 삽입
        async with async_session() as session:
            for candle in candles:
                insert_sql = """
                INSERT INTO candles_history
                (timestamp, symbol, timeframe, open, high, low, close, volume,
                 rsi, atr, ema, sma, upper_band, lower_band)
                VALUES (:timestamp, :symbol, :timeframe, :open, :high, :low, :close, :volume,
                        :rsi, :atr, :ema, :sma, :upper_band, :lower_band)
                ON CONFLICT (symbol, timeframe, timestamp) DO NOTHING
                """

                await session.execute(insert_sql, {
                    'timestamp': datetime.fromtimestamp(candle['timestamp'] / 1000),
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'open': candle['open'],
                    'high': candle['high'],
                    'low': candle['low'],
                    'close': candle['close'],
                    'volume': candle['volume'],
                    'rsi': candle.get('rsi'),
                    'atr': candle.get('atr'),
                    'ema': candle.get('ema'),
                    'sma': candle.get('sma'),
                    'upper_band': candle.get('upper_band'),
                    'lower_band': candle.get('lower_band')
                })

            await session.commit()
            print(f"Successfully migrated {len(candles)} candles")

    finally:
        await redis_client.close()
        await engine.dispose()

if __name__ == "__main__":
    # 마이그레이션 실행
    symbols = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    timeframes = ["1m", "5m", "15m", "1h", "4h"]

    for symbol in symbols:
        for timeframe in timeframes:
            asyncio.run(migrate_candles(symbol, timeframe))
```

**체크리스트**:
- [ ] TimescaleDB Docker 컨테이너 실행
- [ ] 마이그레이션 스크립트 실행
- [ ] 테이블 생성 확인
- [ ] 인덱스 및 압축 정책 확인
- [ ] 샘플 데이터 삽입 테스트
- [ ] 쿼리 성능 테스트

**예상 소요 시간**: 2일 (16시간)

---

### 1.4 기본 API 구조 (3일)

**우선순위**: P1 (높음)

**Step 1: FastAPI 프로젝트 구조**

```python
# trading-backtest-service/src/backtest_service/api/main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from .routes import backtest, optimization, health
from ..database import engine, init_db

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 생명주기 관리"""
    # Startup
    logger.info("Initializing database...")
    await init_db()
    logger.info("Backtest service started")

    yield

    # Shutdown
    logger.info("Shutting down...")
    await engine.dispose()

app = FastAPI(
    title="Trading Backtest Service",
    version="1.0.0",
    description="Backtesting and optimization service for trading strategies",
    lifespan=lifespan
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 프로덕션에서는 제한 필요
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(health.router, tags=["Health"])
app.include_router(backtest.router, prefix="/api/v1/backtest", tags=["Backtest"])
app.include_router(optimization.router, prefix="/api/v1/optimize", tags=["Optimization"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
```

**Step 2: Health Check 엔드포인트**

```python
# trading-backtest-service/src/backtest_service/api/routes/health.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from ...database import get_db
import redis.asyncio as aioredis
from pydantic import BaseModel

router = APIRouter()

class HealthResponse(BaseModel):
    status: str
    database: str
    redis: str

@router.get("/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)):
    """서비스 헬스 체크"""

    # Database 체크
    db_status = "healthy"
    try:
        await db.execute("SELECT 1")
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"

    # Redis 체크 (프로덕션 Redis 읽기 전용)
    redis_status = "healthy"
    try:
        redis_client = await aioredis.from_url("redis://localhost:6379/0")
        await redis_client.ping()
        await redis_client.close()
    except Exception as e:
        redis_status = f"unhealthy: {str(e)}"

    overall_status = "healthy" if "unhealthy" not in [db_status, redis_status] else "unhealthy"

    return HealthResponse(
        status=overall_status,
        database=db_status,
        redis=redis_status
    )
```

**Step 3: 기본 백테스트 엔드포인트 (스켈레톤)**

```python
# trading-backtest-service/src/backtest_service/api/routes/backtest.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from typing import List, Dict, Any
from datetime import datetime
import uuid

from ...database import get_db

router = APIRouter()

class BacktestRequest(BaseModel):
    strategy_name: str = Field(..., description="전략 이름 (예: HYPERRSI)")
    symbol: str = Field(..., example="BTC-USDT-SWAP")
    timeframe: str = Field(..., example="1h")
    start_date: datetime
    end_date: datetime
    parameters: Dict[str, Any] = Field(..., description="전략 파라미터")
    initial_capital: float = Field(default=10000.0, ge=100)

class BacktestResponse(BaseModel):
    backtest_id: str
    status: str
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    total_trades: int

@router.post("/run", response_model=BacktestResponse)
async def run_backtest(
    request: BacktestRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    백테스트 실행

    Phase 1에서는 스켈레톤만 구현, Phase 2에서 실제 로직 추가
    """
    backtest_id = str(uuid.uuid4())

    # TODO: Phase 2에서 실제 백테스트 엔진 통합

    return BacktestResponse(
        backtest_id=backtest_id,
        status="completed",
        total_return=0.0,
        sharpe_ratio=0.0,
        max_drawdown=0.0,
        total_trades=0
    )

@router.get("/{backtest_id}")
async def get_backtest_result(
    backtest_id: str,
    db: AsyncSession = Depends(get_db)
):
    """백테스트 결과 조회"""
    # TODO: 데이터베이스에서 결과 조회
    raise HTTPException(status_code=404, detail="Backtest not found")

@router.get("/")
async def list_backtests(
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db)
):
    """백테스트 목록 조회"""
    # TODO: 데이터베이스에서 목록 조회
    return {"backtests": [], "total": 0}
```

**체크리스트**:
- [ ] FastAPI 프로젝트 설정
- [ ] Health check 엔드포인트 구현 및 테스트
- [ ] 기본 라우터 구조 생성
- [ ] Pydantic 모델 정의
- [ ] API 문서 자동 생성 확인 (/docs)
- [ ] 로깅 설정
- [ ] 환경 변수 관리 (.env)

**예상 소요 시간**: 3일 (24시간)

---

## Phase 2: 코어 엔진 개발 (Weeks 3-4)

**목표**: 백테스팅 엔진 핵심 컴포넌트 구현

### 2.1 DataLoader 개발 (4일)

**우선순위**: P0 (최고)

**구현 내용**:
- Redis 읽기 전용 연결
- TimescaleDB 쿼리 최적화
- 하이브리드 데이터 로딩 전략
- 캐싱 레이어

**코드 예시**:
```python
# trading-backtest-service/src/backtest_service/data/loader.py
from typing import List, Optional
from datetime import datetime, timedelta
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import json

from trading_strategy_core.strategies.base import CandleData

class DataLoader:
    """하이브리드 데이터 로더"""

    def __init__(self, db_session: AsyncSession, redis_url: str):
        self.db = db_session
        self.redis_url = redis_url
        self._redis_client = None

    async def _get_redis_client(self):
        if self._redis_client is None:
            self._redis_client = await aioredis.from_url(self.redis_url)
        return self._redis_client

    async def load_candles(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[CandleData]:
        """
        하이브리드 전략으로 캔들 데이터 로드

        1. Redis에서 최근 48시간 데이터 가져오기
        2. TimescaleDB에서 과거 데이터 가져오기
        3. 병합 및 정렬
        """
        cutoff_date = datetime.now() - timedelta(hours=48)

        tasks = []

        # 과거 데이터는 DB에서
        if start_date < cutoff_date:
            db_end = min(end_date, cutoff_date)
            tasks.append(self._load_from_db(symbol, timeframe, start_date, db_end))

        # 최근 데이터는 Redis에서
        if end_date > cutoff_date:
            redis_start = max(start_date, cutoff_date)
            tasks.append(self._load_from_redis(symbol, timeframe, redis_start, end_date))

        # 병렬 실행
        results = await asyncio.gather(*tasks)

        # 병합 및 정렬
        all_candles = []
        for candles in results:
            all_candles.extend(candles)

        all_candles.sort(key=lambda c: c.timestamp)

        return all_candles

    async def _load_from_db(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[CandleData]:
        """TimescaleDB에서 캔들 로드"""

        query = text("""
            SELECT timestamp, open, high, low, close, volume,
                   rsi, atr, ema, sma, upper_band, lower_band
            FROM candles_history
            WHERE symbol = :symbol
              AND timeframe = :timeframe
              AND timestamp BETWEEN :start_date AND :end_date
            ORDER BY timestamp ASC
        """)

        result = await self.db.execute(query, {
            'symbol': symbol,
            'timeframe': timeframe,
            'start_date': start_date,
            'end_date': end_date
        })

        candles = []
        for row in result:
            candles.append(CandleData(
                timestamp=int(row[0].timestamp() * 1000),
                open=row[1],
                high=row[2],
                low=row[3],
                close=row[4],
                volume=row[5],
                rsi=row[6],
                atr=row[7],
                ema=row[8],
                sma=row[9],
                upper_band=row[10],
                lower_band=row[11]
            ))

        return candles

    async def _load_from_redis(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[CandleData]:
        """Redis에서 캔들 로드"""

        redis_client = await self._get_redis_client()
        key = f"candles_with_indicators:{symbol}:{timeframe}"

        candles_json = await redis_client.get(key)
        if not candles_json:
            return []

        all_candles = json.loads(candles_json)

        # 날짜 필터링
        start_ts = int(start_date.timestamp() * 1000)
        end_ts = int(end_date.timestamp() * 1000)

        filtered = [
            CandleData(**candle)
            for candle in all_candles
            if start_ts <= candle['timestamp'] <= end_ts
        ]

        return filtered
```

**체크리스트**:
- [ ] Redis 읽기 전용 연결 구현
- [ ] TimescaleDB 쿼리 최적화
- [ ] 하이브리드 로딩 로직 구현
- [ ] 단위 테스트 (pytest-asyncio)
- [ ] 성능 테스트 (10만 캔들 로드 시간 측정)

**예상 소요 시간**: 4일 (32시간)

---

### 2.2 StrategyRunner 개발 (4일)

**우선순위**: P0 (최고)

**구현 내용**:
- 전략 인스턴스 관리
- 캔들 데이터 전처리
- 신호 생성 및 검증
- 이벤트 기반 실행 루프

**코드 예시**:
```python
# trading-backtest-service/src/backtest_service/engine/strategy_runner.py
from typing import List, Optional
from trading_strategy_core.strategies.base import TradingStrategy, TradingSignal, CandleData, SignalType

class StrategyRunner:
    """전략 실행 엔진"""

    def __init__(self, strategy: TradingStrategy):
        self.strategy = strategy
        self.signal_history: List[TradingSignal] = []

    def run(self, candles: List[CandleData]) -> List[TradingSignal]:
        """
        전략을 실행하여 거래 신호 생성

        Args:
            candles: 전체 캔들 데이터 (시간순 정렬)

        Returns:
            생성된 신호 리스트
        """
        signals = []
        min_candles = self.strategy.min_candles

        # 슬라이딩 윈도우로 신호 생성
        for i in range(min_candles, len(candles)):
            window = candles[i - min_candles:i + 1]

            signal = self.strategy.analyze(window)

            if signal.signal_type != SignalType.HOLD:
                signals.append(signal)
                self.signal_history.append(signal)

        return signals

    def validate_signal(self, signal: TradingSignal, current_candle: CandleData) -> bool:
        """신호 유효성 검증"""
        if signal.confidence < 0.5:
            return False

        # 가격 유효성 확인
        if current_candle.close <= 0:
            return False

        return True
```

**체크리스트**:
- [ ] StrategyRunner 클래스 구현
- [ ] 슬라이딩 윈도우 로직 구현
- [ ] 신호 검증 로직 구현
- [ ] 단위 테스트
- [ ] 통합 테스트 (실제 전략으로 테스트)

**예상 소요 시간**: 4일 (32시간)

---

### 2.3 PositionTracker 개발 (3일)

**우선순위**: P0 (최고)

**이미 BACKTEST_ENGINE_DESIGN.md에 상세 구현 완료**

**체크리스트**:
- [ ] Position 모델 구현
- [ ] PositionTracker 클래스 구현
- [ ] 수수료 계산 로직 검증
- [ ] PnL 계산 로직 검증
- [ ] 단위 테스트 (다양한 시나리오)

**예상 소요 시간**: 3일 (24시간)

---

### 2.4 기본 백테스트 실행 (3일)

**우선순위**: P0 (최고)

**통합 구현**:
```python
# trading-backtest-service/src/backtest_service/engine/backtest_engine.py
from typing import Dict, Any
from datetime import datetime
import time

from .strategy_runner import StrategyRunner
from .position_tracker import PositionTracker
from ..data.loader import DataLoader
from trading_strategy_core.strategies.base import TradingStrategy, SignalType

class BacktestEngine:
    """백테스트 엔진 - 모든 컴포넌트 통합"""

    def __init__(
        self,
        data_loader: DataLoader,
        strategy: TradingStrategy,
        initial_capital: float = 10000.0,
        fee_rate: float = 0.0004
    ):
        self.data_loader = data_loader
        self.strategy_runner = StrategyRunner(strategy)
        self.position_tracker = PositionTracker(initial_capital, fee_rate)

    async def run(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """
        백테스트 실행

        Returns:
            백테스트 결과 딕셔너리
        """
        start_time = time.time()

        # 1. 데이터 로드
        candles = await self.data_loader.load_candles(symbol, timeframe, start_date, end_date)

        if len(candles) < self.strategy_runner.strategy.min_candles:
            raise ValueError(f"Insufficient candles: {len(candles)} < {self.strategy_runner.strategy.min_candles}")

        # 2. 신호 생성
        signals = self.strategy_runner.run(candles)

        # 3. 포지션 관리 및 거래 실행
        current_position = None

        for i, signal in enumerate(signals):
            current_candle = candles[i]

            if signal.signal_type == SignalType.LONG and current_position is None:
                # Long 포지션 진입
                contracts = self.position_tracker.cash / current_candle.close
                current_position = self.position_tracker.open_position(
                    side="LONG",
                    entry_price=current_candle.close,
                    entry_time=current_candle.timestamp,
                    contracts=contracts,
                    leverage=1.0
                )

            elif signal.signal_type == SignalType.SHORT and current_position is None:
                # Short 포지션 진입
                contracts = self.position_tracker.cash / current_candle.close
                current_position = self.position_tracker.open_position(
                    side="SHORT",
                    entry_price=current_candle.close,
                    entry_time=current_candle.timestamp,
                    contracts=contracts,
                    leverage=1.0
                )

            elif signal.signal_type in [SignalType.CLOSE_LONG, SignalType.CLOSE_SHORT]:
                # 포지션 종료
                if current_position:
                    self.position_tracker.close_position(
                        current_candle.close,
                        current_candle.timestamp
                    )
                    current_position = None

        # 4. 결과 수집
        execution_time = time.time() - start_time

        return {
            'total_candles': len(candles),
            'total_signals': len(signals),
            'total_trades': len(self.position_tracker.trade_history),
            'final_equity': self.position_tracker.equity,
            'total_return': (self.position_tracker.equity - self.position_tracker.initial_capital) / self.position_tracker.initial_capital,
            'execution_time_seconds': execution_time
        }
```

**체크리스트**:
- [ ] BacktestEngine 클래스 구현
- [ ] DataLoader, StrategyRunner, PositionTracker 통합
- [ ] 엔드투엔드 테스트 (HYPERRSI 전략)
- [ ] 성능 프로파일링
- [ ] API 엔드포인트 연결

**예상 소요 시간**: 3일 (24시간)

---

## Phase 3: 최적화 & 리포팅 (Weeks 5-6)

**목표**: 파라미터 최적화 엔진 및 리포트 생성 기능 구현

### 3.1 PerformanceAnalyzer 개발 (3일)

**우선순위**: P1 (높음)

**이미 BACKTEST_ENGINE_DESIGN.md에 상세 구현 완료**

**체크리스트**:
- [ ] 15가지 성능 지표 구현
- [ ] Sharpe/Sortino/Calmar Ratio 검증
- [ ] Drawdown 계산 검증
- [ ] 단위 테스트 (known values)

**예상 소요 시간**: 3일 (24시간)

---

### 3.2 GridSearch 최적화 (4일)

**우선순위**: P1 (높음)

**체크리스트**:
- [ ] GridSearchOptimizer 구현
- [ ] 병렬 처리 (ProcessPoolExecutor)
- [ ] 진행률 추적 (tqdm)
- [ ] 결과 저장 (TimescaleDB)
- [ ] API 엔드포인트 구현

**예상 소요 시간**: 4일 (32시간)

---

### 3.3 Genetic Algorithm 최적화 (4일)

**우선순위**: P2 (중간)

**체크리스트**:
- [ ] GeneticOptimizer 구현
- [ ] Selection, Crossover, Mutation 구현
- [ ] 수렴 조건 설정
- [ ] 결과 시각화 (세대별 진화)
- [ ] API 엔드포인트 구현

**예상 소요 시간**: 4일 (32시간)

---

### 3.4 ReportGenerator 개발 (3일)

**우선순위**: P1 (높음)

**체크리스트**:
- [ ] HTML 템플릿 작성 (Jinja2)
- [ ] matplotlib 차트 생성
- [ ] PDF 변환 (optional, WeasyPrint)
- [ ] 이메일 전송 기능 (optional)
- [ ] API 엔드포인트 구현

**예상 소요 시간**: 3일 (24시간)

---

## Phase 4: 테스트 & 배포 (Weeks 7-8)

**목표**: 전체 시스템 통합 테스트 및 프로덕션 배포

### 4.1 통합 테스트 (4일)

**우선순위**: P0 (최고)

**테스트 범위**:
1. **엔드투엔드 테스트**
   - 실제 과거 데이터로 백테스트 실행
   - HYPERRSI 전략 검증
   - 최적화 실행 검증

2. **성능 테스트**
   - 100만 캔들 백테스트 (목표: <10초)
   - Grid Search 1000 조합 (목표: <5분, 병렬)
   - Genetic Algorithm 100세대 (목표: <10분)

3. **부하 테스트**
   - 동시 백테스트 10개 실행
   - API 응답 시간 측정 (목표: <200ms)

**테스트 스크립트**:
```python
# tests/integration/test_full_backtest.py
import pytest
from datetime import datetime, timedelta
from trading_strategy_core.strategies.hyperrsi import HYPERRSIStrategy, HYPERRSIConfig
from backtest_service.engine.backtest_engine import BacktestEngine

@pytest.mark.asyncio
async def test_full_backtest_hyperrsi():
    """HYPERRSI 전략 전체 백테스트"""

    # 설정
    config = HYPERRSIConfig(
        rsi_period=14,
        rsi_oversold=30,
        rsi_overbought=70,
        entry_option="reverse",
        leverage=3.0
    )

    strategy = HYPERRSIStrategy(config)

    # 백테스트 엔진
    engine = BacktestEngine(
        data_loader=data_loader,
        strategy=strategy,
        initial_capital=10000,
        fee_rate=0.0004
    )

    # 실행
    result = await engine.run(
        symbol="BTC-USDT-SWAP",
        timeframe="1h",
        start_date=datetime.now() - timedelta(days=90),
        end_date=datetime.now()
    )

    # 검증
    assert result['total_trades'] > 0
    assert result['final_equity'] > 0
    assert -1.0 <= result['total_return'] <= 10.0  # 합리적 범위
```

**체크리스트**:
- [ ] 엔드투엔드 테스트 작성 및 실행
- [ ] 성능 테스트 및 프로파일링
- [ ] 부하 테스트 (locust 또는 pytest-benchmark)
- [ ] 테스트 커버리지 측정 (목표: >80%)
- [ ] 테스트 자동화 (CI/CD)

**예상 소요 시간**: 4일 (32시간)

---

### 4.2 성능 최적화 (3일)

**우선순위**: P1 (높음)

**최적화 영역**:

1. **데이터 로딩**
   - Redis 파이프라인 사용
   - TimescaleDB 쿼리 최적화 (EXPLAIN ANALYZE)
   - 캐싱 레이어 추가 (Redis)

2. **백테스트 실행**
   - NumPy 벡터화 (indicator 계산)
   - Numba JIT 컴파일 (핫스팟)
   - 메모리 사용량 최적화

3. **최적화 엔진**
   - multiprocessing 풀 크기 조정
   - Ray 분산 처리 (optional)

**최적화 예시**:
```python
# 벡터화 전 (느림)
def calculate_rsi_slow(prices):
    rsi_values = []
    for i in range(len(prices)):
        rsi_values.append(calculate_single_rsi(prices[:i+1]))
    return rsi_values

# 벡터화 후 (빠름)
def calculate_rsi_fast(prices):
    prices = np.array(prices)
    deltas = np.diff(prices)
    seed = deltas[:14+1]
    up = seed[seed >= 0].sum() / 14
    down = -seed[seed < 0].sum() / 14
    rs = up / down
    rsi = np.zeros_like(prices)
    rsi[:14] = 100. - 100. / (1. + rs)

    for i in range(14, len(prices)):
        delta = deltas[i - 1]
        if delta > 0:
            upval = delta
            downval = 0.
        else:
            upval = 0.
            downval = -delta

        up = (up * 13 + upval) / 14
        down = (down * 13 + downval) / 14
        rs = up / down
        rsi[i] = 100. - 100. / (1. + rs)

    return rsi
```

**체크리스트**:
- [ ] 성능 프로파일링 (cProfile, line_profiler)
- [ ] 핫스팟 최적화
- [ ] 메모리 프로파일링 (memory_profiler)
- [ ] 병렬 처리 최적화
- [ ] 최적화 전후 벤치마크 비교

**예상 소요 시간**: 3일 (24시간)

---

### 4.3 Docker 배포 (3일)

**우선순위**: P0 (최고)

**Dockerfile**:
```dockerfile
# trading-backtest-service/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# 시스템 의존성
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Poetry 설치
RUN pip install poetry==1.6.1
ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false

# 의존성 설치
COPY pyproject.toml poetry.lock ./
RUN poetry install --no-root --only main

# 애플리케이션 복사
COPY . .
RUN poetry install --only main

# 공유 라이브러리 설치
RUN pip install trading-strategy-core

EXPOSE 8001

CMD ["uvicorn", "backtest_service.api.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

**docker-compose.yml**:
```yaml
version: '3.8'

services:
  backtest-api:
    build: .
    container_name: backtest-api
    ports:
      - "8001:8001"
    environment:
      - DATABASE_URL=postgresql+asyncpg://backtest_admin:${DB_PASSWORD}@timescaledb:5432/backtest_db
      - REDIS_URL=redis://production-redis:6379/0
    depends_on:
      - timescaledb
    networks:
      - backtest-network

  timescaledb:
    image: timescale/timescaledb:latest-pg15
    container_name: backtest-timescaledb
    environment:
      POSTGRES_USER: backtest_admin
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: backtest_db
    ports:
      - "5433:5432"
    volumes:
      - timescaledb_data:/var/lib/postgresql/data
      - ./migrations:/docker-entrypoint-initdb.d
    networks:
      - backtest-network

  nginx:
    image: nginx:alpine
    container_name: backtest-nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./ssl:/etc/nginx/ssl
    depends_on:
      - backtest-api
    networks:
      - backtest-network

volumes:
  timescaledb_data:

networks:
  backtest-network:
    driver: bridge
```

**체크리스트**:
- [ ] Dockerfile 작성 및 빌드 테스트
- [ ] docker-compose.yml 작성
- [ ] 환경 변수 관리 (.env)
- [ ] Nginx 설정 (리버스 프록시)
- [ ] SSL 인증서 설정 (Let's Encrypt)
- [ ] 헬스 체크 설정
- [ ] 로그 수집 설정 (Docker logs)

**예상 소요 시간**: 3일 (24시간)

---

### 4.4 문서 완성 (4일)

**우선순위**: P1 (높음)

**문서 종류**:

1. **README.md**
   - 프로젝트 소개
   - 설치 방법
   - 빠른 시작 가이드
   - 아키텍처 다이어그램

2. **API 문서**
   - FastAPI 자동 생성 (/docs)
   - Postman 컬렉션
   - API 사용 예제

3. **개발자 가이드**
   - 로컬 개발 환경 설정
   - 테스트 실행 방법
   - 코드 스타일 가이드
   - 기여 가이드라인

4. **사용자 가이드**
   - 전략 작성 방법
   - 백테스트 실행 가이드
   - 최적화 가이드
   - 리포트 해석 방법

5. **운영 가이드**
   - 배포 프로세스
   - 모니터링 설정
   - 트러블슈팅
   - FAQ

**체크리스트**:
- [ ] README.md 작성
- [ ] API 문서 완성
- [ ] 개발자 가이드 작성
- [ ] 사용자 가이드 작성
- [ ] 운영 가이드 작성
- [ ] 코드 주석 추가
- [ ] 문서 리뷰 및 수정

**예상 소요 시간**: 4일 (32시간)

---

## 리스크 관리 전략

### 주요 리스크 및 완화 방안

| 리스크 | 발생 확률 | 영향도 | 완화 방안 |
|--------|----------|--------|-----------|
| **데이터 불일치** (Redis vs DB) | 중간 | 높음 | - 데이터 검증 레이어 추가<br>- 타임스탬프 비교 로직<br>- 자동 동기화 스크립트 |
| **성능 병목** (대용량 백테스트) | 높음 | 중간 | - 조기 프로파일링<br>- 벡터화/병렬화<br>- 캐싱 전략 |
| **공유 라이브러리 버전 충돌** | 낮음 | 높음 | - Semantic versioning<br>- CI/CD 테스트<br>- 버전 고정 (pyproject.toml) |
| **TimescaleDB 용량 초과** | 중간 | 중간 | - 압축 정책 활성화<br>- 보존 정책 (2년)<br>- 모니터링 설정 |
| **최적화 시간 초과** | 높음 | 낮음 | - 타임아웃 설정<br>- 조기 종료 조건<br>- 진행률 추적 |
| **프로덕션 Redis 장애** | 낮음 | 높음 | - 읽기 전용 모드<br>- 자동 재시도<br>- DB 폴백 |

### 리스크 모니터링

**주간 리뷰**:
- 각 리스크의 현재 상태 평가
- 새로운 리스크 식별
- 완화 방안 효과성 검토

**조기 경보 지표**:
- 테스트 실패율 증가
- 빌드 시간 증가
- 메모리 사용량 증가
- API 응답 시간 증가

---

## 품질 보증 전략

### 코드 품질 관리

**자동화 도구**:
```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/psf/black
    rev: 23.9.1
    hooks:
      - id: black
        language_version: python3.11

  - repo: https://github.com/pycqa/isort
    rev: 5.12.0
    hooks:
      - id: isort

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.5.1
    hooks:
      - id: mypy
        additional_dependencies: [types-all]

  - repo: https://github.com/pycqa/flake8
    rev: 6.1.0
    hooks:
      - id: flake8
        args: [--max-line-length=100]
```

**CI/CD 파이프라인**:
```yaml
# .github/workflows/test.yml
name: Test

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install poetry
          poetry install

      - name: Run tests
        run: |
          poetry run pytest --cov=backtest_service --cov-report=xml

      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

### 테스트 전략

**테스트 피라미드**:
```
       /\
      /E2E\        (10% - 통합 테스트)
     /------\
    /Integr.\     (30% - 통합 테스트)
   /----------\
  /   Unit     \   (60% - 단위 테스트)
 /--------------\
```

**커버리지 목표**:
- 전체: >80%
- 핵심 비즈니스 로직: >90%
- 유틸리티: >70%

---

## 배포 전략

### 배포 환경

**개발 환경** (Local):
- Docker Compose 사용
- 로컬 Redis 및 TimescaleDB
- 핫 리로드 활성화

**스테이징 환경** (Staging):
- 프로덕션과 동일한 인프라
- 프로덕션 데이터 스냅샷 사용
- 배포 전 검증

**프로덕션 환경** (Production):
- Docker Swarm 또는 Kubernetes
- 고가용성 설정
- 모니터링 및 알림

### 배포 프로세스

**Blue-Green 배포**:
```mermaid
graph LR
    A[Load Balancer] --> B[Blue v1.0]
    A -.-> C[Green v1.1 준비]
    C --> D[테스트 통과]
    D --> E[트래픽 전환]
    E --> F[Blue 종료]
```

**배포 체크리스트**:
- [ ] 코드 리뷰 완료
- [ ] 모든 테스트 통과
- [ ] 문서 업데이트
- [ ] 변경사항 로그 작성
- [ ] 스테이징 배포 및 검증
- [ ] 프로덕션 배포
- [ ] 헬스 체크 확인
- [ ] 모니터링 확인
- [ ] 롤백 계획 준비

### 롤백 전략

**자동 롤백 조건**:
- 헬스 체크 실패
- 에러율 >5%
- 응답 시간 >1초

**수동 롤백**:
```bash
# Docker Swarm
docker service update --rollback backtest-api

# Kubernetes
kubectl rollout undo deployment/backtest-api
```

---

## 모니터링 & 유지보수

### 모니터링 설정

**메트릭 수집** (Prometheus):
```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'backtest-api'
    static_configs:
      - targets: ['backtest-api:8001']
    metrics_path: '/metrics'
```

**대시보드** (Grafana):
- API 요청 수 및 응답 시간
- 백테스트 실행 횟수
- 데이터베이스 쿼리 시간
- 시스템 리소스 (CPU, 메모리, 디스크)

**알림 규칙**:
- API 에러율 >5%
- 응답 시간 >1초
- 디스크 사용량 >80%
- 메모리 사용량 >90%

### 로깅 전략

**구조화 로깅**:
```python
import structlog

logger = structlog.get_logger()

logger.info(
    "backtest_completed",
    backtest_id=backtest_id,
    strategy="HYPERRSI",
    symbol="BTC-USDT-SWAP",
    total_return=0.15,
    execution_time_seconds=8.5
)
```

**로그 레벨**:
- DEBUG: 개발 환경만
- INFO: 일반 작업 흐름
- WARNING: 비정상이지만 처리 가능
- ERROR: 에러 발생
- CRITICAL: 서비스 중단

### 유지보수 계획

**일일 작업**:
- [ ] 로그 모니터링
- [ ] 알림 확인
- [ ] 시스템 리소스 확인

**주간 작업**:
- [ ] 백테스트 결과 리뷰
- [ ] 데이터베이스 용량 확인
- [ ] 성능 메트릭 분석
- [ ] 보안 업데이트 확인

**월간 작업**:
- [ ] 데이터베이스 최적화 (VACUUM, REINDEX)
- [ ] 백업 검증
- [ ] 용량 계획 리뷰
- [ ] 문서 업데이트

**분기 작업**:
- [ ] 전체 시스템 감사
- [ ] 의존성 업데이트
- [ ] 보안 감사
- [ ] 성능 벤치마크

---

## 마일스톤 요약

| Phase | 기간 | 주요 산출물 | 완료 기준 |
|-------|------|------------|-----------|
| **Phase 1** | Weeks 1-2 | - 저장소 설정<br>- 공유 라이브러리<br>- 데이터베이스<br>- 기본 API | - 모든 저장소 설정 완료<br>- trading-strategy-core 패키지 빌드 성공<br>- TimescaleDB 테이블 생성 완료<br>- Health API 200 OK |
| **Phase 2** | Weeks 3-4 | - DataLoader<br>- StrategyRunner<br>- PositionTracker<br>- BacktestEngine | - 백테스트 E2E 실행 성공<br>- 단위 테스트 통과<br>- API 엔드포인트 동작 |
| **Phase 3** | Weeks 5-6 | - PerformanceAnalyzer<br>- 최적화 엔진<br>- ReportGenerator | - 15가지 메트릭 계산 성공<br>- Grid Search 100 조합 실행<br>- HTML 리포트 생성 |
| **Phase 4** | Weeks 7-8 | - 통합 테스트<br>- 성능 최적화<br>- Docker 배포<br>- 문서 | - 테스트 커버리지 >80%<br>- Docker 컨테이너 실행 성공<br>- 전체 문서 완성 |

---

## 다음 단계

1. ✅ **Phase 1 시작**: 저장소 설정 및 공유 라이브러리 추출
2. ⏳ **Phase 2**: 코어 엔진 개발
3. ⏳ **Phase 3**: 최적화 & 리포팅
4. ⏳ **Phase 4**: 테스트 & 배포

**시작 준비 사항**:
- [ ] GitHub/GitLab 계정 준비
- [ ] Docker 및 Docker Compose 설치
- [ ] Python 3.11+ 및 Poetry 설치
- [ ] Redis 및 TimescaleDB 접근 권한 확인
- [ ] 개발 환경 설정 (.env 파일)

**문의 및 지원**:
- 기술 문의: [이메일]
- 버그 리포트: GitHub Issues
- 기능 제안: GitHub Discussions

---

**문서 버전**: 1.0
**작성일**: 2025-01-31
**최종 수정일**: 2025-01-31
**작성자**: TradingBoost Team
