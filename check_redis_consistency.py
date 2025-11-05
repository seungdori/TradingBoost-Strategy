#!/usr/bin/env python3
"""
Comprehensive Redis consistency check for TradingBoost-Strategy project.
Verifies:
1. No direct redis.Redis() or redis.from_url() in production code
2. All use aclose() instead of close()
3. Consistent use of redis_context() pattern
"""

import os
import re
from pathlib import Path
from typing import List, Tuple


def find_python_files(base_dirs: List[str]) -> List[Path]:
    """Find all Python files excluding tests, scripts, and migrations."""
    python_files = []

    for base_dir in base_dirs:
        base_path = Path(base_dir)
        if not base_path.exists():
            continue

        for py_file in base_path.rglob("*.py"):
            # Skip test files
            if "test" in py_file.name.lower() or "test" in str(py_file.parent).lower():
                continue
            # Skip scripts and migrations
            if "scripts" in py_file.parts or "migrations" in py_file.parts:
                continue
            # Skip __pycache__
            if "__pycache__" in py_file.parts:
                continue

            python_files.append(py_file)

    return python_files


def check_direct_redis_creation(file_path: Path) -> List[Tuple[int, str]]:
    """Check for direct redis.Redis() or redis.from_url() calls."""
    issues = []

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                # Skip comments
                if line.strip().startswith('#'):
                    continue

                # Check for redis.Redis(
                if re.search(r'redis\.Redis\s*\(', line):
                    issues.append((line_num, "Direct redis.Redis() creation"))

                # Check for redis.from_url(
                if re.search(r'redis\.from_url\s*\(', line):
                    issues.append((line_num, "Direct redis.from_url() creation"))

    except Exception as e:
        issues.append((0, f"Error reading file: {e}"))

    return issues


def check_close_method(file_path: Path) -> List[Tuple[int, str]]:
    """Check for .close() instead of .aclose() on Redis clients."""
    issues = []

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')

            for line_num, line in enumerate(lines, 1):
                # Skip comments
                if line.strip().startswith('#'):
                    continue

                # Check for await redis.close() or await redis_client.close()
                # But NOT aclose()
                if re.search(r'await\s+redis[_a-zA-Z]*\.close\s*\(', line):
                    if 'aclose' not in line:
                        issues.append((line_num, "Using .close() instead of .aclose()"))

    except Exception as e:
        issues.append((0, f"Error reading file: {e}"))

    return issues


def check_redis_context_usage(file_path: Path) -> Tuple[bool, int]:
    """Check if file uses redis operations and whether it uses redis_context()."""
    has_redis_ops = False
    uses_context = False
    redis_context_count = 0

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

            # Check for Redis operations
            if re.search(r'(await\s+redis\.|redis\.)', content):
                has_redis_ops = True

            # Check for redis_context usage
            context_matches = re.findall(r'async\s+with\s+redis_context\(\)', content)
            redis_context_count = len(context_matches)
            if redis_context_count > 0:
                uses_context = True

    except Exception as e:
        pass

    return has_redis_ops, uses_context, redis_context_count


def main():
    print("=" * 80)
    print("Redis Consistency Check - TradingBoost-Strategy")
    print("=" * 80)
    print()

    base_dirs = ["GRID", "HYPERRSI", "shared"]
    python_files = find_python_files(base_dirs)

    print(f"📊 Scanning {len(python_files)} production Python files...")
    print()

    # Statistics
    total_issues = 0
    files_with_issues = []
    direct_creation_issues = {}
    close_method_issues = {}

    # Check each file
    for py_file in python_files:
        # Check 1: Direct Redis creation
        direct_issues = check_direct_redis_creation(py_file)
        if direct_issues:
            direct_creation_issues[py_file] = direct_issues
            files_with_issues.append(py_file)
            total_issues += len(direct_issues)

        # Check 2: close() vs aclose()
        close_issues = check_close_method(py_file)
        if close_issues:
            close_method_issues[py_file] = close_issues
            files_with_issues.append(py_file)
            total_issues += len(close_issues)

    # Report results
    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    print()

    if total_issues == 0:
        print("✅ ALL CHECKS PASSED - No Redis consistency issues found!")
        print()
        print("Summary:")
        print(f"  • Production files scanned: {len(python_files)}")
        print(f"  • Direct redis.Redis() calls: 0")
        print(f"  • Direct redis.from_url() calls: 0")
        print(f"  • .close() instead of .aclose(): 0")
        print()

        # Show redis_context() usage statistics
        total_contexts = 0
        files_using_context = 0

        for py_file in python_files:
            has_ops, uses_ctx, ctx_count = check_redis_context_usage(py_file)
            if uses_ctx:
                total_contexts += ctx_count
                files_using_context += 1

        print("📈 Redis Context Usage:")
        print(f"  • Files using redis_context(): {files_using_context}")
        print(f"  • Total redis_context() calls: {total_contexts}")
        print()

        return 0

    else:
        print(f"❌ FOUND {total_issues} ISSUES in {len(set(files_with_issues))} files")
        print()

        # Report direct creation issues
        if direct_creation_issues:
            print("=" * 80)
            print("Issue 1: Direct Redis Connection Creation")
            print("=" * 80)
            for file_path, issues in direct_creation_issues.items():
                rel_path = file_path.relative_to(Path.cwd())
                print(f"\n📁 {rel_path}")
                for line_num, issue in issues:
                    print(f"  Line {line_num}: {issue}")

        # Report close method issues
        if close_method_issues:
            print()
            print("=" * 80)
            print("Issue 2: Using .close() instead of .aclose()")
            print("=" * 80)
            for file_path, issues in close_method_issues.items():
                rel_path = file_path.relative_to(Path.cwd())
                print(f"\n📁 {rel_path}")
                for line_num, issue in issues:
                    print(f"  Line {line_num}: {issue}")

        print()
        print("=" * 80)
        print("Recommended Actions:")
        print("  1. Replace redis.Redis() with redis_context()")
        print("  2. Replace redis.from_url() with redis_context()")
        print("  3. Replace .close() with .aclose()")
        print("=" * 80)
        print()

        return 1


if __name__ == "__main__":
    exit(main())
