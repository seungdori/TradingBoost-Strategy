#!/usr/bin/env python3
"""
Redis Legacy Keys Cleanup Script

Cleans up legacy Redis keys that don't follow the standardized pattern.
This script should be run after Phase 1 deployment to remove old keys.

Usage:
    python scripts/cleanup_legacy_keys.py [--dry-run]
"""

import asyncio
import argparse
from typing import List, Dict
import re


async def get_redis():
    """Get Redis connection"""
    from shared.database.redis import get_redis
    return await get_redis()


async def find_legacy_keys() -> Dict[str, List[str]]:
    """Find all legacy keys that need cleanup"""
    redis = await get_redis()

    legacy_patterns = {
        "old_position_cache": {
            "pattern": "position:*",
            "regex": r"^position:[^:]+:[^:]+$",  # Missing exchange and side
            "description": "Old position cache keys without exchange/side"
        },
        "old_user_position": {
            "pattern": "user:*:position:*",
            "regex": r"^user:\d+:position:[^:]+:(long|short)$",
            "description": "Legacy user:position pattern"
        },
        "old_order_placed": {
            "pattern": "*:user:*:symbol:*:order_placed",
            "regex": r"^(okx|binance|bitget|upbit|bybit):user:\d+:symbol:[^:]+:order_placed$",
            "description": "Order placed keys without 'orders:' prefix"
        }
    }

    results = {}

    for name, config in legacy_patterns.items():
        keys = await redis.keys(config["pattern"])
        matching_keys = []

        for key in keys:
            key_str = key.decode() if isinstance(key, bytes) else key
            if re.match(config["regex"], key_str):
                matching_keys.append(key_str)

        if matching_keys:
            results[name] = {
                "keys": matching_keys,
                "description": config["description"]
            }

    return results


async def cleanup_old_position_keys(keys: List[str], dry_run: bool = True) -> int:
    """
    Clean up old position cache keys

    These keys are from the old pattern: position:{user_id}:{symbol}
    New pattern: position:{user_id}:{exchange}:{symbol}:{side}

    Since we can't determine exchange and side from old keys, we just delete them.
    The cache will be rebuilt on next access.
    """
    redis = await get_redis()
    deleted = 0

    print(f"\n🔍 Processing {len(keys)} old position cache keys...")

    for key in keys:
        if dry_run:
            print(f"   [DRY RUN] Would delete: {key}")
        else:
            await redis.delete(key)
            print(f"   ✅ Deleted: {key}")
            deleted += 1

    return deleted


async def migrate_user_position_keys(keys: List[str], dry_run: bool = True) -> int:
    """
    Migrate legacy user:position keys to new pattern

    Old: user:{user_id}:position:{symbol}:{side}
    New: position:{user_id}:{exchange}:{symbol}:{side}

    Since these are cache keys, we can safely delete them and let them rebuild.
    """
    redis = await get_redis()
    migrated = 0

    print(f"\n🔍 Processing {len(keys)} legacy user:position keys...")

    for old_key in keys:
        # Parse old key: user:{user_id}:position:{symbol}:{side}
        parts = old_key.split(":")
        if len(parts) != 5:
            print(f"   ⚠️  Skipping malformed key: {old_key}")
            continue

        user_id = parts[1]
        symbol = parts[3]
        side = parts[4]

        # These are cache keys, just delete them
        # New code will recreate with proper pattern
        if dry_run:
            print(f"   [DRY RUN] Would delete: {old_key}")
        else:
            await redis.delete(old_key)
            print(f"   ✅ Deleted: {old_key} (user={user_id}, symbol={symbol}, side={side})")
            migrated += 1

    return migrated


