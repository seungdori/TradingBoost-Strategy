# 통합 Position/Order Manager 사용 예제

## 기본 사용법

### 1. Position Manager 초기화

```python
from shared.services.position_manager import PositionManager
from shared.exchange_apis.exchange_store import ExchangeStore
from shared.database import RedisConnectionManager
from shared.models.trading import Exchange, PositionSide
from decimal import Decimal

# Dependencies 초기화
exchange_store = ExchangeStore()
redis_manager = RedisConnectionManager(host="localhost", port=6379, db=0)
redis_client = await redis_manager.get_connection_async(decode_responses=True)

# Position Manager 생성
position_manager = PositionManager(
    exchange_store=exchange_store,
    redis_client=redis_client
)
```

### 2. 포지션 오픈

```python
# 롱 포지션 오픈
position = await position_manager.open_position(
    user_id="user123",
    exchange=Exchange.OKX,
    symbol="BTC-USDT-SWAP",
    side=PositionSide.LONG,
    size=Decimal("0.1"),
    leverage=10,
    stop_loss=Decimal("44000"),
    take_profit=Decimal("46000"),
    metadata={
        "strategy": "HYPERRSI",
        "signal_strength": 0.85
    }
)

print(f"Position opened: {position.id}")
print(f"Entry price: {position.entry_price}")
print(f"Notional value: {position.notional_value}")
```

### 3. 포지션 조회

```python
# 특정 사용자의 모든 포지션 조회
positions = await position_manager.get_positions(
    user_id="user123",
    exchange=Exchange.OKX
)

for pos in positions:
    print(f"{pos.symbol}: {pos.side.value} {pos.size} @ {pos.entry_price}")
    print(f"  PnL: {pos.pnl_info.net_pnl}")
    print(f"  Status: {pos.status.value}")

# 특정 심볼 포지션만 조회
btc_positions = await position_manager.get_positions(
    user_id="user123",
    exchange=Exchange.OKX,
    symbol="BTC-USDT-SWAP"
)
```

### 4. PnL 계산

```python
# 실시간 PnL 계산
current_price = Decimal("45500")
pnl_info = await position_manager.calculate_pnl(
    position=position,
    current_price=current_price
)

print(f"Unrealized PnL: {pnl_info.unrealized_pnl} USDT")
print(f"PnL %: {position.pnl_percentage}%")
print(f"Net PnL (after fees): {pnl_info.net_pnl} USDT")
```

### 5. 포지션 청산

```python
# 전체 청산
success = await position_manager.close_position(
    position_id=str(position.id),
    reason="take_profit"
)

# 부분 청산 (50%)
success = await position_manager.close_position(
    position_id=str(position.id),
    size=position.size * Decimal("0.5"),
    reason="partial_profit"
)
```

## HYPERRSI 전략 통합 예제

### FastAPI Endpoint 리팩토링

```python
# HYPERRSI/src/api/routes/position_v2.py
from fastapi import APIRouter, Depends, HTTPException
from shared.services.position_manager import PositionManager
from shared.models.trading import Position, PositionSide, Exchange
from shared.dtos.trading import OpenPositionRequest, PositionResponse
from decimal import Decimal

router = APIRouter(prefix="/position/v2", tags=["Position V2"])

async def get_position_manager() -> PositionManager:
    """Dependency injection"""
    exchange_store = ExchangeStore()
    redis_client = await get_redis_connection()
    return PositionManager(exchange_store, redis_client)

@router.post("/open", response_model=PositionResponse)
async def open_position_v2(
    req: OpenPositionRequest,
    manager: PositionManager = Depends(get_position_manager)
):
    """통합 Position Manager를 사용한 포지션 오픈"""
    try:
        position = await manager.open_position(
            user_id=req.user_id,
            exchange=Exchange.OKX,
            symbol=req.symbol,
            side=PositionSide.LONG if req.direction == "long" else PositionSide.SHORT,
            size=Decimal(str(req.size)),
            leverage=int(req.leverage),
            stop_loss=Decimal(str(req.stop_loss)) if req.stop_loss else None,
            take_profit=Decimal(str(req.take_profit[0])) if req.take_profit else None,
            metadata={
                "is_DCA": req.is_DCA,
                "is_hedge": req.is_hedge,
                "hedge_tp_price": req.hedge_tp_price,
                "hedge_sl_price": req.hedge_sl_price,
                "strategy": "HYPERRSI"
            }
        )

        return PositionResponse(
            symbol=position.symbol,
            side=position.side.value,
            size=float(position.size),
            entry_price=float(position.entry_price),
            leverage=position.leverage,
            sl_price=float(position.stop_loss_price) if position.stop_loss_price else None,
            tp_prices=[float(position.take_profit_price)] if position.take_profit_price else None,
            order_id=position.metadata.get("entry_order_id"),
            last_filled_price=float(position.entry_price)
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{user_id}", response_model=List[PositionResponse])
async def get_positions_v2(
    user_id: str,
    symbol: Optional[str] = None,
    manager: PositionManager = Depends(get_position_manager)
):
    """사용자 포지션 조회"""
    positions = await manager.get_positions(
        user_id=user_id,
        exchange=Exchange.OKX,
        symbol=symbol
    )

    return [
        PositionResponse(
            symbol=pos.symbol,
            side=pos.side.value,
            size=float(pos.size),
            entry_price=float(pos.entry_price),
            leverage=pos.leverage,
            sl_price=float(pos.stop_loss_price) if pos.stop_loss_price else None,
            tp_prices=[float(pos.take_profit_price)] if pos.take_profit_price else None,
            order_id=pos.metadata.get("entry_order_id")
        )
        for pos in positions
    ]
```

