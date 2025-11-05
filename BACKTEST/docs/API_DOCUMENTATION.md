# Backtest API Documentation

## 개요

TradingBoost-Strategy 백테스트 API는 HyperRSI 전략의 성능을 검증하고 최적화하기 위한 RESTful API입니다.

**Base URL**: `http://localhost:8013/api/v1/backtest`

**지원 전략**:
- HyperRSI: RSI + 트렌드 기반 매매 전략

---

## 엔드포인트 목록

| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/run` | 백테스트 실행 |
| GET | `/{backtest_id}` | 백테스트 결과 조회 |
| DELETE | `/{backtest_id}` | 백테스트 삭제 |
| GET | `/validate/data` | 데이터 유효성 검증 |

---

## TypeScript/React 통합 가이드

### TypeScript 인터페이스

프로젝트에서 바로 사용할 수 있는 TypeScript 타입 정의입니다.

```typescript
// types/backtest.ts

/**
 * 백테스트 실행 요청
 */
export interface BacktestRequest {
  // 필수 파라미터
  symbol: string;              // 거래 심볼 (예: "BTC/USDT:USDT")
  timeframe: string;           // 타임프레임 (예: "15m", "1h", "4h")
  start_date: string;          // 시작 날짜 (ISO 8601)
  end_date: string;            // 종료 날짜 (ISO 8601)
  initial_capital: number;     // 초기 자본금 (USDT)

  // 선택 파라미터
  position_size_percent?: number;  // 포지션 크기 (기본: 100.0)
  maker_fee?: number;              // 메이커 수수료 % (기본: 0.02)
  taker_fee?: number;              // 테이커 수수료 % (기본: 0.05)
  data_source?: 'timescale' | 'redis' | 'okx';  // 데이터 소스
  strategy_name?: string;          // 전략 이름 (기본: "hyperrsi")

  // 전략 파라미터
  strategy_params: HyperRSIParams;
}

/**
 * HyperRSI 전략 파라미터
 */
export interface HyperRSIParams {
  // === 기본 설정 ===
  rsi_period?: number;         // RSI 계산 기간 (기본: 5)
  rsi_ob?: number;             // RSI 과매수 레벨 (기본: 70)
  rsi_os?: number;             // RSI 과매도 레벨 (기본: 30)
  direction?: 'long' | 'short' | 'both';  // 거래 방향 (기본: 'both')

  // === 트렌드 필터 ===
  use_trend_filter?: boolean;  // 트렌드 필터 사용 (기본: true)
  ema_period?: number;         // 빠른 EMA 기간 (기본: 7)
  sma_period?: number;         // 느린 SMA 기간 (기본: 20)

  // === 진입 조건 ===
  entry_option?: 'all' | 'rsi_only' | 'trend_only';  // 진입 조건
  require_trend_confirm?: boolean;  // 트렌드 확인 필수 (기본: true)

  // === 트렌드 반전 종료 (신규!) ===
  use_trend_close?: boolean;   // 트렌드 반전 종료 (기본: true)

  // === 손절 (Stop Loss) ===
  // 레거시 방식 (하위 호환)
  stop_loss_percent?: number;  // 손절 비율 % (예: 2.8)

  // 새 방식 (권장)
  use_sl?: boolean;            // 일반 손절 사용
  use_sl_on_last?: boolean;    // 마지막 진입만 손절 (DCA용)
  sl_value?: number;           // 손절 값
  sl_option?: 'percentage' | 'price';  // 손절 옵션

  // === 익절 (Take Profit) - 부분 익절 지원 ===
  use_tp1?: boolean;           // 1차 익절 사용
  tp1_percent?: number;        // 1차 익절 비율 % (기본: 1.0)
  tp1_close_percent?: number;  // 1차 익절 청산 비율 % (기본: 50.0)

  use_tp2?: boolean;           // 2차 익절 사용
  tp2_percent?: number;        // 2차 익절 비율 % (기본: 2.0)
  tp2_close_percent?: number;  // 2차 익절 청산 비율 % (기본: 25.0)

  use_tp3?: boolean;           // 3차 익절 사용
  tp3_percent?: number;        // 3차 익절 비율 % (기본: 3.0)
  tp3_close_percent?: number;  // 3차 익절 청산 비율 % (기본: 100.0)

  // === 트레일링 스톱 ===
  use_trailing_stop?: boolean;           // 트레일링 스톱 사용
  trailing_stop_percent?: number;        // 트레일링 스톱 비율 %
  trailing_activation_percent?: number;  // 트레일링 시작 수익 비율 %

  // === Break Even (신규!) ===
  use_break_even?: boolean;      // TP1 hit → SL을 평균단가로 이동 (기본: true)
  use_break_even_tp2?: boolean;  // TP2 hit → SL을 TP1 가격으로 이동 (기본: true)
  use_break_even_tp3?: boolean;  // TP3 hit → SL을 TP2 가격으로 이동 (기본: true)

  // === DCA/피라미딩 (실험적) ===
  use_dca?: boolean;               // DCA 사용
  dca_max_orders?: number;         // 최대 DCA 주문 수
  dca_price_step_percent?: number; // DCA 가격 간격 %
  dca_size_multiplier?: number;    // DCA 물량 승수

  use_pyramiding?: boolean;        // 피라미딩 사용
  pyramiding_max_orders?: number;  // 최대 피라미딩 주문 수
}

/**
 * 백테스트 시작 응답
 */
export interface BacktestStartResponse {
  backtest_id: string;  // UUID
  status: 'pending' | 'running';
  message: string;
}

/**
 * 백테스트 결과 응답
 */
export interface BacktestResultResponse {
  backtest_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';

  // 진행 중일 때
  progress?: number;
  message?: string;

  // 완료되었을 때
  config?: BacktestConfig;
  results?: BacktestResults;
  equity_curve?: EquityPoint[];
  trades?: Trade[];
  created_at?: string;
  completed_at?: string;
}

/**
 * 백테스트 설정
 */
export interface BacktestConfig {
  symbol: string;
  timeframe: string;
  start_date: string;
  end_date: string;
  initial_capital: number;
  strategy_name: string;
  strategy_params: HyperRSIParams;
}

/**
 * 백테스트 성능 결과
 */
export interface BacktestResults {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;              // 승률 %
  total_pnl: number;             // 총 손익 USDT
  total_pnl_percent: number;     // 총 손익률 %
  max_drawdown: number;          // 최대 낙폭 USDT
  max_drawdown_percent: number;  // 최대 낙폭 %
  sharpe_ratio: number;          // 샤프 비율
  profit_factor: number;         // 수익 팩터
  average_win: number;           // 평균 수익
  average_loss: number;          // 평균 손실
  largest_win: number;           // 최대 수익
  largest_loss: number;          // 최대 손실
  total_fees: number;            // 총 수수료
  avg_holding_time_minutes: number;  // 평균 보유 시간 (분)
}

/**
 * 자산 곡선 데이터 포인트
 */
export interface EquityPoint {
  timestamp: string;
  equity: number;
}

/**
 * 거래 기록
 */
export interface Trade {
  trade_id: number;
  entry_time: string;
  exit_time: string | null;
  side: 'long' | 'short';
  entry_price: number;           // 평균 진입가 (DCA 시 가중평균)
  exit_price: number | null;
  size: number;                  // 총 포지션 크기
  pnl: number | null;
  pnl_percent: number | null;
  fees: number;
  exit_reason: string | null;    // "tp1" | "tp2" | "tp3" | "stop_loss" | "trailing_stop" | "signal" | "backtest_end"

  // TP/SL 가격 정보 (신규!)
  tp1_price?: number | null;     // 1차 익절 목표가
  tp2_price?: number | null;     // 2차 익절 목표가
  tp3_price?: number | null;     // 3차 익절 목표가
  stop_loss_price?: number | null;  // 손절가 (break-even 적용 시 변경됨)

  // DCA 정보 (신규!)
  next_dca_levels?: number[];    // 다음 DCA 진입 레벨들 (가격 배열)
  dca_count?: number;            // DCA 진입 횟수 (0 = 초기 진입만)
  total_investment?: number;     // 총 투자 금액 (USDT)
  entry_history?: EntryRecord[]; // 진입 이력 (DCA 포함)

