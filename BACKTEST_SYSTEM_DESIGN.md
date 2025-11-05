# TradingBoost 백테스팅 시스템 설계 및 구축 가이드

## 📑 목차

1. [개요](#1-개요)
2. [현재 시스템 분석](#2-현재-시스템-분석)
3. [아키텍처 설계](#3-아키텍처-설계)
4. [데이터 인프라](#4-데이터-인프라)
5. [백테스팅 엔진](#5-백테스팅-엔진)
6. [API 설계](#6-api-설계)
7. [구현 단계별 가이드](#7-구현-단계별-가이드)
8. [성능 최적화](#8-성능-최적화)
9. [테스트 전략](#9-테스트-전략)
10. [배포 및 운영](#10-배포-및-운영)

---

## 1. 개요

### 1.1 목적

TradingBoost HYPERRSI 전략에 대한 백테스팅 시스템 구축으로 다음을 달성:
- 과거 데이터 기반 전략 성능 검증
- 다양한 파라미터 조합 테스트
- 리스크/수익 분석
- 전략 최적화 기반 제공

### 1.2 핵심 요구사항

#### 기능적 요구사항
- ✅ HYPERRSI 전략 로직 시뮬레이션
- ✅ 과거 데이터 기반 백테스팅
- ✅ 다양한 타임프레임 지원 (1m, 3m, 5m, 15m, 30m, 1h, 4h)
- ✅ 실시간 진행 상황 모니터링
- ✅ 상세한 거래 내역 및 통계 제공
- ✅ 파라미터 최적화 기능

#### 비기능적 요구사항
- ✅ 마이크로서비스 아키텍처 (독립 배포)
- ✅ 확장 가능한 데이터 저장소
- ✅ 빠른 백테스팅 속도 (1일치 데이터 < 10초)
- ✅ 실거래 시스템과의 격리

### 1.3 기술 스택

```yaml
Language: Python 3.9+
Framework: FastAPI
Database:
  - TimescaleDB (시계열 데이터)
  - Redis (캐싱)
Data Processing: pandas, numpy
Async: asyncio, aioredis
Testing: pytest, pytest-asyncio
```

---

## 2. 현재 시스템 분석

### 2.1 데이터 소스 현황

#### 2.1.1 Redis 데이터 구조

**기본 캔들 데이터**
```python
# Key 패턴
candles:{symbol}:{timeframe}

# 예시
"candles:BTC-USDT-SWAP:1m"

# 데이터 구조 (CSV 형식 리스트)
[
    "1704067200,45000.5,45100.0,44950.0,45050.0,1234.56",
    "1704067260,45050.0,45150.0,45000.0,45100.0,987.65",
    ...
]

# 필드: timestamp,open,high,low,close,volume
```

**인디케이터 포함 캔들 데이터**
```python
# Key 패턴
candles_with_indicators:{symbol}:{timeframe}

# 예시
"candles_with_indicators:BTC-USDT-SWAP:1m"

# 데이터 구조 (JSON 형식 리스트)
[
    {
        "timestamp": 1704067200,
        "open": 45000.5,
        "high": 45100.0,
        "low": 44950.0,
        "close": 45050.0,
        "volume": 1234.56,
        "rsi": 65.5,
        "atr": 125.3,
        "ema": 44980.2,
        "bollinger_upper": 45200.0,
        "bollinger_lower": 44800.0,
        "human_time": "2025-01-01 00:00:00",
        "human_time_kr": "2025-01-01 09:00:00"
    },
    ...
]
```

**현재 진행 캔들**
```python
# Key 패턴
current_candle:{symbol}:{timeframe}
current_candle_with_indicators:{symbol}:{timeframe}

# 실시간 업데이트되는 미완성 캔들
```

**최신 캔들**
```python
# Key 패턴
latest:{symbol}:{timeframe}
latest_with_indicators:{symbol}:{timeframe}

# 가장 최근 완성된 캔들 (빠른 조회용)
```

#### 2.1.2 현재 데이터 제약사항

| 항목 | 현황 | 백테스팅 영향 |
|------|------|--------------|
| **보관 기간** | 최대 3000개 캔들 | 1분봉 기준 약 2일치만 백테스팅 가능 |
| **지원 심볼** | BTC, ETH, SOL | 제한적 |
| **지원 타임프레임** | 7개 (1m~4h) | 충분 |
| **인디케이터** | RSI, ATR, EMA, Bollinger | HYPERRSI 전략에 충분 |
| **데이터 갭** | 가능성 있음 | 백테스팅 정확도 저하 |

### 2.2 HYPERRSI 전략 로직 분석

#### 2.2.1 핵심 실행 흐름

```python
# execute_trading_logic.py 주요 흐름

1. 초기화
   ├── 사용자 설정 로드 (Redis)
   ├── OKX API 연결
   └── Redis 연결 확인

2. 포지션 체크
   ├── 현재 포지션 조회
   └── 분기 처리

3. 포지션 없음 (handle_no_position)
   ├── RSI 신호 확인
   ├── 트렌드 상태 분석
   ├── 진입 조건 확인
   └── 주문 실행

4. 포지션 있음 (handle_existing_position)
   ├── TP/SL 체크
   ├── 트레일링 스탑 업데이트
   ├── 피라미딩 조건 확인
   └── 청산/추가 진입 실행

5. 주문 모니터링
   ├── 미체결 주문 확인
   ├── 체결 확인
   └── Redis 상태 업데이트
```

#### 2.2.2 주요 설정 파라미터

```python
# 사용자 설정 (Redis: user:{user_id}:settings)
{
    # 기본 설정
    "symbol": "BTC-USDT-SWAP",
    "timeframe": "1m",
    "leverage": 10,
    "btc_investment": 20,
    "eth_investment": 10,
    "sol_investment": 10,

    # RSI 설정
    "entry_option": "rsi_trend",  # "rsi_only", "rsi_trend"
    "rsi_oversold": 30,
    "rsi_overbought": 70,

    # 트렌드 설정
    "trend_timeframe": "1m",  # 트렌드 분석 타임프레임

    # TP/SL 설정
    "tp_sl_option": "dynamic_atr",  # "fixed", "dynamic_atr"
    "stop_loss_percent": 2.0,
    "take_profit_percent": 4.0,
    "trailing_stop_enabled": true,
    "trailing_stop_callback": 1.0,

    # 피라미딩 설정
    "pyramiding_enabled": false,
    "pyramiding_type": "average_down",
    "max_pyramiding_count": 3,

    # 방향 설정
    "direction": "both",  # "long", "short", "both"

    # 듀얼 사이드 설정
    "dual_side_enabled": false,
    "dual_side_hedge_ratio": 0.5
}
```

#### 2.2.3 진입/청산 조건

**롱 포지션 진입 조건**
```python
# 조건 1: RSI Only
if entry_option == "rsi_only":
    if rsi < rsi_oversold:
        → 롱 진입

# 조건 2: RSI + Trend
if entry_option == "rsi_trend":
    if rsi < rsi_oversold and trend_state == "bullish":
        → 롱 진입
```

**숏 포지션 진입 조건**
```python
# 조건 1: RSI Only
if entry_option == "rsi_only":
    if rsi > rsi_overbought:
        → 숏 진입

# 조건 2: RSI + Trend
if entry_option == "rsi_trend":
    if rsi > rsi_overbought and trend_state == "bearish":
        → 숏 진입
```

**청산 조건**
```python
# 1. Take Profit 도달
if tp_sl_option == "fixed":
    tp_price = entry_price * (1 + take_profit_percent / 100)
elif tp_sl_option == "dynamic_atr":
    tp_price = entry_price + (atr * atr_multiplier)

# 2. Stop Loss 도달
if tp_sl_option == "fixed":
    sl_price = entry_price * (1 - stop_loss_percent / 100)
elif tp_sl_option == "dynamic_atr":
    sl_price = entry_price - (atr * atr_multiplier)

# 3. Trailing Stop
if trailing_stop_enabled:
    if unrealized_pnl > trailing_stop_activation:
        trailing_stop_price = current_price * (1 - trailing_stop_callback / 100)
```

### 2.3 기존 모듈 재사용 계획

#### 2.3.1 재사용 가능한 모듈

```python
# 1. 인디케이터 계산
from shared.indicators import (
    calc_rsi,
    calc_atr,
    calc_ema,
    calc_bollinger_bands,
    compute_all_indicators
)

# 2. 트렌드 분석
from HYPERRSI.src.api.trading.Calculate_signal import TrendStateCalculator

# 3. 설정 관리
from shared.constants.default_settings import (
    DEFAULT_PARAMS_SETTINGS,
    SETTINGS_CONSTRAINTS
)

# 4. 로깅
from shared.logging import get_logger

# 5. Redis 패턴
from shared.database.redis_patterns import RedisTimeout, RedisTTL
```

#### 2.3.2 포팅이 필요한 로직

```python
# 1. 포지션 핸들러 (시뮬레이션용 수정 필요)
HYPERRSI/src/trading/utils/position_handler.py
├── handle_no_position()      → BacktestPositionHandler.check_entry()
└── handle_existing_position() → BacktestPositionHandler.check_exit()

# 2. TP/SL 계산기 (그대로 재사용 가능)
HYPERRSI/src/trading/modules/tp_sl_calculator.py
└── TPSLCalculator → 백테스팅에서 그대로 사용

# 3. 시장 데이터 서비스 (데이터 소스만 변경)
HYPERRSI/src/trading/modules/market_data_service.py
└── get_current_price() → BacktestDataProvider.get_candle()
```

---

## 3. 아키텍처 설계

### 3.1 전체 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                     TradingBoost Platform                    │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   HYPERRSI   │  │     GRID     │  │   BACKTEST   │      │
│  │   (8000)     │  │    (8012)    │  │    (8013)    │      │
│  │              │  │              │  │              │      │
│  │ - 실거래     │  │ - 그리드     │  │ - 백테스팅   │      │
│  │ - 실시간     │  │ - 실시간     │  │ - 전략 검증  │      │
│  │ - 주문 실행  │  │ - 주문 실행  │  │ - 최적화     │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│         │                 │                   │              │
│         └─────────────────┴───────────────────┘              │
│                           │                                  │
│  ┌────────────────────────┴──────────────────────┐          │
│  │             Shared Infrastructure              │          │
│  ├────────────────────────────────────────────────┤          │
│  │ - Config (shared/config.py)                    │          │
│  │ - Database (shared/database/)                  │          │
│  │ - Indicators (shared/indicators.py)            │          │
│  │ - Logging (shared/logging/)                    │          │
│  │ - Utils (shared/utils/)                        │          │
│  └────────────────────────────────────────────────┘          │
│                           │                                  │
│  ┌────────────────────────┴──────────────────────┐          │
│  │              Data Layer                        │          │
│  ├────────────────────────────────────────────────┤          │
│  │                                                │          │
│  │  ┌──────────────┐         ┌──────────────┐   │          │
│  │  │ TimescaleDB  │         │    Redis     │   │          │
│  │  │              │         │              │   │          │
│  │  │ - Users      │         │ - Settings   │   │          │
│  │  │ - API Keys   │         │ - Candles    │   │          │
│  │  │ - Candles ★  │         │ - Cache      │   │          │
│  │  │ - Backtest   │         │ - Sessions   │   │          │
│  │  │   Results    │         │              │   │          │
│  │  └──────────────┘         └──────────────┘   │          │
│  │                                                │          │
│  └────────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────┘

★ = 새로 추가되는 테이블
```

### 3.2 백테스팅 서비스 아키텍처

```
BACKTEST/
├── main.py                      # FastAPI 앱 진입점
├── config.py                    # 백테스팅 전용 설정
├── requirements.txt             # 독립 의존성
│
├── api/                         # API Layer
│   ├── __init__.py
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── backtest.py          # 백테스트 실행 API
│   │   ├── results.py           # 결과 조회 API
│   │   └── optimization.py      # 최적화 API
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── request.py           # 요청 스키마
│   │   └── response.py          # 응답 스키마
│   └── dependencies.py          # API 의존성
│
├── engine/                      # Backtest Engine
│   ├── __init__.py
│   ├── backtest_engine.py       # 메인 엔진
│   ├── position_manager.py      # 포지션 관리 (시뮬레이션)
│   ├── order_simulator.py       # 주문 시뮬레이터
│   ├── balance_tracker.py       # 잔고 추적
│   └── event_logger.py          # 이벤트 로깅
│
├── strategies/                  # Strategy Layer
│   ├── __init__.py
│   ├── base_strategy.py         # 전략 베이스 클래스
│   ├── hyperrsi_strategy.py     # HYPERRSI 전략 (포팅)
│   ├── signal_generator.py      # 시그널 생성
│   └── tp_sl_manager.py         # TP/SL 관리
│
├── data/                        # Data Layer
│   ├── __init__.py
│   ├── data_provider.py         # 데이터 제공자 (추상화)
│   ├── timescale_provider.py    # TimescaleDB 데이터 소스
│   ├── redis_provider.py        # Redis 데이터 소스
│   ├── okx_provider.py          # OKX API 데이터 소스
│   └── data_validator.py        # 데이터 검증
│
├── analysis/                    # Analysis Layer
│   ├── __init__.py
│   ├── metrics_calculator.py    # 성능 지표 계산
│   ├── risk_analyzer.py         # 리스크 분석
│   ├── trade_analyzer.py        # 거래 분석
│   └── report_generator.py      # 리포트 생성
│
├── optimization/                # Optimization Layer
│   ├── __init__.py
│   ├── parameter_optimizer.py   # 파라미터 최적화
│   ├── grid_search.py           # 그리드 서치
│   └── genetic_algorithm.py     # 유전 알고리즘 (선택적)
│
├── models/                      # Data Models
│   ├── __init__.py
│   ├── backtest.py              # 백테스트 모델
│   ├── position.py              # 포지션 모델
│   ├── trade.py                 # 거래 모델
│   └── result.py                # 결과 모델
│
└── tests/                       # Tests
    ├── __init__.py
    ├── test_engine.py
    ├── test_strategies.py
    ├── test_data.py
    └── fixtures/
```

### 3.3 데이터 플로우

```
1. 백테스트 요청
   ┌─────────────┐
   │   Client    │
   │  (Frontend) │
   └──────┬──────┘
          │ POST /backtest/run
          ▼
   ┌─────────────┐
   │  FastAPI    │
   │   Routes    │
   └──────┬──────┘
          │ validate request
          ▼
   ┌─────────────┐
   │  Backtest   │
   │   Engine    │
   └──────┬──────┘
          │
          ├─────────────────────────────────┐
          │                                 │
          ▼                                 ▼
   ┌─────────────┐                  ┌─────────────┐
   │    Data     │                  │  Strategy   │
   │  Provider   │                  │   Module    │
   └──────┬──────┘                  └──────┬──────┘
          │                                 │
          │ get_candles()                   │ check_signals()
          ▼                                 │
   ┌─────────────┐                         │
   │ TimescaleDB │◄────────────────────────┘
   │   / Redis   │    store positions/trades
   └─────────────┘
          │
          │ return candles
          ▼
   ┌─────────────┐
   │  Analysis   │
   │   Module    │
   └──────┬──────┘
          │ calculate metrics
          ▼
   ┌─────────────┐
   │   Result    │
   │  Generator  │
   └──────┬──────┘
          │
          ▼
   ┌─────────────┐
   │   Client    │
   └─────────────┘

2. 실시간 진행 상황 (WebSocket)
   ┌─────────────┐
   │  Backtest   │
   │   Engine    │
   └──────┬──────┘
          │ emit events
          ▼
   ┌─────────────┐
   │  WebSocket  │
   │   Server    │
   └──────┬──────┘
          │
          ▼
   ┌─────────────┐
   │   Client    │
   │ (실시간 업데이트)│
   └─────────────┘
```

### 3.4 마이크로서비스 통신

```
┌──────────────────────────────────────────────────────────┐
│                    Service Communication                  │
├──────────────────────────────────────────────────────────┤
│                                                           │
│  HYPERRSI (8000)           BACKTEST (8013)               │
│  ┌────────────┐            ┌────────────┐               │
│  │  Settings  │───────────▶│  Settings  │               │
│  │   Redis    │  Read-Only │  Consumer  │               │
│  └────────────┘            └────────────┘               │
│       │                          │                       │
│       │                          │                       │
│       ▼                          ▼                       │
│  ┌─────────────────────────────────────┐                │
│  │        Shared Redis (DB 0)          │                │
│  │  - user:{id}:settings               │                │
│  │  - candles_with_indicators:*        │                │
│  └─────────────────────────────────────┘                │
│       │                          │                       │
│       ▼                          ▼                       │
│  ┌─────────────────────────────────────┐                │
│  │       TimescaleDB (Shared)          │                │
│  │  - app_users                        │                │
│  │  - okx_api_info                     │                │
│  │  - candle_history (NEW)             │                │
│  │  - backtest_results (NEW)           │                │
│  └─────────────────────────────────────┘                │
│                                                           │
│  통신 방식:                                              │
│  - Shared Database (권장)                               │
│  - REST API (필요시)                                    │
│  - Redis Pub/Sub (실시간 알림)                          │
│                                                           │
└──────────────────────────────────────────────────────────┘
```

---

## 4. 데이터 인프라

### 4.1 TimescaleDB 스키마 설계

#### 4.1.1 캔들 히스토리 테이블

```sql
-- ============================================
-- 캔들 히스토리 테이블 (시계열 데이터)
-- ============================================

CREATE TABLE candle_history (
    timestamp TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,

    -- OHLCV 데이터
    open NUMERIC(20, 8) NOT NULL,
    high NUMERIC(20, 8) NOT NULL,
    low NUMERIC(20, 8) NOT NULL,
    close NUMERIC(20, 8) NOT NULL,
    volume NUMERIC(20, 8) NOT NULL,

    -- 인디케이터
    rsi NUMERIC(10, 2),
    atr NUMERIC(20, 8),
    ema NUMERIC(20, 8),
    sma NUMERIC(20, 8),
    bollinger_upper NUMERIC(20, 8),
    bollinger_middle NUMERIC(20, 8),
    bollinger_lower NUMERIC(20, 8),

    -- 트렌드 지표 (추가 가능)
    macd NUMERIC(20, 8),
    macd_signal NUMERIC(20, 8),
    macd_histogram NUMERIC(20, 8),

    -- 메타데이터
    data_source VARCHAR(20) DEFAULT 'okx',  -- okx, binance, etc
    is_complete BOOLEAN DEFAULT true,       -- 완성된 캔들 여부
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- 기본키: 심볼 + 타임프레임 + 타임스탬프
    PRIMARY KEY (symbol, timeframe, timestamp)
);

-- TimescaleDB Hypertable 변환 (시계열 최적화)
SELECT create_hypertable(
    'candle_history',
    'timestamp',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

-- 인덱스 생성
CREATE INDEX idx_candle_symbol_timeframe
ON candle_history (symbol, timeframe, timestamp DESC);

CREATE INDEX idx_candle_timestamp
ON candle_history (timestamp DESC);

-- 데이터 보관 정책 (1년 이상 데이터 자동 삭제)
SELECT add_retention_policy(
    'candle_history',
    INTERVAL '1 year',
    if_not_exists => TRUE
);

-- 압축 정책 (7일 이상된 데이터 압축)
ALTER TABLE candle_history SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol,timeframe'
);

SELECT add_compression_policy(
    'candle_history',
    INTERVAL '7 days',
    if_not_exists => TRUE
);

-- 샘플 데이터 조회 쿼리
SELECT
    timestamp,
    symbol,
    timeframe,
    open,
    high,
    low,
    close,
    volume,
    rsi,
    atr
FROM candle_history
WHERE symbol = 'BTC-USDT-SWAP'
    AND timeframe = '1m'
    AND timestamp BETWEEN '2025-01-01' AND '2025-01-31'
ORDER BY timestamp DESC
LIMIT 100;
```

#### 4.1.2 백테스트 결과 테이블

```sql
-- ============================================
-- 백테스트 실행 기록
-- ============================================

CREATE TABLE backtest_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app_users(id),

    -- 백테스트 설정
    symbol VARCHAR(50) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    start_date TIMESTAMPTZ NOT NULL,
    end_date TIMESTAMPTZ NOT NULL,

    -- 전략 설정 (JSONB로 유연하게 저장)
    strategy_name VARCHAR(50) DEFAULT 'hyperrsi',
    strategy_params JSONB NOT NULL,

    -- 실행 상태
    status VARCHAR(20) DEFAULT 'pending',  -- pending, running, completed, failed
    progress NUMERIC(5, 2) DEFAULT 0.0,

    -- 실행 시간
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    execution_time_seconds NUMERIC(10, 2),

    -- 결과 요약 (빠른 조회용)
    total_trades INTEGER,
    winning_trades INTEGER,
    losing_trades INTEGER,
    total_return_percent NUMERIC(10, 2),
    max_drawdown_percent NUMERIC(10, 2),
    sharpe_ratio NUMERIC(10, 4),
    win_rate NUMERIC(5, 2),

    -- 상세 결과 (JSONB)
    detailed_metrics JSONB,

    -- 에러 정보
    error_message TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_backtest_user ON backtest_runs(user_id, created_at DESC);
CREATE INDEX idx_backtest_status ON backtest_runs(status);
CREATE INDEX idx_backtest_symbol ON backtest_runs(symbol, timeframe);

-- ============================================
-- 백테스트 거래 내역
-- ============================================

CREATE TABLE backtest_trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    backtest_run_id UUID NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,

    -- 거래 정보
    trade_number INTEGER NOT NULL,
    side VARCHAR(10) NOT NULL,  -- long, short

    -- 진입
    entry_timestamp TIMESTAMPTZ NOT NULL,
    entry_price NUMERIC(20, 8) NOT NULL,
    entry_reason VARCHAR(100),

    -- 청산
    exit_timestamp TIMESTAMPTZ,
    exit_price NUMERIC(20, 8),
    exit_reason VARCHAR(100),  -- take_profit, stop_loss, trailing_stop, signal

    -- 수량 및 손익
    quantity NUMERIC(20, 8) NOT NULL,
    leverage NUMERIC(5, 2) NOT NULL,

    pnl NUMERIC(20, 8),
    pnl_percent NUMERIC(10, 4),

    -- 수수료
    entry_fee NUMERIC(20, 8) DEFAULT 0,
    exit_fee NUMERIC(20, 8) DEFAULT 0,

    -- TP/SL 레벨
    take_profit_price NUMERIC(20, 8),
    stop_loss_price NUMERIC(20, 8),
    trailing_stop_price NUMERIC(20, 8),

    -- 진입 시점의 지표값
    entry_rsi NUMERIC(10, 2),
    entry_atr NUMERIC(20, 8),

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_btrade_run ON backtest_trades(backtest_run_id, trade_number);
CREATE INDEX idx_btrade_timestamp ON backtest_trades(entry_timestamp);

-- ============================================
-- 백테스트 잔고 스냅샷 (Equity Curve 데이터)
-- ============================================

CREATE TABLE backtest_balance_snapshots (
    id BIGSERIAL PRIMARY KEY,
    backtest_run_id UUID NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,

    timestamp TIMESTAMPTZ NOT NULL,
    balance NUMERIC(20, 8) NOT NULL,
    equity NUMERIC(20, 8) NOT NULL,  -- balance + unrealized PNL

    -- 포지션 정보
    position_side VARCHAR(10),  -- NULL if no position
    position_size NUMERIC(20, 8),
    unrealized_pnl NUMERIC(20, 8) DEFAULT 0,

    -- 누적 통계
    cumulative_pnl NUMERIC(20, 8),
    cumulative_trades INTEGER DEFAULT 0,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_balance_run ON backtest_balance_snapshots(backtest_run_id, timestamp);

-- TimescaleDB Hypertable 변환 (대량 스냅샷 데이터 최적화)
SELECT create_hypertable(
    'backtest_balance_snapshots',
    'timestamp',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists => TRUE
);
```

#### 4.1.3 유용한 쿼리 모음

```sql
-- ============================================
-- 1. 백테스트 실행 결과 조회
-- ============================================

-- 최근 백테스트 목록 (사용자별)
SELECT
    id,
    symbol,
    timeframe,
    start_date,
    end_date,
    status,
    total_return_percent,
    win_rate,
    total_trades,
    created_at
FROM backtest_runs
WHERE user_id = 'your-user-id'
ORDER BY created_at DESC
LIMIT 20;

-- 특정 백테스트 상세 정보
SELECT
    br.*,
    COUNT(bt.id) as trade_count,
    AVG(bt.pnl_percent) as avg_pnl_percent,
    MAX(bt.pnl_percent) as max_win_percent,
    MIN(bt.pnl_percent) as max_loss_percent
FROM backtest_runs br
LEFT JOIN backtest_trades bt ON bt.backtest_run_id = br.id
WHERE br.id = 'backtest-id'
GROUP BY br.id;

-- ============================================
-- 2. 거래 내역 분석
-- ============================================

-- 승률 높은 진입 조건 분석
SELECT
    entry_reason,
    COUNT(*) as total_trades,
    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
    ROUND(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100, 2) as win_rate,
    ROUND(AVG(pnl_percent), 2) as avg_pnl_percent
FROM backtest_trades
WHERE backtest_run_id = 'backtest-id'
GROUP BY entry_reason
ORDER BY win_rate DESC;

-- 롱 vs 숏 성과 비교
SELECT
    side,
    COUNT(*) as trades,
    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
    ROUND(AVG(pnl_percent), 2) as avg_return,
    ROUND(SUM(pnl), 2) as total_pnl
FROM backtest_trades
WHERE backtest_run_id = 'backtest-id'
GROUP BY side;

-- ============================================
-- 3. 캔들 데이터 조회
-- ============================================

-- 특정 기간 캔들 데이터 (인디케이터 포함)
SELECT
    timestamp,
    open,
    high,
    low,
    close,
    volume,
    rsi,
    atr,
    bollinger_upper,
    bollinger_lower
FROM candle_history
WHERE symbol = 'BTC-USDT-SWAP'
    AND timeframe = '1m'
    AND timestamp BETWEEN '2025-01-01' AND '2025-01-02'
ORDER BY timestamp ASC;

-- 데이터 갭 확인
WITH candle_gaps AS (
    SELECT
        timestamp,
        LEAD(timestamp) OVER (ORDER BY timestamp) as next_timestamp,
        EXTRACT(EPOCH FROM (LEAD(timestamp) OVER (ORDER BY timestamp) - timestamp)) / 60 as gap_minutes
    FROM candle_history
    WHERE symbol = 'BTC-USDT-SWAP'
        AND timeframe = '1m'
        AND timestamp BETWEEN '2025-01-01' AND '2025-01-02'
)
SELECT
    timestamp,
    next_timestamp,
    gap_minutes
FROM candle_gaps
WHERE gap_minutes > 1  -- 1분 이상 갭
ORDER BY gap_minutes DESC;

-- ============================================
-- 4. 성능 통계
-- ============================================

-- Equity Curve (잔고 변화)
SELECT
    timestamp,
    equity,
    cumulative_pnl,
    cumulative_trades
FROM backtest_balance_snapshots
WHERE backtest_run_id = 'backtest-id'
ORDER BY timestamp ASC;

-- 최대 낙폭 (Max Drawdown) 계산
WITH equity_high AS (
    SELECT
        timestamp,
        equity,
        MAX(equity) OVER (ORDER BY timestamp) as running_max
    FROM backtest_balance_snapshots
    WHERE backtest_run_id = 'backtest-id'
)
SELECT
    MAX((running_max - equity) / running_max * 100) as max_drawdown_percent
FROM equity_high;
```

### 4.2 데이터 마이그레이션 전략

#### 4.2.1 Redis → TimescaleDB 마이그레이션

```python
# BACKTEST/data/migration/redis_to_timescale.py

import asyncio
import json
from datetime import datetime
from typing import List, Dict, Any

from redis.asyncio import Redis
from shared.database.redis import get_redis
from shared.logging import get_logger
from BACKTEST.data.timescale_provider import TimescaleProvider

logger = get_logger(__name__)

class CandleMigration:
    """Redis의 캔들 데이터를 TimescaleDB로 마이그레이션"""

    SYMBOLS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]
    TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "4h"]

    def __init__(self):
        self.redis: Redis = None
        self.timescale = TimescaleProvider()

    async def migrate_all(self):
        """모든 심볼 및 타임프레임 데이터 마이그레이션"""
        try:
            self.redis = await get_redis()

            total_migrated = 0

            for symbol in self.SYMBOLS:
                for timeframe in self.TIMEFRAMES:
                    logger.info(f"마이그레이션 시작: {symbol} {timeframe}")

                    count = await self._migrate_symbol_timeframe(symbol, timeframe)
                    total_migrated += count

                    logger.info(f"마이그레이션 완료: {symbol} {timeframe} - {count}개 캔들")

            logger.info(f"전체 마이그레이션 완료: 총 {total_migrated}개 캔들")

        except Exception as e:
            logger.error(f"마이그레이션 실패: {e}", exc_info=True)
            raise
        finally:
            if self.redis:
                await self.redis.close()

    async def _migrate_symbol_timeframe(self, symbol: str, timeframe: str) -> int:
        """특정 심볼/타임프레임 데이터 마이그레이션"""

        # Redis 키
        key = f"candles_with_indicators:{symbol}:{timeframe}"

        try:
            # Redis에서 모든 캔들 데이터 가져오기
            raw_candles = await self.redis.lrange(key, 0, -1)

            if not raw_candles:
                logger.warning(f"데이터 없음: {symbol} {timeframe}")
                return 0

            # JSON 파싱
            candles = []
            for raw in raw_candles:
                try:
                    candle = json.loads(raw)
                    candles.append(self._transform_candle(candle, symbol, timeframe))
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON 파싱 실패: {e}")
                    continue

            # TimescaleDB에 배치 삽입
            if candles:
                await self.timescale.batch_insert_candles(candles)

            return len(candles)

        except Exception as e:
            logger.error(f"마이그레이션 오류: {symbol} {timeframe} - {e}")
            raise

    def _transform_candle(self, candle: Dict[str, Any], symbol: str, timeframe: str) -> Dict[str, Any]:
        """Redis 캔들 데이터를 TimescaleDB 형식으로 변환"""

        return {
            "timestamp": datetime.fromtimestamp(candle["timestamp"]),
            "symbol": symbol,
            "timeframe": timeframe,
            "open": float(candle["open"]),
            "high": float(candle["high"]),
            "low": float(candle["low"]),
            "close": float(candle["close"]),
            "volume": float(candle["volume"]),
            "rsi": float(candle.get("rsi")) if candle.get("rsi") is not None else None,
            "atr": float(candle.get("atr")) if candle.get("atr") is not None else None,
            "ema": float(candle.get("ema")) if candle.get("ema") is not None else None,
            "bollinger_upper": float(candle.get("bollinger_upper")) if candle.get("bollinger_upper") is not None else None,
            "bollinger_middle": float(candle.get("bollinger_middle")) if candle.get("bollinger_middle") is not None else None,
            "bollinger_lower": float(candle.get("bollinger_lower")) if candle.get("bollinger_lower") is not None else None,
            "data_source": "redis",
            "is_complete": not candle.get("is_current", False)
        }


# 실행 스크립트
async def main():
    migration = CandleMigration()
    await migration.migrate_all()

if __name__ == "__main__":
    asyncio.run(main())
```

#### 4.2.2 OKX API를 통한 히스토리 데이터 수집

```python
# BACKTEST/data/migration/okx_historical_fetch.py

import asyncio
import ccxt.async_support as ccxt
from datetime import datetime, timedelta
from typing import List, Dict, Any

from shared.logging import get_logger
from shared.indicators import compute_all_indicators
from BACKTEST.data.timescale_provider import TimescaleProvider

logger = get_logger(__name__)

class HistoricalDataFetcher:
    """OKX API를 통해 과거 데이터 수집"""

    def __init__(self, api_key: str, secret: str, passphrase: str):
        self.exchange = ccxt.okx({
            'apiKey': api_key,
            'secret': secret,
            'password': passphrase,
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        self.timescale = TimescaleProvider()

    async def fetch_historical_data(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime
    ) -> int:
        """
        과거 데이터 수집 및 저장

        Args:
            symbol: 거래 심볼 (예: BTC-USDT-SWAP)
            timeframe: 타임프레임 (예: 1m, 5m, 1h)
            start_date: 시작 날짜
            end_date: 종료 날짜

        Returns:
            수집된 캔들 개수
        """
        try:
            logger.info(f"히스토리 데이터 수집 시작: {symbol} {timeframe} ({start_date} ~ {end_date})")

            # OKX API 제한: 한 번에 최대 300개 캔들
            batch_size = 300
            current_date = start_date
            total_candles = 0

            while current_date < end_date:
                # 배치 수집
                candles = await self._fetch_batch(
                    symbol,
                    timeframe,
                    current_date,
                    batch_size
                )

                if not candles:
                    break

                # 인디케이터 계산
                candles_with_indicators = compute_all_indicators(
                    candles,
                    rsi_period=14,
                    atr_period=14
                )

                # TimescaleDB에 저장
                await self._save_candles(
                    candles_with_indicators,
                    symbol,
                    timeframe
                )

                total_candles += len(candles)

                # 다음 배치를 위한 시간 업데이트
                last_timestamp = candles[-1]["timestamp"]
                current_date = datetime.fromtimestamp(last_timestamp) + timedelta(minutes=1)

                # API rate limit 준수
                await asyncio.sleep(0.5)

                logger.info(f"진행 중: {symbol} {timeframe} - {total_candles}개 수집")

            logger.info(f"수집 완료: {symbol} {timeframe} - 총 {total_candles}개 캔들")
            return total_candles

        except Exception as e:
            logger.error(f"히스토리 데이터 수집 실패: {e}", exc_info=True)
            raise
        finally:
            await self.exchange.close()

    async def _fetch_batch(
        self,
        symbol: str,
        timeframe: str,
        since: datetime,
        limit: int
    ) -> List[Dict[str, Any]]:
        """배치 단위로 캔들 데이터 가져오기"""

        try:
            # OKX API 호출
            ohlcv = await self.exchange.fetch_ohlcv(
                symbol,
                timeframe=timeframe,
                since=int(since.timestamp() * 1000),
                limit=limit,
                params={'instType': 'SWAP'}
            )

            # 변환
            candles = []
            for row in ohlcv:
                timestamp, open_, high, low, close, volume = row

                candles.append({
                    "timestamp": timestamp // 1000,
                    "open": float(open_),
                    "high": float(high),
                    "low": float(low),
                    "close": float(close),
                    "volume": float(volume)
                })

            return candles

        except Exception as e:
            logger.error(f"배치 수집 실패: {e}")
            raise

    async def _save_candles(
        self,
        candles: List[Dict[str, Any]],
        symbol: str,
        timeframe: str
    ):
        """캔들 데이터를 TimescaleDB에 저장"""

        records = []
        for candle in candles:
            records.append({
                "timestamp": datetime.fromtimestamp(candle["timestamp"]),
                "symbol": symbol,
                "timeframe": timeframe,
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "volume": candle["volume"],
                "rsi": candle.get("rsi"),
                "atr": candle.get("atr"),
                "ema": candle.get("ema"),
                "bollinger_upper": candle.get("bollinger_upper"),
                "bollinger_middle": candle.get("bollinger_middle"),
                "bollinger_lower": candle.get("bollinger_lower"),
                "data_source": "okx",
                "is_complete": True
            })

        await self.timescale.batch_insert_candles(records)


# 실행 스크립트
async def main():
    """
    예시: BTC 1분봉 최근 30일 데이터 수집
    """
    from shared.config import get_settings

    settings = get_settings()

    fetcher = HistoricalDataFetcher(
        api_key=settings.OKX_API_KEY,
        secret=settings.OKX_SECRET_KEY,
        passphrase=settings.OKX_PASSPHRASE
    )

    # 최근 30일 데이터 수집
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)

    await fetcher.fetch_historical_data(
        symbol="BTC-USDT-SWAP",
        timeframe="1m",
        start_date=start_date,
        end_date=end_date
    )

if __name__ == "__main__":
    asyncio.run(main())
```

### 4.3 데이터 제공자 (Data Provider) 구현

```python
# BACKTEST/data/data_provider.py

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Dict, Any, Optional

from shared.logging import get_logger

logger = get_logger(__name__)

class DataProvider(ABC):
    """
    데이터 제공자 인터페이스

    백테스팅 엔진이 데이터 소스에 독립적으로 작동할 수 있도록
    추상화 계층 제공
    """

    @abstractmethod
    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        include_indicators: bool = True
    ) -> List[Dict[str, Any]]:
        """
        캔들 데이터 조회

        Args:
            symbol: 거래 심볼
            timeframe: 타임프레임
            start_date: 시작 날짜
            end_date: 종료 날짜
            include_indicators: 인디케이터 포함 여부

        Returns:
            캔들 데이터 리스트 (시간순 정렬)
        """
        pass

    @abstractmethod
    async def validate_data_availability(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """
        데이터 가용성 검증

        Returns:
            {
                "available": bool,
                "missing_ranges": List[Tuple[datetime, datetime]],
                "gaps": List[Dict],
                "total_candles": int
            }
        """
        pass
```

```python
# BACKTEST/data/timescale_provider.py

import asyncpg
from datetime import datetime
from typing import List, Dict, Any, Optional

from shared.database.session import get_timescale_pool
from shared.logging import get_logger
from BACKTEST.data.data_provider import DataProvider

logger = get_logger(__name__)

class TimescaleProvider(DataProvider):
    """TimescaleDB 데이터 제공자"""

    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        include_indicators: bool = True
    ) -> List[Dict[str, Any]]:
        """TimescaleDB에서 캔들 데이터 조회"""

        pool = await get_timescale_pool()

        query = """
            SELECT
                EXTRACT(EPOCH FROM timestamp)::BIGINT as timestamp,
                open,
                high,
                low,
                close,
                volume,
                rsi,
                atr,
                ema,
                bollinger_upper,
                bollinger_middle,
                bollinger_lower
            FROM candle_history
            WHERE symbol = $1
                AND timeframe = $2
                AND timestamp >= $3
                AND timestamp < $4
                AND is_complete = true
            ORDER BY timestamp ASC
        """

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, symbol, timeframe, start_date, end_date)

        candles = []
        for row in rows:
            candle = dict(row)

            # NULL 값 처리
            if not include_indicators:
                for key in ['rsi', 'atr', 'ema', 'bollinger_upper', 'bollinger_middle', 'bollinger_lower']:
                    candle.pop(key, None)

            candles.append(candle)

        logger.info(f"TimescaleDB에서 {len(candles)}개 캔들 조회: {symbol} {timeframe}")
        return candles

    async def validate_data_availability(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """데이터 가용성 검증"""

        pool = await get_timescale_pool()

        # 전체 캔들 수 확인
        count_query = """
            SELECT COUNT(*) as total
            FROM candle_history
            WHERE symbol = $1
                AND timeframe = $2
                AND timestamp >= $3
                AND timestamp < $4
                AND is_complete = true
        """

        # 갭 확인
        gap_query = """
            WITH candle_gaps AS (
                SELECT
                    timestamp,
                    LEAD(timestamp) OVER (ORDER BY timestamp) as next_timestamp,
                    EXTRACT(EPOCH FROM (LEAD(timestamp) OVER (ORDER BY timestamp) - timestamp)) / 60 as gap_minutes
                FROM candle_history
                WHERE symbol = $1
                    AND timeframe = $2
                    AND timestamp >= $3
                    AND timestamp < $4
                    AND is_complete = true
            )
            SELECT
                timestamp,
                next_timestamp,
                gap_minutes
            FROM candle_gaps
            WHERE gap_minutes > $5
            ORDER BY gap_minutes DESC
        """

        # 타임프레임별 예상 간격 (분 단위)
        expected_intervals = {
            "1m": 1, "3m": 3, "5m": 5, "15m": 15,
            "30m": 30, "1h": 60, "4h": 240
        }
        expected_interval = expected_intervals.get(timeframe, 1)

        async with pool.acquire() as conn:
            # 총 캔들 수
            total_result = await conn.fetchrow(count_query, symbol, timeframe, start_date, end_date)
            total_candles = total_result['total']

            # 갭 확인
            gap_rows = await conn.fetch(gap_query, symbol, timeframe, start_date, end_date, expected_interval * 1.5)

        gaps = [
            {
                "start": row['timestamp'],
                "end": row['next_timestamp'],
                "gap_minutes": row['gap_minutes']
            }
            for row in gap_rows
        ]

        # 데이터 충분한지 판단
        expected_candles = int((end_date - start_date).total_seconds() / 60 / expected_interval)
        coverage = (total_candles / expected_candles * 100) if expected_candles > 0 else 0

        return {
            "available": total_candles > 0 and coverage > 90,  # 90% 이상 커버리지 필요
            "total_candles": total_candles,
            "expected_candles": expected_candles,
            "coverage_percent": round(coverage, 2),
            "gaps": gaps,
            "gap_count": len(gaps)
        }

    async def batch_insert_candles(self, candles: List[Dict[str, Any]]):
        """캔들 데이터 배치 삽입"""

        if not candles:
            return

        pool = await get_timescale_pool()

        insert_query = """
            INSERT INTO candle_history (
                timestamp, symbol, timeframe,
                open, high, low, close, volume,
                rsi, atr, ema,
                bollinger_upper, bollinger_middle, bollinger_lower,
                data_source, is_complete
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
            ON CONFLICT (symbol, timeframe, timestamp) DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume,
                rsi = EXCLUDED.rsi,
                atr = EXCLUDED.atr,
                ema = EXCLUDED.ema,
                bollinger_upper = EXCLUDED.bollinger_upper,
                bollinger_middle = EXCLUDED.bollinger_middle,
                bollinger_lower = EXCLUDED.bollinger_lower,
                is_complete = EXCLUDED.is_complete
        """

        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(
                    insert_query,
                    [
                        (
                            candle["timestamp"],
                            candle["symbol"],
                            candle["timeframe"],
                            candle["open"],
                            candle["high"],
                            candle["low"],
                            candle["close"],
                            candle["volume"],
                            candle.get("rsi"),
                            candle.get("atr"),
                            candle.get("ema"),
                            candle.get("bollinger_upper"),
                            candle.get("bollinger_middle"),
                            candle.get("bollinger_lower"),
                            candle.get("data_source", "unknown"),
                            candle.get("is_complete", True)
                        )
                        for candle in candles
                    ]
                )

        logger.info(f"{len(candles)}개 캔들 데이터 삽입 완료")
```

---

## 5. 백테스팅 엔진

### 5.1 백테스팅 엔진 코어

```python
# BACKTEST/engine/backtest_engine.py

import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from shared.logging import get_logger
from BACKTEST.data.data_provider import DataProvider
from BACKTEST.strategies.hyperrsi_strategy import HyperRSIStrategy
from BACKTEST.engine.position_manager import PositionManager
from BACKTEST.engine.balance_tracker import BalanceTracker
from BACKTEST.models.backtest import BacktestConfig, BacktestResult
from BACKTEST.models.trade import Trade
from BACKTEST.analysis.metrics_calculator import MetricsCalculator

logger = get_logger(__name__)

@dataclass
class BacktestState:
    """백테스트 실행 상태"""
    current_timestamp: datetime = None
    current_candle_index: int = 0
    total_candles: int = 0
    is_running: bool = False
    progress_percent: float = 0.0

class BacktestEngine:
    """
    백테스팅 엔진 메인 클래스

    과거 데이터를 기반으로 전략을 시뮬레이션하고
    성능을 분석합니다.
    """

    def __init__(
        self,
        data_provider: DataProvider,
        strategy: HyperRSIStrategy,
        initial_balance: float = 10000.0
    ):
        self.data_provider = data_provider
        self.strategy = strategy
        self.initial_balance = initial_balance

        # 컴포넌트
        self.position_manager = PositionManager()
        self.balance_tracker = BalanceTracker(initial_balance)
        self.metrics_calculator = MetricsCalculator()

        # 상태
        self.state = BacktestState()

        # 결과 저장
        self.trades: List[Trade] = []
        self.balance_snapshots: List[Dict[str, Any]] = []

    async def run(self, config: BacktestConfig) -> BacktestResult:
        """
        백테스트 실행

        Args:
            config: 백테스트 설정

        Returns:
            BacktestResult: 백테스트 결과
        """
        try:
            logger.info(f"백테스트 시작: {config.symbol} {config.timeframe}")
            logger.info(f"기간: {config.start_date} ~ {config.end_date}")
            logger.info(f"초기 자본: {self.initial_balance} USDT")

            # 1. 데이터 로드
            candles = await self._load_data(config)

            if not candles:
                raise ValueError("캔들 데이터가 없습니다")

            # 2. 데이터 검증
            await self._validate_data(config, candles)

            # 3. 초기화
            self._initialize(config, candles)

            # 4. 백테스트 루프 실행
            await self._backtest_loop(candles, config)

            # 5. 결과 분석
            result = await self._analyze_results(config)

            logger.info(f"백테스트 완료: 총 {len(self.trades)}개 거래")
            logger.info(f"최종 수익률: {result.total_return_percent:.2f}%")

            return result

        except Exception as e:
            logger.error(f"백테스트 실행 중 오류: {e}", exc_info=True)
            raise
        finally:
            self.state.is_running = False

    async def _load_data(self, config: BacktestConfig) -> List[Dict[str, Any]]:
        """데이터 로드"""
        logger.info("캔들 데이터 로드 중...")

        candles = await self.data_provider.get_candles(
            symbol=config.symbol,
            timeframe=config.timeframe,
            start_date=config.start_date,
            end_date=config.end_date,
            include_indicators=True
        )

        logger.info(f"{len(candles)}개 캔들 로드 완료")
        return candles

    async def _validate_data(self, config: BacktestConfig, candles: List[Dict[str, Any]]):
        """데이터 검증"""
        logger.info("데이터 검증 중...")

        # 데이터 가용성 확인
        validation = await self.data_provider.validate_data_availability(
            symbol=config.symbol,
            timeframe=config.timeframe,
            start_date=config.start_date,
            end_date=config.end_date
        )

        if not validation["available"]:
            logger.warning(f"데이터 커버리지: {validation['coverage_percent']}%")
            logger.warning(f"데이터 갭: {validation['gap_count']}개")

            if validation['coverage_percent'] < 50:
                raise ValueError("데이터가 불충분합니다 (< 50% coverage)")

        # 인디케이터 확인
        required_indicators = ['rsi', 'atr']
        for candle in candles[:10]:  # 샘플 체크
            for indicator in required_indicators:
                if indicator not in candle or candle[indicator] is None:
                    raise ValueError(f"필수 인디케이터 누락: {indicator}")

        logger.info("데이터 검증 완료")

    def _initialize(self, config: BacktestConfig, candles: List[Dict[str, Any]]):
        """백테스트 초기화"""
        self.state.total_candles = len(candles)
        self.state.current_candle_index = 0
        self.state.is_running = True

        self.trades.clear()
        self.balance_snapshots.clear()

        # 전략 초기화
        self.strategy.initialize(config.strategy_params)

    async def _backtest_loop(self, candles: List[Dict[str, Any]], config: BacktestConfig):
        """백테스트 메인 루프"""

        for i, candle in enumerate(candles):
            self.state.current_candle_index = i
            self.state.current_timestamp = datetime.fromtimestamp(candle["timestamp"])
            self.state.progress_percent = (i / self.state.total_candles) * 100

            # 진행 상황 로깅 (1% 단위)
            if i % max(1, len(candles) // 100) == 0:
                logger.debug(f"진행: {self.state.progress_percent:.1f}%")

            # 현재 포지션 확인
            current_position = self.position_manager.get_current_position()

            if current_position:
                # 포지션 있음 -> 청산 조건 확인
                await self._handle_existing_position(candle, current_position, config)
            else:
                # 포지션 없음 -> 진입 조건 확인
                await self._handle_no_position(candle, config)

            # 잔고 스냅샷 저장 (매 캔들)
            self._save_balance_snapshot(candle)

    async def _handle_no_position(self, candle: Dict[str, Any], config: BacktestConfig):
        """포지션 없을 때 처리"""

        # 전략 시그널 확인
        signal = await self.strategy.check_entry_signal(
            candle=candle,
            settings=config.strategy_params
        )

        if signal["should_enter"]:
            # 진입
            trade = await self._enter_position(
                candle=candle,
                side=signal["side"],
                reason=signal["reason"],
                config=config
            )

            if trade:
                self.trades.append(trade)

    async def _handle_existing_position(
        self,
        candle: Dict[str, Any],
        position: Dict[str, Any],
        config: BacktestConfig
    ):
        """포지션 있을 때 처리"""

        # TP/SL 체크
        exit_signal = await self.strategy.check_exit_signal(
            candle=candle,
            position=position,
            settings=config.strategy_params
        )

        if exit_signal["should_exit"]:
            # 청산
            trade = await self._exit_position(
                candle=candle,
                position=position,
                reason=exit_signal["reason"],
                config=config
            )

            if trade:
                # 기존 거래 업데이트
                for t in self.trades:
                    if t.id == position["trade_id"]:
                        t.exit_timestamp = datetime.fromtimestamp(candle["timestamp"])
                        t.exit_price = candle["close"]
                        t.exit_reason = exit_signal["reason"]
                        t.pnl = trade.pnl
                        t.pnl_percent = trade.pnl_percent
                        break

    async def _enter_position(
        self,
        candle: Dict[str, Any],
        side: str,
        reason: str,
        config: BacktestConfig
    ) -> Optional[Trade]:
        """포지션 진입"""

        try:
            # 진입 가격
            entry_price = candle["close"]

            # 포지션 크기 계산
            position_size = self._calculate_position_size(
                entry_price=entry_price,
                config=config
            )

            if position_size <= 0:
                logger.warning("포지션 크기가 0 이하입니다")
                return None

            # TP/SL 계산
            tp_sl = await self.strategy.calculate_tp_sl(
                entry_price=entry_price,
                side=side,
                candle=candle,
                settings=config.strategy_params
            )

            # Trade 객체 생성
            trade = Trade(
                trade_number=len(self.trades) + 1,
                side=side,
                entry_timestamp=datetime.fromtimestamp(candle["timestamp"]),
                entry_price=entry_price,
                entry_reason=reason,
                quantity=position_size,
                leverage=config.strategy_params.get("leverage", 1.0),
                take_profit_price=tp_sl["take_profit"],
                stop_loss_price=tp_sl["stop_loss"],
                entry_rsi=candle.get("rsi"),
                entry_atr=candle.get("atr")
            )

            # 진입 수수료
            trade.entry_fee = self._calculate_fee(entry_price * position_size)

            # 포지션 매니저에 등록
            self.position_manager.open_position(trade)

            # 잔고 차감 (수수료)
            self.balance_tracker.deduct_fee(trade.entry_fee)

            logger.debug(
                f"진입: {side.upper()} @ {entry_price:.2f} "
                f"(수량: {position_size:.4f}, TP: {tp_sl['take_profit']:.2f}, SL: {tp_sl['stop_loss']:.2f})"
            )

            return trade

        except Exception as e:
            logger.error(f"포지션 진입 오류: {e}")
            return None

    async def _exit_position(
        self,
        candle: Dict[str, Any],
        position: Dict[str, Any],
        reason: str,
        config: BacktestConfig
    ) -> Optional[Trade]:
        """포지션 청산"""

        try:
            exit_price = candle["close"]

            # PNL 계산
            pnl_result = self._calculate_pnl(
                entry_price=position["entry_price"],
                exit_price=exit_price,
                quantity=position["quantity"],
                side=position["side"],
                leverage=position["leverage"]
            )

            # 청산 수수료
            exit_fee = self._calculate_fee(exit_price * position["quantity"])

            # Trade 업데이트용 정보
            trade_update = Trade(
                id=position["trade_id"],
                trade_number=position["trade_number"],
                side=position["side"],
                entry_timestamp=position["entry_timestamp"],
                entry_price=position["entry_price"],
                entry_reason=position["entry_reason"],
                exit_timestamp=datetime.fromtimestamp(candle["timestamp"]),
                exit_price=exit_price,
                exit_reason=reason,
                quantity=position["quantity"],
                leverage=position["leverage"],
                pnl=pnl_result["pnl"] - exit_fee,
                pnl_percent=pnl_result["pnl_percent"],
                entry_fee=position.get("entry_fee", 0),
                exit_fee=exit_fee
            )

            # 포지션 닫기
            self.position_manager.close_position(position["trade_id"])

            # 잔고 업데이트
            self.balance_tracker.add_pnl(pnl_result["pnl"] - exit_fee)
            self.balance_tracker.deduct_fee(exit_fee)

            logger.debug(
                f"청산: {position['side'].upper()} @ {exit_price:.2f} "
                f"(PNL: {pnl_result['pnl']:.2f} USDT, {pnl_result['pnl_percent']:.2f}%, 사유: {reason})"
            )

            return trade_update

        except Exception as e:
            logger.error(f"포지션 청산 오류: {e}")
            return None

    def _calculate_position_size(
        self,
        entry_price: float,
        config: BacktestConfig
    ) -> float:
        """포지션 크기 계산"""

        # 투자금
        investment = config.strategy_params.get("investment", 100.0)
        leverage = config.strategy_params.get("leverage", 1.0)

        # 현재 잔고 확인
        current_balance = self.balance_tracker.get_current_balance()

        # 최대 투자 가능 금액
        max_investment = min(investment, current_balance * 0.9)  # 잔고의 90%까지만

        # 포지션 크기 (수량)
        position_value = max_investment * leverage
        position_size = position_value / entry_price

        return position_size

    def _calculate_pnl(
        self,
        entry_price: float,
        exit_price: float,
        quantity: float,
        side: str,
        leverage: float
    ) -> Dict[str, float]:
        """손익 계산"""

        if side == "long":
            price_diff = exit_price - entry_price
        else:  # short
            price_diff = entry_price - exit_price

        pnl = price_diff * quantity
        pnl_percent = (price_diff / entry_price) * 100 * leverage

        return {
            "pnl": pnl,
            "pnl_percent": pnl_percent
        }

    def _calculate_fee(self, trade_value: float) -> float:
        """거래 수수료 계산 (OKX 기준 0.05%)"""
        fee_rate = 0.0005  # 0.05%
        return trade_value * fee_rate

    def _save_balance_snapshot(self, candle: Dict[str, Any]):
        """잔고 스냅샷 저장"""

        current_position = self.position_manager.get_current_position()

        unrealized_pnl = 0.0
        if current_position:
            # 미실현 손익 계산
            pnl_result = self._calculate_pnl(
                entry_price=current_position["entry_price"],
                exit_price=candle["close"],
                quantity=current_position["quantity"],
                side=current_position["side"],
                leverage=current_position["leverage"]
            )
            unrealized_pnl = pnl_result["pnl"]

        snapshot = {
            "timestamp": datetime.fromtimestamp(candle["timestamp"]),
            "balance": self.balance_tracker.get_current_balance(),
            "equity": self.balance_tracker.get_current_balance() + unrealized_pnl,
            "position_side": current_position["side"] if current_position else None,
            "position_size": current_position["quantity"] if current_position else 0.0,
            "unrealized_pnl": unrealized_pnl,
            "cumulative_pnl": self.balance_tracker.get_total_pnl(),
            "cumulative_trades": len(self.trades)
        }

        self.balance_snapshots.append(snapshot)

    async def _analyze_results(self, config: BacktestConfig) -> BacktestResult:
        """결과 분석"""

        metrics = self.metrics_calculator.calculate_all_metrics(
            trades=self.trades,
            balance_snapshots=self.balance_snapshots,
            initial_balance=self.initial_balance,
            final_balance=self.balance_tracker.get_current_balance()
        )

        result = BacktestResult(
            config=config,
            trades=self.trades,
            balance_snapshots=self.balance_snapshots,
            metrics=metrics,
            initial_balance=self.initial_balance,
            final_balance=self.balance_tracker.get_current_balance()
        )

        return result
```

### 5.2 포지션 매니저

```python
# BACKTEST/engine/position_manager.py

from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

from shared.logging import get_logger

logger = get_logger(__name__)

@dataclass
class Position:
    """포지션 정보"""
    trade_id: str
    trade_number: int
    side: str  # long, short
    entry_timestamp: datetime
    entry_price: float
    entry_reason: str
    quantity: float
    leverage: float
    take_profit_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    trailing_stop_price: Optional[float] = None
    entry_rsi: Optional[float] = None
    entry_atr: Optional[float] = None
    entry_fee: float = 0.0
    highest_price: float = 0.0  # 트레일링 스탑용
    lowest_price: float = float('inf')  # 트레일링 스탑용

class PositionManager:
    """
    포지션 관리자

    백테스팅 중 포지션 상태를 관리하고
    TP/SL 업데이트를 처리합니다.
    """

    def __init__(self):
        self.current_position: Optional[Position] = None
        self.position_history = []

    def open_position(self, trade: Any) -> Position:
        """포지션 오픈"""

        if self.current_position:
            logger.warning("기존 포지션이 있는데 새 포지션을 열려고 시도했습니다")
            return None

        position = Position(
            trade_id=trade.id,
            trade_number=trade.trade_number,
            side=trade.side,
            entry_timestamp=trade.entry_timestamp,
            entry_price=trade.entry_price,
            entry_reason=trade.entry_reason,
            quantity=trade.quantity,
            leverage=trade.leverage,
            take_profit_price=trade.take_profit_price,
            stop_loss_price=trade.stop_loss_price,
            entry_rsi=trade.entry_rsi,
            entry_atr=trade.entry_atr,
            entry_fee=trade.entry_fee,
            highest_price=trade.entry_price,
            lowest_price=trade.entry_price
        )

        self.current_position = position
        logger.debug(f"포지션 오픈: {position.side.upper()} @ {position.entry_price}")

        return position

    def close_position(self, trade_id: str):
        """포지션 닫기"""

        if not self.current_position or self.current_position.trade_id != trade_id:
            logger.warning(f"닫을 포지션이 없거나 ID가 일치하지 않습니다: {trade_id}")
            return

        self.position_history.append(self.current_position)
        logger.debug(f"포지션 닫힘: {self.current_position.side.upper()}")

        self.current_position = None

    def get_current_position(self) -> Optional[Dict[str, Any]]:
        """현재 포지션 조회"""

        if not self.current_position:
            return None

        return {
            "trade_id": self.current_position.trade_id,
            "trade_number": self.current_position.trade_number,
            "side": self.current_position.side,
            "entry_timestamp": self.current_position.entry_timestamp,
            "entry_price": self.current_position.entry_price,
            "entry_reason": self.current_position.entry_reason,
            "quantity": self.current_position.quantity,
            "leverage": self.current_position.leverage,
            "take_profit_price": self.current_position.take_profit_price,
            "stop_loss_price": self.current_position.stop_loss_price,
            "trailing_stop_price": self.current_position.trailing_stop_price,
            "entry_fee": self.current_position.entry_fee,
            "highest_price": self.current_position.highest_price,
            "lowest_price": self.current_position.lowest_price
        }

    def update_trailing_stop(self, current_price: float, callback_percent: float):
        """트레일링 스탑 업데이트"""

        if not self.current_position:
            return

        position = self.current_position

        # 최고가/최저가 업데이트
        if position.side == "long":
            position.highest_price = max(position.highest_price, current_price)
            # 롱 포지션: 최고가에서 callback만큼 떨어지면 청산
            position.trailing_stop_price = position.highest_price * (1 - callback_percent / 100)
        else:  # short
            position.lowest_price = min(position.lowest_price, current_price)
            # 숏 포지션: 최저가에서 callback만큼 올라가면 청산
            position.trailing_stop_price = position.lowest_price * (1 + callback_percent / 100)

    def has_position(self) -> bool:
        """포지션 보유 여부"""
        return self.current_position is not None
```

### 5.3 잔고 추적기

```python
# BACKTEST/engine/balance_tracker.py

from typing import List, Dict, Any
from datetime import datetime

from shared.logging import get_logger

logger = get_logger(__name__)

class BalanceTracker:
    """
    잔고 추적기

    백테스팅 중 잔고 변화를 추적하고
    손익을 기록합니다.
    """

    def __init__(self, initial_balance: float):
        self.initial_balance = initial_balance
        self.current_balance = initial_balance

        # 통계
        self.total_pnl = 0.0
        self.total_fees = 0.0
        self.realized_pnl = 0.0

        # 히스토리
        self.pnl_history: List[Dict[str, Any]] = []

    def add_pnl(self, pnl: float):
        """손익 추가"""
        self.current_balance += pnl
        self.total_pnl += pnl
        self.realized_pnl += pnl

        self.pnl_history.append({
            "timestamp": datetime.now(),
            "pnl": pnl,
            "balance": self.current_balance
        })

    def deduct_fee(self, fee: float):
        """수수료 차감"""
        self.current_balance -= fee
        self.total_fees += fee

    def get_current_balance(self) -> float:
        """현재 잔고 조회"""
        return self.current_balance

    def get_total_pnl(self) -> float:
        """총 손익 조회"""
        return self.total_pnl

    def get_total_fees(self) -> float:
        """총 수수료 조회"""
        return self.total_fees

    def get_return_percent(self) -> float:
        """수익률 계산 (%)"""
        if self.initial_balance == 0:
            return 0.0
        return ((self.current_balance - self.initial_balance) / self.initial_balance) * 100

    def get_statistics(self) -> Dict[str, float]:
        """통계 조회"""
        return {
            "initial_balance": self.initial_balance,
            "current_balance": self.current_balance,
            "total_pnl": self.total_pnl,
            "total_fees": self.total_fees,
            "return_percent": self.get_return_percent()
        }
```

### 5.4 전략 모듈 (HYPERRSI 포팅)

```python
# BACKTEST/strategies/hyperrsi_strategy.py

from typing import Dict, Any, Optional
from datetime import datetime

from shared.logging import get_logger
from HYPERRSI.src.api.trading.Calculate_signal import TrendStateCalculator

logger = get_logger(__name__)

class HyperRSIStrategy:
    """
    HYPERRSI 전략 (백테스팅용)

    execute_trading_logic.py의 로직을 백테스팅 환경에 맞게 포팅
    """

    def __init__(self):
        self.trend_calculator = TrendStateCalculator()
        self.settings: Dict[str, Any] = {}

    def initialize(self, settings: Dict[str, Any]):
        """전략 초기화"""
        self.settings = settings
        logger.info(f"HYPERRSI 전략 초기화: {settings}")

    async def check_entry_signal(
        self,
        candle: Dict[str, Any],
        settings: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        진입 시그널 확인

        Returns:
            {
                "should_enter": bool,
                "side": str,  # "long" or "short"
                "reason": str
            }
        """

        rsi = candle.get("rsi")
        if rsi is None:
            return {"should_enter": False}

        entry_option = settings.get("entry_option", "rsi_only")
        rsi_oversold = settings.get("rsi_oversold", 30)
        rsi_overbought = settings.get("rsi_overbought", 70)
        direction = settings.get("direction", "both")

        # RSI Only 모드
        if entry_option == "rsi_only":
            # 롱 진입
            if rsi < rsi_oversold and direction in ["long", "both"]:
                return {
                    "should_enter": True,
                    "side": "long",
                    "reason": f"RSI oversold ({rsi:.2f} < {rsi_oversold})"
                }

            # 숏 진입
            if rsi > rsi_overbought and direction in ["short", "both"]:
                return {
                    "should_enter": True,
                    "side": "short",
                    "reason": f"RSI overbought ({rsi:.2f} > {rsi_overbought})"
                }

        # RSI + Trend 모드
        elif entry_option == "rsi_trend":
            # 트렌드 상태 확인 (실제로는 이전 캔들들 필요)
            # 백테스팅에서는 단순화
            trend_state = self._get_trend_state(candle)

            # 롱 진입 (RSI 과매도 + 상승 트렌드)
            if rsi < rsi_oversold and trend_state == "bullish" and direction in ["long", "both"]:
                return {
                    "should_enter": True,
                    "side": "long",
                    "reason": f"RSI oversold + Bullish trend ({rsi:.2f})"
                }

            # 숏 진입 (RSI 과매수 + 하락 트렌드)
            if rsi > rsi_overbought and trend_state == "bearish" and direction in ["short", "both"]:
                return {
                    "should_enter": True,
                    "side": "short",
                    "reason": f"RSI overbought + Bearish trend ({rsi:.2f})"
                }

        return {"should_enter": False}

    async def check_exit_signal(
        self,
        candle: Dict[str, Any],
        position: Dict[str, Any],
        settings: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        청산 시그널 확인

        Returns:
            {
                "should_exit": bool,
                "reason": str
            }
        """

        current_price = candle["close"]
        entry_price = position["entry_price"]
        side = position["side"]

        # TP/SL 가격
        tp_price = position.get("take_profit_price")
        sl_price = position.get("stop_loss_price")
        trailing_stop_price = position.get("trailing_stop_price")

        # 1. Take Profit 체크
        if tp_price:
            if (side == "long" and current_price >= tp_price) or \
               (side == "short" and current_price <= tp_price):
                return {
                    "should_exit": True,
                    "reason": f"Take Profit (TP: {tp_price:.2f})"
                }

        # 2. Stop Loss 체크
        if sl_price:
            if (side == "long" and current_price <= sl_price) or \
               (side == "short" and current_price >= sl_price):
                return {
                    "should_exit": True,
                    "reason": f"Stop Loss (SL: {sl_price:.2f})"
                }

        # 3. Trailing Stop 체크
        if trailing_stop_price:
            if (side == "long" and current_price <= trailing_stop_price) or \
               (side == "short" and current_price >= trailing_stop_price):
                return {
                    "should_exit": True,
                    "reason": f"Trailing Stop ({trailing_stop_price:.2f})"
                }

        return {"should_exit": False}

    async def calculate_tp_sl(
        self,
        entry_price: float,
        side: str,
        candle: Dict[str, Any],
        settings: Dict[str, Any]
    ) -> Dict[str, float]:
        """TP/SL 가격 계산"""

        tp_sl_option = settings.get("tp_sl_option", "fixed")

        if tp_sl_option == "fixed":
            # 고정 %
            tp_percent = settings.get("take_profit_percent", 4.0)
            sl_percent = settings.get("stop_loss_percent", 2.0)

            if side == "long":
                tp_price = entry_price * (1 + tp_percent / 100)
                sl_price = entry_price * (1 - sl_percent / 100)
            else:  # short
                tp_price = entry_price * (1 - tp_percent / 100)
                sl_price = entry_price * (1 + sl_percent / 100)

        elif tp_sl_option == "dynamic_atr":
            # ATR 기반
            atr = candle.get("atr", entry_price * 0.02)  # ATR 없으면 2% 사용
            atr_multiplier = settings.get("atr_multiplier", 2.0)

            if side == "long":
                tp_price = entry_price + (atr * atr_multiplier)
                sl_price = entry_price - (atr * atr_multiplier * 0.5)
            else:  # short
                tp_price = entry_price - (atr * atr_multiplier)
                sl_price = entry_price + (atr * atr_multiplier * 0.5)

        else:
            # 기본값
            if side == "long":
                tp_price = entry_price * 1.04
                sl_price = entry_price * 0.98
            else:
                tp_price = entry_price * 0.96
                sl_price = entry_price * 1.02

        return {
            "take_profit": tp_price,
            "stop_loss": sl_price
        }

    def _get_trend_state(self, candle: Dict[str, Any]) -> str:
        """
        트렌드 상태 판단 (단순화)

        실제로는 여러 캔들 데이터 필요하지만
        백테스팅에서는 EMA 기준으로 단순화
        """

        close = candle["close"]
        ema = candle.get("ema")

        if ema is None:
            return "neutral"

        if close > ema * 1.01:  # 1% 이상 위
            return "bullish"
        elif close < ema * 0.99:  # 1% 이상 아래
            return "bearish"
        else:
            return "neutral"
```

---

## 6. API 설계

### 6.1 요청/응답 스키마

```python
# BACKTEST/api/schemas/request.py

from pydantic import BaseModel, Field, validator
from datetime import datetime
from typing import Dict, Any, Optional

class BacktestRequest(BaseModel):
    """백테스트 실행 요청"""

    user_id: str = Field(..., description="사용자 ID (OKX UID)")
    symbol: str = Field(..., description="거래 심볼 (예: BTC-USDT-SWAP)")
    timeframe: str = Field(..., description="타임프레임 (예: 1m, 5m, 1h)")

    start_date: datetime = Field(..., description="시작 날짜")
    end_date: datetime = Field(..., description="종료 날짜")

    initial_balance: float = Field(default=10000.0, description="초기 자본 (USDT)")

    strategy_params: Dict[str, Any] = Field(
        default_factory=dict,
        description="전략 파라미터"
    )

    @validator("timeframe")
    def validate_timeframe(cls, v):
        valid_timeframes = ["1m", "3m", "5m", "15m", "30m", "1h", "4h"]
        if v not in valid_timeframes:
            raise ValueError(f"지원하지 않는 타임프레임: {v}")
        return v

    @validator("end_date")
    def validate_date_range(cls, v, values):
        if "start_date" in values and v <= values["start_date"]:
            raise ValueError("종료 날짜는 시작 날짜보다 커야 합니다")
        return v

    @validator("initial_balance")
    def validate_balance(cls, v):
        if v <= 0:
            raise ValueError("초기 자본은 0보다 커야 합니다")
        return v

    class Config:
        schema_extra = {
            "example": {
                "user_id": "123456789012345",
                "symbol": "BTC-USDT-SWAP",
                "timeframe": "1m",
                "start_date": "2025-01-01T00:00:00Z",
                "end_date": "2025-01-31T23:59:59Z",
                "initial_balance": 10000.0,
                "strategy_params": {
                    "leverage": 10,
                    "entry_option": "rsi_trend",
                    "rsi_oversold": 30,
                    "rsi_overbought": 70,
                    "tp_sl_option": "dynamic_atr",
                    "take_profit_percent": 4.0,
                    "stop_loss_percent": 2.0,
                    "trailing_stop_enabled": True,
                    "direction": "both"
                }
            }
        }
```

```python
# BACKTEST/api/schemas/response.py

from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Dict, Any, Optional
from uuid import UUID

class TradeResponse(BaseModel):
    """거래 정보"""
    trade_number: int
    side: str
    entry_timestamp: datetime
    entry_price: float
    entry_reason: str
    exit_timestamp: Optional[datetime]
    exit_price: Optional[float]
    exit_reason: Optional[str]
    quantity: float
    leverage: float
    pnl: Optional[float]
    pnl_percent: Optional[float]
    entry_fee: float
    exit_fee: Optional[float]

class BalanceSnapshotResponse(BaseModel):
    """잔고 스냅샷"""
    timestamp: datetime
    balance: float
    equity: float
    unrealized_pnl: float
    cumulative_pnl: float
    cumulative_trades: int

class MetricsResponse(BaseModel):
    """성능 지표"""
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_return: float
    total_return_percent: float
    max_drawdown: float
    max_drawdown_percent: float
    sharpe_ratio: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    max_win: float
    max_loss: float
    avg_trade_duration_minutes: float

class BacktestResultResponse(BaseModel):
    """백테스트 결과"""
    backtest_id: UUID
    status: str
    progress_percent: float

    # 설정
    symbol: str
    timeframe: str
    start_date: datetime
    end_date: datetime
    initial_balance: float
    final_balance: float

    # 결과
    metrics: Optional[MetricsResponse]
    trades: Optional[List[TradeResponse]]
    balance_snapshots: Optional[List[BalanceSnapshotResponse]]

    # 실행 정보
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    execution_time_seconds: Optional[float]
    error_message: Optional[str]

class BacktestListResponse(BaseModel):
    """백테스트 목록"""
    backtests: List[BacktestResultResponse]
    total: int
    page: int
    page_size: int
```

### 6.2 API 엔드포인트

```python
# BACKTEST/api/routes/backtest.py

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from uuid import uuid4
from typing import Optional

from BACKTEST.api.schemas.request import BacktestRequest
from BACKTEST.api.schemas.response import BacktestResultResponse, BacktestListResponse
from BACKTEST.engine.backtest_engine import BacktestEngine
from BACKTEST.data.timescale_provider import TimescaleProvider
from BACKTEST.strategies.hyperrsi_strategy import HyperRSIStrategy
from BACKTEST.models.backtest import BacktestConfig
from shared.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/backtest", tags=["Backtest"])

# 백테스트 실행 상태 저장소 (실제로는 Redis 또는 DB 사용)
backtest_store = {}

@router.post("/run", response_model=BacktestResultResponse)
async def run_backtest(
    request: BacktestRequest,
    background_tasks: BackgroundTasks
):
    """
    백테스트 실행

    **Request Body:**
    - user_id: 사용자 ID
    - symbol: 거래 심볼
    - timeframe: 타임프레임
    - start_date: 시작 날짜
    - end_date: 종료 날짜
    - initial_balance: 초기 자본
    - strategy_params: 전략 파라미터

    **Response:**
    - backtest_id: 백테스트 실행 ID
    - status: 실행 상태 (pending, running, completed, failed)
    """

    try:
        # 백테스트 ID 생성
        backtest_id = uuid4()

        # 백테스트 설정
        config = BacktestConfig(
            backtest_id=backtest_id,
            user_id=request.user_id,
            symbol=request.symbol,
            timeframe=request.timeframe,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_balance=request.initial_balance,
            strategy_name="hyperrsi",
            strategy_params=request.strategy_params
        )

        # 초기 상태 저장
        backtest_store[str(backtest_id)] = {
            "config": config,
            "status": "pending",
            "progress_percent": 0.0
        }

        # 백그라운드 태스크로 백테스트 실행
        background_tasks.add_task(
            _run_backtest_task,
            backtest_id=backtest_id,
            config=config
        )

        logger.info(f"백테스트 실행 요청: {backtest_id}")

        return BacktestResultResponse(
            backtest_id=backtest_id,
            status="pending",
            progress_percent=0.0,
            symbol=config.symbol,
            timeframe=config.timeframe,
            start_date=config.start_date,
            end_date=config.end_date,
            initial_balance=config.initial_balance,
            final_balance=config.initial_balance
        )

    except Exception as e:
        logger.error(f"백테스트 실행 요청 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{backtest_id}", response_model=BacktestResultResponse)
async def get_backtest_result(backtest_id: str):
    """
    백테스트 결과 조회

    **Path Parameters:**
    - backtest_id: 백테스트 실행 ID

    **Response:**
    - 백테스트 결과 상세 정보
    """

    if backtest_id not in backtest_store:
        raise HTTPException(status_code=404, detail="백테스트를 찾을 수 없습니다")

    result = backtest_store[backtest_id]

    return BacktestResultResponse(**result)


@router.get("/", response_model=BacktestListResponse)
async def list_backtests(
    user_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20
):
    """
    백테스트 목록 조회

    **Query Parameters:**
    - user_id: 사용자 ID (선택)
    - page: 페이지 번호 (기본: 1)
    - page_size: 페이지 크기 (기본: 20)
    """

    # 필터링
    filtered = []
    for bt_id, bt_data in backtest_store.items():
        if user_id is None or bt_data["config"].user_id == user_id:
            filtered.append(BacktestResultResponse(**bt_data))

    # 페이징
    start = (page - 1) * page_size
    end = start + page_size
    paginated = filtered[start:end]

    return BacktestListResponse(
        backtests=paginated,
        total=len(filtered),
        page=page,
        page_size=page_size
    )


@router.delete("/{backtest_id}")
async def delete_backtest(backtest_id: str):
    """백테스트 삭제"""

    if backtest_id not in backtest_store:
        raise HTTPException(status_code=404, detail="백테스트를 찾을 수 없습니다")

    del backtest_store[backtest_id]

    return {"message": "백테스트가 삭제되었습니다"}


# ========================================
# 백그라운드 태스크
# ========================================

async def _run_backtest_task(backtest_id: uuid4, config: BacktestConfig):
    """백테스트 백그라운드 실행"""

    try:
        # 상태 업데이트: running
        backtest_store[str(backtest_id)]["status"] = "running"
        backtest_store[str(backtest_id)]["started_at"] = datetime.now()

        # 백테스트 엔진 초기화
        data_provider = TimescaleProvider()
        strategy = HyperRSIStrategy()
        engine = BacktestEngine(
            data_provider=data_provider,
            strategy=strategy,
            initial_balance=config.initial_balance
        )

        # 실행
        result = await engine.run(config)

        # 결과 저장
        backtest_store[str(backtest_id)].update({
            "status": "completed",
            "progress_percent": 100.0,
            "final_balance": result.final_balance,
            "metrics": result.metrics,
            "trades": result.trades,
            "balance_snapshots": result.balance_snapshots,
            "completed_at": datetime.now(),
            "execution_time_seconds": (datetime.now() - backtest_store[str(backtest_id)]["started_at"]).total_seconds()
        })

        logger.info(f"백테스트 완료: {backtest_id}")

    except Exception as e:
        logger.error(f"백테스트 실행 실패: {backtest_id} - {e}", exc_info=True)

        backtest_store[str(backtest_id)].update({
            "status": "failed",
            "error_message": str(e),
            "completed_at": datetime.now()
        })
```

---

## 7. 구현 단계별 가이드

### Phase 1: 프로젝트 셋업 (1일)

#### Step 1.1: 프로젝트 디렉토리 생성

```bash
# 프로젝트 루트에서
cd /Users/seunghyun/TradingBoost-Strategy

# 백테스팅 서비스 디렉토리 생성
mkdir -p BACKTEST/{api/{routes,schemas},engine,strategies,data/{migration},analysis,optimization,models,tests}

# 필요한 __init__.py 파일 생성
touch BACKTEST/__init__.py
touch BACKTEST/api/__init__.py
touch BACKTEST/api/routes/__init__.py
touch BACKTEST/api/schemas/__init__.py
touch BACKTEST/engine/__init__.py
touch BACKTEST/strategies/__init__.py
touch BACKTEST/data/__init__.py
touch BACKTEST/analysis/__init__.py
touch BACKTEST/models/__init__.py
touch BACKTEST/tests/__init__.py
```

#### Step 1.2: 의존성 파일 생성

```python
# BACKTEST/requirements.txt

# FastAPI
fastapi==0.109.0
uvicorn[standard]==0.27.0
pydantic==2.5.3
pydantic-settings==2.1.0

# Database
asyncpg==0.29.0
redis[asyncio]==5.0.1
psycopg2-binary==2.9.9

# Data Processing
pandas==2.1.4
numpy==1.26.3

# CCXT (OKX API)
ccxt==4.2.25

# Testing
pytest==7.4.4
pytest-asyncio==0.23.3
httpx==0.26.0

# Monitoring
prometheus-client==0.19.0

# Utilities
python-dateutil==2.8.2
pytz==2024.1
```

#### Step 1.3: 설정 파일 작성

```python
# BACKTEST/config.py

from pydantic_settings import BaseSettings
from typing import Optional

class BacktestSettings(BaseSettings):
    """백테스팅 서비스 설정"""

    # 서비스 정보
    SERVICE_NAME: str = "TradingBoost-Backtest"
    VERSION: str = "1.0.0"
    HOST: str = "0.0.0.0"
    PORT: int = 8013

    # Database
    TIMESCALE_HOST: str
    TIMESCALE_PORT: int = 5432
    TIMESCALE_DATABASE: str
    TIMESCALE_USER: str
    TIMESCALE_PASSWORD: str

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None

    # OKX API (데이터 수집용)
    OKX_API_KEY: Optional[str] = None
    OKX_SECRET_KEY: Optional[str] = None
    OKX_PASSPHRASE: Optional[str] = None

    # 백테스팅 설정
    MAX_CONCURRENT_BACKTESTS: int = 5
    DEFAULT_INITIAL_BALANCE: float = 10000.0

    # 로깅
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = BacktestSettings()
```

#### Step 1.4: 메인 앱 작성

```python
# BACKTEST/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from BACKTEST.config import settings
from BACKTEST.api.routes import backtest
from shared.logging import get_logger

logger = get_logger(__name__)

# FastAPI 앱 생성
app = FastAPI(
    title=settings.SERVICE_NAME,
    version=settings.VERSION,
    description="TradingBoost 백테스팅 마이크로서비스"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(backtest.router)

@app.on_event("startup")
async def startup_event():
    logger.info(f"{settings.SERVICE_NAME} v{settings.VERSION} 시작")
    logger.info(f"서비스 포트: {settings.PORT}")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info(f"{settings.SERVICE_NAME} 종료")

@app.get("/")
async def root():
    return {
        "service": settings.SERVICE_NAME,
        "version": settings.VERSION,
        "status": "running"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True
    )
```

### Phase 2: 데이터 인프라 구축 (2-3일)

#### Step 2.1: TimescaleDB 스키마 생성

```bash
# psql로 접속
psql -h localhost -U your_user -d your_database

# 또는 SQL 파일 실행
psql -h localhost -U your_user -d your_database -f BACKTEST/sql/schema.sql
```

```sql
-- BACKTEST/sql/schema.sql

-- 위의 "4.1 TimescaleDB 스키마 설계" 섹션의 SQL 코드 사용
```

#### Step 2.2: 데이터 마이그레이션 스크립트 실행

```bash
# Redis → TimescaleDB 마이그레이션
cd BACKTEST
python -m data.migration.redis_to_timescale

# OKX API로 히스토리 데이터 수집 (최근 30일)
python -m data.migration.okx_historical_fetch
```

#### Step 2.3: 데이터 검증

```python
# BACKTEST/tests/test_data_availability.py

import asyncio
from datetime import datetime, timedelta

from BACKTEST.data.timescale_provider import TimescaleProvider

async def test_data_availability():
    """데이터 가용성 테스트"""

    provider = TimescaleProvider()

    # 최근 7일 데이터 확인
    end_date = datetime.now()
    start_date = end_date - timedelta(days=7)

    validation = await provider.validate_data_availability(
        symbol="BTC-USDT-SWAP",
        timeframe="1m",
        start_date=start_date,
        end_date=end_date
    )

    print(f"데이터 가용성: {validation['available']}")
    print(f"총 캔들: {validation['total_candles']}")
    print(f"예상 캔들: {validation['expected_candles']}")
    print(f"커버리지: {validation['coverage_percent']}%")
    print(f"갭 개수: {validation['gap_count']}")

    if validation['gaps']:
        print("\n데이터 갭:")
        for gap in validation['gaps'][:5]:
            print(f"  {gap['start']} ~ {gap['end']} ({gap['gap_minutes']}분)")

if __name__ == "__main__":
    asyncio.run(test_data_availability())
```

### Phase 3: 백테스팅 엔진 구현 (3-5일)

#### Step 3.1: 모델 정의

```python
# BACKTEST/models/backtest.py
# BACKTEST/models/trade.py
# BACKTEST/models/position.py

# 위의 코드 섹션 참조
```

#### Step 3.2: 엔진 컴포넌트 구현

```bash
# 순서대로 구현
1. BACKTEST/engine/position_manager.py
2. BACKTEST/engine/balance_tracker.py
3. BACKTEST/engine/backtest_engine.py
```

#### Step 3.3: 전략 포팅

```python
# HYPERRSI 로직을 백테스팅용으로 포팅
BACKTEST/strategies/hyperrsi_strategy.py
```

#### Step 3.4: 단위 테스트

```python
# BACKTEST/tests/test_backtest_engine.py

import pytest
from datetime import datetime, timedelta

from BACKTEST.engine.backtest_engine import BacktestEngine
from BACKTEST.data.timescale_provider import TimescaleProvider
from BACKTEST.strategies.hyperrsi_strategy import HyperRSIStrategy
from BACKTEST.models.backtest import BacktestConfig

@pytest.mark.asyncio
async def test_backtest_basic():
    """기본 백테스트 테스트"""

    # 설정
    config = BacktestConfig(
        user_id="test_user",
        symbol="BTC-USDT-SWAP",
        timeframe="1m",
        start_date=datetime.now() - timedelta(days=1),
        end_date=datetime.now(),
        initial_balance=10000.0,
        strategy_params={
            "leverage": 10,
            "entry_option": "rsi_only",
            "rsi_oversold": 30,
            "rsi_overbought": 70
        }
    )

    # 엔진 생성
    data_provider = TimescaleProvider()
    strategy = HyperRSIStrategy()
    engine = BacktestEngine(
        data_provider=data_provider,
        strategy=strategy,
        initial_balance=10000.0
    )

    # 실행
    result = await engine.run(config)

    # 검증
    assert result is not None
    assert result.final_balance > 0
    assert len(result.trades) >= 0
```

### Phase 4: API 구현 (2일)

#### Step 4.1: 스키마 정의

```python
# BACKTEST/api/schemas/request.py
# BACKTEST/api/schemas/response.py

# 위의 "6.1 요청/응답 스키마" 섹션 참조
```

#### Step 4.2: 엔드포인트 구현

```python
# BACKTEST/api/routes/backtest.py

# 위의 "6.2 API 엔드포인트" 섹션 참조
```

#### Step 4.3: API 테스트

```bash
# 서비스 실행
cd BACKTEST
python main.py

# 별도 터미널에서 테스트
curl -X POST http://localhost:8013/api/backtest/run \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "123456789012345",
    "symbol": "BTC-USDT-SWAP",
    "timeframe": "1m",
    "start_date": "2025-01-01T00:00:00Z",
    "end_date": "2025-01-07T23:59:59Z",
    "initial_balance": 10000.0,
    "strategy_params": {
      "leverage": 10,
      "entry_option": "rsi_only",
      "rsi_oversold": 30,
      "rsi_overbought": 70
    }
  }'
```

### Phase 5: 분석 모듈 구현 (2-3일)

#### Step 5.1: 성능 지표 계산기

```python
# BACKTEST/analysis/metrics_calculator.py

from typing import List, Dict, Any
import numpy as np

class MetricsCalculator:
    """성능 지표 계산기"""

    def calculate_all_metrics(
        self,
        trades: List,
        balance_snapshots: List[Dict[str, Any]],
        initial_balance: float,
        final_balance: float
    ) -> Dict[str, Any]:
        """모든 성능 지표 계산"""

        if not trades:
            return self._empty_metrics()

        # 기본 통계
        total_trades = len(trades)
        winning_trades = [t for t in trades if t.pnl and t.pnl > 0]
        losing_trades = [t for t in trades if t.pnl and t.pnl < 0]

        win_count = len(winning_trades)
        loss_count = len(losing_trades)
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0

        # 손익 통계
        total_profit = sum(t.pnl for t in winning_trades)
        total_loss = abs(sum(t.pnl for t in losing_trades))

        avg_win = total_profit / win_count if win_count > 0 else 0
        avg_loss = total_loss / loss_count if loss_count > 0 else 0

        max_win = max((t.pnl for t in winning_trades), default=0)
        max_loss = min((t.pnl for t in losing_trades), default=0)

        # Profit Factor
        profit_factor = total_profit / total_loss if total_loss > 0 else 0

        # 최대 낙폭 (Max Drawdown)
        max_dd, max_dd_pct = self._calculate_max_drawdown(balance_snapshots)

        # Sharpe Ratio
        sharpe = self._calculate_sharpe_ratio(balance_snapshots)

        # 평균 거래 시간
        avg_duration = self._calculate_avg_trade_duration(trades)

        return {
            "total_trades": total_trades,
            "winning_trades": win_count,
            "losing_trades": loss_count,
            "win_rate": round(win_rate, 2),
            "total_return": round(final_balance - initial_balance, 2),
            "total_return_percent": round((final_balance / initial_balance - 1) * 100, 2),
            "max_drawdown": round(max_dd, 2),
            "max_drawdown_percent": round(max_dd_pct, 2),
            "sharpe_ratio": round(sharpe, 4),
            "profit_factor": round(profit_factor, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(abs(avg_loss), 2),
            "max_win": round(max_win, 2),
            "max_loss": round(abs(max_loss), 2),
            "avg_trade_duration_minutes": round(avg_duration, 2)
        }

    def _calculate_max_drawdown(self, snapshots: List[Dict[str, Any]]) -> tuple:
        """최대 낙폭 계산"""

        if not snapshots:
            return 0.0, 0.0

        equity_curve = [s["equity"] for s in snapshots]
        running_max = np.maximum.accumulate(equity_curve)
        drawdown = running_max - equity_curve
        drawdown_pct = (drawdown / running_max) * 100

        max_dd = np.max(drawdown)
        max_dd_pct = np.max(drawdown_pct)

        return max_dd, max_dd_pct

    def _calculate_sharpe_ratio(self, snapshots: List[Dict[str, Any]]) -> float:
        """Sharpe Ratio 계산"""

        if len(snapshots) < 2:
            return 0.0

        # 일일 수익률 계산
        equity_curve = [s["equity"] for s in snapshots]
        returns = np.diff(equity_curve) / equity_curve[:-1]

        if len(returns) == 0:
            return 0.0

        # Sharpe Ratio = (평균 수익률 - 무위험 이자율) / 수익률 표준편차
        # 무위험 이자율 = 0으로 가정
        mean_return = np.mean(returns)
        std_return = np.std(returns)

        if std_return == 0:
            return 0.0

        sharpe = (mean_return / std_return) * np.sqrt(252)  # 연환산

        return sharpe

    def _calculate_avg_trade_duration(self, trades: List) -> float:
        """평균 거래 시간 계산 (분)"""

        durations = []
        for trade in trades:
            if trade.exit_timestamp and trade.entry_timestamp:
                duration = (trade.exit_timestamp - trade.entry_timestamp).total_seconds() / 60
                durations.append(duration)

        return np.mean(durations) if durations else 0.0

    def _empty_metrics(self) -> Dict[str, Any]:
        """빈 지표 (거래 없음)"""
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "total_return": 0.0,
            "total_return_percent": 0.0,
            "max_drawdown": 0.0,
            "max_drawdown_percent": 0.0,
            "sharpe_ratio": 0.0,
            "profit_factor": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "max_win": 0.0,
            "max_loss": 0.0,
            "avg_trade_duration_minutes": 0.0
        }
```

---

## 8. 성능 최적화

### 8.1 데이터베이스 최적화

```sql
-- 인덱스 최적화
CREATE INDEX CONCURRENTLY idx_candle_symbol_timeframe_timestamp
ON candle_history (symbol, timeframe, timestamp DESC)
WHERE is_complete = true;

-- 파티셔닝 (TimescaleDB 자동)
SELECT show_chunks('candle_history');

-- 통계 업데이트
ANALYZE candle_history;

-- 쿼리 성능 확인
EXPLAIN ANALYZE
SELECT * FROM candle_history
WHERE symbol = 'BTC-USDT-SWAP'
  AND timeframe = '1m'
  AND timestamp >= NOW() - INTERVAL '7 days';
```

### 8.2 백테스팅 속도 최적화

```python
# 배치 처리
async def batch_process_candles(candles, batch_size=1000):
    """캔들 데이터 배치 처리"""
    for i in range(0, len(candles), batch_size):
        batch = candles[i:i + batch_size]
        await process_batch(batch)

# 병렬 백테스팅 (여러 파라미터 동시 테스트)
import asyncio

async def parallel_backtests(configs):
    """병렬 백테스트 실행"""
    tasks = [run_backtest(config) for config in configs]
    results = await asyncio.gather(*tasks)
    return results
```

### 8.3 캐싱 전략

```python
# Redis 캐싱
from functools import lru_cache

@lru_cache(maxsize=100)
def get_cached_candles(symbol, timeframe, start, end):
    """캔들 데이터 캐싱"""
    # 자주 조회되는 데이터 캐싱
    pass
```

---

## 9. 테스트 전략

### 9.1 단위 테스트

```python
# pytest 실행
pytest BACKTEST/tests -v --cov=BACKTEST

# 특정 테스트만 실행
pytest BACKTEST/tests/test_backtest_engine.py -v
```

### 9.2 통합 테스트

```python
# End-to-End 테스트
pytest BACKTEST/tests/test_integration.py -v
```

### 9.3 성능 테스트

```bash
# Locust로 부하 테스트
locust -f BACKTEST/tests/locustfile.py --host=http://localhost:8013
```

---

## 10. 배포 및 운영

### 10.1 Docker 배포

```dockerfile
# BACKTEST/Dockerfile

FROM python:3.9-slim

WORKDIR /app

# 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 공유 모듈 복사
COPY shared/ ./shared/

# 백테스팅 서비스 복사
COPY BACKTEST/ ./BACKTEST/

# 포트 노출
EXPOSE 8013

# 실행
CMD ["python", "-m", "BACKTEST.main"]
```

```yaml
# docker-compose.backtest.yml

version: '3.8'

services:
  backtest:
    build:
      context: .
      dockerfile: BACKTEST/Dockerfile
    ports:
      - "8013:8013"
    environment:
      - TIMESCALE_HOST=timescaledb
      - REDIS_HOST=redis
    depends_on:
      - timescaledb
      - redis
    restart: unless-stopped
```

### 10.2 모니터링

```python
# Prometheus 메트릭
from prometheus_client import Counter, Histogram

backtest_requests = Counter('backtest_requests_total', 'Total backtest requests')
backtest_duration = Histogram('backtest_duration_seconds', 'Backtest execution time')
```

### 10.3 로깅

```python
# 구조화된 로깅
logger.info(
    "백테스트 완료",
    extra={
        "backtest_id": backtest_id,
        "symbol": symbol,
        "total_trades": len(trades),
        "return_percent": return_pct
    }
)
```

---

## 부록

### A. 체크리스트

#### 구현 체크리스트

- [ ] Phase 1: 프로젝트 셋업
  - [ ] 디렉토리 구조 생성
  - [ ] 의존성 설치
  - [ ] 설정 파일 작성
  - [ ] 메인 앱 작성

- [ ] Phase 2: 데이터 인프라
  - [ ] TimescaleDB 스키마 생성
  - [ ] Redis → TimescaleDB 마이그레이션
  - [ ] OKX API 히스토리 데이터 수집
  - [ ] 데이터 검증

- [ ] Phase 3: 백테스팅 엔진
  - [ ] 모델 정의
  - [ ] 포지션 매니저 구현
  - [ ] 잔고 추적기 구현
  - [ ] 백테스팅 엔진 구현
  - [ ] 전략 포팅
  - [ ] 단위 테스트

- [ ] Phase 4: API 구현
  - [ ] 스키마 정의
  - [ ] 엔드포인트 구현
  - [ ] API 테스트

- [ ] Phase 5: 분석 모듈
  - [ ] 성능 지표 계산기
  - [ ] 리포트 생성기

- [ ] Phase 6: 테스트 & 최적화
  - [ ] 단위 테스트
  - [ ] 통합 테스트
  - [ ] 성능 최적화
  - [ ] 문서화

- [ ] Phase 7: 배포
  - [ ] Docker 이미지 빌드
  - [ ] 서비스 배포
  - [ ] 모니터링 설정

### B. 트러블슈팅 가이드

#### 데이터 관련

**문제**: 캔들 데이터 갭이 너무 많음
**해결**: OKX API로 누락 데이터 보충

**문제**: 인디케이터 값이 NULL
**해결**: 충분한 과거 데이터 확보 후 재계산

#### 성능 관련

**문제**: 백테스팅이 너무 느림
**해결**: 배치 처리, 병렬화, 인덱스 최적화

**문제**: 메모리 부족
**해결**: 청크 단위 처리, 제너레이터 사용

#### API 관련

**문제**: 타임아웃 발생
**해결**: 백그라운드 태스크 사용, WebSocket 진행 상황 전송

---

## 요약

이 문서는 TradingBoost HYPERRSI 전략을 위한 백테스팅 시스템 구축 가이드입니다.

**핵심 포인트**:
1. **마이크로서비스 아키텍처**: 독립 배포 가능한 백테스팅 서비스
2. **TimescaleDB 기반**: 효율적인 시계열 데이터 관리
3. **전략 재사용**: HYPERRSI 로직 포팅
4. **FastAPI**: RESTful API 제공
5. **확장 가능**: 향후 다른 전략 추가 용이

**예상 일정**: 약 2-3주
- Week 1: 인프라 구축 & 데이터 마이그레이션
- Week 2: 엔진 구현 & API 개발
- Week 3: 테스트 & 최적화 & 배포

**다음 단계**:
1. TimescaleDB 스키마 생성
2. 데이터 마이그레이션 실행
3. 백테스팅 엔진 구현 시작

질문이나 추가 설명이 필요한 부분이 있으시면 말씀해주세요!