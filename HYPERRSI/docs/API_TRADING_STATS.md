# HYPERRSI Trading Statistics API Documentation

> **For Frontend Engineers**
> Last Updated: 2025-11-26
> Base URL: `http://localhost:8000`

---

## 📋 API Overview

HYPERRSI 트레이딩 통계 API는 두 가지 데이터 소스를 제공합니다:

| 소스 | 엔드포인트 | 특징 |
|------|----------|------|
| **Redis** (기존) | `/stats/summary`, `/stats/trade-amount`, `/stats/profit-amount`, `/stats/trade-history` | 실시간 캐싱, 빠른 응답 |
| **PostgreSQL** (신규) | `/stats/trading`, `/stats/trading/daily-pnl`, `/stats/trading/by-symbol`, `/stats/trading/trades` | 영구 저장, 정확한 통계 |

---

## 🆕 New APIs (PostgreSQL 기반)

### 1. 종합 트레이딩 통계

```http
GET /stats/trading
```

#### Request Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `user_id` | string | ✅ | OKX UID 또는 텔레그램 ID |
| `symbol` | string | ❌ | 거래 심볼 (예: `BTC-USDT-SWAP`) |
| `start_date` | string | ❌ | 시작 날짜 (YYYY-MM-DD) |
| `end_date` | string | ❌ | 종료 날짜 (YYYY-MM-DD) |
| `initial_balance` | number | ❌ | MDD 계산용 초기 잔고 (기본: 10000) |

#### Response

```json
{
  "status": "success",
  "data": {
    "user_id": "518796558012178692",
    "symbol": "ALL",
    "period": {
      "start_date": "2025-01-01",
      "end_date": "2025-01-31"
    },
    "summary": {
      "total_trades": 150,
      "winning_trades": 90,
      "losing_trades": 55,
      "breakeven_trades": 5,
      "win_rate": 60.0
    },
    "pnl": {
      "gross_pnl": 1500.0,
      "total_fees": 75.0,
      "net_pnl": 1425.0,
      "total_wins": 2500.0,
      "total_losses": 1000.0,
      "avg_pnl": 9.5,
      "avg_win": 27.78,
      "avg_loss": -18.18,
      "max_win": 250.0,
      "max_loss": -150.0
    },
    "risk_metrics": {
      "profit_factor": 2.5,
      "sharpe_ratio": 1.85,
      "max_drawdown": 350.0,
      "max_drawdown_percent": 3.2,
      "drawdown_start_date": "2025-01-15",
      "drawdown_end_date": "2025-01-18"
    },
    "volume": {
      "total_volume": 500000.0,
      "avg_trade_size": 3333.33
    },
    "holding_time": {
      "avg_hours": 2.5,
      "min_hours": 0.1,
      "max_hours": 48.0
    },
    "close_types": {
      "tp1": 45,
      "tp2": 30,
      "tp3": 15,
      "sl": 40,
      "trailing_stop": 15,
      "manual": 5
    },
    "by_side": {
      "long": {
        "count": 80,
        "win_rate": 62.5,
        "net_pnl": 900.0
      },
      "short": {
        "count": 70,
        "win_rate": 57.14,
        "net_pnl": 525.0
      }
    }
  }
}
```

#### Response Fields 설명

