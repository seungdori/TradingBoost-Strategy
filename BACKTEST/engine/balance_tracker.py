"""
Balance tracker for backtest equity curve management.
"""

from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from shared.logging import get_logger

logger = get_logger(__name__)


@dataclass
class BalanceSnapshot:
    """Single balance snapshot for equity curve."""

    timestamp: datetime
    balance: float
    equity: float  # balance + unrealized P&L
    position_side: Optional[str] = None
    position_size: float = 0.0
    unrealized_pnl: float = 0.0
    cumulative_pnl: float = 0.0
    cumulative_trades: int = 0


class BalanceTracker:
    """Tracks balance and equity curve during backtesting."""

    def __init__(self, initial_balance: float):
        """
        Initialize balance tracker.

        Args:
            initial_balance: Starting capital
        """
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.snapshots: List[BalanceSnapshot] = []

        # Drawdown tracking
        self.peak_balance = initial_balance
        self.current_drawdown = 0.0
        self.max_drawdown = 0.0
        self.max_drawdown_percent = 0.0

        # P&L tracking
        self.cumulative_pnl = 0.0
        self.cumulative_trades = 0

        logger.info(f"BalanceTracker initialized with {initial_balance} USDT")

    def add_snapshot(
        self,
        timestamp: datetime,
        position_side: Optional[str] = None,
        position_size: float = 0.0,
        unrealized_pnl: float = 0.0
    ) -> None:
        """
        Add a balance snapshot to the equity curve.

        Args:
            timestamp: Snapshot timestamp
            position_side: Current position side (long/short) or None
            position_size: Current position size
            unrealized_pnl: Current unrealized P&L
        """
        equity = self.current_balance + unrealized_pnl

        snapshot = BalanceSnapshot(
            timestamp=timestamp,
            balance=self.current_balance,
            equity=equity,
            position_side=position_side,
            position_size=position_size,
            unrealized_pnl=unrealized_pnl,
            cumulative_pnl=self.cumulative_pnl,
            cumulative_trades=self.cumulative_trades
        )

        self.snapshots.append(snapshot)

        # Update drawdown tracking
        self._update_drawdown(equity)

    def update_balance(self, pnl: float, fee: float = 0.0) -> None:
        """
        Update balance after trade close.

        Args:
            pnl: Realized profit/loss
            fee: Trading fee paid
        """
        net_pnl = pnl - fee
        self.current_balance += net_pnl
        self.cumulative_pnl += net_pnl
        self.cumulative_trades += 1

        logger.debug(
            f"Balance updated: PNL={net_pnl:.2f}, "
            f"New balance={self.current_balance:.2f}"
        )

    def _update_drawdown(self, current_equity: float) -> None:
        """
        Update drawdown metrics.

        Args:
            current_equity: Current equity value
        """
        # Update peak
        if current_equity > self.peak_balance:
            self.peak_balance = current_equity
            self.current_drawdown = 0.0
        else:
            # Calculate drawdown
            self.current_drawdown = current_equity - self.peak_balance

            # Update max drawdown if current is worse
            if self.current_drawdown < self.max_drawdown:
                self.max_drawdown = self.current_drawdown
                if self.peak_balance > 0:
                    self.max_drawdown_percent = (self.max_drawdown / self.peak_balance) * 100

    def get_equity_curve(self) -> List[Dict[str, Any]]:
        """
        Get equity curve data for visualization.

        Returns:
            List of equity curve points
        """
        return [
            {
                "timestamp": snap.timestamp.isoformat(),
                "balance": snap.balance,
                "equity": snap.equity,
                "cumulative_pnl": snap.cumulative_pnl,
                "drawdown": snap.equity - self.peak_balance
            }
            for snap in self.snapshots
        ]

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get balance statistics.

        Returns:
            Dictionary of statistics
        """
        if not self.snapshots:
            return {}

        equities = [snap.equity for snap in self.snapshots]

        return {
            "initial_balance": self.initial_balance,
            "current_balance": self.current_balance,
            "peak_balance": self.peak_balance,
            "max_drawdown": self.max_drawdown,
            "max_drawdown_percent": self.max_drawdown_percent,
            "cumulative_pnl": self.cumulative_pnl,
            "cumulative_trades": self.cumulative_trades,
            "total_return_percent": ((self.current_balance - self.initial_balance) / self.initial_balance) * 100,
            "min_equity": min(equities),
            "max_equity": max(equities),
            "avg_equity": sum(equities) / len(equities)
        }

    def reset(self) -> None:
        """Reset tracker to initial state."""
        self.current_balance = self.initial_balance
        self.snapshots.clear()
        self.peak_balance = self.initial_balance
        self.current_drawdown = 0.0
        self.max_drawdown = 0.0
        self.max_drawdown_percent = 0.0
        self.cumulative_pnl = 0.0
        self.cumulative_trades = 0

        logger.info("BalanceTracker reset to initial state")
