"""
Test cases for RSI entry_option modes ('돌파', '변곡돌파', '초과').

Tests the 3 different RSI entry logic modes ported from HYPERRSI live trading system.
"""

import pytest
from datetime import datetime
from BACKTEST.strategies.signal_generator import SignalGenerator
from BACKTEST.strategies.hyperrsi_strategy import HyperrsiStrategy
from BACKTEST.models.candle import Candle
from BACKTEST.models.trade import TradeSide


class TestSignalGeneratorEntryOptions:
    """Test SignalGenerator with different entry_option modes."""

    @pytest.fixture
    def candle_base(self):
        """Base candle fixture."""
        return Candle(
            timestamp=datetime(2025, 1, 1, 0, 0),
            open=100.0,
            high=105.0,
            low=95.0,
            close=100.0,
            volume=1000.0,
            rsi=None,
            atr=None
        )

    def test_entry_option_초과_long(self):
        """Test '초과' mode for long signal (단순 RSI < oversold)."""
        generator = SignalGenerator(
            rsi_oversold=30.0,
            rsi_overbought=70.0,
            use_trend_filter=False,
            entry_option="초과"
        )

        # Current RSI < oversold → should trigger long
        has_signal, reason = generator.check_long_signal(
            rsi=25.0,
            trend_state=None,
            previous_rsi=35.0
        )
        assert has_signal is True
        assert "초과" in reason

        # Current RSI > oversold → should NOT trigger
        has_signal, reason = generator.check_long_signal(
            rsi=35.0,
            trend_state=None,
            previous_rsi=40.0
        )
        assert has_signal is False

    def test_entry_option_초과_short(self):
        """Test '초과' mode for short signal (단순 RSI > overbought)."""
        generator = SignalGenerator(
            rsi_oversold=30.0,
            rsi_overbought=70.0,
            use_trend_filter=False,
            entry_option="초과"
        )

        # Current RSI > overbought → should trigger short
        has_signal, reason = generator.check_short_signal(
            rsi=75.0,
            trend_state=None,
            previous_rsi=65.0
        )
        assert has_signal is True
        assert "초과" in reason

        # Current RSI < overbought → should NOT trigger
        has_signal, reason = generator.check_short_signal(
            rsi=65.0,
            trend_state=None,
            previous_rsi=60.0
        )
        assert has_signal is False

    def test_entry_option_돌파_long(self):
        """Test '돌파' mode for long signal (crossunder oversold)."""
        generator = SignalGenerator(
            rsi_oversold=30.0,
            rsi_overbought=70.0,
            use_trend_filter=False,
            entry_option="돌파"
        )

        # previous_rsi > oversold AND current_rsi <= oversold → should trigger
        has_signal, reason = generator.check_long_signal(
            rsi=28.0,          # current <= 30
            trend_state=None,
            previous_rsi=32.0  # previous > 30
        )
        assert has_signal is True
        assert "돌파" in reason

        # Exact crossover (previous=31, current=30)
        has_signal, reason = generator.check_long_signal(
            rsi=30.0,
            trend_state=None,
            previous_rsi=31.0
        )
        assert has_signal is True

        # Both below oversold → should NOT trigger (already crossed)
        has_signal, reason = generator.check_long_signal(
            rsi=25.0,
            trend_state=None,
            previous_rsi=28.0
        )
        assert has_signal is False

        # Both above oversold → should NOT trigger (not crossed yet)
        has_signal, reason = generator.check_long_signal(
            rsi=35.0,
            trend_state=None,
            previous_rsi=40.0
        )
        assert has_signal is False

    def test_entry_option_변곡_long(self):
        """Test '변곡' mode for long signal (RSI reversal in oversold area)."""
        generator = SignalGenerator(
            rsi_oversold=30.0,
            rsi_overbought=70.0,
            use_trend_filter=False,
            entry_option="변곡"
        )

        # RSI in oversold area AND rising → should trigger
        has_signal, reason = generator.check_long_signal(
            rsi=28.0,          # current < 30, rising
            trend_state=None,
            previous_rsi=25.0  # previous < 30
        )
        assert has_signal is True
        assert "변곡" in reason

        # RSI was above oversold, now in oversold and rising → should trigger
        has_signal, reason = generator.check_long_signal(
            rsi=29.0,          # current < 30 (in oversold), rising
            trend_state=None,
            previous_rsi=27.0  # previous < 30 (was in oversold)
        )
        assert has_signal is True

        # RSI in oversold but falling → should NOT trigger
        has_signal, reason = generator.check_long_signal(
            rsi=25.0,          # current < 30, falling
            trend_state=None,
            previous_rsi=28.0  # previous < 30
        )
        assert has_signal is False

        # RSI above oversold → should NOT trigger
        has_signal, reason = generator.check_long_signal(
            rsi=35.0,
            trend_state=None,
            previous_rsi=33.0
        )
        assert has_signal is False

    def test_entry_option_변곡_short(self):
        """Test '변곡' mode for short signal (RSI reversal in overbought area)."""
        generator = SignalGenerator(
            rsi_oversold=30.0,
            rsi_overbought=70.0,
            use_trend_filter=False,
            entry_option="변곡"
        )

        # RSI in overbought area AND falling → should trigger
        has_signal, reason = generator.check_short_signal(
            rsi=72.0,          # current > 70, falling
            trend_state=None,
            previous_rsi=75.0  # previous > 70
        )
        assert has_signal is True
        assert "변곡" in reason

        # RSI was below overbought, now in overbought and falling → should trigger
        has_signal, reason = generator.check_short_signal(
            rsi=71.0,          # current > 70 (in overbought), falling
            trend_state=None,
            previous_rsi=73.0  # previous > 70 (was in overbought)
        )
        assert has_signal is True

        # RSI in overbought but rising → should NOT trigger
        has_signal, reason = generator.check_short_signal(
            rsi=75.0,          # current > 70, rising
            trend_state=None,
            previous_rsi=72.0  # previous > 70
        )
        assert has_signal is False

        # RSI below overbought → should NOT trigger
        has_signal, reason = generator.check_short_signal(
            rsi=65.0,
            trend_state=None,
            previous_rsi=67.0
        )
        assert has_signal is False

    def test_entry_option_돌파_short(self):
        """Test '돌파' mode for short signal (crossover overbought)."""
        generator = SignalGenerator(
            rsi_oversold=30.0,
            rsi_overbought=70.0,
            use_trend_filter=False,
            entry_option="돌파"
        )

        # previous_rsi < overbought AND current_rsi >= overbought → should trigger
        has_signal, reason = generator.check_short_signal(
            rsi=72.0,          # current >= 70
            trend_state=None,
            previous_rsi=68.0  # previous < 70
        )
        assert has_signal is True
        assert "돌파" in reason

        # Exact crossover (previous=69, current=70)
        has_signal, reason = generator.check_short_signal(
            rsi=70.0,
            trend_state=None,
            previous_rsi=69.0
        )
        assert has_signal is True

        # Both above overbought → should NOT trigger (already crossed)
        has_signal, reason = generator.check_short_signal(
            rsi=75.0,
            trend_state=None,
            previous_rsi=72.0
        )
        assert has_signal is False

    def test_entry_option_변곡돌파_long(self):
        """Test '변곡돌파' mode for long signal (crossover from below oversold)."""
        generator = SignalGenerator(
            rsi_oversold=30.0,
            rsi_overbought=70.0,
            use_trend_filter=False,
            entry_option="변곡돌파"
        )

        # current_rsi < oversold AND previous_rsi >= oversold → should trigger
        # (반등 시작: RSI가 oversold 아래로 떨어졌다가 다시 올라오는 순간)
        has_signal, reason = generator.check_long_signal(
            rsi=28.0,          # current < 30
            trend_state=None,
            previous_rsi=32.0  # previous >= 30
        )
        assert has_signal is True
        assert "변곡돌파" in reason

        # Exact crossover (previous=30, current=29)
        has_signal, reason = generator.check_long_signal(
            rsi=29.0,
            trend_state=None,
            previous_rsi=30.0
        )
        assert has_signal is True

        # Both below oversold → should NOT trigger
        has_signal, reason = generator.check_long_signal(
            rsi=25.0,
            trend_state=None,
            previous_rsi=28.0
        )
        assert has_signal is False

        # Both above oversold → should NOT trigger
        has_signal, reason = generator.check_long_signal(
            rsi=35.0,
            trend_state=None,
            previous_rsi=40.0
        )
        assert has_signal is False

    def test_entry_option_변곡돌파_short(self):
        """Test '변곡돌파' mode for short signal (crossunder from above overbought)."""
        generator = SignalGenerator(
            rsi_oversold=30.0,
            rsi_overbought=70.0,
            use_trend_filter=False,
            entry_option="변곡돌파"
        )

        # current_rsi > overbought AND previous_rsi <= overbought → should trigger
        # (하락 시작: RSI가 overbought 위로 올라갔다가 다시 내려오는 순간)
        has_signal, reason = generator.check_short_signal(
            rsi=72.0,          # current > 70
            trend_state=None,
            previous_rsi=68.0  # previous <= 70
        )
        assert has_signal is True
        assert "변곡돌파" in reason

        # Exact crossover (previous=70, current=71)
        has_signal, reason = generator.check_short_signal(
            rsi=71.0,
            trend_state=None,
            previous_rsi=70.0
        )
        assert has_signal is True

        # Both above overbought → should NOT trigger
        has_signal, reason = generator.check_short_signal(
            rsi=75.0,
            trend_state=None,
            previous_rsi=72.0
        )
        assert has_signal is False

    def test_previous_rsi_required_for_crossover_modes(self):
        """Test that previous_rsi is required for '돌파' and '변곡돌파'."""
        generator_돌파 = SignalGenerator(entry_option="돌파")
        generator_변곡돌파 = SignalGenerator(entry_option="변곡돌파")

        # Without previous_rsi → should return False with error message
        has_signal, reason = generator_돌파.check_long_signal(
            rsi=25.0,
            trend_state=None,
            previous_rsi=None
        )
        assert has_signal is False
        assert "Previous RSI required" in reason

        has_signal, reason = generator_변곡돌파.check_long_signal(
            rsi=25.0,
            trend_state=None,
            previous_rsi=None
        )
        assert has_signal is False
        assert "Previous RSI required" in reason

    def test_entry_option_with_trend_filter(self):
        """Test entry_option works with trend filter."""
        generator = SignalGenerator(
            rsi_oversold=30.0,
            rsi_overbought=70.0,
            use_trend_filter=True,
            entry_option="돌파"
        )

        # Long signal with bullish trend
        has_signal, reason = generator.check_long_signal(
            rsi=28.0,
            trend_state=1,  # bullish
            previous_rsi=32.0
        )
        assert has_signal is True
        assert "돌파" in reason
        assert "bullish" in reason

        # Long signal blocked by bearish trend
        has_signal, reason = generator.check_long_signal(
            rsi=28.0,
            trend_state=-1,  # bearish
            previous_rsi=32.0
        )
        assert has_signal is False
        assert "Bearish trend" in reason