| Field | Type | Description |
|-------|------|-------------|
| `summary.total_trades` | int | 총 거래 횟수 |
| `summary.winning_trades` | int | 수익 거래 수 |
| `summary.losing_trades` | int | 손실 거래 수 |
| `summary.breakeven_trades` | int | 본전 거래 수 |
| `summary.win_rate` | float | 승률 (%) |
| `pnl.gross_pnl` | float | 총 손익 (수수료 포함 전) |
| `pnl.total_fees` | float | 총 수수료 |
| `pnl.net_pnl` | float | 순 손익 (수수료 차감 후) |
| `pnl.total_wins` | float | 수익 거래 총액 |
| `pnl.total_losses` | float | 손실 거래 총액 (양수) |
| `pnl.avg_pnl` | float | 평균 손익 |
| `pnl.avg_win` | float | 평균 수익 |
| `pnl.avg_loss` | float | 평균 손실 (음수) |
| `pnl.max_win` | float | 최대 수익 |
| `pnl.max_loss` | float | 최대 손실 (음수) |
| `risk_metrics.profit_factor` | float | 수익팩터 (총수익/총손실) |
| `risk_metrics.sharpe_ratio` | float | 샤프비율 (연환산) |
| `risk_metrics.max_drawdown` | float | 최대 낙폭 (MDD) 금액 |
| `risk_metrics.max_drawdown_percent` | float | 최대 낙폭률 (%) |
| `volume.total_volume` | float | 총 거래량 (USDT) |
| `volume.avg_trade_size` | float | 평균 거래 크기 |
| `holding_time.avg_hours` | float | 평균 보유 시간 (시간) |
| `holding_time.min_hours` | float | 최소 보유 시간 |
| `holding_time.max_hours` | float | 최대 보유 시간 |
| `close_types` | object | 청산 유형별 거래 수 |
| `by_side.long` | object | 롱 포지션 통계 |
| `by_side.short` | object | 숏 포지션 통계 |

---

### 2. 일별 손익 시계열 (차트용)

```http
GET /stats/trading/daily-pnl
```

#### Request Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `user_id` | string | ✅ | OKX UID |
| `symbol` | string | ❌ | 거래 심볼 |
| `start_date` | string | ❌ | 시작 날짜 |
| `end_date` | string | ❌ | 종료 날짜 |

#### Response

```json
{
  "status": "success",
  "data": {
    "period": "2025-01-01 - 2025-01-31",
    "chart_data": [
      {
        "date": "2025-01-01",
        "trades": 5,
        "net_pnl": 125.50,
        "cumulative_pnl": 125.50
      },
      {
        "date": "2025-01-02",
        "trades": 8,
        "net_pnl": -45.25,
        "cumulative_pnl": 80.25
      },
      {
        "date": "2025-01-03",
        "trades": 12,
        "net_pnl": 200.00,
        "cumulative_pnl": 280.25
      }
    ]
  }
}
```

#### 사용 예시 (React/Chart.js)

```typescript
// API 호출
const response = await fetch('/stats/trading/daily-pnl?user_id=123456&start_date=2025-01-01&end_date=2025-01-31');
const { data } = await response.json();

// Chart.js 데이터 변환
const chartData = {
  labels: data.chart_data.map(d => d.date),
  datasets: [
    {
      label: '일별 손익',
      data: data.chart_data.map(d => d.net_pnl),
      borderColor: 'rgb(75, 192, 192)',
      backgroundColor: data.chart_data.map(d => d.net_pnl >= 0 ? 'rgba(75, 192, 192, 0.5)' : 'rgba(255, 99, 132, 0.5)')
    },
    {
      label: '누적 손익',
      data: data.chart_data.map(d => d.cumulative_pnl),
      borderColor: 'rgb(54, 162, 235)',
      type: 'line'
    }
  ]
};
```

---

### 3. 심볼별 통계 비교

```http
GET /stats/trading/by-symbol
```

#### Request Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `user_id` | string | ✅ | OKX UID |
| `start_date` | string | ❌ | 시작 날짜 |
| `end_date` | string | ❌ | 종료 날짜 |

#### Response

```json
{
  "status": "success",
  "data": [
    {
      "symbol": "BTC-USDT-SWAP",
      "total_trades": 50,
      "winning_trades": 32,
      "win_rate": 64.0,
      "net_pnl": 850.50,
      "total_volume": 250000.0
    },
    {
      "symbol": "ETH-USDT-SWAP",
      "total_trades": 45,
      "winning_trades": 25,
      "win_rate": 55.56,
      "net_pnl": 420.25,
      "total_volume": 150000.0
    },
    {
      "symbol": "SOL-USDT-SWAP",
      "total_trades": 35,
      "winning_trades": 20,
      "win_rate": 57.14,
      "net_pnl": 154.25,
      "total_volume": 100000.0
    }
  ]
}
```

---

### 4. DB 거래 기록 조회 (페이지네이션)

```http
GET /stats/trading/trades
```

