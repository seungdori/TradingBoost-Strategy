"""
Unit tests for PositionManager DCA functionality.

Tests DCA entry tracking, average price calculation, and P&L calculation
for positions with multiple entries.
"""

import pytest
from datetime import datetime, timedelta

from BACKTEST.engine.position_manager import PositionManager
from BACKTEST.models.position import Position
from BACKTEST.models.trade import TradeSide, ExitReason, Trade


class TestPositionDCAInitialization:
    """Tests for Position DCA field initialization."""

    def test_position_initialization_with_dca_fields(self):
        """Test position created with DCA fields initialized."""
        pm = PositionManager()
        position = pm.open_position(
            side=TradeSide.LONG,
            price=100.0,
            quantity=10.0,
            leverage=10,
            timestamp=datetime.now(),
            investment=100.0,
            take_profit_price=104.0,
            stop_loss_price=98.0
        )

        assert position.dca_count == 0
        assert len(position.entry_history) == 1
        assert position.initial_investment == 100.0
        assert position.total_investment == 100.0
        assert position.last_filled_price == 100.0
        assert position.dca_levels == []

    def test_position_initialization_without_investment(self):
        """Test position created without investment parameter uses initial_margin."""
        pm = PositionManager()
        position = pm.open_position(
            side=TradeSide.LONG,
            price=100.0,
            quantity=10.0,
            leverage=10,
            timestamp=datetime.now()
        )

        # investment should default to initial_margin = (100 * 10) / 10 = 100
        expected_initial_margin = (100.0 * 10.0) / 10
        assert position.initial_investment == expected_initial_margin
        assert position.total_investment == expected_initial_margin

    def test_entry_history_initial_record(self):
        """Test initial entry record structure."""
        pm = PositionManager()
        position = pm.open_position(
            side=TradeSide.LONG,
            price=100.0,
            quantity=10.0,
            leverage=10,
            timestamp=datetime.now(),
            investment=100.0,
            entry_reason="rsi_oversold"
        )

        assert len(position.entry_history) == 1
        entry = position.entry_history[0]
        assert entry['price'] == 100.0
        assert entry['quantity'] == 10.0
        assert entry['investment'] == 100.0
        assert entry['reason'] == "rsi_oversold"
        assert entry['dca_count'] == 0


