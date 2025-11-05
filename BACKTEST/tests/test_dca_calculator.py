"""
Unit tests for DCA calculation utilities.
"""

import pytest
from BACKTEST.engine.dca_calculator import (
    calculate_dca_levels,
    check_dca_condition,
    calculate_dca_entry_size,
    check_rsi_condition_for_dca,
    check_trend_condition_for_dca
)


class TestCalculateDcaLevels:
    """Tests for calculate_dca_levels function."""

    def test_percentage_based_long(self):
        """Test percentage-based DCA level for long position."""
        settings = {
            'pyramiding_entry_type': '퍼센트 기준',
            'pyramiding_value': 3.0,
            'entry_criterion': '평균 단가'
        }
        levels = calculate_dca_levels(
            entry_price=100.0,
            last_filled_price=100.0,
            settings=settings,
            side='long',
            atr_value=2.0,
            current_price=98.0
        )
        assert len(levels) == 1
        assert levels[0] == pytest.approx(97.0)  # 100 * (1 - 0.03)

    def test_percentage_based_short(self):
        """Test percentage-based DCA level for short position."""
        settings = {
            'pyramiding_entry_type': '퍼센트 기준',
            'pyramiding_value': 3.0,
            'entry_criterion': '평균 단가'
        }
        levels = calculate_dca_levels(
            entry_price=100.0,
            last_filled_price=100.0,
            settings=settings,
            side='short',
            atr_value=2.0,
            current_price=102.0
        )
        assert len(levels) == 1
        assert levels[0] == pytest.approx(103.0)  # 100 * (1 + 0.03)

    def test_fixed_amount_long(self):
        """Test fixed amount DCA level for long position."""
        settings = {
            'pyramiding_entry_type': '금액 기준',
            'pyramiding_value': 5.0,
            'entry_criterion': '평균 단가'
        }
        levels = calculate_dca_levels(
            entry_price=100.0,
            last_filled_price=100.0,
            settings=settings,
            side='long',
            atr_value=2.0,
            current_price=98.0
        )
        assert len(levels) == 1
        assert levels[0] == pytest.approx(95.0)  # 100 - 5

    def test_atr_based_long(self):
        """Test ATR-based DCA level for long position."""
        settings = {
            'pyramiding_entry_type': 'ATR 기준',
            'pyramiding_value': 2.0,
            'entry_criterion': '평균 단가'
        }
        levels = calculate_dca_levels(
            entry_price=100.0,
            last_filled_price=100.0,
            settings=settings,
            side='long',
            atr_value=2.5,
            current_price=98.0
        )
        assert len(levels) == 1
        assert levels[0] == pytest.approx(95.0)  # 100 - (2.5 * 2)

    def test_entry_criterion_recent(self):
        """Test DCA level uses last filled price when criterion is '최근 진입가'."""
        settings = {
            'pyramiding_entry_type': '퍼센트 기준',
            'pyramiding_value': 3.0,
            'entry_criterion': '최근 진입가'
        }
        levels = calculate_dca_levels(
            entry_price=100.0,
            last_filled_price=95.0,  # Different from average
            settings=settings,
            side='long',
            atr_value=2.0,
            current_price=93.0
        )
        assert len(levels) == 1
        assert levels[0] == pytest.approx(92.15)  # 95 * (1 - 0.03)


class TestCheckDcaCondition:
    """Tests for check_dca_condition function."""

    def test_long_condition_met(self):
        """Test long DCA condition met when price drops below level."""
        result = check_dca_condition(
            current_price=97.0,
            dca_levels=[98.0],
            side='long',
            use_check_DCA_with_price=True
        )
        assert result is True

    def test_long_condition_not_met(self):
        """Test long DCA condition not met when price above level."""
        result = check_dca_condition(
            current_price=99.0,
            dca_levels=[98.0],
            side='long',
            use_check_DCA_with_price=True
        )
        assert result is False

    def test_short_condition_met(self):
        """Test short DCA condition met when price rises above level."""
        result = check_dca_condition(
            current_price=103.0,
            dca_levels=[102.0],
            side='short',
            use_check_DCA_with_price=True
        )
        assert result is True

    def test_disabled_check(self):
        """Test DCA condition always passes when check disabled."""
        result = check_dca_condition(
            current_price=50.0,
            dca_levels=[100.0],
            side='long',
            use_check_DCA_with_price=False
        )
        assert result is True