## GRID 전략 통합 예제

### 그리드 레벨별 포지션 관리

```python
# GRID/strategies/grid_manager.py
from shared.services.position_manager import PositionManager
from shared.models.trading import Position, PositionSide, Exchange
from decimal import Decimal
import asyncio

class GridPositionManager:
    """GRID 전략에 특화된 Position Manager 래퍼"""

    def __init__(self, exchange_name: str, user_id: str, symbol: str):
        self.exchange_name = exchange_name
        self.user_id = str(user_id)
        self.symbol = symbol
        self.manager = None  # 초기화 필요

    async def initialize(self):
        """Manager 초기화"""
        from shared.exchange_apis.exchange_store import ExchangeStore
        from shared.database import RedisConnectionManager

        exchange_store = ExchangeStore()
        redis_manager = RedisConnectionManager()
        redis_client = await redis_manager.get_connection_async(decode_responses=True)

        self.manager = PositionManager(exchange_store, redis_client)

    async def open_grid_position(
        self,
        grid_level: int,
        entry_price: Decimal,
        position_size: Decimal,
        side: PositionSide = PositionSide.LONG
    ) -> Position:
        """그리드 레벨에 포지션 오픈"""
        return await self.manager.open_position(
            user_id=self.user_id,
            exchange=Exchange[self.exchange_name.upper()],
            symbol=self.symbol,
            side=side,
            size=position_size,
            leverage=10,
            grid_level=grid_level,  # GRID 전용 필드
            metadata={
                "strategy": "GRID",
                "grid_level": grid_level,
                "grid_type": "long" if side == PositionSide.LONG else "short"
            }
        )

    async def get_grid_positions(self) -> Dict[int, Position]:
        """그리드 레벨별 포지션 조회"""
        positions = await self.manager.get_positions(
            user_id=self.user_id,
            exchange=Exchange[self.exchange_name.upper()],
            symbol=self.symbol
        )

        # 그리드 레벨별로 매핑
        grid_positions = {}
        for pos in positions:
            if pos.grid_level is not None:
                grid_positions[pos.grid_level] = pos

        return grid_positions

    async def close_grid_level(self, grid_level: int) -> bool:
        """특정 그리드 레벨 포지션 청산"""
        grid_positions = await self.get_grid_positions()

        if grid_level not in grid_positions:
            return False

        position = grid_positions[grid_level]
        return await self.manager.close_position(
            position_id=str(position.id),
            reason=f"grid_level_{grid_level}_close"
        )

    async def rebalance_grid(self, target_levels: List[int], position_size: Decimal):
        """그리드 리밸런싱"""
        current_positions = await self.get_grid_positions()
        current_levels = set(current_positions.keys())
        target_levels_set = set(target_levels)

        # 닫아야 할 레벨
        levels_to_close = current_levels - target_levels_set
        # 새로 열어야 할 레벨
        levels_to_open = target_levels_set - current_levels

        # 비동기 병렬 처리
        tasks = []

        # 포지션 청산
        for level in levels_to_close:
            tasks.append(self.close_grid_level(level))

        # 새 포지션 오픈
        for level in levels_to_open:
            # 그리드 레벨에 해당하는 가격 계산 (예시)
            entry_price = self._calculate_grid_price(level)
            tasks.append(
                self.open_grid_position(level, entry_price, position_size)
            )

        # 모든 작업 동시 실행
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 에러 처리
        errors = [r for r in results if isinstance(r, Exception)]
        if errors:
            print(f"Rebalance errors: {errors}")

        return len(errors) == 0

    def _calculate_grid_price(self, level: int) -> Decimal:
        """그리드 레벨에 따른 가격 계산 (로직 예시)"""
        # 실제 GRID 전략 로직 구현 필요
        base_price = Decimal("45000")
        grid_spacing = Decimal("500")
        return base_price + (grid_spacing * Decimal(str(level - 10)))


# 사용 예제
async def main():
    grid_manager = GridPositionManager(
        exchange_name="okx",
        user_id="123456",
        symbol="BTC-USDT-SWAP"
    )
    await grid_manager.initialize()

    # 그리드 레벨 0-20에 포지션 오픈
    tasks = []
    for level in range(21):
        entry_price = Decimal("45000") + (Decimal("500") * Decimal(str(level - 10)))
        position_size = Decimal("0.01")
        tasks.append(
            grid_manager.open_grid_position(level, entry_price, position_size)
        )

    positions = await asyncio.gather(*tasks)
    print(f"Opened {len(positions)} grid positions")

    # 그리드 포지션 조회
    grid_positions = await grid_manager.get_grid_positions()
    for level, pos in grid_positions.items():
        print(f"Level {level}: {pos.size} @ {pos.entry_price}")
```

