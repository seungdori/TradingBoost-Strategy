"""
Tests for HYPERRSI-style trailing stop functionality.

This test suite verifies the complete HYPERRSI profit-taking flow:
TP1 → TP2 → TP3 → Trailing Stop Activation → Trailing Stop Tracking → Final Exit
"""

import pytest
from datetime import datetime, timedelta

from BACKTEST.models.position import Position
from BACKTEST.models.trade import TradeSide, ExitReason
from BACKTEST.engine.position_manager import PositionManager
from BACKTEST.strategies.hyperrsi_strategy import HyperrsiStrategy


class TestTrailingStopFields:
    """Test trailing stop fields in Position model."""

    def test_position_trailing_stop_fields(self):
        """Test that Position model has trailing stop fields."""
        position = Position(
            side=TradeSide.LONG,
            entry_timestamp=datetime.now(),
            entry_price=100.0,
            quantity=1.0,
            leverage=10.0,
            initial_margin=10.0,
            # Trailing stop fields
            trailing_stop_activated=True,
            trailing_stop_price=99.5,
            trailing_offset=0.5,
            trailing_start_point=3,
            highest_price=100.5,
            lowest_price=None
        )

        assert position.trailing_stop_activated is True
        assert position.trailing_stop_price == 99.5
        assert position.trailing_offset == 0.5
        assert position.trailing_start_point == 3
        assert position.highest_price == 100.5
        assert position.lowest_price is None


class TestTrailingStopActivation:
    """Test HYPERRSI-style trailing stop activation."""

    def test_activate_trailing_stop_long(self):
        """Test activating trailing stop for LONG position."""
        position = Position(
            side=TradeSide.LONG,
            entry_timestamp=datetime.now(),
            entry_price=100.0,
            quantity=1.0,
            leverage=10.0,
            initial_margin=10.0
        )

        # Activate trailing stop at current price 105.0 with 0.5 offset
        position.activate_hyperrsi_trailing_stop(
            current_price=105.0,
            trailing_offset=0.5,
            tp_level=3
        )

        assert position.trailing_stop_activated is True
        assert position.highest_price == 105.0
        assert position.trailing_stop_price == 104.5  # 105.0 - 0.5
        assert position.trailing_offset == 0.5
        assert position.trailing_start_point == 3
        assert position.lowest_price is None  # Only used for SHORT

    def test_activate_trailing_stop_short(self):
        """Test activating trailing stop for SHORT position."""
        position = Position(
            side=TradeSide.SHORT,
            entry_timestamp=datetime.now(),
            entry_price=100.0,
            quantity=1.0,
            leverage=10.0,
            initial_margin=10.0
        )

        # Activate trailing stop at current price 95.0 with 0.5 offset
        position.activate_hyperrsi_trailing_stop(
            current_price=95.0,
            trailing_offset=0.5,
            tp_level=2
        )

        assert position.trailing_stop_activated is True
        assert position.lowest_price == 95.0
        assert position.trailing_stop_price == 95.5  # 95.0 + 0.5
        assert position.trailing_offset == 0.5
        assert position.trailing_start_point == 2
        assert position.highest_price is None  # Only used for LONG


