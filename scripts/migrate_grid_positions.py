#!/usr/bin/env python3
"""
GRID Position Storage Migration Script

Migrates GRID position storage from JSON array to individual Hash pattern.

Old Pattern: {exchange}:positions:{user_id} → JSON array of all positions
New Pattern: positions:{user_id}:{exchange}:{symbol}:{side} → Individual Hash per position
           + positions:index:{user_id}:{exchange} → Set of active positions

This is a Phase 2 migration that requires careful planning and testing.

Usage:
    python scripts/migrate_grid_positions.py [--dry-run] [--exchange okx]
"""

import asyncio
import argparse
import json
from typing import Dict, List, Any, Optional
from datetime import datetime


async def get_redis():
    """Get Redis connection"""
    from shared.database.redis import get_redis
    return await get_redis()


async def find_position_arrays(exchange: Optional[str] = None) -> Dict[str, List[str]]:
    """Find all position arrays that need migration"""
    redis = await get_redis()

    if exchange:
        pattern = f"{exchange}:positions:*"
    else:
        pattern = "*:positions:*"

    keys = await redis.keys(pattern)
    position_arrays = {}

    for key in keys:
        key_str = key.decode() if isinstance(key, bytes) else key
        # Parse: {exchange}:positions:{user_id}
        parts = key_str.split(":")
        if len(parts) == 3 and parts[1] == "positions":
            exchange_name = parts[0]
            user_id = parts[2]

            if exchange_name not in position_arrays:
                position_arrays[exchange_name] = []
            position_arrays[exchange_name].append((key_str, user_id))

    return position_arrays


def determine_position_side(position: Dict[str, Any]) -> str:
    """Determine position side from position data"""
    pos = float(position.get('pos', 0))

    if pos > 0:
        return 'long'
    elif pos < 0:
        return 'short'
    else:
        # Position is closed, but we still need a side for the key
        # Try to get from position data
        pos_side = position.get('posSide', '').lower()
        if pos_side in ['long', 'short']:
            return pos_side

        # Default to 'long' for closed positions
        return 'long'


async def migrate_position_array(
    exchange: str,
    user_id: str,
    old_key: str,
    dry_run: bool = True
) -> Dict[str, Any]:
    """
    Migrate a single position array to individual Hash keys

    Returns migration statistics
    """
    redis = await get_redis()
    stats = {
        "positions_found": 0,
        "positions_migrated": 0,
        "errors": []
    }

    try:
        # Get old data
        old_data = await redis.get(old_key)
        if not old_data:
            print(f"   ⚠️  Key {old_key} is empty")
            return stats

        # Parse JSON array
        positions = json.loads(old_data)
        if not isinstance(positions, list):
            print(f"   ⚠️  Key {old_key} is not a JSON array")
            return stats

        stats["positions_found"] = len(positions)

        if not positions:
            print(f"   ℹ️  No positions found in {old_key}")
            return stats

        print(f"\n   Processing {len(positions)} positions for user {user_id}:")

        # Migrate each position
        index_set = set()

        for position in positions:
            if not isinstance(position, dict):
                stats["errors"].append(f"Invalid position data: {position}")
                continue

            symbol = position.get('instId')
            if not symbol:
                stats["errors"].append(f"Position missing symbol: {position}")
                continue

            side = determine_position_side(position)
            pos_value = float(position.get('pos', 0))

            # Skip zero positions unless they have important metadata
            notional = float(position.get('notionalUsd', 0))
            if pos_value == 0 and notional == 0:
                print(f"      ⏭️  Skipping closed position: {symbol}")
                continue

            # Create new key
            new_key = f"positions:{user_id}:{exchange}:{symbol}:{side}"

            if dry_run:
                print(f"      [DRY RUN] Would create: {new_key}")
                print(f"         pos={pos_value}, notional=${notional:.2f}")
            else:
                # Store as Hash
                await redis.hset(new_key, mapping={
                    'instId': symbol,
                    'pos': str(position.get('pos', 0)),
                    'notionalUsd': str(position.get('notionalUsd', 0)),
                    'posSide': side,
                    'avgPx': str(position.get('avgPx', 0)),
                    'upl': str(position.get('upl', 0)),
                    'uplRatio': str(position.get('uplRatio', 0)),
                    'lever': str(position.get('lever', 1)),
                    'liqPx': str(position.get('liqPx', 0)),
                    'markPx': str(position.get('markPx', 0)),
                    'margin': str(position.get('margin', 0)),
                    'mgnMode': position.get('mgnMode', 'cross'),
                    'mgnRatio': str(position.get('mgnRatio', 0)),
                    'mmr': str(position.get('mmr', 0)),
                    'imr': str(position.get('imr', 0)),
                    'last': str(position.get('last', 0)),
                    'uTime': str(position.get('uTime', '')),
                    'cTime': str(position.get('cTime', '')),
                    # Add migration metadata
                    'migrated_at': datetime.utcnow().isoformat(),
                    'migrated_from': old_key
                })

                # Add to index
                index_set.add(f"{symbol}:{side}")
                print(f"      ✅ Created: {new_key} (pos={pos_value})")

            stats["positions_migrated"] += 1

        # Create index key
        if index_set and not dry_run:
            index_key = f"positions:index:{user_id}:{exchange}"
            await redis.sadd(index_key, *list(index_set))
            print(f"   ✅ Created index: {index_key} ({len(index_set)} positions)")

        # Backup old key before deletion
        if not dry_run:
            backup_key = f"{old_key}:backup:{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
            await redis.set(backup_key, old_data)
            await redis.expire(backup_key, 86400 * 7)  # Keep backup for 7 days
            print(f"   💾 Backed up to: {backup_key} (expires in 7 days)")

            # Delete old key
            await redis.delete(old_key)
            print(f"   🗑️  Deleted old key: {old_key}")

    except json.JSONDecodeError as e:
        error_msg = f"JSON decode error for {old_key}: {e}"
        stats["errors"].append(error_msg)
        print(f"   ❌ {error_msg}")
    except Exception as e:
        error_msg = f"Error processing {old_key}: {e}"
        stats["errors"].append(error_msg)
        print(f"   ❌ {error_msg}")

    return stats