class TestAddToPosition:
    """Tests for add_to_position DCA functionality."""

    def test_add_to_position_updates_average_price(self):
        """Test DCA entry updates average price correctly."""
        pm = PositionManager()

        # Initial entry
        position = pm.open_position(
            side=TradeSide.LONG,
            price=100.0,
            quantity=10.0,
            leverage=10,
            timestamp=datetime.now(),
            investment=100.0
        )

        # DCA entry
        position = pm.add_to_position(
            price=95.0,
            quantity=5.0,
            investment=50.0,
            timestamp=datetime.now(),
            reason='dca_1'
        )

        # Check updates
        assert position.dca_count == 1
        assert len(position.entry_history) == 2
        assert position.total_investment == 150.0
        assert position.last_filled_price == 95.0

        # Check average price calculation
        # (100*10 + 95*5) / (10+5) = 1475/15 = 98.33
        avg_price = position.get_average_entry_price()
        assert avg_price == pytest.approx(98.333, rel=1e-2)

        # Check total quantity
        total_qty = position.get_total_quantity()
        assert total_qty == 15.0

        # Check position fields updated
        assert position.entry_price == pytest.approx(98.333, rel=1e-2)
        assert position.quantity == 15.0

    def test_multiple_dca_entries(self):
        """Test multiple DCA entries update correctly."""
        pm = PositionManager()

        # Initial
        pm.open_position(
            side=TradeSide.LONG,
            price=100.0,
            quantity=10.0,
            leverage=10,
            timestamp=datetime.now(),
            investment=100.0
        )

        # DCA 1
        pm.add_to_position(95.0, 5.0, 50.0, datetime.now())

        # DCA 2
        pm.add_to_position(90.0, 2.5, 25.0, datetime.now())

        position = pm.current_position
        assert position.dca_count == 2
        assert len(position.entry_history) == 3
        assert position.total_investment == 175.0
        assert position.last_filled_price == 90.0

        # Average: (100*10 + 95*5 + 90*2.5) / 17.5 = 1700/17.5 = 97.14
        avg_price = position.get_average_entry_price()
        assert avg_price == pytest.approx(97.14, rel=1e-2)

        total_qty = position.get_total_quantity()
        assert total_qty == 17.5

    def test_add_to_position_no_position_raises(self):
        """Test add_to_position raises ValueError when no position exists."""
        pm = PositionManager()

        with pytest.raises(ValueError, match="Cannot add to position: no position exists"):
            pm.add_to_position(
                price=95.0,
                quantity=5.0,
                investment=50.0,
                timestamp=datetime.now()
            )

    def test_entry_history_dca_records(self):
        """Test DCA entry records added to history."""
        pm = PositionManager()

        pm.open_position(
            side=TradeSide.LONG,
            price=100.0,
            quantity=10.0,
            leverage=10,
            timestamp=datetime.now(),
            investment=100.0
        )

        pm.add_to_position(95.0, 5.0, 50.0, datetime.now(), reason='dca_level_1')
        pm.add_to_position(90.0, 2.5, 25.0, datetime.now(), reason='dca_level_2')

        position = pm.current_position
        assert len(position.entry_history) == 3

        # Check DCA records
        dca1 = position.entry_history[1]
        assert dca1['price'] == 95.0
        assert dca1['quantity'] == 5.0
        assert dca1['investment'] == 50.0
        assert dca1['reason'] == 'dca_level_1'
        assert dca1['dca_count'] == 1

        dca2 = position.entry_history[2]
        assert dca2['price'] == 90.0
        assert dca2['dca_count'] == 2


class TestClosePositionDCA:
    """Tests for close_position with DCA."""

    def test_close_position_uses_average_price(self):
        """Test trade P&L calculated from average entry price."""
        pm = PositionManager()

        # Initial entry
        pm.open_position(
            side=TradeSide.LONG,
            price=100.0,
            quantity=10.0,
            leverage=10,
            timestamp=datetime.now(),
            investment=100.0
        )

        # DCA entry
        pm.add_to_position(95.0, 5.0, 50.0, datetime.now())

        # Close at 104
        # Average entry: 98.33, Total qty: 15
        # PNL: (104 - 98.33) * 15 * 10 = 850.5
        trade = pm.close_position(
            exit_price=104.0,
            exit_reason=ExitReason.TAKE_PROFIT,
            timestamp=datetime.now()
        )

        assert trade is not None
        assert trade.entry_price == pytest.approx(98.333, rel=1e-2)
        assert trade.quantity == 15.0

        # Calculate expected PNL
        # price_diff = 104 - 98.333 = 5.667
        # gross_pnl = 5.667 * 15 * 10 = 850.05
        # fees = (98.333 * 15 * 0.0005) + (104 * 15 * 0.0005) = 7.375 + 7.8 = 15.175
        # net_pnl = 850.05 - 15.175 = 834.875
        assert trade.pnl == pytest.approx(834.875, rel=1e-1)

        assert trade.dca_count == 1
        assert len(trade.entry_history) == 2
        assert trade.total_investment == 150.0

    def test_close_position_no_dca_works(self):
        """Test close_position works for non-DCA positions."""
        pm = PositionManager()

        # Initial entry only (no DCA)
        pm.open_position(
            side=TradeSide.LONG,
            price=100.0,
            quantity=10.0,
            leverage=10,
            timestamp=datetime.now(),
            investment=100.0
        )

        trade = pm.close_position(
            exit_price=105.0,
            exit_reason=ExitReason.TAKE_PROFIT,
            timestamp=datetime.now()
        )

        assert trade is not None
        assert trade.entry_price == 100.0
        assert trade.quantity == 10.0
        assert trade.dca_count == 0
        assert len(trade.entry_history) == 1

    def test_short_position_dca(self):
        """Test DCA for short position."""
        pm = PositionManager()

        # Initial short
        pm.open_position(
            side=TradeSide.SHORT,
            price=100.0,
            quantity=10.0,
            leverage=10,
            timestamp=datetime.now(),
            investment=100.0
        )

        # DCA at higher price (adding to short as price rises)
        pm.add_to_position(105.0, 5.0, 50.0, datetime.now())

        position = pm.current_position
        # Average: (100*10 + 105*5) / 15 = 1525/15 = 101.67
        avg_price = position.get_average_entry_price()
        assert avg_price == pytest.approx(101.67, rel=1e-2)

        # Close at 95 (profit for short)
        # PNL: (101.67 - 95) * 15 * 10 = 1000.5
        trade = pm.close_position(
            exit_price=95.0,
            exit_reason=ExitReason.TAKE_PROFIT,
            timestamp=datetime.now()
        )

        assert trade.pnl > 0  # Profit
        assert trade.dca_count == 1