class TestHyperrsiStrategyEntryOptions:
    """Test HyperrsiStrategy with different entry_option modes."""

    @pytest.fixture
    def base_params(self):
        """Base strategy parameters."""
        return {
            "entry_option": "rsi_only",
            "rsi_oversold": 30,
            "rsi_overbought": 70,
            "rsi_period": 14,
            "leverage": 10,
            "investment": 100,
            "tp_sl_option": "fixed",
            "stop_loss_percent": 2.0,
            "take_profit_percent": 4.0,
        }

    def test_strategy_초과_mode(self, base_params):
        """Test strategy with '초과' mode."""
        params = {**base_params, "rsi_entry_option": "초과"}
        strategy = HyperrsiStrategy(params)

        assert strategy.rsi_entry_option == "초과"
        assert strategy.signal_generator.entry_option == "초과"

    def test_strategy_돌파_mode(self, base_params):
        """Test strategy with '돌파' mode."""
        params = {**base_params, "rsi_entry_option": "돌파"}
        strategy = HyperrsiStrategy(params)

        assert strategy.rsi_entry_option == "돌파"
        assert strategy.signal_generator.entry_option == "돌파"

    def test_strategy_변곡_mode(self, base_params):
        """Test strategy with '변곡' mode."""
        params = {**base_params, "rsi_entry_option": "변곡"}
        strategy = HyperrsiStrategy(params)

        assert strategy.rsi_entry_option == "변곡"
        assert strategy.signal_generator.entry_option == "변곡"

    def test_strategy_변곡돌파_mode(self, base_params):
        """Test strategy with '변곡돌파' mode."""
        params = {**base_params, "rsi_entry_option": "변곡돌파"}
        strategy = HyperrsiStrategy(params)

        assert strategy.rsi_entry_option == "변곡돌파"
        assert strategy.signal_generator.entry_option == "변곡돌파"

    def test_invalid_rsi_entry_option(self, base_params):
        """Test that invalid rsi_entry_option raises ValueError."""
        params = {**base_params, "rsi_entry_option": "invalid"}

        with pytest.raises(ValueError) as exc_info:
            HyperrsiStrategy(params)

        assert "Invalid rsi_entry_option" in str(exc_info.value)
        assert "돌파" in str(exc_info.value)
        assert "변곡" in str(exc_info.value)
        assert "변곡돌파" in str(exc_info.value)
        assert "초과" in str(exc_info.value)

    def test_default_rsi_entry_option(self):
        """Test default rsi_entry_option is '초과'."""
        strategy = HyperrsiStrategy()

        assert strategy.rsi_entry_option == "초과"
        assert strategy.signal_generator.entry_option == "초과"


