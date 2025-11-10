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
        candles_df: pd.DataFrame,
        use_longer_trend: bool = False,
        use_custom_length: bool = False,
        custom_length: int = 10,
        current_timeframe_minutes: Optional[int] = None
    ) -> int:
        """
        Calculate PineScript-based trend state using shared indicators.

        Uses the same logic as HYPERRSI production system:
        - JMA/T3 + VIDYA moving averages
        - Rational quadratic smoothing
        - Bollinger Band Width (BBW) analysis
        - CYCLE_Bull/CYCLE_Bear conditions
        - State persistence (PineScript 'var' behavior)

        Returns 3-level system:
        - +2: Extreme uptrend (CYCLE_Bull + BB_State=2)
        - 0: Neutral
        - -2: Extreme downtrend (CYCLE_Bear + BB_State=-2)

        Args:
            candles_df: DataFrame with columns: timestamp, open, high, low, close, volume
            use_longer_trend: Use longer timeframe trend (T3 20,40,120)
            use_custom_length: Use custom MA lengths
            custom_length: Custom MA base length

        Returns:
            Trend state: -2, 0, or 2
        """
        from shared.indicators import compute_all_indicators

        # Minimum data requirement (based on longest MA + rational_quadratic lookback)
        min_required = 200  # Safe buffer for all calculations
        if len(candles_df) < min_required:
            logger.debug(f"Insufficient data for PineScript trend calculation: {len(candles_df)} < {min_required}")
            return 0

        # Convert DataFrame to candle dict list
        candles = []
        for idx, row in candles_df.iterrows():
            candles.append({
                "timestamp": int(row.name.timestamp()) if isinstance(row.name, pd.Timestamp) else int(idx),
                "open": float(row['open']),
                "high": float(row['high']),
                "low": float(row['low']),
                "close": float(row['close']),
                "volume": float(row['volume'])
            })

        # Calculate indicators using PineScript logic
        try:
            candles_with_indicators = compute_all_indicators(
                candles,
                rsi_period=14,
                atr_period=14,
                use_longer_trend=use_longer_trend,
                use_custom_length=use_custom_length,
                custom_length=custom_length,
                current_timeframe_minutes=current_timeframe_minutes
            )

            # Get the last candle's trend_state
            last_candle = candles_with_indicators[-1]
            trend_state = last_candle.get('trend_state', 0)

            logger.debug(
                f"PineScript trend state calculated: state={trend_state}, "
                f"CYCLE_Bull={last_candle.get('CYCLE_Bull')}, "
                f"CYCLE_Bear={last_candle.get('CYCLE_Bear')}, "
                f"BB_State={last_candle.get('BB_State')}"
            )

            return trend_state

        except Exception as e:
            logger.error(f"Error calculating PineScript trend state: {e}")
            return 0

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
