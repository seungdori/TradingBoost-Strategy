# Backtest UI Design Specification

Next.js 개발자를 위한 백테스트 결과 UI 디자인 명세서

---

## 🎨 전체 레이아웃 구조

```
┌─────────────────────────────────────────────────────────────┐
│  📊 Backtest Results                                        │
│  BTCUSDT | 15m | 2025-08-01 ~ 2025-10-31 (3개월)          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────────────────────────────────────────────────┐ │
│  │  📈 Performance Summary (Summary Cards)               │ │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐    │ │
│  │  │ Total   │ │ Win     │ │ Sharpe  │ │ Max     │    │ │
│  │  │ Return  │ │ Rate    │ │ Ratio   │ │ DD      │    │ │
│  │  │ +30.82% │ │ 100%    │ │ 17.37   │ │ -6.34%  │    │ │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘    │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐ │
│  │  📊 Equity Curve (Chart)                              │ │
│  │  [Line chart showing balance over time]              │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐ │
│  │  🎯 Trades List (Expandable Trade Cards)             │ │
│  │                                                        │ │
│  │  ┌─────────────────────────────────────────────────┐ │ │
│  │  │ Trade #1  SHORT  ✅                             │ │ │
│  │  │ Entry: $113,537.52 → Exit: $109,056.00        │ │ │
│  │  │ PnL: +$393.52 (4.11%)                          │ │ │
│  │  │ [No DCA]                                        │ │ │
│  │  └─────────────────────────────────────────────────┘ │ │
│  │                                                        │ │
│  │  ┌─────────────────────────────────────────────────┐ │ │
│  │  │ Trade #2  LONG  ✅  📊 DCA 3회 발동 [펼치기] │ │ │
│  │  │ Entry: $111,733.52 → Exit: $117,018.62        │ │ │
│  │  │ PnL: +$1,874.78 (4.73%)  🚀 +376% vs no DCA   │ │ │
│  │  │                                                 │ │ │
│  │  │ ┌─ DCA Details (펼쳐진 상태) ────────────────┐ │ │ │
│  │  │ │                                             │ │ │ │
│  │  │ │  📍 Entry Timeline                          │ │ │ │
│  │  │ │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │ │ │ │
│  │  │ │  🎯 Entry 1: $112,579.78                   │ │ │ │
│  │  │ │  │  ├ 2025-09-09 11:30                     │ │ │ │
│  │  │ │  │  ├ 0.00888747 BTC ($10,000)            │ │ │ │
│  │  │ │  │  └ RSI oversold + neutral trend        │ │ │ │
│  │  │ │  │                                          │ │ │ │
│  │  │ │  📊 DCA 1: $111,606.85 (-0.86%)            │ │ │ │
│  │  │ │  │  ├ 2025-09-09 14:30 (3시간 후)         │ │ │ │
│  │  │ │  │  ├ 0.00888747 BTC ($10,000)            │ │ │ │
│  │  │ │  │  └ Price reached DCA level             │ │ │ │
│  │  │ │  │                                          │ │ │ │
│  │  │ │  📊 DCA 2: $111,416.25 (-1.03%)            │ │ │ │
│  │  │ │  │  └ ... (similar format)                 │ │ │ │
│  │  │ │  │                                          │ │ │ │
│  │  │ │  📊 DCA 3: $111,331.20 (-1.11%)            │ │ │ │
│  │  │ │     └ ... (similar format)                 │ │ │ │
│  │  │ │                                             │ │ │ │
│  │  │ │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │ │ │ │
│  │  │ │                                             │ │ │ │
│  │  │ │  📊 Price Chart                            │ │ │ │
│  │  │ │  [Candlestick chart with entry markers]   │ │ │ │
│  │  │ │                                             │ │ │ │
│  │  │ │  💰 Summary                                │ │ │ │
│  │  │ │  • Total Entries: 4회                      │ │ │ │
│  │  │ │  • Total Investment: $40,000               │ │ │ │
│  │  │ │  • Average Entry: $111,733.52              │ │ │ │
│  │  │ │  • Price Improvement: -0.75%               │ │ │ │
│  │  │ │  • Position Size: 4x initial               │ │ │ │
│  │  │ └─────────────────────────────────────────┘ │ │ │
│  │  └─────────────────────────────────────────────────┘ │ │
│  │                                                        │ │
│  │  [Trade #3... similar structure]                      │ │
│  └───────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## 📐 Component 구조

```typescript
// 페이지 레벨
BacktestResultPage
├── BacktestHeader              // 심볼, 기간 정보
├── PerformanceSummary          // 성과 요약 카드들
│   ├── MetricCard (Total Return)
│   ├── MetricCard (Win Rate)
│   ├── MetricCard (Sharpe Ratio)
│   └── MetricCard (Max Drawdown)
├── EquityCurveChart            // 자산 곡선 차트
└── TradesList                  // 거래 목록
    └── TradeCard (반복)
        ├── TradeHeader         // 거래 기본 정보
        ├── TradeMetrics        // 진입가, 청산가, 수익
        ├── DCABadge           // DCA 발동 배지 (조건부)
        └── DCADetails         // DCA 상세 정보 (펼침 가능)
            ├── EntryTimeline   // 진입 타임라인
            ├── DCAChart        // 가격 차트
            └── DCASummary      // 요약 정보
