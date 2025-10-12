"""Unit Tests for Position Manager

Tests the PositionManager service with mocked dependencies.
Uses pytest-asyncio for async test support and fakeredis for Redis mocking.

Run tests:
    pytest shared/services/tests/test_position_manager.py -v
"""

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from shared.models.trading import Exchange, PnLInfo, Position, PositionSide, PositionStatus
from shared.services.position_manager import PositionManager


@pytest.fixture
async def position_manager():
    """Create Position Manager instance with mocked Redis"""
    manager = PositionManager()

    # Mock Redis connection
    mock_redis = AsyncMock()
    manager._get_redis = AsyncMock(return_value=mock_redis)

    return manager


@pytest.fixture
def sample_position_data():
    """Sample position data for testing"""
    return {
        "id": str(uuid4()),
        "user_id": "test_user",
        "exchange": "okx",
        "symbol": "BTC-USDT-SWAP",
        "side": "long",
        "size": "0.1",
        "entry_price": "45000.0",
        "current_price": "45500.0",
        "leverage": "10",
        "liquidation_price": "",
        "stop_loss_price": "",
        "take_profit_price": "",
        "realized_pnl": "0",
        "unrealized_pnl": "50.0",
        "fees": "5.0",
        "status": "open",
        "metadata": "{}",
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "closed_at": "",
        "grid_level": ""
    }


@pytest.mark.asyncio
async def test_get_positions_with_symbol_and_side(position_manager, sample_position_data):
    """Test getting positions with symbol and side filters"""
    mock_redis = await position_manager._get_redis()
    mock_redis.hgetall.return_value = sample_position_data

    positions = await position_manager.get_positions(
        user_id="test_user",
        exchange="okx",
        symbol="BTC-USDT-SWAP",
        side="long"
    )

    assert len(positions) == 1
    position = positions[0]
    assert position.symbol == "BTC-USDT-SWAP"
    assert position.side == PositionSide.LONG
    assert position.size == Decimal("0.1")


@pytest.mark.asyncio
async def test_get_positions_no_results(position_manager):
    """Test getting positions when none exist"""
    mock_redis = await position_manager._get_redis()
    mock_redis.hgetall.return_value = {}

    positions = await position_manager.get_positions(
        user_id="test_user",
        exchange="okx",
        symbol="BTC-USDT-SWAP"
    )

    assert len(positions) == 0


@pytest.mark.asyncio
async def test_get_positions_with_grid_level_filter(position_manager, sample_position_data):
    """Test getting positions filtered by grid level"""
    sample_position_data["grid_level"] = "5"
    mock_redis = await position_manager._get_redis()
    mock_redis.hgetall.return_value = sample_position_data

    # Should return position matching grid level
    positions = await position_manager.get_positions(
        user_id="test_user",
        exchange="okx",
        symbol="BTC-USDT-SWAP",
        side="long",
        grid_level=5
    )

    assert len(positions) == 1
    assert positions[0].grid_level == 5

    # Should not return position with different grid level
    positions = await position_manager.get_positions(
        user_id="test_user",
        exchange="okx",
        symbol="BTC-USDT-SWAP",
        side="long",
        grid_level=3
    )

    assert len(positions) == 0


@pytest.mark.asyncio
@patch('shared.services.position_manager.ccxt')
async def test_open_position_success(mock_ccxt, position_manager):
    """Test successfully opening a position"""
    # Mock CCXT exchange
    mock_exchange = AsyncMock()
    mock_exchange.create_market_order.return_value = {
        'id': 'order123',
        'average': 45000.0,
        'filled': 0.1
    }
    mock_ccxt.okx.return_value = mock_exchange

    # Mock Redis
    mock_redis = await position_manager._get_redis()

    # Mock API keys
    position_manager._get_user_api_keys = AsyncMock(return_value={
        'api_key': 'test_key',
        'api_secret': 'test_secret',
        'passphrase': 'test_pass'
    })

    position = await position_manager.open_position(
        user_id="test_user",
        exchange="okx",
        symbol="BTC-USDT-SWAP",
        side="long",
        size=Decimal("0.1"),
        leverage=10
    )

    # Verify position created
    assert position.symbol == "BTC-USDT-SWAP"
    assert position.side == PositionSide.LONG
    assert position.size == Decimal("0.1")
    assert position.leverage == 10
    assert position.status == PositionStatus.OPEN

    # Verify Redis calls
    assert mock_redis.hset.called
    assert mock_redis.sadd.called

    # Verify exchange client closed
    assert mock_exchange.close.called


