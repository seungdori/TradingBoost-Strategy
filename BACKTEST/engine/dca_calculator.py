"""
DCA (Dollar Cost Averaging) calculation utilities for backtesting.

Ported from HYPERRSI live trading system (trading_utils.py).
"""

from typing import List, Optional, Dict, Any
from shared.logging import get_logger

logger = get_logger(__name__)


def calculate_dca_levels(
    entry_price: float,
    last_filled_price: float,
    settings: Dict[str, Any],
    side: str,
    atr_value: Optional[float],
    current_price: float
) -> List[float]:
    """
    Calculate DCA price levels for additional entries.

    Ported from: HYPERRSI/src/trading/utils/trading_utils.py:calculate_dca_levels()

    Args:
        entry_price: Average entry price of position
        last_filled_price: Most recent filled entry price
        settings: Strategy settings dict containing:
            - pyramiding_entry_type: '퍼센트 기준' | '금액 기준' | 'ATR 기준'
            - pyramiding_value: Distance value for DCA levels
            - pyramiding_limit: Max number of additional entries (default: 3)
            - entry_criterion: '평균 단가' | '최근 진입가'
        side: Position side ('long' or 'short')
        atr_value: ATR indicator value (required for ATR-based calculation)
        current_price: Current market price (for logging)

    Returns:
        List of DCA level prices (length = pyramiding_limit)

    Example:
        >>> settings = {
        ...     'pyramiding_entry_type': '퍼센트 기준',
        ...     'pyramiding_value': 3.0,
        ...     'pyramiding_limit': 3,
        ...     'entry_criterion': '평균 단가'
        ... }
        >>> levels = calculate_dca_levels(
        ...     entry_price=100.0,
        ...     last_filled_price=100.0,
        ...     settings=settings,
        ...     side='long',
        ...     atr_value=2.0,
        ...     current_price=98.0
        ... )
        >>> levels
        [97.0, 94.09, 91.27]  # Each level 3% below previous
    """
    # Determine reference price based on criterion
    entry_criterion = settings.get('entry_criterion', '평균 단가')
    if entry_criterion == "평균 단가":
        reference_price = entry_price
    else:  # "최근 진입가"
        reference_price = last_filled_price

    # Get calculation parameters
    pyramiding_entry_type = settings.get('pyramiding_entry_type', '퍼센트 기준')
    pyramiding_value = settings.get('pyramiding_value', 3.0)
    pyramiding_limit = settings.get('pyramiding_limit', 3)

    # Generate multiple DCA levels sequentially
    dca_levels = []
    base_price = reference_price

    for i in range(1, pyramiding_limit + 1):
        # Calculate DCA level based on entry type
        if pyramiding_entry_type == "퍼센트 기준":
            # Percentage-based calculation
            if side == "long":
                level = base_price * (1 - (pyramiding_value / 100))
            else:  # short
                level = base_price * (1 + (pyramiding_value / 100))

        elif pyramiding_entry_type == "금액 기준":
            # Fixed amount calculation
            if side == "long":
                level = base_price - pyramiding_value
            else:  # short
                level = base_price + pyramiding_value

        else:  # "ATR 기준"
            # ATR-based calculation
            if atr_value is None or atr_value == 0:
                logger.warning(
                    f"ATR value is {atr_value}, cannot calculate ATR-based DCA level. "
                    f"Falling back to percentage-based with 3%"
                )
                if side == "long":
                    level = base_price * 0.97  # 3% below
                else:
                    level = base_price * 1.03  # 3% above
            else:
                if side == "long":
                    level = base_price - (atr_value * pyramiding_value)
                else:  # short
                    level = base_price + (atr_value * pyramiding_value)

        dca_levels.append(level)
        base_price = level  # 다음 레벨은 이전 레벨 기준으로 계산

    logger.debug(
        f"DCA levels calculated: {dca_levels} "
        f"(type={pyramiding_entry_type}, value={pyramiding_value}, "
        f"limit={pyramiding_limit}, reference={reference_price:.2f}, side={side})"
    )

    return dca_levels


