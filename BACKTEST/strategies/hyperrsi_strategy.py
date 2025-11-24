"""
HYPERRSI strategy implementation for backtesting.

Combines RSI (Relative Strength Index) with optional trend confirmation and
supports configurable DCA (Dollar Cost Averaging) / pyramiding behaviour.
"""

from typing import Optional, Tuple, Dict, Any
import pandas as pd

from BACKTEST.strategies.base_strategy import BaseStrategy, TradingSignal
from BACKTEST.strategies.signal_generator import SignalGenerator
from BACKTEST.models.candle import Candle
from BACKTEST.models.trade import TradeSide
from shared.logging import get_logger

logger = get_logger(__name__)


class HyperrsiStrategy(BaseStrategy):
    """
    HYPERRSI strategy for backtesting.

    Entry signals rely on RSI oversold/overbought states with optional trend
    confirmation. TP/SL can be fixed percentage or dynamic ATR-based.

    DCA / Pyramiding parameters (phase 1):
        pyramiding_enabled (bool): Master switch for additional entries
        pyramiding_limit (int): Max additional entries (0-10)
        entry_multiplier (float): Scale factor per additional entry (0.1-10.0, default: 1.6)
        pyramiding_entry_type (str): '퍼센트 기준' | '금액 기준' | 'ATR 기준'
        pyramiding_value (float): Distance to next entry level
        entry_criterion (str): '평균 단가' | '최근 진입가'
        use_check_DCA_with_price (bool): Require price trigger hit
        use_rsi_with_pyramiding (bool): Enforce RSI condition for DCA
        use_trend_logic (bool): Enforce trend filter for DCA
    """

    DEFAULT_PARAMS: Dict[str, Any] = {
        # Entry configuration
        "entry_option": "rsi_trend",  # "rsi_only" or "rsi_trend" (trend filter)
        "rsi_entry_option": "초과",    # RSI entry logic: '돌파' | '변곡돌파' | '초과'
        "direction": "both",  # Trading direction: "long", "short", or "both"

        # RSI parameters
        "rsi_oversold": 30,
        "rsi_overbought": 70,
        "rsi_period": 14,

        # Position sizing
        "leverage": 10,
        "investment": 100,

        # TP/SL configuration
        "tp_sl_option": "fixed",
        "stop_loss_percent": 2.0,
        "take_profit_percent": 4.0,
        "atr_sl_multiplier": 2.0,
        "atr_tp_multiplier": 3.0,

        # Partial exits TP option (NEW!)
        "tp_option": "percentage",  # "percentage", "atr", or "price"

        # Trailing stop (backward compatible)
        "trailing_stop_enabled": False,
        "trailing_stop_percent": 2.0,

        # HYPERRSI-style trailing stop
        "trailing_stop_active": False,
        "trailing_start_point": "tp3",  # "tp1", "tp2", or "tp3"
        "trailing_stop_offset_value": 0.5,  # Percentage
        "use_trailing_stop_value_with_tp2_tp3_difference": False,

        # Break even settings
        "use_break_even": True,  # TP1 hit → move SL to entry price
        "use_break_even_tp2": True,  # TP2 hit → move SL to TP1 price
        "use_break_even_tp3": True,  # TP3 hit → move SL to TP2 price

        # DCA / Pyramiding defaults
        "pyramiding_enabled": True,
        "pyramiding_limit": 3,
        "entry_multiplier": 1.6,
        "pyramiding_entry_type": "퍼센트 기준",
        "pyramiding_value": 3.0,
        "entry_criterion": "평균 단가",
        "use_check_DCA_with_price": True,
        "use_rsi_with_pyramiding": True,
        "use_trend_logic": True,
    }

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        """
        Initialize HYPERRSI strategy.

        Expected params:
        - entry_option: "rsi_only" or "rsi_trend"
        - rsi_oversold: RSI oversold level (default 30)
        - rsi_overbought: RSI overbought level (default 70)
        - rsi_period: RSI calculation period (default 14)
        - leverage: Leverage multiplier (default 10)
        - investment: Investment amount per trade (default 100 USDT)
        - tp_sl_option: "fixed" or "dynamic_atr"
        - stop_loss_percent: SL percentage (default 2.0%)
        - take_profit_percent: TP percentage (default 4.0%)
        - atr_sl_multiplier: ATR multiplier for SL (default 2.0)
        - atr_tp_multiplier: ATR multiplier for TP (default 3.0)
        - trailing_stop_enabled: Enable trailing stop (default False)
        - trailing_stop_percent: Trailing stop % (default 2.0%)
        """
        merged_params: Dict[str, Any] = {**self.DEFAULT_PARAMS}
        if params:
            merged_params.update(params)

        # 한국어 파라미터를 영어로 매핑 (백테스트 호환성)
        merged_params = self._map_korean_params_to_english(merged_params)

        super().__init__(merged_params)
        self.params = merged_params

        # Entry configuration
        self.entry_option = self.params["entry_option"]  # "rsi_only" or "rsi_trend"
        self.use_trend_filter = self.entry_option == "rsi_trend"
        self.rsi_entry_option = self.params.get("rsi_entry_option", "초과")  # '돌파' | '변곡돌파' | '초과'

        # Trading direction configuration
        # Support both new direction parameter and legacy use_long/use_short for backward compatibility
        self.direction = self.params.get("direction", "both")

        # Backward compatibility: if use_long/use_short specified, derive direction
        if "use_long" in self.params or "use_short" in self.params:
            use_long = self.params.get("use_long", True)
            use_short = self.params.get("use_short", True)
            if use_long and use_short:
                self.direction = "both"
            elif use_long:
                self.direction = "long"
            elif use_short:
                self.direction = "short"
            else:
                # Neither long nor short enabled - default to both
                self.direction = "both"
            logger.info(
                f"Derived direction from legacy flags: use_long={use_long}, use_short={use_short} → direction='{self.direction}'"
            )

        # Signal generator
        self.signal_generator = SignalGenerator(
            rsi_oversold=float(self.params["rsi_oversold"]),
            rsi_overbought=float(self.params["rsi_overbought"]),
            rsi_period=int(self.params["rsi_period"]),
            use_trend_filter=self.use_trend_filter,
            entry_option=self.rsi_entry_option
        )

        # Position sizing
        self.leverage = float(self.params["leverage"])
        self.investment = float(self.params["investment"])

        # TP/SL configuration
        self.tp_sl_option = self.params["tp_sl_option"]

        # None 처리: SL/TP가 비활성화되면 None 허용
        sl_percent = self.params.get("stop_loss_percent")
        self.stop_loss_percent = float(sl_percent) if sl_percent is not None else None

        tp_percent = self.params.get("take_profit_percent")
        self.take_profit_percent = float(tp_percent) if tp_percent is not None else None

        self.atr_sl_multiplier = float(self.params.get("atr_sl_multiplier", 2.0))
        self.atr_tp_multiplier = float(self.params.get("atr_tp_multiplier", 3.0))

        # Trailing stop (backward compatible)
        self.trailing_stop_enabled = bool(self.params.get("trailing_stop_enabled", False))
        ts_percent = self.params.get("trailing_stop_percent", 2.0)
        self.trailing_stop_percent = float(ts_percent) if ts_percent is not None else 2.0

        # HYPERRSI-style trailing stop configuration
        self.trailing_stop_active = bool(self.params.get("trailing_stop_active", False))
        self.trailing_start_point = str(self.params.get("trailing_start_point", "tp3")).lower()  # "tp1", "tp2", or "tp3"
        self.trailing_stop_offset_value = float(self.params.get("trailing_stop_offset_value", 0.5))  # Offset percentage
        self.use_tp2_tp3_diff_for_offset = bool(self.params.get("use_trailing_stop_value_with_tp2_tp3_difference", False))

        # Break even configuration
        self.use_break_even = bool(self.params.get("use_break_even", True))  # TP1 hit → move SL to entry price
        self.use_break_even_tp2 = bool(self.params.get("use_break_even_tp2", True))  # TP2 hit → move SL to TP1
        self.use_break_even_tp3 = bool(self.params.get("use_break_even_tp3", True))  # TP3 hit → move SL to TP2

        # Trend reversal exit configuration
        self.use_trend_close = bool(self.params.get("use_trend_close", True))

        # Partial exits (TP1/TP2/TP3) - 먼저 설정
        self.use_tp1 = bool(self.params.get("use_tp1", False))
        self.use_tp2 = bool(self.params.get("use_tp2", False))
        self.use_tp3 = bool(self.params.get("use_tp3", False))
        self.tp1_ratio = float(self.params.get("tp1_ratio", 30)) / 100  # Convert to 0-1
        self.tp2_ratio = float(self.params.get("tp2_ratio", 30)) / 100
        self.tp3_ratio = float(self.params.get("tp3_ratio", 40)) / 100
        self.tp1_value = float(self.params.get("tp1_value", 2.0))  # TP1 profit target value
        self.tp2_value = float(self.params.get("tp2_value", 3.0))
        self.tp3_value = float(self.params.get("tp3_value", 4.0))

        # SL 설정
        self.use_sl = bool(self.params.get("use_sl", False))
        self.use_sl_on_last = bool(self.params.get("use_sl_on_last", False))
        self.sl_value = float(self.params.get("sl_value", 5.0))
        self.sl_option = self.params.get("sl_option", "percentage")

        # TP/SL 활성화 플래그 계산
        # TP: use_tp1/2/3 중 하나라도 True이면 활성화
        self.take_profit_enabled = any([self.use_tp1, self.use_tp2, self.use_tp3])

        # SL: 새로운 시스템(use_sl, use_sl_on_last) 또는 레거시 시스템(stop_loss_percent) 지원
        # 명시적으로 stop_loss_enabled가 설정된 경우 해당 값 사용
        if 'stop_loss_enabled' in params and params['stop_loss_enabled'] is not None:
            self.stop_loss_enabled = bool(params['stop_loss_enabled'])
        else:
            # 레거시 호환성: stop_loss_percent가 설정되어 있으면 자동으로 활성화
            has_legacy_sl = self.stop_loss_percent is not None and self.stop_loss_percent > 0
            self.stop_loss_enabled = self.use_sl or self.use_sl_on_last or has_legacy_sl

        # 로그 메시지 준비
        if 'stop_loss_enabled' in params and params['stop_loss_enabled'] is not None:
            sl_source = "explicit"
        else:
            has_legacy_sl = self.stop_loss_percent is not None and self.stop_loss_percent > 0
            sl_source = f"calculated (use_sl={self.use_sl}, use_sl_on_last={self.use_sl_on_last}, has_legacy_sl={has_legacy_sl})"

        logger.info(
            f"TP/SL enabled flags calculated: "
            f"take_profit_enabled={self.take_profit_enabled} (tp1={self.use_tp1}, tp2={self.use_tp2}, tp3={self.use_tp3}), "
            f"stop_loss_enabled={self.stop_loss_enabled} (source={sl_source})"
        )

        # TP option: "percentage", "atr", or "price"
        self.tp_option = str(self.params.get("tp_option", "percentage")).lower()

        # DCA / Pyramiding configuration
        self.pyramiding_enabled = bool(self.params["pyramiding_enabled"])
        self.pyramiding_limit = int(self.params["pyramiding_limit"])
        self.entry_multiplier = float(self.params["entry_multiplier"])
        self.pyramiding_entry_type = self.params["pyramiding_entry_type"]
        self.pyramiding_value = float(self.params["pyramiding_value"])
        self.entry_criterion = self.params["entry_criterion"]
        self.use_check_DCA_with_price = bool(self.params["use_check_DCA_with_price"])
        self.use_rsi_with_pyramiding = bool(self.params["use_rsi_with_pyramiding"])
        self.use_trend_logic = bool(self.params["use_trend_logic"])

        # Price history for indicators
        self.price_history: list[Candle] = []
        self.max_history = 100  # Keep last 100 candles

        # Data provider for loading historical data (set by backtest engine)
        self.data_provider = None
        self.symbol = None
        self.timeframe = None

        # Validate configuration eagerly for early feedback
        self.validate_params()

        logger.info(f"HyperrsiStrategy initialized: {self.params}")

    def set_data_provider(self, data_provider, symbol: str, timeframe: str):
        """
        Set data provider for loading historical data.

        Args:
            data_provider: DataProvider instance
            symbol: Trading symbol (e.g., "BTC-USDT")
            timeframe: Timeframe (e.g., "1h")
        """
        self.data_provider = data_provider
        self.symbol = symbol
        self.timeframe = timeframe
        logger.info(f"Data provider set for {symbol} {timeframe}")

    async def _load_historical_data(self, current_candle: 'Candle', needed: int = 61):
        """
        Load historical data if price_history is insufficient.

        This is called automatically when indicators need more data.
        Loads past data from DB to fill price_history for indicator calculation.

        Args:
            current_candle: Current candle being processed
            needed: Number of candles needed (default: 61 for trend calculation)
        """
        if self.data_provider is None:
            logger.warning("Cannot load historical data: data_provider not set")
            return

        current_count = len(self.price_history)

        if current_count >= needed:
            return  # Already have enough

        missing = needed - current_count
        logger.info(
            f"Loading {missing} historical candles to fill price_history "
            f"(current: {current_count}, needed: {needed})"
        )

        # Calculate start date for historical data
        from datetime import timedelta

        if self.timeframe == "1h":
            start_date = current_candle.timestamp - timedelta(hours=missing + 10)
        elif self.timeframe == "4h":
            start_date = current_candle.timestamp - timedelta(hours=(missing + 10) * 4)
        elif self.timeframe == "1d":
            start_date = current_candle.timestamp - timedelta(days=missing + 10)
        elif self.timeframe == "15m":
            start_date = current_candle.timestamp - timedelta(minutes=(missing + 10) * 15)
        else:
            start_date = current_candle.timestamp - timedelta(days=missing + 10)

        end_date = current_candle.timestamp

        # Load historical candles
        historical_candles = await self.data_provider.get_candles(
            self.symbol,
            self.timeframe,
            start_date,
            end_date
        )

        if historical_candles:
            # Prepend to price_history (oldest first)
            self.price_history = historical_candles + self.price_history

            # Trim to max_history
            if len(self.price_history) > self.max_history:
                self.price_history = self.price_history[-self.max_history:]

            logger.info(
                f"Loaded {len(historical_candles)} historical candles. "
                f"price_history now has {len(self.price_history)} candles."
            )
        else:
            logger.warning(
                f"Failed to load historical data from {start_date} to {end_date}"
            )

    async def calculate_rsi_from_history(self, current_candle: 'Candle') -> Optional[float]:
        """
        Calculate RSI from price_history, loading more data if needed.

        Args:
            current_candle: Current candle

        Returns:
            RSI value or None if calculation fails
        """
        import pandas as pd

        # Try to calculate with current history
        closes = pd.Series([c.close for c in self.price_history])
        rsi = self.signal_generator.calculate_rsi(closes, self.signal_generator.rsi_period)

        if rsi is None:
            # Not enough data - load more
            needed = self.signal_generator.rsi_period + 10
            logger.info(f"Loading {needed} candles for RSI calculation")
            await self._load_historical_data(current_candle, needed=needed)

            # Retry calculation
            closes = pd.Series([c.close for c in self.price_history])
            rsi = self.signal_generator.calculate_rsi(closes, self.signal_generator.rsi_period)

        return rsi

    async def calculate_trend_indicators(self, current_candle: 'Candle') -> tuple[Optional[float], Optional[float]]:
        """
        Calculate EMA and SMA from price_history, loading more data if needed.

        Args:
            current_candle: Current candle

        Returns:
            Tuple of (EMA, SMA) or (None, None) if calculation fails
        """
        import pandas as pd

        # Try to calculate with current history
        closes = pd.Series([c.close for c in self.price_history])

        # EMA (7-period) and SMA (20-period) - matching TimescaleDB columns (ma7, ma20)
        ema_period = 7
        sma_period = 20

        ema = closes.ewm(span=ema_period, adjust=False).mean().iloc[-1] if len(closes) >= ema_period else None
        sma = closes.rolling(window=sma_period).mean().iloc[-1] if len(closes) >= sma_period else None

        if ema is None or sma is None:
            # Not enough data - load more
            needed = max(ema_period, sma_period) + 10
            logger.info(f"Loading {needed} candles for EMA/SMA calculation")
            await self._load_historical_data(current_candle, needed=needed)

            # Retry calculation
            closes = pd.Series([c.close for c in self.price_history])
            ema = closes.ewm(span=ema_period, adjust=False).mean().iloc[-1] if len(closes) >= ema_period else None
            sma = closes.rolling(window=sma_period).mean().iloc[-1] if len(closes) >= sma_period else None

        return ema, sma

    async def generate_signal(self, candle: Candle) -> TradingSignal:
        """
        Generate trading signal for current candle.

        Args:
            candle: Current candle with indicators

        Returns:
            TradingSignal object
        """
        # Update price history
        self.price_history.append(candle)
        if len(self.price_history) > self.max_history:
            self.price_history.pop(0)

        # Extract price data
        closes = pd.Series([c.close for c in self.price_history])

        # Calculate RSI if not provided
        if candle.rsi is None:
            rsi = self.signal_generator.calculate_rsi(closes, self.signal_generator.rsi_period)

            if rsi is None:
                # Not enough data - load more historical data
                needed = self.signal_generator.rsi_period + 10
                logger.info(f"RSI is None, loading {needed} historical candles")
                await self._load_historical_data(candle, needed=needed)

                # Recalculate with loaded data
                closes = pd.Series([c.close for c in self.price_history])
                rsi = self.signal_generator.calculate_rsi(closes, self.signal_generator.rsi_period)

                if rsi is None:
                    logger.warning(f"RSI calc failed after loading history (size: {len(self.price_history)})")
                    return TradingSignal(side=None, reason="RSI calculation failed")
        else:
            rsi = candle.rsi

        # Get previous RSI for '돌파' and '변곡돌파' modes
        previous_rsi = None
        if len(self.price_history) >= 2:
            # Calculate previous RSI or use from previous candle
            if self.price_history[-2].rsi is not None:
                previous_rsi = self.price_history[-2].rsi
            else:
                # Calculate from price history
                prev_closes = pd.Series([c.close for c in self.price_history[:-1]])
                previous_rsi = self.signal_generator.calculate_rsi(prev_closes, self.signal_generator.rsi_period)

        # Calculate ATR if not provided
        atr = None
        if candle.atr is not None:
            atr = candle.atr
        else:
            # Calculate from price history
            if len(self.price_history) >= 15:  # Need at least 15 candles for ATR(14)
                highs = pd.Series([c.high for c in self.price_history])
                lows = pd.Series([c.low for c in self.price_history])
                closes_for_atr = pd.Series([c.close for c in self.price_history])
                atr = self.signal_generator.calculate_atr(highs, lows, closes_for_atr, period=14)
                if atr is not None:
                    logger.debug(f"Calculated ATR from price_history: {atr:.2f}")

        # Get trend state from candle if available (DB value), otherwise calculate
        trend_state = None
        if self.use_trend_filter:
            # ✅ Use DB trend_state if available (more reliable)
            if hasattr(candle, 'trend_state') and candle.trend_state is not None:
                trend_state = candle.trend_state
            else:
                # Fallback: Calculate from price_history if DB value not available
                candles_data = [{
                    'timestamp': c.timestamp,
                    'open': c.open,
                    'high': c.high,
                    'low': c.low,
                    'close': c.close,
                    'volume': c.volume
                } for c in self.price_history]

                candles_df = pd.DataFrame(candles_data)
                candles_df.set_index('timestamp', inplace=True)

                trend_state = self.signal_generator.calculate_trend_state(candles_df)
                logger.debug(f"Calculated trend_state from price_history: {trend_state}")

        # Debug logging for '돌파' mode
        if self.rsi_entry_option == "돌파":
            prev_rsi_str = f"{previous_rsi:.2f}" if previous_rsi is not None else "None"
            logger.debug(
                f"[돌파 CHECK] time={candle.timestamp}, price={candle.close:.2f}, "
                f"rsi={rsi:.2f}, prev_rsi={prev_rsi_str}, "
                f"trend={trend_state}, direction={self.direction}"
            )

        # Check long signal (if direction allows)
        if self.direction in ["long", "both"]:
            has_long, long_reason = self.signal_generator.check_long_signal(rsi, trend_state, previous_rsi)

            # Debug logging for signal check result
            if self.rsi_entry_option == "돌파":
                logger.debug(f"[돌파 LONG] has_signal={has_long}, reason={long_reason}")

            if has_long:
                prev_rsi_str = f"{previous_rsi:.2f}" if previous_rsi is not None else "None"
                logger.info(
                    f"LONG SIGNAL GENERATED: {long_reason}, "
                    f"rsi={rsi:.2f}, prev_rsi={prev_rsi_str}, trend={trend_state}"
                )
                return TradingSignal(
                    side=TradeSide.LONG,
                    reason=long_reason,
                    indicators={"rsi": rsi, "previous_rsi": previous_rsi, "trend_state": trend_state, "atr": atr}
                )

        # Check short signal (if direction allows)
        if self.direction in ["short", "both"]:
            has_short, short_reason = self.signal_generator.check_short_signal(rsi, trend_state, previous_rsi)
            if has_short:
                return TradingSignal(
                    side=TradeSide.SHORT,
                    reason=short_reason,
                    indicators={"rsi": rsi, "previous_rsi": previous_rsi, "trend_state": trend_state, "atr": atr}
                )

        return TradingSignal(
            side=None,
            reason="No signal",
            indicators={"rsi": rsi, "previous_rsi": previous_rsi, "trend_state": trend_state, "atr": atr}
        )

    def calculate_position_size(
        self,
        _signal: TradingSignal,
        current_balance: float,
        current_price: float
    ) -> Tuple[float, float]:
        """
        Calculate position size and leverage.

        Args:
            _signal: Trading signal (required by BaseStrategy interface, unused in implementation)
            current_balance: Current account balance
            current_price: Current market price

        Returns:
            Tuple of (quantity, leverage)
        """
        # Use fixed investment amount (matches HYPERRSI live trading logic)
        investment_amount = min(self.investment, current_balance * 0.95)

        # Calculate quantity with leverage
        # quantity = (investment_amount * leverage) / price
        quantity = (investment_amount * self.leverage) / current_price

        return quantity, self.leverage

    def calculate_tp_sl(
        self,
        side: TradeSide,
        entry_price: float,
        candle: Candle
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Calculate take profit and stop loss levels.

        Args:
            side: Position side
            entry_price: Entry price
            candle: Current candle with indicators

        Returns:
            Tuple of (take_profit_price, stop_loss_price)
        """
        take_profit = None
        stop_loss = None

        if self.tp_sl_option == "dynamic_atr" and candle.atr:
            # ATR-based TP/SL
            atr = candle.atr

            if side == TradeSide.LONG:
                if self.take_profit_enabled:
                    take_profit = entry_price + (atr * self.atr_tp_multiplier)
                if self.stop_loss_enabled:
                    stop_loss = entry_price - (atr * self.atr_sl_multiplier)
            else:  # SHORT
                if self.take_profit_enabled:
                    take_profit = entry_price - (atr * self.atr_tp_multiplier)
                if self.stop_loss_enabled:
                    stop_loss = entry_price + (atr * self.atr_sl_multiplier)

        else:
            # Fixed percentage TP/SL
            if side == TradeSide.LONG:
                if self.take_profit_enabled and self.take_profit_percent is not None:
                    take_profit = entry_price * (1 + self.take_profit_percent / 100)
                if self.stop_loss_enabled and self.stop_loss_percent is not None:
                    stop_loss = entry_price * (1 - self.stop_loss_percent / 100)
            else:  # SHORT
                if self.take_profit_enabled and self.take_profit_percent is not None:
                    take_profit = entry_price * (1 - self.take_profit_percent / 100)
                if self.stop_loss_enabled and self.stop_loss_percent is not None:
                    stop_loss = entry_price * (1 + self.stop_loss_percent / 100)

        logger.debug(
            f"TP/SL calculated: side={side.value}, entry={entry_price:.2f}, "
            f"TP={take_profit if take_profit else 'None'}, SL={stop_loss if stop_loss else 'None'}"
        )

        return take_profit, stop_loss

    def calculate_tp_levels(
        self,
        side: TradeSide,
        entry_price: float,
        atr_value: Optional[float] = None
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """
        Calculate TP1, TP2, TP3 levels for partial exits.

        Mirrors HYPERRSI's calculate_tp_prices() logic with 3 calculation options:
        - "percentage": entry_price * (1 ± tp_value/100)
        - "atr": entry_price ± (ATR × tp_value)
        - "price": entry_price ± tp_value

        Args:
            side: Position side
            entry_price: Entry price
            atr_value: ATR value (required for tp_option="atr")

        Returns:
            Tuple of (tp1_price, tp2_price, tp3_price)
            None for disabled TP levels
        """
        tp1 = None
        tp2 = None
        tp3 = None

        # Direction multiplier: +1 for LONG, -1 for SHORT
        multiplier = 1 if side == TradeSide.LONG else -1

        # Ensure 1ATR is at least 0.1% of entry price when using ATR-based TP
        if self.tp_option == "atr":
            min_atr = entry_price * 0.001  # 0.1% of entry price
            if atr_value is None:
                atr_value = min_atr
                logger.warning(f"Missing ATR value, using minimum 0.1%: {atr_value:.2f}")
            elif atr_value < min_atr:
                logger.info(f"ATR {atr_value:.2f} below minimum 0.1%, adjusted to {min_atr:.2f}")
                atr_value = min_atr

        # Calculate TP levels based on tp_option
        for i, (use_tp, tp_value) in enumerate([
            (self.use_tp1, self.tp1_value),
            (self.use_tp2, self.tp2_value),
            (self.use_tp3, self.tp3_value)
        ], start=1):
            if not use_tp or tp_value is None or tp_value <= 0:
                logger.debug(
                    f"Skipping TP{i}: use_tp={use_tp}, tp_value={tp_value}"
                )
                continue

            logger.debug(
                f"Calculating TP{i}: option={self.tp_option}, value={tp_value}, "
                f"entry={entry_price:.2f}, side={side.value}"
            )

            if self.tp_option == "percentage":
                # Percentage-based: entry_price * (1 ± tp_value/100)
                tp_percent = tp_value / 100
                raw_tp = entry_price * (1 + (multiplier * tp_percent))
                logger.debug(f"TP{i} percentage: {tp_percent*100:.2f}% → raw_tp={raw_tp:.2f}")

            elif self.tp_option == "atr":
                # ATR-based: entry_price ± (ATR × tp_value)
                raw_tp = entry_price + (multiplier * atr_value * tp_value)
                logger.debug(f"TP{i} ATR: atr={atr_value:.2f} × {tp_value} → raw_tp={raw_tp:.2f}")

            elif self.tp_option == "price":
                # Price-based: entry_price ± tp_value
                raw_tp = entry_price + (multiplier * tp_value)
                logger.debug(f"TP{i} price: ±{tp_value} → raw_tp={raw_tp:.2f}")

            else:
                logger.error(f"Invalid tp_option: {self.tp_option}, skipping TP{i}")
                continue

            # Apply safety bounds to ensure TP is profitable
            if side == TradeSide.LONG:
                tp_price = max(raw_tp, entry_price * 1.0001)
            else:  # SHORT
                tp_price = min(raw_tp, entry_price * 0.9999)

            # Assign to appropriate TP level
            if i == 1:
                tp1 = tp_price
            elif i == 2:
                tp2 = tp_price
            elif i == 3:
                tp3 = tp_price

        logger.debug(
            f"TP levels calculated: side={side.value}, entry={entry_price:.2f}, "
            f"option={self.tp_option}, "
            f"TP1={tp1 if tp1 else 'None'}, TP2={tp2 if tp2 else 'None'}, TP3={tp3 if tp3 else 'None'}"
        )

        return tp1, tp2, tp3

    def calculate_trailing_offset(
        self,
        side: TradeSide,
        current_price: float,
        tp2_price: Optional[float] = None,
        tp3_price: Optional[float] = None
    ) -> float:
        """
        Calculate trailing stop offset using HYPERRSI logic.

        Mirrors HYPERRSI's activate_trailing_stop() offset calculation:
        - If use_tp2_tp3_diff_for_offset: Use |TP3 - TP2| as offset
        - Otherwise: Use percentage of current price

        Args:
            side: Position side
            current_price: Current market price
            tp2_price: TP2 price (for TP2-TP3 difference method)
            tp3_price: TP3 price (for TP2-TP3 difference method)

        Returns:
            Trailing offset (absolute price difference)
        """
        if self.use_tp2_tp3_diff_for_offset and tp2_price and tp3_price:
            # Use TP2-TP3 price difference as offset (matches HYPERRSI live trading logic)
            if side == TradeSide.LONG:
                offset = abs(tp3_price - tp2_price)
            else:  # SHORT
                offset = abs(tp2_price - tp3_price)
            logger.debug(
                f"Trailing offset from TP2-TP3 difference: offset={offset:.2f} "
                f"(side={side.value}, tp2={tp2_price:.2f}, tp3={tp3_price:.2f})"
            )

        else:
            # Use percentage-based offset
            offset = abs(current_price * self.trailing_stop_offset_value * 0.01)
            logger.debug(
                f"Trailing offset from percentage: offset={offset:.2f} "
                f"({self.trailing_stop_offset_value}% of {current_price:.2f})"
            )

        return offset

    def should_activate_trailing_stop(
        self,
        unrealized_pnl_percent: float
    ) -> bool:
        """
        Check if trailing stop should be activated.

        Args:
            unrealized_pnl_percent: Current unrealized P&L percentage

        Returns:
            True if trailing stop should be activated
        """
        if not self.trailing_stop_enabled:
            return False

        # If any TP level is active, wait for trailing_start_point to trigger
        # Trailing stop will be activated by TP partial exit logic
        if self.use_tp1 or self.use_tp2 or self.use_tp3:
            return False  # Wait for TP level to activate via trailing_start_point

        # If no TP levels are active, activate trailing stop immediately when in profit
        return unrealized_pnl_percent >= 0

    def get_trailing_stop_params(
        self,
        candle: Candle
    ) -> Tuple[float, Optional[float], Optional[float]]:
        """
        Get trailing stop parameters.

        Args:
            candle: Current candle with indicators

        Returns:
            Tuple of (trailing_percent, atr_multiplier, atr_value)
        """
        trailing_percent = self.trailing_stop_percent

        # ATR-based trailing if available and using dynamic option
        atr_multiplier = None
        atr_value = None

        if self.tp_sl_option == "dynamic_atr" and candle.atr:
            atr_multiplier = self.atr_sl_multiplier
            atr_value = candle.atr

        return trailing_percent, atr_multiplier, atr_value

    def validate_params(self) -> bool:
        """
        Validate strategy parameters.

        Returns:
            True if parameters are valid

        Raises:
            ValueError: If parameters are invalid
        """
        if self.leverage <= 0:
            raise ValueError("Leverage must be positive")

        if self.investment <= 0:
            raise ValueError("Investment must be positive")

        # SL 검증: Legacy SL 또는 새로운 use_sl 시스템 검증
        if self.stop_loss_enabled:
            # Legacy 시스템: stop_loss_percent 사용
            if self.stop_loss_percent is not None:
                if not (0 < self.stop_loss_percent < 100):
                    raise ValueError("Stop loss percent must be between 0 and 100")
            # 새로운 시스템: use_sl 또는 use_sl_on_last 사용
            elif not (self.use_sl or self.use_sl_on_last):
                raise ValueError("Stop loss enabled but no SL configuration found")

        # TP 검증: Legacy TP 또는 새로운 partial exit 시스템 검증
        if self.take_profit_enabled:
            # Legacy 시스템: take_profit_percent 사용
            if self.take_profit_percent is not None:
                if not (0 < self.take_profit_percent < 100):
                    raise ValueError("Take profit percent must be between 0 and 100")
            # 새로운 partial exit 시스템: use_tp1/2/3 사용
            elif any([self.use_tp1, self.use_tp2, self.use_tp3]):
                # TP1/2/3 값 검증
                if self.use_tp1 and self.tp1_value <= 0:
                    raise ValueError("TP1 enabled but tp1_value is not positive")
                if self.use_tp2 and self.tp2_value <= 0:
                    raise ValueError("TP2 enabled but tp2_value is not positive")
                if self.use_tp3 and self.tp3_value <= 0:
                    raise ValueError("TP3 enabled but tp3_value is not positive")

                # TP 비율 검증
                if self.use_tp1 and not (0 < self.tp1_ratio <= 1):
                    raise ValueError("tp1_ratio must be between 0 and 1")
                if self.use_tp2 and not (0 < self.tp2_ratio <= 1):
                    raise ValueError("tp2_ratio must be between 0 and 1")
                if self.use_tp3 and not (0 < self.tp3_ratio <= 1):
                    raise ValueError("tp3_ratio must be between 0 and 1")
            else:
                raise ValueError("Take profit enabled but no TP configuration found")

        if self.entry_option not in ["rsi_only", "rsi_trend"]:
            raise ValueError("Invalid entry_option. Must be 'rsi_only' or 'rsi_trend'")

        # Validate direction
        valid_directions = ["long", "short", "both"]
        if self.direction not in valid_directions:
            raise ValueError(
                f"Invalid direction. Must be one of {valid_directions}, "
                f"got '{self.direction}'"
            )

        # Validate rsi_entry_option
        valid_rsi_entry_options = ["돌파", "변곡", "변곡돌파", "초과"]
        if self.rsi_entry_option not in valid_rsi_entry_options:
            raise ValueError(
                f"Invalid rsi_entry_option. Must be one of {valid_rsi_entry_options}, "
                f"got '{self.rsi_entry_option}'"
            )

        if self.tp_sl_option not in ["fixed", "dynamic_atr"]:
            raise ValueError("Invalid tp_sl_option. Must be 'fixed' or 'dynamic_atr'")

        # Validate tp_option (영어와 한국어 둘 다 허용)
        valid_tp_options = ["percentage", "atr", "price", "퍼센트 기준", "ATR 기준", "금액 기준"]
        if self.tp_option not in valid_tp_options:
            raise ValueError(
                f"Invalid tp_option. Must be one of {valid_tp_options}, got '{self.tp_option}'"
            )

        self._validate_dca_params(self.params)

        return True

    def _validate_dca_params(self, params: Dict[str, Any]) -> None:
        """Validate DCA-specific parameters."""
        pyramiding_limit = params.get("pyramiding_limit", 1)
        if not isinstance(pyramiding_limit, int) or pyramiding_limit < 1 or pyramiding_limit > 10:
            raise ValueError(
                f"pyramiding_limit must be integer between 1-10, got {pyramiding_limit}"
            )

        entry_multiplier = params.get("entry_multiplier", 1.6)
        if not isinstance(entry_multiplier, (int, float)) or entry_multiplier < 0.1 or entry_multiplier > 10.0:
            raise ValueError(
                f"entry_multiplier must be between 0.1-10.0, got {entry_multiplier}"
            )

        # 영어와 한국어 둘 다 허용
        valid_entry_types = ["퍼센트 기준", "금액 기준", "ATR 기준", "percentage", "atr", "price"]
        entry_type = params.get("pyramiding_entry_type", "퍼센트 기준")
        if entry_type not in valid_entry_types:
            raise ValueError(
                f"pyramiding_entry_type must be one of {valid_entry_types}, got {entry_type}"
            )

        pyramiding_value = params.get("pyramiding_value", 3.0)
        if not isinstance(pyramiding_value, (int, float)) or pyramiding_value <= 0:
            raise ValueError(
                f"pyramiding_value must be positive number, got {pyramiding_value}"
            )

        # 한국어만 허용 (entry_criterion은 매핑 대상 아님)
        valid_criteria = ["평균 단가", "최근 진입가"]
        entry_criterion = params.get("entry_criterion", "평균 단가")
        if entry_criterion not in valid_criteria:
            raise ValueError(
                f"entry_criterion must be one of {valid_criteria}, got {entry_criterion}"
            )

        for flag in [
            "pyramiding_enabled",
            "use_check_DCA_with_price",
            "use_rsi_with_pyramiding",
            "use_trend_logic",
        ]:
            value = params.get(flag, True)
            if not isinstance(value, bool):
                raise ValueError(f"{flag} must be boolean, got {type(value)}")

    def get_required_indicators(self) -> list[str]:
        """
        Get list of required indicators.

        Returns:
            List of indicator names
        """
        indicators = ["rsi"]

        if self.tp_sl_option == "dynamic_atr":
            indicators.append("atr")

        return indicators

    @staticmethod
    def _map_korean_params_to_english(params: Dict[str, Any]) -> Dict[str, Any]:
        """
        한국어 파라미터를 영어로 매핑합니다.

        백테스트 전략은 영어 파라미터를 기대하지만,
        shared/constants/default_settings.py는 한국어 값을 사용하므로
        호환성을 위해 매핑이 필요합니다.

        매핑 대상:
        - "퍼센트 기준" → "percentage"
        - "ATR 기준" → "atr"
        - "금액 기준" → "price"

        Args:
            params: 원본 파라미터 딕셔너리

        Returns:
            매핑된 파라미터 딕셔너리
        """
        # 한국어 → 영어 매핑 테이블
        korean_to_english = {
            "퍼센트 기준": "percentage",
            "ATR 기준": "atr",
            "금액 기준": "price",
        }

        # 매핑 대상 파라미터 목록
        params_to_map = ["tp_option", "sl_option", "pyramiding_entry_type"]

        # 매핑 실행
        for param_name in params_to_map:
            if param_name in params:
                korean_value = params[param_name]
                if isinstance(korean_value, str) and korean_value in korean_to_english:
                    english_value = korean_to_english[korean_value]
                    params[param_name] = english_value
                    logger.debug(
                        f"Parameter mapping: {param_name}='{korean_value}' → '{english_value}'"
                    )

        return params

    def reset(self) -> None:
        """Reset strategy state."""
        self.price_history.clear()
        logger.info("HyperrsiStrategy reset")