## Order Manager 사용 예제

### 1. Order Manager 초기화

```python
from shared.services.order_manager import OrderManager
from shared.models.trading import OrderSide, OrderType, OrderStatus

# Order Manager 생성
order_manager = OrderManager(
    exchange_store=exchange_store,
    redis_client=redis_client
)
```

### 2. 주문 생성

```python
# 지정가 주문
limit_order = await order_manager.create_order(
    user_id="user123",
    exchange=Exchange.OKX,
    symbol="BTC-USDT-SWAP",
    side=OrderSide.BUY,
    order_type=OrderType.LIMIT,
    quantity=Decimal("0.1"),
    price=Decimal("45000"),
    post_only=True  # Maker-only
)

# 시장가 주문
market_order = await order_manager.create_order(
    user_id="user123",
    exchange=Exchange.OKX,
    symbol="BTC-USDT-SWAP",
    side=OrderSide.SELL,
    order_type=OrderType.MARKET,
    quantity=Decimal("0.1"),
    reduce_only=True  # 포지션 청산만
)

# 손절 주문 (Trigger)
stop_loss_order = await order_manager.create_order(
    user_id="user123",
    exchange=Exchange.OKX,
    symbol="BTC-USDT-SWAP",
    side=OrderSide.SELL,
    order_type=OrderType.STOP_MARKET,
    quantity=Decimal("0.1"),
    trigger_price=Decimal("44000"),
    reduce_only=True
)
```

### 3. 주문 상태 모니터링

```python
# 폴링 방식
while True:
    order = await order_manager.get_order_by_id(str(limit_order.id))

    if order.status == OrderStatus.FILLED:
        print(f"Order filled at {order.avg_fill_price}")
        break
    elif order.status == OrderStatus.CANCELLED:
        print("Order was cancelled")
        break

    await asyncio.sleep(1)

# 스트리밍 방식 (더 효율적)
async for filled_order in order_manager.monitor_order_fills(
    user_id="user123",
    exchange=Exchange.OKX
):
    print(f"Order {filled_order.id} filled: {filled_order.filled_qty} @ {filled_order.avg_fill_price}")
    # 체결 후 후속 처리 (포지션 업데이트 등)
```

### 4. 주문 취소

```python
# 단일 주문 취소
success = await order_manager.cancel_order(order_id=str(limit_order.id))

# 심볼의 모든 오픈 주문 취소
open_orders = await order_manager.get_orders(
    user_id="user123",
    exchange=Exchange.OKX,
    symbol="BTC-USDT-SWAP",
    status=OrderStatus.OPEN
)

cancel_tasks = [
    order_manager.cancel_order(str(order.id))
    for order in open_orders
]
results = await asyncio.gather(*cancel_tasks, return_exceptions=True)
```

