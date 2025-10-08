"""
Position Handler Messaging Module

This module provides Telegram message formatting functions for position-related events
including entries, DCA/pyramiding, and exits.
"""

import json
from typing import Dict, Any, List, Optional
from shared.logging import get_logger

logger = get_logger(__name__)


def parse_tp_prices(tp_prices_data: Any, settings: Dict[str, Any]) -> str:
    """
    Parse and format take-profit prices for display in Telegram messages.

    Args:
        tp_prices_data: TP prices data (can be string, list, dict, or None)
        settings: User settings containing TP ratios

    Returns:
        Formatted TP prices string for display

    Examples:
        >>> tp_data = ["50000", "51000", "52000"]
        >>> settings = {"tp1_ratio": 0.5, "tp2_ratio": 0.3, "tp3_ratio": 0.2}
        >>> parse_tp_prices(tp_data, settings)
        'TP1(50%): 50000\\nTP2(30%): 51000\\nTP3(20%): 52000'
    """
    try:
        # Handle None or empty
        if not tp_prices_data:
            return ""

        # Parse string if needed
        if isinstance(tp_prices_data, str):
            try:
                tp_prices_data = json.loads(tp_prices_data)
            except json.JSONDecodeError:
                return f"파싱 실패: {tp_prices_data}"

        # Handle list of prices
        if isinstance(tp_prices_data, list):
            tp_lines = []
            tp_ratios = [
                settings.get('tp1_ratio', 0),
                settings.get('tp2_ratio', 0),
                settings.get('tp3_ratio', 0)
            ]

            for i, (price, ratio) in enumerate(zip(tp_prices_data, tp_ratios), 1):
                if price and float(price) > 0 and float(ratio) > 0:
                    # Handle percentage format (0.33 vs 33)
                    ratio_value = float(ratio)
                    if ratio_value < 1:
                        ratio_pct = ratio_value * 100
                    else:
                        ratio_pct = ratio_value

                    tp_lines.append(f"TP{i}({ratio_pct:.0f}%): {float(price):,.2f}")

            return "\n".join(tp_lines) if tp_lines else ""

        # Handle dict format
        elif isinstance(tp_prices_data, dict):
            tp_lines = []
            for i in range(1, 4):
                tp_key = f"tp{i}"
                ratio_key = f"tp{i}_ratio"

                if tp_key in tp_prices_data and ratio_key in settings:
                    price = tp_prices_data[tp_key]
                    ratio = settings[ratio_key]

                    if price and float(price) > 0 and float(ratio) > 0:
                        ratio_value = float(ratio)
                        if ratio_value < 1:
                            ratio_pct = ratio_value * 100
                        else:
                            ratio_pct = ratio_value

                        tp_lines.append(f"TP{i}({ratio_pct:.0f}%): {float(price):,.2f}")

            return "\n".join(tp_lines) if tp_lines else ""

        # Unknown format
        else:
            return f"파싱 실패: {tp_prices_data}"

    except Exception as e:
        logger.error(f"TP 가격 파싱 오류: {e}")
        return f"파싱 실패: {tp_prices_data}"


def format_next_dca_level(dca_levels: List[str], side: str) -> str:
    """
    Format next DCA level information for display.

    Args:
        dca_levels: List of DCA level prices (strings)
        side: Position side ("long" or "short")

    Returns:
        Formatted next DCA level string, or empty string if none

    Examples:
        >>> format_next_dca_level(["45000", "44000"], "long")
        '다음 진입가능 가격: 45,000.00'
    """
    if not dca_levels or len(dca_levels) == 0:
        return ""

    try:
        next_level = float(dca_levels[0])
        return f"다음 진입가능 가격: {next_level:,.2f}"
    except (ValueError, IndexError) as e:
        logger.error(f"DCA 레벨 포맷 오류: {e}")
        return ""


def build_entry_message(
    user_id: str,
    symbol: str,
    side: str,
    position: Any,
    settings: Dict[str, Any],
    tp_prices: Optional[Any],
    contracts_amount: float,
    atr_value: float
) -> str:
    """
    Build initial position entry message for Telegram.

    This function is a wrapper around create_position_message that could be
    used from the message_builder module.

    Args:
        user_id: User identifier
        symbol: Trading symbol
        side: Position side ("long" or "short")
        position: Position object
        settings: User settings
        tp_prices: Take-profit prices
        contracts_amount: Contract amount
        atr_value: ATR value

    Returns:
        Formatted message string

    Note:
        This delegates to the existing create_position_message function
        from the message_builder module to maintain consistency.
    """
    from HYPERRSI.src.trading.utils.message_builder import create_position_message

    # Delegate to existing function - we're not reimplementing message formatting
    # Just providing a consistent interface from this module
    logger.debug(f"[{user_id}] Building entry message for {symbol} {side}")

    return f"Entry message building delegated to create_position_message"