@pytest.mark.asyncio
async def test_open_position_invalid_side(position_manager):
    """Test opening position with invalid side"""
    with pytest.raises(ValueError, match="Invalid side"):
        await position_manager.open_position(
            user_id="test_user",
            exchange="okx",
            symbol="BTC-USDT-SWAP",
            side="invalid",
            size=Decimal("0.1")
        )


@pytest.mark.asyncio
async def test_open_position_invalid_size(position_manager):
    """Test opening position with invalid size"""
    with pytest.raises(ValueError, match="Invalid size"):
        await position_manager.open_position(
            user_id="test_user",
            exchange="okx",
            symbol="BTC-USDT-SWAP",
            side="long",
            size=Decimal("0")
        )


@pytest.mark.asyncio
async def test_open_position_invalid_leverage(position_manager):
    """Test opening position with invalid leverage"""
    with pytest.raises(ValueError, match="Invalid leverage"):
        await position_manager.open_position(
            user_id="test_user",
            exchange="okx",
            symbol="BTC-USDT-SWAP",
            side="long",
            size=Decimal("0.1"),
            leverage=200  # Exceeds max leverage
        )


@pytest.mark.asyncio
@patch('shared.services.position_manager.ccxt')
async def test_close_position_full(mock_ccxt, position_manager, sample_position_data):
    """Test fully closing a position"""
    # Mock CCXT exchange
    mock_exchange = AsyncMock()
    mock_exchange.create_market_order.return_value = {
        'id': 'order456',
        'average': 46000.0,
        'filled': 0.1
    }
    mock_ccxt.okx.return_value = mock_exchange

    # Mock Redis
    mock_redis = await position_manager._get_redis()
    mock_redis.hgetall.return_value = sample_position_data

    # Mock API keys
    position_manager._get_user_api_keys = AsyncMock(return_value={
        'api_key': 'test_key',
        'api_secret': 'test_secret',
        'passphrase': 'test_pass'
    })

    success = await position_manager.close_position(
        user_id="test_user",
        exchange="okx",
        symbol="BTC-USDT-SWAP",
        side="long",
        reason="Take profit"
    )

    assert success is True

    # Verify Redis cleanup
    assert mock_redis.delete.called
    assert mock_redis.srem.called
    assert mock_redis.lpush.called  # Saved to history


@pytest.mark.asyncio
@patch('shared.services.position_manager.ccxt')
async def test_close_position_partial(mock_ccxt, position_manager, sample_position_data):
    """Test partially closing a position"""
    # Mock CCXT exchange
    mock_exchange = AsyncMock()
    mock_exchange.create_market_order.return_value = {
        'id': 'order456',
        'average': 46000.0,
        'filled': 0.05
    }
    mock_ccxt.okx.return_value = mock_exchange

    # Mock Redis
    mock_redis = await position_manager._get_redis()
    mock_redis.hgetall.return_value = sample_position_data

    # Mock API keys
    position_manager._get_user_api_keys = AsyncMock(return_value={
        'api_key': 'test_key',
        'api_secret': 'test_secret',
        'passphrase': 'test_pass'
    })

    success = await position_manager.close_position(
        user_id="test_user",
        exchange="okx",
        symbol="BTC-USDT-SWAP",
        side="long",
        size=Decimal("0.05"),  # Partial close
        reason="Partial take profit"
    )

    assert success is True

    # Verify Redis update (not delete)
    assert mock_redis.hset.called
    assert not mock_redis.delete.called


@pytest.mark.asyncio
async def test_close_position_not_found(position_manager):
    """Test closing non-existent position"""
    mock_redis = await position_manager._get_redis()
    mock_redis.hgetall.return_value = {}

    success = await position_manager.close_position(
        user_id="test_user",
        exchange="okx",
        symbol="BTC-USDT-SWAP",
        side="long"
    )

    assert success is False


@pytest.mark.asyncio
async def test_update_position(position_manager, sample_position_data):
    """Test updating position fields"""
    mock_redis = await position_manager._get_redis()
    mock_redis.hgetall.return_value = sample_position_data

    updated_position = await position_manager.update_position(
        user_id="test_user",
        exchange="okx",
        symbol="BTC-USDT-SWAP",
        side="long",
        updates={
            "current_price": Decimal("46000.0"),
            "stop_loss_price": Decimal("44000.0")
        }
    )

    assert updated_position is not None
    assert updated_position.current_price == Decimal("46000.0")
    assert updated_position.stop_loss_price == Decimal("44000.0")
    assert mock_redis.hset.called