## 고급 사용 패턴

### 1. Batch Operations

```python
# 여러 심볼에 동시 포지션 오픈
symbols = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]

tasks = [
    position_manager.open_position(
        user_id="user123",
        exchange=Exchange.OKX,
        symbol=symbol,
        side=PositionSide.LONG,
        size=Decimal("0.1"),
        leverage=10
    )
    for symbol in symbols
]

positions = await asyncio.gather(*tasks, return_exceptions=True)

# 성공/실패 분리
successful = [p for p in positions if isinstance(p, Position)]
failed = [p for p in positions if isinstance(p, Exception)]

print(f"Opened {len(successful)} positions, {len(failed)} failed")
```

### 2. Error Handling

```python
from shared.errors import (
    InsufficientBalanceException,
    ExchangeException,
    ValidationException
)

try:
    position = await position_manager.open_position(...)

except InsufficientBalanceException as e:
    print(f"Not enough balance: {e.required_balance} USDT")
    # 사용자에게 입금 안내

except ExchangeException as e:
    print(f"Exchange error: {e.exchange_message}")
    # 재시도 또는 알림

except ValidationException as e:
    print(f"Validation error: {e.errors}")
    # 입력값 검증 실패

except Exception as e:
    print(f"Unexpected error: {e}")
    # 로깅 및 알림
```

### 3. Context Manager 패턴

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def trading_session(user_id: str, exchange: Exchange):
    """Trading session with automatic cleanup"""
    # Setup
    exchange_store = ExchangeStore()
    redis_manager = RedisConnectionManager()
    redis_client = await redis_manager.get_connection_async(decode_responses=True)

    position_manager = PositionManager(exchange_store, redis_client)
    order_manager = OrderManager(exchange_store, redis_client)

    try:
        yield position_manager, order_manager
    finally:
        # Cleanup
        await redis_client.close()

# 사용
async with trading_session("user123", Exchange.OKX) as (pos_mgr, ord_mgr):
    position = await pos_mgr.open_position(...)
    order = await ord_mgr.create_order(...)
```

### 4. Retry Logic

```python
from shared.utils.retry import retry_async

@retry_async(max_attempts=3, backoff=2.0, exceptions=(ExchangeException,))
async def open_position_with_retry(manager, **kwargs):
    """자동 재시도가 포함된 포지션 오픈"""
    return await manager.open_position(**kwargs)

# 사용
position = await open_position_with_retry(
    position_manager,
    user_id="user123",
    exchange=Exchange.OKX,
    symbol="BTC-USDT-SWAP",
    side=PositionSide.LONG,
    size=Decimal("0.1"),
    leverage=10
)
```

## 테스트 예제

```python
# tests/integration/test_position_manager.py
import pytest
from shared.services.position_manager import PositionManager
from shared.models.trading import Position, PositionSide, PositionStatus, Exchange
from decimal import Decimal

@pytest.mark.asyncio
async def test_position_lifecycle(position_manager, mock_exchange, mock_redis):
    """포지션 전체 라이프사이클 테스트"""

    # 1. Open position
    position = await position_manager.open_position(
        user_id="test_user",
        exchange=Exchange.OKX,
        symbol="BTC-USDT-SWAP",
        side=PositionSide.LONG,
        size=Decimal("0.1"),
        leverage=10
    )

    assert position.status == PositionStatus.OPEN
    assert position.size == Decimal("0.1")
    assert position.leverage == 10

    # 2. Verify Redis storage
    redis_key = f"positions:test_user:okx:BTC-USDT-SWAP:long"
    redis_data = await mock_redis.hgetall(redis_key)
    assert redis_data["size"] == "0.1"

    # 3. Calculate PnL
    pnl_info = await position_manager.calculate_pnl(
        position=position,
        current_price=Decimal("45500")
    )
    assert pnl_info.unrealized_pnl > 0

    # 4. Close position
    success = await position_manager.close_position(
        position_id=str(position.id),
        reason="test"
    )
    assert success

    # 5. Verify position is closed
    closed_position = await position_manager.get_position_by_id(str(position.id))
    assert closed_position.status == PositionStatus.CLOSED
```

이 예제들을 통해 통합 Position/Order Manager를 HYPERRSI와 GRID 전략에 효과적으로 적용할 수 있습니다.
