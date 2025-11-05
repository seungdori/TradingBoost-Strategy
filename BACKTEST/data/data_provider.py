"""
Abstract data provider interface for backtesting system.

Defines the contract that all data sources must implement.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional
import pandas as pd

from BACKTEST.models.candle import Candle


class DataProvider(ABC):
    """Abstract base class for all data providers."""

    @abstractmethod
    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        limit: Optional[int] = None
    ) -> List[Candle]:
        """
        Fetch candle data for the specified period.

        Args:
            symbol: Trading symbol (e.g., "BTC-USDT-SWAP")
            timeframe: Timeframe (e.g., "1m", "5m", "1h")
            start_date: Start datetime (UTC)
            end_date: End datetime (UTC)
            limit: Optional maximum number of candles

        Returns:
            List of Candle objects sorted by timestamp

        Raises:
            DataNotFoundError: If no data available for the period
            DataValidationError: If data quality is insufficient
        """
        pass

    @abstractmethod
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
            DataFrame with columns: timestamp, open, high, low, close, volume

        Raises:
            DataNotFoundError: If no data available
            DataValidationError: If data quality is insufficient
        """
        pass

    @abstractmethod
    async def validate_data_availability(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime
    ) -> dict:
        """
        Validate data availability and quality for the period.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            start_date: Start datetime (UTC)
            end_date: End datetime (UTC)

        Returns:
            dict with validation results:
            {
                "available": bool,
                "coverage": float,  # 0.0 to 1.0
                "missing_periods": List[tuple],  # [(start, end), ...]
                "data_source": str
            }
        """
        pass

    @abstractmethod
    async def get_latest_timestamp(
        self,
        symbol: str,
        timeframe: str
    ) -> Optional[datetime]:
        """
        Get the timestamp of the most recent available candle.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe

        Returns:
            Latest timestamp or None if no data
        """
        pass

    @abstractmethod
    async def get_symbol_info(
        self,
        symbol: str
    ) -> Optional[dict]:
        """
        Get symbol/instrument information including min_size.

        Args:
            symbol: Trading symbol (e.g., "BTC-USDT-SWAP")

        Returns:
            dict with symbol info or None if not found
            {
                "symbol": str,
                "min_size": float,  # Minimum order size
                "contract_size": float,  # Contract value
                "tick_size": float,  # Minimum price increment
                "base_currency": str
            }
        """
        pass