@pytest.mark.asyncio
async def test_calculate_pnl_long(position_manager):
    """Test P&L calculation for long position"""
    position = Position(
        user_id="test_user",
        exchange=Exchange.OKX,
        symbol="BTC-USDT-SWAP",
        side=PositionSide.LONG,
        size=Decimal("0.1"),
        entry_price=Decimal("45000"),
        leverage=10
    )

    pnl_info = await position_manager.calculate_pnl(
        position=position,
        current_price=Decimal("46000")
    )

    # Expected: (46000 - 45000) * 0.1 * 10 = 100 USDT
    assert pnl_info.unrealized_pnl == Decimal("100")


@pytest.mark.asyncio
async def test_calculate_pnl_short(position_manager):
    """Test P&L calculation for short position"""
    position = Position(
        user_id="test_user",
        exchange=Exchange.OKX,
        symbol="BTC-USDT-SWAP",
        side=PositionSide.SHORT,
        size=Decimal("0.1"),
        entry_price=Decimal("46000"),
        leverage=10
    )

    pnl_info = await position_manager.calculate_pnl(
        position=position,
        current_price=Decimal("45000")
    )

    # Expected: (46000 - 45000) * 0.1 * 10 = 100 USDT (profit for short)
    assert pnl_info.unrealized_pnl == Decimal("100")


@pytest.mark.asyncio
async def test_get_positions_history(position_manager, sample_position_data):
    """Test getting position history"""
    import json

    mock_redis = await position_manager._get_redis()
    mock_redis.lrange.return_value = [
        json.dumps(sample_position_data),
        json.dumps(sample_position_data)
    ]

    history = await position_manager.get_positions_history(
        user_id="test_user",
        exchange="okx",
        limit=10
    )

    assert len(history) == 2
    assert all(isinstance(p, Position) for p in history)


@pytest.mark.asyncio
@patch('shared.services.position_manager.ccxt')
async def test_open_position_with_grid_level(mock_ccxt, position_manager):
    """Test opening position with GRID strategy support"""
    # Mock CCXT exchange
    mock_exchange = AsyncMock()
    mock_exchange.create_market_order.return_value = {
        'id': 'order123',
        'average': 45000.0,
        'filled': 0.1
    }
    mock_ccxt.okx.return_value = mock_exchange

    # Mock Redis
    mock_redis = await position_manager._get_redis()

    # Mock API keys
    position_manager._get_user_api_keys = AsyncMock(return_value={
        'api_key': 'test_key',
        'api_secret': 'test_secret',
        'passphrase': 'test_pass'
    })

    position = await position_manager.open_position(
        user_id="test_user",
        exchange="okx",
        symbol="BTC-USDT-SWAP",
        side="long",
        size=Decimal("0.05"),
        leverage=10,
        grid_level=5  # GRID strategy specific
    )

    assert position.grid_level == 5
    assert position.size == Decimal("0.05")


@pytest.mark.asyncio
@patch('shared.services.position_manager.ccxt')
async def test_open_position_retry_on_failure(mock_ccxt, position_manager):
    """Test retry logic when opening position fails"""
    # Mock CCXT exchange to fail 2 times then succeed
    mock_exchange = AsyncMock()
    mock_exchange.create_market_order.side_effect = [
        Exception("Network error"),
        Exception("Timeout"),
        {
            'id': 'order123',
            'average': 45000.0,
            'filled': 0.1
        }
    ]
    mock_ccxt.okx.return_value = mock_exchange

    # Mock Redis
    mock_redis = await position_manager._get_redis()

    # Mock API keys
    position_manager._get_user_api_keys = AsyncMock(return_value={
        'api_key': 'test_key',
        'api_secret': 'test_secret',
        'passphrase': 'test_pass'
    })

    position = await position_manager.open_position(
        user_id="test_user",
        exchange="okx",
        symbol="BTC-USDT-SWAP",
        side="long",
        size=Decimal("0.1"),
        leverage=10
    )

    # Should succeed after retries
    assert position.status == PositionStatus.OPEN
    assert mock_exchange.create_market_order.call_count == 3
