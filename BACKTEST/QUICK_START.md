# BACKTEST Quick Start Guide

## Setup

### 1. Install Dependencies
```bash
# From project root
pip install -e .
```

### 2. Start TimescaleDB
Ensure TimescaleDB is running with historical candle data:
```bash
# Check if TimescaleDB is accessible
psql -h localhost -U your_user -d trading_db -c "SELECT COUNT(*) FROM candle_history;"
```

### 3. Start BACKTEST Service
```bash
cd BACKTEST
python main.py
```

Server will start on `http://localhost:8013`

## Running a Backtest

### Basic HYPERRSI Strategy Backtest

```bash
curl -X POST "http://localhost:8013/backtest/run" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTC-USDT-SWAP",
    "timeframe": "15m",
    "start_date": "2024-01-01T00:00:00Z",
    "end_date": "2024-01-31T23:59:59Z",
    "strategy_name": "hyperrsi",
    "strategy_params": {
      "entry_option": "rsi_trend",
      "rsi_oversold": 30,
      "rsi_overbought": 70,
      "rsi_period": 14,
      "leverage": 10,
      "investment": 100,
      "tp_sl_option": "fixed",
      "stop_loss_percent": 2.0,
      "take_profit_percent": 4.0,
      "trailing_stop_enabled": false,
      "trailing_stop_percent": 2.0
    },
    "initial_balance": 10000,
    "fee_rate": 0.0005,
    "slippage_percent": 0.05
  }'
```

### Response Structure

```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "user_id": "00000000-0000-0000-0000-000000000000",
  "symbol": "BTC-USDT-SWAP",
  "timeframe": "15m",
  "start_date": "2024-01-01T00:00:00Z",
  "end_date": "2024-01-31T23:59:59Z",
  "strategy_name": "hyperrsi",
  "strategy_params": {...},
  "started_at": "2024-10-31T10:30:00Z",
  "completed_at": "2024-10-31T10:30:05Z",
  "execution_time_seconds": 5.2,
  "initial_balance": 10000.0,
  "final_balance": 10450.25,
  "total_return": 450.25,
  "total_return_percent": 4.5,
  "total_trades": 15,
  "winning_trades": 10,
  "losing_trades": 5,
  "win_rate": 66.67,
  "profit_factor": 2.5,
  "sharpe_ratio": 1.85,
  "max_drawdown": 250.0,
  "max_drawdown_percent": 2.5,
  "average_win": 75.5,
  "average_loss": -30.2,
  "largest_win": 150.0,
  "largest_loss": -50.0,
  "trades": [
    {
      "trade_number": 1,
      "side": "long",
      "entry_timestamp": "2024-01-01T10:15:00Z",
      "entry_price": 42500.0,
      "entry_reason": "RSI oversold + bullish trend",
      "exit_timestamp": "2024-01-01T12:30:00Z",
      "exit_price": 43000.0,
      "exit_reason": "take_profit",
      "quantity": 0.023529,
      "leverage": 10.0,
      "pnl": 117.65,
      "pnl_percent": 11.76,
      "entry_fee": 0.05,
      "exit_fee": 0.05,
      "total_fees": 0.10,
      "take_profit_price": 43350.0,
      "stop_loss_price": 41650.0
    }
  ],
  "equity_curve": [
    {
      "timestamp": "2024-01-01T00:00:00Z",
      "balance": 10000.0,
      "equity": 10000.0,
      "drawdown": 0.0,
      "drawdown_percent": 0.0
    }
  ],
  "detailed_metrics": {
    "event_summary": {
      "position_opened": 15,
      "position_closed": 15,
      "take_profit_hit": 8,
      "stop_loss_hit": 7,
      "trailing_stop_hit": 2,
      "trailing_stop_activated": 12
    },
    "balance_stats": {
      "max_drawdown": 250.0,
      "max_drawdown_percent": 2.5,
      "peak_balance": 10650.0,
      "lowest_balance": 9750.0
    }
  }
}
```

## Strategy Parameters

### HYPERRSI Strategy

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `entry_option` | string | "rsi_trend" | Entry signal type: "rsi_only" or "rsi_trend" |
| `rsi_oversold` | float | 30.0 | RSI level for oversold (long entry) |
| `rsi_overbought` | float | 70.0 | RSI level for overbought (short entry) |
| `rsi_period` | int | 14 | RSI calculation period |
| `leverage` | float | 10.0 | Leverage multiplier |
| `investment` | float | 100.0 | Investment amount per trade (USDT) |
| `tp_sl_option` | string | "fixed" | TP/SL type: "fixed" or "dynamic_atr" |
| `stop_loss_percent` | float | 2.0 | Stop loss percentage (if fixed) |
| `take_profit_percent` | float | 4.0 | Take profit percentage (if fixed) |
| `atr_sl_multiplier` | float | 2.0 | ATR multiplier for SL (if dynamic_atr) |
| `atr_tp_multiplier` | float | 3.0 | ATR multiplier for TP (if dynamic_atr) |
| `trailing_stop_enabled` | bool | false | Enable trailing stop |
| `trailing_stop_percent` | float | 2.0 | Trailing stop percentage |

### Entry Options

**rsi_only**: Pure RSI signals
- Long when RSI < oversold
- Short when RSI > overbought
- No trend filter

**rsi_trend** (Recommended): RSI + trend filter
- Long when RSI < oversold AND (bullish or neutral trend)
- Short when RSI > overbought AND (bearish or neutral trend)
- Avoids counter-trend trades