#### Request Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `user_id` | string | ✅ | OKX UID |
| `symbol` | string | ❌ | 거래 심볼 필터 |
| `side` | string | ❌ | `long` 또는 `short` |
| `close_type` | string | ❌ | 청산 유형 필터 |
| `start_date` | string | ❌ | 시작 날짜 |
| `end_date` | string | ❌ | 종료 날짜 |
| `limit` | int | ❌ | 조회 수 (1-200, 기본: 50) |
| `offset` | int | ❌ | 오프셋 (기본: 0) |

#### Response

```json
{
  "status": "success",
  "data": {
    "trades": [
      {
        "id": 1234,
        "symbol": "BTC-USDT-SWAP",
        "side": "long",
        "entry_time": "2025-01-15T10:30:00Z",
        "entry_price": 92000.0,
        "entry_size": 0.1,
        "exit_time": "2025-01-15T14:45:00Z",
        "exit_price": 92500.0,
        "exit_size": 0.1,
        "close_type": "tp1",
        "leverage": 10,
        "dca_count": 0,
        "realized_pnl": 50.0,
        "realized_pnl_percent": 0.54,
        "entry_fee": 0.92,
        "exit_fee": 0.93,
        "net_pnl": 48.15,
        "holding_seconds": 15300,
        "is_hedge": false
      }
    ],
    "pagination": {
      "total": 150,
      "limit": 50,
      "offset": 0,
      "has_more": true
    }
  }
}
```

#### Close Type 값 목록

| Value | Description |
|-------|-------------|
| `tp1`, `tp2`, `tp3` | Take Profit 레벨 |
| `sl` | Stop Loss |
| `trailing_stop` | 트레일링 스탑 |
| `break_even` | 본전 청산 |
| `trend_reversal` | 트렌드 반전 청산 |
| `manual` | 수동 청산 |
| `signal` | 시그널 기반 청산 |
| `liquidation` | 청산 |

---

## 📊 기존 APIs (Redis 기반)

### 1. 거래 요약 통계

```http
GET /stats/summary
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `user_id` | string | ✅ | 사용자 ID |
| `refresh` | boolean | ❌ | 캐시 무시 (기본: false) |

```json
{
  "status": "success",
  "data": {
    "total_balance": {"label": "총 잔고", "value": 5000.0, "unit": "달러"},
    "total_volume": {"label": "거래량", "value": 50000.0, "unit": "달러"},
    "total_profit": {"label": "수익금액", "value": 500.0, "unit": "달러"}
  }
}
```

---

### 2. 일별 거래량 차트

```http
GET /stats/trade-amount
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `user_id` | string | ✅ | 사용자 ID |
| `start_date` | string | ❌ | 시작일 (YYYY-MM-DD) |
| `end_date` | string | ❌ | 종료일 (기본: 오늘) |
| `refresh` | boolean | ❌ | 캐시 무시 |

```json
{
  "status": "success",
  "data": {
    "period": "2025-01-01 - 2025-01-10",
    "chart_data": [
      {"date": "2025-01-01", "amount": 1500.50},
      {"date": "2025-01-02", "amount": 2300.75}
    ]
  }
}
```

---

### 3. 일별 수익 차트 (누적 포함)

```http
GET /stats/profit-amount
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `user_id` | string | ✅ | 사용자 ID |
| `start_date` | string | ❌ | 시작일 |
| `end_date` | string | ❌ | 종료일 |
| `refresh` | boolean | ❌ | 캐시 무시 |

```json
{
  "status": "success",
  "data": {
    "period": "2025-01-01 - 2025-01-10",
    "chart_data": [
      {"date": "2025-01-01", "profit": 50.25, "cumulative_profit": 50.25},
      {"date": "2025-01-02", "profit": 75.50, "cumulative_profit": 125.75}
    ],
    "stats": {
      "total_trades": 42,
      "win_rate": 71.4,
      "winning_trades": 30,
      "losing_trades": 12
    }
  }
}
```

---

### 4. 거래 내역

```http
GET /stats/trade-history
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `user_id` | string | ✅ | 사용자 ID |
| `limit` | int | ❌ | 조회 수 (1-100, 기본: 10) |
| `status` | string | ❌ | `open` 또는 `closed` |
| `refresh` | boolean | ❌ | 캐시 무시 |

