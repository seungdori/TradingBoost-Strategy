# Partial Exits API Documentation (분할매도 API 문서)

**Date**: 2025-11-03
**Version**: 1.0.0
**Status**: ✅ Production Ready

## Overview

This system implements the **complete HYPERRSI profit-taking logic** with partial exits (분할매도) and trailing stop, allowing positions to be closed progressively through TP levels and then tracking price with a dynamic trailing stop.

### Complete HYPERRSI Flow

1. **TP1**: Close first portion at +X% profit (e.g., 30%)
2. **TP2**: Close second portion at +Y% profit (e.g., 30%)
3. **TP3**: Close third portion at +Z% profit (e.g., 40%)
4. **Trailing Stop Activation**: Automatically activates after specified TP level (e.g., TP3)
5. **Trailing Stop Tracking**: Dynamically adjusts stop price as price moves favorably
6. **Final Exit**: Closes remaining position when trailing stop is hit

### Key Features

- **3-Level Partial Exits**: Independent TP1, TP2, TP3 configuration
- **Flexible Ratios**: Configure how much of position to close at each level (e.g., 30%, 30%, 40%)
- **Trailing Stop**: HYPERRSI-style trailing stop activated after TP level
- **Two Offset Methods**: Percentage-based or TP2-TP3 price difference
- **Dynamic Tracking**: Tracks highest/lowest price and adjusts stop automatically
- **Trade Tracking**: Each partial exit and final trailing stop creates separate trade records
- **DCA Compatible**: Works seamlessly with DCA (Dollar Cost Averaging) entries
- **Exact HYPERRSI Match**: Mirrors live HYPERRSI trading behavior precisely

---

## Request Parameters

### Backtest Run Request

When creating a backtest with partial exits, include these parameters in `strategy_params`:

#### Partial Exit Configuration (TP1/TP2/TP3)

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `use_tp1` | boolean | No | `false` | Enable TP1 level |
| `use_tp2` | boolean | No | `false` | Enable TP2 level |
| `use_tp3` | boolean | No | `false` | Enable TP3 level |
| `tp1_value` | number | No | `2.0` | TP1 profit target in % (e.g., 2.0 = +2% profit) |
| `tp2_value` | number | No | `3.0` | TP2 profit target in % |
| `tp3_value` | number | No | `4.0` | TP3 profit target in % |
| `tp1_ratio` | number | No | `30` | Percentage of position to close at TP1 (0-100) |
| `tp2_ratio` | number | No | `30` | Percentage of position to close at TP2 (0-100) |
| `tp3_ratio` | number | No | `40` | Percentage of position to close at TP3 (0-100) |

#### Trailing Stop Configuration (HYPERRSI Complete Flow)

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `trailing_stop_active` | boolean | No | `false` | Enable trailing stop after TP level |
| `trailing_start_point` | string | No | `"tp3"` | TP level that triggers trailing stop activation ("tp1", "tp2", or "tp3") |
| `trailing_stop_offset_value` | number | No | `0.5` | Trailing stop offset in % (e.g., 0.5 = 0.5% offset from current price) |
| `use_trailing_stop_value_with_tp2_tp3_difference` | boolean | No | `false` | Use TP2-TP3 price difference as offset instead of percentage |

**Important Notes**:
- Ratios should sum to 100 for complete position closure
- Ratios are based on ORIGINAL position size, not remaining
- TP levels are triggered sequentially (TP1 → TP2 → TP3)
- When all partial exits are disabled, the original single `take_profit_percent` is used

### Example Request

