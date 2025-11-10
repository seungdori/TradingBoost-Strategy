"""
API response schemas for BACKTEST service.
"""

from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from uuid import UUID


class TradeResponse(BaseModel):
    """Trade result response."""

    trade_number: int
    side: str
    entry_timestamp: datetime
    entry_price: float
    exit_timestamp: Optional[datetime]
    exit_price: Optional[float]
    exit_reason: Optional[str]
    quantity: float
    leverage: float
    pnl: Optional[float]
    pnl_percent: Optional[float]
    entry_fee: float
    exit_fee: float

    # TP/SL levels
    take_profit_price: Optional[float] = Field(None, description="Take profit price")
    stop_loss_price: Optional[float] = Field(None, description="Stop loss price")
    trailing_stop_price: Optional[float] = Field(None, description="Trailing stop price")

    # Partial TP levels (TP1/TP2/TP3)
    tp1_price: Optional[float] = Field(None, description="TP1 price for partial exit")
    tp2_price: Optional[float] = Field(None, description="TP2 price for partial exit")
    tp3_price: Optional[float] = Field(None, description="TP3 price for partial exit")

    # DCA levels
    next_dca_levels: List[float] = Field(default_factory=list, description="Next DCA entry levels")

    # Entry indicators
    entry_rsi: Optional[float] = Field(None, description="RSI at entry")
    entry_atr: Optional[float] = Field(None, description="ATR at entry")

    # DCA metadata
    dca_count: int = Field(default=0, description="Number of additional entries")
    entry_history: List[Dict[str, Any]] = Field(default_factory=list, description="Entry history records")
    total_investment: float = Field(default=0.0, description="Total investment (USDT)")

    # Partial exit metadata (TP1/TP2/TP3)
    is_partial_exit: bool = Field(default=False, description="Is this a partial exit trade")
    tp_level: Optional[int] = Field(None, description="TP level (1, 2, or 3) for partial exits")
    exit_ratio: Optional[float] = Field(None, description="Exit ratio for partial exits (0-1)")
    remaining_quantity: Optional[float] = Field(None, description="Remaining quantity after partial exit")


class BacktestSummaryResponse(BaseModel):
    """Backtest result summary."""

    id: UUID
    symbol: str
    timeframe: str
    start_date: datetime
    end_date: datetime
    strategy_name: str
    status: str
    execution_time_seconds: Optional[float]

    # Key metrics
    total_trades: int
    win_rate: float
    total_return_percent: float
    max_drawdown_percent: float
    sharpe_ratio: Optional[float]
    profit_factor: float

    created_at: datetime = Field(default_factory=datetime.utcnow)


class BacktestDetailResponse(BaseModel):
    """Detailed backtest result."""

    # Metadata
    id: UUID
    user_id: UUID
    symbol: str
    timeframe: str
    start_date: datetime
    end_date: datetime
    strategy_name: str
    strategy_params: Dict[str, Any]

    # Execution info
    status: str
    started_at: datetime
    completed_at: Optional[datetime]
    execution_time_seconds: Optional[float]

    # Financial results
    initial_balance: float
    final_balance: float
    total_return: float
    total_return_percent: float
    max_drawdown: float
    max_drawdown_percent: float

    # Trading statistics
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: float
    sharpe_ratio: Optional[float]
    sortino_ratio: Optional[float]

    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float
    avg_trade_duration_minutes: Optional[float]
    total_fees_paid: float

    # Trade history
    trades: List[TradeResponse]

    # Equity curve
    equity_curve: List[Dict[str, Any]]

    # Additional metrics
    detailed_metrics: Optional[Dict[str, Any]]

    class Config:
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "user_id": "123e4567-e89b-12d3-a456-426614174001",
                "symbol": "BTC-USDT-SWAP",
                "timeframe": "1m",
                "start_date": "2025-01-01T00:00:00Z",
                "end_date": "2025-01-31T23:59:59Z",
                "strategy_name": "hyperrsi",
                "strategy_params": {
                    "entry_option": "rsi_trend",
                    "rsi_oversold": 30,
                    "leverage": 10
                },
                "status": "completed",
                "started_at": "2025-01-15T10:00:00Z",
                "completed_at": "2025-01-15T10:05:30Z",
                "execution_time_seconds": 330.5,
                "initial_balance": 10000.0,
                "final_balance": 11250.0,
                "total_return": 1250.0,
                "total_return_percent": 12.5,
                "max_drawdown": -450.0,
                "max_drawdown_percent": -4.5,
                "total_trades": 45,
                "winning_trades": 28,
                "losing_trades": 17,
                "win_rate": 62.22,
                "profit_factor": 1.85,
                "sharpe_ratio": 1.45,
                "avg_win": 75.5,
                "avg_loss": -35.2,
                "largest_win": 250.0,
                "largest_loss": -120.0,
                "avg_trade_duration_minutes": 45.3,
                "total_fees_paid": 125.50,
                "trades": [],
                "equity_curve": []
            }
        }


class BacktestListResponse(BaseModel):
    """List of backtest results."""

    results: List[BacktestSummaryResponse]
    total: int
    limit: int
    offset: int


class OptimizationResultResponse(BaseModel):
    """Parameter optimization result."""

    optimization_id: UUID
    symbol: str
    timeframe: str
    strategy_name: str
    optimization_method: str
    optimization_metric: str

    # Best parameters found
    best_params: Dict[str, Any]
    best_score: float

    # All tested combinations
    total_combinations: int
    completed_combinations: int

    # Execution info
    started_at: datetime
    completed_at: Optional[datetime]
    execution_time_seconds: Optional[float]

    # Top results
    top_results: List[Dict[str, Any]]

    class Config:
        json_schema_extra = {
            "example": {
                "optimization_id": "123e4567-e89b-12d3-a456-426614174002",
                "symbol": "BTC-USDT-SWAP",
                "timeframe": "5m",
                "strategy_name": "hyperrsi",
                "optimization_method": "grid_search",
                "optimization_metric": "sharpe_ratio",
                "best_params": {
                    "rsi_oversold": 30,
                    "rsi_overbought": 70,
                    "stop_loss_percent": 2.0,
                    "take_profit_percent": 4.0
                },
                "best_score": 1.85,
                "total_combinations": 81,
                "completed_combinations": 81,
                "started_at": "2025-01-15T10:00:00Z",
                "completed_at": "2025-01-15T11:30:00Z",
                "execution_time_seconds": 5400.0,
                "top_results": []
            }
        }


class ErrorResponse(BaseModel):
    """Error response."""

    error: str
    detail: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_schema_extra = {
            "example": {
                "error": "Data not available",
                "detail": "No candle data found for the specified period",
                "timestamp": "2025-01-15T10:00:00Z"
            }
        }


class CandleData(BaseModel):
    """Single candle data point."""

    timestamp: datetime = Field(..., description="Candle timestamp")
    open: str = Field(..., description="Open price")
    high: str = Field(..., description="High price")
    low: str = Field(..., description="Low price")
    close: str = Field(..., description="Close price")
    volume: str = Field(..., description="Trading volume")

    class Config:
        json_schema_extra = {
            "example": {
                "timestamp": "2025-01-01T00:00:00Z",
                "open": "42000.50",
                "high": "42100.75",
                "low": "41950.25",
                "close": "42050.00",
                "volume": "125.45"
            }
        }