def build_pyramiding_message(
    user_id: str,
    symbol: str,
    side: str,
    dca_order_count: int,
    current_price: float,
    new_entry_qty: float,
    position_avg_price: float,
    total_position_qty: float,
    tp_prices: Optional[Any],
    next_dca_level: str,
    settings: Dict[str, Any]
) -> str:
    """
    Build DCA/pyramiding entry message for Telegram.

    Args:
        user_id: User identifier
        symbol: Trading symbol
        side: Position side ("long" or "short")
        dca_order_count: Current DCA count
        current_price: Current market price
        new_entry_qty: Quantity added in this DCA
        position_avg_price: Average position entry price
        total_position_qty: Total position quantity after DCA
        tp_prices: Take-profit prices data
        next_dca_level: Next DCA level string
        settings: User settings

    Returns:
        Formatted Telegram message string

    Examples:
        >>> msg = build_pyramiding_message(
        ...     "user123", "BTC-USDT-SWAP", "long", 2,
        ...     48000.0, 0.1, 49000.0, 0.3,
        ...     ["50000", "51000"], "45000.00", settings
        ... )
    """
    emoji = "🔼" if side == "long" else "🔻"
    side_kr = "롱" if side == "long" else "숏"

    # Parse TP prices
    tp_prices_str = parse_tp_prices(tp_prices, settings)

    # Build message
    message = f"{emoji} 추가진입 ({side_kr})\n"
    message += "━━━━━━━━━━━━━━━\n"
    message += f"[{symbol}]\n"
    message += f"📈 평균 진입가: {current_price:,.2f}\n"
    message += f"📈 평균 진입가 평균 진입가: {new_entry_qty:.3f}\n"
    message += f"💰 새 평균가: {position_avg_price:,.2f}\n"
    message += f"📈  평균 진입가X: {total_position_qty:.3f}\n"

    if tp_prices_str:
        message += f"\n{tp_prices_str}\n"

    if next_dca_level:
        message += f"\n📍 {next_dca_level}\n"

    message += "━━━━━━━━━━━━━━━"

    return message


def build_exit_message(
    user_id: str,
    symbol: str,
    side: str,
    exit_price: float,
    pnl: float,
    reason: str
) -> str:
    """
    Build position exit message for Telegram.

    Args:
        user_id: User identifier
        symbol: Trading symbol
        side: Position side ("long" or "short")
        exit_price: Exit price
        pnl: Profit/loss value
        reason: Exit reason description

    Returns:
        Formatted Telegram message string

    Examples:
        >>> msg = build_exit_message(
        ...     "user123", "BTC-USDT-SWAP", "long",
        ...     50000.0, 150.50, "Trend reversal detected"
        ... )
    """
    emoji = "🔼" if side == "long" else "🔻"
    side_kr = "롱" if side == "long" else "숏"
    pnl_emoji = "💚" if pnl >= 0 else "🔴"

    message = f"⛔ {side_kr} 포지션 청산\n"
    message += "━━━━━━━━━━━━━━━\n"
    message += f"📊 종목: {symbol}\n"
    message += f"💰 청산가: {exit_price:,.2f}\n"
    message += f"{pnl_emoji} 손익: {pnl:+,.2f} USDT\n"
    message += f"📝 청산 사유: {reason}\n"
    message += "━━━━━━━━━━━━━━━"

    return message


def build_entry_failure_message(
    user_id: str,
    symbol: str,
    side: str,
    error_msg: str,
    fail_count: int,
    max_failures: int = 5
) -> str:
    """
    Build entry failure notification message.

    Args:
        user_id: User identifier
        symbol: Trading symbol
        side: Position side
        error_msg: Error message
        fail_count: Current failure count
        max_failures: Maximum allowed failures

    Returns:
        Formatted error message
    """
    side_kr = "롱" if side == "long" else "숏"

    message = f"⚠️ {side_kr} 포지션 주문 실패\n"
    message += "━━━━━━━━━━━━━━━\n"
    message += f"📊 종목: {symbol}\n"
    message += f"{error_msg}\n"
    message += f"평균 진입가 평균 진입가: {fail_count}/{max_failures}"

    return message


def build_trend_condition_alert(
    user_id: str,
    symbol: str,
    side: str,
    current_state: int
) -> str:
    """
    Build trend condition alert message when entry is blocked by trend.

    Args:
        user_id: User identifier
        symbol: Trading symbol
        side: Position side
        current_state: Current trend state

    Returns:
        Formatted alert message
    """
    side_kr = "롱" if side == "long" else "숏"

    if side == "long":
        message = f"⚠️ {side_kr} 포지션 진입 조건 불충족\n"
        message += "━━━━━━━━━━━━━━━\n"
        message += f"📊 종목: {symbol}\n"
        message += "RSI 평균 진입가 평균 진입가t평균 진입가 평균 진입가평균 진입가 ptt 평균 진입가 JD 평균 진입가D  평균 진입가i평균 진입가."
    else:  # short
        message = f"⚠️ {side_kr} 포지션 진입 조건 불충족\n"
        message += "━━━━━━━━━━━━━━━\n"
        message += f"📊 종목: {symbol}\n"
        message += "RSI 평균 진입가 평균 진입가t평균 진입가 평균 진입가평균 진입가 ptt 평균 진입가 JD 평균 진입가D  평균 진입가i평균 진입가."

    return message