```

---

## 🎨 1. Performance Summary Cards

### 디자인

```
┌─────────────────────────────────────────────────────────────┐
│  4개의 카드를 Grid로 배치 (반응형: 모바일 2x2, 데스크탑 1x4)  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ 💰 Total    │  │ 🎯 Win      │  │ 📊 Sharpe   │     │
│  │    Return   │  │    Rate     │  │    Ratio    │     │
│  │             │  │             │  │             │     │
│  │   +30.82%   │  │    100%     │  │    17.37    │     │
│  │   ━━━━━━━━  │  │   ━━━━━━━━  │  │   ━━━━━━━━  │     │
│  │ +$3,081.97  │  │  3/3 trades │  │   Excellent │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ 📉 Max DD   │  │ 💵 Final    │  │ 🔄 Total    │     │
│  │             │  │    Balance  │  │    Trades   │     │
│  │   -6.34%    │  │             │  │             │     │
│  │   ━━━━━━━━  │  │  $13,082    │  │      3      │     │
│  │  -$634.30   │  │  (+30.82%)  │  │   All wins  │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

### 컴포넌트 코드

```typescript
// components/backtest/MetricCard.tsx
interface MetricCardProps {
  icon: string;
  label: string;
  value: string | number;
  subValue?: string;
  trend?: 'up' | 'down' | 'neutral';
  color?: 'green' | 'red' | 'blue' | 'purple';
}

export const MetricCard: React.FC<MetricCardProps> = ({
  icon,
  label,
  value,
  subValue,
  trend,
  color = 'blue'
}) => {
  return (
    <div className="bg-white rounded-lg shadow-md p-6 hover:shadow-lg transition-shadow">
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <span className="text-2xl">{icon}</span>
        <span className="text-sm font-medium text-gray-600">{label}</span>
      </div>

      {/* Value */}
      <div className={`text-3xl font-bold mb-2 ${
        trend === 'up' ? 'text-green-600' :
        trend === 'down' ? 'text-red-600' :
        'text-gray-900'
      }`}>
        {value}
      </div>

      {/* Progress bar */}
      <div className="w-full h-1 bg-gray-200 rounded-full mb-2">
        <div className={`h-full rounded-full bg-${color}-500`} style={{ width: '75%' }} />
      </div>

      {/* Sub value */}
      {subValue && (
        <div className="text-sm text-gray-500">{subValue}</div>
      )}
    </div>
  );
};

// components/backtest/PerformanceSummary.tsx
export const PerformanceSummary: React.FC<{ result: BacktestResponse }> = ({ result }) => {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <MetricCard
        icon="💰"
        label="Total Return"
        value={`${result.total_return_percent > 0 ? '+' : ''}${result.total_return_percent.toFixed(2)}%`}
        subValue={`$${result.total_return.toLocaleString()}`}
        trend={result.total_return > 0 ? 'up' : 'down'}
        color="green"
      />
      <MetricCard
        icon="🎯"
        label="Win Rate"
        value={`${result.win_rate.toFixed(0)}%`}
        subValue={`${result.winning_trades}/${result.total_trades} trades`}
        trend="neutral"
        color="blue"
      />
      <MetricCard
        icon="📊"
        label="Sharpe Ratio"
        value={result.sharpe_ratio?.toFixed(2) || 'N/A'}
        subValue={result.sharpe_ratio > 2 ? 'Excellent' : 'Good'}
        trend="neutral"
        color="purple"
      />
      <MetricCard
        icon="📉"
        label="Max Drawdown"
        value={`${result.max_drawdown_percent.toFixed(2)}%`}
        subValue={`$${Math.abs(result.max_drawdown).toLocaleString()}`}
        trend="down"
        color="red"
      />
    </div>
  );
};
```