```json
{
  "symbol": "BTC-USDT-SWAP",
  "timeframe": "1m",
  "start_date": "2025-01-01T00:00:00Z",
  "end_date": "2025-01-31T23:59:59Z",
  "strategy_name": "hyperrsi",
  "strategy_params": {
    "entry_option": "rsi_trend",
    "rsi_entry_option": "돌파",
    "rsi_oversold": 30,
    "rsi_overbought": 70,
    "rsi_period": 14,
    "leverage": 10,
    "investment": 100,

    "tp_sl_option": "fixed",
    "stop_loss_percent": 2.0,

    "use_tp1": true,
    "use_tp2": true,
    "use_tp3": true,
    "tp1_value": 2.0,
    "tp2_value": 3.0,
    "tp3_value": 4.0,
    "tp1_ratio": 30,
    "tp2_ratio": 30,
    "tp3_ratio": 30,

    "trailing_stop_active": true,
    "trailing_start_point": "tp3",
    "trailing_stop_offset_value": 0.5,
    "use_trailing_stop_value_with_tp2_tp3_difference": false,

    "pyramiding_limit": 3,
    "entry_multiplier": 0.5,
    "pyramiding_entry_type": "퍼센트 기준",
    "pyramiding_value": 3.0
  },
  "initial_balance": 10000.0,
  "fee_rate": 0.0005,
  "slippage_percent": 0.05
}
```

---

## Response Schema

### Trade Response

Each trade in the backtest result includes the following fields:

#### Basic Trade Fields

| Field | Type | Description |
|-------|------|-------------|
| `trade_number` | integer | Sequential trade number |
| `side` | string | "long" or "short" |
| `entry_timestamp` | string (ISO 8601) | Entry time (UTC) |
| `entry_price` | number | Average entry price |
| `exit_timestamp` | string (ISO 8601) | Exit time (UTC) |
| `exit_price` | number | Exit price |
| `exit_reason` | string | "tp1", "tp2", "tp3", "take_profit", "stop_loss", "trailing_stop", "signal" |
| `quantity` | number | Position size for this trade |
| `leverage` | number | Leverage multiplier |
| `pnl` | number | Realized P&L in USDT |
| `pnl_percent` | number | P&L percentage |
| `entry_fee` | number | Entry trading fee |
| `exit_fee` | number | Exit trading fee |

#### DCA Metadata Fields

| Field | Type | Description |
|-------|------|-------------|
| `dca_count` | integer | Number of additional DCA entries (0 = no DCA) |
| `entry_history` | array | Complete entry history with prices and quantities |
| `total_investment` | number | Total investment across all entries (USDT) |

#### Partial Exit Metadata Fields (NEW!)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `is_partial_exit` | boolean | Yes | `true` if this is a partial exit, `false` otherwise |
| `tp_level` | integer \| null | No | TP level that was hit (1, 2, or 3). `null` if not a partial exit |
| `exit_ratio` | number \| null | No | Ratio of original position closed (0-1). `null` if not a partial exit |
| `remaining_quantity` | number \| null | No | Position size remaining after this exit. `null` if not a partial exit |

### Example Response - Partial Exit Trades