```json
{
  "status": "success",
  "data": [
    {
      "timestamp": "2025-01-10 14:30:25",
      "symbol": "BTC-USDT-SWAP",
      "coin_name": "BTC",
      "entry_price": 92000.0,
      "exit_price": 92500.0,
      "size": 0.1,
      "pnl": 50.0,
      "pnl_percent": 0.54,
      "status": "closed",
      "side": "long",
      "close_type": "tp"
    }
  ]
}
```

---

## 🔄 API 선택 가이드

| 사용 목적 | 추천 API |
|----------|---------|
| 대시보드 요약 | `/stats/summary` (Redis) |
| 상세 통계 분석 | `/stats/trading` (PostgreSQL) |
| 일별 수익 차트 | `/stats/trading/daily-pnl` (PostgreSQL) |
| 심볼별 비교 | `/stats/trading/by-symbol` (PostgreSQL) |
| 실시간 거래 내역 | `/stats/trade-history` (Redis) |
| 과거 거래 기록 조회 | `/stats/trading/trades` (PostgreSQL) |

---

## ⚠️ Error Responses

### 400 Bad Request

```json
{"detail": "Invalid date format. Use YYYY-MM-DD"}
```

### 404 Not Found

```json
{"status": "no_data", "message": "해당 기간에 거래 기록이 없습니다."}
```

### 500 Internal Server Error

```json
{"detail": "트레이딩 통계 조회에 실패했습니다."}
```

### API 키 미등록

```json
{
  "status": "no_api_key",
  "message": "API 키가 등록되지 않았습니다. API 키를 먼저 등록해주세요.",
  "data": {}
}
```

---

## 📝 TypeScript Interfaces

```typescript
// 종합 통계 응답
interface TradingStatsResponse {
  status: "success" | "no_data";
  data?: {
    user_id: string;
    symbol: string;
    period: {
      start_date: string | null;
      end_date: string | null;
    };
    summary: {
      total_trades: number;
      winning_trades: number;
      losing_trades: number;
      breakeven_trades: number;
      win_rate: number;
    };
    pnl: {
      gross_pnl: number;
      total_fees: number;
      net_pnl: number;
      total_wins: number;
      total_losses: number;
      avg_pnl: number;
      avg_win: number;
      avg_loss: number;
      max_win: number;
      max_loss: number;
    };
    risk_metrics: {
      profit_factor: number | null;
      sharpe_ratio: number | null;
      max_drawdown: number;
      max_drawdown_percent: number;
      drawdown_start_date: string | null;
      drawdown_end_date: string | null;
    };
    volume: {
      total_volume: number;
      avg_trade_size: number;
    };
    holding_time: {
      avg_hours: number;
      min_hours: number;
      max_hours: number;
    };
    close_types: Record<string, number>;
    by_side: {
      long: SideStats;
      short: SideStats;
    };
  };
  message?: string;
}

interface SideStats {
  count: number;
  win_rate: number;
  net_pnl: number;
}

// 일별 PnL
interface DailyPnL {
  date: string;
  trades: number;
  net_pnl: number;
  cumulative_pnl: number;
}

// 심볼별 통계
interface SymbolStats {
  symbol: string;
  total_trades: number;
  winning_trades: number;
  win_rate: number;
  net_pnl: number;
  total_volume: number;
}

// 거래 기록
interface TradeRecord {
  id: number;
  symbol: string;
  side: "long" | "short";
  entry_time: string;
  entry_price: number;
  entry_size: number;
  exit_time: string;
  exit_price: number;
  exit_size: number;
  close_type: string;
  leverage: number;
  dca_count: number;
  realized_pnl: number;
  realized_pnl_percent: number;
  entry_fee: number;
  exit_fee: number;
  net_pnl: number;
  holding_seconds: number;
  is_hedge: boolean;
}
```

---

## 📞 Questions?

API 관련 문의사항은 백엔드 팀에 연락해주세요.
