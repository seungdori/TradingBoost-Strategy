# Frontend Integration Guide - Partial Exits (분할매도)

**프론트엔드 개발자를 위한 빠른 통합 가이드**

## 📋 체크리스트

### 1. API 스키마 업데이트 (필수)

- [ ] **Request 파라미터 추가** - 백테스트 실행 요청 시 포함:
  ```typescript
  // Partial exits (TP1/TP2/TP3)
  use_tp1?: boolean;
  use_tp2?: boolean;
  use_tp3?: boolean;
  tp1_value?: number;
  tp2_value?: number;
  tp3_value?: number;
  tp1_ratio?: number;
  tp2_ratio?: number;
  tp3_ratio?: number;

  // Trailing stop (HYPERRSI complete flow)
  trailing_stop_active?: boolean;
  trailing_start_point?: "tp1" | "tp2" | "tp3";
  trailing_stop_offset_value?: number;
  use_trailing_stop_value_with_tp2_tp3_difference?: boolean;
  ```

- [ ] **Response 필드 추가** - Trade 응답에서 처리:
  ```typescript
  is_partial_exit: boolean;
  tp_level: 1 | 2 | 3 | null;
  exit_ratio: number | null;
  remaining_quantity: number | null;
  ```

### 2. UI 컴포넌트 (권장)

- [ ] **설정 폼**: TP1/TP2/TP3 enable/disable 토글
- [ ] **입력 필드**: 각 TP의 profit target (%) 및 ratio (%)
- [ ] **유효성 검증**:
  - TP ratios 합계 ≤ 100%
  - TP values 오름차순 (TP1 < TP2 < TP3)
  - 양수 값 체크
- [ ] **결과 표시**:
  - Partial exit 뱃지/태그 (TP1, TP2, TP3)
  - Remaining quantity 표시
  - 진행 바 (30% → 60% → 100%)

### 3. 데이터 처리 (권장)

- [ ] **Trade Grouping**: 같은 entry_timestamp의 partial exits를 그룹화
- [ ] **메트릭 계산**:
  - Per-exit 메트릭 vs Per-position 메트릭 구분
  - 필터링 기능 (partial exits only, by TP level)
- [ ] **차트 시각화**:
  - Partial exit 포인트 표시
  - 색상 구분 (TP1/TP2/TP3)

---

## 🚀 5분 빠른 시작

### Step 1: TypeScript 인터페이스 복사

프로젝트에 아래 인터페이스를 추가하세요:

```typescript
// types/backtest.ts

export interface PartialExitConfig {
  // Partial exits (TP1/TP2/TP3)
  use_tp1?: boolean;
  use_tp2?: boolean;
  use_tp3?: boolean;
  tp1_value?: number;
  tp2_value?: number;
  tp3_value?: number;
  tp1_ratio?: number;
  tp2_ratio?: number;
  tp3_ratio?: number;

  // Trailing stop (HYPERRSI complete flow)
  trailing_stop_active?: boolean;
  trailing_start_point?: "tp1" | "tp2" | "tp3";
  trailing_stop_offset_value?: number;
  use_trailing_stop_value_with_tp2_tp3_difference?: boolean;
}

export interface StrategyParams extends PartialExitConfig {
  entry_option: string;
  rsi_oversold: number;
  rsi_overbought: number;
  leverage: number;
  investment: number;
  // ... 기타 파라미터
}

export interface TradeResponse {
  trade_number: number;
  side: "long" | "short";
  entry_timestamp: string;
  entry_price: number;
  exit_timestamp: string | null;
  exit_price: number | null;
  exit_reason: string | null;
  quantity: number;
  leverage: number;
  pnl: number | null;
  pnl_percent: number | null;

  // DCA 메타데이터
  dca_count: number;
  entry_history: any[];
  total_investment: number;

  // Partial exit 메타데이터 (NEW!)
  is_partial_exit: boolean;
  tp_level: 1 | 2 | 3 | null;
  exit_ratio: number | null;
  remaining_quantity: number | null;
}
```

### Step 2: API 요청 예제