```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "symbol": "BTC-USDT-SWAP",
  "timeframe": "1m",
  "total_trades": 3,
  "trades": [
    {
      "trade_number": 1,
      "side": "long",
      "entry_timestamp": "2025-01-15T10:30:00Z",
      "entry_price": 100000.0,
      "exit_timestamp": "2025-01-15T10:35:00Z",
      "exit_price": 102000.0,
      "exit_reason": "tp1",
      "quantity": 0.3,
      "leverage": 10.0,
      "pnl": 5970.0,
      "pnl_percent": 2.0,
      "entry_fee": 15.0,
      "exit_fee": 15.3,
      "dca_count": 0,
      "entry_history": [
        {
          "price": 100000.0,
          "quantity": 1.0,
          "investment": 100.0,
          "timestamp": "2025-01-15T10:30:00Z",
          "reason": "initial_entry",
          "dca_count": 0
        }
      ],
      "total_investment": 100.0,
      "is_partial_exit": true,
      "tp_level": 1,
      "exit_ratio": 0.3,
      "remaining_quantity": 0.7
    },
    {
      "trade_number": 2,
      "side": "long",
      "entry_timestamp": "2025-01-15T10:30:00Z",
      "entry_price": 100000.0,
      "exit_timestamp": "2025-01-15T10:40:00Z",
      "exit_price": 103000.0,
      "exit_reason": "tp2",
      "quantity": 0.3,
      "leverage": 10.0,
      "pnl": 8970.0,
      "pnl_percent": 3.0,
      "entry_fee": 15.0,
      "exit_fee": 15.45,
      "dca_count": 0,
      "entry_history": [
        {
          "price": 100000.0,
          "quantity": 1.0,
          "investment": 100.0,
          "timestamp": "2025-01-15T10:30:00Z",
          "reason": "initial_entry",
          "dca_count": 0
        }
      ],
      "total_investment": 100.0,
      "is_partial_exit": true,
      "tp_level": 2,
      "exit_ratio": 0.3,
      "remaining_quantity": 0.4
    },
    {
      "trade_number": 3,
      "side": "long",
      "entry_timestamp": "2025-01-15T10:30:00Z",
      "entry_price": 100000.0,
      "exit_timestamp": "2025-01-15T10:45:00Z",
      "exit_price": 104000.0,
      "exit_reason": "tp3",
      "quantity": 0.4,
      "leverage": 10.0,
      "pnl": 15940.0,
      "pnl_percent": 4.0,
      "entry_fee": 20.0,
      "exit_fee": 20.8,
      "dca_count": 0,
      "entry_history": [
        {
          "price": 100000.0,
          "quantity": 1.0,
          "investment": 100.0,
          "timestamp": "2025-01-15T10:30:00Z",
          "reason": "initial_entry",
          "dca_count": 0
        }
      ],
      "total_investment": 100.0,
      "is_partial_exit": true,
      "tp_level": 3,
      "exit_ratio": 0.4,
      "remaining_quantity": 0.0
    }
  ]
}
```

---

## TypeScript Interfaces

For TypeScript/JavaScript frontends, use these interfaces:

```typescript
/**
 * Strategy parameters for partial exits configuration
 */
interface StrategyParams {
  // ... other strategy params ...

  // Partial exits (TP1/TP2/TP3)
  use_tp1?: boolean;
  use_tp2?: boolean;
  use_tp3?: boolean;
  tp1_value?: number;  // Profit target in %
  tp2_value?: number;
  tp3_value?: number;
  tp1_ratio?: number;  // Position % to close (0-100)
  tp2_ratio?: number;
  tp3_ratio?: number;

  // Trailing stop (HYPERRSI complete flow)
  trailing_stop_active?: boolean;
  trailing_start_point?: "tp1" | "tp2" | "tp3";
  trailing_stop_offset_value?: number;
  use_trailing_stop_value_with_tp2_tp3_difference?: boolean;
}

/**
 * Backtest run request
 */
interface BacktestRunRequest {
  symbol: string;
  timeframe: string;
  start_date: string;  // ISO 8601 format
  end_date: string;
  strategy_name: string;
  strategy_params: StrategyParams;
  initial_balance?: number;
  fee_rate?: number;
  slippage_percent?: number;
}

/**
 * Single trade result
 */
interface TradeResponse {
  // Basic fields
  trade_number: number;
  side: "long" | "short";
  entry_timestamp: string;
  entry_price: number;
  exit_timestamp: string | null;
  exit_price: number | null;
  exit_reason: "tp1" | "tp2" | "tp3" | "take_profit" | "stop_loss" | "trailing_stop" | "signal" | null;
  quantity: number;
  leverage: number;
  pnl: number | null;
  pnl_percent: number | null;
  entry_fee: number;
  exit_fee: number;

  // DCA metadata
  dca_count: number;
  entry_history: Array<{
    price: number;
    quantity: number;
    investment: number;
    timestamp: string;
    reason: string;
    dca_count: number;
  }>;
  total_investment: number;

  // Partial exit metadata
  is_partial_exit: boolean;
  tp_level: 1 | 2 | 3 | null;
  exit_ratio: number | null;  // 0-1 range
  remaining_quantity: number | null;
}

/**
 * Complete backtest result
 */
interface BacktestDetailResponse {
  id: string;
  user_id: string;
  symbol: string;
  timeframe: string;
  start_date: string;
  end_date: string;
  strategy_name: string;
  strategy_params: StrategyParams;

  status: "pending" | "running" | "completed" | "failed";
  started_at: string;
  completed_at: string | null;
  execution_time_seconds: number | null;

  initial_balance: number;
  final_balance: number;
  total_return: number;
  total_return_percent: number;
  max_drawdown: number;
  max_drawdown_percent: number;

  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  profit_factor: number;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;

  avg_win: number;
  avg_loss: number;
  largest_win: number;
  largest_loss: number;
  avg_trade_duration_minutes: number | null;
  total_fees_paid: number;

  trades: TradeResponse[];
  equity_curve: Array<{
    timestamp: string;
    balance: number;
    drawdown_percent: number;
  }>;
  detailed_metrics: Record<string, any> | null;
}
```