class TestTrailingStopUpdate:
    """Test HYPERRSI-style trailing stop price updates."""

    def test_update_trailing_stop_long_price_rises(self):
        """Test trailing stop updates when LONG position price rises."""
        position = Position(
            side=TradeSide.LONG,
            entry_timestamp=datetime.now(),
            entry_price=100.0,
            quantity=1.0,
            leverage=10.0,
            initial_margin=10.0
        )

        # Activate at 105.0
        position.activate_hyperrsi_trailing_stop(
            current_price=105.0,
            trailing_offset=0.5,
            tp_level=3
        )

        initial_stop = position.trailing_stop_price
        assert initial_stop == 104.5

        # Price rises to 106.0 - stop should move up
        position.update_hyperrsi_trailing_stop(106.0)
        assert position.highest_price == 106.0
        assert position.trailing_stop_price == 105.5  # 106.0 - 0.5
        assert position.trailing_stop_price > initial_stop

        # Price rises to 107.0 - stop should move up again
        position.update_hyperrsi_trailing_stop(107.0)
        assert position.highest_price == 107.0
        assert position.trailing_stop_price == 106.5  # 107.0 - 0.5

    def test_update_trailing_stop_long_price_falls(self):
        """Test trailing stop does NOT update when LONG position price falls."""
        position = Position(
            side=TradeSide.LONG,
            entry_timestamp=datetime.now(),
            entry_price=100.0,
            quantity=1.0,
            leverage=10.0,
            initial_margin=10.0
        )

        # Activate at 105.0
        position.activate_hyperrsi_trailing_stop(
            current_price=105.0,
            trailing_offset=0.5,
            tp_level=3
        )

        # Price falls to 104.0 - stop should NOT move down
        position.update_hyperrsi_trailing_stop(104.0)
        assert position.highest_price == 105.0  # Still tracks highest
        assert position.trailing_stop_price == 104.5  # Unchanged

        # Price falls to 103.0 - stop should still NOT move
        position.update_hyperrsi_trailing_stop(103.0)
        assert position.highest_price == 105.0
        assert position.trailing_stop_price == 104.5  # Unchanged

    def test_update_trailing_stop_short_price_falls(self):
        """Test trailing stop updates when SHORT position price falls."""
        position = Position(
            side=TradeSide.SHORT,
            entry_timestamp=datetime.now(),
            entry_price=100.0,
            quantity=1.0,
            leverage=10.0,
            initial_margin=10.0
        )

        # Activate at 95.0
        position.activate_hyperrsi_trailing_stop(
            current_price=95.0,
            trailing_offset=0.5,
            tp_level=3
        )

        initial_stop = position.trailing_stop_price
        assert initial_stop == 95.5

        # Price falls to 94.0 - stop should move down
        position.update_hyperrsi_trailing_stop(94.0)
        assert position.lowest_price == 94.0
        assert position.trailing_stop_price == 94.5  # 94.0 + 0.5
        assert position.trailing_stop_price < initial_stop

        # Price falls to 93.0 - stop should move down again
        position.update_hyperrsi_trailing_stop(93.0)
        assert position.lowest_price == 93.0
        assert position.trailing_stop_price == 93.5  # 93.0 + 0.5

    def test_update_trailing_stop_short_price_rises(self):
        """Test trailing stop does NOT update when SHORT position price rises."""
        position = Position(
            side=TradeSide.SHORT,
            entry_timestamp=datetime.now(),
            entry_price=100.0,
            quantity=1.0,
            leverage=10.0,
            initial_margin=10.0
        )

        # Activate at 95.0
        position.activate_hyperrsi_trailing_stop(
            current_price=95.0,
            trailing_offset=0.5,
            tp_level=3
        )

        # Price rises to 96.0 - stop should NOT move up
        position.update_hyperrsi_trailing_stop(96.0)
        assert position.lowest_price == 95.0  # Still tracks lowest
        assert position.trailing_stop_price == 95.5  # Unchanged

        # Price rises to 97.0 - stop should still NOT move
        position.update_hyperrsi_trailing_stop(97.0)
        assert position.lowest_price == 95.0
        assert position.trailing_stop_price == 95.5  # Unchanged