  // 부분 익절 메타데이터
  is_partial_exit?: boolean;     // 부분 익절 여부
  tp_level?: 1 | 2 | 3 | null;   // 어떤 TP 레벨에서 청산되었는지
  exit_ratio?: number | null;    // 청산 비율 (0-1)
  remaining_quantity?: number | null;  // 남은 포지션 크기
}

/**
 * 진입 기록 (DCA 추적용)
 */
export interface EntryRecord {
  price: number;          // 진입 가격
  quantity: number;       // 진입 수량
  investment: number;     // 투자 금액 (USDT)
  timestamp: string;      // 진입 시간
  reason: string;         // 진입 이유 (예: "initial_entry", "dca_entry")
  dca_count: number;      // DCA 카운트 (0 = 초기 진입)
}

/**
 * 데이터 검증 응답
 */
export interface DataValidationResponse {
  valid: boolean;
  candle_count: number;
  expected_count?: number;
  start_date: string;
  end_date: string;
  missing_periods?: MissingPeriod[];
  data_quality: DataQuality;
}

export interface MissingPeriod {
  start: string;
  end: string;
  missing_candles: number;
}

export interface DataQuality {
  completeness: number;      // 0-100%
  gap_count: number;
  largest_gap_minutes: number;
}
```

---

## 프론트엔드 데이터 처리 가이드

### 백테스트 결과 해석하기

백테스트 API에서 받은 데이터를 프론트엔드에서 효과적으로 처리하는 방법을 설명합니다.

#### 1. 거래(Trade) 데이터 이해하기

**1-1. 기본 거래 vs 부분 익절 거래 구분**

```typescript
function isPartialExit(trade: Trade): boolean {
  return trade.is_partial_exit === true;
}

function isFullExit(trade: Trade): boolean {
  return !trade.is_partial_exit;
}

// 예시: 거래 리스트 필터링
const partialExits = trades.filter(isPartialExit);
const fullExits = trades.filter(isFullExit);
```

**1-2. 평균 진입가 vs 청산가 계산**

```typescript
function calculateProfitLoss(trade: Trade) {
  if (!trade.exit_price) return null;

  const entryValue = trade.entry_price * trade.size;
  const exitValue = trade.exit_price * trade.size;

  return {
    absolutePnL: trade.pnl,           // 수수료 차감 후 순손익
    percentPnL: trade.pnl_percent,    // 수익률 (%)
    priceChange: trade.side === 'long'
      ? trade.exit_price - trade.entry_price
      : trade.entry_price - trade.exit_price
  };
}
```

**1-3. DCA 거래 식별 및 처리**

```typescript
function isDCAPosition(trade: Trade): boolean {
  return (trade.dca_count ?? 0) > 0;
}

function getAverageEntryPrice(trade: Trade): number {
  // entry_price는 이미 가중평균 계산된 값
  return trade.entry_price;
}

function getTotalInvestment(trade: Trade): number {
  // DCA 포함 총 투자금액
  return trade.total_investment ?? (trade.entry_price * trade.size);
}

