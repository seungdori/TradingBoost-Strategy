# BACKTEST - TradingBoost 백테스팅 시스템

HYPERRSI 전략을 위한 백테스팅 및 파라미터 최적화 시스템

## 개요

TradingBoost BACKTEST는 과거 데이터를 기반으로 HYPERRSI 전략의 성능을 검증하고 최적의 파라미터를 찾기 위한 백테스팅 시스템입니다.

### 주요 기능

- ✅ HYPERRSI 전략 시뮬레이션
- ✅ 과거 데이터 기반 백테스팅
- ✅ 다양한 타임프레임 지원 (1m, 3m, 5m, 15m, 30m, 1h, 4h)
- ✅ 실시간 진행 상황 모니터링
- ✅ 상세한 거래 내역 및 통계 제공
- ✅ 파라미터 최적화 기능
- ✅ TimescaleDB 기반 효율적인 데이터 저장

## 아키텍처

```
BACKTEST/
├── api/              # FastAPI 라우트 및 스키마
├── engine/           # 백테스팅 엔진 코어
├── strategies/       # 전략 구현 (HYPERRSI 포팅)
├── data/             # 데이터 제공자 (TimescaleDB, Redis, OKX)
├── analysis/         # 성능 분석 및 리포팅
├── optimization/     # 파라미터 최적화
├── models/           # 데이터 모델
└── tests/            # 테스트
```

## 설치

### 1. 의존성 설치

프로젝트 루트에서:

```bash
# 프로젝트 전체 의존성 설치
pip install -e .

# 백테스팅 전용 추가 의존성 설치 (선택적)
pip install -r BACKTEST/requirements.txt
```

### 2. TimescaleDB 설정

TimescaleDB는 PostgreSQL 기반의 시계열 데이터베이스로, 대량의 캔들 데이터를 효율적으로 저장합니다.

**.env 파일 설정:**

```bash
# TimescaleDB 설정 (필수)
TIMESCALE_HOST=localhost
TIMESCALE_PORT=5432
TIMESCALE_DATABASE=tradingboost
TIMESCALE_USER=your_user
TIMESCALE_PASSWORD=your_password
```

### 3. 데이터베이스 마이그레이션

```bash
# TimescaleDB에 백테스팅 테이블 생성
psql -h localhost -U your_user -d tradingboost -f migrations/backtest/001_create_candle_history.sql
psql -h localhost -U your_user -d tradingboost -f migrations/backtest/002_create_backtest_tables.sql
```

### 4. 과거 데이터 수집 (선택적)

백테스팅을 위해서는 과거 캔들 데이터가 필요합니다:

```bash
# OKX API를 통한 히스토리 데이터 수집 (예정)
python -m BACKTEST.data.okx_provider --symbol BTC-USDT-SWAP --timeframe 1m --days 30
```

또는 Redis에 저장된 기존 데이터를 TimescaleDB로 마이그레이션:

```bash
# Redis → TimescaleDB 마이그레이션 (예정)
python -m BACKTEST.data.redis_migration
```

## 사용법

### 1. 백테스팅 서버 실행

```bash
cd BACKTEST
python main.py
```

서버가 http://localhost:8013 에서 실행됩니다.

### 2. API를 통한 백테스팅 실행

```bash
# 백테스트 실행 예시 (curl)
curl -X POST http://localhost:8013/backtest/run \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTC-USDT-SWAP",
    "timeframe": "1m",
    "start_date": "2025-01-01T00:00:00Z",
    "end_date": "2025-01-31T23:59:59Z",
    "strategy_params": {
      "entry_option": "rsi_trend",
      "rsi_oversold": 30,
      "rsi_overbought": 70,
      "leverage": 10,
      "investment": 100,
      "tp_sl_option": "dynamic_atr",
      "stop_loss_percent": 2.0,
      "take_profit_percent": 4.0,
      "trailing_stop_enabled": true
    }
  }'
```

### 3. 결과 조회

```bash
# 백테스트 목록 조회
curl http://localhost:8013/backtest/results?user_id=your_user_id

# 특정 백테스트 상세 결과
curl http://localhost:8013/backtest/results/{backtest_id}
```

## 데이터 소스

### 지원 데이터 소스

1. **TimescaleDB** (권장): 대용량 과거 데이터 저장 및 빠른 조회
2. **Redis**: 최근 캔들 데이터 (최대 3000개)
3. **OKX API**: 실시간 과거 데이터 수집

### 데이터 우선순위

백테스팅 엔진은 다음 순서로 데이터를 조회합니다:

1. TimescaleDB (가장 빠르고 효율적)
2. Redis (최근 데이터만 가능)
3. OKX API (실시간 수집, 속도 제한 있음)

## 성능 지표

백테스팅 결과는 다음과 같은 성능 지표를 제공합니다:

- **총 거래 수** (Total Trades)
- **승률** (Win Rate)
- **총 수익률** (Total Return %)
- **최대 낙폭** (Max Drawdown %)
- **샤프 비율** (Sharpe Ratio)
- **평균 거래당 수익** (Avg PNL per Trade)
- **손익 비율** (Profit Factor)
- **Equity Curve** (잔고 변화 그래프)

## 개발 가이드

### 프로젝트 구조

상세한 구조는 `BACKTEST_SYSTEM_DESIGN.md` 참조

### Import 규칙

BACKTEST는 TradingBoost monorepo의 일부이므로 absolute imports를 사용합니다:

```python
# ✅ Correct
from BACKTEST.engine import BacktestEngine
from BACKTEST.data import TimescaleProvider
from shared.config import get_settings
from shared.logging import get_logger

# ❌ Wrong
from engine import BacktestEngine
from ..data import TimescaleProvider
```

### 테스트 실행

```bash
cd BACKTEST
pytest tests/
```

## 문제 해결

### TimescaleDB 연결 오류

```bash
# TimescaleDB 연결 확인
psql -h localhost -U your_user -d tradingboost -c "SELECT 1"

# Hypertable 생성 확인
psql -h localhost -U your_user -d tradingboost -c "SELECT * FROM timescaledb_information.hypertables"
```

### 데이터 없음 오류

백테스팅 전에 과거 데이터가 TimescaleDB에 저장되어 있어야 합니다. 데이터 수집 스크립트를 실행하세요.

## 로드맵

- [ ] OKX 과거 데이터 자동 수집
- [ ] Redis → TimescaleDB 마이그레이션 스크립트
- [ ] 파라미터 최적화 (Grid Search)
- [ ] 웹 UI 대시보드
- [ ] 여러 전략 동시 비교
- [ ] ML 기반 파라미터 추천

## 참고 문서

- [백테스팅 시스템 설계](../BACKTEST_SYSTEM_DESIGN.md)
- [백테스팅 데이터 분석](../BACKTEST_DATA_ANALYSIS.md)
- [프로젝트 아키텍처](../ARCHITECTURE.md)

## 라이센스

TradingBoost-Strategy 프로젝트의 일부
