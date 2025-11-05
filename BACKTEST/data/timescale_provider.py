"""
TimescaleDB data provider implementation.

Provides efficient access to historical candle data stored in TimescaleDB.
"""

from datetime import datetime
from typing import List, Optional
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import aiohttp

from BACKTEST.data.data_provider import DataProvider
from BACKTEST.models.candle import Candle
from shared.database.session import DatabaseConfig
from shared.logging import get_logger

logger = get_logger(__name__)


class TimescaleProvider(DataProvider):
    """TimescaleDB-based data provider for historical candle data."""

    def __init__(self, session: Optional[AsyncSession] = None):
        """
        Initialize TimescaleDB provider.

        Args:
            session: Optional database session. If not provided, will create one
        """
        self.session = session
        self._own_session = session is None
        self._session_instance: Optional[AsyncSession] = None

    async def _get_session(self) -> AsyncSession:
        """Get database session."""
        if self.session:
            return self.session

        # Create session if we own it and haven't created one yet
        if self._own_session and not self._session_instance:
            session_factory = DatabaseConfig.get_session_factory()
            self._session_instance = session_factory()

        return self._session_instance

    async def close(self):
        """Close the session if we own it."""
        if self._own_session and self._session_instance:
            await self._session_instance.close()
            self._session_instance = None

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """
        Normalize symbol format for database query.

        Converts OKX format to Binance format stored in database.

        Args:
            symbol: Symbol in any format (e.g., "BTC-USDT-SWAP", "BTC/USDT:USDT", or "BTCUSDT")

        Returns:
            Normalized symbol (e.g., "BTCUSDT")

        Examples:
            "BTC-USDT-SWAP" -> "BTCUSDT"
            "BTC/USDT:USDT" -> "BTCUSDT"
            "ETH/USDT:USDT" -> "ETHUSDT"
            "BTCUSDT" -> "BTCUSDT" (unchanged)
        """
        # Handle OKX perpetual futures format: BTC/USDT:USDT
        # Remove settlement currency suffix (e.g., :USDT)
        if ":" in symbol:
            symbol = symbol.split(":")[0]  # "BTC/USDT:USDT" -> "BTC/USDT"

        # Remove -SWAP suffix and all separators (/, -)
        normalized = (symbol
                     .replace("-SWAP", "")
                     .replace("/", "")
                     .replace("-", ""))
        logger.debug(f"Symbol normalized: {symbol} -> {normalized}")
        return normalized

    @staticmethod
    def _get_table_name(timeframe: str) -> str:
        """
        Get table name for given timeframe.

        Args:
            timeframe: Timeframe (e.g., "15m", "1h", "1d")

        Returns:
            Table name (e.g., "okx_candles_15m")
        """
        return f"okx_candles_{timeframe}"

    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        limit: Optional[int] = None
    ) -> List[Candle]:
        """
        Fetch candle data from TimescaleDB.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            start_date: Start datetime (UTC)
            end_date: End datetime (UTC)
            limit: Optional maximum number of candles

        Returns:
            List of Candle objects sorted by timestamp
        """
        session = await self._get_session()
        table_name = self._get_table_name(timeframe)
        normalized_symbol = self._normalize_symbol(symbol)

        try:
            # Build query - note: time column instead of timestamp
            query_str = f"""
                SELECT
                    time as timestamp,
                    symbol,
                    open, high, low, close, volume,
                    rsi, atr,
                    ma7 as ema, ma20 as sma
                FROM {table_name}
                WHERE symbol = :symbol
                    AND time >= :start_date
                    AND time <= :end_date
                ORDER BY time ASC
            """

            if limit:
                query_str += f" LIMIT {limit}"

            result = await session.execute(
                text(query_str),
                {
                    "symbol": normalized_symbol,
                    "start_date": start_date,
                    "end_date": end_date
                }
            )

            rows = result.fetchall()

            candles = [
                Candle(
                    timestamp=row.timestamp,
                    symbol=symbol,  # Use original symbol from parameter, not DB
                    timeframe=timeframe,  # Add timeframe from parameter
                    open=float(row.open),
                    high=float(row.high),
                    low=float(row.low),
                    close=float(row.close),
                    volume=float(row.volume),
                    rsi=float(row.rsi) if row.rsi else None,
                    atr=float(row.atr) if row.atr else None,
                    ema=float(row.ema) if row.ema else None,
                    sma=float(row.sma) if row.sma else None,
                    bollinger_upper=None,  # Not available in this schema
                    bollinger_middle=None,
                    bollinger_lower=None,
                    macd=None,
                    macd_signal=None,
                    macd_histogram=None,
                    data_source="timescaledb",
                    is_complete=True
                )
                for row in rows
            ]

            logger.info(
                f"Fetched {len(candles)} candles from TimescaleDB "
                f"for {symbol} {timeframe} ({start_date} to {end_date})"
            )

            # Check for NULL indicators and calculate/update if needed
            if candles:
                # Filter candles with NULL indicators
                null_candles = [
                    c for c in candles
                    if c.rsi is None or c.atr is None or c.ema is None or c.sma is None
                ]

                if null_candles:
                    logger.info(
                        f"Found {len(null_candles)}/{len(candles)} candles with NULL indicators. "
                        f"Calculating and updating database..."
                    )

                    # Calculate and update ONLY the NULL candles
                    updated_candles = await self.calculate_and_update_indicators(
                        symbol, timeframe, null_candles
                    )

                    # Merge back: replace NULL candles with updated ones
                    updated_dict = {c.timestamp: c for c in updated_candles}
                    for i, candle in enumerate(candles):
                        if candle.timestamp in updated_dict:
                            candles[i] = updated_dict[candle.timestamp]

                    logger.info(f"Successfully calculated and updated {len(null_candles)} candles")

            return candles

        except Exception as e:
            logger.error(f"Error fetching candles from TimescaleDB: {e}")
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
        Validate data availability and quality.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            start_date: Start datetime (UTC)
            end_date: End datetime (UTC)

        Returns:
            Validation results dict
        """
        session = await self._get_session()
        table_name = self._get_table_name(timeframe)
        normalized_symbol = self._normalize_symbol(symbol)

        try:
            # Count available candles
            count_query = text(f"""
                SELECT COUNT(*) as count
                FROM {table_name}
                WHERE symbol = :symbol
                    AND time >= :start_date
                    AND time <= :end_date
            """)

            result = await session.execute(
                count_query,
                {
                    "symbol": normalized_symbol,
                    "start_date": start_date,
                    "end_date": end_date
                }
            )

            count = result.scalar()

            # Calculate expected candle count based on timeframe
            time_delta = end_date - start_date
            timeframe_minutes = self._parse_timeframe_minutes(timeframe)
            expected_count = int(time_delta.total_seconds() / 60 / timeframe_minutes)

            coverage = count / expected_count if expected_count > 0 else 0.0

            # Find missing periods (simplified - actual implementation would be more sophisticated)
            missing_periods = []
            if coverage < 1.0:
                # This is a placeholder - real implementation would query for gaps
                missing_periods = [(start_date, end_date)]

            return {
                "available": count > 0,
                "coverage": coverage,
                "missing_periods": missing_periods,
                "data_source": "timescaledb",
                "actual_count": count,
                "expected_count": expected_count
            }

        except Exception as e:
            logger.error(f"Error validating data availability: {e}")
            return {
                "available": False,
                "coverage": 0.0,
                "missing_periods": [(start_date, end_date)],
                "data_source": "timescaledb",
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
        session = await self._get_session()
        table_name = self._get_table_name(timeframe)

        try:
            query = text(f"""
                SELECT MAX(time) as latest
                FROM {table_name}
                WHERE symbol = :symbol
            """)

            result = await session.execute(
                query,
                {"symbol": symbol}
            )

            latest = result.scalar()
            return latest

        except Exception as e:
            logger.error(f"Error getting latest timestamp: {e}")
            return None

    @staticmethod
    def _parse_timeframe_minutes(timeframe: str) -> int:
        """
        Parse timeframe string to minutes.

        Args:
            timeframe: Timeframe string (1m, 5m, 1h, 4h, 1d)

        Returns:
            Number of minutes
        """
        mapping = {
            "1m": 1,
            "3m": 3,
            "5m": 5,
            "15m": 15,
            "30m": 30,
            "1h": 60,
            "2h": 120,
            "4h": 240,
            "6h": 360,
            "12h": 720,
            "1d": 1440,
        }

        return mapping.get(timeframe, 1)

    async def calculate_and_update_indicators(
        self,
        symbol: str,
        timeframe: str,
        candles: List[Candle],
        rsi_period: int = 14
    ) -> List[Candle]:
        """
        Calculate missing indicators and update them in TimescaleDB.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            candles: List of candles (some may have None indicators)
            rsi_period: RSI calculation period (default: 14)

        Returns:
            Updated candles with calculated indicators
        """
        if not candles:
            return candles

        # Build DataFrame from candles
        df = pd.DataFrame([{
            'timestamp': c.timestamp,
            'close': c.close,
            'high': c.high,
            'low': c.low,
            'rsi': c.rsi,
            'atr': c.atr,
            'ema': c.ema,
            'sma': c.sma
        } for c in candles])

        df.set_index('timestamp', inplace=True)
        df.sort_index(inplace=True)

        # Calculate RSI if any None
        if df['rsi'].isna().any():
            df['rsi'] = self._calculate_rsi(df['close'], period=rsi_period)
            logger.info(f"Calculated RSI for {df['rsi'].isna().sum()} candles")

        # Calculate ATR if any None
        if df['atr'].isna().any():
            df['atr'] = self._calculate_atr(df['high'], df['low'], df['close'], period=rsi_period)
            logger.info(f"Calculated ATR for {df['atr'].isna().sum()} candles")

        # Calculate EMA (7-period, matching ma7 in DB)
        if df['ema'].isna().any():
            df['ema'] = df['close'].ewm(span=7, adjust=False).mean()
            logger.info(f"Calculated EMA for {df['ema'].isna().sum()} candles")

        # Calculate SMA (20-period, matching ma20 in DB)
        if df['sma'].isna().any():
            df['sma'] = df['close'].rolling(window=20).mean()
            logger.info(f"Calculated SMA for {df['sma'].isna().sum()} candles")

        # Update candles in DB
        await self._bulk_update_indicators(symbol, timeframe, df)

        # Update Candle objects
        for i, candle in enumerate(candles):
            timestamp = candle.timestamp
            if timestamp in df.index:
                candle.rsi = df.loc[timestamp, 'rsi'] if not pd.isna(df.loc[timestamp, 'rsi']) else None
                candle.atr = df.loc[timestamp, 'atr'] if not pd.isna(df.loc[timestamp, 'atr']) else None
                candle.ema = df.loc[timestamp, 'ema'] if not pd.isna(df.loc[timestamp, 'ema']) else None
                candle.sma = df.loc[timestamp, 'sma'] if not pd.isna(df.loc[timestamp, 'sma']) else None

        logger.info(f"Updated {len(candles)} candles with calculated indicators in DB")
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

    async def _bulk_update_indicators(
        self,
        symbol: str,
        timeframe: str,
        df: pd.DataFrame
    ) -> None:
        """
        Bulk update indicators in TimescaleDB.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            df: DataFrame with calculated indicators
        """
        session = await self._get_session()
        table_name = self._get_table_name(timeframe)
        normalized_symbol = self._normalize_symbol(symbol)

        try:
            # Prepare bulk update values
            update_values = []
            for timestamp, row in df.iterrows():
                update_values.append({
                    'timestamp': timestamp,
                    'rsi': float(row['rsi']) if not pd.isna(row['rsi']) else None,
                    'atr': float(row['atr']) if not pd.isna(row['atr']) else None,
                    'ma7': float(row['ema']) if not pd.isna(row['ema']) else None,
                    'ma20': float(row['sma']) if not pd.isna(row['sma']) else None
                })

            # Execute bulk update with progress logging
            total = len(update_values)
            batch_size = 1000

            update_query_template = f"""
                UPDATE {table_name}
                SET
                    rsi = :rsi,
                    atr = :atr,
                    ma7 = :ma7,
                    ma20 = :ma20
                WHERE symbol = :symbol
                    AND time = :timestamp
            """

            for i in range(0, total, batch_size):
                batch = update_values[i:i + batch_size]

                for val in batch:
                    await session.execute(text(update_query_template), {
                        'symbol': normalized_symbol,
                        'timestamp': val['timestamp'],
                        'rsi': val['rsi'],
                        'atr': val['atr'],
                        'ma7': val['ma7'],
                        'ma20': val['ma20']
                    })

                # Progress logging
                processed = min(i + batch_size, total)
                logger.info(f"Updating indicators: {processed}/{total} ({processed*100//total}%)")

            await session.commit()
            logger.info(f"✅ Successfully updated {total} candles with indicators in DB")

        except Exception as e:
            logger.error(f"Error bulk updating indicators: {e}")
            await session.rollback()
            raise

    async def get_symbol_info(self, symbol: str) -> Optional[dict]:
        """
        Get symbol/instrument information from OKX API.

        Args:
            symbol: Trading symbol (e.g., "BTC-USDT-SWAP")

        Returns:
            dict with symbol info or None if not found
        """
        try:
            # OKX Public API - No authentication required
            base_url = "https://www.okx.com"
            conn = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(connector=conn) as session:
                url = f"{base_url}/api/v5/public/instruments?instType=SWAP"
                async with session.get(url) as response:
                    data = await response.json()

            if not data or 'data' not in data:
                logger.warning(f"Failed to fetch instruments from OKX API")
                return self._get_default_symbol_info(symbol)

            # Find matching instrument
            for instrument in data['data']:
                if instrument['instId'] == symbol:
                    return {
                        'symbol': symbol,
                        'min_size': float(instrument.get('minSz', 1)),  # Minimum order size
                        'contract_size': float(instrument.get('ctVal', 0.01)),  # Contract value
                        'tick_size': float(instrument.get('tickSz', 0.01)),  # Price increment
                        'base_currency': symbol.split('-')[0],
                        'lot_size': float(instrument.get('lotSz', 1))  # Lot size
                    }

            # Symbol not found, return default
            logger.warning(f"Symbol {symbol} not found in OKX instruments, using defaults")
            return self._get_default_symbol_info(symbol)

        except Exception as e:
            logger.error(f"Error fetching symbol info from OKX: {e}")
            return self._get_default_symbol_info(symbol)

    @staticmethod
    def _get_default_symbol_info(symbol: str) -> dict:
        """
        Get default symbol info when API fetch fails.

        Args:
            symbol: Trading symbol

        Returns:
            Default symbol info dict
        """
        # Common defaults for popular coins
        defaults = {
            'BTC-USDT-SWAP': {'min_size': 1, 'contract_size': 0.01},  # 1 contract = 0.01 BTC
            'ETH-USDT-SWAP': {'min_size': 1, 'contract_size': 0.1},   # 1 contract = 0.1 ETH
            'SOL-USDT-SWAP': {'min_size': 1, 'contract_size': 1},     # 1 contract = 1 SOL
            'BNB-USDT-SWAP': {'min_size': 1, 'contract_size': 0.1},   # 1 contract = 0.1 BNB
        }

        base_currency = symbol.split('-')[0] if '-' in symbol else symbol[:3]

        if symbol in defaults:
            default_info = defaults[symbol]
            return {
                'symbol': symbol,
                'min_size': default_info['min_size'],
                'contract_size': default_info['contract_size'],
                'tick_size': 0.01,
                'base_currency': base_currency,
                'lot_size': 1
            }

        # Generic default
        return {
            'symbol': symbol,
            'min_size': 1,
            'contract_size': 0.01,
            'tick_size': 0.01,
            'base_currency': base_currency,
            'lot_size': 1
        }
