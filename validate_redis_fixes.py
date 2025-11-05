#!/usr/bin/env python3
"""
Validation script for Redis connection fixes.
Checks that pooled connection .close() calls have been removed and Celery uses dedicated DBs.
"""

import re
from pathlib import Path

def check_redis_close_calls(grid_dir: Path) -> tuple[bool, list[str]]:
    """Check for remaining await redis.close() calls in GRID directory."""
    found_issues = []

    for py_file in grid_dir.rglob('*.py'):
        try:
            with open(py_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # Find all await redis.close() that are not commented out
            pattern = r'^\s*await redis\.close\(\)'
            matches = re.findall(pattern, content, re.MULTILINE)

            if matches:
                found_issues.append(str(py_file.relative_to(grid_dir.parent)))

        except Exception as e:
            print(f"Warning: Could not read {py_file}: {e}")

    success = len(found_issues) == 0
    return success, found_issues

def check_celery_db_config(project_root: Path) -> tuple[bool, str]:
    """Check that GRID Celery uses dedicated databases."""
    celery_file = project_root / 'GRID' / 'jobs' / 'celery_app.py'

    try:
        with open(celery_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check for imports
        has_imports = 'REDIS_DB_BROKER' in content and 'REDIS_DB_BACKEND' in content

        # Check for usage in broker URL
        has_broker = re.search(r'broker=.*REDIS_DB_BROKER', content)
        has_backend = re.search(r'backend=.*REDIS_DB_BACKEND', content)

        # Check password-protected URLs
        has_broker_pw = re.search(r'broker_url.*REDIS_DB_BROKER', content)
        has_backend_pw = re.search(r'result_backend.*REDIS_DB_BACKEND', content)

        if has_imports and has_broker and has_backend and has_broker_pw and has_backend_pw:
            return True, "✓ Celery uses dedicated databases (DB 1: broker, DB 2: backend)"
        else:
            details = []
            if not has_imports:
                details.append("Missing imports for REDIS_DB_BROKER/REDIS_DB_BACKEND")
            if not has_broker:
                details.append("Broker URL not using REDIS_DB_BROKER")
            if not has_backend:
                details.append("Backend URL not using REDIS_DB_BACKEND")
            return False, "✗ Issues found:\n  - " + "\n  - ".join(details)

    except Exception as e:
        return False, f"✗ Error reading celery_app.py: {e}"

def check_redis_imports(grid_dir: Path) -> tuple[bool, dict]:
    """Check Redis import patterns in GRID directory."""
    stats = {
        'uses_shared_pool': 0,
        'direct_connections': 0,
        'files_with_issues': []
    }

    # Patterns to detect
    shared_pool_pattern = r'from shared\.database\.redis import get_redis'
    direct_conn_pattern = r'redis\.Redis\('

    for py_file in grid_dir.rglob('*.py'):
        try:
            with open(py_file, 'r', encoding='utf-8') as f:
                content = f.read()

            uses_shared = bool(re.search(shared_pool_pattern, content))
            has_direct = bool(re.search(direct_conn_pattern, content))

            if uses_shared:
                stats['uses_shared_pool'] += 1

            if has_direct:
                stats['direct_connections'] += 1
                stats['files_with_issues'].append(str(py_file.relative_to(grid_dir.parent)))

        except Exception:
            pass

    success = stats['direct_connections'] == 0
    return success, stats

def main():
    project_root = Path('/Users/seunghyun/TradingBoost-Strategy')
    grid_dir = project_root / 'GRID'

    print("=" * 70)
    print("Redis Connection Fixes Validation")
    print("=" * 70)
    print()

    # Check 1: No more await redis.close() calls
    print("[1/3] Checking for remaining redis.close() calls...")
    success1, issues = check_redis_close_calls(grid_dir)

    if success1:
        print("  ✓ No problematic redis.close() calls found")
    else:
        print(f"  ✗ Found redis.close() calls in {len(issues)} files:")
        for issue in issues:
            print(f"    - {issue}")

    print()

    # Check 2: Celery DB configuration
    print("[2/3] Checking GRID Celery database configuration...")
    success2, message = check_celery_db_config(project_root)
    print(f"  {message}")
    print()

    # Check 3: Redis import patterns
    print("[3/3] Checking Redis import patterns...")
    success3, stats = check_redis_imports(grid_dir)

    print(f"  Files using shared pool: {stats['uses_shared_pool']}")
    print(f"  Files with direct connections: {stats['direct_connections']}")

    if not success3:
        print(f"  ✗ Files still using direct redis.Redis():")
        for file in stats['files_with_issues'][:10]:  # Show first 10
            print(f"    - {file}")
        if len(stats['files_with_issues']) > 10:
            print(f"    ... and {len(stats['files_with_issues']) - 10} more")
    else:
        print("  ✓ No direct Redis connections found")

    print()
    print("=" * 70)
    print("Summary:")
    print("=" * 70)

    all_critical_passed = success1 and success2

    print(f"  [{'✓' if success1 else '✗'}] Connection leak fix (redis.close() removal)")
    print(f"  [{'✓' if success2 else '✗'}] Celery DB configuration")
    print(f"  [{'⚠' if not success3 else '✓'}] Direct connections (will be fixed in Task 2)")

    print()
    if all_critical_passed:
        print("✓ All critical fixes validated successfully!")
        print()
        print("Next steps:")
        print("  1. Task 2: Migrate remaining direct connections to shared pool")
        print("  2. Test the application")
        print("  3. Monitor Redis connection pool metrics")
    else:
        print("✗ Some critical issues remain. Please review above.")

    return all_critical_passed

if __name__ == '__main__':
    import sys
    success = main()
    sys.exit(0 if success else 1)
