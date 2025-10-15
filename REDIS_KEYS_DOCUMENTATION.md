# Redis Keys Documentation

Complete reference for all Redis key patterns used across TradingBoost-Strategy project.

**Last Updated**: 2025-10-14

---

## Table of Contents

1. [User Management Keys](#user-management-keys)
2. [Trading Keys](#trading-keys)
3. [Position & Order Keys](#position--order-keys)
4. [Grid Trading Keys](#grid-trading-keys)
5. [Cache Keys](#cache-keys)
6. [WebSocket & Real-time Keys](#websocket--real-time-keys)
7. [Job & Status Keys](#job--status-keys)
8. [Statistics Keys](#statistics-keys)

---

## User Management Keys

### User Settings
**Pattern**: `user:{user_id}:settings`
**Type**: Hash
**Module**: HYPERRSI (redis_service.py)
**Purpose**: Store user trading settings and preferences
**TTL**: Persistent (with local cache: 30s)

**Fields**:
- `direction`: "long" | "short" | "both"
- `entry_option`: Entry strategy option
- `tp_sl_option`: Take profit/stop loss configuration
- `pyramiding_type`: Position scaling strategy
- `leverage`: Trading leverage (1-125)
- `initial_capital`: Starting capital amount
- `risk_per_trade`: Risk percentage per trade
- All fields from `DEFAULT_PARAMS_SETTINGS`

**Example**:
```python
await redis.hgetall("user:12345:settings")
# Returns: {"direction": "long", "leverage": "10", ...}
```

---

### User API Keys
**Pattern**: `user:{user_id}:api:keys`
**Type**: Hash
**Module**: HYPERRSI (redis_service.py), GRID (api_key_service.py)
**Purpose**: Store exchange API credentials (encrypted)

**Fields**:
- `api_key`: Exchange API key
- `api_secret`: Exchange secret key
- `passphrase`: API passphrase (for OKX/Bitget)

**Example**:
```python
await redis.hgetall("user:12345:api:keys")
```

---

### Exchange-Specific User Data
**Pattern**: `{exchange}:user:{user_id}`
**Type**: Hash
**Module**: GRID (redis_database.py)
**Purpose**: Store user configuration per exchange

**Fields**:
- `api_key`, `api_secret`, `password`: API credentials
- `initial_capital`: Starting capital (JSON)
- `direction`: "long" | "short"
- `numbers_to_entry`: Number of entry levels
- `leverage`: Trading leverage
- `is_running`: "0" | "1" (bot running status)
- `stop_loss`: Stop loss percentage
- `tasks`: JSON array of active tasks
- `running_symbols`: JSON array of active symbols
- `completed_symbols`: JSON array of completed symbols
- `grid_num`: Number of grid levels (default: 20)
- `stop_task_only`: "0" | "1"
- `last_updated_time`: ISO timestamp

**Example**:
```python
await redis.hgetall("okx:user:12345")
```

---

### User Index
**Pattern**: `{exchange}:user_ids`
**Type**: Set
**Module**: GRID (redis_database.py)
**Purpose**: Track all registered user IDs for an exchange

**Example**:
```python
await redis.smembers("okx:user_ids")  # Returns: {"12345", "67890", ...}
```

---

### User Telegram Integration
**Pattern**: `{exchange}:telegram_ids`
**Type**: Hash
**Module**: GRID (redis_database.py)
**Purpose**: Map user IDs to Telegram IDs

**Example**:
```python
await redis.hget("okx:telegram_ids", "12345")  # Returns: "telegram_id"
```

---

### User Watchlist
**Pattern**: `user:{user_id}:watchlist:{exchange}`
**Type**: Set
**Module**: position-order-service (active_user_manager.py)
**Purpose**: Track symbols user is monitoring

**Example**:
```python
await redis.smembers("user:12345:watchlist:okx")  # Returns: {"BTC-USDT", "ETH-USDT"}
```

---

## Trading Keys

### Active Positions
**Pattern**: `positions:{user_id}:{exchange}:{symbol}:{side}`
**Type**: Hash
**Module**: shared (redis_schemas.py)
**Purpose**: Store active position details

**Fields** (RedisSerializer.position_to_dict):
- `id`: Position UUID
- `user_id`: User identifier
- `exchange`: Exchange name (okx, binance, etc.)
- `symbol`: Trading pair (BTC-USDT)
- `side`: "long" | "short"
- `size`: Position size (Decimal as string)
- `entry_price`: Entry price (Decimal)
- `current_price`: Current price (Decimal)
- `exit_price`: Exit price if closed
- `leverage`: Leverage multiplier
- `liquidation_price`: Liquidation threshold
- `stop_loss_price`: Stop loss trigger price
- `take_profit_price`: Take profit target
- `realized_pnl`: Realized profit/loss
- `unrealized_pnl`: Unrealized profit/loss
- `fees`: Trading fees paid
- `status`: "open" | "closed" | "liquidated"
- `metadata`: JSON additional data
- `created_at`, `updated_at`, `closed_at`: ISO timestamps
- `grid_level`: Grid level (for GRID strategy)

**Example**:
```python
await redis.hgetall("positions:12345:okx:BTC-USDT:long")
```

---

### Position Index
**Pattern**: `positions:index:{user_id}:{exchange}`
**Type**: Set
**Module**: shared (redis_schemas.py)
**Purpose**: Track all active positions for a user

**Example**:
```python
await redis.smembers("positions:index:12345:okx")
# Returns: {"BTC-USDT:long", "ETH-USDT:short", ...}
```

---

### Global Active Positions
**Pattern**: `positions:active`
**Type**: Set
**Module**: shared (redis_schemas.py)
**Purpose**: Track all active positions system-wide

**Example**:
```python
await redis.smembers("positions:active")
# Returns: {"12345:okx:BTC-USDT:long", ...}
```

---

### Position History
**Pattern**: `positions:history:{user_id}:{exchange}`
**Type**: Sorted Set (score = timestamp)
**Module**: shared (redis_schemas.py)
**Purpose**: Store closed position summaries

**Example**:
```python
await redis.zrange("positions:history:12345:okx", 0, -1)
```

---

### Order Details
**Pattern**: `orders:{order_id}`
**Type**: Hash
**Module**: shared (redis_schemas.py)
**Purpose**: Store order information

**Fields** (RedisSerializer.order_to_dict):
- `id`: Order UUID
- `user_id`: User identifier
- `exchange`: Exchange name
- `exchange_order_id`: Exchange's order ID
- `symbol`: Trading pair
- `side`: "buy" | "sell"
- `order_type`: "market" | "limit" | "stop_limit" | "trigger"
- `quantity`: Order quantity
- `price`: Limit price (if applicable)
- `trigger_price`: Stop/trigger price
- `filled_qty`: Filled quantity
- `avg_fill_price`: Average fill price
- `status`: "pending" | "open" | "filled" | "cancelled" | "rejected"
- `reduce_only`: "True" | "False"
- `post_only`: "True" | "False"
- `time_in_force`: "GTC" | "IOC" | "FOK"
- `maker_fee`, `taker_fee`, `funding_fee`: Fee amounts
- `metadata`: JSON additional data
- `created_at`, `updated_at`, `filled_at`: ISO timestamps
- `grid_level`: Grid level (for GRID strategy)

**Example**:
```python
await redis.hgetall("orders:550e8400-e29b-41d4-a716-446655440000")
```

---

### Order Index
**Pattern**: `orders:user:{user_id}:{exchange}`
**Type**: Set
**Module**: shared (redis_schemas.py)
**Purpose**: Track all orders for a user

**Example**:
```python
await redis.smembers("orders:user:12345:okx")
```

---

### Open Orders by Symbol
**Pattern**: `orders:open:{exchange}:{symbol}`
**Type**: Set
**Module**: shared (redis_schemas.py)
**Purpose**: Track all open orders for a symbol

**Example**:
```python
await redis.smembers("orders:open:okx:BTC-USDT")
```

---

### Position Cache (HYPERRSI) - ✅ Updated Phase 1
**Pattern**: `position:{user_id}:{exchange}:{symbol}:{side}`
**Type**: JSON String
**Module**: shared (trading_cache.py)
**TTL**: 300 seconds (5 minutes)
**Purpose**: Short-term cache for position data with exchange and side support

**Changes (2025-10-14)**:
- ✅ Added `exchange` parameter (default: "okx")
- ✅ Added `side` parameter ("long" | "short")
- ✅ Backward compatible with default parameters

**Example**:
```python
from shared.cache import trading_cache

# New API (recommended)
await trading_cache.set_position("12345", "BTC-USDT-SWAP", "long", data, "okx")
pos = await trading_cache.get_position("12345", "BTC-USDT-SWAP", "long", "okx")

# With default exchange (backward compatible)
await trading_cache.set_position("12345", "BTC-USDT-SWAP", "long", data)
pos = await trading_cache.get_position("12345", "BTC-USDT-SWAP", "long")

# Bulk get
positions = await trading_cache.bulk_get_positions(
    ["12345", "67890"], "BTC-USDT-SWAP", "long", "okx"
)

# Remove
await trading_cache.remove_position("12345", "BTC-USDT-SWAP", "long", "okx")
```

---

### Order Cache (HYPERRSI)
**Pattern**: `order:{order_id}`
**Type**: JSON String
**Module**: HYPERRSI (trading_cache.py)
**TTL**: 3600 seconds (1 hour)

**Example**:
```python
await redis.get("order:550e8400-e29b-41d4-a716-446655440000")
```

---

## Grid Trading Keys

### Active Grid Level
**Pattern**: `{exchange}:user:{user_id}:symbol:{symbol}:active_grid:{level}`
**Type**: Hash
**Module**: GRID (redis_database.py)
**Purpose**: Store grid level details (0-20)

**Fields**:
- `entry_price`: Entry price at this level (JSON number)
- `position_size`: Position size at this level (JSON number)
- `grid_count`: Number of fills at this level (JSON integer)
- `pnl`: Profit/loss at this level (JSON number)
- `execution_time`: Last execution timestamp (JSON ISO string)

**Example**:
```python
await redis.hgetall("okx:user:12345:symbol:BTC-USDT:active_grid:10")
```

---

### Grid Active Level (Alternative Pattern)
**Pattern**: `{exchange}:user:{user_id}:symbol:{symbol}:active_grid`
**Type**: Hash (flattened, `{level}:{field}` keys)
**Module**: GRID (redis_database.py, initialize_active_grid)
**Purpose**: Store all grid levels in single hash

**Example**:
```python
await redis.hget("okx:user:12345:symbol:BTC-USDT:active_grid", "10:entry_price")
```

---

### Order Placed Status - ✅ Updated Phase 1
**Pattern**: `orders:{exchange}:user:{user_id}:symbol:{symbol}:order_placed`
**Type**: Hash
**Module**: GRID (redis_database.py, order_service.py)
**Purpose**: Track if order is placed at each grid level

**Changes (2025-10-14)**:
- ✅ Added `orders:` prefix for namespace consistency
- ✅ Aligns with order_service.py pattern
- ✅ Improved organization with related order keys

**Fields**: `{level}` → "0" | "1"

**Example**:
```python
from GRID.database.redis_database import get_order_placed, set_order_placed

# Get status
placed = await get_order_placed(redis, "okx", 12345, "BTC-USDT", 10)

# Set status
await set_order_placed(redis, "okx", 12345, "BTC-USDT", 10, True)

# Direct Redis access
await redis.hget("orders:okx:user:12345:symbol:BTC-USDT:order_placed", "10")  # Returns: "1"
```

---

### Grid Order Prices
**Pattern**: `orders:{exchange}:user:{user_id}:symbol:{symbol}:orders`
**Type**: Sorted Set (score = price)
**Module**: GRID (order_service.py)
**Purpose**: Track all order prices for grid

**Example**:
```python
await redis.zrange("orders:okx:user:12345:symbol:BTC-USDT:orders", 0, -1, withscores=True)
```

---

### Grid Order Placed Index
**Pattern**: `orders:{exchange}:user:{user_id}:symbol:{symbol}:order_placed_index`
**Type**: Set
**Module**: GRID (order_service.py)
**Purpose**: Track order IDs placed for grid

**Example**:
```python
await redis.smembers("orders:okx:user:12345:symbol:BTC-USDT:order_placed_index")
```

---

### Grid Order IDs
**Pattern**: `{exchange}:user:{user_id}:symbol:{symbol}:order_ids`
**Type**: List
**Module**: GRID (grid_core.py)
**Purpose**: Track order IDs for cancellation

**Example**:
```python
await redis.lrange("okx:user:12345:symbol:BTC-USDT:order_ids", 0, -1)
```

---

### Take Profit Orders Info
**Pattern**: `{exchange}:user:{user_id}:symbol:{symbol}` (field: `take_profit_orders_info`)
**Type**: Hash field (JSON)
**Module**: GRID (redis_database.py)
**Purpose**: Track take profit orders per grid level

**JSON Structure**:
```json
{
  "10": {
    "order_id": "order_123",
    "target_price": 50000.5,
    "quantity": 0.01,
    "active": true,
    "side": "sell"
  }
}
```

**Example**:
```python
info = await redis.hget("okx:user:12345:symbol:BTC-USDT", "take_profit_orders_info")
```

---

### Symbol Data
**Pattern**: `{exchange}:user:{user_id}:{symbol}`
**Type**: Hash
**Module**: GRID (various)
**Purpose**: Store symbol-specific trading data

**Example**:
```python
await redis.hgetall("okx:user:12345:BTC-USDT")
```

---

## Cache Keys

### Generic Cache
**Pattern**: Custom (application-defined)
**Type**: String (JSON)
**Module**: shared (trading_cache.py)
**TTL**: Configurable (default: 3600s)

**Usage**:
```python
cache = Cache()
await cache.set("custom_key", {"data": "value"}, expire=3600)
```

---

### Local Cache
**Module**: HYPERRSI (redis_service.py)
**Purpose**: In-memory cache layer with 30s TTL
**Implementation**: Dictionary with TTL tracking

**Note**: Local cache is automatically synced with Redis

---

## WebSocket & Real-time Keys

### WebSocket Connection Status
**Pattern**: `websocket:{user_id}:{exchange}:status`
**Type**: String
**Module**: HYPERRSI (websocket_service.py)
**Purpose**: Track WebSocket connection state

**Values**: "connected" | "disconnected" | "reconnecting"

---

### Real-time Price Feed
**Pattern**: `price:{exchange}:{symbol}`
**Type**: String (JSON)
**Module**: GRID (okx_ws.py)
**TTL**: 60 seconds

**Example**:
```python
await redis.get("price:okx:BTC-USDT")  # Returns: {"price": 50000, "timestamp": ...}
```

---

## Job & Status Keys

### Job Information
**Pattern**: `{exchange}:job:{user_id}`
**Type**: Hash
**Module**: GRID (redis_database.py)
**Purpose**: Track Celery job status

**Fields**:
- `job_id`: Celery task ID
- `status`: "running" | "stopped" | "failed"
- `start_time`: ISO timestamp

**Example**:
```python
await redis.hgetall("okx:job:12345")
```

---

### Bot Status
**Pattern**: `user:{user_id}:bot:status`
**Type**: String
**Module**: position-order-service (active_user_manager.py)
**Purpose**: Track bot enabled/disabled status

**Values**: "enabled" | "disabled"

**Example**:
```python
await redis.get("user:12345:bot:status")
```

---

### Bot Exchanges
**Pattern**: `user:{user_id}:bot:exchanges`
**Type**: Set
**Module**: position-order-service (active_user_manager.py)
**Purpose**: Track which exchanges to monitor

**Example**:
```python
await redis.smembers("user:12345:bot:exchanges")  # Returns: {"okx", "binance"}
```

---

### Running Symbols
**Pattern**: `running_symbols:{exchange}:{user_id}`
**Type**: String (JSON array)
**Module**: GRID (redis_database.py)
**Purpose**: Track currently trading symbols

**Example**:
```python
await redis.get("running_symbols:okx:12345")  # Returns: '["BTC-USDT", "ETH-USDT"]'
```

---

## Statistics Keys

### Trading Volume
**Pattern**: `{exchange}:user:{user_id}:symbol:{symbol}` (Sorted Set)
**Type**: Sorted Set (score = volume, member = date)
**Module**: GRID (redis_database.py)
**Purpose**: Track daily trading volume per symbol

**Example**:
```python
await redis.zscore("okx:user:12345:symbol:BTC-USDT", "2025-10-14")  # Returns: 1500.5
```

---

### Total Symbol Volume
**Pattern**: `{exchange}:symbol:{symbol}` (Sorted Set)
**Type**: Sorted Set (score = volume, member = date)
**Module**: GRID (redis_database.py)
**Purpose**: Track total trading volume for symbol

**Example**:
```python
await redis.zscore("okx:symbol:BTC-USDT", "2025-10-14")
```

---

### User PnL by Symbol
**Pattern**: `{exchange}:user:{user_id}:pnl:{symbol}` (Sorted Set)
**Type**: Sorted Set (score = pnl, member = date)
**Module**: GRID (redis_database.py)
**Purpose**: Track daily profit/loss per symbol

**Example**:
```python
await redis.zscore("okx:user:12345:pnl:BTC-USDT", "2025-10-14")  # Returns: 250.75
```

---

### Total Symbol PnL
**Pattern**: `{exchange}:pnl:{symbol}` (Sorted Set)
**Type**: Sorted Set (score = pnl, member = date)
**Module**: GRID (redis_database.py)
**Purpose**: Track total profit/loss for symbol

**Example**:
```python
await redis.zscore("okx:pnl:BTC-USDT", "2025-10-14")
```

---

## Legacy/Deprecated Keys

### User Position (Old Pattern) - ✅ Removed Phase 1
**Pattern**: `user:{user_id}:position:{symbol}:{side}`
**Module**: HYPERRSI (trading_cache.py, remove_position)
**Status**: ✅ **Removed** (2025-10-14)
**Migration**: Use `position:{user_id}:{exchange}:{symbol}:{side}` instead

**Migration Script**:
```bash
python scripts/cleanup_legacy_keys.py --force
```

---

### Position Cache without Exchange/Side - ✅ Updated Phase 1
**Old Pattern**: `position:{user_id}:{symbol}`
**New Pattern**: `position:{user_id}:{exchange}:{symbol}:{side}`
**Module**: shared (trading_cache.py)
**Status**: ✅ **Updated** (2025-10-14)
**Changes**:
- Added exchange parameter (default: "okx")
- Added side parameter (required)
- Backward compatible

---

### Order Placed without Prefix - ✅ Updated Phase 1
**Old Pattern**: `{exchange}:user:{user_id}:symbol:{symbol}:order_placed`
**New Pattern**: `orders:{exchange}:user:{user_id}:symbol:{symbol}:order_placed`
**Module**: GRID (redis_database.py)
**Status**: ✅ **Updated** (2025-10-14)
**Changes**: Added `orders:` prefix for namespace organization

---

### Exchange Positions (JSON Array) - 🔧 Phase 2
**Pattern**: `{exchange}:positions:{user_id}`
**Type**: String (JSON array of all positions)
**Module**: GRID (redis_database.py, balance_service.py)
**Status**: ⚠️ **Active** - Migration script available for Phase 2

**Problems**:
- Inefficient: Must load entire array to access one position
- Concurrency: Race conditions on updates
- Memory: Wasteful for users with many positions

**Recommended Migration** (Optional):
```bash
# Phase 2 - Migrate to Hash pattern
python scripts/migrate_grid_positions.py --dry-run --exchange okx
python scripts/migrate_grid_positions.py --force --exchange okx
```

**New Pattern** (Phase 2):
- Individual Hash: `positions:{user_id}:{exchange}:{symbol}:{side}`
- Index Set: `positions:index:{user_id}:{exchange}`

---

## System Keys

### Default Settings
**Pattern**: `{exchange}:default_settings`
**Type**: Hash
**Module**: GRID (redis_database.py)
**Purpose**: Store system-wide default settings

**Example**:
```python
await redis.hgetall("okx:default_settings")
```

---

### Global Blacklist
**Pattern**: `{exchange}:global_blacklist`
**Type**: Set
**Module**: GRID (redis_database.py)
**Purpose**: System-wide blocked symbols

**Example**:
```python
await redis.smembers("okx:global_blacklist")
```

---

### Global Whitelist
**Pattern**: `{exchange}:global_whitelist`
**Type**: Set
**Module**: GRID (redis_database.py)
**Purpose**: System-wide allowed symbols

**Example**:
```python
await redis.smembers("okx:global_whitelist")
```

---

### User Blacklist
**Pattern**: `{exchange}:blacklist:{user_id}`
**Type**: Set
**Module**: GRID (redis_database.py)
**Purpose**: User-specific blocked symbols

**Example**:
```python
await redis.sadd("okx:blacklist:12345", "DOGE-USDT")
```

---

### User Whitelist
**Pattern**: `{exchange}:whitelist:{user_id}`
**Type**: Set
**Module**: GRID (redis_database.py)
**Purpose**: User-specific allowed symbols

**Example**:
```python
await redis.sadd("okx:whitelist:12345", "BTC-USDT")
```

---

### Last Update Timestamp
**Pattern**: `{exchange}:last_update`
**Type**: String (Unix timestamp)
**Module**: GRID (redis_database.py)
**Purpose**: Track system initialization/update time

**Example**:
```python
await redis.get("okx:last_update")
```

---

### Next User ID Counter
**Pattern**: `{exchange}:next_user_id`
**Type**: Integer (auto-increment)
**Module**: GRID (redis_database.py)
**Purpose**: Generate unique user IDs

**Example**:
```python
new_id = await redis.incr("okx:next_user_id")
```

---

### Job Table Initialization
**Pattern**: `{exchange}:job_table_initialized`
**Type**: String ("true")
**Module**: GRID (redis_database.py)
**Purpose**: Track if job table is initialized

---

## Key Naming Conventions

### Prefixes by Module

| Module | Prefix Pattern | Example |
|--------|----------------|---------|
| HYPERRSI | `user:{user_id}:*` | `user:12345:settings` |
| GRID | `{exchange}:user:{user_id}:*` | `okx:user:12345:*` |
| Shared | `positions:*`, `orders:*` | `positions:12345:okx:BTC-USDT:long` |
| Position Service | `user:{user_id}:bot:*` | `user:12345:bot:status` |

### Separator Usage
- `:` - Primary key component separator
- `_` - Word separator within components
- No spaces allowed in keys

### Exchange Names
- `okx`, `okx_spot`
- `binance`, `binance_spot`
- `upbit`
- `bitget`, `bitget_spot`
- `bybit`, `bybit_spot`

---

## Data Types Summary

| Type | Usage | Example Keys |
|------|-------|--------------|
| **Hash** | Structured data | `user:*:settings`, `positions:*`, `orders:*` |
| **Set** | Unique collections | `positions:index:*`, `*:user_ids`, `*:blacklist:*` |
| **Sorted Set** | Ranked/scored data | `*:pnl:*`, `*:symbol:*` (volume) |
| **String** | Simple values | `websocket:*:status`, `price:*` |
| **List** | Ordered sequences | `*:order_ids` |

---

## TTL Policies

| Key Pattern | TTL | Purpose |
|-------------|-----|---------|
| `position:{user_id}:{symbol}` | 300s | Short-term position cache |
| `order:{order_id}` | 3600s | Order cache |
| `price:*` | 60s | Real-time price data |
| User settings (local cache) | 30s | Reduce Redis load |
| Most other keys | Persistent | Long-term storage |

---

## Migration Notes

### Phase 1 Migrations (Completed ✅ 2025-10-14)

#### 1. Position Cache Keys
**Old Pattern**:
```python
# Missing exchange and side
key = f"position:{user_id}:{symbol}"

# Legacy user:position pattern
key = f"user:{user_id}:position:{symbol}:{side}"
```

**New Pattern**:
```python
key = f"position:{user_id}:{exchange}:{symbol}:{side}"
```

**API Changes**:
```python
# Old (no longer works)
await trading_cache.set_position(user_id, symbol, data)

# New (backward compatible)
await trading_cache.set_position(user_id, symbol, side, data, exchange="okx")
```

**Migration Steps**:
1. ✅ Code updated with new signatures
2. ✅ Backward compatibility maintained
3. ✅ Legacy keys cleaned up
4. ✅ Validation script created

#### 2. Order Placed Keys
**Old Pattern**:
```python
key = f"{exchange}:user:{user_id}:symbol:{symbol}:order_placed"
```

**New Pattern**:
```python
key = f"orders:{exchange}:user:{user_id}:symbol:{symbol}:order_placed"
```

**Migration Steps**:
1. ✅ Updated `get_order_placed()`, `set_order_placed()`, `upload_order_placed()`
2. ✅ Aligned with `order_service.py` patterns
3. ✅ Namespace organization improved

### Phase 2 Migrations (Optional 🔧)

#### GRID Position Storage
**Current Pattern**: JSON array at `{exchange}:positions:{user_id}`
**Target Pattern**: Individual Hash per position

**Benefits**:
- Faster individual position access
- Safer concurrent updates
- Better memory efficiency

**Migration Script**:
```bash
python scripts/migrate_grid_positions.py --dry-run
python scripts/migrate_grid_positions.py --force
```

See [REDIS_MIGRATION_GUIDE.md](./REDIS_MIGRATION_GUIDE.md) for detailed instructions.

### GRID to Shared Migration

GRID strategy can optionally transition from flat key structure to hierarchical shared schema. Both patterns currently coexist for backward compatibility.

**Migration Resources**:
- [REDIS_KEY_INCONSISTENCIES.md](./REDIS_KEY_INCONSISTENCIES.md) - Problem analysis
- [REDIS_KEY_STANDARDIZATION_SUMMARY.md](./REDIS_KEY_STANDARDIZATION_SUMMARY.md) - Implementation summary
- [REDIS_MIGRATION_GUIDE.md](./REDIS_MIGRATION_GUIDE.md) - Step-by-step guide

---

## Best Practices

### Key Design
1. **Start with entity type**: `user:`, `positions:`, `orders:`
2. **Add hierarchical identifiers**: `{user_id}`, `{exchange}`, `{symbol}`
3. **End with specific attribute**: `settings`, `status`, `active_grid`

### Performance
1. Use **Hash** for multi-field entities (positions, orders)
2. Use **Sets** for membership tests (active users, watchlists)
3. Use **Sorted Sets** for time-series or ranked data (PnL, volume)
4. Implement **local caching** for frequently accessed data

### Maintenance
1. Set **TTL** for temporary data (cache, prices)
2. Use **pipelines** for bulk operations
3. Implement **connection pooling** (shared.database.redis)
4. Monitor **key expiration** and cleanup

---

## Connection Management

### Shared Connection Pool
```python
from shared.database.redis import get_redis

redis = await get_redis()
await redis.set("key", "value")
```

### GRID Legacy (Deprecated)
```python
from GRID.core.redis import get_redis_connection

redis = await get_redis_connection()
await redis.close()  # Manual cleanup required
```

### HYPERRSI Service
```python
from HYPERRSI.src.services.redis_service import redis_service

settings = await redis_service.get_user_settings(user_id)
```

---

## Monitoring & Debugging

### Check Key Existence
```bash
redis-cli EXISTS "user:12345:settings"
```

### List Keys by Pattern
```bash
redis-cli KEYS "okx:user:*"
```

### Get Key Type
```bash
redis-cli TYPE "positions:12345:okx:BTC-USDT:long"
```

### Monitor Real-time Commands
```bash
redis-cli MONITOR
```

### Count Keys by Pattern
```bash
redis-cli --scan --pattern "positions:*" | wc -l
```

---

## Related Documentation

- [Redis Migration Report](./REDIS_MIGRATION_REPORT.md) - Migration from legacy to shared infrastructure
- [Redis Quick Reference](./REDIS_QUICK_REFERENCE.md) - Common operations and patterns
- [Architecture Guide](./ARCHITECTURE.md) - Overall system architecture
- [shared/database/redis_schemas.py](./shared/database/redis_schemas.py) - Schema definitions

---

## Contributing

When adding new Redis keys:

1. Follow existing naming conventions
2. Document the key pattern in this file
3. Add to appropriate category
4. Specify data type and TTL
5. Provide usage example
6. Update related modules documentation

---

**End of Redis Keys Documentation**
