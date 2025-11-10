"""
OKX API data provider implementation.

Fetches historical candle data directly from OKX exchange API.
"""

from datetime import datetime, timezone
from typing import List, Optional
import pandas as pd
import ccxt.async_support as ccxt
import asyncio

from BACKTEST.data.data_provider import DataProvider
from BACKTEST.models.candle import Candle
from shared.logging import get_logger

logger = get_logger(__name__)


class OKXProvider(DataProvider):
    """OKX API-based data provider for historical candle data."""

    def __init__(self):
        """Initialize OKX provider."""
        self.exchange = ccxt.okx({
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap'  # Use perpetual futures
            }
        })

    async def close(self):
        """Close the exchange connection."""
        if self.exchange:
            await self.exchange.close()

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """
        Normalize symbol format for OKX API.

        Args:
            symbol: Symbol in any format (e.g., "BTC-USDT-SWAP", "BTC/USDT:USDT")

        Returns:
            Normalized symbol for CCXT (e.g., "BTC/USDT:USDT")

        Examples:
            "BTC-USDT-SWAP" -> "BTC/USDT:USDT"
            "ETH-USDT-SWAP" -> "ETH/USDT:USDT"
            "BTC/USDT:USDT" -> "BTC/USDT:USDT" (unchanged)
        """
        # Already in CCXT format
        if "/" in symbol and ":" in symbol:
            return symbol

        # Convert from OKX format: BTC-USDT-SWAP -> BTC/USDT:USDT
        if "-SWAP" in symbol:
            parts = symbol.replace("-SWAP", "").split("-")
            if len(parts) == 2:
                return f"{parts[0]}/{parts[1]}:{parts[1]}"

        # Default: assume it's already correct
        return symbol

    @staticmethod
    def _normalize_timeframe(timeframe: str) -> str:
        """
        Normalize timeframe format for OKX API.

        Args:
            timeframe: Timeframe (e.g., "15m", "1h", "1d")

        Returns:
            Normalized timeframe for CCXT

        Examples:
            "15m" -> "15m"
            "1h" -> "1h"
            "1d" -> "1d"
        """
        # CCXT uses the same format as our internal format
        return timeframe

    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        limit: Optional[int] = None
    ) -> List[Candle]:
        """
        Fetch candle data from OKX API.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            start_date: Start datetime (UTC)
            end_date: End datetime (UTC)
            limit: Optional maximum number of candles

        Returns:
            List of Candle objects sorted by timestamp
        """
        normalized_symbol = self._normalize_symbol(symbol)
        normalized_timeframe = self._normalize_timeframe(timeframe)

        try:
            # Convert datetime to milliseconds
            since = int(start_date.timestamp() * 1000)
            end_ms = int(end_date.timestamp() * 1000)

            all_candles = []
            current_since = since

            # OKX API limit is 100-300 candles per request
            batch_limit = limit if limit and limit < 300 else 300

            logger.info(
                f"Fetching candles from OKX API: {normalized_symbol} {normalized_timeframe} "
                f"({start_date} to {end_date})"
            )

            while current_since < end_ms:
                # Fetch batch
                ohlcv = await self.exchange.fetch_ohlcv(
                    symbol=normalized_symbol,
                    timeframe=normalized_timeframe,
                    since=current_since,
                    limit=batch_limit
                )

                if not ohlcv:
                    break

                # Convert to Candle objects
                for row in ohlcv:
                    timestamp = datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc)

                    # Stop if we've reached the end date
                    if timestamp > end_date:
                        break

                    candle = Candle(
                        timestamp=timestamp,
                        symbol=symbol,  # Use original symbol
                        timeframe=timeframe,
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=float(row[5]),
                        rsi=None,  # Will be calculated later
                        atr=None,
                        ema=None,
                        sma=None,
                        bollinger_upper=None,
                        bollinger_middle=None,
                        bollinger_lower=None,
                        macd=None,
                        macd_signal=None,
                        macd_histogram=None,
                        data_source="okx_api",
                        is_complete=True
                    )
                    all_candles.append(candle)

                # Update since for next batch
                if ohlcv:
                    last_timestamp = ohlcv[-1][0]
                    current_since = last_timestamp + 1

                    # Stop if we've reached the end
                    if current_since >= end_ms:
                        break
                else:
                    break

                # Add small delay to respect rate limits
                await asyncio.sleep(0.1)

            # Filter candles to exact date range
            filtered_candles = [
                c for c in all_candles
                if start_date <= c.timestamp <= end_date
            ]

            logger.info(
                f"Fetched {len(filtered_candles)} candles from OKX API "
                f"for {symbol} {timeframe}"
            )

            # Calculate indicators
            if filtered_candles:
                filtered_candles = await self._calculate_indicators(filtered_candles)

            return filtered_candles

        except Exception as e:
            logger.error(f"Error fetching candles from OKX API: {e}")
            raise

    async def get_candles_df(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        limit: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Fetch candle data as pandas DataFrame.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            start_date: Start datetime (UTC)
            end_date: End datetime (UTC)
            limit: Optional maximum number of candles

        Returns:
            DataFrame with OHLCV and indicator columns
        """
        candles = await self.get_candles(symbol, timeframe, start_date, end_date, limit)

        if not candles:
            return pd.DataFrame()

        # Convert to DataFrame
        df = pd.DataFrame([candle.model_dump() for candle in candles])
        df.set_index('timestamp', inplace=True)
        df.sort_index(inplace=True)

        return df

    async def validate_data_availability(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime
    ) -> dict:
        """
        Validate data availability from OKX API.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            start_date: Start datetime (UTC)
            end_date: End datetime (UTC)

        Returns:
            Validation results dict
        """
        try:
            # Try to fetch a small sample
            candles = await self.get_candles(
                symbol, timeframe, start_date, end_date, limit=10
            )

            available = len(candles) > 0

            return {
                "available": available,
                "coverage": 1.0 if available else 0.0,  # OKX should have full coverage
                "missing_periods": [],
                "data_source": "okx_api"
            }

        except Exception as e:
            logger.error(f"Error validating OKX data availability: {e}")
            return {
                "available": False,
                "coverage": 0.0,
                "missing_periods": [(start_date, end_date)],
                "data_source": "okx_api",
                "error": str(e)
            }

    async def get_latest_timestamp(
        self,
        symbol: str,
        timeframe: str
    ) -> Optional[datetime]:
        """
        Get the timestamp of the most recent candle.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe

        Returns:
            Latest timestamp or None
        """
        normalized_symbol = self._normalize_symbol(symbol)
        normalized_timeframe = self._normalize_timeframe(timeframe)

        try:
            # Fetch just the last candle
            ohlcv = await self.exchange.fetch_ohlcv(
                symbol=normalized_symbol,
                timeframe=normalized_timeframe,
                limit=1
            )

            if ohlcv:
                timestamp = datetime.fromtimestamp(ohlcv[0][0] / 1000, tz=timezone.utc)
                return timestamp

            return None

        except Exception as e:
            logger.error(f"Error getting latest timestamp from OKX: {e}")
            return None

    async def get_symbol_info(self, symbol: str) -> Optional[dict]:
        """
        Get symbol/instrument information from OKX.

        Args:
            symbol: Trading symbol (e.g., "BTC-USDT-SWAP")

        Returns:
            dict with symbol info or None if not found
        """
        normalized_symbol = self._normalize_symbol(symbol)

        try:
            # Load markets if not already loaded
            if not self.exchange.markets:
                await self.exchange.load_markets()

            # Get market info
            if normalized_symbol in self.exchange.markets:
                market = self.exchange.markets[normalized_symbol]
                return {
                    'symbol': symbol,
                    'min_size': market.get('limits', {}).get('amount', {}).get('min', 1),
                    'contract_size': market.get('contractSize', 0.01),
                    'tick_size': market.get('precision', {}).get('price', 0.01),
                    'base_currency': market.get('base', 'BTC'),
                    'lot_size': market.get('limits', {}).get('amount', {}).get('min', 1)
                }

            # Symbol not found
            logger.warning(f"Symbol {symbol} not found in OKX markets")
            return None

        except Exception as e:
            logger.error(f"Error fetching symbol info from OKX: {e}")
            return None

    async def _calculate_indicators(
        self,
        candles: List[Candle],
        rsi_period: int = 14
    ) -> List[Candle]:
        """
        Calculate technical indicators for candles.

        Args:
            candles: List of candles
            rsi_period: RSI calculation period

        Returns:
            Updated candles with calculated indicators
        """
        if not candles:
            return candles

        # Build DataFrame
        df = pd.DataFrame([{
            'timestamp': c.timestamp,
            'close': c.close,
            'high': c.high,
            'low': c.low
        } for c in candles])

        df.set_index('timestamp', inplace=True)
        df.sort_index(inplace=True)

        # Calculate RSI
        df['rsi'] = self._calculate_rsi(df['close'], period=rsi_period)

        # Calculate ATR
        df['atr'] = self._calculate_atr(df['high'], df['low'], df['close'], period=rsi_period)

        # Calculate EMA (7-period)
        df['ema'] = df['close'].ewm(span=7, adjust=False).mean()

        # Calculate SMA (20-period)
        df['sma'] = df['close'].rolling(window=20).mean()

        # Update Candle objects
        for candle in candles:
            timestamp = candle.timestamp
            if timestamp in df.index:
                candle.rsi = df.loc[timestamp, 'rsi'] if not pd.isna(df.loc[timestamp, 'rsi']) else None
                candle.atr = df.loc[timestamp, 'atr'] if not pd.isna(df.loc[timestamp, 'atr']) else None
                candle.ema = df.loc[timestamp, 'ema'] if not pd.isna(df.loc[timestamp, 'ema']) else None
                candle.sma = df.loc[timestamp, 'sma'] if not pd.isna(df.loc[timestamp, 'sma']) else None

        return candles

    @staticmethod
    def _calculate_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI indicator."""
        delta = closes.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
        avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    @staticmethod
    def _calculate_atr(highs: pd.Series, lows: pd.Series, closes: pd.Series, period: int = 14) -> pd.Series:
        """Calculate ATR indicator."""
        high_low = highs - lows
        high_close = (highs - closes.shift()).abs()
        low_close = (lows - closes.shift()).abs()

        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1/period, min_periods=period).mean()
        return atr
