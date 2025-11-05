# Partial Exits (분할매도) Integration

**Date**: 2025-11-03
**Status**: ✅ Complete (8/8 tests passing)

## Overview

Partial exits (분할매도) functionality has been successfully integrated into the BACKTEST system, allowing positions to be closed in multiple steps at different take-profit levels (TP1, TP2, TP3).

This feature mirrors the functionality available in HYPERRSI live trading and provides more sophisticated exit strategies for backtesting.

## Features

### 3-Level Take Profit System

- **TP1**: First take-profit level (e.g., 30% of position)
- **TP2**: Second take-profit level (e.g., 30% of position)
- **TP3**: Third take-profit level (e.g., 40% of position)

Each level has:
- Independent enable/disable flag
- Configurable price target
- Configurable exit ratio (0-1)

### Key Characteristics

1. **Original Quantity Based**: Exit ratios are calculated based on the ORIGINAL position quantity, not remaining quantity
   - Example: 1.0 BTC position with 30%/30%/40% ratios
   - TP1: Close 0.3 BTC (30% of original 1.0)
   - TP2: Close 0.3 BTC (30% of original 1.0)
   - TP3: Close 0.4 BTC (40% of original 1.0)

2. **Sequential Execution**: TP levels are triggered in order (TP1 → TP2 → TP3)

3. **Independent Trade Records**: Each partial exit creates a separate Trade object with:
   - `is_partial_exit=True`
   - `tp_level` (1, 2, or 3)
   - `exit_ratio` (proportion closed)
   - `remaining_quantity` (amount left after this exit)

4. **DCA Compatible**: Works seamlessly with DCA entries by using average entry price

5. **Backward Compatible**: When partial exits are disabled, the original single take-profit behavior is maintained

## Implementation Details

### 1. Position Model Extensions

**File**: `BACKTEST/models/position.py`

Added 13 new fields to support partial exits:

```python
# Enable flags
use_tp1: bool = False
use_tp2: bool = False
use_tp3: bool = False

# Price targets
tp1_price: Optional[float] = None
tp2_price: Optional[float] = None
tp3_price: Optional[float] = None

# Exit ratios (0-1)
tp1_ratio: float = 0.0
tp2_ratio: float = 0.0
tp3_ratio: float = 0.0

# Fill status
tp1_filled: bool = False
tp2_filled: bool = False
tp3_filled: bool = False

# Quantity tracking
remaining_quantity: Optional[float] = None
```

**New Methods**:
- `should_exit_partial(current_price)` → (should_exit, reason, tp_level)
- `get_current_quantity()` → current position size
- `all_tp_levels_filled()` → check if all enabled TPs filled

### 2. Trade Model Extensions

**File**: `BACKTEST/models/trade.py`

Added new exit reasons and partial exit metadata:

```python
class ExitReason(str, Enum):
    TP1 = "tp1"
    TP2 = "tp2"
    TP3 = "tp3"
    # ... existing reasons ...

# Partial exit metadata fields
is_partial_exit: bool = False
tp_level: Optional[int] = None  # 1, 2, or 3
exit_ratio: Optional[float] = None  # 0-1
remaining_quantity: Optional[float] = None  # >= 0
```

### 3. PositionManager Enhancement

**File**: `BACKTEST/engine/position_manager.py`

New method `partial_close_position()`:

```python
def partial_close_position(
    self,
    exit_price: float,
    timestamp: datetime,
    tp_level: int,
    exit_ratio: float
) -> Optional[Trade]:
    """
    Partially close position at a specific TP level.

    - Calculates close quantity based on ORIGINAL total quantity
    - Adjusts for remaining quantity to prevent over-closing
    - Creates Trade record with partial exit metadata
    - Updates position state (remaining_quantity, tp_filled flags)
    - Clears position when all quantity is closed
    """
```

**Logic Flow**:
1. Get average entry price (for DCA positions)
2. Calculate original quantity and current remaining quantity
3. Calculate close quantity: `original_qty * exit_ratio`
4. Ensure close quantity doesn't exceed remaining quantity
5. Calculate fees and P&L for this partial exit
6. Create Trade record with partial exit metadata
7. Update position: mark TP as filled, reduce remaining_quantity
8. Clear position if remaining_quantity < 1e-8

### 4. Strategy Integration

**File**: `BACKTEST/strategies/hyperrsi_strategy.py`

Added configuration parameters and TP calculation:

```python
# In __init__:
self.use_tp1 = bool(params.get("use_tp1", False))
self.use_tp2 = bool(params.get("use_tp2", False))
self.use_tp3 = bool(params.get("use_tp3", False))
self.tp1_ratio = float(params.get("tp1_ratio", 30)) / 100  # Convert to 0-1
self.tp2_ratio = float(params.get("tp2_ratio", 30)) / 100
self.tp3_ratio = float(params.get("tp3_ratio", 40)) / 100
self.tp1_value = float(params.get("tp1_value", 2.0))  # Profit target %
self.tp2_value = float(params.get("tp2_value", 3.0))
self.tp3_value = float(params.get("tp3_value", 4.0))

def calculate_tp_levels(
    self,
    side: TradeSide,
    entry_price: float
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Calculate TP1, TP2, TP3 prices based on entry price and side."""
    # For LONG: entry_price * (1 + tp_value/100)
    # For SHORT: entry_price * (1 - tp_value/100)
    return tp1, tp2, tp3
```