---

## UI Implementation Guidelines

### Displaying Partial Exits

When displaying trades in the frontend, consider these approaches:

#### 1. Group Partial Exits by Entry

Group all partial exits from the same entry together:

```typescript
// Example: Group trades by entry timestamp
const groupedTrades = trades.reduce((groups, trade) => {
  const key = trade.entry_timestamp;
  if (!groups[key]) {
    groups[key] = [];
  }
  groups[key].push(trade);
  return groups;
}, {} as Record<string, TradeResponse[]>);

// Display each group as a "position" with multiple exits
Object.entries(groupedTrades).forEach(([entryTime, exitTrades]) => {
  console.log(`Position opened at ${entryTime}`);
  exitTrades.forEach(trade => {
    if (trade.is_partial_exit) {
      console.log(`  TP${trade.tp_level}: ${(trade.exit_ratio! * 100).toFixed(0)}% closed @ ${trade.exit_price}, P&L: ${trade.pnl}`);
    } else {
      console.log(`  Full exit @ ${trade.exit_price}, P&L: ${trade.pnl}`);
    }
  });
});
```

#### 2. Visual Indicators

- **Badge/Tag**: Show "TP1", "TP2", "TP3" badges for partial exits
- **Progress Bar**: Visualize how much of position has been closed (e.g., 30% → 60% → 100%)
- **Color Coding**: Different colors for each TP level
- **Remaining Quantity**: Display remaining position size after each partial exit

#### 3. Trade Table Columns

Suggested columns for trade table with partial exits:

| Column | Description |
|--------|-------------|
| Entry Time | Position entry timestamp |
| Exit Time | This partial exit timestamp |
| Side | Long/Short |
| Entry Price | Average entry price |
| Exit Price | This exit price |
| Exit Reason | TP1/TP2/TP3 or other reason |
| Quantity | Amount closed in this exit |
| Remaining | Position size still open |
| P&L | Profit/Loss for this partial exit |
| Total P&L | Cumulative P&L for entire position |

#### 4. Filtering Trades

Allow users to filter trades:

```typescript
// Filter partial exits only
const partialExits = trades.filter(t => t.is_partial_exit);

// Filter by TP level
const tp1Exits = trades.filter(t => t.tp_level === 1);
const tp2Exits = trades.filter(t => t.tp_level === 2);
const tp3Exits = trades.filter(t => t.tp_level === 3);

// Filter full exits (non-partial)
const fullExits = trades.filter(t => !t.is_partial_exit);
```

### Performance Metrics

When calculating aggregate metrics, consider:

1. **Total Trades**: Count partial exits separately or as a single position?
   - Recommend: Count as separate trades for detailed analysis

2. **Win Rate**: Based on individual partial exits or complete positions?
   - Recommend: Provide both metrics

3. **Average P&L**: Per partial exit or per complete position?
   - Recommend: Show both "Avg P&L per exit" and "Avg P&L per position"

---

## Common Use Cases

### Use Case 1: Conservative Exit Strategy

Take profits gradually with tighter levels:

```json
{
  "use_tp1": true,
  "use_tp2": true,
  "use_tp3": true,
  "tp1_value": 1.0,    // +1% profit
  "tp2_value": 1.5,    // +1.5% profit
  "tp3_value": 2.0,    // +2% profit
  "tp1_ratio": 50,     // Close 50% at TP1
  "tp2_ratio": 30,     // Close 30% at TP2
  "tp3_ratio": 20      // Close 20% at TP3
}
```

