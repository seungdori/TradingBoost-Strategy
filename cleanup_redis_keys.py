#!/usr/bin/env python3
"""Clean up Redis keys with wrong data types"""
import asyncio
import redis.asyncio as redis
from shared.config import get_settings

async def cleanup_redis_keys():
    """Remove keys that have wrong data types"""
    settings = get_settings()

    # Build Redis URL with password if provided
    if settings.REDIS_PASSWORD:
        redis_url = f"redis://:{settings.REDIS_PASSWORD}@{settings.REDIS_HOST}:{settings.REDIS_PORT}/0"
    else:
        redis_url = f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/0"

    r = redis.from_url(redis_url, decode_responses=True)
    
    try:
        # Patterns to check
        patterns = [
            "user:*:settings",
            "okx:user:*",
            "binance:user:*",
            "upbit:user:*",
            "bitget:user:*",
            "bybit:user:*"
        ]
        
        fixed_count = 0
        
        for pattern in patterns:
            cursor = 0
            while True:
                cursor, keys = await r.scan(cursor, match=pattern, count=100)
                
                for key in keys:
                    key_type = await r.type(key)
                    # If it's not a hash but should be, delete it
                    if key_type != 'hash' and key_type != 'none':
                        print(f"Deleting non-hash key: {key} (type: {key_type})")
                        await r.delete(key)
                        fixed_count += 1
                
                if cursor == 0:
                    break
        
        print(f"\n✅ Cleanup complete! Deleted {fixed_count} problematic keys.")
        
    finally:
        await r.aclose()

if __name__ == "__main__":
    asyncio.run(cleanup_redis_keys())