### 5. BacktestEngine Integration

**File**: `BACKTEST/engine/backtest_engine.py`

Two key modifications:

**A. Position Opening** (lines 325-348):
```python
# After opening position, calculate and set TP levels
if hasattr(strategy_executor, 'calculate_tp_levels'):
    tp1, tp2, tp3 = strategy_executor.calculate_tp_levels(
        signal.side,
        filled_price
    )

    # Set TP configuration on position
    position.use_tp1 = strategy_executor.use_tp1
    position.use_tp2 = strategy_executor.use_tp2
    position.use_tp3 = strategy_executor.use_tp3
    position.tp1_price = tp1
    position.tp2_price = tp2
    position.tp3_price = tp3
    position.tp1_ratio = strategy_executor.tp1_ratio
    position.tp2_ratio = strategy_executor.tp2_ratio
    position.tp3_ratio = strategy_executor.tp3_ratio
```

**B. Exit Checking** (lines 391-475):
```python
async def _check_exit_conditions(self, candle: Candle) -> None:
    """Check exit conditions including partial exits."""

    # 1. Check partial exits first (TP1/TP2/TP3)
    should_exit_partial, exit_reason, tp_level = position.should_exit_partial(candle.close)

    if should_exit_partial and tp_level:
        # Get TP price and ratio for this level
        tp_price = getattr(position, f'tp{tp_level}_price')
        exit_ratio = getattr(position, f'tp{tp_level}_ratio')

        # Use order simulator to check if TP hit
        hit, filled_price = self.order_simulator.check_take_profit_hit(
            candle, tp_price, position.side
        )

        if hit and filled_price:
            # Execute partial close
            trade = self.position_manager.partial_close_position(
                exit_price=filled_price,
                timestamp=candle.timestamp,
                tp_level=tp_level,
                exit_ratio=exit_ratio
            )

            # Update balance and log
            if trade:
                self.balance_tracker.update_balance(trade.pnl, trade.total_fees)
                # ... logging ...

            # Return if position fully closed
            if not self.position_manager.has_position():
                return

    # 2. Check full take profit (backward compatibility)
    has_partial_exits = position.use_tp1 or position.use_tp2 or position.use_tp3
    if not has_partial_exits and position.take_profit_price:
        # ... existing full TP logic ...

    # 3. Check stop loss (unchanged)
    # 4. Check trailing stop (unchanged)
```

## Configuration Example

```python
strategy_params = {
    # Partial exits configuration
    "use_tp1": True,
    "use_tp2": True,
    "use_tp3": True,
    "tp1_value": 2.0,    # TP1 at +2% profit
    "tp2_value": 3.0,    # TP2 at +3% profit
    "tp3_value": 4.0,    # TP3 at +4% profit
    "tp1_ratio": 30,     # Close 30% at TP1
    "tp2_ratio": 30,     # Close 30% at TP2
    "tp3_ratio": 40,     # Close 40% at TP3

    # Other strategy parameters...
}
```

### Example Scenario: LONG Position

**Entry**: 1.0 BTC @ $100,000 with 10x leverage

**Partial Exit Configuration**:
- TP1: $102,000 (+2%), close 30%
- TP2: $103,000 (+3%), close 30%
- TP3: $104,000 (+4%), close 40%

**Execution Flow**:

1. **TP1 Hit @ $102,000**:
   - Close: 0.3 BTC (30% of original 1.0)
   - Remaining: 0.7 BTC
   - P&L: +$2,000 * 0.3 * 10x = +$6,000 (minus fees)
   - Trade record created with `is_partial_exit=True, tp_level=1`

2. **TP2 Hit @ $103,000**:
   - Close: 0.3 BTC (30% of original 1.0)
   - Remaining: 0.4 BTC
   - P&L: +$3,000 * 0.3 * 10x = +$9,000 (minus fees)
   - Trade record created with `is_partial_exit=True, tp_level=2`

3. **TP3 Hit @ $104,000**:
   - Close: 0.4 BTC (remaining 40%)
   - Remaining: 0.0 BTC
   - P&L: +$4,000 * 0.4 * 10x = +$16,000 (minus fees)
   - Trade record created with `is_partial_exit=True, tp_level=3`
   - Position cleared from PositionManager

**Total P&L**: +$31,000 (minus total fees)

## Testing

### Test Suite

**File**: `BACKTEST/tests/test_partial_exits.py`

**8 comprehensive test cases** covering:

