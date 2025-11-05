"""
Backtest Result Repository

Provides database access layer for backtest results using repository pattern.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import json

from BACKTEST.models.result import BacktestResult
from BACKTEST.models.trade import Trade, TradeSide, ExitReason
from shared.logging import get_logger

logger = get_logger(__name__)


class BacktestRepository:
    """Repository for backtest result persistence."""

    def __init__(self, session: AsyncSession):
        """
        Initialize repository with database session.

        Args:
            session: SQLAlchemy async session
        """
        self.session = session

    async def save(self, result: BacktestResult) -> UUID:
        """
        Save backtest result to database with transaction safety.

        Saves to three tables:
        - backtest_runs (main result)
        - backtest_trades (trade history)
        - backtest_balance_snapshots (equity curve)

        Args:
            result: Backtest result to save

        Returns:
            UUID of saved backtest run

        Raises:
            Exception: If save fails (auto-rollback)
        """
        try:
            # 1. Insert into backtest_runs
            run_query = text("""
                INSERT INTO backtest_runs (
                    id, user_id, symbol, timeframe, start_date, end_date,
                    strategy_name, strategy_params,
                    status, started_at, completed_at, execution_time_seconds,
                    total_trades, winning_trades, losing_trades,
                    total_return_percent, max_drawdown_percent,
                    sharpe_ratio, win_rate,
                    detailed_metrics
                ) VALUES (
                    :id, :user_id, :symbol, :timeframe, :start_date, :end_date,
                    :strategy_name, :strategy_params,
                    :status, :started_at, :completed_at, :execution_time_seconds,
                    :total_trades, :winning_trades, :losing_trades,
                    :total_return_percent, :max_drawdown_percent,
                    :sharpe_ratio, :win_rate,
                    :detailed_metrics
                )
            """)

            await self.session.execute(run_query, {
                'id': str(result.id),
                'user_id': str(result.user_id),
                'symbol': result.symbol,
                'timeframe': result.timeframe,
                'start_date': result.start_date,
                'end_date': result.end_date,
                'strategy_name': result.strategy_name,
                'strategy_params': json.dumps(result.strategy_params),
                'status': result.status,
                'started_at': result.started_at,
                'completed_at': result.completed_at,
                'execution_time_seconds': result.execution_time_seconds,
                'total_trades': result.total_trades,
                'winning_trades': result.winning_trades,
                'losing_trades': result.losing_trades,
                'total_return_percent': result.total_return_percent,
                'max_drawdown_percent': result.max_drawdown_percent,
                'sharpe_ratio': result.sharpe_ratio,
                'win_rate': result.win_rate,
                'detailed_metrics': json.dumps(result.detailed_metrics) if result.detailed_metrics else None
            })

            logger.info(f"✅ Saved backtest run: {result.id}")

            # 2. Insert trades
            if result.trades:
                await self._save_trades(result.id, result.trades)

            # 3. Insert equity curve
            if result.equity_curve:
                await self._save_equity_curve(result.id, result.equity_curve)

            await self.session.commit()
            logger.info(f"✅ Backtest result saved successfully: {result.id}")

            return result.id

        except Exception as e:
            await self.session.rollback()
            logger.error(f"❌ Failed to save backtest result: {e}", exc_info=True)
            raise

    async def _save_trades(self, backtest_id: UUID, trades: List[Trade]) -> None:
        """
        Save trade history to database.

        Args:
            backtest_id: Parent backtest run ID
            trades: List of trades to save
        """
        trade_query = text("""
            INSERT INTO backtest_trades (
                backtest_id, trade_number, side,
                entry_timestamp, entry_price, entry_reason,
                exit_timestamp, exit_price, exit_reason,
                quantity, leverage,
                pnl, pnl_percent,
                entry_fee, exit_fee,
                take_profit_price, stop_loss_price, trailing_stop_price,
                tp1_price, tp2_price, tp3_price,
                entry_rsi, entry_atr,
                dca_count, entry_history, total_investment,
                is_partial_exit, tp_level, exit_ratio, remaining_quantity
            ) VALUES (
                :backtest_id, :trade_number, :side,
                :entry_timestamp, :entry_price, :entry_reason,
                :exit_timestamp, :exit_price, :exit_reason,
                :quantity, :leverage,
                :pnl, :pnl_percent,
                :entry_fee, :exit_fee,
                :take_profit_price, :stop_loss_price, :trailing_stop_price,
                :tp1_price, :tp2_price, :tp3_price,
                :entry_rsi, :entry_atr,
                :dca_count, :entry_history, :total_investment,
                :is_partial_exit, :tp_level, :exit_ratio, :remaining_quantity
            )
        """)

        for trade in trades:
            await self.session.execute(trade_query, {
                'backtest_id': str(backtest_id),
                'trade_number': trade.trade_number,
                'side': trade.side.value if isinstance(trade.side, TradeSide) else trade.side,
                'entry_timestamp': trade.entry_timestamp,
                'entry_price': trade.entry_price,
                'entry_reason': trade.entry_reason,
                'exit_timestamp': trade.exit_timestamp,
                'exit_price': trade.exit_price,
                'exit_reason': trade.exit_reason.value if isinstance(trade.exit_reason, ExitReason) else trade.exit_reason,
                'quantity': trade.quantity,
                'leverage': trade.leverage,
                'pnl': trade.pnl,
                'pnl_percent': trade.pnl_percent,
                'entry_fee': trade.entry_fee,
                'exit_fee': trade.exit_fee,
                'take_profit_price': trade.take_profit_price,
                'stop_loss_price': trade.stop_loss_price,
                'trailing_stop_price': trade.trailing_stop_price,
                'tp1_price': getattr(trade, 'tp1_price', None),
                'tp2_price': getattr(trade, 'tp2_price', None),
                'tp3_price': getattr(trade, 'tp3_price', None),
                'entry_rsi': trade.entry_rsi,
                'entry_atr': trade.entry_atr,
                'dca_count': trade.dca_count,
                'entry_history': json.dumps(trade.entry_history) if trade.entry_history else None,
                'total_investment': trade.total_investment,
                'is_partial_exit': trade.is_partial_exit,
                'tp_level': trade.tp_level,
                'exit_ratio': trade.exit_ratio,
                'remaining_quantity': trade.remaining_quantity
            })

        logger.info(f"✅ Saved {len(trades)} trades for backtest {backtest_id}")

    async def _save_equity_curve(self, backtest_id: UUID, equity_curve: List[Dict[str, Any]]) -> None:
        """
        Save equity curve snapshots to database.

        Args:
            backtest_id: Parent backtest run ID
            equity_curve: List of balance snapshots
        """
        snapshot_query = text("""
            INSERT INTO backtest_balance_snapshots (
                backtest_id, timestamp, balance, equity,
                cumulative_pnl, cumulative_trades
            ) VALUES (
                :backtest_id, :timestamp, :balance, :equity,
                :cumulative_pnl, :cumulative_trades
            )
        """)

        for snapshot in equity_curve:
            # Parse timestamp if it's a string
            timestamp = snapshot.get('timestamp')
            if isinstance(timestamp, str):
                from datetime import datetime
                timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))

            await self.session.execute(snapshot_query, {
                'backtest_id': str(backtest_id),
                'timestamp': timestamp,
                'balance': snapshot.get('balance'),
                'equity': snapshot.get('equity', snapshot.get('balance')),
                'cumulative_pnl': snapshot.get('pnl', 0),
                'cumulative_trades': snapshot.get('trade_number', 0)
            })

        logger.info(f"✅ Saved {len(equity_curve)} snapshots for backtest {backtest_id}")

    async def get_by_id(self, backtest_id: UUID) -> Optional[BacktestResult]:
        """
        Retrieve backtest result by ID with all related data.

        Args:
            backtest_id: Backtest run ID

        Returns:
            BacktestResult or None if not found
        """
        try:
            # 1. Get main result
            run_query = text("""
                SELECT
                    id, user_id, symbol, timeframe, start_date, end_date,
                    strategy_name, strategy_params,
                    status, started_at, completed_at, execution_time_seconds,
                    total_trades, winning_trades, losing_trades,
                    total_return_percent, max_drawdown_percent,
                    sharpe_ratio, win_rate,
                    detailed_metrics,
                    created_at
                FROM backtest_runs
                WHERE id = :id
            """)

            result = await self.session.execute(run_query, {'id': str(backtest_id)})
            row = result.fetchone()

            if not row:
                return None

            # 2. Get trades
            trades = await self._get_trades(backtest_id)

            # 3. Get equity curve
            equity_curve = await self._get_equity_curve(backtest_id)

            # Extract initial and final balance from equity curve
            initial_balance = equity_curve[0].get('balance', 10000.0) if equity_curve else 10000.0
            final_balance = equity_curve[-1].get('balance', 10000.0) if equity_curve else 10000.0

            # 4. Build BacktestResult
            # Convert asyncpg UUIDs to Python UUIDs safely
            result_id = row.id if isinstance(row.id, UUID) else UUID(str(row.id))
            result_user_id = row.user_id if isinstance(row.user_id, UUID) else (UUID(str(row.user_id)) if row.user_id else None)

            backtest_result = BacktestResult(
                id=result_id,
                user_id=result_user_id,
                symbol=row.symbol,
                timeframe=row.timeframe,
                start_date=row.start_date,
                end_date=row.end_date,
                strategy_name=row.strategy_name,
                strategy_params=json.loads(row.strategy_params) if isinstance(row.strategy_params, str) else row.strategy_params,
                status=row.status,
                started_at=row.started_at,
                completed_at=row.completed_at,
                execution_time_seconds=float(row.execution_time_seconds) if row.execution_time_seconds else None,
                initial_balance=initial_balance,
                final_balance=final_balance,
                total_trades=row.total_trades or 0,
                winning_trades=row.winning_trades or 0,
                losing_trades=row.losing_trades or 0,
                total_return_percent=float(row.total_return_percent) if row.total_return_percent else 0.0,
                max_drawdown_percent=float(row.max_drawdown_percent) if row.max_drawdown_percent else 0.0,
                win_rate=float(row.win_rate) if row.win_rate else 0.0,
                sharpe_ratio=float(row.sharpe_ratio) if row.sharpe_ratio else None,
                trades=trades,
                equity_curve=equity_curve,
                detailed_metrics=json.loads(row.detailed_metrics) if isinstance(row.detailed_metrics, str) else row.detailed_metrics
            )

            logger.info(f"✅ Retrieved backtest result: {backtest_id}")
            return backtest_result

        except Exception as e:
            logger.error(f"❌ Failed to get backtest result {backtest_id}: {e}", exc_info=True)
            raise

    async def _get_trades(self, backtest_id: UUID) -> List[Trade]:
        """Get all trades for a backtest run."""
        trade_query = text("""
            SELECT
                trade_number, side,
                entry_timestamp, entry_price, entry_reason,
                exit_timestamp, exit_price, exit_reason,
                quantity, leverage,
                pnl, pnl_percent,
                entry_fee, exit_fee,
                take_profit_price, stop_loss_price, trailing_stop_price,
                tp1_price, tp2_price, tp3_price,
                entry_rsi, entry_atr,
                dca_count, entry_history, total_investment,
                is_partial_exit, tp_level, exit_ratio, remaining_quantity
            FROM backtest_trades
            WHERE backtest_id = :backtest_id
            ORDER BY trade_number ASC
        """)

        result = await self.session.execute(trade_query, {'backtest_id': str(backtest_id)})
        rows = result.fetchall()

        trades = []
        for row in rows:
            trade = Trade(
                trade_number=row.trade_number,
                side=TradeSide(row.side),
                entry_timestamp=row.entry_timestamp,
                entry_price=float(row.entry_price),
                entry_reason=row.entry_reason,
                exit_timestamp=row.exit_timestamp,
                exit_price=float(row.exit_price) if row.exit_price else None,
                exit_reason=ExitReason(row.exit_reason) if row.exit_reason else None,
                quantity=float(row.quantity),
                leverage=float(row.leverage),
                pnl=float(row.pnl) if row.pnl else None,
                pnl_percent=float(row.pnl_percent) if row.pnl_percent else None,
                entry_fee=float(row.entry_fee) if row.entry_fee else 0,
                exit_fee=float(row.exit_fee) if row.exit_fee else 0,
                take_profit_price=float(row.take_profit_price) if row.take_profit_price else None,
                stop_loss_price=float(row.stop_loss_price) if row.stop_loss_price else None,
                trailing_stop_price=float(row.trailing_stop_price) if row.trailing_stop_price else None,
                tp1_price=float(row.tp1_price) if row.tp1_price else None,
                tp2_price=float(row.tp2_price) if row.tp2_price else None,
                tp3_price=float(row.tp3_price) if row.tp3_price else None,
                entry_rsi=float(row.entry_rsi) if row.entry_rsi else None,
                entry_atr=float(row.entry_atr) if row.entry_atr else None,
                dca_count=row.dca_count or 0,
                entry_history=json.loads(row.entry_history) if isinstance(row.entry_history, str) else row.entry_history or [],
                total_investment=float(row.total_investment) if row.total_investment else None,
                is_partial_exit=row.is_partial_exit or False,
                tp_level=row.tp_level,
                exit_ratio=float(row.exit_ratio) if row.exit_ratio else None,
                remaining_quantity=float(row.remaining_quantity) if row.remaining_quantity else None
            )
            trades.append(trade)

        return trades

    async def _get_equity_curve(self, backtest_id: UUID) -> List[Dict[str, Any]]:
        """Get equity curve snapshots for a backtest run."""
        snapshot_query = text("""
            SELECT
                timestamp, balance, equity,
                cumulative_pnl, cumulative_trades
            FROM backtest_balance_snapshots
            WHERE backtest_id = :backtest_id
            ORDER BY timestamp ASC
        """)

        result = await self.session.execute(snapshot_query, {'backtest_id': str(backtest_id)})
        rows = result.fetchall()

        return [
            {
                'timestamp': row.timestamp.isoformat() if hasattr(row.timestamp, 'isoformat') else row.timestamp,
                'balance': float(row.balance),
                'equity': float(row.equity),
                'pnl': float(row.cumulative_pnl) if row.cumulative_pnl else 0,
                'trade_number': row.cumulative_trades or 0
            }
            for row in rows
        ]

    async def list_by_user(
        self,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        List backtest results for a user with pagination.

        Args:
            user_id: User ID
            limit: Maximum results per page
            offset: Pagination offset

        Returns:
            List of backtest summaries
        """
        try:
            list_query = text("""
                SELECT
                    id, symbol, timeframe,
                    strategy_name,
                    total_trades, winning_trades, losing_trades,
                    total_return_percent, max_drawdown_percent,
                    win_rate, sharpe_ratio,
                    created_at, status
                FROM backtest_runs
                WHERE user_id = :user_id
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """)

            result = await self.session.execute(list_query, {
                'user_id': str(user_id),
                'limit': limit,
                'offset': offset
            })

            rows = result.fetchall()

            return [
                {
                    'id': str(row.id),  # Convert UUID to string for JSON serialization
                    'symbol': row.symbol,
                    'timeframe': row.timeframe,
                    'strategy_name': row.strategy_name,
                    'total_trades': row.total_trades,
                    'winning_trades': row.winning_trades,
                    'losing_trades': row.losing_trades,
                    'total_return_percent': float(row.total_return_percent) if row.total_return_percent else 0.0,
                    'max_drawdown_percent': float(row.max_drawdown_percent) if row.max_drawdown_percent else 0.0,
                    'win_rate': float(row.win_rate) if row.win_rate else 0.0,
                    'sharpe_ratio': float(row.sharpe_ratio) if row.sharpe_ratio else None,
                    'created_at': row.created_at.isoformat() if row.created_at else None,
                    'status': row.status
                }
                for row in rows
            ]

        except Exception as e:
            logger.error(f"❌ Failed to list backtests for user {user_id}: {e}", exc_info=True)
            raise

    async def delete(self, backtest_id: UUID, user_id: UUID) -> bool:
        """
        Delete backtest result (with authorization check).

        Args:
            backtest_id: Backtest run ID
            user_id: User ID (for authorization)

        Returns:
            True if deleted, False if not found or unauthorized

        Raises:
            Exception: If delete fails
        """
        try:
            delete_query = text("""
                DELETE FROM backtest_runs
                WHERE id = :id AND user_id = :user_id
            """)

            result = await self.session.execute(delete_query, {
                'id': str(backtest_id),
                'user_id': str(user_id)
            })

            await self.session.commit()

            if result.rowcount > 0:
                logger.info(f"✅ Deleted backtest {backtest_id}")
                return True
            else:
                logger.warning(f"⚠️ Backtest {backtest_id} not found or unauthorized")
                return False

        except Exception as e:
            await self.session.rollback()
            logger.error(f"❌ Failed to delete backtest {backtest_id}: {e}", exc_info=True)
            raise

    async def get_stats(self, user_id: UUID) -> Dict[str, Any]:
        """
        Get backtest statistics for a user.

        Args:
            user_id: User ID

        Returns:
            Statistics dict
        """
        try:
            stats_query = text("""
                SELECT
                    COUNT(*) as total_backtests,
                    AVG(total_return_percent) as avg_return,
                    MAX(total_return_percent) as best_return,
                    MIN(total_return_percent) as worst_return,
                    AVG(win_rate) as avg_win_rate,
                    AVG(sharpe_ratio) as avg_sharpe_ratio
                FROM backtest_runs
                WHERE user_id = :user_id
                  AND status = 'completed'
            """)

            result = await self.session.execute(stats_query, {'user_id': str(user_id)})
            row = result.fetchone()

            if not row or row.total_backtests == 0:
                return {
                    'total_backtests': 0,
                    'avg_return': 0.0,
                    'best_return': 0.0,
                    'worst_return': 0.0,
                    'avg_win_rate': 0.0,
                    'avg_sharpe_ratio': 0.0
                }

            return {
                'total_backtests': row.total_backtests,
                'avg_return': float(row.avg_return) if row.avg_return else 0.0,
                'best_return': float(row.best_return) if row.best_return else 0.0,
                'worst_return': float(row.worst_return) if row.worst_return else 0.0,
                'avg_win_rate': float(row.avg_win_rate) if row.avg_win_rate else 0.0,
                'avg_sharpe_ratio': float(row.avg_sharpe_ratio) if row.avg_sharpe_ratio else 0.0
            }

        except Exception as e:
            logger.error(f"❌ Failed to get stats for user {user_id}: {e}", exc_info=True)
            raise

