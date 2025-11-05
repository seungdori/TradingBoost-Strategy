# DCA Integration Overview

> **⚠️ 중요**: 이 문서는 2025년 1월 15일 기준으로 **모든 작업이 완료**되었습니다.
> **최신 현황**: [DCA_INTEGRATION_CURRENT_STATUS.md](./DCA_INTEGRATION_CURRENT_STATUS.md)를 참조하세요.
>
> 이 문서는 초기 계획 및 설계 자료로 보관됩니다.

## Purpose

Complete integration of existing DCA (Dollar Cost Averaging) / Pyramiding logic from live HYPERRSI trading system into the BACKTEST engine. This document provides architectural overview and integration strategy.

---

## ✅ 완료 상태 (2025-01-15)

모든 Phase (1-5)가 완료되었습니다:
- ✅ Phase 1: DCA Parameters and Configuration
- ✅ Phase 2: DCA Calculation Utilities
- ✅ Phase 3: Position Manager Enhancement
- ✅ Phase 4: Backtest Engine Integration
- ✅ Phase 5: Testing and Validation

상세 내용은 [DCA_INTEGRATION_CURRENT_STATUS.md](./DCA_INTEGRATION_CURRENT_STATUS.md)를 참조하세요.

---

## Current State Analysis

### What Works
- ✅ TimescaleDB data provider correctly fetches OHLCV + indicators
- ✅ BacktestEngine processes candles sequentially
- ✅ Initial position entry based on RSI signals
- ✅ TP/SL exit conditions
- ✅ Basic position management (open/close)
- ✅ Event logging and trade recording

### ✅ Implemented Features (Completed)
- ✅ DCA level calculation after initial entry
- ✅ Additional entry logic (pyramiding)
- ✅ Entry size scaling with multiplier
- ✅ Multi-entry position tracking
- ✅ Average entry price calculation
- ✅ DCA-specific RSI/trend conditions

### Impact (Achieved)
- Previous backtest: 3 trades in 3 months (1 per month)
- With DCA enabled: 10-30+ entries total (3-10 additional entries per initial position)
- Trades now show varying profit based on DCA count and average entry price
- Complete pyramiding profit accumulation mechanism implemented

## Source Code Locations

### Live Trading DCA Implementation
```
HYPERRSI/src/trading/utils/position_handler/pyramiding.py (1111 lines)
├── handle_pyramiding() - Main orchestrator
├── _calculate_dca_entry_size() - Position sizing with multiplier
├── _execute_long_pyramiding() - Long DCA execution
└── _execute_short_pyramiding() - Short DCA execution

HYPERRSI/src/trading/utils/trading_utils.py (lines 101-154)
├── calculate_dca_levels() - DCA price level calculation
└── check_dca_condition() - Price trigger validation
```

### Backtest Files to Modify
```
BACKTEST/strategies/hyperrsi_strategy.py
├── Add DCA parameters to strategy config
└── Validate DCA parameter ranges

BACKTEST/engine/position_manager.py
├── Add add_to_position() method
├── Track DCA count and entry history
├── Calculate average entry price
└── Update P&L for multi-entry positions

BACKTEST/engine/backtest_engine.py
├── Add DCA checking loop after initial entry
├── Calculate DCA levels from entry price
├── Check DCA conditions each candle
└── Execute additional entries via position_manager

BACKTEST/strategies/base_strategy.py (optional)
└── Add DCA parameter validation interface
```

## Architecture Components

### 1. DCA Configuration Layer
**Location**: `strategies/hyperrsi_strategy.py`

Adds parameters:
- `pyramiding_limit`: Max additional entries (default: 3)
- `entry_multiplier`: Position size scale factor (default: 0.5)
- `pyramiding_entry_type`: '퍼센트 기준' | '금액 기준' | 'ATR 기준'
- `pyramiding_value`: Distance for DCA levels (default: 3.0)
- `entry_criterion`: '평균 단가' | '최근 진입가'
- `use_check_DCA_with_price`: Enable price trigger check
- `use_rsi_with_pyramiding`: Check RSI for additional entries
- `use_trend_logic`: Check trend for additional entries