async def main():
    """Main migration function"""
    parser = argparse.ArgumentParser(
        description="Migrate GRID positions from JSON array to Hash storage"
    )
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be done without making changes")
    parser.add_argument("--exchange", type=str,
                       help="Only migrate positions for specific exchange")
    parser.add_argument("--force", action="store_true",
                       help="Skip confirmation prompts")
    args = parser.parse_args()

    print("\n" + "="*80)
    print("GRID Position Storage Migration")
    print("JSON Array → Individual Hash Pattern")
    if args.dry_run:
        print("[DRY RUN MODE - No changes will be made]")
    print("="*80 + "\n")

    # Find all position arrays
    print("🔍 Scanning for position arrays...")
    position_arrays = await find_position_arrays(args.exchange)

    if not position_arrays:
        print("✅ No position arrays found!")
        if args.exchange:
            print(f"   (for exchange: {args.exchange})")
        return 0

    # Display summary
    print("\n📊 Found position arrays:\n")
    total_users = 0
    for exchange, users in position_arrays.items():
        total_users += len(users)
        print(f"  {exchange}: {len(users)} users")

    print(f"\n  Total: {total_users} users")

    if not args.dry_run and not args.force:
        print("\n⚠️  WARNING: This is a major data migration!")
        print("   - Old keys will be backed up for 7 days")
        print("   - Test on staging environment first")
        print("   - Ensure no trading operations during migration")
        response = input("\n⚠️  Proceed with migration? (type 'yes' to confirm): ")
        if response != "yes":
            print("Migration cancelled.")
            return 1

    # Perform migration
    total_stats = {
        "users_processed": 0,
        "positions_found": 0,
        "positions_migrated": 0,
        "errors": []
    }

    for exchange, users in position_arrays.items():
        print(f"\n{'='*80}")
        print(f"Processing exchange: {exchange}")
        print(f"{'='*80}")

        for old_key, user_id in users:
            total_stats["users_processed"] += 1
            print(f"\n[{total_stats['users_processed']}/{total_users}] User {user_id}:")

            stats = await migrate_position_array(
                exchange=exchange,
                user_id=user_id,
                old_key=old_key,
                dry_run=args.dry_run
            )

            total_stats["positions_found"] += stats["positions_found"]
            total_stats["positions_migrated"] += stats["positions_migrated"]
            total_stats["errors"].extend(stats["errors"])

    # Summary
    print("\n" + "="*80)
    if args.dry_run:
        print("DRY RUN COMPLETE")
        print(f"\nWould migrate:")
    else:
        print("MIGRATION COMPLETE")
        print(f"\nMigrated:")

    print(f"  Users processed: {total_stats['users_processed']}")
    print(f"  Positions found: {total_stats['positions_found']}")
    print(f"  Positions migrated: {total_stats['positions_migrated']}")

    if total_stats["errors"]:
        print(f"\n⚠️  Errors encountered: {len(total_stats['errors'])}")
        print("\nError details:")
        for error in total_stats["errors"][:10]:  # Show first 10 errors
            print(f"  - {error}")
        if len(total_stats["errors"]) > 10:
            print(f"  ... and {len(total_stats['errors']) - 10} more")

    if args.dry_run:
        print("\n💡 Run without --dry-run to apply changes")
    else:
        print("\n✅ Migration completed successfully!")
        print("   Old keys backed up for 7 days")
        print("   Monitor application for any issues")

    print("="*80)

    return 0 if not total_stats["errors"] else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