class TestCalculateDcaEntrySize:
    """Tests for calculate_dca_entry_size function."""

    def test_first_dca_entry(self):
        """Test size calculation for first DCA entry."""
        investment, contracts = calculate_dca_entry_size(
            initial_investment=100.0,
            initial_contracts=10.0,
            dca_count=1,
            entry_multiplier=0.5,
            current_price=95.0,
            leverage=10
        )
        assert investment == pytest.approx(50.0)  # 100 * 0.5^1
        assert contracts == pytest.approx(5.0)    # 10 * 0.5^1

    def test_second_dca_entry(self):
        """Test size calculation for second DCA entry."""
        investment, contracts = calculate_dca_entry_size(
            initial_investment=100.0,
            initial_contracts=10.0,
            dca_count=2,
            entry_multiplier=0.5,
            current_price=90.0,
            leverage=10
        )
        assert investment == pytest.approx(25.0)  # 100 * 0.5^2
        assert contracts == pytest.approx(2.5)    # 10 * 0.5^2

    def test_third_dca_entry(self):
        """Test size calculation for third DCA entry."""
        investment, contracts = calculate_dca_entry_size(
            initial_investment=100.0,
            initial_contracts=10.0,
            dca_count=3,
            entry_multiplier=0.5,
            current_price=85.0,
            leverage=10
        )
        assert investment == pytest.approx(12.5)  # 100 * 0.5^3
        assert contracts == pytest.approx(1.25)   # 10 * 0.5^3


class TestCheckRsiConditionForDca:
    """Tests for check_rsi_condition_for_dca function."""

    def test_long_rsi_oversold(self):
        """Test long DCA allowed when RSI oversold."""
        result = check_rsi_condition_for_dca(
            rsi=28.0,
            side='long',
            rsi_oversold=30.0,
            rsi_overbought=70.0,
            use_rsi_with_pyramiding=True
        )
        assert result is True

    def test_long_rsi_not_oversold(self):
        """Test long DCA blocked when RSI not oversold."""
        result = check_rsi_condition_for_dca(
            rsi=35.0,
            side='long',
            rsi_oversold=30.0,
            rsi_overbought=70.0,
            use_rsi_with_pyramiding=True
        )
        assert result is False

    def test_short_rsi_overbought(self):
        """Test short DCA allowed when RSI overbought."""
        result = check_rsi_condition_for_dca(
            rsi=72.0,
            side='short',
            rsi_oversold=30.0,
            rsi_overbought=70.0,
            use_rsi_with_pyramiding=True
        )
        assert result is True

    def test_disabled_rsi_check(self):
        """Test RSI check disabled."""
        result = check_rsi_condition_for_dca(
            rsi=50.0,
            side='long',
            rsi_oversold=30.0,
            rsi_overbought=70.0,
            use_rsi_with_pyramiding=False
        )
        assert result is True


class TestCheckTrendConditionForDca:
    """Tests for check_trend_condition_for_dca function."""

    def test_long_weak_downtrend_allowed(self):
        """Test long DCA allowed in weak downtrend."""
        result = check_trend_condition_for_dca(
            ema=98.5,
            sma=100.0,  # EMA 1.5% below SMA (weak downtrend)
            side='long',
            use_trend_logic=True
        )
        assert result is True

    def test_long_strong_downtrend_blocked(self):
        """Test long DCA blocked in strong downtrend."""
        result = check_trend_condition_for_dca(
            ema=100.0,
            sma=110.0,  # EMA 9% below SMA
            side='long',
            use_trend_logic=True
        )
        assert result is False

    def test_short_weak_uptrend_allowed(self):
        """Test short DCA allowed in weak uptrend."""
        result = check_trend_condition_for_dca(
            ema=101.5,
            sma=100.0,  # EMA 1.5% above SMA (weak uptrend)
            side='short',
            use_trend_logic=True
        )
        assert result is True

    def test_disabled_trend_check(self):
        """Test trend check disabled."""
        result = check_trend_condition_for_dca(
            ema=100.0,
            sma=120.0,  # Strong downtrend
            side='long',
            use_trend_logic=False
        )
        assert result is True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
