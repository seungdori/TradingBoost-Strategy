# BACKTEST API - Partial Exits & Trailing Stop

**Last Updated**: 2025-11-03
**Status**: Production Ready

---

## API Request Format

### Endpoint

```http
POST /backtest
```

### Request Body

```json
{
  "symbol": "BTC-USDT-SWAP",
  "timeframe": "1m",
  "start_date": "2025-01-01T00:00:00Z",
  "end_date": "2025-01-31T23:59:59Z",
  "strategy_name": "hyperrsi",
  "strategy_params": {
    // Partial Exits (TP1/TP2/TP3)
    "use_tp1": true,
    "use_tp2": true,
    "use_tp3": true,
    "tp_option": "percentage",  // "percentage" | "atr" | "price"
    "tp1_value": 2.0,      // Value based on tp_option (% / ATR multiplier / price)
    "tp2_value": 3.0,
    "tp3_value": 4.0,
    "tp1_ratio": 30,       // Exit ratio % (e.g., 30 = 30% of position)
    "tp2_ratio": 30,
    "tp3_ratio": 30,

    // Trailing Stop (HYPERRSI complete flow)
    "trailing_stop_active": true,
    "trailing_start_point": "tp3",  // "tp1" | "tp2" | "tp3"
    "trailing_stop_offset_value": 0.5,  // Offset % (e.g., 0.5 = 0.5%)
    "use_trailing_stop_value_with_tp2_tp3_difference": false
  }
}
```

### Parameters

#### Partial Exits

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `use_tp1` | boolean | No | `false` | Enable TP1 partial exit |
| `use_tp2` | boolean | No | `false` | Enable TP2 partial exit |
| `use_tp3` | boolean | No | `false` | Enable TP3 partial exit |
| `tp_option` | string | No | `"percentage"` | TP calculation method ("percentage", "atr", "price") |
| `tp1_value` | number | No | - | TP1 value (% if percentage, ATR multiplier if atr, price if price) |
| `tp2_value` | number | No | - | TP2 value (% if percentage, ATR multiplier if atr, price if price) |
| `tp3_value` | number | No | - | TP3 value (% if percentage, ATR multiplier if atr, price if price) |
| `tp1_ratio` | number | No | - | Exit ratio % (0-100) |
| `tp2_ratio` | number | No | - | Exit ratio % (0-100) |
| `tp3_ratio` | number | No | - | Exit ratio % (0-100) |

#### Trailing Stop

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `trailing_stop_active` | boolean | No | `false` | Enable trailing stop |
| `trailing_start_point` | string | No | `"tp3"` | TP level to activate trailing ("tp1", "tp2", "tp3") |
| `trailing_stop_offset_value` | number | No | `0.5` | Offset % (e.g., 0.5 = 0.5%) |
| `use_trailing_stop_value_with_tp2_tp3_difference` | boolean | No | `false` | Use TP2-TP3 price diff as offset |

---

## API Response Format

### Response Body

```json
{
  "backtest_id": "uuid",
  "status": "completed",
  "result": {
    "total_pnl": 1234.56,
    "total_trades": 10,
    "win_rate": 70.0
  },
  "trades": [
    {
      "trade_number": 1,
      "side": "long",
      "entry_price": 100000.0,
      "exit_price": 102000.0,
      "quantity": 0.3,
      "pnl": 5970.0,
      "exit_reason": "tp1",

      // Partial exit metadata
      "is_partial_exit": true,
      "tp_level": 1,
      "exit_ratio": 0.3,
      "remaining_quantity": 0.7
    },
    {
      "trade_number": 1,
      "side": "long",
      "entry_price": 100000.0,
      "exit_price": 103000.0,
      "quantity": 0.3,
      "pnl": 8970.0,
      "exit_reason": "tp2",

      "is_partial_exit": true,
      "tp_level": 2,
      "exit_ratio": 0.3,
      "remaining_quantity": 0.4
    },
    {
      "trade_number": 1,
      "side": "long",
      "entry_price": 100000.0,
      "exit_price": 104000.0,
      "quantity": 0.4,
      "pnl": 15940.0,
      "exit_reason": "tp3",

      "is_partial_exit": true,
      "tp_level": 3,
      "exit_ratio": 0.4,
      "remaining_quantity": 0.0
    }
  ]
}
```

### Trade Fields

| Field | Type | Description |
|-------|------|-------------|
| `is_partial_exit` | boolean | `true` if this is a partial exit (TP1/TP2/TP3) |
| `tp_level` | number \| null | TP level (1, 2, or 3) if partial exit |
| `exit_ratio` | number \| null | Exit ratio (0.0-1.0) if partial exit |
| `remaining_quantity` | number \| null | Remaining position quantity after this exit |