def check_dca_condition(
    current_price: float,
    dca_levels: List[float],
    side: str,
    use_check_DCA_with_price: bool
) -> bool:
    """
    Check if DCA entry condition is met.

    Ported from: HYPERRSI/src/trading/utils/trading_utils.py:check_dca_condition()

    Args:
        current_price: Current market price
        dca_levels: List of calculated DCA price levels
        side: Position side ('long' or 'short')
        use_check_DCA_with_price: If False, always returns True (for testing)

    Returns:
        True if DCA condition met, False otherwise

    Logic:
        - For long positions: triggers when price <= DCA level (price dropped)
        - For short positions: triggers when price >= DCA level (price rose)
        - If use_check_DCA_with_price is False, always triggers (testing mode)

    Example:
        >>> check_dca_condition(
        ...     current_price=97.0,
        ...     dca_levels=[98.0],
        ...     side='long',
        ...     use_check_DCA_with_price=True
        ... )
        True  # Price 97 <= Level 98, long DCA triggers
    """
    if not use_check_DCA_with_price:
        # Testing mode: always trigger
        return True

    if not dca_levels:
        # No DCA levels set
        return False

    next_dca_level = float(dca_levels[0])

    if side == "long":
        # Long position: trigger when price drops to or below DCA level
        return current_price <= next_dca_level
    else:  # short
        # Short position: trigger when price rises to or above DCA level
        return current_price >= next_dca_level


def calculate_dca_entry_size(
    initial_investment: float,
    initial_contracts: float,
    dca_count: int,
    entry_multiplier: float,
    current_price: float,
    leverage: float
) -> tuple[float, float]:
    """
    Calculate investment and contract quantity for DCA entry.

    Uses exponential scaling: Entry N = Initial × (multiplier ^ N)

    Args:
        initial_investment: Investment amount of first entry (USDT)
        initial_contracts: Contract quantity of first entry
        dca_count: Current DCA count (0 = first DCA, 1 = second DCA, etc.)
        entry_multiplier: Scale factor (e.g., 0.5 = 50% of previous)
        current_price: Current market price
        leverage: Leverage multiplier

    Returns:
        Tuple of (investment_amount, contract_quantity)

    Example:
        >>> calculate_dca_entry_size(
        ...     initial_investment=100.0,
        ...     initial_contracts=10.0,
        ...     dca_count=1,  # First additional entry
        ...     entry_multiplier=0.5,
        ...     current_price=95.0,
        ...     leverage=10
        ... )
        (50.0, 5.0)  # 100 × 0.5^1 = 50, 10 × 0.5^1 = 5

        >>> calculate_dca_entry_size(
        ...     initial_investment=100.0,
        ...     initial_contracts=10.0,
        ...     dca_count=2,  # Second additional entry
        ...     entry_multiplier=0.5,
        ...     current_price=90.0,
        ...     leverage=10
        ... )
        (25.0, 2.5)  # 100 × 0.5^2 = 25, 10 × 0.5^2 = 2.5
    """
    # Calculate scaled amounts using exponential decay
    scale = entry_multiplier ** dca_count

    new_investment = float(initial_investment) * scale
    new_contracts = float(initial_contracts) * scale

    logger.debug(
        f"DCA entry size calculated: investment={new_investment:.2f} USDT, "
        f"contracts={new_contracts:.4f} (scale={scale:.4f}, dca_count={dca_count})"
    )

    return new_investment, new_contracts


def check_rsi_condition_for_dca(
    rsi: Optional[float],
    side: str,
    rsi_oversold: float,
    rsi_overbought: float,
    use_rsi_with_pyramiding: bool
) -> bool:
    """
    Check if RSI condition allows DCA entry.

    Args:
        rsi: Current RSI value
        side: Position side ('long' or 'short')
        rsi_oversold: RSI oversold threshold (e.g., 30)
        rsi_overbought: RSI overbought threshold (e.g., 70)
        use_rsi_with_pyramiding: If False, always returns True

    Returns:
        True if RSI condition met, False otherwise

    Logic:
        - For long positions: RSI must be <= oversold threshold
        - For short positions: RSI must be >= overbought threshold
        - If use_rsi_with_pyramiding is False, always passes

    Example:
        >>> check_rsi_condition_for_dca(
        ...     rsi=28.0,
        ...     side='long',
        ...     rsi_oversold=30.0,
        ...     rsi_overbought=70.0,
        ...     use_rsi_with_pyramiding=True
        ... )
        True  # RSI 28 <= 30, long DCA allowed
    """
    if not use_rsi_with_pyramiding:
        # RSI check disabled
        return True

    if rsi is None:
        logger.debug("RSI value is None, skipping RSI condition check")
        return False

    if side == "long":
        # Long DCA: RSI must be oversold
        is_oversold = rsi <= rsi_oversold

        return is_oversold
    else:  # short
        # Short DCA: RSI must be overbought
        is_overbought = rsi >= rsi_overbought

        return is_overbought