class TestTrailingStopHitDetection:
    """Test trailing stop hit detection."""

    def test_trailing_stop_hit_long(self):
        """Test detecting when trailing stop is hit for LONG position."""
        position = Position(
            side=TradeSide.LONG,
            entry_timestamp=datetime.now(),
            entry_price=100.0,
            quantity=1.0,
            leverage=10.0,
            initial_margin=10.0
        )

        # Activate trailing stop
        position.activate_hyperrsi_trailing_stop(
            current_price=105.0,
            trailing_offset=0.5,
            tp_level=3
        )

        # Price at 105.0 - above stop (104.5), not hit
        assert position.check_hyperrsi_trailing_stop_hit(105.0) is False

        # Price at 104.6 - above stop, not hit
        assert position.check_hyperrsi_trailing_stop_hit(104.6) is False

        # Price at 104.5 - exactly at stop, HIT
        assert position.check_hyperrsi_trailing_stop_hit(104.5) is True

        # Price at 104.4 - below stop, HIT
        assert position.check_hyperrsi_trailing_stop_hit(104.4) is True

    def test_trailing_stop_hit_short(self):
        """Test detecting when trailing stop is hit for SHORT position."""
        position = Position(
            side=TradeSide.SHORT,
            entry_timestamp=datetime.now(),
            entry_price=100.0,
            quantity=1.0,
            leverage=10.0,
            initial_margin=10.0
        )

        # Activate trailing stop
        position.activate_hyperrsi_trailing_stop(
            current_price=95.0,
            trailing_offset=0.5,
            tp_level=3
        )

        # Price at 95.0 - below stop (95.5), not hit
        assert position.check_hyperrsi_trailing_stop_hit(95.0) is False

        # Price at 95.4 - below stop, not hit
        assert position.check_hyperrsi_trailing_stop_hit(95.4) is False

        # Price at 95.5 - exactly at stop, HIT
        assert position.check_hyperrsi_trailing_stop_hit(95.5) is True

        # Price at 95.6 - above stop, HIT
        assert position.check_hyperrsi_trailing_stop_hit(95.6) is True

    def test_trailing_stop_not_activated(self):
        """Test that hit detection returns False when trailing stop not activated."""
        position = Position(
            side=TradeSide.LONG,
            entry_timestamp=datetime.now(),
            entry_price=100.0,
            quantity=1.0,
            leverage=10.0,
            initial_margin=10.0
        )

        # Trailing stop not activated
        assert position.trailing_stop_activated is False
        assert position.check_hyperrsi_trailing_stop_hit(90.0) is False
        assert position.check_hyperrsi_trailing_stop_hit(110.0) is False


class TestTrailingStopOffsetCalculation:
    """Test trailing stop offset calculation methods."""

    def test_offset_percentage_based_long(self):
        """Test percentage-based offset calculation for LONG."""
        strategy = HyperrsiStrategy({
            "trailing_stop_active": True,
            "trailing_stop_offset_value": 0.5,  # 0.5%
            "use_trailing_stop_value_with_tp2_tp3_difference": False
        })

        offset = strategy.calculate_trailing_offset(
            side=TradeSide.LONG,
            current_price=100000.0,
            tp2_price=None,
            tp3_price=None
        )

        # 0.5% of 100,000 = 500
        assert offset == pytest.approx(500.0, rel=1e-6)

    def test_offset_percentage_based_short(self):
        """Test percentage-based offset calculation for SHORT."""
        strategy = HyperrsiStrategy({
            "trailing_stop_active": True,
            "trailing_stop_offset_value": 1.0,  # 1.0%
            "use_trailing_stop_value_with_tp2_tp3_difference": False
        })

        offset = strategy.calculate_trailing_offset(
            side=TradeSide.SHORT,
            current_price=50000.0,
            tp2_price=None,
            tp3_price=None
        )

        # 1.0% of 50,000 = 500
        assert offset == pytest.approx(500.0, rel=1e-6)

    def test_offset_tp2_tp3_difference(self):
        """Test TP2-TP3 difference offset calculation."""
        strategy = HyperrsiStrategy({
            "trailing_stop_active": True,
            "trailing_stop_offset_value": 0.5,  # Ignored when using TP2-TP3 diff
            "use_trailing_stop_value_with_tp2_tp3_difference": True
        })

        offset = strategy.calculate_trailing_offset(
            side=TradeSide.LONG,
            current_price=100000.0,
            tp2_price=103000.0,
            tp3_price=104000.0
        )

        # |104,000 - 103,000| = 1,000
        assert offset == pytest.approx(1000.0, rel=1e-6)

    def test_offset_tp2_tp3_difference_short(self):
        """Test TP2-TP3 difference offset calculation for SHORT."""
        strategy = HyperrsiStrategy({
            "trailing_stop_active": True,
            "use_trailing_stop_value_with_tp2_tp3_difference": True
        })

        offset = strategy.calculate_trailing_offset(
            side=TradeSide.SHORT,
            current_price=100000.0,
            tp2_price=97000.0,
            tp3_price=96000.0
        )

        # |96,000 - 97,000| = 1,000
        assert offset == pytest.approx(1000.0, rel=1e-6)


