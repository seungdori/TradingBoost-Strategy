"""
Candle data model for backtesting system.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class Candle(BaseModel):
    """OHLCV candle data."""

    timestamp: datetime = Field(..., description="Candle timestamp (UTC)")
    symbol: str = Field(..., description="Trading symbol")
    timeframe: str = Field(..., description="Timeframe (1m, 5m, 1h, etc.)")

    # OHLCV data
    open: float = Field(..., description="Open price", gt=0)
    high: float = Field(..., description="High price", gt=0)
    low: float = Field(..., description="Low price", gt=0)
    close: float = Field(..., description="Close price", gt=0)
    volume: float = Field(..., description="Trading volume", ge=0)

    # Optional indicators
    rsi: Optional[float] = Field(None, description="RSI indicator", ge=0, le=100)
    atr: Optional[float] = Field(None, description="ATR indicator", ge=0)
    ema: Optional[float] = Field(None, description="EMA value", gt=0)
    sma: Optional[float] = Field(None, description="SMA value", gt=0)

    # Bollinger Bands
    bollinger_upper: Optional[float] = Field(None, description="Bollinger upper band", gt=0)
    bollinger_middle: Optional[float] = Field(None, description="Bollinger middle band", gt=0)
    bollinger_lower: Optional[float] = Field(None, description="Bollinger lower band", gt=0)

    # MACD
    macd: Optional[float] = Field(None, description="MACD value")
    macd_signal: Optional[float] = Field(None, description="MACD signal line")
    macd_histogram: Optional[float] = Field(None, description="MACD histogram")

    # Metadata
    data_source: str = Field(default="unknown", description="Data source")
    is_complete: bool = Field(default=True, description="Whether candle is complete")

    class Config:
        json_schema_extra = {
            "example": {
                "timestamp": "2025-01-15T10:30:00Z",
                "symbol": "BTC-USDT-SWAP",
                "timeframe": "1m",
                "open": 42500.0,
                "high": 42600.0,
                "low": 42450.0,
                "close": 42550.0,
                "volume": 123.45,
                "rsi": 55.5,
                "atr": 125.0,
                "data_source": "timescaledb",
                "is_complete": True
            }
        }

    def validate_ohlc(self) -> bool:
        """Validate OHLC relationships."""
        if self.high < max(self.open, self.close, self.low):
            return False
        if self.low > min(self.open, self.close, self.high):
            return False
        return True
