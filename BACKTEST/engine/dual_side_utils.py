"""
Utility helpers for dual-side (hedge) backtesting logic.

These functions mirror the behavior used in the live trading stack so the
backtest can reproduce dual-side entries, sizing, and TP/SL handling.
"""

from typing import Any, Dict, Optional

from BACKTEST.models.trade import TradeSide
from shared.constants.default_settings import DEFAULT_DUAL_SIDE_ENTRY_SETTINGS


def _to_bool(value: Any) -> bool:
    """Normalize truthy strings and other types to bool."""
    if isinstance(value, str):
        return value.lower() == "true"
    return bool(value)


def merge_dual_side_params(strategy_params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge strategy params with dual-side defaults.

    Unknown keys are ignored; missing values fall back to DEFAULT_DUAL_SIDE_ENTRY_SETTINGS.
    """
    params = {**DEFAULT_DUAL_SIDE_ENTRY_SETTINGS}

    override_keys = {
        "use_dual_side_entry",
        "dual_side_entry_trigger",
        "dual_side_entry_ratio_type",
        "dual_side_entry_ratio_value",
        "dual_side_entry_tp_trigger_type",
        "dual_side_entry_tp_value",
        "close_main_on_hedge_tp",
        "use_dual_sl",
        "dual_side_entry_sl_trigger_type",
        "dual_side_entry_sl_value",
        "dual_side_pyramiding_limit",
        "dual_side_trend_close",
        "dual_side_close_on_main_sl",
    }

    for key in override_keys:
        if key in strategy_params and strategy_params[key] is not None:
            params[key] = strategy_params[key]

    # Normalize booleans that may arrive as strings
    params["use_dual_side_entry"] = _to_bool(params.get("use_dual_side_entry"))
    params["close_main_on_hedge_tp"] = _to_bool(params.get("close_main_on_hedge_tp"))
    params["use_dual_sl"] = _to_bool(params.get("use_dual_sl"))
    params["dual_side_trend_close"] = _to_bool(params.get("dual_side_trend_close"))
    params["dual_side_close_on_main_sl"] = _to_bool(params.get("dual_side_close_on_main_sl", False))

    return params


def should_create_dual_side_position(current_entry_count: int, params: Dict[str, Any]) -> bool:
    """
    Determine if the dual-side position should be (re)entered at the given DCA index.

    Args:
        current_entry_count: Current DCA count on the main position (1-indexed)
        params: Dual-side parameters
    """
    if not params.get("use_dual_side_entry"):
        return False

    trigger = int(params.get("dual_side_entry_trigger", 0) or 0)
    return current_entry_count >= trigger


def calculate_dual_side_quantity(main_position_qty: float, params: Dict[str, Any]) -> float:
    """
    Calculate hedge quantity based on ratio configuration.
    """
    ratio_type = params.get("dual_side_entry_ratio_type", "percent_of_position")
    ratio_value = params.get("dual_side_entry_ratio_value", 100)

    try:
        ratio_value = float(ratio_value)
    except (TypeError, ValueError):
        ratio_value = 0.0

    if ratio_type == "percent_of_position":
        return main_position_qty * (ratio_value / 100.0)

    return ratio_value  # fixed_amount


def calculate_dual_side_tp_price(
    entry_price: float,
    side: TradeSide,
    params: Dict[str, Any],
    main_position_sl_price: Optional[float] = None,
    last_main_dca_price: Optional[float] = None,
    is_last_main_dca: bool = False
) -> Optional[float]:
    """
    Calculate TP price for hedge position based on configured trigger type.
    """
    tp_type = params.get("dual_side_entry_tp_trigger_type", "do_not_close")

    if tp_type == "do_not_close":
        return None

    if tp_type == "last_dca_on_position":
        if not is_last_main_dca:
            return None
        if not last_main_dca_price:
            return None
        target = last_main_dca_price
        # Ensure TP is in the profitable direction
        if side == TradeSide.LONG and target <= entry_price:
            target = entry_price * 1.001  # nudge above entry to avoid fee-only loss
        elif side == TradeSide.SHORT and target >= entry_price:
            target = entry_price * 0.999  # nudge below entry to avoid fee-only loss
        return target

    if tp_type == "existing_position":
        if main_position_sl_price is None:
            return None
        # Ensure TP is on the profitable side for the hedge
        if side == TradeSide.LONG and main_position_sl_price <= entry_price:
            return None
        if side == TradeSide.SHORT and main_position_sl_price >= entry_price:
            return None
        return main_position_sl_price

    # percent
    tp_percent = params.get("dual_side_entry_tp_value", 0)
    try:
        tp_percent = float(tp_percent)
    except (TypeError, ValueError):
        tp_percent = 0.0

    if tp_percent <= 0:
        return None

    if side == TradeSide.LONG:
        return entry_price * (1 + tp_percent / 100)

    return entry_price * (1 - tp_percent / 100)


def calculate_dual_side_sl_price(
    entry_price: float,
    side: TradeSide,
    params: Dict[str, Any],
    main_tp_prices: Optional[Dict[str, Optional[float]]] = None,
    is_last_main_dca: bool = False
) -> Optional[float]:
    """
    Calculate SL price for hedge position.
    """
    if not params.get("use_dual_sl"):
        return None

    sl_type = params.get("dual_side_entry_sl_trigger_type", "percent")
    sl_value = params.get("dual_side_entry_sl_value")

    if sl_type == "existing_position":
        tp_level = str(sl_value) if sl_value is not None else "1"
        tp_key = f"tp{tp_level}"
        if main_tp_prices and tp_key in main_tp_prices:
            return main_tp_prices[tp_key]
        return None

    try:
        sl_percent = float(sl_value)
    except (TypeError, ValueError):
        sl_percent = 0.0

    if side == TradeSide.LONG:
        return entry_price * (1 - sl_percent / 100)

    return entry_price * (1 + sl_percent / 100)


def can_add_dual_side_position(current_dual_entry_count: int, params: Dict[str, Any]) -> bool:
    """
    Check if another hedge entry is allowed under dual-side pyramiding limit.
    """
    max_entries = int(params.get("dual_side_pyramiding_limit", 1) or 1)
    return current_dual_entry_count < max_entries


def should_close_main_on_hedge_tp(params: Dict[str, Any]) -> bool:
    """Return whether main position should close when hedge TP hits."""
    return _to_bool(params.get("close_main_on_hedge_tp", False))


def should_close_dual_on_trend(params: Dict[str, Any]) -> bool:
    """Return whether hedge should close when main closes via trend exit."""
    return _to_bool(params.get("dual_side_trend_close", False))


def should_close_dual_on_main_sl(params: Dict[str, Any]) -> bool:
    """Return whether hedge should close when main position hits SL (including break-even SL)."""
    return _to_bool(params.get("dual_side_close_on_main_sl", False))