---

## 🎯 2. Trade Card (DCA 없는 경우)

### 디자인

```
┌─────────────────────────────────────────────────────────┐
│  #1  SHORT  ✅  2025-08-24 ~ 2025-08-26  (25.25h)     │
├─────────────────────────────────────────────────────────┤
│  📍 Entry: $113,537.52  →  📍 Exit: $109,056.00       │
│  📊 Quantity: 0.00880282 BTC  (Leverage: 10x)         │
│  💰 PnL: +$393.52 (+4.11%)                            │
│  💸 Fees: $0.50                                        │
└─────────────────────────────────────────────────────────┘
```

### 컴포넌트 코드

```typescript
// components/backtest/TradeCard.tsx
export const TradeCard: React.FC<{ trade: Trade }> = ({ trade }) => {
  const [expanded, setExpanded] = useState(false);
  const hasDCA = trade.dca_count > 0;

  return (
    <div className="bg-white rounded-lg shadow-md overflow-hidden mb-4">
      {/* Header */}
      <div className="flex items-center justify-between p-4 bg-gradient-to-r from-gray-50 to-white border-b">
        <div className="flex items-center gap-3">
          <span className="text-lg font-bold text-gray-700">#{trade.trade_number}</span>
          <span className={`px-3 py-1 rounded-full text-sm font-semibold ${
            trade.side === 'long'
              ? 'bg-green-100 text-green-800'
              : 'bg-red-100 text-red-800'
          }`}>
            {trade.side.toUpperCase()}
          </span>
          <span className="text-2xl">{trade.pnl > 0 ? '✅' : '❌'}</span>
        </div>

        <div className="text-sm text-gray-500">
          {formatDuration(trade.entry_timestamp, trade.exit_timestamp)}
        </div>
      </div>

      {/* Body */}
      <div className="p-4">
        {/* Price Flow */}
        <div className="flex items-center gap-2 mb-3">
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-600">Entry:</span>
            <span className="text-lg font-bold text-gray-900">
              ${trade.entry_price.toLocaleString()}
            </span>
          </div>
          <span className="text-gray-400">→</span>
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-600">Exit:</span>
            <span className="text-lg font-bold text-gray-900">
              ${trade.exit_price?.toLocaleString()}
            </span>
          </div>
        </div>

        {/* Metrics Grid */}
        <div className="grid grid-cols-2 gap-3 mb-3">
          <div>
            <span className="text-sm text-gray-600">Quantity:</span>
            <span className="ml-2 font-medium">{trade.quantity.toFixed(8)} BTC</span>
          </div>
          <div>
            <span className="text-sm text-gray-600">Leverage:</span>
            <span className="ml-2 font-medium">{trade.leverage}x</span>
          </div>
        </div>

        {/* PnL */}
        <div className={`text-xl font-bold ${trade.pnl > 0 ? 'text-green-600' : 'text-red-600'}`}>
          {trade.pnl > 0 ? '+' : ''}${trade.pnl?.toFixed(2)} ({trade.pnl_percent?.toFixed(2)}%)
        </div>

        {/* DCA Badge (조건부) */}
        {hasDCA && (
          <DCABadge
            trade={trade}
            expanded={expanded}
            onToggle={() => setExpanded(!expanded)}
          />
        )}

        {/* DCA Details (조건부, 펼침 가능) */}
        {hasDCA && expanded && (
          <DCADetails trade={trade} />
        )}
      </div>
    </div>
  );
};
```

