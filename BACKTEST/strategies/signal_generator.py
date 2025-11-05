"""
Signal generator for HYPERRSI strategy.

Simplified version of HYPERRSI signal logic for backtesting.
"""

from typing import Optional, Tuple
import pandas as pd
import numpy as np

from shared.logging import get_logger

logger = get_logger(__name__)


class SignalGenerator:
    """
    Generates trading signals based on RSI and trend indicators.

    Ported from HYPERRSI/src/trading/modules/market_data_service.py
    """

    def __init__(
        self,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        rsi_period: int = 14,
        use_trend_filter: bool = True,
        entry_option: str = "초과"
    ):
        """
        Initialize signal generator.

        Args:
            rsi_oversold: RSI oversold level
            rsi_overbought: RSI overbought level
            rsi_period: RSI calculation period
            use_trend_filter: Whether to use trend filter
            entry_option: RSI entry logic ('돌파' | '변곡돌파' | '초과')
        """
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.rsi_period = rsi_period
        self.use_trend_filter = use_trend_filter
        self.entry_option = entry_option

    def check_long_signal(
        self,
        rsi: float,
        trend_state: Optional[int] = None,
        previous_rsi: Optional[float] = None
    ) -> Tuple[bool, str]:
        """
        Check for long entry signal.

        Ported from HYPERRSI/src/trading/modules/market_data_service.py

        Args:
            rsi: Current RSI value
            trend_state: Trend state (1=bullish, -1=bearish, 0=neutral)
            previous_rsi: Previous RSI value (required for '돌파' and '변곡돌파')

        Returns:
            Tuple of (has_signal, reason)
        """
        # RSI oversold check based on entry_option
        is_oversold = False

        if self.entry_option == '돌파':
            # 롱: RSI가 oversold 선을 아래로 돌파 (crossunder)
            if previous_rsi is None:
                return False, "Previous RSI required for '돌파'"
            is_oversold = previous_rsi > self.rsi_oversold and rsi <= self.rsi_oversold

        elif self.entry_option == '변곡':
            # 롱: RSI가 oversold 영역에서 반등 시작 (방향 전환)
            if previous_rsi is None:
                return False, "Previous RSI required for '변곡'"
            is_oversold = ((previous_rsi < self.rsi_oversold) or (rsi < self.rsi_oversold)) and rsi > previous_rsi

        elif self.entry_option == '변곡돌파':
            # 롱: RSI가 oversold 아래에서 위로 반등 (crossover)
            if previous_rsi is None:
                return False, "Previous RSI required for '변곡돌파'"
            is_oversold = rsi >= self.rsi_oversold and previous_rsi < self.rsi_oversold

        elif self.entry_option == '초과':
            # 롱: 단순히 RSI < oversold
            is_oversold = rsi < self.rsi_oversold

        else:
            # 기본 동작 (기존 코드와 동일)
            is_oversold = rsi < self.rsi_oversold

        if not is_oversold:
            return False, f"RSI not oversold ({self.entry_option})"

        # Trend filter (matching HYPERRSI validation.py:344-346)
        # HYPERRSI blocks LONG only on -2 (strong downtrend)
        if self.use_trend_filter and trend_state is not None:
            if trend_state == -2:
                return False, "Strong downtrend detected - long entry blocked"
            elif trend_state == 2:
                return True, f"RSI oversold ({self.entry_option}) + strong uptrend"
            elif trend_state == 1:
                return True, f"RSI oversold ({self.entry_option}) + uptrend"
            elif trend_state == -1:
                return True, f"RSI oversold ({self.entry_option}) + downtrend (allowed)"
            else:
                return True, f"RSI oversold ({self.entry_option}) + neutral trend"

        return True, f"RSI oversold ({self.entry_option})"

    def check_short_signal(
        self,
        rsi: float,
        trend_state: Optional[int] = None,
        previous_rsi: Optional[float] = None
    ) -> Tuple[bool, str]:
        """
        Check for short entry signal.

        Ported from HYPERRSI/src/trading/modules/market_data_service.py

        Args:
            rsi: Current RSI value
            trend_state: Trend state (1=bullish, -1=bearish, 0=neutral)
            previous_rsi: Previous RSI value (required for '돌파' and '변곡돌파')

        Returns:
            Tuple of (has_signal, reason)
        """
        # RSI overbought check based on entry_option
        is_overbought = False

        if self.entry_option == '돌파':
            # 숏: RSI가 overbought 선을 위로 돌파 (crossover)
            if previous_rsi is None:
                return False, "Previous RSI required for '돌파'"
            is_overbought = previous_rsi < self.rsi_overbought and rsi >= self.rsi_overbought

        elif self.entry_option == '변곡':
            # 숏: RSI가 overbought 영역에서 하락 시작 (방향 전환)
            if previous_rsi is None:
                return False, "Previous RSI required for '변곡'"
            is_overbought = ((previous_rsi > self.rsi_overbought) or (rsi > self.rsi_overbought)) and rsi < previous_rsi

        elif self.entry_option == '변곡돌파':
            # 숏: RSI가 overbought 위에서 아래로 하락 (crossunder)
            if previous_rsi is None:
                return False, "Previous RSI required for '변곡돌파'"
            is_overbought = rsi <= self.rsi_overbought and previous_rsi > self.rsi_overbought

        elif self.entry_option == '초과':
            # 숏: 단순히 RSI > overbought
            is_overbought = rsi > self.rsi_overbought

        else:
            # 기본 동작 (기존 코드와 동일)
            is_overbought = rsi > self.rsi_overbought

        if not is_overbought:
            return False, f"RSI not overbought ({self.entry_option})"

        # Trend filter (matching HYPERRSI validation.py:350-352)
        # HYPERRSI blocks SHORT only on +2 (strong uptrend)
        if self.use_trend_filter and trend_state is not None:
            if trend_state == 2:
                return False, "Strong uptrend detected - short entry blocked"
            elif trend_state == -2:
                return True, f"RSI overbought ({self.entry_option}) + strong downtrend"
            elif trend_state == -1:
                return True, f"RSI overbought ({self.entry_option}) + downtrend"
            elif trend_state == 1:
                return True, f"RSI overbought ({self.entry_option}) + uptrend (allowed)"
            else:
                return True, f"RSI overbought ({self.entry_option}) + neutral trend"

        return True, f"RSI overbought ({self.entry_option})"

    def calculate_trend_state(
        self,
        closes: pd.Series,
        highs: Optional[pd.Series] = None,
        lows: Optional[pd.Series] = None,
        ma20_period: int = 20,
        ma60_period: int = 60,
        bb_period: int = 20,
        bb_std: float = 2.0,
        momentum_period: int = 20
    ) -> int:
        """
        Calculate trend state matching HYPERRSI's 5-level system.

        Uses Bollinger Bands, moving averages, and momentum to determine:
        - +2: Strong uptrend (price > BB upper, momentum > 0)
        - +1: Uptrend (price > MA20 > MA60, momentum > 0)
        -  0: Neutral (price within BB)
        - -1: Downtrend (price < MA20 < MA60, momentum < 0)
        - -2: Strong downtrend (price < BB lower, momentum < 0)

        Mirrors HYPERRSI/src/api/trading/trend_state_calculator.py:analyze_market_state_from_redis()

        Args:
            closes: Series of close prices (minimum 21 periods)
            highs: Series of high prices (for BB calculation, optional)
            lows: Series of low prices (for BB calculation, optional)
            ma20_period: MA20 period (default: 20)
            ma60_period: MA60 period (default: 60)
            bb_period: Bollinger Band period (default: 20)
            bb_std: Bollinger Band standard deviation multiplier (default: 2.0)
            momentum_period: Momentum calculation period (default: 20)

        Returns:
            Trend state: -2, -1, 0, 1, or 2
        """
        required_periods = max(ma60_period, bb_period, momentum_period) + 1
        if len(closes) < required_periods:
            logger.debug(f"Insufficient data for trend calculation: {len(closes)} < {required_periods}")
            return 0

        # Current price and historical price for momentum
        current_price = closes.iloc[-1]

        # Calculate 20-period momentum: (current - price_20_ago) / price_20_ago
        if len(closes) >= momentum_period + 1:
            price_20_ago = closes.iloc[-(momentum_period + 1)]
            momentum = (current_price - price_20_ago) / price_20_ago
        else:
            momentum = 0

        # Calculate moving averages
        ma20 = closes.rolling(window=ma20_period).mean().iloc[-1]
        ma60 = closes.rolling(window=ma60_period).mean().iloc[-1]

        # Calculate Bollinger Bands
        bb_middle = closes.rolling(window=bb_period).mean().iloc[-1]
        bb_std_val = closes.rolling(window=bb_period).std().iloc[-1]
        upper_band = bb_middle + (bb_std_val * bb_std)
        lower_band = bb_middle - (bb_std_val * bb_std)

        # Determine trend state (matching HYPERRSI logic exactly)
        extreme_state = 0  # Default: neutral

        if current_price > upper_band and momentum > 0:
            extreme_state = 2  # Strong uptrend
        elif current_price > ma20 and ma20 > ma60 and momentum > 0:
            extreme_state = 1  # Uptrend
        elif current_price >= lower_band and current_price <= upper_band:
            extreme_state = 0  # Neutral
        elif current_price < ma20 and ma20 < ma60 and momentum < 0:
            extreme_state = -1  # Downtrend
        elif current_price < lower_band and momentum < 0:
            extreme_state = -2  # Strong downtrend

        logger.debug(
            f"Trend state calculated: state={extreme_state}, price={current_price:.2f}, "
            f"BB=[{lower_band:.2f}, {upper_band:.2f}], MA20={ma20:.2f}, MA60={ma60:.2f}, "
            f"momentum={momentum:.4f}"
        )

        return extreme_state

    @staticmethod
    def calculate_rsi(closes: pd.Series, period: int = 14) -> Optional[float]:
        """
        Calculate RSI indicator.

        Args:
            closes: Series of close prices
            period: RSI period

        Returns:
            RSI value or None if insufficient data
        """
        if len(closes) < period + 1:
            return None

        # Calculate price changes
        delta = closes.diff()

        # Separate gains and losses
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        # Calculate average gain and loss
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()

        # Calculate RS and RSI
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))

        return rsi.iloc[-1]

    @staticmethod
    def calculate_atr(
        highs: pd.Series,
        lows: pd.Series,
        closes: pd.Series,
        period: int = 14
    ) -> Optional[float]:
        """
        Calculate ATR (Average True Range) indicator.

        Args:
            highs: Series of high prices
            lows: Series of low prices
            closes: Series of close prices
            period: ATR period

        Returns:
            ATR value or None if insufficient data
        """
        if len(closes) < period + 1:
            return None

        # Calculate True Range
        high_low = highs - lows
        high_close = abs(highs - closes.shift())
        low_close = abs(lows - closes.shift())

        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)

        # Calculate ATR
        atr = tr.rolling(window=period).mean()

        return atr.iloc[-1]
