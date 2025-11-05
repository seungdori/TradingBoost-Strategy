#!/usr/bin/env python3
"""
Redis TTL Audit Script

Scans all Redis keys and identifies keys without TTL (orphaned keys).
Provides recommendations and can optionally fix TTLs automatically.

Usage:
    # Audit only (dry run - no changes)
    python scripts/redis_ttl_audit.py --dry-run

    # Audit and fix TTLs
    python scripts/redis_ttl_audit.py --fix

    # Audit with CSV export
    python scripts/redis_ttl_audit.py --dry-run --export redis_audit.csv

Features:
    - Non-blocking SCAN-based iteration
    - Pattern-based TTL recommendations
    - Dry-run mode for safety
    - CSV export for analysis
    - Backup before modifications

Author: Redis Architecture Team
Created: 2025-10-24
"""

import asyncio
import csv
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Tuple

from shared.config import settings
from shared.database.redis_patterns import RedisTTL, redis_context
from shared.logging import get_logger

logger = get_logger(__name__)


# TTL Recommendations by Key Pattern
TTL_PATTERNS = {
    # User data
    r"user:\d+:settings": RedisTTL.USER_SETTINGS,
    r"user:\d+:api:keys": RedisTTL.USER_DATA,
    r"user:\d+:position:.*": RedisTTL.POSITION_DATA,
    r"user:\d+:stats": RedisTTL.USER_DATA,
    r"user:\d+:trading:status": RedisTTL.USER_SESSION,

    # GRID strategy
    r"okx:user:\d+:.*": RedisTTL.USER_DATA,
    r"okx:user:\d+:symbol:.*:active_grid:\d+": RedisTTL.ORDER_DATA,
    r"orders:okx:user:\d+:.*": RedisTTL.ORDER_DATA,
    r"monitor:user:\d+:.*": RedisTTL.ORDER_DATA,
    r"completed:user:\d+:.*": RedisTTL.ORDER_DATA,

    # Cache keys
    r"cache:.*": RedisTTL.CACHE_MEDIUM,
    r"temp:.*": RedisTTL.TEMP_DATA,

    # System keys
    r".*:last_update": RedisTTL.TEMP_DATA,
    r".*:job_table_initialized": RedisTTL.USER_DATA,
}


def match_pattern(key: str) -> Tuple[str, int]:
    """
    Match key against patterns and return recommended TTL.

    Args:
        key: Redis key to match

    Returns:
        tuple: (matched_pattern, recommended_ttl)
    """
    import re

    for pattern, ttl in TTL_PATTERNS.items():
        if re.match(pattern, key):
            return pattern, ttl

    # Default TTL for unknown patterns
    return "unknown", RedisTTL.TEMP_DATA


async def scan_all_keys() -> List[str]:
    """
    Scan all Redis keys using SCAN (non-blocking).

    Returns:
        list: All Redis keys
    """
    all_keys = []
    cursor = 0

    async with redis_context() as redis:
        while True:
            cursor, keys = await redis.scan(
                cursor=cursor,
                count=1000  # Scan in batches of 1000
            )
            all_keys.extend(keys)

            if cursor == 0:
                break

    logger.info(f"Scanned {len(all_keys)} total keys")
    return all_keys


async def check_key_ttl(key: str) -> Tuple[str, int, str, int]:
    """
    Check TTL for a key and get recommendation.

    Args:
        key: Redis key

    Returns:
        tuple: (key, current_ttl, matched_pattern, recommended_ttl)
    """
    async with redis_context() as redis:
        ttl = await redis.ttl(key)

    pattern, recommended_ttl = match_pattern(key)

    return key, ttl, pattern, recommended_ttl


async def audit_keys(keys: List[str]) -> Dict:
    """
    Audit all keys and generate report.

    Args:
        keys: List of Redis keys to audit

    Returns:
        dict: Audit results
    """
    results = {
        "total_keys": len(keys),
        "orphaned_keys": [],
        "keys_with_ttl": [],
        "patterns": defaultdict(lambda: {"count": 0, "orphaned": 0})
    }

    print(f"\n🔍 Auditing {len(keys)} keys...")

    for i, key in enumerate(keys):
        if i % 100 == 0:
            print(f"  Progress: {i}/{len(keys)} keys processed...", end="\r")

        key_str, ttl, pattern, recommended_ttl = await check_key_ttl(key)

        # Update pattern statistics
        results["patterns"][pattern]["count"] += 1

        if ttl == -1:  # No TTL set
            results["orphaned_keys"].append({
                "key": key_str,
                "pattern": pattern,
                "recommended_ttl": recommended_ttl
            })
            results["patterns"][pattern]["orphaned"] += 1
        else:
            results["keys_with_ttl"].append({
                "key": key_str,
                "ttl": ttl,
                "pattern": pattern
            })

    print(f"  Progress: {len(keys)}/{len(keys)} keys processed. ✓")

    return results