```typescript
// api/backtest.ts

export async function runBacktest(params: {
  symbol: string;
  timeframe: string;
  start_date: string;
  end_date: string;
  strategy_params: StrategyParams;
}) {
  const response = await fetch('http://localhost:8013/backtest/run', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      ...params,
      initial_balance: 10000.0,
      fee_rate: 0.0005,
      slippage_percent: 0.05,
    }),
  });

  if (!response.ok) {
    throw new Error('Backtest failed');
  }

  return response.json();
}
```

### Step 3: UI 폼 예제 (React)

```typescript
// components/PartialExitSettings.tsx

import React from 'react';

interface Props {
  values: PartialExitConfig;
  onChange: (config: PartialExitConfig) => void;
}

export function PartialExitSettings({ values, onChange }: Props) {
  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold">분할매도 설정 (Partial Exits)</h3>

      {/* TP1 */}
      <div className="flex items-center gap-4">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={values.use_tp1 || false}
            onChange={(e) => onChange({ ...values, use_tp1: e.target.checked })}
          />
          <span>TP1 활성화</span>
        </label>

        {values.use_tp1 && (
          <>
            <input
              type="number"
              placeholder="Profit %"
              value={values.tp1_value || 2.0}
              onChange={(e) => onChange({ ...values, tp1_value: parseFloat(e.target.value) })}
              className="w-24 px-2 py-1 border rounded"
            />
            <span>%</span>

            <input
              type="number"
              placeholder="Ratio %"
              value={values.tp1_ratio || 30}
              onChange={(e) => onChange({ ...values, tp1_ratio: parseInt(e.target.value) })}
              className="w-24 px-2 py-1 border rounded"
            />
            <span>% 청산</span>
          </>
        )}
      </div>

      {/* TP2 */}
      <div className="flex items-center gap-4">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={values.use_tp2 || false}
            onChange={(e) => onChange({ ...values, use_tp2: e.target.checked })}
          />
          <span>TP2 활성화</span>
        </label>

        {values.use_tp2 && (
          <>
            <input
              type="number"
              placeholder="Profit %"
              value={values.tp2_value || 3.0}
              onChange={(e) => onChange({ ...values, tp2_value: parseFloat(e.target.value) })}
              className="w-24 px-2 py-1 border rounded"
            />
            <span>%</span>

            <input
              type="number"
              placeholder="Ratio %"
              value={values.tp2_ratio || 30}
              onChange={(e) => onChange({ ...values, tp2_ratio: parseInt(e.target.value) })}
              className="w-24 px-2 py-1 border rounded"
            />
            <span>% 청산</span>
          </>
        )}
      </div>

      {/* TP3 */}
      <div className="flex items-center gap-4">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={values.use_tp3 || false}
            onChange={(e) => onChange({ ...values, use_tp3: e.target.checked })}
          />
          <span>TP3 활성화</span>
        </label>

        {values.use_tp3 && (
          <>
            <input
              type="number"
              placeholder="Profit %"
              value={values.tp3_value || 4.0}
              onChange={(e) => onChange({ ...values, tp3_value: parseFloat(e.target.value) })}
              className="w-24 px-2 py-1 border rounded"
            />
            <span>%</span>

            <input
              type="number"
              placeholder="Ratio %"
              value={values.tp3_ratio || 40}
              onChange={(e) => onChange({ ...values, tp3_ratio: parseInt(e.target.value) })}
              className="w-24 px-2 py-1 border rounded"
            />
            <span>% 청산</span>
          </>
        )}
      </div>

      {/* Trailing Stop Settings */}
      <div className="border-t pt-4 mt-4">
        <h4 className="text-md font-semibold mb-3">Trailing Stop (HYPERRSI 완전한 익절 로직)</h4>

        <label className="flex items-center gap-2 mb-3">
          <input
            type="checkbox"
            checked={values.trailing_stop_active || false}
            onChange={(e) => onChange({ ...values, trailing_stop_active: e.target.checked })}
          />
          <span>Trailing Stop 활성화</span>
        </label>

        {values.trailing_stop_active && (
          <>
            <div className="flex items-center gap-4 mb-3">
              <label className="w-32">활성화 시점:</label>
              <select
                value={values.trailing_start_point || "tp3"}
                onChange={(e) => onChange({ ...values, trailing_start_point: e.target.value as "tp1" | "tp2" | "tp3" })}
                className="px-2 py-1 border rounded"
              >
                <option value="tp1">TP1 도달 시</option>
                <option value="tp2">TP2 도달 시</option>
                <option value="tp3">TP3 도달 시</option>
              </select>
            </div>

            <div className="flex items-center gap-4 mb-3">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={values.use_trailing_stop_value_with_tp2_tp3_difference || false}
                  onChange={(e) => onChange({ ...values, use_trailing_stop_value_with_tp2_tp3_difference: e.target.checked })}
                />
                <span>TP2-TP3 가격 차이로 Offset 계산</span>
              </label>
            </div>

            {!values.use_trailing_stop_value_with_tp2_tp3_difference && (
              <div className="flex items-center gap-4">
                <label className="w-32">Offset (%):</label>
                <input
                  type="number"
                  step="0.1"
                  value={values.trailing_stop_offset_value || 0.5}
                  onChange={(e) => onChange({ ...values, trailing_stop_offset_value: parseFloat(e.target.value) })}
                  className="w-24 px-2 py-1 border rounded"
                />
                <span>%</span>
              </div>
            )}
          </>
        )}
      </div>

      {/* Validation display */}
      <ValidationMessages config={values} />
    </div>
  );
}

function ValidationMessages({ config }: { config: PartialExitConfig }) {
  const totalRatio =
    (config.use_tp1 ? config.tp1_ratio || 0 : 0) +
    (config.use_tp2 ? config.tp2_ratio || 0 : 0) +
    (config.use_tp3 ? config.tp3_ratio || 0 : 0);

  if (totalRatio > 100) {
    return <p className="text-red-500">⚠️ 합계가 100%를 초과할 수 없습니다</p>;
  }

  if (totalRatio < 100) {
    return <p className="text-yellow-500">ℹ️ 나머지 {100 - totalRatio}%는 청산되지 않습니다</p>;
  }

  return <p className="text-green-500">✓ 설정이 올바릅니다</p>;
}
```

