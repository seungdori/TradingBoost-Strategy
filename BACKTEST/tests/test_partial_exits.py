"""
Tests for partial exits (TP1/TP2/TP3) functionality.
"""

import pytest
from datetime import datetime, timedelta

from BACKTEST.models.position import Position
from BACKTEST.models.trade import TradeSide, ExitReason
from BACKTEST.engine.position_manager import PositionManager
from BACKTEST.strategies.hyperrsi_strategy import HyperrsiStrategy


class TestPartialExits:
    """Test partial exit functionality."""

    def test_position_partial_exit_fields(self):
        """Test that Position model has partial exit fields."""
        position = Position(
            side=TradeSide.LONG,
            entry_timestamp=datetime.now(),
            entry_price=100.0,
            quantity=1.0,
            leverage=10.0,
            initial_margin=10.0,
            # Partial exit configuration
            use_tp1=True,
            use_tp2=True,
            use_tp3=True,
            tp1_price=102.0,
            tp2_price=103.0,
            tp3_price=104.0,
            tp1_ratio=0.3,
            tp2_ratio=0.3,
            tp3_ratio=0.4
        )

        assert position.use_tp1 is True
        assert position.use_tp2 is True
        assert position.use_tp3 is True
        assert position.tp1_price == 102.0
        assert position.tp2_price == 103.0
        assert position.tp3_price == 104.0
        assert position.tp1_ratio == 0.3
        assert position.tp2_ratio == 0.3
        assert position.tp3_ratio == 0.4
        assert position.tp1_filled is False
        assert position.tp2_filled is False
        assert position.tp3_filled is False

    def test_position_should_exit_partial_long(self):
        """Test should_exit_partial for LONG position."""
        position = Position(
            side=TradeSide.LONG,
            entry_timestamp=datetime.now(),
            entry_price=100.0,
            quantity=1.0,
            leverage=10.0,
            initial_margin=10.0,
            use_tp1=True,
            use_tp2=True,
            use_tp3=False,
            tp1_price=102.0,
            tp2_price=103.0,
            tp3_price=104.0,
            tp1_ratio=0.5,
            tp2_ratio=0.5,
            tp3_ratio=0.0
        )

        # Price below TP1 - no exit
        should_exit, reason, level = position.should_exit_partial(101.0)
        assert should_exit is False

        # Price hits TP1
        should_exit, reason, level = position.should_exit_partial(102.0)
        assert should_exit is True
        assert reason == "tp1"
        assert level == 1

        # Mark TP1 as filled
        position.tp1_filled = True

        # Price still at TP1 - should not trigger (already filled)
        should_exit, reason, level = position.should_exit_partial(102.0)
        assert should_exit is False

        # Price hits TP2
        should_exit, reason, level = position.should_exit_partial(103.0)
        assert should_exit is True
        assert reason == "tp2"
        assert level == 2

    def test_position_should_exit_partial_short(self):
        """Test should_exit_partial for SHORT position."""
        position = Position(
            side=TradeSide.SHORT,
            entry_timestamp=datetime.now(),
            entry_price=100.0,
            quantity=1.0,
            leverage=10.0,
            initial_margin=10.0,
            use_tp1=True,
            use_tp2=True,
            use_tp3=True,
            tp1_price=98.0,
            tp2_price=97.0,
            tp3_price=96.0,
            tp1_ratio=0.3,
            tp2_ratio=0.3,
            tp3_ratio=0.4
        )

        # Price above TP1 - no exit
        should_exit, reason, level = position.should_exit_partial(99.0)
        assert should_exit is False

        # Price hits TP1 (crosses below for SHORT)
        should_exit, reason, level = position.should_exit_partial(98.0)
        assert should_exit is True
        assert reason == "tp1"
        assert level == 1

    def test_position_manager_partial_close(self):
        """Test PositionManager.partial_close_position."""
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

        # Configure partial exits
        position.use_tp1 = True
        position.use_tp2 = True
        position.use_tp3 = True
        position.tp1_price = 102.0
        position.tp2_price = 103.0
        position.tp3_price = 104.0
        position.tp1_ratio = 0.3
        position.tp2_ratio = 0.3
        position.tp3_ratio = 0.4

        # Partial close TP1 (30%)
        trade1 = pm.partial_close_position(
            exit_price=102.0,
            timestamp=datetime.now() + timedelta(minutes=1),
            tp_level=1,
            exit_ratio=0.3
        )

        assert trade1 is not None
        assert trade1.is_partial_exit is True
        assert trade1.tp_level == 1
        assert trade1.exit_ratio == pytest.approx(0.3)
        assert trade1.quantity == pytest.approx(0.3)  # 30% of 1.0
        assert trade1.remaining_quantity == pytest.approx(0.7)
        assert trade1.exit_reason == ExitReason.TP1
        assert position.tp1_filled is True
        assert position.remaining_quantity == pytest.approx(0.7)
        assert pm.has_position() is True

        # Partial close TP2 (30%)
        trade2 = pm.partial_close_position(
            exit_price=103.0,
            timestamp=datetime.now() + timedelta(minutes=2),
            tp_level=2,
            exit_ratio=0.3
        )

        assert trade2 is not None
        assert trade2.tp_level == 2
        assert trade2.quantity == pytest.approx(0.3)  # 30% of original 1.0
        assert trade2.remaining_quantity == pytest.approx(0.4)
        assert position.tp2_filled is True
        assert position.remaining_quantity == pytest.approx(0.4)
        assert pm.has_position() is True

        # Partial close TP3 (40%) - closes remaining position
        trade3 = pm.partial_close_position(
            exit_price=104.0,
            timestamp=datetime.now() + timedelta(minutes=3),
            tp_level=3,
            exit_ratio=0.4
        )

        assert trade3 is not None
        assert trade3.tp_level == 3
        assert trade3.quantity == pytest.approx(0.4)  # Remaining 40%
        assert trade3.remaining_quantity == pytest.approx(0.0, abs=1e-8)
        assert position.tp3_filled is True
        # Position should be cleared when all quantity is closed
        assert pm.has_position() is False

        # Verify all 3 trades recorded
        history = pm.get_trade_history()
        assert len(history) == 3

    def test_strategy_calculate_tp_levels_percentage(self):
        """Test HyperrsiStrategy.calculate_tp_levels with percentage mode (default)."""
        strategy = HyperrsiStrategy(params={
            "use_tp1": True,
            "use_tp2": True,
            "use_tp3": True,
            "tp_option": "percentage",
            "tp1_value": 2.0,
            "tp2_value": 3.0,
            "tp3_value": 4.0,
            "tp1_ratio": 30,
            "tp2_ratio": 30,
            "tp3_ratio": 40
        })

        # Test LONG
        tp1, tp2, tp3 = strategy.calculate_tp_levels(TradeSide.LONG, 100.0)
        assert tp1 == pytest.approx(102.0)  # 100 * (1 + 2/100)
        assert tp2 == pytest.approx(103.0)  # 100 * (1 + 3/100)
        assert tp3 == pytest.approx(104.0)  # 100 * (1 + 4/100)

        # Test SHORT
        tp1, tp2, tp3 = strategy.calculate_tp_levels(TradeSide.SHORT, 100.0)
        assert tp1 == pytest.approx(98.0)   # 100 * (1 - 2/100)
        assert tp2 == pytest.approx(97.0)   # 100 * (1 - 3/100)
        assert tp3 == pytest.approx(96.0)   # 100 * (1 - 4/100)

    def test_strategy_calculate_tp_levels_atr_long(self):
        """Test HyperrsiStrategy.calculate_tp_levels with ATR mode for LONG."""
        strategy = HyperrsiStrategy(params={
            "use_tp1": True,
            "use_tp2": True,
            "use_tp3": True,
            "tp_option": "atr",
            "tp1_value": 1.5,  # ATR multiplier
            "tp2_value": 2.0,
            "tp3_value": 3.0,
            "tp1_ratio": 30,
            "tp2_ratio": 30,
            "tp3_ratio": 40
        })

        entry_price = 100.0
        atr_value = 2.0  # ATR = $2

        # Test LONG: entry_price + (ATR × tp_value)
        tp1, tp2, tp3 = strategy.calculate_tp_levels(
            TradeSide.LONG,
            entry_price,
            atr_value=atr_value
        )

        assert tp1 == pytest.approx(103.0)  # 100 + (2 * 1.5)
        assert tp2 == pytest.approx(104.0)  # 100 + (2 * 2.0)
        assert tp3 == pytest.approx(106.0)  # 100 + (2 * 3.0)

    def test_strategy_calculate_tp_levels_atr_short(self):
        """Test HyperrsiStrategy.calculate_tp_levels with ATR mode for SHORT."""
        strategy = HyperrsiStrategy(params={
            "use_tp1": True,
            "use_tp2": True,
            "use_tp3": True,
            "tp_option": "atr",
            "tp1_value": 1.5,
            "tp2_value": 2.0,
            "tp3_value": 3.0,
            "tp1_ratio": 30,
            "tp2_ratio": 30,
            "tp3_ratio": 40
        })

        entry_price = 100.0
        atr_value = 2.0

        # Test SHORT: entry_price - (ATR × tp_value)
        tp1, tp2, tp3 = strategy.calculate_tp_levels(
            TradeSide.SHORT,
            entry_price,
            atr_value=atr_value
        )

        assert tp1 == pytest.approx(97.0)   # 100 - (2 * 1.5)
        assert tp2 == pytest.approx(96.0)   # 100 - (2 * 2.0)
        assert tp3 == pytest.approx(94.0)   # 100 - (2 * 3.0)

    def test_strategy_calculate_tp_levels_price_long(self):
        """Test HyperrsiStrategy.calculate_tp_levels with price mode for LONG."""
        strategy = HyperrsiStrategy(params={
            "use_tp1": True,
            "use_tp2": True,
            "use_tp3": True,
            "tp_option": "price",
            "tp1_value": 2.0,  # Absolute price difference
            "tp2_value": 3.0,
            "tp3_value": 5.0,
            "tp1_ratio": 30,
            "tp2_ratio": 30,
            "tp3_ratio": 40
        })

        entry_price = 100.0

        # Test LONG: entry_price + tp_value
        tp1, tp2, tp3 = strategy.calculate_tp_levels(TradeSide.LONG, entry_price)

        assert tp1 == pytest.approx(102.0)  # 100 + 2
        assert tp2 == pytest.approx(103.0)  # 100 + 3
        assert tp3 == pytest.approx(105.0)  # 100 + 5

    def test_strategy_calculate_tp_levels_price_short(self):
        """Test HyperrsiStrategy.calculate_tp_levels with price mode for SHORT."""
        strategy = HyperrsiStrategy(params={
            "use_tp1": True,
            "use_tp2": True,
            "use_tp3": True,
            "tp_option": "price",
            "tp1_value": 2.0,
            "tp2_value": 3.0,
            "tp3_value": 5.0,
            "tp1_ratio": 30,
            "tp2_ratio": 30,
            "tp3_ratio": 40
        })

        entry_price = 100.0

        # Test SHORT: entry_price - tp_value
        tp1, tp2, tp3 = strategy.calculate_tp_levels(TradeSide.SHORT, entry_price)

        assert tp1 == pytest.approx(98.0)   # 100 - 2
        assert tp2 == pytest.approx(97.0)   # 100 - 3
        assert tp3 == pytest.approx(95.0)   # 100 - 5

    def test_strategy_calculate_tp_levels_atr_fallback(self):
        """Test ATR fallback when ATR is None or too small."""
        strategy = HyperrsiStrategy(params={
            "use_tp1": True,
            "use_tp2": True,
            "use_tp3": True,
            "tp_option": "atr",
            "tp1_value": 1.0,
            "tp2_value": 2.0,
            "tp3_value": 3.0,
            "tp1_ratio": 30,
            "tp2_ratio": 30,
            "tp3_ratio": 40
        })

        entry_price = 100.0

        # Test with None ATR - should use fallback (0.1% of entry price)
        tp1, tp2, tp3 = strategy.calculate_tp_levels(
            TradeSide.LONG,
            entry_price,
            atr_value=None
        )

        # Fallback ATR = 100 * 0.01 * 0.1 = 0.1
        assert tp1 == pytest.approx(100.1)  # 100 + (0.1 * 1.0)
        assert tp2 == pytest.approx(100.2)  # 100 + (0.1 * 2.0)
        assert tp3 == pytest.approx(100.3)  # 100 + (0.1 * 3.0)

        # Test with very small ATR - should use fallback
        tp1, tp2, tp3 = strategy.calculate_tp_levels(
            TradeSide.LONG,
            entry_price,
            atr_value=0.01  # Too small (< entry_price * 0.001 = 0.1)
        )

        assert tp1 == pytest.approx(100.1)  # Uses fallback
        assert tp2 == pytest.approx(100.2)
        assert tp3 == pytest.approx(100.3)

    def test_strategy_calculate_tp_levels_invalid_option(self):
        """Test that invalid tp_option gracefully skips TP calculation."""
        strategy = HyperrsiStrategy(params={
            "use_tp1": True,
            "use_tp2": True,
            "use_tp3": True,
            "tp_option": "invalid_mode",  # Invalid mode
            "tp1_value": 2.0,
            "tp2_value": 3.0,
            "tp3_value": 4.0,
            "tp1_ratio": 30,
            "tp2_ratio": 30,
            "tp3_ratio": 40
        })

        # Should return all None due to invalid tp_option
        tp1, tp2, tp3 = strategy.calculate_tp_levels(TradeSide.LONG, 100.0)

        assert tp1 is None
        assert tp2 is None
        assert tp3 is None

    def test_strategy_calculate_tp_levels_mixed_enabled(self):
        """Test partial TP enablement with different tp_option modes."""
        # Test with only TP1 and TP3 enabled (TP2 disabled)
        strategy = HyperrsiStrategy(params={
            "use_tp1": True,
            "use_tp2": False,
            "use_tp3": True,
            "tp_option": "atr",
            "tp1_value": 1.5,
            "tp2_value": 2.0,  # Will be ignored
            "tp3_value": 3.0,
            "tp1_ratio": 50,
            "tp2_ratio": 0,
            "tp3_ratio": 50
        })

        entry_price = 100.0
        atr_value = 2.0

        tp1, tp2, tp3 = strategy.calculate_tp_levels(
            TradeSide.LONG,
            entry_price,
            atr_value=atr_value
        )

        assert tp1 == pytest.approx(103.0)  # 100 + (2 * 1.5)
        assert tp2 is None  # Disabled
        assert tp3 == pytest.approx(106.0)  # 100 + (2 * 3.0)

    def test_strategy_partial_exit_disabled(self):
        """Test that partial exits can be disabled."""
        strategy = HyperrsiStrategy(params={
            "use_tp1": False,
            "use_tp2": False,
            "use_tp3": False
        })

        tp1, tp2, tp3 = strategy.calculate_tp_levels(TradeSide.LONG, 100.0)
        assert tp1 is None
        assert tp2 is None
        assert tp3 is None

    def test_position_all_tp_levels_filled(self):
        """Test all_tp_levels_filled check."""
        position = Position(
            side=TradeSide.LONG,
            entry_timestamp=datetime.now(),
            entry_price=100.0,
            quantity=1.0,
            leverage=10.0,
            initial_margin=10.0,
            use_tp1=True,
            use_tp2=True,
            use_tp3=True,
            tp1_price=102.0,
            tp2_price=103.0,
            tp3_price=104.0,
            tp1_ratio=0.3,
            tp2_ratio=0.3,
            tp3_ratio=0.4
        )

        assert position.all_tp_levels_filled() is False

        position.tp1_filled = True
        assert position.all_tp_levels_filled() is False

        position.tp2_filled = True
        assert position.all_tp_levels_filled() is False

        position.tp3_filled = True
        assert position.all_tp_levels_filled() is True

    def test_position_get_current_quantity(self):
        """Test get_current_quantity with partial exits."""
        position = Position(
            side=TradeSide.LONG,
            entry_timestamp=datetime.now(),
            entry_price=100.0,
            quantity=1.0,
            leverage=10.0,
            initial_margin=10.0,
            entry_history=[{
                'price': 100.0,
                'quantity': 1.0,
                'investment': 100.0,
                'timestamp': datetime.now(),
                'reason': 'initial_entry',
                'dca_count': 0
            }]
        )

        # Before any partial exits
        assert position.get_current_quantity() == 1.0

        # After partial exit
        position.remaining_quantity = 0.7
        assert position.get_current_quantity() == 0.7

        # After another partial exit
        position.remaining_quantity = 0.4
        assert position.get_current_quantity() == 0.4