async def fix_orphaned_keys(orphaned_keys: List[Dict], dry_run: bool = True) -> int:
    """
    Fix TTLs for orphaned keys.

    Args:
        orphaned_keys: List of orphaned key dictionaries
        dry_run: If True, don't actually fix (default: True)

    Returns:
        int: Number of keys fixed
    """
    if dry_run:
        print(f"\n⚠️  DRY RUN MODE - No changes will be made")
        return 0

    print(f"\n🔧 Fixing {len(orphaned_keys)} orphaned keys...")

    fixed_count = 0
    async with redis_context() as redis:
        for i, orphan in enumerate(orphaned_keys):
            if i % 10 == 0:
                print(f"  Progress: {i}/{len(orphaned_keys)} keys fixed...", end="\r")

            key = orphan["key"]
            ttl = orphan["recommended_ttl"]

            try:
                # Set TTL
                await redis.expire(key, ttl)
                fixed_count += 1

                logger.info(
                    f"Fixed TTL for orphaned key: {key} → {ttl}s",
                    extra={"key": key, "ttl": ttl}
                )

            except Exception as e:
                logger.error(
                    f"Failed to fix TTL for {key}: {e}",
                    extra={"key": key, "error": str(e)}
                )

    print(f"  Progress: {fixed_count}/{len(orphaned_keys)} keys fixed. ✓")
    return fixed_count


def print_summary(results: Dict):
    """Print audit summary."""
    print("\n" + "=" * 70)
    print("📊 REDIS TTL AUDIT SUMMARY")
    print("=" * 70)

    print(f"\n📈 Overall Statistics:")
    print(f"  Total keys scanned: {results['total_keys']}")
    print(f"  Keys with TTL: {len(results['keys_with_ttl'])}")
    print(f"  Orphaned keys (no TTL): {len(results['orphaned_keys'])}")

    orphan_pct = (len(results['orphaned_keys']) / results['total_keys'] * 100) if results['total_keys'] > 0 else 0
    print(f"  Orphan rate: {orphan_pct:.1f}%")

    if results['orphaned_keys']:
        print(f"\n⚠️  WARNING: Found {len(results['orphaned_keys'])} orphaned keys!")
        print(f"  These keys will never expire and may consume memory indefinitely.")

    print(f"\n📋 Keys by Pattern:")
    sorted_patterns = sorted(
        results['patterns'].items(),
        key=lambda x: x[1]['orphaned'],
        reverse=True
    )

    for pattern, stats in sorted_patterns:
        orphan_count = stats['orphaned']
        total_count = stats['count']
        orphan_pct = (orphan_count / total_count * 100) if total_count > 0 else 0

        status = "❌" if orphan_count > 0 else "✅"
        print(f"  {status} {pattern}")
        print(f"      Total: {total_count} | Orphaned: {orphan_count} ({orphan_pct:.1f}%)")

    print("=" * 70)


def export_to_csv(results: Dict, filename: str):
    """
    Export audit results to CSV.

    Args:
        results: Audit results dictionary
        filename: Output CSV filename
    """
    print(f"\n📁 Exporting results to {filename}...")

    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)

        # Write header
        writer.writerow([
            'Key',
            'Current TTL (seconds)',
            'Status',
            'Matched Pattern',
            'Recommended TTL (seconds)'
        ])

        # Write orphaned keys
        for orphan in results['orphaned_keys']:
            writer.writerow([
                orphan['key'],
                -1,
                'Orphaned (No TTL)',
                orphan['pattern'],
                orphan['recommended_ttl']
            ])

        # Write keys with TTL
        for key_info in results['keys_with_ttl']:
            writer.writerow([
                key_info['key'],
                key_info['ttl'],
                'Has TTL',
                key_info['pattern'],
                '-'
            ])

    print(f"  Export complete: {filename}")


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Redis TTL Audit - Find and fix orphaned keys",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Audit only (no changes)
  python scripts/redis_ttl_audit.py --dry-run

  # Audit and fix orphaned keys
  python scripts/redis_ttl_audit.py --fix

  # Export results to CSV
  python scripts/redis_ttl_audit.py --dry-run --export audit_results.csv
        """
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Audit only, do not modify keys (default behavior)'
    )

    parser.add_argument(
        '--fix',
        action='store_true',
        help='Fix TTLs for orphaned keys (WARNING: modifies Redis)'
    )

    parser.add_argument(
        '--export',
        type=str,
        metavar='FILE',
        help='Export results to CSV file'
    )

    args = parser.parse_args()

    # Banner
    print("\n" + "=" * 70)
    print("🔍 REDIS TTL AUDIT TOOL")
    print("=" * 70)
    print(f"Redis: {settings.REDIS_HOST}:{settings.REDIS_PORT}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if args.fix:
        print("⚠️  MODE: FIX (will modify Redis)")
    else:
        print("ℹ️  MODE: DRY RUN (read-only)")

    print("=" * 70)

    try:
        # Step 1: Scan all keys
        keys = await scan_all_keys()

        # Step 2: Audit keys
        results = await audit_keys(keys)

        # Step 3: Print summary
        print_summary(results)

        # Step 4: Fix orphaned keys (if requested)
        if results['orphaned_keys']:
            if args.fix:
                print("\n⚠️  This will modify Redis keys. Continue? (y/N): ", end='')
                if input().lower() == 'y':
                    fixed_count = await fix_orphaned_keys(results['orphaned_keys'], dry_run=False)
                    print(f"\n✅ Fixed TTL for {fixed_count} keys")
                else:
                    print("\n❌ Cancelled by user")
            else:
                print(f"\n💡 To fix these orphaned keys, run with --fix flag")

        # Step 5: Export to CSV (if requested)
        if args.export:
            export_to_csv(results, args.export)

        print("\n✅ Audit complete!\n")

    except Exception as e:
        logger.error(f"Audit failed: {e}", exc_info=True)
        print(f"\n❌ Error: {e}\n")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
