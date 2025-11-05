"""
Test DCA parameter validation for HYPERRSI strategy.

This test suite achieves 100% coverage of DCA parameter validation logic
in BACKTEST/strategies/hyperrsi_strategy.py.
"""

import pytest
from BACKTEST.strategies.hyperrsi_strategy import HyperrsiStrategy


class TestDCAParameterValidation:
    """Comprehensive test suite for DCA parameter validation - 100% coverage."""

    # ==================== Valid Parameter Tests ====================

    def test_default_params_valid(self):
        """Default DCA parameters should be valid."""
        strategy = HyperrsiStrategy()

        # Verify all default DCA params are set correctly
        assert strategy.pyramiding_enabled is True
        assert strategy.pyramiding_limit == 3
        assert strategy.entry_multiplier == 0.5
        assert strategy.pyramiding_entry_type == "퍼센트 기준"
        assert strategy.pyramiding_value == 3.0
        assert strategy.entry_criterion == "평균 단가"
        assert strategy.use_check_DCA_with_price is True
        assert strategy.use_rsi_with_pyramiding is True
        assert strategy.use_trend_logic is True

    def test_minimal_pyramiding_limit(self):
        """pyramiding_limit=1 should be valid (minimum)."""
        params = {"pyramiding_limit": 1}
        strategy = HyperrsiStrategy(params)
        assert strategy.pyramiding_limit == 1

    def test_maximum_pyramiding_limit(self):
        """pyramiding_limit=10 should be valid (maximum)."""
        params = {"pyramiding_limit": 10}
        strategy = HyperrsiStrategy(params)
        assert strategy.pyramiding_limit == 10

    def test_mid_range_pyramiding_limit(self):
        """Mid-range pyramiding_limit values should be valid."""
        for limit in [2, 3, 4, 5, 6, 7, 8, 9]:
            params = {"pyramiding_limit": limit}
            strategy = HyperrsiStrategy(params)
            assert strategy.pyramiding_limit == limit

    def test_minimal_entry_multiplier(self):
        """entry_multiplier=0.1 should be valid (minimum)."""
        params = {"entry_multiplier": 0.1}
        strategy = HyperrsiStrategy(params)
        assert strategy.entry_multiplier == 0.1

    def test_maximum_entry_multiplier(self):
        """entry_multiplier=1.0 should be valid (maximum)."""
        params = {"entry_multiplier": 1.0}
        strategy = HyperrsiStrategy(params)
        assert strategy.entry_multiplier == 1.0

    def test_mid_range_entry_multiplier(self):
        """Mid-range entry_multiplier values should be valid."""
        for multiplier in [0.2, 0.3, 0.5, 0.7, 0.9]:
            params = {"entry_multiplier": multiplier}
            strategy = HyperrsiStrategy(params)
            assert strategy.entry_multiplier == multiplier

    def test_entry_type_percent(self):
        """'퍼센트 기준' entry type should be valid."""
        params = {"pyramiding_entry_type": "퍼센트 기준"}
        strategy = HyperrsiStrategy(params)
        assert strategy.pyramiding_entry_type == "퍼센트 기준"

    def test_entry_type_fixed_amount(self):
        """'금액 기준' entry type should be valid."""
        params = {"pyramiding_entry_type": "금액 기준"}
        strategy = HyperrsiStrategy(params)
        assert strategy.pyramiding_entry_type == "금액 기준"

    def test_entry_type_atr(self):
        """'ATR 기준' entry type should be valid."""
        params = {"pyramiding_entry_type": "ATR 기준"}
        strategy = HyperrsiStrategy(params)
        assert strategy.pyramiding_entry_type == "ATR 기준"

    def test_entry_criterion_average(self):
        """'평균 단가' entry criterion should be valid."""
        params = {"entry_criterion": "평균 단가"}
        strategy = HyperrsiStrategy(params)
        assert strategy.entry_criterion == "평균 단가"

    def test_entry_criterion_last_filled(self):
        """'최근 진입가' entry criterion should be valid."""
        params = {"entry_criterion": "최근 진입가"}
        strategy = HyperrsiStrategy(params)
        assert strategy.entry_criterion == "최근 진입가"

    def test_small_pyramiding_value(self):
        """Small positive pyramiding_value should be valid."""
        params = {"pyramiding_value": 0.1}
        strategy = HyperrsiStrategy(params)
        assert strategy.pyramiding_value == 0.1

    def test_large_pyramiding_value(self):
        """Large pyramiding_value should be valid."""
        params = {"pyramiding_value": 100.0}
        strategy = HyperrsiStrategy(params)
        assert strategy.pyramiding_value == 100.0

    def test_int_pyramiding_value(self):
        """Integer pyramiding_value should be accepted."""
        params = {"pyramiding_value": 5}
        strategy = HyperrsiStrategy(params)
        assert strategy.pyramiding_value == 5

    def test_all_boolean_flags_true(self):
        """All boolean flags set to True should be valid."""
        params = {
            "pyramiding_enabled": True,
            "use_check_DCA_with_price": True,
            "use_rsi_with_pyramiding": True,
            "use_trend_logic": True
        }
        strategy = HyperrsiStrategy(params)
        assert strategy.pyramiding_enabled is True
        assert strategy.use_check_DCA_with_price is True
        assert strategy.use_rsi_with_pyramiding is True
        assert strategy.use_trend_logic is True

    def test_all_boolean_flags_false(self):
        """All boolean flags set to False should be valid."""
        params = {
            "pyramiding_enabled": False,
            "use_check_DCA_with_price": False,
            "use_rsi_with_pyramiding": False,
            "use_trend_logic": False
        }
        strategy = HyperrsiStrategy(params)
        assert strategy.pyramiding_enabled is False
        assert strategy.use_check_DCA_with_price is False
        assert strategy.use_rsi_with_pyramiding is False
        assert strategy.use_trend_logic is False

    def test_mixed_boolean_flags(self):
        """Mixed boolean flag values should be valid."""
        params = {
            "pyramiding_enabled": True,
            "use_check_DCA_with_price": False,
            "use_rsi_with_pyramiding": True,
            "use_trend_logic": False
        }
        strategy = HyperrsiStrategy(params)
        assert strategy.pyramiding_enabled is True
        assert strategy.use_check_DCA_with_price is False
        assert strategy.use_rsi_with_pyramiding is True
        assert strategy.use_trend_logic is False

    def test_complete_valid_params_conservative(self):
        """Complete set of valid conservative DCA parameters."""
        params = {
            "pyramiding_enabled": True,
            "pyramiding_limit": 2,
            "entry_multiplier": 0.3,
            "pyramiding_entry_type": "퍼센트 기준",
            "pyramiding_value": 5.0,
            "entry_criterion": "평균 단가",
            "use_check_DCA_with_price": True,
            "use_rsi_with_pyramiding": True,
            "use_trend_logic": True
        }
        strategy = HyperrsiStrategy(params)
        assert strategy.pyramiding_limit == 2
        assert strategy.entry_multiplier == 0.3

    def test_complete_valid_params_aggressive(self):
        """Complete set of valid aggressive DCA parameters."""
        params = {
            "pyramiding_enabled": True,
            "pyramiding_limit": 5,
            "entry_multiplier": 0.7,
            "pyramiding_entry_type": "ATR 기준",
            "pyramiding_value": 1.5,
            "entry_criterion": "최근 진입가",
            "use_check_DCA_with_price": True,
            "use_rsi_with_pyramiding": False,
            "use_trend_logic": False
        }
        strategy = HyperrsiStrategy(params)
        assert strategy.pyramiding_limit == 5
        assert strategy.entry_multiplier == 0.7

    # ==================== Invalid Parameter Tests ====================

    def test_pyramiding_limit_zero_invalid(self):
        """pyramiding_limit=0 should raise ValueError (minimum is 1)."""
        params = {"pyramiding_limit": 0}
        with pytest.raises(ValueError, match="pyramiding_limit must be integer between 1-10"):
            HyperrsiStrategy(params)

    def test_pyramiding_limit_negative_invalid(self):
        """Negative pyramiding_limit should raise ValueError."""
        params = {"pyramiding_limit": -1}
        with pytest.raises(ValueError, match="pyramiding_limit must be integer between 1-10"):
            HyperrsiStrategy(params)

    def test_pyramiding_limit_too_large_invalid(self):
        """pyramiding_limit>10 should raise ValueError."""
        params = {"pyramiding_limit": 11}
        with pytest.raises(ValueError, match="pyramiding_limit must be integer between 1-10"):
            HyperrsiStrategy(params)

    def test_pyramiding_limit_way_too_large_invalid(self):
        """pyramiding_limit>>10 should raise ValueError."""
        params = {"pyramiding_limit": 100}
        with pytest.raises(ValueError, match="pyramiding_limit must be integer between 1-10"):
            HyperrsiStrategy(params)

    def test_pyramiding_limit_float_invalid(self):
        """Float pyramiding_limit should raise ValueError."""
        params = {"pyramiding_limit": 3.5}
        with pytest.raises(ValueError, match="pyramiding_limit must be integer between 1-10"):
            HyperrsiStrategy(params)

    def test_pyramiding_limit_string_invalid(self):
        """String pyramiding_limit should raise ValueError."""
        params = {"pyramiding_limit": "3"}
        with pytest.raises(ValueError, match="pyramiding_limit must be integer between 1-10"):
            HyperrsiStrategy(params)

    def test_entry_multiplier_too_small_invalid(self):
        """entry_multiplier<0.1 should raise ValueError."""
        params = {"entry_multiplier": 0.09}
        with pytest.raises(ValueError, match="entry_multiplier must be between 0.1-1.0"):
            HyperrsiStrategy(params)

    def test_entry_multiplier_zero_invalid(self):
        """entry_multiplier=0 should raise ValueError."""
        params = {"entry_multiplier": 0.0}
        with pytest.raises(ValueError, match="entry_multiplier must be between 0.1-1.0"):
            HyperrsiStrategy(params)

    def test_entry_multiplier_negative_invalid(self):
        """Negative entry_multiplier should raise ValueError."""
        params = {"entry_multiplier": -0.5}
        with pytest.raises(ValueError, match="entry_multiplier must be between 0.1-1.0"):
            HyperrsiStrategy(params)

    def test_entry_multiplier_too_large_invalid(self):
        """entry_multiplier>1.0 should raise ValueError."""
        params = {"entry_multiplier": 1.01}
        with pytest.raises(ValueError, match="entry_multiplier must be between 0.1-1.0"):
            HyperrsiStrategy(params)

    def test_entry_multiplier_way_too_large_invalid(self):
        """entry_multiplier>>1.0 should raise ValueError."""
        params = {"entry_multiplier": 2.0}
        with pytest.raises(ValueError, match="entry_multiplier must be between 0.1-1.0"):
            HyperrsiStrategy(params)

    def test_invalid_entry_type_english(self):
        """English entry type should raise ValueError."""
        params = {"pyramiding_entry_type": "percentage"}
        with pytest.raises(ValueError, match="pyramiding_entry_type must be one of"):
            HyperrsiStrategy(params)

    def test_invalid_entry_type_random(self):
        """Random entry type string should raise ValueError."""
        params = {"pyramiding_entry_type": "invalid_type"}
        with pytest.raises(ValueError, match="pyramiding_entry_type must be one of"):
            HyperrsiStrategy(params)

    def test_invalid_entry_type_empty(self):
        """Empty entry type string should raise ValueError."""
        params = {"pyramiding_entry_type": ""}
        with pytest.raises(ValueError, match="pyramiding_entry_type must be one of"):
            HyperrsiStrategy(params)

    def test_pyramiding_value_zero_invalid(self):
        """pyramiding_value=0 should raise ValueError."""
        params = {"pyramiding_value": 0}
        with pytest.raises(ValueError, match="pyramiding_value must be positive number"):
            HyperrsiStrategy(params)

    def test_pyramiding_value_negative_invalid(self):
        """Negative pyramiding_value should raise ValueError."""
        params = {"pyramiding_value": -1.0}
        with pytest.raises(ValueError, match="pyramiding_value must be positive number"):
            HyperrsiStrategy(params)

    def test_pyramiding_value_large_negative_invalid(self):
        """Large negative pyramiding_value should raise ValueError."""
        params = {"pyramiding_value": -100.0}
        with pytest.raises(ValueError, match="pyramiding_value must be positive number"):
            HyperrsiStrategy(params)

    def test_invalid_entry_criterion_english(self):
        """English entry criterion should raise ValueError."""
        params = {"entry_criterion": "average"}
        with pytest.raises(ValueError, match="entry_criterion must be one of"):
            HyperrsiStrategy(params)

    def test_invalid_entry_criterion_random(self):
        """Random entry criterion should raise ValueError."""
        params = {"entry_criterion": "invalid_criterion"}
        with pytest.raises(ValueError, match="entry_criterion must be one of"):
            HyperrsiStrategy(params)

    def test_invalid_entry_criterion_empty(self):
        """Empty entry criterion should raise ValueError."""
        params = {"entry_criterion": ""}
        with pytest.raises(ValueError, match="entry_criterion must be one of"):
            HyperrsiStrategy(params)

    def test_pyramiding_enabled_not_boolean(self):
        """Non-boolean pyramiding_enabled should raise ValueError."""
        params = {"pyramiding_enabled": "true"}
        with pytest.raises(ValueError, match="pyramiding_enabled must be boolean"):
            HyperrsiStrategy(params)

    def test_pyramiding_enabled_integer(self):
        """Integer pyramiding_enabled should raise ValueError."""
        params = {"pyramiding_enabled": 1}
        with pytest.raises(ValueError, match="pyramiding_enabled must be boolean"):
            HyperrsiStrategy(params)

    def test_use_check_DCA_with_price_not_boolean(self):
        """Non-boolean use_check_DCA_with_price should raise ValueError."""
        params = {"use_check_DCA_with_price": "false"}
        with pytest.raises(ValueError, match="use_check_DCA_with_price must be boolean"):
            HyperrsiStrategy(params)

    def test_use_rsi_with_pyramiding_not_boolean(self):
        """Non-boolean use_rsi_with_pyramiding should raise ValueError."""
        params = {"use_rsi_with_pyramiding": 0}
        with pytest.raises(ValueError, match="use_rsi_with_pyramiding must be boolean"):
            HyperrsiStrategy(params)

    def test_use_trend_logic_not_boolean(self):
        """Non-boolean use_trend_logic should raise ValueError."""
        params = {"use_trend_logic": None}
        with pytest.raises(ValueError, match="use_trend_logic must be boolean"):
            HyperrsiStrategy(params)

    # ==================== Edge Case Tests ====================

    def test_pyramiding_disabled_still_validates(self):
        """Even with pyramiding_enabled=False, params should still validate."""
        params = {
            "pyramiding_enabled": False,
            "pyramiding_limit": 5,
            "entry_multiplier": 0.6
        }
        strategy = HyperrsiStrategy(params)
        assert strategy.pyramiding_enabled is False
        assert strategy.pyramiding_limit == 5

    def test_float_as_int_pyramiding_value(self):
        """Float that is whole number pyramiding_value should be accepted."""
        params = {"pyramiding_value": 5.0}
        strategy = HyperrsiStrategy(params)
        assert strategy.pyramiding_value == 5.0

    def test_very_small_positive_pyramiding_value(self):
        """Very small positive pyramiding_value should be valid."""
        params = {"pyramiding_value": 0.001}
        strategy = HyperrsiStrategy(params)
        assert strategy.pyramiding_value == 0.001

    def test_korean_string_encoding(self):
        """Korean strings should be properly handled and validated."""
        # Test all three Korean entry types
        for entry_type in ["퍼센트 기준", "금액 기준", "ATR 기준"]:
            params = {"pyramiding_entry_type": entry_type}
            strategy = HyperrsiStrategy(params)
            assert strategy.pyramiding_entry_type == entry_type

        # Test both Korean entry criteria
        for criterion in ["평균 단가", "최근 진입가"]:
            params = {"entry_criterion": criterion}
            strategy = HyperrsiStrategy(params)
            assert strategy.entry_criterion == criterion

    def test_boundary_entry_multiplier_0_1(self):
        """entry_multiplier exactly 0.1 should be valid."""
        params = {"entry_multiplier": 0.1}
        strategy = HyperrsiStrategy(params)
        assert strategy.entry_multiplier == 0.1

    def test_boundary_entry_multiplier_1_0(self):
        """entry_multiplier exactly 1.0 should be valid."""
        params = {"entry_multiplier": 1.0}
        strategy = HyperrsiStrategy(params)
        assert strategy.entry_multiplier == 1.0

    def test_boundary_pyramiding_limit_1(self):
        """pyramiding_limit exactly 1 should be valid."""
        params = {"pyramiding_limit": 1}
        strategy = HyperrsiStrategy(params)
        assert strategy.pyramiding_limit == 1

    def test_boundary_pyramiding_limit_10(self):
        """pyramiding_limit exactly 10 should be valid."""
        params = {"pyramiding_limit": 10}
        strategy = HyperrsiStrategy(params)
        assert strategy.pyramiding_limit == 10

    def test_partial_params_with_defaults(self):
        """Partial DCA params should merge with defaults."""
        params = {
            "pyramiding_limit": 5,
            "entry_multiplier": 0.7
        }
        strategy = HyperrsiStrategy(params)
        assert strategy.pyramiding_limit == 5
        assert strategy.entry_multiplier == 0.7
        # Defaults should apply for unspecified params
        assert strategy.pyramiding_entry_type == "퍼센트 기준"
        assert strategy.entry_criterion == "평균 단가"

    def test_mixed_valid_and_defaults(self):
        """Mix of custom and default params should work."""
        params = {
            "pyramiding_enabled": False,
            "pyramiding_limit": 2,
            "pyramiding_entry_type": "금액 기준"
        }
        strategy = HyperrsiStrategy(params)
        assert strategy.pyramiding_enabled is False
        assert strategy.pyramiding_limit == 2
        assert strategy.pyramiding_entry_type == "금액 기준"
        # Other params should use defaults
        assert strategy.entry_multiplier == 0.5
        assert strategy.pyramiding_value == 3.0
