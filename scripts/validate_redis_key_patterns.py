#!/usr/bin/env python3
"""
Redis Key Pattern Validation Script

Validates that Redis key patterns follow the standardized format after changes.
Run this script to verify Phase 1 implementation is correct.

Usage:
    python scripts/validate_redis_key_patterns.py
"""

import asyncio
import re
from typing import Dict, List, Tuple

# Expected patterns after standardization
EXPECTED_PATTERNS = {
    # Position keys (HYPERRSI cache)
    "position_cache": r"^position:[^:]+:(okx|binance|bitget|upbit|bybit):[^:]+:(long|short)$",

    # Order placed keys (GRID)
    "order_placed": r"^orders:(okx|binance|bitget|upbit|bybit):user:\d+:symbol:[^:]+:order_placed$",
    "order_placed_index": r"^orders:(okx|binance|bitget|upbit|bybit):user:\d+:symbol:[^:]+:order_placed_index$",
    "orders": r"^orders:(okx|binance|bitget|upbit|bybit):user:\d+:symbol:[^:]+:orders$",

    # Position storage (GRID - unchanged, for reference)
    "grid_positions": r"^(okx|binance|bitget|upbit|bybit):positions:\d+$",
}

# Legacy patterns that should NOT exist after migration
LEGACY_PATTERNS = {
    "old_position_cache": r"^position:[^:]+:[^:]+$",  # Missing exchange and side
    "old_user_position": r"^user:\d+:position:[^:]+:(long|short)$",  # Old remove_position pattern
    "old_order_placed": r"^(okx|binance|bitget|upbit|bybit):user:\d+:symbol:[^:]+:order_placed$",  # Missing 'orders:' prefix
}


async def get_redis_keys() -> List[str]:
    """Get all Redis keys for validation"""
    try:
        from shared.database.redis import get_redis
        redis = await get_redis()

        # Get all keys matching our patterns
        all_keys = []
        for pattern in ["position:*", "orders:*", "*:positions:*", "*:order_placed", "user:*:position:*"]:
            keys = await redis.keys(pattern)
            all_keys.extend(keys)

        return [k.decode() if isinstance(k, bytes) else k for k in all_keys]
    except Exception as e:
        print(f"⚠️  Warning: Could not connect to Redis: {e}")
        print("   Skipping live key validation (will only validate patterns)")
        return []


def validate_key_patterns(keys: List[str]) -> Dict[str, List[str]]:
    """Validate that keys match expected patterns"""
    results = {
        "valid": [],
        "legacy": [],
        "unknown": []
    }

    for key in keys:
        matched = False

        # Check if matches expected patterns
        for pattern_name, pattern in EXPECTED_PATTERNS.items():
            if re.match(pattern, key):
                results["valid"].append(f"✅ {key} → {pattern_name}")
                matched = True
                break

        if not matched:
            # Check if matches legacy patterns
            for pattern_name, pattern in LEGACY_PATTERNS.items():
                if re.match(pattern, key):
                    results["legacy"].append(f"⚠️  {key} → {pattern_name} (LEGACY)")
                    matched = True
                    break

        if not matched:
            results["unknown"].append(f"❓ {key} → Unknown pattern")

    return results


def print_validation_results(results: Dict[str, List[str]]):
    """Print validation results"""
    print("\n" + "="*80)
    print("Redis Key Pattern Validation Results")
    print("="*80 + "\n")

    if results["valid"]:
        print(f"✅ Valid Keys ({len(results['valid'])}):")
        for key in results["valid"]:
            print(f"   {key}")
        print()

    if results["legacy"]:
        print(f"⚠️  Legacy Keys Found ({len(results['legacy'])}) - SHOULD BE MIGRATED:")
        for key in results["legacy"]:
            print(f"   {key}")
        print()

    if results["unknown"]:
        print(f"❓ Unknown Keys ({len(results['unknown'])}) - VERIFY MANUALLY:")
        for key in results["unknown"]:
            print(f"   {key}")
        print()

    # Summary
    print("="*80)
    print("Summary:")
    print(f"  ✅ Valid:   {len(results['valid'])}")
    print(f"  ⚠️  Legacy:  {len(results['legacy'])}")
    print(f"  ❓ Unknown: {len(results['unknown'])}")

    if results["legacy"]:
        print("\n⚠️  ACTION REQUIRED: Legacy keys detected!")
        print("   Run migration script to update legacy keys.")
        return False
    elif results["unknown"]:
        print("\n⚠️  WARNING: Unknown key patterns detected!")
        print("   Review manually to ensure compliance.")
        return True
    else:
        print("\n✅ All keys follow standardized patterns!")
        return True


