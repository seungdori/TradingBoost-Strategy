# Redis Connection Pool - Quick Reference Guide

## 🚀 Quick Start

### For New Code

**Use shared pool for all Redis operations:**

```python
from shared.database.redis import get_redis

async def my_function():
    redis = await get_redis()
    await redis.set('key', 'value')
    value = await redis.get('key')
```

### For Existing Code

**No changes needed!** All modules automatically use the shared pool.

## 📊 Connection Pool Information

| Property | Value |
|----------|-------|
| Max Connections | 200 (configurable) |
| Pool Type | Shared singleton |
| Database | 0 (default) |
| Decode Responses | Yes |
| Location | `shared/database/redis.py` |

## 🔧 Configuration

**Environment Variables:**

```bash
# Optional - defaults to 200
export REDIS_MAX_CONNECTIONS=200

# Redis connection (required)
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_PASSWORD=your_password  # if needed
```

**In code:**

```python
from shared.config import settings

# Access settings
max_connections = settings.REDIS_MAX_CONNECTIONS
```

## 🏥 Health Monitoring

### Check Redis Health

**HYPERRSI:**
```bash
curl http://localhost:8000/api/health/redis
```

**GRID:**
```bash
curl http://localhost:8012/health/redis
```

**Response:**
```json
{
  "status": "healthy",
  "message": "Redis responding normally",
  "latency_ms": 1.23,
  "pool": {
    "max_connections": 200,
    "min_size": 200
  }
}
```

### Available Endpoints

| Endpoint | Description |
|----------|-------------|
| `/health` | Overall system health |
| `/health/redis` | Redis pool metrics |
| `/health/db` | Database pool metrics |
| `/health/ready` | Readiness probe |
| `/health/live` | Liveness probe |

## 💡 Common Patterns

### Get Redis Client

```python
from shared.database.redis import get_redis

async def example():
    redis = await get_redis()
    # Use redis client
```

### Lazy Initialization in Class

```python
from shared.database.redis import get_redis

class MyService:
    def __init__(self):
        self._redis = None
    
    async def _ensure_redis(self):
        if self._redis is None:
            self._redis = await get_redis()
        return self._redis
    
    async def do_something(self):
        redis = await self._ensure_redis()
        await redis.set('key', 'value')
```

### Pipeline Operations

```python
async def batch_operations():
    redis = await get_redis()
    
    pipe = redis.pipeline()
    pipe.set('key1', 'value1')
    pipe.set('key2', 'value2')
    pipe.get('key1')
    
    results = await pipe.execute()
```

## 🎯 Best Practices

### DO ✅

- Use `await get_redis()` to get the client
- Implement lazy initialization in classes
- Use pipeline for batch operations
- Check health endpoints regularly
- Use async/await patterns

### DON'T ❌

- Don't create new connection pools
- Don't close the shared pool
- Don't use synchronous Redis operations
- Don't store credentials in code
- Don't exceed max connections

## 🐛 Troubleshooting

### Connection Issues

```python
# Check if Redis is reachable
from shared.database.redis import get_redis

async def check_connection():
    try:
        redis = await get_redis()
        await redis.ping()
        print("✅ Connected")
    except Exception as e:
        print(f"❌ Error: {e}")
```

### Pool Exhaustion

If you see "ConnectionError: Too many connections":

1. Check current connections: `redis-cli CLIENT LIST`
2. Review health endpoint: `curl http://localhost:8000/api/health/redis`
3. Increase max connections if needed (edit `.env`)
4. Look for connection leaks in your code

### Import Errors

Ensure you're using absolute imports:

```python
# ✅ Correct
from shared.database.redis import get_redis
from HYPERRSI.src.services.redis_service import RedisService
from GRID.core.redis import get_redis_connection

# ❌ Wrong
from database.redis import get_redis
from services.redis_service import RedisService
```

## 📈 Monitoring Commands

### Redis CLI

```bash
# Check connection count
redis-cli CLIENT LIST | wc -l

# Monitor commands
redis-cli MONITOR

# Check memory usage
redis-cli INFO memory

# Check stats
redis-cli INFO stats
```

### Python Monitoring

```python
from shared.database.redis import RedisConnectionPool

async def check_pool_health():
    health = await RedisConnectionPool.health_check()
    print(f"Status: {health['status']}")
    print(f"Latency: {health['latency_ms']}ms")
```

## 🔄 Migration from Old Code

If you have old code with independent pools:

**Before:**
```python
import redis.asyncio as aioredis

pool = aioredis.ConnectionPool.from_url(
    'redis://localhost',
    max_connections=100
)
redis_client = aioredis.Redis(connection_pool=pool)
```

**After:**
```python
from shared.database.redis import get_redis

redis_client = await get_redis()
```

## 📚 Related Documentation

- **Full Migration Report**: `REDIS_MIGRATION_REPORT.md`
- **Shared Config**: `shared/config.py`
- **Pool Implementation**: `shared/database/redis.py`
- **Health Endpoints**: `shared/api/health.py`

## 🆘 Support

For issues or questions:

1. Check health endpoints first
2. Review logs for error messages
3. Verify environment variables are set
4. Check Redis server is running
5. Review this guide and migration report

---

**Last Updated**: October 14, 2025  
**Status**: Production Ready  
**Pool Max Connections**: 200