async def migrate_order_placed_keys(keys: List[str], dry_run: bool = True) -> int:
    """
    Migrate order_placed keys to new pattern

    Old: {exchange}:user:{user_id}:symbol:{symbol}:order_placed
    New: orders:{exchange}:user:{user_id}:symbol:{symbol}:order_placed

    This is actual data, so we copy it to the new key.
    """
    redis = await get_redis()
    migrated = 0

    print(f"\n🔍 Processing {len(keys)} order_placed keys...")

    for old_key in keys:
        # Parse old key: {exchange}:user:{user_id}:symbol:{symbol}:order_placed
        parts = old_key.split(":")
        if len(parts) < 6:
            print(f"   ⚠️  Skipping malformed key: {old_key}")
            continue

        exchange = parts[0]
        user_id = parts[2]
        symbol = parts[4]

        # Create new key with 'orders:' prefix
        new_key = f"orders:{old_key}"

        if dry_run:
            print(f"   [DRY RUN] Would migrate:")
            print(f"      Old: {old_key}")
            print(f"      New: {new_key}")
        else:
            # Check if new key already exists
            if await redis.exists(new_key):
                print(f"   ⚠️  New key already exists, comparing data...")
                old_data = await redis.hgetall(old_key)
                new_data = await redis.hgetall(new_key)

                if old_data == new_data:
                    print(f"   ✅ Data matches, deleting old key: {old_key}")
                    await redis.delete(old_key)
                    migrated += 1
                else:
                    print(f"   ⚠️  Data mismatch! Manual review needed:")
                    print(f"      Old: {old_data}")
                    print(f"      New: {new_data}")
            else:
                # Copy all hash fields to new key
                data = await redis.hgetall(old_key)
                if data:
                    await redis.hset(new_key, mapping=data)

                    # Copy TTL if exists
                    ttl = await redis.ttl(old_key)
                    if ttl > 0:
                        await redis.expire(new_key, ttl)

                    # Delete old key
                    await redis.delete(old_key)
                    print(f"   ✅ Migrated: {old_key} → {new_key}")
                    migrated += 1
                else:
                    print(f"   ⚠️  Empty key, deleting: {old_key}")
                    await redis.delete(old_key)

    return migrated


async def main():
    """Main cleanup function"""
    parser = argparse.ArgumentParser(description="Clean up legacy Redis keys")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be done without making changes")
    parser.add_argument("--force", action="store_true",
                       help="Skip confirmation prompts")
    args = parser.parse_args()

    print("\n" + "="*80)
    print("Redis Legacy Keys Cleanup")
    if args.dry_run:
        print("[DRY RUN MODE - No changes will be made]")
    print("="*80 + "\n")

    # Find all legacy keys
    print("🔍 Scanning for legacy keys...")
    legacy_keys = await find_legacy_keys()

    if not legacy_keys:
        print("✅ No legacy keys found! Database is clean.")
        return 0

    # Display summary
    print("\n📊 Found the following legacy keys:\n")
    total_keys = 0
    for name, info in legacy_keys.items():
        count = len(info["keys"])
        total_keys += count
        print(f"  {name}: {count} keys")
        print(f"    Description: {info['description']}")

    print(f"\n  Total: {total_keys} legacy keys")

    if not args.dry_run and not args.force:
        response = input("\n⚠️  Proceed with cleanup? (yes/no): ")
        if response.lower() != "yes":
            print("Cleanup cancelled.")
            return 1

    # Perform cleanup
    total_processed = 0

    if "old_position_cache" in legacy_keys:
        count = await cleanup_old_position_keys(
            legacy_keys["old_position_cache"]["keys"],
            dry_run=args.dry_run
        )
        total_processed += count

    if "old_user_position" in legacy_keys:
        count = await migrate_user_position_keys(
            legacy_keys["old_user_position"]["keys"],
            dry_run=args.dry_run
        )
        total_processed += count

    if "old_order_placed" in legacy_keys:
        count = await migrate_order_placed_keys(
            legacy_keys["old_order_placed"]["keys"],
            dry_run=args.dry_run
        )
        total_processed += count

    # Summary
    print("\n" + "="*80)
    if args.dry_run:
        print("DRY RUN COMPLETE")
        print(f"  Would process {total_processed} keys")
        print("\nRun without --dry-run to apply changes")
    else:
        print("CLEANUP COMPLETE")
        print(f"  Processed: {total_processed} keys")
        print("\n✅ Legacy keys have been cleaned up!")
    print("="*80)

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