1. ✅ `test_position_partial_exit_fields` - Position model field validation
2. ✅ `test_position_should_exit_partial_long` - TP triggering logic for LONG
3. ✅ `test_position_should_exit_partial_short` - TP triggering logic for SHORT
4. ✅ `test_position_manager_partial_close` - Full workflow (TP1→TP2→TP3)
5. ✅ `test_strategy_calculate_tp_levels` - Strategy TP calculation
6. ✅ `test_strategy_partial_exit_disabled` - Disabled partial exits behavior
7. ✅ `test_position_all_tp_levels_filled` - Fill status checking
8. ✅ `test_position_get_current_quantity` - Quantity tracking

**Run Tests**:
```bash
cd /Users/seunghyun/TradingBoost-Strategy
pytest BACKTEST/tests/test_partial_exits.py -v
```

**Test Results**: 8 passed, 0 failed ✅

## Files Modified

1. **Models**:
   - `BACKTEST/models/position.py` - Added 13 partial exit fields and 3 methods
   - `BACKTEST/models/trade.py` - Added 4 partial exit fields and new ExitReasons

2. **Engine**:
   - `BACKTEST/engine/position_manager.py` - Added 133-line `partial_close_position()` method
   - `BACKTEST/engine/backtest_engine.py` - Modified position opening and exit checking logic

3. **Strategy**:
   - `BACKTEST/strategies/hyperrsi_strategy.py` - Added TP configuration and `calculate_tp_levels()` method

4. **Tests**:
   - `BACKTEST/tests/test_partial_exits.py` - New 300+ line test file with 8 test cases

## Validation & Fixes

### Issues Resolved During Testing

1. **Floating Point Precision** (test_position_manager_partial_close):
   - **Issue**: 0.7 - 0.3 = 0.39999999999999997 (not 0.4)
   - **Fix**: Used `pytest.approx()` for float comparisons in tests

2. **Pydantic Validation Error** (remaining_quantity):
   - **Issue**: Trade model required `remaining_quantity > 0`, but final partial exit has remaining=0
   - **Fix**: Changed validation from `gt=0` to `ge=0` in Trade model

## Usage in Backtest

```python
from BACKTEST.engine import BacktestEngine
from BACKTEST.strategies.hyperrsi_strategy import HyperrsiStrategy

# Create strategy with partial exits enabled
strategy_params = {
    "use_tp1": True,
    "use_tp2": True,
    "use_tp3": True,
    "tp1_value": 2.0,
    "tp2_value": 3.0,
    "tp3_value": 4.0,
    "tp1_ratio": 30,
    "tp2_ratio": 30,
    "tp3_ratio": 40,
}

strategy = HyperrsiStrategy(params=strategy_params)

# Run backtest
engine = BacktestEngine(strategy=strategy, ...)
result = await engine.run_backtest(...)

# Analyze partial exit trades
for trade in result.trades:
    if trade.is_partial_exit:
        print(f"Partial exit TP{trade.tp_level}: "
              f"{trade.exit_ratio*100}% closed, "
              f"{trade.remaining_quantity} remaining, "
              f"P&L: {trade.pnl:.2f}")
```

## Backward Compatibility

The implementation maintains full backward compatibility:

1. **Disabled Partial Exits**: When `use_tp1/tp2/tp3` are all False, the original single `take_profit_price` behavior is used

2. **Existing Tests**: All existing entry option and DCA tests continue to pass (14/14)

3. **API Compatibility**: Position and Trade models remain compatible with existing code through Optional fields with default values

## Performance Considerations

- **Memory**: Each partial exit creates a separate Trade object, increasing memory usage proportionally
- **Processing**: Minimal overhead - only checks partial exits when position exists
- **Logging**: Additional log entries for each partial exit (can be controlled via log level)

## Future Enhancements

Potential improvements for future versions:

1. **Dynamic TP Adjustment**: Allow TP levels to be adjusted based on market conditions during backtest
2. **Partial Exit Analysis**: Add specific metrics for partial exit performance in results
3. **Visualization**: Chart showing partial exit execution on price chart
4. **More TP Levels**: Support for TP4, TP5, etc. for more granular exits
5. **Percentage-Based Remaining**: Alternative mode where ratios are based on remaining quantity instead of original

## Related Features

- **DCA Integration**: Partial exits work with DCA entries using average entry price
- **Entry Options**: Compatible with all entry types (돌파, 변곡, 변곡돌파, 초과)
- **Trailing Stop**: Can be used alongside partial exits for remaining position
- **Stop Loss**: Global stop loss still applies to entire remaining position

## Conclusion

The partial exits integration provides a sophisticated exit strategy that:
- ✅ Works seamlessly with existing DCA functionality
- ✅ Maintains backward compatibility
- ✅ Passes comprehensive test suite (8/8)
- ✅ Provides detailed tracking through independent Trade records
- ✅ Supports flexible configuration via strategy parameters

This feature brings BACKTEST closer to production trading capabilities and enables more realistic strategy testing.