class TestPositionManagerTrailingStop:
    """Test PositionManager trailing stop integration."""

    def test_activate_trailing_stop_after_tp(self):
        """Test activating trailing stop after TP partial exit."""
        pm = PositionManager(fee_rate=0.0005)

        # Open position
        position = pm.open_position(
            side=TradeSide.LONG,
            price=100.0,
            quantity=1.0,
            leverage=10.0,
            timestamp=datetime.now(),
            investment=100.0,
            take_profit_price=None,
            stop_loss_price=95.0
        )

        assert position.trailing_stop_activated is False

        # Activate trailing stop after TP3
        activated = pm.activate_trailing_stop_after_tp(
            current_price=104.0,
            trailing_offset=0.5,
            tp_level=3
        )

        assert activated is True
        assert position.trailing_stop_activated is True
        assert position.highest_price == 104.0
        assert position.trailing_stop_price == 103.5
        assert position.trailing_offset == 0.5
        assert position.trailing_start_point == 3

    def test_activate_trailing_stop_already_activated(self):
        """Test that activating trailing stop twice does not override."""
        pm = PositionManager(fee_rate=0.0005)

        # Open position
        position = pm.open_position(
            side=TradeSide.LONG,
            price=100.0,
            quantity=1.0,
            leverage=10.0,
            timestamp=datetime.now(),
            investment=100.0,
            take_profit_price=None,
            stop_loss_price=95.0
        )

        # Activate once
        pm.activate_trailing_stop_after_tp(
            current_price=104.0,
            trailing_offset=0.5,
            tp_level=3
        )

        original_stop = position.trailing_stop_price

        # Try to activate again - should skip
        activated = pm.activate_trailing_stop_after_tp(
            current_price=105.0,
            trailing_offset=1.0,
            tp_level=2
        )

        assert activated is False
        assert position.trailing_stop_price == original_stop  # Unchanged

    def test_activate_trailing_stop_no_position(self):
        """Test activating trailing stop when no position exists."""
        pm = PositionManager(fee_rate=0.0005)

        # No position
        activated = pm.activate_trailing_stop_after_tp(
            current_price=104.0,
            trailing_offset=0.5,
            tp_level=3
        )

        assert activated is False


