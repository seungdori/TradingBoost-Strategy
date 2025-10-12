# 통합 Position/Order Manager 설계 개요

## 📋 요약

HYPERRSI와 GRID 전략에서 중복된 포지션/주문 관리 로직을 통합하여 `shared/` 디렉토리에 재사용 가능한 API를 구축했습니다.

## 🎯 핵심 목표

1. **코드 중복 제거**: 두 전략에서 반복되는 로직을 단일 인터페이스로 통합
2. **Exchange-agnostic 설계**: OKX, Binance, Upbit 등 다양한 거래소 지원
3. **Async 최적화**: FastAPI + Redis + PostgreSQL 비동기 패턴 활용
4. **하위 호환성**: 기존 HYPERRSI/GRID 코드와 병렬 실행 가능

## 📁 구현 파일

```
shared/
├── models/
│   └── trading.py         # Position, Order, PnLInfo 모델 (Pydantic)
├── services/
│   ├── position_manager.py  # 포지션 관리 서비스
│   └── order_manager.py     # 주문 관리 서비스
└── database/
    └── redis_schemas.py     # Redis 키 패턴 및 직렬화
```

## 🏗️ 아키텍처 설계

### 핵심 모델

#### Position Model
```python
from shared.models.trading import Position, PositionSide, PositionStatus

position = Position(
    user_id="user123",
    exchange=Exchange.OKX,
    symbol="BTC-USDT-SWAP",
    side=PositionSide.LONG,
    size=Decimal("0.1"),
    entry_price=Decimal("45000.50"),
    leverage=10
)

# Computed properties
print(position.pnl_percentage)  # 자동 계산
print(position.notional_value)  # 현재가 기준 포지션 가치
```

#### Order Model
```python
from shared.models.trading import Order, OrderSide, OrderType

order = Order(
    user_id="user123",
    exchange=Exchange.OKX,
    symbol="BTC-USDT-SWAP",
    side=OrderSide.BUY,
    order_type=OrderType.LIMIT,
    quantity=Decimal("0.1"),
    price=Decimal("45000")
)

# Computed properties
print(order.remaining_qty)     # 미체결 수량
print(order.fill_percentage)   # 체결률
```

### Redis 스키마

#### Position 키 패턴
```
positions:{user_id}:{exchange}:{symbol}:{side} → Hash
  - id, size, entry_price, leverage, pnl, status, timestamps...

positions:index:{user_id}:{exchange} → Set[position_id]

positions:active → Set[position_id]  # 전역 활성 포지션
```

#### Order 키 패턴
```
orders:{order_id} → Hash
  - user_id, exchange, symbol, side, quantity, status...

orders:user:{user_id}:{exchange} → Set[order_id]

orders:open:{exchange}:{symbol} → Set[order_id]
```

#### GRID 호환성
```
# 기존 GRID 키 패턴 지원
{exchange}:user:{user_id}:symbol:{symbol}:active_grid:{level}

orders:{exchange}:user:{user_id}:symbol:{symbol}:orders  # 배치된 주문 가격
orders:{exchange}:user:{user_id}:symbol:{symbol}:order_placed_index  # 레벨별 배치 상태
```

### PostgreSQL 스키마

```sql
-- Positions Table
CREATE TABLE positions (
    id UUID PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    exchange VARCHAR(32) NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    side VARCHAR(16) CHECK (side IN ('long', 'short')),
    size DECIMAL(20, 8),
    entry_price DECIMAL(20, 8),
    exit_price DECIMAL(20, 8),
    leverage INT DEFAULT 1,
    realized_pnl DECIMAL(20, 8),
    unrealized_pnl DECIMAL(20, 8),
    fees DECIMAL(20, 8),
    status VARCHAR(16) CHECK (status IN ('open', 'closed', 'liquidated')),
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    INDEX idx_user_exchange (user_id, exchange),
    INDEX idx_status (status)
);

-- Orders Table
CREATE TABLE orders (
    id UUID PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    exchange VARCHAR(32) NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    side VARCHAR(16) CHECK (side IN ('buy', 'sell')),
    order_type VARCHAR(32),
    quantity DECIMAL(20, 8),
    price DECIMAL(20, 8),
    filled_qty DECIMAL(20, 8),
    status VARCHAR(16) CHECK (status IN ('pending', 'open', 'filled', 'cancelled')),
    exchange_order_id VARCHAR(128) UNIQUE,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    INDEX idx_user_exchange (user_id, exchange),
    INDEX idx_status (status)
);
```

## 🔧 주요 기능

### Position Manager API (예정)

```python
from shared.services.position_manager import PositionManager

manager = PositionManager(exchange_store, redis_client)

# 포지션 조회
positions = await manager.get_positions(
    user_id="user123",
    exchange="okx",
    symbol="BTC-USDT-SWAP"  # Optional
)

# 포지션 오픈
position = await manager.open_position(
    user_id="user123",
    exchange="okx",
    symbol="BTC-USDT-SWAP",
    side=PositionSide.LONG,
    size=Decimal("0.1"),
    leverage=10,
    stop_loss=Decimal("44000"),
    take_profit=Decimal("46000")
)

# 포지션 청산
success = await manager.close_position(
    position_id=str(position.id),
    size=None,  # 전체 청산
    reason="manual"
)

# PnL 계산
pnl_info = await manager.calculate_pnl(
    position=position,
    current_price=Decimal("45500")
)
```