### 2. DCA Calculation Utilities
**New File**: `engine/dca_calculator.py`

Functions:
- `calculate_dca_levels()`: Compute price levels based on entry type
- `check_dca_condition()`: Validate if price reached DCA level
- `calculate_dca_entry_size()`: Compute position size with exponential scaling
- `check_rsi_condition()`: Validate RSI for additional entry
- `check_trend_condition()`: Validate trend for additional entry

### 3. Position State Management
**Location**: `engine/position_manager.py`

Enhanced Position model:
```python
@dataclass
class Position:
    symbol: str
    side: PositionSide
    entry_price: float  # Average entry price (recalculated)
    quantity: float  # Total position size (accumulated)
    leverage: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    trailing_stop: Optional[float]
    entry_time: datetime

    # DCA tracking (NEW)
    dca_count: int = 0  # Number of additional entries
    entry_history: List[Dict] = field(default_factory=list)  # All entries
    dca_levels: List[float] = field(default_factory=list)  # Remaining levels
    initial_investment: float = 0.0  # First entry investment
    total_investment: float = 0.0  # Accumulated investment
```

New method:
```python
def add_to_position(
    self,
    entry_price: float,
    quantity: float,
    investment: float,
    timestamp: datetime,
    reason: str
) -> None:
    """Add to existing position (DCA entry)"""
```

### 4. Backtest Engine Integration
**Location**: `engine/backtest_engine.py`

Enhanced main loop:
```python
for candle in candles:
    if not position_manager.current_position:
        # Generate signal and open initial position
        signal = strategy.generate_signal(candle)
        if signal.side:
            # Open position (existing code)
            ...
            # Calculate DCA levels (NEW)
            dca_levels = calculate_dca_levels(...)
            position.dca_levels = dca_levels
    else:
        position = position_manager.current_position

        # Check TP/SL (existing)
        if check_take_profit(...) or check_stop_loss(...):
            position_manager.close_position(...)
            continue

        # Check DCA conditions (NEW)
        if position.dca_count < pyramiding_limit:
            if check_dca_condition(candle.close, position.dca_levels, position.side):
                if check_rsi_condition(...) and check_trend_condition(...):
                    # Execute additional entry
                    entry_size = calculate_dca_entry_size(...)
                    filled_price, quantity = order_simulator.execute_order(...)
                    position_manager.add_to_position(...)

                    # Recalculate DCA levels
                    dca_levels = calculate_dca_levels(...)
                    position.dca_levels = dca_levels
```

## Data Flow

```
1. Initial Entry
   ├─> Open position at entry_price_1
   ├─> Set initial_investment
   ├─> Calculate DCA levels from entry_price_1
   └─> dca_count = 0

2. Each Subsequent Candle
   ├─> Check TP/SL (priority check)
   │   └─> If hit: close position, record trade
   │
   └─> If position still open and dca_count < pyramiding_limit:
       ├─> Check if price reached next DCA level
       ├─> Check RSI condition (if enabled)
       ├─> Check trend condition (if enabled)
       │
       └─> If all conditions met:
           ├─> Calculate entry size (scaled by multiplier^dca_count)
           ├─> Execute order via order_simulator
           ├─> Add to position (update average price, total quantity)
           ├─> Increment dca_count
           ├─> Recalculate DCA levels from new average price
           └─> Log event

3. Position Close
   ├─> Calculate total P&L from average_entry_price
   ├─> Record trade with all entry history
   └─> Reset position state
```

## Key Algorithms

### DCA Level Calculation
```python
if pyramiding_entry_type == "퍼센트 기준":
    # Percentage-based
    if side == "long":
        level = entry_price * (1 - pyramiding_value/100)
    else:
        level = entry_price * (1 + pyramiding_value/100)

elif pyramiding_entry_type == "금액 기준":
    # Fixed amount
    if side == "long":
        level = entry_price - pyramiding_value
    else:
        level = entry_price + pyramiding_value

else:  # "ATR 기준"
    # ATR-based
    if side == "long":
        level = entry_price - (atr_value * pyramiding_value)
    else:
        level = entry_price + (atr_value * pyramiding_value)
```