### Use Case 2: Aggressive Profit Maximization

Hold more position for higher targets:

```json
{
  "use_tp1": true,
  "use_tp2": true,
  "use_tp3": true,
  "tp1_value": 2.0,    // +2% profit
  "tp2_value": 4.0,    // +4% profit
  "tp3_value": 6.0,    // +6% profit
  "tp1_ratio": 20,     // Close only 20% at TP1
  "tp2_ratio": 30,     // Close 30% at TP2
  "tp3_ratio": 50      // Close 50% at TP3
}
```

### Use Case 3: Two-Level Exit

Use only TP1 and TP2:

```json
{
  "use_tp1": true,
  "use_tp2": true,
  "use_tp3": false,    // Disable TP3
  "tp1_value": 2.0,
  "tp2_value": 4.0,
  "tp1_ratio": 50,     // Close 50% at TP1
  "tp2_ratio": 50      // Close remaining 50% at TP2
}
```

### Use Case 4: Disable Partial Exits

Use traditional single take-profit:

```json
{
  "use_tp1": false,
  "use_tp2": false,
  "use_tp3": false,
  "take_profit_percent": 4.0  // Use original single TP
}
```

---

## Validation Rules

### Backend Validation

The backend validates:

1. **TP Ratios**: Must be between 0 and 100
2. **TP Values**: Must be positive numbers
3. **Sequential Prices**: For LONG positions, tp1_price < tp2_price < tp3_price
4. **Sequential Prices**: For SHORT positions, tp1_price > tp2_price > tp3_price

### Frontend Validation (Recommended)

Implement these validations before submitting:

```typescript
function validatePartialExits(params: StrategyParams): string[] {
  const errors: string[] = [];

  // Check if any TP is enabled
  const hasPartialExits = params.use_tp1 || params.use_tp2 || params.use_tp3;

  if (hasPartialExits) {
    // Validate ratios sum to 100 (optional, can be less)
    const totalRatio =
      (params.use_tp1 ? params.tp1_ratio || 0 : 0) +
      (params.use_tp2 ? params.tp2_ratio || 0 : 0) +
      (params.use_tp3 ? params.tp3_ratio || 0 : 0);

    if (totalRatio > 100) {
      errors.push("Total of TP ratios cannot exceed 100%");
    }

    // Validate TP values are in ascending order
    const tpValues: number[] = [];
    if (params.use_tp1 && params.tp1_value) tpValues.push(params.tp1_value);
    if (params.use_tp2 && params.tp2_value) tpValues.push(params.tp2_value);
    if (params.use_tp3 && params.tp3_value) tpValues.push(params.tp3_value);

    for (let i = 1; i < tpValues.length; i++) {
      if (tpValues[i] <= tpValues[i - 1]) {
        errors.push("TP values must be in ascending order (TP1 < TP2 < TP3)");
        break;
      }
    }

    // Validate positive values
    if (params.use_tp1 && (params.tp1_value <= 0 || params.tp1_ratio <= 0)) {
      errors.push("TP1 value and ratio must be positive");
    }
    if (params.use_tp2 && (params.tp2_value <= 0 || params.tp2_ratio <= 0)) {
      errors.push("TP2 value and ratio must be positive");
    }
    if (params.use_tp3 && (params.tp3_value <= 0 || params.tp3_ratio <= 0)) {
      errors.push("TP3 value and ratio must be positive");
    }
  }

  return errors;
}
```

---

## Testing

### Sample Test Data

Use this test request to verify partial exits integration:

```bash
curl -X POST http://localhost:8013/api/v1/backtest/run \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTC-USDT-SWAP",
    "timeframe": "1m",
    "start_date": "2025-01-01T00:00:00Z",
    "end_date": "2025-01-02T00:00:00Z",
    "strategy_name": "hyperrsi",
    "strategy_params": {
      "entry_option": "rsi_trend",
      "rsi_entry_option": "돌파",
      "rsi_oversold": 30,
      "rsi_overbought": 70,
      "leverage": 10,
      "investment": 100,
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
  }'
```