### Step 4: 결과 표시 예제

```typescript
// components/TradesList.tsx

import React from 'react';
import { TradeResponse } from '../types/backtest';

interface Props {
  trades: TradeResponse[];
}

export function TradesList({ trades }: Props) {
  // Group partial exits by entry timestamp
  const groupedTrades = trades.reduce((groups, trade) => {
    const key = trade.entry_timestamp;
    if (!groups[key]) {
      groups[key] = [];
    }
    groups[key].push(trade);
    return groups;
  }, {} as Record<string, TradeResponse[]>);

  return (
    <div className="space-y-4">
      {Object.entries(groupedTrades).map(([entryTime, exitTrades]) => {
        const totalPnl = exitTrades.reduce((sum, t) => sum + (t.pnl || 0), 0);
        const hasPartialExits = exitTrades.some(t => t.is_partial_exit);

        return (
          <div key={entryTime} className="border rounded-lg p-4">
            <div className="flex justify-between items-center mb-2">
              <h4 className="font-semibold">
                Position {exitTrades[0].side.toUpperCase()} @ ${exitTrades[0].entry_price.toLocaleString()}
              </h4>
              <span className={totalPnl >= 0 ? 'text-green-600' : 'text-red-600'}>
                Total P&L: ${totalPnl.toFixed(2)}
              </span>
            </div>

            <div className="text-sm text-gray-600 mb-3">
              Entry: {new Date(entryTime).toLocaleString()}
            </div>

            {hasPartialExits && (
              <div className="mb-3">
                <PositionProgressBar trades={exitTrades} />
              </div>
            )}

            <table className="w-full text-sm">
              <thead className="bg-gray-100">
                <tr>
                  <th className="px-2 py-1">Exit</th>
                  <th className="px-2 py-1">Exit Time</th>
                  <th className="px-2 py-1">Price</th>
                  <th className="px-2 py-1">Quantity</th>
                  <th className="px-2 py-1">Remaining</th>
                  <th className="px-2 py-1">P&L</th>
                </tr>
              </thead>
              <tbody>
                {exitTrades.map((trade, idx) => (
                  <tr key={idx} className="border-t">
                    <td className="px-2 py-1">
                      {trade.is_partial_exit ? (
                        <span className={`px-2 py-1 rounded text-xs font-semibold ${getTPBadgeClass(trade.tp_level)}`}>
                          TP{trade.tp_level}
                        </span>
                      ) : (
                        <span className="text-gray-500">Full</span>
                      )}
                    </td>
                    <td className="px-2 py-1">{new Date(trade.exit_timestamp!).toLocaleString()}</td>
                    <td className="px-2 py-1">${trade.exit_price?.toLocaleString()}</td>
                    <td className="px-2 py-1">{trade.quantity.toFixed(4)}</td>
                    <td className="px-2 py-1">
                      {trade.remaining_quantity !== null ? trade.remaining_quantity.toFixed(4) : '-'}
                    </td>
                    <td className={`px-2 py-1 ${trade.pnl! >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                      ${trade.pnl?.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </div>
  );
}