class TestPositionHelperMethods:
    """Tests for Position helper methods."""

    def test_get_average_entry_price_empty_history(self):
        """Test get_average_entry_price with empty history returns entry_price."""
        pm = PositionManager()
        position = pm.open_position(
            side=TradeSide.LONG,
            price=100.0,
            quantity=10.0,
            leverage=10,
            timestamp=datetime.now()
        )

        # Clear entry_history to test fallback
        position.entry_history = []
        avg_price = position.get_average_entry_price()
        assert avg_price == 100.0

    def test_get_total_quantity_empty_history(self):
        """Test get_total_quantity with empty history returns quantity."""
        pm = PositionManager()
        position = pm.open_position(
            side=TradeSide.LONG,
            price=100.0,
            quantity=10.0,
            leverage=10,
            timestamp=datetime.now()
        )

        # Clear entry_history to test fallback
        position.entry_history = []
        total_qty = position.get_total_quantity()
        assert total_qty == 10.0

    def test_get_unrealized_pnl_amount_long_profit(self):
        """Test unrealized P&L calculation for long position in profit."""
        pm = PositionManager()
        position = pm.open_position(
            side=TradeSide.LONG,
            price=100.0,
            quantity=10.0,
            leverage=10,
            timestamp=datetime.now()
        )

        # Current price 105 -> 5 profit per unit
        # PNL = 5 * 10 * 10 = 500
        pnl = position.get_unrealized_pnl_amount(105.0)
        assert pnl == pytest.approx(500.0)

    def test_get_unrealized_pnl_amount_short_profit(self):
        """Test unrealized P&L calculation for short position in profit."""
        pm = PositionManager()
        position = pm.open_position(
            side=TradeSide.SHORT,
            price=100.0,
            quantity=10.0,
            leverage=10,
            timestamp=datetime.now()
        )

        # Current price 95 -> 5 profit per unit for short
        # PNL = 5 * 10 * 10 = 500
        pnl = position.get_unrealized_pnl_amount(95.0)
        assert pnl == pytest.approx(500.0)

    def test_get_unrealized_pnl_amount_with_dca(self):
        """Test unrealized P&L uses average entry price with DCA."""
        pm = PositionManager()
        pm.open_position(
            side=TradeSide.LONG,
            price=100.0,
            quantity=10.0,
            leverage=10,
            timestamp=datetime.now()
        )
        pm.add_to_position(95.0, 5.0, 50.0, datetime.now())

        position = pm.current_position
        # Average: 98.33, Quantity: 15
        # Current price 104 -> 5.67 profit per unit
        # PNL = 5.67 * 15 * 10 = 850.5
        pnl = position.get_unrealized_pnl_amount(104.0)
        assert pnl == pytest.approx(850.5, rel=1e-1)

    def test_update_unrealized_pnl_uses_total_investment(self):
        """Test update_unrealized_pnl uses total_investment for percentage."""
        pm = PositionManager()
        pm.open_position(
            side=TradeSide.LONG,
            price=100.0,
            quantity=10.0,
            leverage=10,
            timestamp=datetime.now(),
            investment=100.0
        )
        pm.add_to_position(95.0, 5.0, 50.0, datetime.now())

        position = pm.current_position
        position.update_unrealized_pnl(104.0)

        # total_investment = 150
        # unrealized_pnl = 850.5
        # unrealized_pnl_percent = (850.5 / 150) * 100 = 567%
        assert position.unrealized_pnl == pytest.approx(850.5, rel=1e-1)
        assert position.unrealized_pnl_percent == pytest.approx(567.0, rel=1e-1)