// DCA 진입 이력 표시
function DCAHistoryDisplay({ trade }: { trade: Trade }) {
  if (!isDCAPosition(trade)) {
    return <div>단일 진입</div>;
  }

  return (
    <div className="space-y-2">
      <p>총 {trade.dca_count! + 1}회 진입</p>
      <p>평균 진입가: ${trade.entry_price.toFixed(2)}</p>
      <p>총 투자: ${trade.total_investment!.toFixed(2)} USDT</p>

      {trade.entry_history?.map((entry, idx) => (
        <div key={idx} className="text-sm">
          {entry.reason}: ${entry.price.toFixed(2)} × {entry.quantity.toFixed(4)}
        </div>
      ))}
    </div>
  );
}
```

**1-4. TP/SL 가격 표시**

```typescript
function TradeTargetsDisplay({ trade }: { trade: Trade }) {
  return (
    <div className="grid grid-cols-2 gap-4">
      {/* 익절 목표가 */}
      <div>
        <h4 className="font-semibold">익절 목표가</h4>
        {trade.tp1_price && <p>TP1: ${trade.tp1_price.toFixed(2)}</p>}
        {trade.tp2_price && <p>TP2: ${trade.tp2_price.toFixed(2)}</p>}
        {trade.tp3_price && <p>TP3: ${trade.tp3_price.toFixed(2)}</p>}
      </div>

      {/* 손절가 */}
      <div>
        <h4 className="font-semibold">손절가</h4>
        {trade.stop_loss_price && (
          <p className="text-red-600">
            SL: ${trade.stop_loss_price.toFixed(2)}
          </p>
        )}
      </div>
    </div>
  );
}
```

**1-5. 다음 DCA 레벨 표시**

```typescript
function NextDCALevelsDisplay({ trade }: { trade: Trade }) {
  if (!trade.next_dca_levels || trade.next_dca_levels.length === 0) {
    return <div>DCA 설정 없음</div>;
  }

  return (
    <div className="space-y-2">
      <h4 className="font-semibold">다음 DCA 진입 레벨</h4>
      <div className="space-y-1">
        {trade.next_dca_levels.map((price, idx) => (
          <div key={idx} className="flex justify-between">
            <span>DCA {idx + 1}:</span>
            <span className="font-mono">${price.toFixed(2)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

#### 2. 종료 이유(Exit Reason) 해석

```typescript
type ExitReasonType =
  | 'tp1' | 'tp2' | 'tp3'              // 부분 익절
  | 'take_profit'                       // 전체 익절
  | 'stop_loss'                         // 손절
  | 'trailing_stop'                     // 트레일링 스톱
  | 'signal'                            // 트렌드 반전 시그널
  | 'backtest_end';                     // 백테스트 종료 시 강제청산

function getExitReasonLabel(reason: string): string {
  const labels: Record<string, string> = {
    'tp1': '1차 익절 (TP1)',
    'tp2': '2차 익절 (TP2)',
    'tp3': '3차 익절 (TP3)',
    'take_profit': '익절',
    'stop_loss': '손절',
    'trailing_stop': '트레일링 스톱',
    'signal': '트렌드 반전',
    'backtest_end': '백테스트 종료'
  };
  return labels[reason] || reason;
}

function getExitReasonColor(reason: string): string {
  if (reason.startsWith('tp')) return 'text-green-600';
  if (reason === 'take_profit') return 'text-green-600';
  if (reason === 'stop_loss') return 'text-red-600';
  if (reason === 'trailing_stop') return 'text-yellow-600';
  if (reason === 'signal') return 'text-blue-600';
  return 'text-gray-600';
}

// 사용 예시
function ExitReasonBadge({ reason }: { reason: string }) {
  return (
    <span className={`px-2 py-1 rounded text-sm ${getExitReasonColor(reason)}`}>
      {getExitReasonLabel(reason)}
    </span>
  );
}
```

#### 3. 부분 익절 거래 그룹화

동일 포지션의 부분 익절 거래들을 그룹화하여 표시:

```typescript
interface TradeGroup {
  initialTrade: Trade;      // 최초 진입
  partialExits: Trade[];    // 부분 익절들
  finalExit?: Trade;        // 최종 청산
  totalPnL: number;         // 총 손익
  totalFees: number;        // 총 수수료
}

function groupPartialExits(trades: Trade[]): TradeGroup[] {
  const groups: Map<string, TradeGroup> = new Map();

  // 시간순 정렬
  const sortedTrades = [...trades].sort((a, b) =>
    new Date(a.entry_time).getTime() - new Date(b.entry_time).getTime()
  );

  for (const trade of sortedTrades) {
    const key = `${trade.entry_time}_${trade.side}`;

    if (!groups.has(key)) {
      groups.set(key, {
        initialTrade: trade,
        partialExits: [],
        totalPnL: 0,
        totalFees: 0
      });
    }

    const group = groups.get(key)!;

    if (trade.is_partial_exit) {
      group.partialExits.push(trade);
    } else if (trade.exit_time) {
      group.finalExit = trade;
    }

    group.totalPnL += trade.pnl ?? 0;
    group.totalFees += trade.fees;
  }

  return Array.from(groups.values());
}

// 그룹화된 거래 표시 컴포넌트
function TradeGroupDisplay({ group }: { group: TradeGroup }) {
  const { initialTrade, partialExits, finalExit, totalPnL } = group;

  return (
    <div className="border rounded-lg p-4 space-y-3">
      {/* 초기 진입 */}
      <div className="flex justify-between items-center">
        <div>
          <span className={`font-semibold ${
            initialTrade.side === 'long' ? 'text-green-600' : 'text-red-600'
          }`}>
            {initialTrade.side.toUpperCase()}
          </span>
          <span className="ml-2">${initialTrade.entry_price.toFixed(2)}</span>
          <span className="ml-2 text-gray-500">
            {new Date(initialTrade.entry_time).toLocaleString()}
          </span>
        </div>
        <div className={`font-bold ${totalPnL >= 0 ? 'text-green-600' : 'text-red-600'}`}>
          {totalPnL >= 0 ? '+' : ''}{totalPnL.toFixed(2)} USDT
        </div>
      </div>

      {/* 부분 익절들 */}
      {partialExits.length > 0 && (
        <div className="ml-4 space-y-2 border-l-2 border-green-200 pl-4">
          {partialExits.map((exit, idx) => (
            <div key={idx} className="flex justify-between text-sm">
              <div>
                <ExitReasonBadge reason={exit.exit_reason!} />
                <span className="ml-2">${exit.exit_price?.toFixed(2)}</span>
                <span className="ml-2 text-gray-500">
                  ({(exit.exit_ratio! * 100).toFixed(0)}% 청산)
                </span>
              </div>
              <span className="text-green-600">
                +{exit.pnl?.toFixed(2)} USDT
              </span>
            </div>
          ))}
        </div>
      )}

      {/* 최종 청산 */}
      {finalExit && (
        <div className="ml-4 border-l-2 border-gray-200 pl-4 text-sm">
          <div className="flex justify-between">
            <div>
              <ExitReasonBadge reason={finalExit.exit_reason!} />
              <span className="ml-2">${finalExit.exit_price?.toFixed(2)}</span>
              <span className="ml-2 text-gray-500">
                ({new Date(finalExit.exit_time!).toLocaleString()})
              </span>
            </div>
            <span className={finalExit.pnl! >= 0 ? 'text-green-600' : 'text-red-600'}>
              {finalExit.pnl! >= 0 ? '+' : ''}{finalExit.pnl?.toFixed(2)} USDT
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
```

#### 4. 자산 곡선(Equity Curve) 시각화

```typescript
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

function EquityCurveChart({ equityCurve }: { equityCurve: EquityPoint[] }) {
  const data = equityCurve.map(point => ({
    time: new Date(point.timestamp).toLocaleDateString(),
    equity: point.equity,
    timestamp: point.timestamp
  }));

  const initialEquity = data[0]?.equity ?? 0;
  const finalEquity = data[data.length - 1]?.equity ?? 0;
  const totalReturn = ((finalEquity - initialEquity) / initialEquity) * 100;

  return (
    <div className="space-y-4">
      <div className="flex justify-between">
        <div>
          <p className="text-gray-600">초기 자본</p>
          <p className="text-2xl font-bold">${initialEquity.toFixed(2)}</p>
        </div>
        <div>
          <p className="text-gray-600">최종 자본</p>
          <p className={`text-2xl font-bold ${finalEquity >= initialEquity ? 'text-green-600' : 'text-red-600'}`}>
            ${finalEquity.toFixed(2)}
          </p>
        </div>
        <div>
          <p className="text-gray-600">총 수익률</p>
          <p className={`text-2xl font-bold ${totalReturn >= 0 ? 'text-green-600' : 'text-red-600'}`}>
            {totalReturn >= 0 ? '+' : ''}{totalReturn.toFixed(2)}%
          </p>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={400}>
        <LineChart data={data}>
          <XAxis
            dataKey="time"
            tick={{ fontSize: 12 }}
          />
          <YAxis
            tick={{ fontSize: 12 }}
            domain={['auto', 'auto']}
          />
          <Tooltip
            formatter={(value: number) => `$${value.toFixed(2)}`}
            labelFormatter={(label) => `날짜: ${label}`}
          />
          <Line
            type="monotone"
            dataKey="equity"
            stroke="#3b82f6"
            strokeWidth={2}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

#### 5. 성능 메트릭 대시보드

```typescript
function PerformanceMetricsDashboard({ results }: { results: BacktestResults }) {
  const metrics = [
    {
      label: '총 거래',
      value: results.total_trades,
      color: 'text-blue-600'
    },
    {
      label: '승률',
      value: `${results.win_rate.toFixed(2)}%`,
      color: results.win_rate >= 50 ? 'text-green-600' : 'text-red-600'
    },
    {
      label: '총 손익',
      value: `${results.total_pnl >= 0 ? '+' : ''}${results.total_pnl.toFixed(2)} USDT`,
      color: results.total_pnl >= 0 ? 'text-green-600' : 'text-red-600'
    },
    {
      label: '수익률',
      value: `${results.total_pnl_percent >= 0 ? '+' : ''}${results.total_pnl_percent.toFixed(2)}%`,
      color: results.total_pnl_percent >= 0 ? 'text-green-600' : 'text-red-600'
    },
    {
      label: '최대 낙폭',
      value: `${results.max_drawdown_percent.toFixed(2)}%`,
      color: 'text-red-600'
    },
    {
      label: '샤프 비율',
      value: results.sharpe_ratio.toFixed(2),
      color: results.sharpe_ratio >= 1.5 ? 'text-green-600' : 'text-yellow-600'
    },
    {
      label: '수익 팩터',
      value: results.profit_factor.toFixed(2),
      color: results.profit_factor >= 2.0 ? 'text-green-600' : 'text-yellow-600'
    },
    {
      label: '평균 보유 시간',
      value: formatDuration(results.avg_holding_time_minutes),
      color: 'text-gray-600'
    }
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {metrics.map((metric, idx) => (
        <div key={idx} className="border rounded-lg p-4">
          <p className="text-sm text-gray-600">{metric.label}</p>
          <p className={`text-2xl font-bold ${metric.color}`}>
            {metric.value}
          </p>
        </div>
      ))}
    </div>
  );
}

function formatDuration(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const mins = Math.floor(minutes % 60);

  if (hours > 24) {
    const days = Math.floor(hours / 24);
    const remainingHours = hours % 24;
    return `${days}일 ${remainingHours}시간`;
  }

  return `${hours}시간 ${mins}분`;
}
```

---

### React 컴포넌트 예제

#### 1. 백테스트 설정 폼

```typescript
// components/BacktestForm.tsx

import React, { useState } from 'react';
import { BacktestRequest, HyperRSIParams } from '../types/backtest';

export function BacktestForm() {
  const [formData, setFormData] = useState<BacktestRequest>({
    symbol: 'BTC/USDT:USDT',
    timeframe: '15m',
    start_date: '2025-01-01T00:00:00',
    end_date: '2025-02-01T00:00:00',
    initial_capital: 10000,
    strategy_params: {
      rsi_period: 5,
      rsi_ob: 70,
      rsi_os: 30,
      use_trend_close: true,
    }
  });

  const updateStrategyParam = <K extends keyof HyperRSIParams>(
    key: K,
    value: HyperRSIParams[K]
  ) => {
    setFormData(prev => ({
      ...prev,
      strategy_params: {
        ...prev.strategy_params,
        [key]: value
      }
    }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    try {
      const response = await fetch('http://localhost:8013/api/v1/backtest/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData)
      });

      if (!response.ok) throw new Error('Backtest failed');

      const result = await response.json();
      console.log('Backtest started:', result.backtest_id);
    } catch (error) {
      console.error('Error:', error);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {/* 기본 설정 */}
      <div className="space-y-4">
        <h3 className="text-lg font-semibold">기본 설정</h3>

        <input
          type="text"
          placeholder="Symbol"
          value={formData.symbol}
          onChange={(e) => setFormData({...formData, symbol: e.target.value})}
          className="w-full px-3 py-2 border rounded"
        />

        <select
          value={formData.timeframe}
          onChange={(e) => setFormData({...formData, timeframe: e.target.value})}
          className="w-full px-3 py-2 border rounded"
        >
          <option value="1m">1분</option>
          <option value="5m">5분</option>
          <option value="15m">15분</option>
          <option value="1h">1시간</option>
          <option value="4h">4시간</option>
        </select>

        {/* 거래 방향 설정 */}
        <div className="space-y-2">
          <label className="block text-sm font-medium text-gray-700">거래 방향</label>
          <select
            value={formData.strategy_params.direction ?? 'both'}
            onChange={(e) => updateStrategyParam('direction', e.target.value as 'long' | 'short' | 'both')}
            className="w-full px-3 py-2 border rounded"
          >
            <option value="both">양방향 (롱 + 숏)</option>
            <option value="long">롱만</option>
            <option value="short">숏만</option>
          </select>
        </div>
      </div>

      {/* 트렌드 반전 종료 */}
      <TrendReversalSettings
        value={formData.strategy_params.use_trend_close ?? true}
        onChange={(value) => updateStrategyParam('use_trend_close', value)}
      />

      {/* 손절 설정 */}
      <StopLossSettings
        params={formData.strategy_params}
        onChange={updateStrategyParam}
      />

      {/* 부분 익절 설정 */}
      <PartialExitsSettings
        params={formData.strategy_params}
        onChange={updateStrategyParam}
      />

      <button
        type="submit"
        className="w-full px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
      >
        백테스트 실행
      </button>
    </form>
  );
}
```

#### 2. 트렌드 반전 종료 설정

```typescript
// components/TrendReversalSettings.tsx

import React from 'react';

interface Props {
  value: boolean;
  onChange: (value: boolean) => void;
}

export function TrendReversalSettings({ value, onChange }: Props) {
  return (
    <div className="space-y-3 p-4 border rounded-lg bg-blue-50">
      <div className="flex items-center justify-between">
        <div>
          <h4 className="font-semibold text-blue-900">🔄 트렌드 반전 종료</h4>
          <p className="text-sm text-blue-700">
            강한 트렌드 반전 감지 시 자동으로 포지션 종료
          </p>
        </div>
        <label className="relative inline-flex items-center cursor-pointer">
          <input
            type="checkbox"
            checked={value}
            onChange={(e) => onChange(e.target.checked)}
            className="sr-only peer"
          />
          <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
        </label>
      </div>

      {value && (
        <div className="text-sm space-y-2 text-blue-800 bg-blue-100 p-3 rounded">
          <p className="font-medium">동작 방식:</p>
          <ul className="list-disc list-inside space-y-1">
            <li>롱: 강한 하락 트렌드(-2) 감지 시 종료</li>
            <li>숏: 강한 상승 트렌드(+2) 감지 시 종료</li>
            <li>⚡ 최우선 종료 조건 (TP/SL보다 먼저 체크)</li>
          </ul>
        </div>
      )}
    </div>
  );
}
```

#### 3. 손절 설정 컴포넌트

```typescript
// components/StopLossSettings.tsx

import React from 'react';
import { HyperRSIParams } from '../types/backtest';

interface Props {
  params: HyperRSIParams;
  onChange: <K extends keyof HyperRSIParams>(
    key: K,
    value: HyperRSIParams[K]
  ) => void;
}

export function StopLossSettings({ params, onChange }: Props) {
  const [useNewSystem, setUseNewSystem] = React.useState(false);

  return (
    <div className="space-y-4 p-4 border rounded-lg">
      <h4 className="font-semibold">🛡️ 손절 (Stop Loss)</h4>

      {/* 시스템 선택 */}
      <div className="flex gap-4">
        <label className="flex items-center gap-2">
          <input
            type="radio"
            checked={!useNewSystem}
            onChange={() => setUseNewSystem(false)}
          />
          <span>레거시 시스템 (간단)</span>
        </label>
        <label className="flex items-center gap-2">
          <input
            type="radio"
            checked={useNewSystem}
            onChange={() => setUseNewSystem(true)}
          />
          <span>새 시스템 (고급)</span>
        </label>
      </div>

      {/* 레거시 시스템 */}
      {!useNewSystem && (
        <div className="flex items-center gap-4">
          <label className="w-32">손절 비율 (%):</label>
          <input
            type="number"
            step="0.1"
            value={params.stop_loss_percent ?? ''}
            onChange={(e) => onChange('stop_loss_percent', parseFloat(e.target.value))}
            placeholder="예: 2.8"
            className="w-32 px-3 py-2 border rounded"
          />
          <span className="text-sm text-gray-600">
            모든 포지션에 일괄 적용
          </span>
        </div>
      )}

      {/* 새 시스템 */}
      {useNewSystem && (
        <div className="space-y-3">
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={params.use_sl ?? false}
                onChange={(e) => onChange('use_sl', e.target.checked)}
              />
              <span>일반 손절</span>
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={params.use_sl_on_last ?? false}
                onChange={(e) => onChange('use_sl_on_last', e.target.checked)}
              />
              <span>마지막 진입만 손절 (DCA용)</span>
            </label>
          </div>

          {(params.use_sl || params.use_sl_on_last) && (
            <>
              <div className="flex items-center gap-4">
                <label className="w-32">손절 값:</label>
                <input
                  type="number"
                  step="0.1"
                  value={params.sl_value ?? 5.0}
                  onChange={(e) => onChange('sl_value', parseFloat(e.target.value))}
                  className="w-32 px-3 py-2 border rounded"
                />
              </div>

              <div className="flex items-center gap-4">
                <label className="w-32">손절 옵션:</label>
                <select
                  value={params.sl_option ?? 'percentage'}
                  onChange={(e) => onChange('sl_option', e.target.value as 'percentage' | 'price')}
                  className="px-3 py-2 border rounded"
                >
                  <option value="percentage">퍼센트 (%) 기준</option>
                  <option value="price">절대 가격 기준</option>
                </select>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
```

#### 4. 부분 익절 설정 컴포넌트

```typescript
// components/PartialExitsSettings.tsx

import React from 'react';
import { HyperRSIParams } from '../types/backtest';

interface Props {
  params: HyperRSIParams;
  onChange: <K extends keyof HyperRSIParams>(
    key: K,
    value: HyperRSIParams[K]
  ) => void;
}

export function PartialExitsSettings({ params, onChange }: Props) {
  const totalRatio =
    (params.use_tp1 ? params.tp1_close_percent ?? 50 : 0) +
    (params.use_tp2 ? params.tp2_close_percent ?? 25 : 0) +
    (params.use_tp3 ? params.tp3_close_percent ?? 100 : 0);

  return (
    <div className="space-y-4 p-4 border rounded-lg">
      <h4 className="font-semibold">🎯 부분 익절 (Partial Exits)</h4>

      {/* TP1 */}
      <div className="space-y-2">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={params.use_tp1 ?? false}
            onChange={(e) => onChange('use_tp1', e.target.checked)}
          />
          <span className="font-medium">TP1 (1차 익절)</span>
        </label>

        {params.use_tp1 && (
          <div className="flex items-center gap-4 ml-6">
            <input
              type="number"
              step="0.1"
              value={params.tp1_percent ?? 1.0}
              onChange={(e) => onChange('tp1_percent', parseFloat(e.target.value))}
              className="w-24 px-3 py-2 border rounded"
            />
            <span>% 수익 시</span>
            <input
              type="number"
              value={params.tp1_close_percent ?? 50}
              onChange={(e) => onChange('tp1_close_percent', parseInt(e.target.value))}
              className="w-24 px-3 py-2 border rounded"
            />
            <span>% 청산</span>
          </div>
        )}
      </div>

      {/* TP2 */}
      <div className="space-y-2">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={params.use_tp2 ?? false}
            onChange={(e) => onChange('use_tp2', e.target.checked)}
          />
          <span className="font-medium">TP2 (2차 익절)</span>
        </label>

        {params.use_tp2 && (
          <div className="flex items-center gap-4 ml-6">
            <input
              type="number"
              step="0.1"
              value={params.tp2_percent ?? 2.0}
              onChange={(e) => onChange('tp2_percent', parseFloat(e.target.value))}
              className="w-24 px-3 py-2 border rounded"
            />
            <span>% 수익 시</span>
            <input
              type="number"
              value={params.tp2_close_percent ?? 25}
              onChange={(e) => onChange('tp2_close_percent', parseInt(e.target.value))}
              className="w-24 px-3 py-2 border rounded"
            />
            <span>% 청산</span>
          </div>
        )}
      </div>

      {/* TP3 */}
      <div className="space-y-2">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={params.use_tp3 ?? false}
            onChange={(e) => onChange('use_tp3', e.target.checked)}
          />
          <span className="font-medium">TP3 (3차 익절)</span>
        </label>

        {params.use_tp3 && (
          <div className="flex items-center gap-4 ml-6">
            <input
              type="number"
              step="0.1"
              value={params.tp3_percent ?? 3.0}
              onChange={(e) => onChange('tp3_percent', parseFloat(e.target.value))}
              className="w-24 px-3 py-2 border rounded"
            />
            <span>% 수익 시</span>
            <input
              type="number"
              value={params.tp3_close_percent ?? 100}
              onChange={(e) => onChange('tp3_close_percent', parseInt(e.target.value))}
              className="w-24 px-3 py-2 border rounded"
            />
            <span>% 청산</span>
          </div>
        )}
      </div>

      {/* 유효성 검증 */}
      {totalRatio > 0 && (
        <div className={`p-3 rounded text-sm ${
          totalRatio > 100
            ? 'bg-red-100 text-red-800'
            : totalRatio === 100
            ? 'bg-green-100 text-green-800'
            : 'bg-yellow-100 text-yellow-800'
        }`}>
          {totalRatio > 100 && `⚠️ 청산 비율 합계가 100%를 초과합니다 (${totalRatio}%)`}
          {totalRatio === 100 && `✓ 전체 포지션이 청산됩니다 (${totalRatio}%)`}
          {totalRatio < 100 && `ℹ️ ${100 - totalRatio}%는 청산되지 않습니다`}
        </div>
      )}
    </div>
  );
}
```

#### 5. Break Even 설정 컴포넌트

```typescript
// components/BreakEvenSettings.tsx

import React from 'react';
import { HyperRSIParams } from '../types/backtest';

interface Props {
  params: HyperRSIParams;
  onChange: <K extends keyof HyperRSIParams>(
    key: K,
    value: HyperRSIParams[K]
  ) => void;
}

export function BreakEvenSettings({ params, onChange }: Props) {
  // TP 사용 여부 확인
  const hasTP1 = params.use_tp1 ?? false;
  const hasTP2 = params.use_tp2 ?? false;
  const hasTP3 = params.use_tp3 ?? false;

  // 적어도 하나의 TP가 활성화되어 있어야 break-even 설정 가능
  const canEnableBreakEven = hasTP1 || hasTP2 || hasTP3;

  if (!canEnableBreakEven) {
    return (
      <div className="p-4 border rounded-lg bg-gray-50">
        <h4 className="font-semibold text-gray-500">🔒 Break Even (손익분기점 보호)</h4>
        <p className="text-sm text-gray-500 mt-2">
          Break Even 기능을 사용하려면 먼저 부분 익절(TP)을 활성화하세요.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4 p-4 border rounded-lg bg-blue-50">
      <div className="flex items-center justify-between">
        <div>
          <h4 className="font-semibold text-blue-900">🔒 Break Even (손익분기점 보호)</h4>
          <p className="text-sm text-blue-700">
            부분 익절 후 손절가를 자동으로 조정하여 손실 리스크 감소
          </p>
        </div>
      </div>

      <div className="space-y-3">
        {/* TP1 → Entry Price */}
        {hasTP1 && (
          <div className="flex items-center justify-between p-3 bg-white rounded">
            <div className="flex-1">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={params.use_break_even ?? true}
                  onChange={(e) => onChange('use_break_even', e.target.checked)}
                  className="w-4 h-4"
                />
                <div>
                  <span className="font-medium">TP1 후 Break Even</span>
                  <p className="text-sm text-gray-600">
                    TP1 도달 시 → 손절가를 <strong>평균 진입가</strong>로 이동
                  </p>
                </div>
              </label>
            </div>
            <span className="text-green-600 font-mono text-sm">
              SL → Entry
            </span>
          </div>
        )}

        {/* TP2 → TP1 Price */}
        {hasTP2 && (
          <div className="flex items-center justify-between p-3 bg-white rounded">
            <div className="flex-1">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={params.use_break_even_tp2 ?? true}
                  onChange={(e) => onChange('use_break_even_tp2', e.target.checked)}
                  className="w-4 h-4"
                  disabled={!hasTP1}
                />
                <div>
                  <span className="font-medium">TP2 후 Break Even</span>
                  <p className="text-sm text-gray-600">
                    TP2 도달 시 → 손절가를 <strong>TP1 가격</strong>으로 이동
                  </p>
                </div>
              </label>
            </div>
            <span className="text-green-600 font-mono text-sm">
              SL → TP1
            </span>
          </div>
        )}

        {/* TP3 → TP2 Price */}
        {hasTP3 && (
          <div className="flex items-center justify-between p-3 bg-white rounded">
            <div className="flex-1">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={params.use_break_even_tp3 ?? true}
                  onChange={(e) => onChange('use_break_even_tp3', e.target.checked)}
                  className="w-4 h-4"
                  disabled={!hasTP2}
                />
                <div>
                  <span className="font-medium">TP3 후 Break Even</span>
                  <p className="text-sm text-gray-600">
                    TP3 도달 시 → 손절가를 <strong>TP2 가격</strong>으로 이동
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    ⚠️ TP 합계가 100% 미만일 때만 적용됨
                  </p>
                </div>
              </label>
            </div>
            <span className="text-green-600 font-mono text-sm">
              SL → TP2
            </span>
          </div>
        )}
      </div>

      {/* 설명 */}
      <div className="text-sm text-blue-800 bg-blue-100 p-3 rounded">
        <p className="font-medium">💡 Break Even 작동 원리:</p>
        <ul className="list-disc list-inside space-y-1 mt-2">
          <li>부분 익절이 실행되면 손절가가 자동으로 상승하여 리스크 감소</li>
          <li>최악의 경우에도 손실 없이 포지션 종료 가능</li>
          <li>수익을 보호하면서 남은 포지션으로 추가 수익 추구</li>
        </ul>
      </div>

      {/* 시각적 예시 */}
      <div className="text-sm bg-white p-3 rounded border border-blue-200">
        <p className="font-medium mb-2">예시 시나리오:</p>
        <div className="space-y-1 font-mono text-xs">
          <div>진입: $100 (SL: $97)</div>
          <div className="text-green-600">→ TP1 Hit ($101.5) → SL 이동: $97 → <strong>$100</strong> ✅</div>
          <div className="text-green-600">→ TP2 Hit ($103) → SL 이동: $100 → <strong>$101.5</strong> ✅</div>
          <div className="text-green-600">→ TP3 Hit ($105) → SL 이동: $101.5 → <strong>$103</strong> ✅</div>
          <div className="text-gray-600 mt-2">결과: 최소 수익 보장 상태로 포지션 유지</div>
        </div>
      </div>
    </div>
  );
}
```

#### 6. API 호출 유틸리티

```typescript
// api/backtest.ts

import {
  BacktestRequest,
  BacktestStartResponse,
  BacktestResultResponse,
  DataValidationResponse
} from '../types/backtest';

const API_BASE = 'http://localhost:8013/api/v1/backtest';

/**
 * 백테스트 실행
 */
export async function runBacktest(
  request: BacktestRequest
): Promise<BacktestStartResponse> {
  const response = await fetch(`${API_BASE}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request)
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Backtest failed');
  }

  return response.json();
}

/**
 * 백테스트 결과 조회
 */
export async function getBacktestResult(
  backtestId: string
): Promise<BacktestResultResponse> {
  const response = await fetch(`${API_BASE}/${backtestId}`);

  if (!response.ok) {
    throw new Error('Backtest not found');
  }

  return response.json();
}

/**
 * 백테스트 삭제
 */
export async function deleteBacktest(backtestId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/${backtestId}`, {
    method: 'DELETE'
  });

  if (!response.ok) {
    throw new Error('Failed to delete backtest');
  }
}

/**
 * 데이터 유효성 검증
 */
export async function validateData(params: {
  symbol: string;
  timeframe: string;
  start_date: string;
  end_date: string;
  data_source?: string;
}): Promise<DataValidationResponse> {
  const query = new URLSearchParams(params as any).toString();
  const response = await fetch(`${API_BASE}/validate/data?${query}`);

  if (!response.ok) {
    throw new Error('Validation failed');
  }

  return response.json();
}

/**
 * 백테스트 상태 폴링 (완료까지 대기)
 */
export async function waitForBacktest(
  backtestId: string,
  onProgress?: (progress: number) => void
): Promise<BacktestResultResponse> {
  while (true) {
    const result = await getBacktestResult(backtestId);

    if (result.status === 'completed') {
      return result;
    }

    if (result.status === 'failed') {
      throw new Error('Backtest failed');
    }

    if (result.progress && onProgress) {
      onProgress(result.progress);
    }

    // 2초 대기 후 재시도
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
}
```

#### 6. 사용 예제

```typescript
// 예제: 백테스트 실행하고 결과 대기

import { runBacktest, waitForBacktest } from './api/backtest';

async function example() {
  // 1. 백테스트 실행
  const startResponse = await runBacktest({
    symbol: 'BTC/USDT:USDT',
    timeframe: '15m',
    start_date: '2025-01-01T00:00:00',
    end_date: '2025-02-01T00:00:00',
    initial_capital: 10000,
    strategy_params: {
      rsi_period: 5,
      use_trend_close: true,
      stop_loss_percent: 2.8,
      use_tp1: true,
      tp1_percent: 1.5,
      tp1_close_percent: 50
    }
  });

  console.log('Backtest started:', startResponse.backtest_id);

  // 2. 결과 대기 (진행률 표시)
  const result = await waitForBacktest(
    startResponse.backtest_id,
    (progress) => console.log(`Progress: ${progress.toFixed(1)}%`)
  );

  // 3. 결과 출력
  console.log('Results:', result.results);
  console.log(`Total PNL: ${result.results?.total_pnl} USDT`);
  console.log(`Win Rate: ${result.results?.win_rate}%`);
  console.log(`Total Trades: ${result.results?.total_trades}`);
}
```

---

## 1. 백테스트 실행

### `POST /run`

새로운 백테스트를 실행합니다.

#### Request Body

```json
{
  "symbol": "BTC/USDT:USDT",
  "timeframe": "15m",
  "start_date": "2025-01-01T00:00:00",
  "end_date": "2025-03-01T00:00:00",
  "initial_capital": 10000.0,
  "position_size_percent": 100.0,
  "maker_fee": 0.02,
  "taker_fee": 0.05,
  "data_source": "timescale",
  "strategy_name": "hyperrsi",
  "strategy_params": {
    // HyperRSI 전략 파라미터 (아래 섹션 참조)
  }
}
```

#### 필수 파라미터

| 파라미터 | 타입 | 설명 | 예시 |
|---------|------|------|------|
| `symbol` | string | 거래 심볼 (CCXT 형식) | `"BTC/USDT:USDT"` |
| `timeframe` | string | 타임프레임 | `"15m"`, `"1h"`, `"4h"` |
| `start_date` | string | 시작 날짜 (ISO 8601) | `"2025-01-01T00:00:00"` |
| `end_date` | string | 종료 날짜 (ISO 8601) | `"2025-03-01T00:00:00"` |
| `initial_capital` | float | 초기 자본금 (USDT) | `10000.0` |

#### 선택 파라미터

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `position_size_percent` | float | `100.0` | 포지션 크기 (자본금 대비 %) |
| `maker_fee` | float | `0.02` | 메이커 수수료 (%) |
| `taker_fee` | float | `0.05` | 테이커 수수료 (%) |
| `data_source` | string | `"timescale"` | 데이터 소스 (`timescale`, `redis`, `okx`) |
| `strategy_name` | string | `"hyperrsi"` | 전략 이름 |

#### Response

**성공 (200)**:
```json
{
  "backtest_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "Backtest started successfully"
}
```

**실패 (400)**:
```json
{
  "detail": "Invalid date range: start_date must be before end_date"
}
```

#### 예제

```bash
curl -X POST "http://localhost:8013/api/v1/backtest/run" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTC/USDT:USDT",
    "timeframe": "15m",
    "start_date": "2025-01-01T00:00:00",
    "end_date": "2025-02-01T00:00:00",
    "initial_capital": 10000,
    "strategy_params": {
      "rsi_period": 5,
      "rsi_ob": 70,
      "rsi_os": 30,
      "use_trend_close": true,
      "stop_loss_percent": 2.8
    }
  }'
```

---

## 2. 백테스트 결과 조회

### `GET /{backtest_id}`

실행 중이거나 완료된 백테스트의 결과를 조회합니다.

#### Path Parameters

| 파라미터 | 타입 | 설명 |
|---------|------|------|
| `backtest_id` | UUID | 백테스트 ID |

#### Response

**성공 (200)**:
```json
{
  "backtest_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "config": {
    "symbol": "BTC/USDT:USDT",
    "timeframe": "15m",
    "start_date": "2025-01-01T00:00:00",
    "end_date": "2025-02-01T00:00:00",
    "initial_capital": 10000.0,
    "strategy_name": "hyperrsi",
    "strategy_params": { ... }
  },
  "results": {
    "total_trades": 45,
    "winning_trades": 28,
    "losing_trades": 17,
    "win_rate": 62.22,
    "total_pnl": 1523.45,
    "total_pnl_percent": 15.23,
    "max_drawdown": -8.5,
    "max_drawdown_percent": -0.85,
    "sharpe_ratio": 1.85,
    "profit_factor": 2.34,
    "average_win": 125.30,
    "average_loss": -68.90,
    "largest_win": 450.20,
    "largest_loss": -180.50,
    "total_fees": 142.30,
    "avg_holding_time_minutes": 245.5
  },
  "equity_curve": [
    {"timestamp": "2025-01-01T00:00:00", "equity": 10000.0},
    {"timestamp": "2025-01-01T00:15:00", "equity": 10025.5}
  ],
  "trades": [
    {
      "trade_id": 1,
      "entry_time": "2025-01-01T01:30:00",
      "exit_time": "2025-01-01T05:45:00",
      "side": "long",
      "entry_price": 42500.0,
      "exit_price": 43100.0,
      "size": 0.235,
      "pnl": 141.0,
      "pnl_percent": 1.41,
      "fees": 3.2,
      "exit_reason": "take_profit"
    }
  ],
  "created_at": "2025-11-04T10:00:00",
  "completed_at": "2025-11-04T10:05:23"
}
```

**진행 중 (200)**:
```json
{
  "backtest_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "running",
  "progress": 45.5,
  "message": "Processing candles..."
}
```

**실패 (404)**:
```json
{
  "detail": "Backtest not found"
}
```

#### 예제

```bash
curl "http://localhost:8013/api/v1/backtest/550e8400-e29b-41d4-a716-446655440000"
```

---

## 3. 백테스트 삭제

### `DELETE /{backtest_id}`

백테스트 결과를 삭제합니다.

#### Path Parameters

| 파라미터 | 타입 | 설명 |
|---------|------|------|
| `backtest_id` | UUID | 백테스트 ID |

#### Response

**성공 (200)**:
```json
{
  "message": "Backtest deleted successfully"
}
```

**실패 (404)**:
```json
{
  "detail": "Backtest not found"
}
```

#### 예제

```bash
curl -X DELETE "http://localhost:8013/api/v1/backtest/550e8400-e29b-41d4-a716-446655440000"
```

---

## 4. 데이터 유효성 검증

### `GET /validate/data`

지정된 기간의 데이터가 존재하는지 검증합니다.

#### Query Parameters

| 파라미터 | 타입 | 필수 | 설명 |
|---------|------|------|------|
| `symbol` | string | O | 거래 심볼 |
| `timeframe` | string | O | 타임프레임 |
| `start_date` | string | O | 시작 날짜 |
| `end_date` | string | O | 종료 날짜 |
| `data_source` | string | X | 데이터 소스 (기본: `timescale`) |

#### Response

**성공 (200)**:
```json
{
  "valid": true,
  "candle_count": 5832,
  "start_date": "2025-01-01T00:00:00",
  "end_date": "2025-02-01T00:00:00",
  "missing_periods": [],
  "data_quality": {
    "completeness": 100.0,
    "gap_count": 0,
    "largest_gap_minutes": 0
  }
}
```

**데이터 부족 (200)**:
```json
{
  "valid": false,
  "candle_count": 2345,
  "expected_count": 5832,
  "missing_periods": [
    {
      "start": "2025-01-15T03:00:00",
      "end": "2025-01-15T12:00:00",
      "missing_candles": 36
    }
  ],
  "data_quality": {
    "completeness": 40.2,
    "gap_count": 3,
    "largest_gap_minutes": 540
  }
}
```

#### 예제

```bash
curl "http://localhost:8013/api/v1/backtest/validate/data?symbol=BTC/USDT:USDT&timeframe=15m&start_date=2025-01-01T00:00:00&end_date=2025-02-01T00:00:00"
```

---

## HyperRSI 전략 파라미터

### 기본 설정

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `rsi_period` | int | `5` | RSI 계산 기간 |
| `rsi_ob` | int | `70` | RSI 과매수 레벨 |
| `rsi_os` | int | `30` | RSI 과매도 레벨 |
| `direction` | string | `"both"` | 거래 방향 (`"long"`, `"short"`, `"both"`) |

### 트렌드 필터 설정

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `use_trend_filter` | bool | `true` | 트렌드 필터 사용 여부 |
| `ema_period` | int | `7` | 빠른 EMA 기간 |
| `sma_period` | int | `20` | 느린 SMA 기간 |

### 진입 조건 설정

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `entry_option` | string | `"all"` | 진입 조건 옵션 |
| | | | - `"all"`: 모든 조건 만족 시 진입 |
| | | | - `"rsi_only"`: RSI만 확인 |
| | | | - `"trend_only"`: 트렌드만 확인 |
| `require_trend_confirm` | bool | `true` | 트렌드 확인 필수 여부 |

### 종료 조건 설정

#### 1. 트렌드 반전 종료 (Trend Reversal Exit)

**신규 기능** - 강한 트렌드 반전 발생 시 자동 종료

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `use_trend_close` | bool | `true` | 트렌드 반전 종료 사용 여부 |

**동작 방식**:
- **롱 포지션**: 강한 하락 트렌드 감지 시 (trend_state = -2) 자동 종료
- **숏 포지션**: 강한 상승 트렌드 감지 시 (trend_state = +2) 자동 종료
- **우선순위**: 가장 높음 (TP/SL보다 먼저 체크)

**트렌드 상태 계산**:
- EMA7, SMA20 기반으로 트렌드 강도를 -2 ~ +2 범위로 계산
- -2: 강한 하락 트렌드
- -1: 약한 하락 트렌드
- 0: 중립
- +1: 약한 상승 트렌드
- +2: 강한 상승 트렌드

#### 2. 손절 (Stop Loss)

**레거시 시스템** (하위 호환성 지원):

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `stop_loss_percent` | float | `null` | 손절 비율 (%) |

**새 시스템** (권장):

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `use_sl` | bool | `false` | 일반 손절 사용 여부 |
| `use_sl_on_last` | bool | `false` | 마지막 진입만 손절 |
| `sl_value` | float | `5.0` | 손절 값 |
| `sl_option` | string | `"percentage"` | 손절 옵션 (`percentage`, `price`) |

**중요**:
- `stop_loss_percent`가 설정되면 자동으로 손절이 활성화됩니다 (하위 호환)
- 새 시스템(`use_sl`)이 우선 적용되며, 없으면 레거시 시스템 확인
- 손절 활성화 조건: `use_sl=true` OR `use_sl_on_last=true` OR `stop_loss_percent > 0`

**예시**:
```json
// 레거시 방식 (여전히 작동)
{
  "stop_loss_percent": 2.8  // 2.8% 손절
}

// 새 방식 (권장)
{
  "use_sl": true,
  "sl_value": 2.8,
  "sl_option": "percentage"
}
```

#### 3. 익절 (Take Profit)

**부분 익절 지원** - 최대 3단계 익절 가능

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `use_tp1` | bool | `false` | 1차 익절 사용 여부 |
| `tp1_percent` | float | `1.0` | 1차 익절 비율 (%) |
| `tp1_close_percent` | float | `50.0` | 1차 익절 시 청산 비율 (%) |
| `use_tp2` | bool | `false` | 2차 익절 사용 여부 |
| `tp2_percent` | float | `2.0` | 2차 익절 비율 (%) |
| `tp2_close_percent` | float | `25.0` | 2차 익절 시 청산 비율 (%) |
| `use_tp3` | bool | `false` | 3차 익절 사용 여부 |
| `tp3_percent` | float | `3.0` | 3차 익절 비율 (%) |
| `tp3_close_percent` | float | `100.0` | 3차 익절 시 청산 비율 (%) |

**예시**:
```json
{
  "use_tp1": true,
  "tp1_percent": 1.5,      // 1.5% 수익 시
  "tp1_close_percent": 50, // 50% 청산
  "use_tp2": true,
  "tp2_percent": 3.0,      // 3.0% 수익 시
  "tp2_close_percent": 30, // 30% 청산 (총 80% 청산)
  "use_tp3": true,
  "tp3_percent": 5.0,      // 5.0% 수익 시
  "tp3_close_percent": 100 // 나머지 전체 청산
}
```

#### 4. 트레일링 스톱 (Trailing Stop)

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `use_trailing_stop` | bool | `false` | 트레일링 스톱 사용 여부 |
| `trailing_stop_percent` | float | `1.0` | 트레일링 스톱 비율 (%) |
| `trailing_activation_percent` | float | `2.0` | 트레일링 시작 수익 비율 (%) |

#### 5. Break Even (손익분기점 보호)

**신규 기능** - 부분 익절 후 손절가를 자동으로 조정하여 손실 리스크 감소

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `use_break_even` | bool | `true` | TP1 hit 후 break-even 활성화 |
| `use_break_even_tp2` | bool | `true` | TP2 hit 후 break-even 활성화 |
| `use_break_even_tp3` | bool | `true` | TP3 hit 후 break-even 활성화 |

**동작 방식**:
- **TP1 도달 시**: 손절가를 평균 진입가로 이동 (손실 리스크 제거)
- **TP2 도달 시**: 손절가를 TP1 가격으로 이동 (최소 수익 확보)
- **TP3 도달 시**: 손절가를 TP2 가격으로 이동 (수익 보호)
  - ⚠️ TP 합계가 100% 미만일 때만 적용 (남은 포지션이 있을 때)

**예시 시나리오**:
```json
{
  "entry_price": 100,
  "initial_sl": 97,        // -3% 손절
  "use_tp1": true,
  "tp1_percent": 1.5,      // +1.5% 익절
  "use_break_even": true,

  // TP1 Hit ($101.5) → SL moves: $97 → $100 (break-even)
  // 이제 최악의 경우에도 손실 없음 ✅
}
```

**혜택**:
- 부분 익절 후 리스크 단계적 감소
- 최소 수익 확보 상태로 포지션 유지
- 수익을 보호하면서 추가 수익 추구 가능

### DCA/피라미딩 설정

**현재 상태**: DCA/피라미딩 기능은 구현되어 있지만, 테스트 및 검증 단계입니다.

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `use_dca` | bool | `false` | DCA 사용 여부 |
| `dca_max_orders` | int | `3` | 최대 DCA 주문 수 |
| `dca_price_step_percent` | float | `1.0` | DCA 가격 간격 (%) |
| `dca_size_multiplier` | float | `1.5` | DCA 물량 승수 |
| `use_pyramiding` | bool | `false` | 피라미딩 사용 여부 |
| `pyramiding_max_orders` | int | `3` | 최대 피라미딩 주문 수 |

**⚠️ 경고**:
- DCA/피라미딩 기능은 아직 완전히 검증되지 않았습니다
- 프로덕션 환경에서 사용 전 충분한 백테스트를 권장합니다
- 자세한 내용은 `DCA_INTEGRATION_CURRENT_STATUS.md` 참조

---

## 종료 조건 우선순위

백테스트 엔진은 다음 순서로 종료 조건을 체크합니다:

1. **트렌드 반전 종료** (최우선)
   - `use_trend_close=true`일 때
   - 강한 트렌드 반전 감지 시 즉시 종료

2. **부분 익절** (TP1/TP2/TP3)
   - 설정된 익절 레벨 도달 시 지정 비율만큼 청산

3. **전체 익절** (TP3 100%)
   - 마지막 익절 레벨에서 나머지 전체 청산

4. **손절** (Stop Loss)
   - 레거시 `stop_loss_percent` 또는 새 시스템 `use_sl`

5. **트레일링 스톱**
   - `use_trailing_stop=true`일 때

---

## 실전 사용 예제

### 예제 1: 기본 백테스트

```bash
curl -X POST "http://localhost:8013/api/v1/backtest/run" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTC/USDT:USDT",
    "timeframe": "15m",
    "start_date": "2025-01-01T00:00:00",
    "end_date": "2025-02-01T00:00:00",
    "initial_capital": 10000,
    "strategy_params": {
      "rsi_period": 5,
      "rsi_ob": 70,
      "rsi_os": 30
    }
  }'
```

### 예제 2: 트렌드 반전 + 손절 설정

```bash
curl -X POST "http://localhost:8013/api/v1/backtest/run" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "ETH/USDT:USDT",
    "timeframe": "1h",
    "start_date": "2025-01-01T00:00:00",
    "end_date": "2025-03-01T00:00:00",
    "initial_capital": 10000,
    "strategy_params": {
      "rsi_period": 5,
      "use_trend_close": true,
      "stop_loss_percent": 2.8
    }
  }'
```

### 예제 3: 부분 익절 전략

```bash
curl -X POST "http://localhost:8013/api/v1/backtest/run" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTC/USDT:USDT",
    "timeframe": "15m",
    "start_date": "2025-01-01T00:00:00",
    "end_date": "2025-02-01T00:00:00",
    "initial_capital": 10000,
    "strategy_params": {
      "rsi_period": 5,
      "use_trend_close": true,
      "use_tp1": true,
      "tp1_percent": 1.5,
      "tp1_close_percent": 50,
      "use_tp2": true,
      "tp2_percent": 3.0,
      "tp2_close_percent": 30,
      "use_sl": true,
      "sl_value": 2.5,
      "sl_option": "percentage"
    }
  }'
```

### 예제 4: 트레일링 스톱

```bash
curl -X POST "http://localhost:8013/api/v1/backtest/run" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTC/USDT:USDT",
    "timeframe": "15m",
    "start_date": "2025-01-01T00:00:00",
    "end_date": "2025-02-01T00:00:00",
    "initial_capital": 10000,
    "strategy_params": {
      "rsi_period": 5,
      "use_trend_close": true,
      "use_trailing_stop": true,
      "trailing_stop_percent": 1.0,
      "trailing_activation_percent": 2.0,
      "stop_loss_percent": 3.0
    }
  }'
```

### 예제 5: 롱 전용 전략

```bash
curl -X POST "http://localhost:8013/api/v1/backtest/run" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTC/USDT:USDT",
    "timeframe": "1h",
    "start_date": "2025-01-01T00:00:00",
    "end_date": "2025-02-01T00:00:00",
    "initial_capital": 10000,
    "strategy_params": {
      "rsi_period": 5,
      "direction": "long",
      "use_trend_close": true,
      "stop_loss_percent": 2.5
    }
  }'
```

---

## 에러 코드

| 상태 코드 | 설명 |
|----------|------|
| 200 | 성공 |
| 400 | 잘못된 요청 (파라미터 오류) |
| 404 | 백테스트를 찾을 수 없음 |
| 500 | 서버 내부 오류 |

### 일반적인 에러 메시지

| 에러 메시지 | 원인 | 해결 방법 |
|-----------|------|---------|
| `Invalid date range` | 시작일이 종료일보다 늦음 | 날짜 순서 확인 |
| `Insufficient data` | 데이터 부족 | `/validate/data`로 데이터 확인 |
| `Invalid symbol format` | 심볼 형식 오류 | CCXT 형식 확인 (예: `BTC/USDT:USDT`) |
| `Invalid timeframe` | 지원하지 않는 타임프레임 | `1m`, `5m`, `15m`, `1h`, `4h` 등 사용 |

---

## 성능 메트릭 설명

| 메트릭 | 설명 | 좋은 값 |
|-------|------|---------|
| `total_pnl` | 총 손익 (USDT) | > 0 |
| `total_pnl_percent` | 총 손익률 (%) | > 10% |
| `win_rate` | 승률 (%) | > 50% |
| `profit_factor` | 수익 팩터 (총 수익 / 총 손실) | > 2.0 |
| `sharpe_ratio` | 샤프 비율 (위험 대비 수익) | > 1.5 |
| `max_drawdown_percent` | 최대 낙폭 (%) | < -10% |
| `average_win` | 평균 수익 거래 | - |
| `average_loss` | 평균 손실 거래 | - |
| `avg_holding_time_minutes` | 평균 보유 시간 (분) | - |

---

## 주의사항

1. **데이터 검증**: 백테스트 실행 전 `/validate/data`로 데이터 존재 여부 확인
2. **타임프레임**: 낮은 타임프레임(1m, 5m)은 대용량 데이터로 인해 느릴 수 있음
3. **DCA/피라미딩**: 아직 실험적 기능으로 프로덕션 사용 전 충분한 테스트 필요
4. **손절 설정**: 레거시 `stop_loss_percent`와 새 시스템을 혼용하지 말 것
5. **부분 익절**: TP1/TP2/TP3의 `close_percent` 합계가 100%를 초과하지 않도록 주의
6. **트렌드 반전**: `use_trend_close=true`일 때 TP/SL보다 먼저 종료될 수 있음

---

## 참고 문서

- **부분 익절**: `API_PARTIAL_EXITS.md`
- **DCA 통합**: `DCA_INTEGRATION_OVERVIEW.md`, `DCA_INTEGRATION_CURRENT_STATUS.md`
- **프론트엔드 통합**: `FRONTEND_INTEGRATION_GUIDE.md`
- **진입 옵션**: `ENTRY_OPTION_INTEGRATION.md`

---

## 변경 이력

### 2025-11-05
- ✅ **Break Even 기능 추가** (`use_break_even`, `use_break_even_tp2`, `use_break_even_tp3`)
  - TP1 hit → SL을 평균단가로 이동
  - TP2 hit → SL을 TP1 가격으로 이동
  - TP3 hit → SL을 TP2 가격으로 이동
- ✅ **Trade 인터페이스 확장**
  - `tp1_price`, `tp2_price`, `tp3_price`: 익절 목표가 정보
  - `next_dca_levels`: 다음 DCA 진입 레벨 배열
  - `stop_loss_price`: 손절가 (break-even 적용 시 변경됨)
  - `dca_count`, `total_investment`, `entry_history`: DCA 메타데이터
  - `entry_price`: 평균 진입가 명시 (DCA 시 가중평균)
- ✅ **프론트엔드 데이터 처리 가이드 추가**
  - 거래 데이터 해석 (기본 vs 부분 익절 vs DCA)
  - 종료 이유 해석 및 색상 매핑
  - 부분 익절 거래 그룹화
  - 자산 곡선 시각화
  - 성능 메트릭 대시보드
- ✅ **Break Even 설정 React 컴포넌트** 예제 추가

### 2025-11-04
- ✅ TypeScript/React 통합 가이드 추가
  - 전체 HyperRSI 파라미터 TypeScript 인터페이스
  - React 컴포넌트 예제 (트렌드 반전, 손절, 부분 익절)
  - API 호출 유틸리티 함수
  - 실전 사용 예제 코드
- ✅ 트렌드 반전 종료 기능 추가 (`use_trend_close`)
- ✅ 레거시 손절 시스템 지원 (`stop_loss_percent`)
- ✅ 종료 조건 우선순위 문서화
- ✅ curl 실전 사용 예제 추가

### 2025-11-03
- 부분 익절 기능 추가 (TP1/TP2/TP3)
- DCA/피라미딩 통합 (실험적)
- 진입 옵션 설정 추가

---

## 지원

문제가 발생하거나 질문이 있으면:
1. 로그 확인: `BACKTEST/logs/`
2. 데이터 검증: `/validate/data` 엔드포인트 사용
3. 문서 참조: `BACKTEST/docs/` 디렉토리의 관련 문서 확인
