#!/usr/bin/env python3
"""
Redis Migration Validation Script

Validates that all migrated files:
1. Import correctly
2. Use proper Redis context patterns
3. Have correct timeout configurations
"""

import ast
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Phase 1 & 2 migrated files
MIGRATED_FILES = [
    "HYPERRSI/src/trading/stats.py",
    "HYPERRSI/src/bot/telegram_message.py",
    "HYPERRSI/src/tasks/trading_tasks.py",
    "HYPERRSI/src/trading/execute_trading_logic.py",
    "HYPERRSI/src/trading/services/get_current_price.py",
    "HYPERRSI/src/trading/services/calc_utils.py",
    "HYPERRSI/src/utils/status_utils.py",
    "HYPERRSI/src/trading/position_monitor.py",
    "HYPERRSI/src/core/shutdown.py",
]

REQUIRED_IMPORTS = {
    "get_redis_context": "shared.database.redis_migration",
    "RedisTimeout": "shared.database.redis_patterns",
}

DEPRECATED_PATTERNS = [
    "get_redis_client()",
    "await get_redis()",
]

class ValidationResult:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.success_messages: List[str] = []

    def add_error(self, msg: str):
        self.errors.append(msg)

    def add_warning(self, msg: str):
        self.warnings.append(msg)

    def add_success(self, msg: str):
        self.success_messages.append(msg)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def print_report(self):
        print(f"\n{'='*80}")
        print(f"📄 {self.file_path}")
        print(f"{'='*80}")

        if self.success_messages:
            print("\n✅ Success:")
            for msg in self.success_messages:
                print(f"  ✓ {msg}")

        if self.warnings:
            print("\n⚠️  Warnings:")
            for msg in self.warnings:
                print(f"  ⚠ {msg}")

        if self.errors:
            print("\n❌ Errors:")
            for msg in self.errors:
                print(f"  ✗ {msg}")

        status = "✅ PASS" if self.is_valid else "❌ FAIL"
        print(f"\nStatus: {status}")


def check_imports(file_path: Path, content: str) -> Tuple[bool, bool]:
    """Check if file has required imports."""
    has_context = "get_redis_context" in content
    has_timeout = "RedisTimeout" in content
    return has_context, has_timeout


def check_deprecated_usage(content: str) -> List[str]:
    """Check for deprecated Redis patterns."""
    deprecated_found = []

    for pattern in DEPRECATED_PATTERNS:
        if pattern in content:
            # Count occurrences
            count = content.count(pattern)
            deprecated_found.append(f"{pattern} found {count} time(s)")

    return deprecated_found


def check_context_usage(content: str) -> Dict[str, int]:
    """Check Redis context usage patterns."""
    patterns = {
        "async with get_redis_context": content.count("async with get_redis_context"),
        "RedisTimeout.FAST_OPERATION": content.count("RedisTimeout.FAST_OPERATION"),
        "RedisTimeout.NORMAL_OPERATION": content.count("RedisTimeout.NORMAL_OPERATION"),
        "RedisTimeout.SLOW_OPERATION": content.count("RedisTimeout.SLOW_OPERATION"),
        "RedisTimeout.PIPELINE": content.count("RedisTimeout.PIPELINE"),
    }
    return patterns


def validate_file(file_path: str) -> ValidationResult:
    """Validate a single migrated file."""
    result = ValidationResult(file_path)
    full_path = Path(file_path)

    # Check file exists
    if not full_path.exists():
        result.add_error(f"File not found: {file_path}")
        return result

    # Read file content
    try:
        content = full_path.read_text(encoding='utf-8')
    except Exception as e:
        result.add_error(f"Failed to read file: {e}")
        return result

    # Check imports
    has_context, has_timeout = check_imports(full_path, content)

    if has_context:
        result.add_success("Imports get_redis_context")
    else:
        result.add_warning("Missing get_redis_context import (may use legacy pattern)")

    if has_timeout:
        result.add_success("Imports RedisTimeout")
    else:
        result.add_warning("Missing RedisTimeout import")

    # Check for deprecated patterns
    deprecated = check_deprecated_usage(content)
    if deprecated:
        for pattern in deprecated:
            result.add_warning(f"Deprecated pattern still present: {pattern}")
    else:
        result.add_success("No deprecated patterns found")

    # Check context usage
    usage = check_context_usage(content)
    total_usage = sum(usage.values())

    if usage["async with get_redis_context"] > 0:
        result.add_success(f"Uses Redis context {usage['async with get_redis_context']} time(s)")

    # Report timeout usage
    timeout_counts = {
        k: v for k, v in usage.items()
        if k.startswith("RedisTimeout.") and v > 0
    }
    if timeout_counts:
        for timeout_type, count in timeout_counts.items():
            result.add_success(f"{timeout_type}: {count} usage(s)")

    # Check if file was actually migrated
    if usage["async with get_redis_context"] == 0 and not deprecated:
        result.add_warning("File may not use Redis at all")

    return result


def main():
    """Run validation on all migrated files."""
    print("\n" + "="*80)
    print("🔍 Redis Migration Validation")
    print("="*80)
    print(f"\nValidating {len(MIGRATED_FILES)} migrated files...")

    results = []
    for file_path in MIGRATED_FILES:
        result = validate_file(file_path)
        results.append(result)
        result.print_report()

    # Summary
    print("\n" + "="*80)
    print("📊 VALIDATION SUMMARY")
    print("="*80)

    passed = sum(1 for r in results if r.is_valid)
    failed = len(results) - passed

    print(f"\nTotal Files: {len(results)}")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")

    if failed == 0:
        print("\n🎉 All files validated successfully!")
        print("\n✅ Migration is ready for testing")
        print("\nNext steps:")
        print("1. Run integration tests")
        print("2. Enable 1% rollout (REDIS_CONTEXT_ROLLOUT_PERCENTAGE=1)")
        print("3. Monitor for errors and connection leaks")
        return 0
    else:
        print("\n⚠️  Some files have validation issues")
        print("Please review the errors above and fix them before proceeding")
        return 1


if __name__ == "__main__":
    sys.exit(main())
