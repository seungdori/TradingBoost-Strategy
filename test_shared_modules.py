#!/usr/bin/env python3
"""
Test script for all newly migrated shared modules.
Tests imports and basic functionality of phase 2 migration.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

def test_time_helpers():
    """Test time helper functions from shared.utils"""
    print("\n=== Testing Time Helpers ===")

    from shared.utils import (
        parse_timeframe,
        calculate_current_timeframe_start,
        timeframe_to_seconds,
        timeframe_to_timedelta
    )
    from datetime import timedelta

    # Test parse_timeframe
    unit, value = parse_timeframe('15m')
    assert unit == 'minutes' and value == 15, "Failed: parse_timeframe('15m')"
    print("✅ parse_timeframe('15m') -> ('minutes', 15)")

    unit, value = parse_timeframe('1h')
    assert unit == 'hours' and value == 1, "Failed: parse_timeframe('1h')"
    print("✅ parse_timeframe('1h') -> ('hours', 1)")

    # Test timeframe_to_seconds
    seconds = timeframe_to_seconds('15m')
    assert seconds == 900, "Failed: timeframe_to_seconds('15m')"
    print("✅ timeframe_to_seconds('15m') -> 900")

    seconds = timeframe_to_seconds('1h')
    assert seconds == 3600, "Failed: timeframe_to_seconds('1h')"
    print("✅ timeframe_to_seconds('1h') -> 3600")

    # Test timeframe_to_timedelta
    td = timeframe_to_timedelta('15m')
    assert td == timedelta(minutes=15), "Failed: timeframe_to_timedelta('15m')"
    print("✅ timeframe_to_timedelta('15m') -> timedelta(minutes=15)")

    # Test calculate_current_timeframe_start
    start = calculate_current_timeframe_start('15m')
    print(f"✅ calculate_current_timeframe_start('15m') -> {start}")

    print("✅ All time helper tests passed!")


def test_type_converters():
    """Test type converter functions from shared.utils"""
    print("\n=== Testing Type Converters ===")

    from shared.utils import (
        safe_float,
        safe_int,
        parse_bool,
        convert_bool_to_string,
        convert_bool_to_int
    )

    # Test safe_float
    assert safe_float("3.14") == 3.14, "Failed: safe_float('3.14')"
    print("✅ safe_float('3.14') -> 3.14")

    assert safe_float(None, default=1.0) == 1.0, "Failed: safe_float(None, default=1.0)"
    print("✅ safe_float(None, default=1.0) -> 1.0")

    # Test safe_int
    assert safe_int("42") == 42, "Failed: safe_int('42')"
    print("✅ safe_int('42') -> 42")

    assert safe_int("3.14") == 3, "Failed: safe_int('3.14')"
    print("✅ safe_int('3.14') -> 3")

    # Test parse_bool
    assert parse_bool("true") == True, "Failed: parse_bool('true')"
    print("✅ parse_bool('true') -> True")

    assert parse_bool("false") == False, "Failed: parse_bool('false')"
    print("✅ parse_bool('false') -> False")

    assert parse_bool(1) == True, "Failed: parse_bool(1)"
    print("✅ parse_bool(1) -> True")

    # Test convert_bool_to_string
    data = {"active": True, "value": 10}
    converted = convert_bool_to_string(data)
    assert converted == {"active": "true", "value": 10}, "Failed: convert_bool_to_string"
    print("✅ convert_bool_to_string({'active': True, 'value': 10}) -> {'active': 'true', 'value': 10}")

    # Test convert_bool_to_int
    data = {"enabled": False, "count": 5}
    converted = convert_bool_to_int(data)
    assert converted == {"enabled": 0, "count": 5}, "Failed: convert_bool_to_int"
    print("✅ convert_bool_to_int({'enabled': False, 'count': 5}) -> {'enabled': 0, 'count': 5}")

    print("✅ All type converter tests passed!")


def test_async_helpers():
    """Test async helper functions from shared.utils"""
    print("\n=== Testing Async Helpers ===")

    from shared.utils import ensure_async_loop, get_or_create_event_loop
    import asyncio

    # Test ensure_async_loop
    loop = ensure_async_loop()
    assert isinstance(loop, asyncio.AbstractEventLoop), "Failed: ensure_async_loop()"
    print("✅ ensure_async_loop() -> asyncio.AbstractEventLoop")

    # Test get_or_create_event_loop (alias)
    loop2 = get_or_create_event_loop()
    assert loop == loop2, "Failed: get_or_create_event_loop() should return same loop"
    print("✅ get_or_create_event_loop() -> same loop as ensure_async_loop()")

    print("✅ All async helper tests passed!")


def test_trading_helpers():
    """Test trading helper functions from shared.utils"""
    print("\n=== Testing Trading Helpers ===")

    from shared.utils import (
        round_to_qty,
        get_minimum_qty,
        parse_order_info,
        is_tp_order,
        is_sl_order,
        get_contract_size,
        get_tick_size_from_redis,
        round_to_tick_size
    )

    # Just verify imports work - many functions require Redis/async/complex inputs
    print("✅ round_to_qty imported successfully")
    print("✅ get_minimum_qty imported successfully")
    print("✅ get_contract_size imported successfully")
    print("✅ get_tick_size_from_redis imported successfully")
    print("✅ round_to_tick_size imported successfully")
    print("✅ parse_order_info imported successfully")

    # Test simple utility functions
    # Test is_tp_order (case-sensitive, expects lowercase)
    assert is_tp_order("tp1") == True, "Failed: is_tp_order('tp1')"
    print("✅ is_tp_order('tp1') -> True")

    assert is_tp_order("entry") == False, "Failed: is_tp_order('entry')"
    print("✅ is_tp_order('entry') -> False")

    # Test is_sl_order
    assert is_sl_order("sl") == True, "Failed: is_sl_order('sl')"
    print("✅ is_sl_order('sl') -> True")

    assert is_sl_order("tp1") == False, "Failed: is_sl_order('tp1')"
    print("✅ is_sl_order('tp1') -> False")

    print("✅ All trading helper tests passed!")


def test_imports_from_hyperrsi():
    """Test that imports work from HYPERRSI perspective"""
    print("\n=== Testing HYPERRSI Imports ===")

    # Simulate HYPERRSI imports
    from shared.utils import (
        safe_float,
        round_to_qty,
        convert_symbol_to_okx_instrument,
        get_tick_size_from_redis,
        get_minimum_qty,
        get_contract_size,
        round_to_tick_size,
        convert_bool_to_string,
        convert_bool_to_int,
        ensure_async_loop
    )

    print("✅ All HYPERRSI imports successful")


def test_imports_from_grid():
    """Test that imports work from GRID perspective"""
    print("\n=== Testing GRID Imports ===")

    # Simulate GRID imports
    from shared.utils import (
        parse_timeframe,
        calculate_current_timeframe_start,
        calculate_next_timeframe_start,
        calculate_sleep_duration,
        timeframe_to_seconds,
        timeframe_to_timedelta,
        get_timeframe_boundaries
    )

    print("✅ All GRID imports successful")


def main():
    """Run all tests"""
    print("=" * 60)
    print("Testing Phase 2 Shared Module Migration")
    print("=" * 60)

    try:
        test_time_helpers()
        test_type_converters()
        test_async_helpers()
        test_trading_helpers()
        test_imports_from_hyperrsi()
        test_imports_from_grid()

        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED!")
        print("=" * 60)
        return 0

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