class TestCompleteHyperRSIFlow:
    """Test complete HYPERRSI flow: TP1 → TP2 → TP3 → Trailing Stop → Final Exit."""

    def test_complete_flow_long_position(self):
        """Test complete HYPERRSI profit-taking flow for LONG position."""
        pm = PositionManager(fee_rate=0.0005)

        # Open position at 100.0
        position = pm.open_position(
            side=TradeSide.LONG,
            price=100.0,
            quantity=1.0,
            leverage=10.0,
            timestamp=datetime.now(),
            investment=100.0,
            take_profit_price=None,
            stop_loss_price=95.0
        )

        # Configure partial exits + trailing stop
        position.use_tp1 = True
        position.use_tp2 = True
        position.use_tp3 = True
        position.tp1_price = 102.0
        position.tp2_price = 103.0
        position.tp3_price = 104.0
        position.tp1_ratio = 0.3
        position.tp2_ratio = 0.3
        position.tp3_ratio = 0.3  # Leave 10% for trailing stop

        # TP1 hit at 102.0 - close 30%
        trade1 = pm.partial_close_position(
            exit_price=102.0,
            timestamp=datetime.now() + timedelta(minutes=1),
            tp_level=1,
            exit_ratio=0.3
        )

        assert trade1.exit_reason == ExitReason.TP1
        assert position.remaining_quantity == pytest.approx(0.7)
        assert pm.has_position() is True

        # TP2 hit at 103.0 - close 30%
        trade2 = pm.partial_close_position(
            exit_price=103.0,
            timestamp=datetime.now() + timedelta(minutes=2),
            tp_level=2,
            exit_ratio=0.3
        )

        assert trade2.exit_reason == ExitReason.TP2
        assert position.remaining_quantity == pytest.approx(0.4)

        # TP3 hit at 104.0 - close 30%
        trade3 = pm.partial_close_position(
            exit_price=104.0,
            timestamp=datetime.now() + timedelta(minutes=3),
            tp_level=3,
            exit_ratio=0.3
        )

        assert trade3.exit_reason == ExitReason.TP3
        assert position.remaining_quantity == pytest.approx(0.1)  # 10% remaining

        # Activate trailing stop after TP3
        activated = pm.activate_trailing_stop_after_tp(
            current_price=104.0,
            trailing_offset=0.5,
            tp_level=3
        )

        assert activated is True
        assert position.trailing_stop_activated is True
        assert position.trailing_stop_price == 103.5

        # Price rises to 105.0 - trailing stop moves up
        position.update_hyperrsi_trailing_stop(105.0)
        assert position.trailing_stop_price == 104.5

        # Price rises to 106.0 - trailing stop moves up again
        position.update_hyperrsi_trailing_stop(106.0)
        assert position.trailing_stop_price == 105.5

        # Price falls to 105.5 - trailing stop hit, close remaining 10%
        assert position.check_hyperrsi_trailing_stop_hit(105.5) is True

        trade4 = pm.close_position(
            exit_price=105.5,
            timestamp=datetime.now() + timedelta(minutes=4),
            exit_reason=ExitReason.TRAILING_STOP
        )

        assert trade4.exit_reason == ExitReason.TRAILING_STOP
        assert trade4.quantity == pytest.approx(0.1)  # Final 10%
        assert pm.has_position() is False  # Position fully closed

        # Verify all trades were created
        assert len(pm.get_trade_history()) == 4

    def test_complete_flow_short_position(self):
        """Test complete HYPERRSI profit-taking flow for SHORT position."""
        pm = PositionManager(fee_rate=0.0005)

        # Open SHORT position at 100.0
        position = pm.open_position(
            side=TradeSide.SHORT,
            price=100.0,
            quantity=1.0,
            leverage=10.0,
            timestamp=datetime.now(),
            investment=100.0,
            take_profit_price=None,
            stop_loss_price=105.0
        )

        # Configure partial exits + trailing stop
        position.use_tp1 = True
        position.use_tp2 = True
        position.use_tp3 = True
        position.tp1_price = 98.0
        position.tp2_price = 97.0
        position.tp3_price = 96.0
        position.tp1_ratio = 0.3
        position.tp2_ratio = 0.3
        position.tp3_ratio = 0.3

        # TP1 hit at 98.0
        trade1 = pm.partial_close_position(
            exit_price=98.0,
            timestamp=datetime.now() + timedelta(minutes=1),
            tp_level=1,
            exit_ratio=0.3
        )
        assert trade1.exit_reason == ExitReason.TP1

        # TP2 hit at 97.0
        trade2 = pm.partial_close_position(
            exit_price=97.0,
            timestamp=datetime.now() + timedelta(minutes=2),
            tp_level=2,
            exit_ratio=0.3
        )
        assert trade2.exit_reason == ExitReason.TP2

        # TP3 hit at 96.0
        trade3 = pm.partial_close_position(
            exit_price=96.0,
            timestamp=datetime.now() + timedelta(minutes=3),
            tp_level=3,
            exit_ratio=0.3
        )
        assert trade3.exit_reason == ExitReason.TP3
        assert position.remaining_quantity == pytest.approx(0.1)

        # Activate trailing stop after TP3
        activated = pm.activate_trailing_stop_after_tp(
            current_price=96.0,
            trailing_offset=0.5,
            tp_level=3
        )

        assert activated is True
        assert position.trailing_stop_price == 96.5

        # Price falls to 95.0 - trailing stop moves down (favorable for SHORT)
        position.update_hyperrsi_trailing_stop(95.0)
        assert position.trailing_stop_price == 95.5

        # Price rises to 95.5 - trailing stop hit, close remaining
        assert position.check_hyperrsi_trailing_stop_hit(95.5) is True

        trade4 = pm.close_position(
            exit_price=95.5,
            timestamp=datetime.now() + timedelta(minutes=4),
            exit_reason=ExitReason.TRAILING_STOP
        )

        assert trade4.exit_reason == ExitReason.TRAILING_STOP
        assert pm.has_position() is False

        # Verify all trades
        assert len(pm.get_trade_history()) == 4


