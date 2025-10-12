"""
Improved Type Definitions - Python 3.12+ Features

Uses modern Python typing features:
- PEP 695: Type Parameter Syntax
- PEP 692: TypedDict for better kwargs typing
- Generic type improvements
"""

from datetime import datetime
from typing import Literal, Optional, Protocol, TypedDict, Unpack

# ============================================
# Trading Types with TypedDict (PEP 692)
# ============================================

class OrderParams(TypedDict, total=False):
    """Type-safe order parameters using TypedDict"""
    order_type: Literal['market', 'limit', 'stop', 'stop_limit']
    price: Optional[float]
    stop_price: Optional[float]
    time_in_force: Literal['GTC', 'IOC', 'FOK']
    reduce_only: bool
    post_only: bool
    client_order_id: Optional[str]


class PositionParams(TypedDict, total=False):
    """Type-safe position parameters"""
    leverage: float
    margin_mode: Literal['isolated', 'cross']
    position_side: Literal['long', 'short', 'both']
    stop_loss: Optional[float]
    take_profit: Optional[float]


class TPSLSettings(TypedDict, total=False):
    """Take Profit / Stop Loss settings"""
    tp_option: Literal['fixed', 'atr', 'dynamic']
    sl_option: Literal['fixed', 'atr', 'dynamic']
    tp_percentage: float
    sl_percentage: float
    atr_multiplier: float
    trailing_stop: bool
    break_even_enabled: bool


class UserSettings(TypedDict, total=False):
    """Complete user settings with all optional fields"""
    direction: Literal['long', 'short', 'both']
    leverage: float
    position_size: float
    entry_option: str
    tp_sl_option: str
    pyramiding_type: str
    max_pyramiding: int
    rsi_period: int
    rsi_oversold: int
    rsi_overbought: int


# ============================================
# Generic Protocol for Exchange Clients
# ============================================

class ExchangeClient(Protocol):
    """Protocol for exchange client interface"""

    async def fetch_balance(self) -> dict:
        """Fetch account balance"""
        ...

    async def fetch_positions(self, symbols: Optional[list[str]] = None) -> list[dict]:
        """Fetch open positions"""
        ...

    async def create_order(
        self,
        symbol: str,
        type: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        params: Optional[dict] = None
    ) -> dict:
        """Create order"""
        ...

    async def cancel_order(self, order_id: str, symbol: str) -> dict:
        """Cancel order"""
        ...


# ============================================
# Result Types with Generic Type Parameters
# ============================================

class OrderResult[T]:
    """
    Generic order result container using PEP 695 type parameter syntax

    Example:
        result: OrderResult[dict] = OrderResult(
            success=True,
            data={'order_id': '123'},
            timestamp=datetime.now()
        )
    """

    def __init__(
        self,
        success: bool,
        data: Optional[T] = None,
        error: Optional[str] = None,
        timestamp: Optional[datetime] = None
    ):
        self.success = success
        self.data = data
        self.error = error
        self.timestamp = timestamp or datetime.now()

    def __repr__(self) -> str:
        return f"OrderResult(success={self.success}, data={self.data}, error={self.error})"


class PositionResult[T]:
    """
    Generic position result container

    Example:
        result: PositionResult[Position] = PositionResult(
            success=True,
            position=Position(...),
            message="Position opened successfully"
        )
    """

    def __init__(
        self,
        success: bool,
        position: Optional[T] = None,
        message: Optional[str] = None,
        timestamp: Optional[datetime] = None
    ):
        self.success = success
        self.position = position
        self.message = message
        self.timestamp = timestamp or datetime.now()


# ============================================
# Type-Safe Function Signatures
# ============================================

def create_order_with_params(
    symbol: str,
    side: Literal['buy', 'sell'],
    amount: float,
    **params: Unpack[OrderParams]
) -> OrderResult[dict]:
    """
    Type-safe order creation using TypedDict unpack

    Example:
        result = create_order_with_params(
            'BTC-USDT-SWAP',
            'buy',
            1.0,
            order_type='limit',
            price=50000.0,
            time_in_force='GTC'
        )
    """
    raise NotImplementedError("This function is a type example and not implemented")


def open_position_with_settings(
    user_id: str,
    symbol: str,
    **settings: Unpack[UserSettings]
) -> PositionResult[dict]:
    """
    Type-safe position opening with user settings

    Example:
        result = open_position_with_settings(
            'user123',
            'ETH-USDT-SWAP',
            direction='long',
            leverage=10.0,
            position_size=100.0
        )
    """
    raise NotImplementedError("This function is a type example and not implemented")


# ============================================
# Cache Key Types
# ============================================

class CacheKey(TypedDict):
    """Redis cache key structure"""
    prefix: str
    user_id: str
    resource: str
    identifier: Optional[str]


def build_cache_key(**parts: Unpack[CacheKey]) -> str:
    """
    Build type-safe cache key

    Example:
        key = build_cache_key(
            prefix='user',
            user_id='123',
            resource='position',
            identifier='BTC-USDT-SWAP'
        )
        # Returns: 'user:123:position:BTC-USDT-SWAP'
    """
    key_parts = [parts['prefix'], parts['user_id'], parts['resource']]
    identifier = parts.get('identifier')
    if identifier:
        key_parts.append(identifier)
    return ':'.join(key_parts)


# ============================================
# API Response Types
# ============================================

class APIResponse[T](TypedDict):
    """Generic API response structure"""
    status: Literal['success', 'error']
    data: Optional[T]
    error: Optional[str]
    timestamp: str


class TradingAPIResponse(APIResponse[dict]):
    """Trading-specific API response"""
    execution_time_ms: float
    rate_limit_remaining: int


# ============================================
# Connection Pool Types
# ============================================

class PoolMetrics(TypedDict):
    """Connection pool metrics"""
    total_clients: int
    in_use_clients: int
    available_clients: int
    created_count: int
    released_count: int
    error_count: int
    avg_wait_time_ms: float


class ClientMetadata(TypedDict):
    """Client metadata for tracking"""
    created_at: float
    last_used: float
    use_count: int
    error_count: int
    health_check_passed: bool


# ============================================
# Example Usage
# ============================================

if __name__ == "__main__":
    # Example 1: Type-safe order parameters
    order_params: OrderParams = {
        'order_type': 'limit',
        'price': 50000.0,
        'time_in_force': 'GTC',
        'reduce_only': False
    }

    # Example 2: Generic result type
    result: OrderResult[dict] = OrderResult(
        success=True,
        data={'order_id': '12345', 'status': 'filled'}
    )

    # Example 3: Type-safe cache key
    key = build_cache_key(
        prefix='user',
        user_id='123',
        resource='settings',
        identifier=None
    )
    print(f"Cache key: {key}")

    # Example 4: Pool metrics
    metrics: PoolMetrics = {
        'total_clients': 10,
        'in_use_clients': 5,
        'available_clients': 5,
        'created_count': 15,
        'released_count': 10,
        'error_count': 2,
        'avg_wait_time_ms': 23.5
    }
    print(f"Pool metrics: {metrics}")