class TestBackwardCompatibility:
    """Tests to ensure backward compatibility for non-DCA positions."""

    def test_open_position_without_investment_parameter(self):
        """Test open_position works without investment parameter (backward compatible)."""
        pm = PositionManager()
        position = pm.open_position(
            side=TradeSide.LONG,
            price=100.0,
            quantity=10.0,
            leverage=10,
            timestamp=datetime.now(),
            take_profit_price=104.0,
            stop_loss_price=98.0
        )

        assert position is not None
        assert position.entry_price == 100.0
        assert position.quantity == 10.0

    def test_close_position_without_dca(self):
        """Test close_position works for positions without DCA."""
        pm = PositionManager()
        pm.open_position(
            side=TradeSide.LONG,
            price=100.0,
            quantity=10.0,
            leverage=10,
            timestamp=datetime.now()
        )

        trade = pm.close_position(
            exit_price=105.0,
            exit_reason=ExitReason.TAKE_PROFIT,
            timestamp=datetime.now()
        )

        assert trade is not None
        assert trade.entry_price == 100.0
        assert trade.dca_count == 0


class TestTradeToDict:
    """Tests for Trade.to_dict() method."""

    def test_to_dict_includes_dca_metadata(self):
        """Test to_dict() includes DCA metadata fields."""
        pm = PositionManager()

        # Create position with DCA
        pm.open_position(
            side=TradeSide.LONG,
            price=100.0,
            quantity=10.0,
            leverage=10,
            timestamp=datetime.now(),
            investment=100.0,
            entry_reason="rsi_oversold"
        )
        pm.add_to_position(95.0, 5.0, 50.0, datetime.now(), reason='dca_1')

        trade = pm.close_position(
            exit_price=104.0,
            exit_reason=ExitReason.TAKE_PROFIT,
            timestamp=datetime.now()
        )

        trade_dict = trade.to_dict()

        # Verify DCA fields
        assert trade_dict['dca_count'] == 1
        assert len(trade_dict['entry_history']) == 2
        assert trade_dict['total_investment'] == 150.0

        # Verify other fields
        assert trade_dict['side'] == 'long'
        assert trade_dict['exit_reason'] == 'take_profit'
        assert trade_dict['trade_number'] == 1
        assert 'is_open' in trade_dict
        assert 'total_fees' in trade_dict

    def test_to_dict_without_dca(self):
        """Test to_dict() for non-DCA trade."""
        pm = PositionManager()

        pm.open_position(
            side=TradeSide.SHORT,
            price=100.0,
            quantity=10.0,
            leverage=10,
            timestamp=datetime.now(),
            investment=100.0
        )

        trade = pm.close_position(
            exit_price=95.0,
            exit_reason=ExitReason.STOP_LOSS,
            timestamp=datetime.now()
        )

        trade_dict = trade.to_dict()

        assert trade_dict['dca_count'] == 0
        assert len(trade_dict['entry_history']) == 1
        assert trade_dict['total_investment'] == 100.0
        assert trade_dict['side'] == 'short'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
