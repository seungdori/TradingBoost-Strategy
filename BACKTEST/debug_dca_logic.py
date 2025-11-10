"""
Debug script to test DCA logic directly.
"""
from engine.dca_calculator import (
    calculate_dca_levels,
    check_dca_condition,
    check_rsi_condition_for_dca,
    check_trend_condition_for_dca
)

# Simulate Trade 1 scenario
entry_price = 110208.35
current_price = 110876.00  # First candle where it crossed DCA level
side = "short"

settings = {
    'pyramiding_entry_type': 'atr',
    'pyramiding_value': 3,
    'pyramiding_limit': 8,
    'entry_criterion': '평균 단가',
    'use_check_DCA_with_price': True,
    'use_rsi_with_pyramiding': False,  # DISABLED
    'use_trend_logic': False,  # DISABLED
}

# Calculate DCA levels
atr_value = 664.04  # Example ATR value
dca_levels = calculate_dca_levels(
    entry_price=entry_price,
    last_filled_price=entry_price,
    settings=settings,
    side=side,
    atr_value=atr_value,
    current_price=current_price
)

print("=== DCA Logic Test ===\n")
print(f"Entry price: {entry_price:.2f}")
print(f"Current price: {current_price:.2f} (+{((current_price/entry_price)-1)*100:.2f}%)")
print(f"Side: {side}")
print(f"ATR: {atr_value:.2f}")
print(f"\nDCA Levels: {[f'{level:.2f}' for level in dca_levels]}")
print(f"DCA Level 1: {dca_levels[0]:.2f} (+{((dca_levels[0]/entry_price)-1)*100:.2f}%)")

# Test price condition
price_passed = check_dca_condition(
    current_price=current_price,
    dca_levels=dca_levels,
    side=side,
    use_check_DCA_with_price=True
)

print(f"\n1. Price condition check:")
print(f"   Current: {current_price:.2f} >= DCA Level: {dca_levels[0]:.2f}?")
print(f"   Result: {'✅ PASSED' if price_passed else '❌ FAILED'}")

# Test RSI condition
rsi = 70.5
rsi_passed = check_rsi_condition_for_dca(
    rsi=rsi,
    side=side,
    rsi_oversold=30,
    rsi_overbought=70,
    use_rsi_with_pyramiding=False  # DISABLED
)

print(f"\n2. RSI condition check:")
print(f"   RSI: {rsi:.2f}, use_rsi_with_pyramiding: False")
print(f"   Result: {'✅ PASSED' if rsi_passed else '❌ FAILED'}")

# Test trend condition
ema = 109500.0
sma = 109000.0
trend_passed = check_trend_condition_for_dca(
    ema=ema,
    sma=sma,
    side=side,
    use_trend_logic=False  # DISABLED
)

print(f"\n3. Trend condition check:")
print(f"   EMA: {ema:.2f}, SMA: {sma:.2f}, use_trend_logic: False")
print(f"   Result: {'✅ PASSED' if trend_passed else '❌ FAILED'}")

print(f"\n=== Final Result ===")
all_passed = price_passed and rsi_passed and trend_passed
print(f"DCA should trigger: {'✅ YES' if all_passed else '❌ NO'}")

if not all_passed:
    print("\nFailed checks:")
    if not price_passed:
        print(f"  - Price: {current_price:.2f} not >= {dca_levels[0]:.2f}")
    if not rsi_passed:
        print(f"  - RSI condition failed")
    if not trend_passed:
        print(f"  - Trend condition failed")