class TestEdgeCases:
    """Test edge cases for trailing stop."""

    def test_trailing_stop_with_zero_remaining(self):
        """Test that trailing stop is not activated if no quantity remains."""
        pm = PositionManager(fee_rate=0.0005)

        position = pm.open_position(
            side=TradeSide.LONG,
            price=100.0,
            quantity=1.0,
            leverage=10.0,
            timestamp=datetime.now(),
            investment=100.0
        )

        # Configure to close 100% with TPs
        position.use_tp1 = True
        position.use_tp2 = False
        position.use_tp3 = False
        position.tp1_price = 102.0
        position.tp1_ratio = 1.0  # 100%

        # Close entire position
        trade = pm.partial_close_position(
            exit_price=102.0,
            timestamp=datetime.now() + timedelta(minutes=1),
            tp_level=1,
            exit_ratio=1.0
        )

        assert pm.has_position() is False  # Position cleared

        # Try to activate trailing stop - should fail (no position)
        activated = pm.activate_trailing_stop_after_tp(
            current_price=102.0,
            trailing_offset=0.5,
            tp_level=1
        )

        assert activated is False

    def test_trailing_stop_with_very_small_offset(self):
        """Test trailing stop with very small offset (precision test)."""
        position = Position(
            side=TradeSide.LONG,
            entry_timestamp=datetime.now(),
            entry_price=100000.0,
            quantity=1.0,
            leverage=10.0,
            initial_margin=10000.0
        )

        # Activate with very small offset (0.01)
        position.activate_hyperrsi_trailing_stop(
            current_price=105000.0,
            trailing_offset=0.01,
            tp_level=3
        )

        assert position.trailing_stop_price == pytest.approx(104999.99, rel=1e-6)

        # Price rises slightly
        position.update_hyperrsi_trailing_stop(105000.01)
        assert position.trailing_stop_price == pytest.approx(105000.0, rel=1e-6)

    def test_trailing_stop_large_price_movements(self):
        """Test trailing stop with large price movements."""
        position = Position(
            side=TradeSide.LONG,
            entry_timestamp=datetime.now(),
            entry_price=100.0,
            quantity=1.0,
            leverage=10.0,
            initial_margin=10.0
        )

        # Activate at 110.0
        position.activate_hyperrsi_trailing_stop(
            current_price=110.0,
            trailing_offset=5.0,
            tp_level=3
        )

        assert position.trailing_stop_price == 105.0

        # Massive price jump to 150.0
        position.update_hyperrsi_trailing_stop(150.0)
        assert position.highest_price == 150.0
        assert position.trailing_stop_price == 145.0

        # Price crashes to 120.0 - stop should not move down
        position.update_hyperrsi_trailing_stop(120.0)
        assert position.highest_price == 150.0  # Still tracks highest
        assert position.trailing_stop_price == 145.0  # Unchanged