function getTPBadgeClass(tpLevel: number | null): string {
  switch (tpLevel) {
    case 1:
      return 'bg-green-100 text-green-800';
    case 2:
      return 'bg-blue-100 text-blue-800';
    case 3:
      return 'bg-purple-100 text-purple-800';
    default:
      return 'bg-gray-100 text-gray-800';
  }
}

function PositionProgressBar({ trades }: { trades: TradeResponse[] }) {
  const partialExits = trades.filter(t => t.is_partial_exit).sort((a, b) => a.tp_level! - b.tp_level!);

  let closedPercent = 0;

  return (
    <div className="space-y-1">
      <div className="flex h-6 rounded overflow-hidden border">
        {partialExits.map((trade, idx) => {
          const percent = (trade.exit_ratio || 0) * 100;
          closedPercent += percent;

          return (
            <div
              key={idx}
              className={`flex items-center justify-center text-xs text-white font-semibold ${getTPBarClass(trade.tp_level)}`}
              style={{ width: `${percent}%` }}
              title={`TP${trade.tp_level}: ${percent.toFixed(0)}%`}
            >
              {percent >= 10 && `TP${trade.tp_level}`}
            </div>
          );
        })}
        {closedPercent < 100 && (
          <div
            className="flex items-center justify-center text-xs bg-gray-200 text-gray-600"
            style={{ width: `${100 - closedPercent}%` }}
          >
            {100 - closedPercent >= 10 && 'Open'}
          </div>
        )}
      </div>
      <p className="text-xs text-gray-600">
        {closedPercent.toFixed(0)}% closed, {(100 - closedPercent).toFixed(0)}% remaining
      </p>
    </div>
  );
}

function getTPBarClass(tpLevel: number | null): string {
  switch (tpLevel) {
    case 1:
      return 'bg-green-500';
    case 2:
      return 'bg-blue-500';
    case 3:
      return 'bg-purple-500';
    default:
      return 'bg-gray-500';
  }
}
```

---

## 📊 데이터 처리 팁

### 1. Partial Exits 필터링

```typescript
// 모든 partial exit trades만 추출
const partialExits = trades.filter(t => t.is_partial_exit);

// TP level별 필터링
const tp1Exits = trades.filter(t => t.tp_level === 1);
const tp2Exits = trades.filter(t => t.tp_level === 2);
const tp3Exits = trades.filter(t => t.tp_level === 3);

// Full exits (partial이 아닌 것)
const fullExits = trades.filter(t => !t.is_partial_exit);
```

### 2. 포지션별 P&L 계산

```typescript
// Entry timestamp별로 그룹화한 후 total P&L 계산
function calculatePositionPnL(trades: TradeResponse[]): Array<{ entryTime: string; totalPnl: number; exitCount: number }> {
  const grouped = trades.reduce((acc, trade) => {
    const key = trade.entry_timestamp;
    if (!acc[key]) {
      acc[key] = [];
    }
    acc[key].push(trade);
    return acc;
  }, {} as Record<string, TradeResponse[]>);

  return Object.entries(grouped).map(([entryTime, exitTrades]) => ({
    entryTime,
    totalPnl: exitTrades.reduce((sum, t) => sum + (t.pnl || 0), 0),
    exitCount: exitTrades.length,
  }));
}
```

### 3. 메트릭 계산

```typescript
// Per-exit 메트릭
const avgPnlPerExit = trades.reduce((sum, t) => sum + (t.pnl || 0), 0) / trades.length;

