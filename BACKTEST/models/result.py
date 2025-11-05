"""
Backtest result model.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from uuid import UUID, uuid4

from BACKTEST.models.trade import Trade


class BacktestResult(BaseModel):
    """Comprehensive backtest results."""

    # Run metadata
    id: UUID = Field(default_factory=uuid4, description="Backtest run ID")
    user_id: Optional[UUID] = Field(None, description="User ID (optional for standalone backtests)")
    symbol: str = Field(..., description="Trading symbol")
    timeframe: str = Field(..., description="Timeframe")
    start_date: datetime = Field(..., description="Backtest start date")
    end_date: datetime = Field(..., description="Backtest end date")

    # Strategy configuration
    strategy_name: str = Field(default="hyperrsi", description="Strategy name")
    strategy_params: Dict[str, Any] = Field(..., description="Strategy parameters")

    # Execution info
    status: str = Field(default="completed", description="Run status")
    started_at: datetime = Field(..., description="Execution start time")
    completed_at: Optional[datetime] = Field(None, description="Execution completion time")
    execution_time_seconds: Optional[float] = Field(None, description="Execution duration")

    # Trading results
    initial_balance: float = Field(..., description="Starting capital", gt=0)
    final_balance: float = Field(..., description="Ending capital", gt=0)
    unrealized_pnl: float = Field(default=0.0, description="Unrealized P&L from open positions")
    total_trades: int = Field(default=0, description="Total number of trades", ge=0)
    winning_trades: int = Field(default=0, description="Number of winning trades", ge=0)
    losing_trades: int = Field(default=0, description="Number of losing trades", ge=0)

    # Performance metrics
    total_return: float = Field(default=0.0, description="Total return amount")
    total_return_percent: float = Field(default=0.0, description="Total return percentage")
    max_drawdown: float = Field(default=0.0, description="Maximum drawdown amount", le=0)
    max_drawdown_percent: float = Field(default=0.0, description="Maximum drawdown percentage", le=0)

    win_rate: float = Field(default=0.0, description="Win rate percentage", ge=0, le=100)
    profit_factor: float = Field(default=0.0, description="Profit factor", ge=0)
    sharpe_ratio: Optional[float] = Field(None, description="Sharpe ratio")
    sortino_ratio: Optional[float] = Field(None, description="Sortino ratio")

    avg_win: float = Field(default=0.0, description="Average winning trade")
    avg_loss: float = Field(default=0.0, description="Average losing trade")
    largest_win: float = Field(default=0.0, description="Largest winning trade")
    largest_loss: float = Field(default=0.0, description="Largest losing trade", le=0)

    avg_trade_duration_minutes: Optional[float] = Field(None, description="Average trade duration")
    total_fees_paid: float = Field(default=0.0, description="Total fees paid", ge=0)

    # Trade history
    trades: List[Trade] = Field(default_factory=list, description="All executed trades")

    # Equity curve data points (timestamp, balance)
    equity_curve: List[Dict[str, Any]] = Field(default_factory=list, description="Balance over time")

    # Additional metrics
    detailed_metrics: Optional[Dict[str, Any]] = Field(None, description="Additional analysis")

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
                    "rsi_overbought": 70,
                    "leverage": 10,
                    "investment": 100
                },
                "status": "completed",
                "started_at": "2025-01-15T10:00:00Z",
                "completed_at": "2025-01-15T10:05:30Z",
                "execution_time_seconds": 330.5,
                "initial_balance": 10000.0,
                "final_balance": 11250.0,
                "total_trades": 45,
                "winning_trades": 28,
                "losing_trades": 17,
                "total_return": 1250.0,
                "total_return_percent": 12.5,
                "max_drawdown": -450.0,
                "max_drawdown_percent": -4.5,
                "win_rate": 62.22,
                "profit_factor": 1.85,
                "sharpe_ratio": 1.45,
                "avg_win": 75.5,
                "avg_loss": -35.2,
                "largest_win": 250.0,
                "largest_loss": -120.0,
                "avg_trade_duration_minutes": 45.3,
                "total_fees_paid": 125.50
            }
        }

    def calculate_metrics(self) -> None:
        """Calculate all performance metrics from trade history."""
        if not self.trades:
            return

        closed_trades = [t for t in self.trades if not t.is_open]

        if not closed_trades:
            return

        # Count wins/losses
        winners = [t for t in closed_trades if t.pnl and t.pnl > 0]
        losers = [t for t in closed_trades if t.pnl and t.pnl < 0]

        self.total_trades = len(closed_trades)
        self.winning_trades = len(winners)
        self.losing_trades = len(losers)

        # Win rate
        if self.total_trades > 0:
            self.win_rate = (self.winning_trades / self.total_trades) * 100

        # Average win/loss
        if winners:
            self.avg_win = sum(t.pnl for t in winners) / len(winners)
            self.largest_win = max(t.pnl for t in winners)

        if losers:
            self.avg_loss = sum(t.pnl for t in losers) / len(losers)
            self.largest_loss = min(t.pnl for t in losers)

        # Profit factor
        total_profit = sum(t.pnl for t in winners) if winners else 0
        total_loss = abs(sum(t.pnl for t in losers)) if losers else 0
        if total_loss > 0:
            self.profit_factor = total_profit / total_loss

        # Total return
        self.total_return = self.final_balance - self.initial_balance
        if self.initial_balance > 0:
            self.total_return_percent = (self.total_return / self.initial_balance) * 100

        # Average trade duration
        durations = [t.duration_seconds for t in closed_trades if t.duration_seconds]
        if durations:
            avg_seconds = sum(durations) / len(durations)
            self.avg_trade_duration_minutes = avg_seconds / 60

        # Total fees
        self.total_fees_paid = sum(t.total_fees for t in closed_trades)

    def calculate_sharpe_ratio(self, risk_free_rate: float = 0.0) -> float:
        """
        Calculate Sharpe ratio from trade returns.

        Args:
            risk_free_rate: Annual risk-free rate (default 0%)

        Returns:
            Sharpe ratio
        """
        if not self.trades:
            return 0.0

        import numpy as np

        # Get returns from closed trades
        returns = [
            t.pnl_percent for t in self.trades
            if not t.is_open and t.pnl_percent is not None
        ]

        if len(returns) < 2:
            return 0.0

        returns_array = np.array(returns)
        mean_return = np.mean(returns_array)
        std_return = np.std(returns_array)

        if std_return == 0:
            return 0.0

        sharpe = (mean_return - risk_free_rate) / std_return
        return float(sharpe)