---

## 📊 3. DCA Badge (핵심 UI)

### 디자인 (접힌 상태)

```
┌─────────────────────────────────────────────────────────┐
│  💜 DCA 3회 발동  |  평균가 ↓0.75%  |  수익 +376%  [▼] │
└─────────────────────────────────────────────────────────┘
```

### 컴포넌트 코드

```typescript
// components/backtest/DCABadge.tsx
interface DCABadgeProps {
  trade: Trade;
  expanded: boolean;
  onToggle: () => void;
}

export const DCABadge: React.FC<DCABadgeProps> = ({ trade, expanded, onToggle }) => {
  // 초기 진입가
  const initialEntry = trade.entry_history[0];

  // 가격 개선율
  const priceImprovement = trade.side === 'long'
    ? ((initialEntry.price - trade.entry_price) / initialEntry.price) * 100
    : ((trade.entry_price - initialEntry.price) / initialEntry.price) * 100;

  // DCA 없었을 때의 가상 수익 계산
  const initialQuantity = initialEntry.quantity;
  const virtualPnL = trade.side === 'long'
    ? initialQuantity * (trade.exit_price - initialEntry.price)
    : initialQuantity * (initialEntry.price - trade.exit_price);

  const pnlImprovement = ((trade.pnl - virtualPnL) / virtualPnL) * 100;

  return (
    <div
      onClick={onToggle}
      className="mt-4 p-4 rounded-lg cursor-pointer transition-all
                 bg-gradient-to-r from-purple-500 to-indigo-600
                 hover:from-purple-600 hover:to-indigo-700
                 text-white shadow-lg hover:shadow-xl"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          {/* DCA Count */}
          <div className="flex items-center gap-2">
            <span className="text-2xl">📊</span>
            <span className="font-bold text-lg">
              DCA {trade.dca_count}회 발동
            </span>
          </div>

          {/* Price Improvement */}
          <div className="bg-white bg-opacity-20 px-3 py-1 rounded-full">
            <span className="text-sm font-medium">
              평균가 {priceImprovement > 0 ? '↓' : '↑'} {Math.abs(priceImprovement).toFixed(2)}%
            </span>
          </div>

          {/* PnL Improvement */}
          <div className="bg-white bg-opacity-20 px-3 py-1 rounded-full">
            <span className="text-sm font-medium">
              수익 +{pnlImprovement.toFixed(0)}%
            </span>
          </div>
        </div>

        {/* Toggle Icon */}
        <div className="text-2xl transition-transform"
             style={{ transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)' }}>
          ▼
        </div>
      </div>

      {/* Subtitle */}
      <div className="mt-2 text-sm text-purple-100">
        총 {trade.entry_history.length}회 진입 •
        투자금 ${trade.total_investment.toLocaleString()} •
        포지션 {trade.entry_history.length}x
      </div>
    </div>
  );
};
```

---

## 📍 4. Entry Timeline (펼쳐진 상태)

### 디자인