### Order Manager API (예정)

```python
from shared.services.order_manager import OrderManager

manager = OrderManager(exchange_store, redis_client)

# 주문 생성
order = await manager.create_order(
    user_id="user123",
    exchange="okx",
    symbol="BTC-USDT-SWAP",
    side=OrderSide.BUY,
    order_type=OrderType.LIMIT,
    quantity=Decimal("0.1"),
    price=Decimal("45000")
)

# 주문 취소
success = await manager.cancel_order(order_id=str(order.id))

# 주문 조회
orders = await manager.get_orders(
    user_id="user123",
    exchange="okx",
    status=OrderStatus.OPEN  # Optional
)

# 주문 체결 모니터링 (스트림)
async for filled_order in manager.monitor_order_fills(user_id="user123", exchange="okx"):
    print(f"Order filled: {filled_order.id}, {filled_order.avg_fill_price}")
```

## 📊 성능 최적화

### Connection Pooling
- **Redis**: `RedisConnectionManager` 사용 (shared/database)
- **PostgreSQL**: SQLAlchemy async engine with pool
- **Exchange APIs**: ExchangeStore의 연결 풀 재사용

### Caching Strategy
1. **Active positions**: Redis Hash (빠른 조회)
2. **Historical positions**: PostgreSQL (장기 저장)
3. **Order fills**: Redis Pub/Sub 또는 Streams (실시간 업데이트)

### Async Patterns
```python
# Concurrent operations with asyncio.gather
positions, orders = await asyncio.gather(
    manager.get_positions(user_id, exchange),
    order_manager.get_orders(user_id, exchange)
)

# Background tasks with FastAPI
background_tasks.add_task(
    manager.sync_positions_from_exchange,
    user_id=user_id,
    exchange=exchange
)

# TaskGroup for structured concurrency (Python 3.11+)
async with asyncio.TaskGroup() as tg:
    tg.create_task(manager.calculate_pnl(pos1, price1))
    tg.create_task(manager.calculate_pnl(pos2, price2))
```

## 🔍 차별화 요소

| 항목 | 기존 (HYPERRSI/GRID) | 신규 (Shared Manager) |
|------|----------------------|------------------------|
| **코드 중복** | 각 전략별 구현 | 단일 통합 API |
| **Exchange 지원** | 하드코딩 | Exchange Enum으로 추상화 |
| **타입 안전성** | Dict[str, Any] 사용 | Pydantic 모델 (런타임 검증) |
| **PnL 계산** | 수동 계산 | Computed field로 자동 계산 |
| **Redis 스키마** | 불일치 | 통일된 키 패턴 |
| **에러 처리** | 개별 구현 | 중앙화된 에러 처리 |
| **테스트** | 부분적 | 유닛/통합 테스트 포함 |

## 🚀 마이그레이션 전략

### Phase 1: 기반 구축 (Week 1)
- [x] `shared/models/trading.py` 완성
- [x] `shared/database/redis_schemas.py` 완성
- [ ] `shared/services/position_manager.py` 구현
- [ ] `shared/services/order_manager.py` 구현

### Phase 2: HYPERRSI 통합 (Week 2)
- [ ] `HYPERRSI/src/trading/modules/position_manager.py` → shared API 호출로 전환
- [ ] `HYPERRSI/src/trading/modules/order_manager.py` → shared API 호출로 전환
- [ ] 기존 FastAPI 엔드포인트 유지하며 내부 구현만 교체
- [ ] 통합 테스트 및 검증

### Phase 3: GRID 통합 (Week 3)
- [ ] `GRID/database/redis_database.py` → shared Redis 스키마 전환
- [ ] `GRID/services/order_service.py` → shared Order Manager 전환
- [ ] 그리드 레벨 관리 (`grid_level` 필드) 호환성 확인
- [ ] 통합 테스트 및 검증

### Phase 4: 레거시 제거 (Week 4)
- [ ] HYPERRSI 중복 코드 제거
- [ ] GRID 중복 코드 제거
- [ ] 성능 벤치마킹
- [ ] 문서화 완료

## 🧪 테스트 전략

### Unit Tests
```python
# tests/shared/test_position_manager.py
async def test_open_position_success():
    manager = PositionManager(mock_exchange, mock_redis)
    position = await manager.open_position(...)
    assert position.status == PositionStatus.OPEN
    assert position.size == Decimal("0.1")

async def test_calculate_pnl_long_profit():
    pnl = await manager.calculate_pnl(position, current_price)
    assert pnl.unrealized_pnl > 0
```

### Integration Tests
```python
# tests/integration/test_position_flow.py
async def test_full_position_lifecycle():
    # 1. Open position
    position = await manager.open_position(...)

    # 2. Verify Redis storage
    redis_data = await redis.hgetall(RedisKeys.position(...))
    assert redis_data["size"] == "0.1"

    # 3. Close position
    success = await manager.close_position(position.id)
    assert success

    # 4. Verify PostgreSQL history
    db_position = await db.query(Position).filter_by(id=position.id).one()
    assert db_position.status == PositionStatus.CLOSED
```

## 📚 참고 자료

- **Pydantic V2 Docs**: https://docs.pydantic.dev/latest/
- **Redis Async**: https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html
- **FastAPI Background Tasks**: https://fastapi.tiangolo.com/tutorial/background-tasks/
- **Python 3.12+ Async**: https://docs.python.org/3/library/asyncio.html