---

## TypeScript Interface

```typescript
export interface StrategyParams {
  // Partial Exits
  use_tp1?: boolean;
  use_tp2?: boolean;
  use_tp3?: boolean;
  tp_option?: "percentage" | "atr" | "price";
  tp1_value?: number;
  tp2_value?: number;
  tp3_value?: number;
  tp1_ratio?: number;
  tp2_ratio?: number;
  tp3_ratio?: number;

  // Trailing Stop
  trailing_stop_active?: boolean;
  trailing_start_point?: "tp1" | "tp2" | "tp3";
  trailing_stop_offset_value?: number;
  use_trailing_stop_value_with_tp2_tp3_difference?: boolean;
}

export interface Trade {
  trade_number: number;
  side: "long" | "short";
  entry_price: number;
  exit_price: number;
  quantity: number;
  pnl: number;
  exit_reason: string;

  // Partial exit metadata
  is_partial_exit: boolean;
  tp_level: 1 | 2 | 3 | null;
  exit_ratio: number | null;
  remaining_quantity: number | null;
}
```

---

## Examples

### Example 1: Complete HYPERRSI Flow (TP + Trailing Stop)

**Request**:

```json
{
  "strategy_params": {
    "use_tp1": true,
    "use_tp2": true,
    "use_tp3": true,
    "tp_option": "percentage",
    "tp1_value": 2.0,
    "tp2_value": 3.0,
    "tp3_value": 4.0,
    "tp1_ratio": 30,
    "tp2_ratio": 30,
    "tp3_ratio": 30,
    "trailing_stop_active": true,
    "trailing_start_point": "tp3",
    "trailing_stop_offset_value": 0.5
  }
}
```

**Expected Flow**:

1. TP1 @ +2%: Close 30% (remaining: 70%)
2. TP2 @ +3%: Close 30% (remaining: 40%)
3. TP3 @ +4%: Close 30% (remaining: 10%)
4. Trailing stop activated after TP3
5. Final exit @ trailing stop: Close 10% (remaining: 0%)

**Response**: 4 trades (3 partial exits + 1 trailing stop exit)

### Example 2: Partial Exits Only (No Trailing Stop)

**Request**:

```json
{
  "strategy_params": {
    "use_tp1": true,
    "use_tp2": true,
    "use_tp3": true,
    "tp_option": "percentage",
    "tp1_value": 2.0,
    "tp2_value": 3.0,
    "tp3_value": 4.0,
    "tp1_ratio": 30,
    "tp2_ratio": 30,
    "tp3_ratio": 40,
    "trailing_stop_active": false
  }
}
```

**Response**: 3 trades (all partial exits, no trailing)

### Example 3: ATR-Based TP

**Request**:

```json
{
  "strategy_params": {
    "use_tp1": true,
    "use_tp2": true,
    "use_tp3": true,
    "tp_option": "atr",
    "tp1_value": 1.5,
    "tp2_value": 2.0,
    "tp3_value": 3.0,
    "tp1_ratio": 30,
    "tp2_ratio": 30,
    "tp3_ratio": 40
  }
}
```

**Expected**: TP prices calculated as entry_price ± (ATR × tp_value)

**Response**: 3 trades with ATR-based TP levels

### Example 4: Disabled (Backward Compatibility)

**Request**:

```json
{
  "strategy_params": {
    "use_tp1": false,
    "use_tp2": false,
    "use_tp3": false
  }
}
```

**Response**: Single trade with `is_partial_exit: false`

---

## Validation Rules

1. **Exit Ratio Sum**: `tp1_ratio + tp2_ratio + tp3_ratio ≤ 100`
2. **TP Value Order** (LONG): `tp1_value < tp2_value < tp3_value`
3. **TP Value Order** (SHORT): `tp1_value > tp2_value > tp3_value`
4. **Trailing Offset**: Must be > 0 if trailing stop enabled

---

## Integration Checklist

- [ ] TypeScript interface 추가
- [ ] API request에 새 파라미터 추가
- [ ] API response 파싱에 새 필드 추가
- [ ] UI 설정 폼 구현 (optional)
- [ ] 결과 표시 UI 업데이트 (optional)
- [ ] Validation 로직 추가 (optional)
- [ ] 테스트 시나리오 1 통과 (Complete HYPERRSI flow)
- [ ] 테스트 시나리오 2 통과 (Backward compatibility)

---

## Notes

- All new fields are **optional** (backward compatible)
- DCA compatible: Uses average entry price
- Exit ratios based on original position size, not remaining
- Trailing stop activates only after specified TP level hits