### TP/SL Options

**fixed**: Fixed percentage
- Simple percentage-based levels
- SL: `entry_price * (1 - stop_loss_percent/100)`
- TP: `entry_price * (1 + take_profit_percent/100)`

**dynamic_atr**: Volatility-based
- Uses ATR indicator for dynamic levels
- SL: `entry_price - (ATR * atr_sl_multiplier)`
- TP: `entry_price + (ATR * atr_tp_multiplier)`
- Adapts to market volatility

### Example Configurations

#### Conservative (Lower Risk)
```json
{
  "entry_option": "rsi_trend",
  "rsi_oversold": 25,
  "rsi_overbought": 75,
  "leverage": 5,
  "investment": 100,
  "tp_sl_option": "fixed",
  "stop_loss_percent": 1.5,
  "take_profit_percent": 3.0,
  "trailing_stop_enabled": true,
  "trailing_stop_percent": 1.5
}
```

#### Aggressive (Higher Risk)
```json
{
  "entry_option": "rsi_only",
  "rsi_oversold": 35,
  "rsi_overbought": 65,
  "leverage": 20,
  "investment": 100,
  "tp_sl_option": "dynamic_atr",
  "atr_sl_multiplier": 1.5,
  "atr_tp_multiplier": 4.0,
  "trailing_stop_enabled": false
}
```

#### Balanced (Recommended)
```json
{
  "entry_option": "rsi_trend",
  "rsi_oversold": 30,
  "rsi_overbought": 70,
  "leverage": 10,
  "investment": 100,
  "tp_sl_option": "fixed",
  "stop_loss_percent": 2.0,
  "take_profit_percent": 4.0,
  "trailing_stop_enabled": true,
  "trailing_stop_percent": 2.0
}
```

## API Endpoints

### Run Backtest
```
POST /backtest/run
```
Execute a backtest with specified parameters.

### Validate Data Availability
```
GET /backtest/validate/data?symbol=BTC-USDT-SWAP&timeframe=15m&start_date=2024-01-01T00:00:00Z&end_date=2024-01-31T23:59:59Z
```
Check if sufficient historical data exists for the backtest period.

Response:
```json
{
  "available": true,
  "coverage": 0.98,
  "data_source": "timescaledb",
  "message": "Data coverage: 98.0%"
}
```

### Health Check
```
GET /health
```
Check service health status.

## Common Use Cases

### 1. Parameter Optimization
Test different RSI levels:
```bash
for oversold in 25 30 35; do
  for overbought in 65 70 75; do
    echo "Testing RSI($oversold, $overbought)"
    curl -X POST "http://localhost:8013/backtest/run" \
      -H "Content-Type: application/json" \
      -d "{\"symbol\": \"BTC-USDT-SWAP\", \"timeframe\": \"15m\", ...}"
  done
done
```

### 2. Comparing TP/SL Strategies
Test fixed vs dynamic:
```bash
# Fixed TP/SL
curl ... -d '{"tp_sl_option": "fixed", "stop_loss_percent": 2.0, "take_profit_percent": 4.0}'

# Dynamic ATR
curl ... -d '{"tp_sl_option": "dynamic_atr", "atr_sl_multiplier": 2.0, "atr_tp_multiplier": 3.0}'
```

### 3. Trailing Stop Analysis
Compare with and without trailing stop:
```bash
# Without trailing
curl ... -d '{"trailing_stop_enabled": false}'

# With trailing
curl ... -d '{"trailing_stop_enabled": true, "trailing_stop_percent": 2.0}'
```

## Troubleshooting

### No Data Available
**Error**: "No data available for specified period"

**Solution**:
1. Check TimescaleDB connection
2. Verify data exists: `SELECT * FROM candle_history WHERE symbol='BTC-USDT-SWAP' LIMIT 10;`
3. Use `/backtest/validate/data` endpoint to check coverage

### Low Data Coverage
**Warning**: "Low data coverage: 65.0%"

**Solution**:
- Adjust date range to period with better data
- Run data collection to fill gaps
- Minimum 90% coverage recommended

### Validation Errors
**Error**: "Leverage must be positive"

**Solution**:
- Check strategy parameters match expected types and ranges
- Review parameter validation rules in `HyperrsiStrategy.validate_params()`

### Import Errors
**Error**: "ModuleNotFoundError: No module named 'BACKTEST'"

**Solution**:
```bash
# Install project in editable mode
cd /path/to/TradingBoost-Strategy
pip install -e .
```

## Performance Tips

1. **Date Range**: Limit to reasonable periods (1-3 months) for faster execution
2. **Timeframe**: Higher timeframes (1h, 4h) process faster than lower (1m, 5m)
3. **Event Logging**: Disable for production runs (not yet configurable in API)
4. **Parallel Testing**: Run multiple backtests in parallel (API is async)

## Next Steps

- [ ] Phase 5: Implement metrics calculator for advanced analysis
- [ ] Phase 6: Add parameter optimization (grid search, walk-forward)
- [ ] Phase 7: Implement database persistence for results
- [ ] Phase 8: Add GRID strategy support
- [ ] Web UI: Create dashboard for backtest visualization

For more details, see:
- `BACKTEST_SYSTEM_DESIGN.md` - Complete system architecture
- `IMPLEMENTATION_STATUS.md` - Current implementation status
- `BACKTEST/strategies/hyperrsi_strategy.py` - Strategy source code