### Entry Size Scaling
```python
scale = entry_multiplier  # e.g., 0.5
new_investment = initial_investment * (scale ** dca_count)
new_contracts = initial_contracts * (scale ** dca_count)

# Example with scale=0.5:
# Entry 0 (initial): investment = 100, contracts = 10
# Entry 1 (DCA 1): investment = 50, contracts = 5
# Entry 2 (DCA 2): investment = 25, contracts = 2.5
# Entry 3 (DCA 3): investment = 12.5, contracts = 1.25
```

### Average Entry Price
```python
# After each additional entry
total_cost = sum(entry.price * entry.quantity for entry in entry_history)
total_quantity = sum(entry.quantity for entry in entry_history)
average_entry_price = total_cost / total_quantity
```

## ✅ Completed Integration Phases

### Phase 1: DCA Parameters and Configuration ✅
- ✅ Added DCA parameters to strategy config
- ✅ Updated strategy validation
- ✅ Added parameter documentation
**Completed**: 2025-01-15

### Phase 2: DCA Calculation Utilities ✅
- ✅ Created `dca_calculator.py`
- ✅ Ported calculation functions from `trading_utils.py`
- ✅ Added unit tests for calculations
**Completed**: 2025-01-15

### Phase 3: Position Manager Enhancement ✅
- ✅ Enhanced Position model with DCA fields
- ✅ Implemented `add_to_position()` method
- ✅ Updated average price and P&L calculations
**Completed**: 2025-01-15

### Phase 4: Backtest Engine Integration ✅
- ✅ Added DCA checking loop
- ✅ Integrated DCA calculations
- ✅ Execute additional entries
- ✅ Updated event logging
**Completed**: 2025-01-15

### Phase 5: Testing and Validation ✅
- ✅ Unit tests for each component
- ✅ Integration tests for full DCA flow
- ✅ Backtest validation (3-month test)
- ✅ Compared with expected behavior
**Completed**: 2025-01-15

**All phases completed on 2025-01-15**

## Success Criteria

### Functional Requirements
- ✅ Backtest generates multiple additional entries per initial position
- ✅ Entry sizes follow exponential scaling with multiplier
- ✅ DCA levels calculated correctly for all 3 types (%, fixed, ATR)
- ✅ Average entry price updated after each additional entry
- ✅ RSI and trend conditions enforced for additional entries
- ✅ Position closed only when TP/SL hit (not before DCA limit)

### Performance Metrics
- ✅ 3-month backtest shows 10-30+ total entries (vs current 3)
- ✅ Trades show varying P&L (based on DCA count)
- ✅ Positions with multiple DCA entries show higher profit potential
- ✅ Execution time remains under 5 seconds for 3-month period

### Code Quality
- ✅ All DCA logic extracted into reusable functions
- ✅ Unit test coverage ≥80% for DCA components
- ✅ Type hints for all new functions
- ✅ Documentation for all new parameters
- ✅ Event logging for all DCA activities

## Risk Mitigation

### Potential Issues
1. **Average Price Calculation Error**: Wrong P&L calculation
   - Mitigation: Unit tests with known scenarios

2. **DCA Level Drift**: Levels not recalculated after each entry
   - Mitigation: Always recalculate from current average price or last filled price

3. **Infinite Loop**: DCA condition always met
   - Mitigation: Enforce pyramiding_limit, consume DCA level after hit

4. **Order Simulator Consistency**: Slippage applied multiple times
   - Mitigation: Single slippage application per order

### Testing Strategy
1. **Unit Tests**: Test each calculation function independently
2. **Integration Tests**: Test full DCA flow with mock data
3. **Regression Tests**: Compare 3-month backtest before/after
4. **Edge Cases**: Test limit conditions (max DCA, TP during DCA, etc.)

## Next Steps

All integration phases are complete. For current implementation details, see:
- `DCA_INTEGRATION_CURRENT_STATUS.md` - Complete implementation status and usage guide
- `DCA_INTEGRATION_SUMMARY.md` - Documentation summary and key algorithms