```
┌─────────────────────────────────────────────────────────┐
│  📍 Entry Timeline                                      │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                         │
│  ⦿ Entry 1 (Initial)                                   │
│  ┃  $112,579.78                                         │
│  ┃  Sep 9, 2025 11:30 AM                               │
│  ┃  0.00888747 BTC • $10,000                           │
│  ┃  📝 RSI oversold + neutral trend                    │
│  ┃                                                      │
│  ⦿ DCA 1 (-0.86% from initial)                         │
│  ┃  $111,606.85                                         │
│  ┃  Sep 9, 2025 2:30 PM (3h later)                     │
│  ┃  0.00888747 BTC • $10,000                           │
│  ┃  📝 Price reached DCA level                         │
│  ┃                                                      │
│  ⦿ DCA 2 (-1.03% from initial)                         │
│  ┃  $111,416.25                                         │
│  ┃  Sep 9, 2025 3:00 PM (30m later)                    │
│  ┃  0.00888747 BTC • $10,000                           │
│  ┃                                                      │
│  ⦿ DCA 3 (-1.11% from initial)                         │
│     $111,331.20                                         │
│     Sep 9, 2025 3:15 PM (15m later)                    │
│     0.00888747 BTC • $10,000                           │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 컴포넌트 코드

```typescript
// components/backtest/EntryTimeline.tsx
export const EntryTimeline: React.FC<{ trade: Trade }> = ({ trade }) => {
  const initialPrice = trade.entry_history[0].price;

  return (
    <div className="mt-6">
      <h4 className="text-lg font-bold mb-4 flex items-center gap-2">
        <span>📍</span>
        <span>Entry Timeline</span>
      </h4>

      <div className="relative pl-8">
        {/* Vertical line */}
        <div className="absolute left-3 top-0 bottom-0 w-0.5 bg-gradient-to-b from-purple-400 to-indigo-400" />

        {/* Entries */}
        {trade.entry_history.map((entry, idx) => {
          const priceChange = ((entry.price - initialPrice) / initialPrice) * 100;
          const isInitial = idx === 0;

          // 이전 진입과의 시간 차이
          const timeDiff = idx > 0
            ? getTimeDifference(trade.entry_history[idx - 1].timestamp, entry.timestamp)
            : null;

          return (
            <div key={idx} className="relative mb-6 last:mb-0">
              {/* Dot */}
              <div className={`absolute -left-6 w-6 h-6 rounded-full border-4 ${
                isInitial
                  ? 'bg-green-500 border-green-200'
                  : 'bg-purple-500 border-purple-200'
              } shadow-lg`} />

              {/* Content */}
              <div className="bg-gray-50 rounded-lg p-4 hover:bg-gray-100 transition-colors">
                {/* Title */}
                <div className="flex items-center gap-2 mb-2">
                  <span className="font-bold text-gray-900">
                    {isInitial ? '🎯 Entry 1 (Initial)' : `📊 DCA ${entry.dca_count}`}
                  </span>
                  {!isInitial && (
                    <span className={`text-sm px-2 py-0.5 rounded ${
                      priceChange < 0 ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                    }`}>
                      {priceChange > 0 ? '+' : ''}{priceChange.toFixed(2)}% from initial
                    </span>
                  )}
                </div>

                {/* Price */}
                <div className="text-2xl font-bold text-gray-900 mb-1">
                  ${entry.price.toLocaleString()}
                </div>

                {/* Time */}
                <div className="text-sm text-gray-600 mb-2">
                  {formatDateTime(entry.timestamp)}
                  {timeDiff && (
                    <span className="ml-2 text-purple-600">
                      ({timeDiff} later)
                    </span>
                  )}
                </div>

                {/* Amount */}
                <div className="flex items-center gap-4 text-sm">
                  <span className="text-gray-700">
                    {entry.quantity.toFixed(8)} BTC
                  </span>
                  <span className="text-gray-400">•</span>
                  <span className="font-semibold text-purple-600">
                    ${entry.investment.toLocaleString()}
                  </span>
                </div>

                {/* Reason */}
                <div className="mt-2 text-sm text-gray-500 italic">
                  📝 {entry.reason}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
```

---

## 📊 5. DCA Price Chart

### 디자인

```
┌─────────────────────────────────────────────────────────┐
│  Entry Price Movement & DCA Levels                      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  $117,000 ┤                                            │
│           │                            ╱───TP          │
│  $115,000 ┤                         ╱                  │
│           │                      ╱                      │
│  $113,000 ┤  🎯Entry 1 ────────                        │
│           │     ╲                                       │
│  $112,000 ┤      ╲  📊DCA 1                            │
│           │       ╲  📊DCA 2                            │
│  $111,000 ┤        ╲─📊DCA 3                           │
│           │         ╲                                   │
│  $110,000 ┤          ╲___min                           │
│           │                                             │
│           └─┬────┬────┬────┬────┬────┬────┬────┬───    │
│            11:30 14:30 15:00 15:15 ...               │
│                                                         │
│  Legend:                                                │
│  🎯 Initial Entry  📊 DCA Entry  ─── Avg Entry        │
│  ··· Exit Price    ─── Price Action                   │
└─────────────────────────────────────────────────────────┘
```

### 컴포넌트 코드

```typescript
// components/backtest/DCAChart.tsx
import { Line } from 'react-chartjs-2';

export const DCAChart: React.FC<{ trade: Trade }> = ({ trade }) => {
  // 차트 데이터 준비 (실제로는 API에서 candle data 필요)
  const data = {
    labels: trade.entry_history.map(e =>
      new Date(e.timestamp).toLocaleTimeString('ko-KR', {
        hour: '2-digit',
        minute: '2-digit'
      })
    ),
    datasets: [
      {
        label: 'Entry Price',
        data: trade.entry_history.map(e => e.price),
        borderColor: 'rgb(147, 51, 234)', // purple
        backgroundColor: 'rgba(147, 51, 234, 0.1)',
        pointRadius: 8,
        pointBackgroundColor: trade.entry_history.map((e, idx) =>
          idx === 0 ? 'rgb(34, 197, 94)' : 'rgb(147, 51, 234)' // green for initial, purple for DCA
        ),
        pointBorderColor: '#fff',
        pointBorderWidth: 2,
        tension: 0.4
      },
      {
        label: 'Average Entry',
        data: trade.entry_history.map(() => trade.entry_price),
        borderColor: 'rgb(99, 102, 241)', // indigo
        borderDash: [5, 5],
        pointRadius: 0,
        borderWidth: 2
      },
      {
        label: 'Exit Price',
        data: trade.entry_history.map(() => trade.exit_price),
        borderColor: 'rgb(245, 158, 11)', // amber
        borderDash: [3, 3],
        pointRadius: 0,
        borderWidth: 2
      }
    ]
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'bottom' as const,
      },
      title: {
        display: true,
        text: 'Entry Price Movement & DCA Levels',
        font: {
          size: 16,
          weight: 'bold'
        }
      },
      tooltip: {
        callbacks: {
          afterLabel: (context: any) => {
            const entry = trade.entry_history[context.dataIndex];
            return [
              `Quantity: ${entry.quantity.toFixed(8)} BTC`,
              `Investment: $${entry.investment.toLocaleString()}`,
              `Reason: ${entry.reason}`
            ];
          }
        }
      }
    },
    scales: {
      y: {
        title: {
          display: true,
          text: 'Price (USDT)'
        },
        ticks: {
          callback: (value: number) => `$${value.toLocaleString()}`
        }
      },
      x: {
        title: {
          display: true,
          text: 'Time'
        }
      }
    }
  };

  return (
    <div className="mt-6 bg-white rounded-lg p-4 border border-gray-200">
      <div style={{ height: '300px' }}>
        <Line data={data} options={options} />
      </div>
    </div>
  );
};
```

---

## 💰 6. DCA Summary

### 디자인

```
┌─────────────────────────────────────────────────────────┐
│  💰 Summary                                             │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Total Entries        4회                               │
│  Total Investment     $40,000                           │
│  Average Entry        $111,733.52                       │
│  Price Improvement    -0.75% ↓                          │
│  Position Size        4x initial                        │
│                                                         │
│  ───────────────────────────────────────────────────    │
│                                                         │
│  💡 DCA Effect Analysis:                                │
│  • Without DCA: $393 profit (estimated)                │
│  • With DCA: $1,874 profit (+376.5%) 🚀               │
│  • Risk: 4x larger position, higher exposure           │
└─────────────────────────────────────────────────────────┘
```

---

## 🎨 7. 전체 페이지 컴포넌트

```typescript
// app/backtest/[id]/page.tsx
export default function BacktestResultPage({ params }: { params: { id: string } }) {
  const { data: result, isLoading } = useBacktestResult(params.id);

  if (isLoading) return <LoadingSkeleton />;
  if (!result) return <NotFound />;

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      {/* Header */}
      <BacktestHeader result={result} />

      {/* Performance Summary */}
      <PerformanceSummary result={result} />

      {/* Equity Curve */}
      <div className="mb-8">
        <h2 className="text-2xl font-bold mb-4">📈 Equity Curve</h2>
        <EquityCurveChart data={result.equity_curve} />
      </div>

      {/* Trades List */}
      <div>
        <h2 className="text-2xl font-bold mb-4">
          🎯 Trades ({result.total_trades})
        </h2>
        <div className="space-y-4">
          {result.trades.map((trade) => (
            <TradeCard key={trade.trade_number} trade={trade} />
          ))}
        </div>
      </div>
    </div>
  );
}
```

---

## 📱 반응형 디자인

### 모바일 (< 768px)

- Performance Summary: 2x3 grid
- Trade Card: 전체 너비, 세로 스택
- DCA Timeline: 왼쪽 여백 축소
- Chart: 높이 200px

### 태블릿 (768px ~ 1024px)

- Performance Summary: 2x3 grid
- Trade Card: 전체 너비
- Chart: 높이 300px

### 데스크탑 (> 1024px)

- Performance Summary: 1x6 grid (한 줄)
- Trade Card: max-width 사용
- Chart: 높이 400px

---

## 🎨 색상 팔레트

```typescript
// tailwind.config.js 추가
module.exports = {
  theme: {
    extend: {
      colors: {
        // DCA 전용 색상
        'dca-purple': {
          50: '#faf5ff',
          500: '#9333ea',
          600: '#7c3aed',
          700: '#6d28d9',
        },
        'dca-indigo': {
          500: '#6366f1',
          600: '#4f46e5',
        },
        // Trade 상태 색상
        'trade-long': {
          bg: '#dcfce7',
          text: '#16a34a',
        },
        'trade-short': {
          bg: '#fee2e2',
          text: '#dc2626',
        }
      }
    }
  }
}
```

---

## ✅ Next.js 개발자 체크리스트

### 1단계: 기본 구조
- [ ] `/app/backtest/[id]/page.tsx` 생성
- [ ] API 연결 (`/api/v1/backtest/{id}`)
- [ ] TypeScript 타입 정의
- [ ] Tailwind CSS 설정

### 2단계: 컴포넌트 개발
- [ ] `MetricCard` 컴포넌트
- [ ] `PerformanceSummary` 컴포넌트
- [ ] `TradeCard` 컴포넌트 (기본)
- [ ] `DCABadge` 컴포넌트
- [ ] `EntryTimeline` 컴포넌트
- [ ] `DCASummary` 컴포넌트

### 3단계: 차트 통합
- [ ] `react-chartjs-2` 설치
- [ ] `EquityCurveChart` 컴포넌트
- [ ] `DCAChart` 컴포넌트

### 4단계: 인터랙션
- [ ] DCA Details 펼치기/접기
- [ ] 차트 호버 툴팁
- [ ] 반응형 레이아웃

### 5단계: 최적화
- [ ] Loading skeleton
- [ ] Error boundary
- [ ] Image optimization
- [ ] Code splitting

---

이 문서를 Next.js 개발자에게 전달하면 DCA 정보를 포함한 완전한 백테스트 결과 UI를 구현할 수 있습니다! 🚀