def check_trend_condition_for_dca(
    ema: Optional[float],
    sma: Optional[float],
    side: str,
    use_trend_logic: bool,
    trend_state: Optional[int] = None
) -> bool:
    """
    Check if trend condition allows DCA entry.

    Uses both trend_state (PineScript) and EMA/SMA relationship to determine trend strength.
    Priority: trend_state check first (strong filter), then EMA/SMA check (weak filter).

    Args:
        ema: EMA (ma7) indicator value
        sma: SMA (ma20) indicator value
        side: Position side ('long' or 'short')
        use_trend_logic: If False, always returns True
        trend_state: Trend state from PineScript indicator (-2: strong downtrend, 0: neutral, 2: strong uptrend)

    Returns:
        True if trend condition met, False otherwise

    Logic:
        1. If use_trend_logic is False, always passes
        2. If trend_state provided, apply strong filter:
           - Block LONG DCA when trend_state == -2 (strong downtrend)
           - Block SHORT DCA when trend_state == 2 (strong uptrend)
        3. Fallback to EMA/SMA relationship check:
           - For long positions: NOT in strong downtrend (EMA not too far below SMA)
           - For short positions: NOT in strong uptrend (EMA not too far above SMA)
           - Strong trend defined as EMA/SMA ratio > 2% divergence

    Example:
        >>> check_trend_condition_for_dca(
        ...     ema=100.0,
        ...     sma=105.0,
        ...     side='long',
        ...     use_trend_logic=True,
        ...     trend_state=-2
        ... )
        False  # trend_state=-2 blocks long DCA

        >>> check_trend_condition_for_dca(
        ...     ema=100.0,
        ...     sma=105.0,
        ...     side='long',
        ...     use_trend_logic=True,
        ...     trend_state=0
        ... )
        True  # trend_state=0 (neutral) allows DCA

        >>> check_trend_condition_for_dca(
        ...     ema=100.0,
        ...     sma=110.0,
        ...     side='long',
        ...     use_trend_logic=True,
        ...     trend_state=None
        ... )
        False  # EMA 9% below SMA, strong downtrend - block long DCA
    """
    if not use_trend_logic:
        # Trend check disabled
        return True

    # === Priority 1: trend_state check (strong filter) ===
    # Matches SignalGenerator.check_long_signal() logic (BACKTEST/strategies/signal_generator.py:101-102)
    if trend_state is not None:
        if side == "long":
            if trend_state == -2:
                logger.debug(
                    f"[DCA] ❌ LONG DCA BLOCKED by trend_state: trend_state={trend_state} (strong downtrend)"
                )
                return False
            else:
                logger.debug(
                    f"[DCA] ✅ LONG DCA ALLOWED by trend_state: trend_state={trend_state}"
                )
                return True
        else:  # short
            if trend_state == 2:
                logger.debug(
                    f"[DCA] ❌ SHORT DCA BLOCKED by trend_state: trend_state={trend_state} (strong uptrend)"
                )
                return False
            else:
                logger.debug(
                    f"[DCA] ✅ SHORT DCA ALLOWED by trend_state: trend_state={trend_state}"
                )
                return True

    # === Priority 2: EMA/SMA check (fallback weak filter) ===
    if ema is None or sma is None:
        logger.debug("EMA or SMA is None, skipping trend condition check")
        return False

    # Calculate trend strength
    trend_ratio = (ema - sma) / sma if sma != 0 else 0
    strong_trend_threshold = 0.02  # 2% divergence

    if side == "long":
        # Long DCA: Allow if NOT in strong downtrend
        # Strong downtrend = EMA significantly below SMA
        is_strong_downtrend = trend_ratio < -strong_trend_threshold
        allow_dca = not is_strong_downtrend

        logger.debug(
            f"Trend condition for long DCA: EMA={ema:.2f}, SMA={sma:.2f}, "
            f"trend_ratio={trend_ratio:.4f}, strong_downtrend={is_strong_downtrend}, "
            f"allow={allow_dca}"
        )
        return allow_dca
    else:  # short
        # Short DCA: Allow if NOT in strong uptrend
        # Strong uptrend = EMA significantly above SMA
        is_strong_uptrend = trend_ratio > strong_trend_threshold
        allow_dca = not is_strong_uptrend

        logger.debug(
            f"Trend condition for short DCA: EMA={ema:.2f}, SMA={sma:.2f}, "
            f"trend_ratio={trend_ratio:.4f}, strong_uptrend={is_strong_uptrend}, "
            f"allow={allow_dca}"
        )
        return allow_dca
