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

# Lazy import to avoid circular dependency
_okx_provider_instance = None


def _get_okx_provider():
    """Get or create OKX provider instance (lazy loading)."""
    global _okx_provider_instance
    if _okx_provider_instance is None:
        from BACKTEST.data.okx_provider import OKXProvider
        _okx_provider_instance = OKXProvider()
    return _okx_provider_instance


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
        """Close the session if we own it and OKX provider if used."""
        if self._own_session and self._session_instance:
            await self._session_instance.close()
            self._session_instance = None

        # Close OKX provider if it was used
        global _okx_provider_instance
        if _okx_provider_instance is not None:
            await _okx_provider_instance.close()
            _okx_provider_instance = None

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
                    ma7 as ema, ma20 as sma,
                    trend_state,
                    cycle_bull, cycle_bear, bb_state
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
                    trend_state=int(row.trend_state) if hasattr(row, 'trend_state') and row.trend_state is not None else None,
                    # PineScript components
                    CYCLE_Bull=bool(row.cycle_bull) if hasattr(row, 'cycle_bull') and row.cycle_bull is not None else None,
                    CYCLE_Bear=bool(row.cycle_bear) if hasattr(row, 'cycle_bear') and row.cycle_bear is not None else None,
                    BB_State=int(row.bb_state) if hasattr(row, 'bb_state') and row.bb_state is not None else None,
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
                # Filter candles with NULL indicators (including trend_state)
                null_candles = [
                    c for c in candles
                    if c.rsi is None or c.atr is None or c.ema is None or c.sma is None or c.trend_state is None
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

            # Detect and fill gaps if enabled
            if candles:
                candles = await self._detect_and_fill_gaps(
                    symbol, timeframe, candles, start_date, end_date
                )

            return candles

        except Exception as e:
            logger.error(f"Error fetching candles from TimescaleDB: {e}")
            raise

    async def _detect_and_fill_gaps(
        self,
        symbol: str,
        timeframe: str,
        candles: List[Candle],
        start_date: datetime,
        end_date: datetime
    ) -> List[Candle]:
        """
        Detect gaps in candle data and fill them from OKX API.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            candles: List of candles from DB
            start_date: Expected start date
            end_date: Expected end date

        Returns:
            Complete list of candles with gaps filled
        """
        if not candles:
            # No data at all - fetch everything from OKX
            logger.warning(
                f"No data in TimescaleDB for {symbol} {timeframe}. "
                f"Fetching all data from OKX API..."
            )
            okx_provider = _get_okx_provider()
            all_candles = await okx_provider.get_candles(
                symbol, timeframe, start_date, end_date
            )
            # Save to DB
            if all_candles:
                await self._save_candles_to_db(symbol, timeframe, all_candles)
            return all_candles

        # Detect gaps
        gaps = self._detect_gaps(candles, timeframe)

        if not gaps:
            logger.debug(f"No gaps detected in {symbol} {timeframe} data")
            return candles

        logger.info(
            f"Detected {len(gaps)} gaps in {symbol} {timeframe} data. "
            f"Filling from OKX API..."
        )

        # Fill gaps from OKX API
        okx_provider = _get_okx_provider()
        filled_candles = []

        for gap_start, gap_end in gaps:
            logger.info(f"Filling gap: {gap_start} to {gap_end}")
            gap_candles = await okx_provider.get_candles(
                symbol, timeframe, gap_start, gap_end
            )
            if gap_candles:
                filled_candles.extend(gap_candles)
                logger.info(f"Filled {len(gap_candles)} candles for gap")

        # Save filled candles to DB
        if filled_candles:
            await self._save_candles_to_db(symbol, timeframe, filled_candles)

            # Merge with existing candles
            all_candles = candles + filled_candles

            # Sort by timestamp and remove duplicates
            candle_dict = {c.timestamp: c for c in all_candles}
            all_candles = sorted(candle_dict.values(), key=lambda c: c.timestamp)

            logger.info(
                f"Successfully filled {len(filled_candles)} candles. "
                f"Total: {len(all_candles)} candles"
            )

            return all_candles

        return candles

    def _detect_gaps(
        self,
        candles: List[Candle],
        timeframe: str
    ) -> List[tuple[datetime, datetime]]:
        """
        Detect gaps in candle data.

        Args:
            candles: List of candles sorted by timestamp
            timeframe: Timeframe

        Returns:
            List of (gap_start, gap_end) tuples
        """
        if len(candles) < 2:
            return []

        gaps = []
        timeframe_minutes = self._parse_timeframe_minutes(timeframe)
        expected_delta = pd.Timedelta(minutes=timeframe_minutes)

        for i in range(1, len(candles)):
            prev_candle = candles[i - 1]
            curr_candle = candles[i]

            actual_delta = curr_candle.timestamp - prev_candle.timestamp

            # Allow 10% tolerance for small timing variations
            if actual_delta > expected_delta * 1.1:
                gap_start = prev_candle.timestamp + expected_delta
                gap_end = curr_candle.timestamp  # Include the current candle timestamp
                gaps.append((gap_start, gap_end))

        return gaps

    async def _save_candles_to_db(
        self,
        symbol: str,
        timeframe: str,
        candles: List[Candle]
    ) -> None:
        """
        Save candles to TimescaleDB (insert or update).

        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            candles: List of candles to save
        """
        if not candles:
            return

        session = await self._get_session()
        table_name = self._get_table_name(timeframe)
        normalized_symbol = self._normalize_symbol(symbol)

        try:
            # Use INSERT ... ON CONFLICT DO UPDATE
            insert_query = f"""
                INSERT INTO {table_name} (
                    time, symbol, open, high, low, close, volume,
                    rsi, atr, ma7, ma20, trend_state
                ) VALUES (
                    :time, :symbol, :open, :high, :low, :close, :volume,
                    :rsi, :atr, :ma7, :ma20, :trend_state
                )
                ON CONFLICT (time, symbol) DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    rsi = EXCLUDED.rsi,
                    atr = EXCLUDED.atr,
                    ma7 = EXCLUDED.ma7,
                    ma20 = EXCLUDED.ma20,
                    trend_state = EXCLUDED.trend_state
            """

            total = len(candles)
            batch_size = 1000

            for i in range(0, total, batch_size):
                batch = candles[i:i + batch_size]

                for candle in batch:
                    await session.execute(text(insert_query), {
                        'time': candle.timestamp,
                        'symbol': normalized_symbol,
                        'open': candle.open,
                        'high': candle.high,
                        'low': candle.low,
                        'close': candle.close,
                        'volume': candle.volume,
                        'rsi': candle.rsi,
                        'atr': candle.atr,
                        'ma7': candle.ema,
                        'ma20': candle.sma,
                        'trend_state': candle.trend_state
                    })

                # Progress logging
                processed = min(i + batch_size, total)
                logger.info(
                    f"Saving candles to DB: {processed}/{total} ({processed*100//total}%)"
                )

            await session.commit()
            logger.info(f"✅ Successfully saved {total} candles to {table_name}")

        except Exception as e:
            logger.error(f"Error saving candles to DB: {e}")
            await session.rollback()
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
        Calculate missing indicators using PineScript-based logic and update them in TimescaleDB.

        Uses shared.indicators.compute_all_indicators() for trend_state calculation,
        ensuring consistency with HYPERRSI production system.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            candles: List of candles (some may have None indicators)
            rsi_period: RSI calculation period (default: 14)

        Returns:
            Updated candles with calculated indicators
        """
        from shared.indicators import compute_all_indicators

        if not candles:
            return candles

        # Convert Candle objects to dict list for compute_all_indicators
        candles_dict = [{
            'timestamp': int(c.timestamp.timestamp()),
            'open': c.open,
            'high': c.high,
            'low': c.low,
            'close': c.close,
            'volume': c.volume
        } for c in candles]

        # Calculate all indicators using PineScript-based logic
        try:
            candles_with_indicators = compute_all_indicators(
                candles_dict,
                rsi_period=rsi_period,
                atr_period=14
            )

            # Update Candle objects with calculated values
            for i, candle in enumerate(candles):
                ind = candles_with_indicators[i]

                # Update basic indicators (safely handle None and invalid values)
                if candle.rsi is None:
                    rsi_val = ind.get('rsi')
                    if rsi_val is not None and 0 <= rsi_val <= 100:
                        candle.rsi = rsi_val

                if candle.atr is None:
                    atr_val = ind.get('atr14')
                    if atr_val is not None and atr_val >= 0:
                        candle.atr = atr_val

                # EMA/SMA (use JMA5 and SMA20 from PineScript calculation)
                # Must be > 0 per Candle model constraint
                if candle.ema is None:
                    ema_val = ind.get('jma5')
                    if ema_val is not None and ema_val > 0:
                        candle.ema = ema_val

                if candle.sma is None:
                    sma_val = ind.get('sma20')
                    if sma_val is not None and sma_val > 0:
                        candle.sma = sma_val

                # PineScript-based trend state components
                # Always update (overwrite previous values)
                trend_val = ind.get('trend_state')
                candle.trend_state = trend_val if trend_val is not None else 0

                cycle_bull = ind.get('CYCLE_Bull')
                candle.CYCLE_Bull = cycle_bull if cycle_bull is not None else False

                cycle_bear = ind.get('CYCLE_Bear')
                candle.CYCLE_Bear = cycle_bear if cycle_bear is not None else False

                bb_state = ind.get('BB_State')
                candle.BB_State = bb_state if bb_state is not None else 0

            # Update database with new indicators
            await self._bulk_update_indicators_pinescript(symbol, timeframe, candles)

            logger.info(f"Updated {len(candles)} candles with PineScript-based indicators in DB")
            return candles

        except Exception as e:
            logger.error(f"Error calculating PineScript indicators: {e}")
            # Fallback to simple indicators if PineScript calculation fails
            return await self._calculate_simple_indicators(symbol, timeframe, candles, rsi_period)

    async def _bulk_update_indicators(
        self,
        symbol: str,
        timeframe: str,
        df: pd.DataFrame
    ) -> None:
        """
        Bulk update indicators (including trend_state) in TimescaleDB.

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
                    'ma20': float(row['sma']) if not pd.isna(row['sma']) else None,
                    'trend_state': int(row['trend_state']) if not pd.isna(row['trend_state']) else None
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
                    ma20 = :ma20,
                    trend_state = :trend_state
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
                        'ma20': val['ma20'],
                        'trend_state': val['trend_state']
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

    async def _bulk_update_indicators_pinescript(
        self,
        symbol: str,
        timeframe: str,
        candles: List[Candle]
    ) -> None:
        """
        Bulk update PineScript-based indicators in TimescaleDB.

        Updates trend_state and PineScript components (CYCLE_Bull, CYCLE_Bear, BB_State).

        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            candles: List of Candle objects with calculated indicators
        """
        session = await self._get_session()
        table_name = self._get_table_name(timeframe)
        normalized_symbol = self._normalize_symbol(symbol)

        try:
            # Prepare bulk update values
            update_values = []
            for candle in candles:
                update_values.append({
                    'timestamp': candle.timestamp,
                    'rsi': candle.rsi,
                    'atr': candle.atr,
                    'ma7': candle.ema,  # JMA5 stored as ma7
                    'ma20': candle.sma,  # SMA20 stored as ma20
                    'trend_state': candle.trend_state,
                    'cycle_bull': candle.CYCLE_Bull,
                    'cycle_bear': candle.CYCLE_Bear,
                    'bb_state': candle.BB_State
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
                    ma20 = :ma20,
                    trend_state = :trend_state,
                    cycle_bull = :cycle_bull,
                    cycle_bear = :cycle_bear,
                    bb_state = :bb_state
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
                        'ma20': val['ma20'],
                        'trend_state': val['trend_state'],
                        'cycle_bull': val['cycle_bull'],
                        'cycle_bear': val['cycle_bear'],
                        'bb_state': val['bb_state']
                    })

                # Progress logging
                processed = min(i + batch_size, total)
                logger.info(f"Updating PineScript indicators: {processed}/{total} ({processed*100//total}%)")

            await session.commit()
            logger.info(f"✅ Successfully updated {total} candles with PineScript indicators in DB")

        except Exception as e:
            logger.error(f"Error bulk updating PineScript indicators: {e}")
            await session.rollback()
            raise

    async def _calculate_simple_indicators(
        self,
        symbol: str,
        timeframe: str,
        candles: List[Candle],
        rsi_period: int = 14
    ) -> List[Candle]:
        """
        Fallback method to calculate simple indicators when PineScript calculation fails.

        Calculates basic RSI and ATR indicators without trend_state.
        This is a safety fallback and should not be used as primary calculation method.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            candles: List of Candle objects
            rsi_period: RSI period (default: 14)

        Returns:
            List of Candle objects with basic indicators
        """
        logger.warning(f"Using fallback simple indicator calculation for {symbol} {timeframe}")

        if not candles:
            return candles

        # Convert to DataFrame for pandas calculations
        df = pd.DataFrame([{
            'timestamp': c.timestamp,
            'open': c.open,
            'high': c.high,
            'low': c.low,
            'close': c.close,
            'volume': c.volume
        } for c in candles])

        df.set_index('timestamp', inplace=True)

        # Calculate simple RSI
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.rolling(window=rsi_period).mean()
        avg_loss = loss.rolling(window=rsi_period).mean()
        rs = avg_gain / avg_loss
        df['rsi'] = 100.0 - (100.0 / (1.0 + rs))

        # Calculate simple ATR
        high_low = df['high'] - df['low']
        high_close = abs(df['high'] - df['close'].shift())
        low_close = abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr'] = tr.rolling(window=14).mean()

        # Calculate simple EMA and SMA
        df['ema'] = df['close'].ewm(span=7, adjust=False).mean()
        df['sma'] = df['close'].rolling(window=20).mean()

        # trend_state is None in fallback mode (no PineScript calculation)
        df['trend_state'] = None

        # Update Candle objects with calculated values
        for i, candle in enumerate(candles):
            if candle.rsi is None and not pd.isna(df.iloc[i]['rsi']):
                candle.rsi = float(df.iloc[i]['rsi'])
            if candle.atr is None and not pd.isna(df.iloc[i]['atr']):
                candle.atr = float(df.iloc[i]['atr'])
            if candle.ema is None and not pd.isna(df.iloc[i]['ema']):
                candle.ema = float(df.iloc[i]['ema'])
            if candle.sma is None and not pd.isna(df.iloc[i]['sma']):
                candle.sma = float(df.iloc[i]['sma'])
            # trend_state remains None in fallback mode

        # Update database with simple indicators
        try:
            await self._bulk_update_indicators(symbol, timeframe, df)
            logger.info(f"Updated {len(candles)} candles with simple indicators in DB")
        except Exception as e:
            logger.error(f"Error updating simple indicators in DB: {e}")

        return candles

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
            'BTC-USDT-SWAP': {'min_size': 1, 'contract_size': 0.001},  # 1 contract = 0.001 BTC
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
            'contract_size': 0.001,
            'tick_size': 0.01,
            'base_currency': base_currency,
            'lot_size': 1
        }
