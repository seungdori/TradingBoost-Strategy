"""Tests for strategy parameter handling."""

import pytest

from BACKTEST.strategies.hyperrsi_strategy import HyperrsiStrategy


def test_hyperrsi_strategy_applies_default_dca_params() -> None:
    """Default construction should populate DCA parameters."""

    strategy = HyperrsiStrategy()

    assert strategy.params["pyramiding_enabled"] is True
    assert strategy.params["pyramiding_limit"] == 3
    assert strategy.params["entry_multiplier"] == 1.6
    assert strategy.params["pyramiding_entry_type"] == "퍼센트 기준"
    assert strategy.params["pyramiding_value"] == 3.0
    assert strategy.params["entry_criterion"] == "평균 단가"
    assert strategy.params["use_check_DCA_with_price"] is True
    assert strategy.params["use_rsi_with_pyramiding"] is True
    assert strategy.params["use_trend_logic"] is True


def test_hyperrsi_strategy_accepts_custom_dca_params() -> None:
    """Custom DCA params should override defaults if valid."""

    custom_params = {
        "pyramiding_enabled": False,
        "pyramiding_limit": 5,
        "entry_multiplier": 0.6,
        "pyramiding_entry_type": "ATR 기준",
        "pyramiding_value": 2.5,
        "entry_criterion": "최근 진입가",
        "use_check_DCA_with_price": False,
        "use_rsi_with_pyramiding": False,
        "use_trend_logic": False,
    }

    strategy = HyperrsiStrategy(custom_params)

    for key, value in custom_params.items():
        assert strategy.params[key] == value


@pytest.mark.parametrize(
    "invalid_params",
    [
        {"pyramiding_limit": 15},
        {"entry_multiplier": 0.05},
        {"entry_multiplier": 1.5},
        {"pyramiding_entry_type": "invalid"},
        {"pyramiding_value": 0},
        {"entry_criterion": "invalid"},
        {"use_trend_logic": "yes"},
    ],
)
def test_hyperrsi_strategy_rejects_invalid_dca_params(invalid_params: dict) -> None:
    """Invalid DCA params should raise ValueError."""

    with pytest.raises(ValueError):
        HyperrsiStrategy(invalid_params)