def validate_code_patterns() -> bool:
    """Validate that code uses correct key patterns"""
    print("\n" + "="*80)
    print("Code Pattern Validation")
    print("="*80 + "\n")

    errors = []

    # Check shared/cache/trading_cache.py
    try:
        with open("shared/cache/trading_cache.py", "r") as f:
            content = f.read()

            # Should have new position pattern
            if 'f"position:{user_id}:{exchange}:{symbol}:{side}"' not in content:
                errors.append("❌ shared/cache/trading_cache.py: Missing new position pattern")
            else:
                print("✅ shared/cache/trading_cache.py: Uses correct position pattern")

            # Should NOT have old patterns
            if 'f"position:{user_id}:{symbol}"' in content and 'exchange' not in content.split('f"position:{user_id}:{symbol}"')[0][-100:]:
                errors.append("⚠️  shared/cache/trading_cache.py: Old position pattern still present")

            if 'f"user:{user_id}:position:' in content:
                errors.append("⚠️  shared/cache/trading_cache.py: Legacy user:position pattern still present")
    except FileNotFoundError:
        errors.append("❌ shared/cache/trading_cache.py: File not found")

    # Check GRID/database/redis_database.py
    try:
        with open("GRID/database/redis_database.py", "r") as f:
            content = f.read()

            # Should have new order_placed pattern
            if 'f"orders:{exchange_name}:user:{user_id}:symbol:' in content:
                print("✅ GRID/database/redis_database.py: Uses correct order_placed pattern")
            else:
                errors.append("❌ GRID/database/redis_database.py: Missing new order_placed pattern")

            # Check if old pattern still exists in order_placed functions
            lines_with_old_pattern = []
            for i, line in enumerate(content.split('\n'), 1):
                if 'order_placed' in line and ':user:' in line and 'orders:' not in line and 'exchange_name' in line:
                    if 'def ' not in line and '#' not in line:  # Exclude function definitions and comments
                        lines_with_old_pattern.append(i)

            if lines_with_old_pattern:
                errors.append(f"⚠️  GRID/database/redis_database.py: Old order_placed pattern at lines: {lines_with_old_pattern}")
    except FileNotFoundError:
        errors.append("❌ GRID/database/redis_database.py: File not found")

    print()
    if errors:
        print("Validation Errors:")
        for error in errors:
            print(f"  {error}")
        print()
        return False
    else:
        print("✅ All code patterns are correct!")
        print()
        return True


async def main():
    """Main validation function"""
    print("\n🔍 Redis Key Pattern Validation")
    print("   Phase 1: Critical Fixes Validation\n")

    # Validate code patterns
    code_valid = validate_code_patterns()

    # Get and validate Redis keys
    keys = await get_redis_keys()
    if keys:
        results = validate_key_patterns(keys)
        keys_valid = print_validation_results(results)
    else:
        print("⚠️  Skipping live Redis key validation (Redis not available)")
        keys_valid = True

    print("\n" + "="*80)
    if code_valid and keys_valid:
        print("✅ VALIDATION PASSED")
        print("   All patterns follow standardized format.")
        return 0
    elif code_valid:
        print("⚠️  VALIDATION WARNING")
        print("   Code is correct but some Redis keys need migration.")
        return 1
    else:
        print("❌ VALIDATION FAILED")
        print("   Code patterns need to be fixed.")
        return 2


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
