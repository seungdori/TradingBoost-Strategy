"""
API request schemas for BACKTEST service.
"""

from datetime import datetime
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, validator
from uuid import UUID


class BacktestRunRequest(BaseModel):
    """Request schema for running a backtest."""

    # Time period
    symbol: str = Field(..., description="Trading symbol", example="BTC-USDT-SWAP")
    timeframe: str = Field(..., description="Timeframe", example="1m")
    start_date: datetime = Field(..., description="Start date (UTC)")
    end_date: datetime = Field(..., description="End date (UTC)")

    # Strategy configuration
    strategy_name: str = Field(default="hyperrsi", description="Strategy name")
    strategy_params: Dict[str, Any] = Field(..., description="Strategy parameters")

    # Optional settings
    initial_balance: Optional[float] = Field(10000.0, description="Initial capital", gt=0)
    fee_rate: Optional[float] = Field(0.0005, description="Trading fee rate", ge=0, le=0.01)
    slippage_percent: Optional[float] = Field(0.05, description="Slippage %", ge=0, le=1.0)

    @validator("end_date")
    def validate_dates(cls, v, values):
        """Validate that end_date is after start_date."""
        if "start_date" in values and v <= values["start_date"]:
            raise ValueError("end_date must be after start_date")
        return v

    @validator("timeframe")
    def validate_timeframe(cls, v):
        """Validate timeframe format."""
        valid_timeframes = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"]
        if v not in valid_timeframes:
            raise ValueError(f"Invalid timeframe. Must be one of: {valid_timeframes}")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "symbol": "BTC-USDT-SWAP",
                "timeframe": "1m",
                "start_date": "2025-01-01T00:00:00Z",
                "end_date": "2025-01-31T23:59:59Z",
                "strategy_name": "hyperrsi",
                "strategy_params": {
                    "entry_option": "rsi_trend",
                    "rsi_entry_option": "돌파",  # 4가지: "초과" | "돌파" | "변곡" | "변곡돌파"
                    "rsi_oversold": 30,
                    "rsi_overbought": 70,
                    "rsi_period": 14,
                    "leverage": 10,
                    "investment": 100,
                    "tp_sl_option": "fixed",
                    "stop_loss_percent": 2.0,
                    "take_profit_percent": 4.0,
                    "use_tp1": True,
                    "use_tp2": True,
                    "use_tp3": True,
                    "tp1_ratio": 30,
                    "tp2_ratio": 30,
                    "tp3_ratio": 40,
                    "tp1_value": 2.0,
                    "tp2_value": 3.0,
                    "tp3_value": 4.0,
                    "pyramiding_limit": 3,
                    "entry_multiplier": 0.5,
                    "pyramiding_entry_type": "퍼센트 기준",
                    "pyramiding_value": 3.0,
                    "trailing_stop_enabled": False
                },
                "initial_balance": 10000.0,
                "fee_rate": 0.0005,
                "slippage_percent": 0.05
            }
        }


class OptimizationRequest(BaseModel):
    """Request schema for parameter optimization."""

    # Time period
    symbol: str = Field(..., description="Trading symbol")
    timeframe: str = Field(..., description="Timeframe")
    start_date: datetime = Field(..., description="Start date (UTC)")
    end_date: datetime = Field(..., description="End date (UTC)")

    # Strategy
    strategy_name: str = Field(default="hyperrsi", description="Strategy name")

    # Parameter ranges to optimize
    param_ranges: Dict[str, Any] = Field(
        ...,
        description="Parameter ranges for optimization"
    )

    # Optimization settings
    optimization_method: str = Field(default="grid_search", description="Optimization method")
    optimization_metric: str = Field(default="sharpe_ratio", description="Metric to optimize")

    # Optional settings
    initial_balance: Optional[float] = Field(10000.0, description="Initial capital", gt=0)
    max_iterations: Optional[int] = Field(100, description="Max optimization iterations", gt=0)

    class Config:
        json_schema_extra = {
            "example": {
                "symbol": "BTC-USDT-SWAP",
                "timeframe": "5m",
                "start_date": "2025-01-01T00:00:00Z",
                "end_date": "2025-01-31T23:59:59Z",
                "strategy_name": "hyperrsi",
                "param_ranges": {
                    "rsi_oversold": [25, 30, 35],
                    "rsi_overbought": [65, 70, 75],
                    "stop_loss_percent": [1.5, 2.0, 2.5],
                    "take_profit_percent": [3.0, 4.0, 5.0]
                },
                "optimization_method": "grid_search",
                "optimization_metric": "sharpe_ratio",
                "initial_balance": 10000.0,
                "max_iterations": 100
            }
        }


class BacktestListRequest(BaseModel):
    """Request schema for listing backtests."""

    user_id: Optional[UUID] = Field(None, description="Filter by user ID")
    symbol: Optional[str] = Field(None, description="Filter by symbol")
    strategy_name: Optional[str] = Field(None, description="Filter by strategy")
    limit: Optional[int] = Field(50, description="Max results", ge=1, le=100)
    offset: Optional[int] = Field(0, description="Pagination offset", ge=0)

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "123e4567-e89b-12d3-a456-426614174000",
                "symbol": "BTC-USDT-SWAP",
                "strategy_name": "hyperrsi",
                "limit": 20,
                "offset": 0
            }
        }


class CandleDataRequest(BaseModel):
    """Request schema for fetching candle data for chart display."""

    symbol: str = Field(..., description="Trading symbol", example="BTC/USDT:USDT")
    timeframe: str = Field(..., description="Timeframe", example="15m")
    start_date: datetime = Field(..., description="Start date (UTC)")
    end_date: datetime = Field(..., description="End date (UTC)")

    @validator("end_date")
    def validate_dates(cls, v, values):
        """Validate that end_date is after start_date."""
        if "start_date" in values and v <= values["start_date"]:
            raise ValueError("end_date must be after start_date")
        return v

    @validator("timeframe")
    def validate_timeframe(cls, v):
        """Validate timeframe format."""
        valid_timeframes = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"]
        if v not in valid_timeframes:
            raise ValueError(f"Invalid timeframe. Must be one of: {valid_timeframes}")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "symbol": "BTC/USDT:USDT",
                "timeframe": "15m",
                "start_date": "2025-01-01T00:00:00Z",
                "end_date": "2025-01-31T23:59:59Z"
            }
        }


class RecalculateIndicatorsRequest(BaseModel):
    """Request schema for recalculating indicators and trend_state."""

    symbol: str = Field(..., description="Trading symbol", example="BTC-USDT-SWAP")
    timeframe: str = Field(..., description="Timeframe", example="15m")
    start_date: Optional[datetime] = Field(None, description="Start date (UTC), if None recalculate all")
    end_date: Optional[datetime] = Field(None, description="End date (UTC), if None use now")

    @validator("timeframe")
    def validate_timeframe(cls, v):
        """Validate timeframe format."""
        valid_timeframes = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"]
        if v not in valid_timeframes:
            raise ValueError(f"Invalid timeframe. Must be one of: {valid_timeframes}")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "symbol": "BTC-USDT-SWAP",
                "timeframe": "15m",
                "start_date": "2025-01-01T00:00:00Z",
                "end_date": "2025-01-31T23:59:59Z"
            }
        }