### Expected Response

Check that response includes:

1. Trades with `is_partial_exit: true`
2. Sequential TP levels (1, 2, 3)
3. Decreasing `remaining_quantity` (0.7 → 0.4 → 0.0)
4. Correct `exit_reason` values ("tp1", "tp2", "tp3")

---

## Migration Guide

### From Single TP to Partial Exits

If you have existing code using single take-profit:

**Before (Single TP)**:
```json
{
  "take_profit_percent": 4.0
}
```

**After (Partial Exits)**:
```json
{
  "use_tp1": true,
  "use_tp2": false,
  "use_tp3": false,
  "tp1_value": 4.0,
  "tp1_ratio": 100  // Close 100% at TP1 (equivalent to single TP)
}
```

Or simply disable all partial exits to maintain old behavior:
```json
{
  "use_tp1": false,
  "use_tp2": false,
  "use_tp3": false,
  "take_profit_percent": 4.0  // Original single TP behavior
}
```

---

## FAQ

**Q: What happens if TP ratios don't sum to 100%?**
A: Remaining position will stay open until stopped out or manually closed. For example, if TP1=30%, TP2=30%, TP3=30%, then 10% remains open.

**Q: Can I use partial exits with DCA?**
A: Yes! Partial exits work seamlessly with DCA. Exit ratios are calculated from the total position size (including DCA entries).

**Q: What if price jumps over a TP level?**
A: The order simulator checks if price crossed the TP level within the candle. If yes, the TP is triggered at the TP price (not the close price).

**Q: Can I have different ratios for LONG vs SHORT?**
A: Currently, TP configuration applies to both LONG and SHORT positions. Different ratios per side would require separate backtest runs.

**Q: How are fees calculated for partial exits?**
A: Each partial exit incurs its own entry and exit fees based on the quantity closed in that specific exit.

**Q: Will partial exits affect win rate calculations?**
A: Each partial exit is counted as a separate trade. If you want position-level win rate, you'll need to group partial exits by entry timestamp.

**Q: When does trailing stop activate?**
A: Trailing stop activates automatically when the TP level specified in `trailing_start_point` is hit. Default is "tp3", meaning it activates after TP3 partial exit. You can also set it to "tp1" or "tp2" for earlier activation.

**Q: How is trailing stop offset calculated?**
A: Two methods are supported:
1. **Percentage-based** (default): `trailing_stop_offset_value` % of current price (e.g., 0.5% = $500 offset on $100,000 BTC)
2. **TP2-TP3 difference**: Uses the absolute price difference between TP3 and TP2 (e.g., if TP2=$103k, TP3=$104k, offset=$1k)

**Q: How does trailing stop track price?**
A: For LONG positions, it tracks the highest price reached and sets stop = highest_price - offset. For SHORT positions, it tracks the lowest price and sets stop = lowest_price + offset. The stop price only moves in the favorable direction (up for LONG, down for SHORT), never backward.

**Q: What happens if TP ratios sum to less than 100% with trailing stop?**
A: The remaining position after partial exits will be managed by the trailing stop. For example, if TP1+TP2+TP3=90%, the last 10% will be closed by the trailing stop trigger.

**Q: Can I use trailing stop without partial exits?**
A: Yes! You can disable all TPs (use_tp1=false, use_tp2=false, use_tp3=false) and set trailing_stop_active=true with trailing_start_point="tp3". This will activate trailing stop immediately after position entry (since no TP levels are active).

---

## Support

For issues or questions:

1. Check the main integration documentation: `PARTIAL_EXITS_INTEGRATION.md`
2. Review test cases: `BACKTEST/tests/test_partial_exits.py`
3. Contact backend team with specific error messages or unexpected behavior

---

**Last Updated**: 2025-11-03
**Backend Version**: BACKTEST v1.0.0
**Feature Status**: ✅ Production Ready