// Per-position 메트릭
const positions = calculatePositionPnL(trades);
const avgPnlPerPosition = positions.reduce((sum, p) => sum + p.totalPnl, 0) / positions.length;

// Win rate (per exit)
const winningExits = trades.filter(t => (t.pnl || 0) > 0).length;
const winRatePerExit = (winningExits / trades.length) * 100;

// Win rate (per position)
const winningPositions = positions.filter(p => p.totalPnl > 0).length;
const winRatePerPosition = (winningPositions / positions.length) * 100;
```

---

## 🎨 UI/UX 권장사항

### 색상 구분

```typescript
const TP_COLORS = {
  TP1: {
    bg: '#10B981',      // Green
    badge: '#ECFDF5',
    text: '#047857',
  },
  TP2: {
    bg: '#3B82F6',      // Blue
    badge: '#EFF6FF',
    text: '#1E40AF',
  },
  TP3: {
    bg: '#8B5CF6',      // Purple
    badge: '#F5F3FF',
    text: '#6D28D9',
  },
};
```

### 아이콘/뱃지

- TP1: 🟢 Green badge
- TP2: 🔵 Blue badge
- TP3: 🟣 Purple badge
- Full Exit: ⚪ Gray badge

### 프로그레스 바

포지션이 얼마나 청산되었는지 시각화:
```
[====TP1====][====TP2====][====TP3====][==Open==]
    30%           30%           30%        10%
```

---

## ✅ 테스트 시나리오

### 시나리오 1: 기본 분할매도 (30-30-40)

**Input**:
```json
{
  "use_tp1": true,
  "use_tp2": true,
  "use_tp3": true,
  "tp1_value": 2.0,
  "tp2_value": 3.0,
  "tp3_value": 4.0,
  "tp1_ratio": 30,
  "tp2_ratio": 30,
  "tp3_ratio": 40
}
```

**Expected Output**:
- 3개의 trade records
- `is_partial_exit: true` for all
- `tp_level: 1, 2, 3`
- `remaining_quantity: 0.7 → 0.4 → 0.0`

### 시나리오 2: 2-Level 분할매도

**Input**:
```json
{
  "use_tp1": true,
  "use_tp2": true,
  "use_tp3": false,
  "tp1_value": 2.0,
  "tp2_value": 4.0,
  "tp1_ratio": 50,
  "tp2_ratio": 50
}
```

**Expected Output**:
- 2개의 trade records
- `tp_level: 1, 2`
- `remaining_quantity: 0.5 → 0.0`

### 시나리오 3: 분할매도 비활성화

**Input**:
```json
{
  "use_tp1": false,
  "use_tp2": false,
  "use_tp3": false,
  "take_profit_percent": 4.0
}
```

**Expected Output**:
- 1개의 trade record
- `is_partial_exit: false`
- `tp_level: null`

---

## 🐛 문제 해결

### 문제 1: TP ratios 합계가 100%가 아닌 경우

**증상**: 일부 포지션이 완전히 청산되지 않음
**원인**: TP1=30, TP2=30, TP3=30 → 합계 90%
**해결**: UI에서 경고 메시지 표시, 나머지 10%는 stop loss나 수동 청산 필요

### 문제 2: TP values가 역순인 경우

**증상**: Backend validation error
**원인**: TP1=4.0, TP2=3.0, TP3=2.0 (역순)
**해결**: Frontend에서 오름차순 검증 추가

### 문제 3: Trade 개수가 예상과 다름

**증상**: 3개의 TP level을 설정했는데 2개만 나옴
**원인**: 가격이 TP3에 도달하지 못함 (stop loss 먼저 hit)
**해결**: 정상 동작, 실제 시장 상황에 따라 일부 TP만 실행될 수 있음

---

## 📞 지원

질문이나 문제가 있으면:

1. **상세 API 문서**: `BACKTEST/docs/API_PARTIAL_EXITS.md` 참고
2. **백엔드 통합 문서**: `PARTIAL_EXITS_INTEGRATION.md` 참고
3. **테스트 케이스**: `BACKTEST/tests/test_partial_exits.py` 참고
4. **백엔드 팀 문의**: 에러 메시지와 함께 문의

---

**마지막 업데이트**: 2025-11-03
**문서 버전**: 1.0.0