class TestEntryOptionComparison:
    """Compare behavior of different entry_option modes."""

    def test_entry_frequency_comparison(self):
        """
        Demonstrate that different entry_option modes have different trigger frequencies.

        '초과' > '돌파' + '변곡돌파' (combined)

        In a typical downtrend scenario:
        - '초과': Triggers on ALL candles where RSI < 30
        - '돌파': Triggers ONLY when RSI crosses below 30
        - '변곡돌파': Triggers ONLY when RSI crosses above 30 while still below
        """
        generator_초과 = SignalGenerator(rsi_oversold=30.0, entry_option="초과", use_trend_filter=False)
        generator_돌파 = SignalGenerator(rsi_oversold=30.0, entry_option="돌파", use_trend_filter=False)
        generator_변곡돌파 = SignalGenerator(rsi_oversold=30.0, entry_option="변곡돌파", use_trend_filter=False)

        # Scenario: RSI sequence = [35, 28, 25, 22, 27, 32]
        rsi_sequence = [35, 28, 25, 22, 27, 32]

        signals_초과 = []
        signals_돌파 = []
        signals_변곡돌파 = []

        for i in range(1, len(rsi_sequence)):
            current = rsi_sequence[i]
            previous = rsi_sequence[i - 1]

            # Check each mode
            has_초과, _ = generator_초과.check_long_signal(current, None, previous)
            has_돌파, _ = generator_돌파.check_long_signal(current, None, previous)
            has_변곡돌파, _ = generator_변곡돌파.check_long_signal(current, None, previous)

            signals_초과.append(has_초과)
            signals_돌파.append(has_돌파)
            signals_변곡돌파.append(has_변곡돌파)

        # Count triggers
        count_초과 = sum(signals_초과)
        count_돌파 = sum(signals_돌파)
        count_변곡돌파 = sum(signals_변곡돌파)

        # Verify relative frequencies
        assert count_초과 >= count_돌파  # '초과' triggers more often
        assert count_초과 >= count_변곡돌파  # '초과' triggers more often

        # Expected results:
        # - '초과': [True, True, True, True, False] = 4 triggers (all RSI < 30)
        # - '돌파': [True, False, False, False, False] = 1 trigger (35→28 crossunder)
        # - '변곡돌파': [True, False, False, False, False] = 1 trigger (35→28 crosses below)

        assert count_초과 == 4
        assert count_돌파 == 1
        assert count_변곡돌파 == 1  # Both '돌파' and '변곡돌파' trigger at crossover point

        # Index 0 (35→28): both '돌파' and '변곡돌파' trigger
        assert signals_돌파[0] is True
        assert signals_변곡돌파[0] is True

        # Indices 1-3 (RSI staying below 30): only 초과 triggers
        assert signals_초과[1] is True
        assert signals_초과[2] is True
        assert signals_초과[3] is True
