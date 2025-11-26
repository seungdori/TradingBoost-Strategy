"""
HYPERRSI Trading Statistics Service.

트레이딩 통계 계산 서비스 - MDD, 샤프비율, 승률, 수익팩터 등 종합 통계 제공.
"""

from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, asdict
import math

from sqlalchemy import select, func, text, case
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.session import get_transactional_session
from shared.logging import get_logger

from HYPERRSI.src.core.models.trade import HyperrsiTrade, HyperrsiDailyStats

logger = get_logger(__name__)


@dataclass
class PnLStats:
    """손익 통계."""
    gross_pnl: float  # 총 손익
    total_fees: float  # 총 수수료
    net_pnl: float  # 순 손익
    total_wins: float  # 총 수익 금액
    total_losses: float  # 총 손실 금액
    avg_pnl: float  # 평균 손익
    avg_win: float  # 평균 수익
    avg_loss: float  # 평균 손실
    max_win: float  # 최대 수익
    max_loss: float  # 최대 손실


@dataclass
class TradeStats:
    """거래 통계."""
    total_trades: int  # 총 거래 수
    winning_trades: int  # 수익 거래 수
    losing_trades: int  # 손실 거래 수
    breakeven_trades: int  # 손익분기 거래 수
    win_rate: float  # 승률 (%)


@dataclass
class RiskMetrics:
    """리스크 메트릭."""
    profit_factor: Optional[float]  # 수익팩터
    sharpe_ratio: Optional[float]  # 샤프비율 (연환산)
    max_drawdown: float  # 최대 낙폭 (금액)
    max_drawdown_percent: float  # 최대 낙폭 (%)
    drawdown_start_date: Optional[str]  # 낙폭 시작일
    drawdown_end_date: Optional[str]  # 낙폭 종료일


@dataclass
class VolumeStats:
    """거래량 통계."""
    total_volume: float  # 총 거래량
    avg_trade_size: float  # 평균 거래 크기


@dataclass
class HoldingTimeStats:
    """보유 시간 통계."""
    avg_hours: float  # 평균 보유 시간 (시간)
    min_hours: float  # 최소 보유 시간
    max_hours: float  # 최대 보유 시간


@dataclass
class SideStats:
    """방향별 통계."""
    count: int  # 거래 수
    win_rate: float  # 승률 (%)
    net_pnl: float  # 순 손익


@dataclass
class TradingStatistics:
    """종합 트레이딩 통계."""
    user_id: str
    symbol: str  # 'ALL' for all symbols
    period_start: str
    period_end: str
    trade_stats: TradeStats
    pnl_stats: PnLStats
    risk_metrics: RiskMetrics
    volume_stats: VolumeStats
    holding_time_stats: HoldingTimeStats
    close_type_distribution: Dict[str, int]
    long_stats: SideStats
    short_stats: SideStats

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'user_id': self.user_id,
            'symbol': self.symbol,
            'period': {
                'start_date': self.period_start,
                'end_date': self.period_end,
            },
            'summary': asdict(self.trade_stats),
            'pnl': asdict(self.pnl_stats),
            'risk_metrics': asdict(self.risk_metrics),
            'volume': asdict(self.volume_stats),
            'holding_time': asdict(self.holding_time_stats),
            'close_types': self.close_type_distribution,
            'by_side': {
                'long': asdict(self.long_stats),
                'short': asdict(self.short_stats),
            }
        }


class TradingStatsService:
    """
    트레이딩 통계 계산 서비스.

    MDD, 샤프비율, 승률, 수익팩터 등 종합적인 거래 통계를 제공합니다.
    """

    # 리스크 무위험 이자율 (연간, 기본값 2%)
    DEFAULT_RISK_FREE_RATE = 0.02
    # 연간 거래일 수
    TRADING_DAYS_PER_YEAR = 365

    async def get_trading_statistics(
        self,
        okx_uid: str,
        symbol: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        initial_balance: float = 10000.0
    ) -> Optional[TradingStatistics]:
        """
        종합 트레이딩 통계 조회.

        Args:
            okx_uid: OKX 사용자 UID
            symbol: 거래 심볼 (None이면 전체)
            start_date: 시작 날짜
            end_date: 종료 날짜
            initial_balance: 초기 잔고 (MDD 계산용)

        Returns:
            Optional[TradingStatistics]: 종합 통계 (데이터 없으면 None)
        """
        try:
            async with get_transactional_session() as session:
                # 기본 통계 조회
                base_stats = await self._get_base_stats(
                    session, okx_uid, symbol, start_date, end_date
                )

                if not base_stats or base_stats['total_trades'] == 0:
                    logger.info(f"No trades found for user {okx_uid}")
                    return None

                # 방향별 통계
                long_stats = await self._get_side_stats(
                    session, okx_uid, symbol, start_date, end_date, 'long'
                )
                short_stats = await self._get_side_stats(
                    session, okx_uid, symbol, start_date, end_date, 'short'
                )

                # 청산 유형별 분포
                close_type_dist = await self._get_close_type_distribution(
                    session, okx_uid, symbol, start_date, end_date
                )

                # MDD 계산
                mdd_result = await self._calculate_mdd(
                    session, okx_uid, symbol, start_date, end_date, initial_balance
                )

                # 샤프비율 계산
                sharpe = await self._calculate_sharpe_ratio(
                    session, okx_uid, symbol, start_date, end_date
                )

                # 결과 구성
                trade_stats = TradeStats(
                    total_trades=base_stats['total_trades'],
                    winning_trades=base_stats['winning_trades'],
                    losing_trades=base_stats['losing_trades'],
                    breakeven_trades=base_stats['breakeven_trades'],
                    win_rate=base_stats['win_rate']
                )

                pnl_stats = PnLStats(
                    gross_pnl=base_stats['gross_pnl'],
                    total_fees=base_stats['total_fees'],
                    net_pnl=base_stats['net_pnl'],
                    total_wins=base_stats['total_wins'],
                    total_losses=base_stats['total_losses'],
                    avg_pnl=base_stats['avg_pnl'],
                    avg_win=base_stats['avg_win'],
                    avg_loss=base_stats['avg_loss'],
                    max_win=base_stats['max_win'],
                    max_loss=base_stats['max_loss']
                )

                risk_metrics = RiskMetrics(
                    profit_factor=base_stats['profit_factor'],
                    sharpe_ratio=sharpe,
                    max_drawdown=mdd_result['max_drawdown'],
                    max_drawdown_percent=mdd_result['max_drawdown_percent'],
                    drawdown_start_date=mdd_result['drawdown_start_date'],
                    drawdown_end_date=mdd_result['drawdown_end_date']
                )

                volume_stats = VolumeStats(
                    total_volume=base_stats['total_volume'],
                    avg_trade_size=base_stats['avg_trade_size']
                )

                holding_time_stats = HoldingTimeStats(
                    avg_hours=base_stats['avg_holding_hours'],
                    min_hours=base_stats['min_holding_hours'],
                    max_hours=base_stats['max_holding_hours']
                )

                return TradingStatistics(
                    user_id=okx_uid,
                    symbol=symbol or 'ALL',
                    period_start=str(base_stats['first_trade']),
                    period_end=str(base_stats['last_trade']),
                    trade_stats=trade_stats,
                    pnl_stats=pnl_stats,
                    risk_metrics=risk_metrics,
                    volume_stats=volume_stats,
                    holding_time_stats=holding_time_stats,
                    close_type_distribution=close_type_dist,
                    long_stats=long_stats,
                    short_stats=short_stats
                )

        except Exception as e:
            logger.error(f"Failed to get trading statistics: {e}", exc_info=True)
            return None

    async def _get_base_stats(
        self,
        session: AsyncSession,
        okx_uid: str,
        symbol: Optional[str],
        start_date: Optional[date],
        end_date: Optional[date]
    ) -> Optional[Dict[str, Any]]:
        """기본 통계 조회."""
        # 동적 WHERE 조건 구성
        conditions = ["okx_uid = :okx_uid"]
        params: Dict[str, Any] = {"okx_uid": okx_uid}

        if symbol:
            conditions.append("symbol = :symbol")
            params["symbol"] = symbol
        if start_date:
            conditions.append("exit_time >= :start_date")
            params["start_date"] = datetime.combine(start_date, datetime.min.time())
        if end_date:
            conditions.append("exit_time <= :end_date")
            params["end_date"] = datetime.combine(end_date, datetime.max.time())

        where_clause = " AND ".join(conditions)

        query = text(f"""
            SELECT
                COUNT(*) as total_trades,
                COUNT(*) FILTER (WHERE (realized_pnl - entry_fee - exit_fee) > 0) as winning_trades,
                COUNT(*) FILTER (WHERE (realized_pnl - entry_fee - exit_fee) < 0) as losing_trades,
                COUNT(*) FILTER (WHERE (realized_pnl - entry_fee - exit_fee) = 0) as breakeven_trades,

                ROUND(
                    COALESCE(
                        COUNT(*) FILTER (WHERE (realized_pnl - entry_fee - exit_fee) > 0)::NUMERIC
                        / NULLIF(COUNT(*), 0) * 100,
                        0
                    ), 2
                ) as win_rate,

                COALESCE(SUM(realized_pnl), 0) as gross_pnl,
                COALESCE(SUM(entry_fee + exit_fee), 0) as total_fees,
                COALESCE(SUM(realized_pnl - entry_fee - exit_fee), 0) as net_pnl,

                COALESCE(SUM(realized_pnl - entry_fee - exit_fee) FILTER (WHERE (realized_pnl - entry_fee - exit_fee) > 0), 0) as total_wins,
                ABS(COALESCE(SUM(realized_pnl - entry_fee - exit_fee) FILTER (WHERE (realized_pnl - entry_fee - exit_fee) < 0), 0)) as total_losses,

                COALESCE(AVG(realized_pnl - entry_fee - exit_fee), 0) as avg_pnl,
                COALESCE(AVG(realized_pnl - entry_fee - exit_fee) FILTER (WHERE (realized_pnl - entry_fee - exit_fee) > 0), 0) as avg_win,
                COALESCE(AVG(realized_pnl - entry_fee - exit_fee) FILTER (WHERE (realized_pnl - entry_fee - exit_fee) < 0), 0) as avg_loss,

                COALESCE(MAX(realized_pnl - entry_fee - exit_fee), 0) as max_win,
                COALESCE(MIN(realized_pnl - entry_fee - exit_fee), 0) as max_loss,

                ROUND(
                    NULLIF(
                        SUM(realized_pnl - entry_fee - exit_fee) FILTER (WHERE (realized_pnl - entry_fee - exit_fee) > 0),
                        0
                    ) /
                    NULLIF(
                        ABS(SUM(realized_pnl - entry_fee - exit_fee) FILTER (WHERE (realized_pnl - entry_fee - exit_fee) < 0)),
                        0
                    ),
                    4
                ) as profit_factor,

                COALESCE(SUM(entry_value), 0) as total_volume,
                COALESCE(AVG(entry_value), 0) as avg_trade_size,

                COALESCE(AVG(EXTRACT(EPOCH FROM (exit_time - entry_time)) / 3600.0), 0) as avg_holding_hours,
                COALESCE(MIN(EXTRACT(EPOCH FROM (exit_time - entry_time)) / 3600.0), 0) as min_holding_hours,
                COALESCE(MAX(EXTRACT(EPOCH FROM (exit_time - entry_time)) / 3600.0), 0) as max_holding_hours,

                MIN(exit_time) as first_trade,
                MAX(exit_time) as last_trade
            FROM hyperrsi_trades
            WHERE {where_clause}
        """)

        result = await session.execute(query, params)
        row = result.fetchone()

        if not row or row.total_trades == 0:
            return None

        return {
            'total_trades': row.total_trades,
            'winning_trades': row.winning_trades,
            'losing_trades': row.losing_trades,
            'breakeven_trades': row.breakeven_trades,
            'win_rate': float(row.win_rate),
            'gross_pnl': float(row.gross_pnl),
            'total_fees': float(row.total_fees),
            'net_pnl': float(row.net_pnl),
            'total_wins': float(row.total_wins),
            'total_losses': float(row.total_losses),
            'avg_pnl': float(row.avg_pnl),
            'avg_win': float(row.avg_win),
            'avg_loss': float(row.avg_loss),
            'max_win': float(row.max_win),
            'max_loss': float(row.max_loss),
            'profit_factor': float(row.profit_factor) if row.profit_factor else None,
            'total_volume': float(row.total_volume),
            'avg_trade_size': float(row.avg_trade_size),
            'avg_holding_hours': round(float(row.avg_holding_hours), 2),
            'min_holding_hours': round(float(row.min_holding_hours), 2),
            'max_holding_hours': round(float(row.max_holding_hours), 2),
            'first_trade': row.first_trade.date() if row.first_trade else None,
            'last_trade': row.last_trade.date() if row.last_trade else None,
        }

    async def _get_side_stats(
        self,
        session: AsyncSession,
        okx_uid: str,
        symbol: Optional[str],
        start_date: Optional[date],
        end_date: Optional[date],
        side: str
    ) -> SideStats:
        """방향별 통계 조회."""
        conditions = ["okx_uid = :okx_uid", "side = :side"]
        params: Dict[str, Any] = {"okx_uid": okx_uid, "side": side}

        if symbol:
            conditions.append("symbol = :symbol")
            params["symbol"] = symbol
        if start_date:
            conditions.append("exit_time >= :start_date")
            params["start_date"] = datetime.combine(start_date, datetime.min.time())
        if end_date:
            conditions.append("exit_time <= :end_date")
            params["end_date"] = datetime.combine(end_date, datetime.max.time())

        where_clause = " AND ".join(conditions)

        query = text(f"""
            SELECT
                COUNT(*) as count,
                ROUND(
                    COALESCE(
                        COUNT(*) FILTER (WHERE (realized_pnl - entry_fee - exit_fee) > 0)::NUMERIC
                        / NULLIF(COUNT(*), 0) * 100,
                        0
                    ), 2
                ) as win_rate,
                COALESCE(SUM(realized_pnl - entry_fee - exit_fee), 0) as net_pnl
            FROM hyperrsi_trades
            WHERE {where_clause}
        """)

        result = await session.execute(query, params)
        row = result.fetchone()

        return SideStats(
            count=row.count if row else 0,
            win_rate=float(row.win_rate) if row else 0.0,
            net_pnl=float(row.net_pnl) if row else 0.0
        )

    async def _get_close_type_distribution(
        self,
        session: AsyncSession,
        okx_uid: str,
        symbol: Optional[str],
        start_date: Optional[date],
        end_date: Optional[date]
    ) -> Dict[str, int]:
        """청산 유형별 분포 조회."""
        conditions = ["okx_uid = :okx_uid"]
        params: Dict[str, Any] = {"okx_uid": okx_uid}

        if symbol:
            conditions.append("symbol = :symbol")
            params["symbol"] = symbol
        if start_date:
            conditions.append("exit_time >= :start_date")
            params["start_date"] = datetime.combine(start_date, datetime.min.time())
        if end_date:
            conditions.append("exit_time <= :end_date")
            params["end_date"] = datetime.combine(end_date, datetime.max.time())

        where_clause = " AND ".join(conditions)

        query = text(f"""
            SELECT close_type, COUNT(*) as count
            FROM hyperrsi_trades
            WHERE {where_clause}
            GROUP BY close_type
        """)

        result = await session.execute(query, params)
        return {row.close_type: row.count for row in result.fetchall()}

    async def _calculate_mdd(
        self,
        session: AsyncSession,
        okx_uid: str,
        symbol: Optional[str],
        start_date: Optional[date],
        end_date: Optional[date],
        initial_balance: float
    ) -> Dict[str, Any]:
        """
        최대 낙폭 (MDD) 계산.

        일별 손익을 기반으로 MDD를 계산합니다.
        """
        conditions = ["okx_uid = :okx_uid"]
        params: Dict[str, Any] = {"okx_uid": okx_uid}

        if symbol:
            conditions.append("symbol = :symbol")
            params["symbol"] = symbol
        if start_date:
            conditions.append("exit_time >= :start_date")
            params["start_date"] = datetime.combine(start_date, datetime.min.time())
        if end_date:
            conditions.append("exit_time <= :end_date")
            params["end_date"] = datetime.combine(end_date, datetime.max.time())

        where_clause = " AND ".join(conditions)

        # 일별 손익 조회
        query = text(f"""
            SELECT
                DATE(exit_time AT TIME ZONE 'UTC') as trade_date,
                SUM(realized_pnl - entry_fee - exit_fee) as daily_pnl
            FROM hyperrsi_trades
            WHERE {where_clause}
            GROUP BY DATE(exit_time AT TIME ZONE 'UTC')
            ORDER BY trade_date
        """)

        result = await session.execute(query, params)
        daily_pnls = result.fetchall()

        if not daily_pnls:
            return {
                'max_drawdown': 0.0,
                'max_drawdown_percent': 0.0,
                'drawdown_start_date': None,
                'drawdown_end_date': None
            }

        # MDD 계산
        running_balance = initial_balance
        peak_balance = initial_balance
        max_drawdown = 0.0
        max_drawdown_percent = 0.0
        current_drawdown_start = None
        drawdown_start = None
        drawdown_end = None

        for row in daily_pnls:
            running_balance += float(row.daily_pnl)

            if running_balance > peak_balance:
                peak_balance = running_balance
                current_drawdown_start = None
            else:
                current_drawdown = peak_balance - running_balance

                if current_drawdown_start is None:
                    current_drawdown_start = row.trade_date

                if current_drawdown > max_drawdown:
                    max_drawdown = current_drawdown
                    max_drawdown_percent = (current_drawdown / peak_balance) * 100
                    drawdown_start = str(current_drawdown_start)
                    drawdown_end = str(row.trade_date)

        return {
            'max_drawdown': round(max_drawdown, 4),
            'max_drawdown_percent': round(max_drawdown_percent, 4),
            'drawdown_start_date': drawdown_start,
            'drawdown_end_date': drawdown_end
        }

    async def _calculate_sharpe_ratio(
        self,
        session: AsyncSession,
        okx_uid: str,
        symbol: Optional[str],
        start_date: Optional[date],
        end_date: Optional[date],
        risk_free_rate: float = DEFAULT_RISK_FREE_RATE
    ) -> Optional[float]:
        """
        샤프비율 계산 (연환산).

        일별 수익률의 평균과 표준편차를 사용하여 계산합니다.
        """
        conditions = ["okx_uid = :okx_uid"]
        params: Dict[str, Any] = {"okx_uid": okx_uid}

        if symbol:
            conditions.append("symbol = :symbol")
            params["symbol"] = symbol
        if start_date:
            conditions.append("exit_time >= :start_date")
            params["start_date"] = datetime.combine(start_date, datetime.min.time())
        if end_date:
            conditions.append("exit_time <= :end_date")
            params["end_date"] = datetime.combine(end_date, datetime.max.time())

        where_clause = " AND ".join(conditions)

        # 일별 수익률 통계
        query = text(f"""
            SELECT
                AVG(daily_return) as avg_return,
                STDDEV_SAMP(daily_return) as std_return
            FROM (
                SELECT
                    DATE(exit_time AT TIME ZONE 'UTC') as trade_date,
                    SUM(realized_pnl_percent) / 100.0 as daily_return
                FROM hyperrsi_trades
                WHERE {where_clause}
                GROUP BY DATE(exit_time AT TIME ZONE 'UTC')
            ) daily_returns
        """)

        result = await session.execute(query, params)
        row = result.fetchone()

        if not row or row.avg_return is None or row.std_return is None or row.std_return == 0:
            return None

        avg_return = float(row.avg_return)
        std_return = float(row.std_return)
        daily_risk_free = risk_free_rate / self.TRADING_DAYS_PER_YEAR

        # 연환산 샤프비율
        sharpe = ((avg_return - daily_risk_free) / std_return) * math.sqrt(self.TRADING_DAYS_PER_YEAR)
        return round(sharpe, 4)

    async def get_daily_pnl_series(
        self,
        okx_uid: str,
        symbol: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> List[Dict[str, Any]]:
        """
        일별 손익 시계열 조회.

        차트 데이터 등에 활용됩니다.
        """
        try:
            async with get_transactional_session() as session:
                conditions = ["okx_uid = :okx_uid"]
                params: Dict[str, Any] = {"okx_uid": okx_uid}

                if symbol:
                    conditions.append("symbol = :symbol")
                    params["symbol"] = symbol
                if start_date:
                    conditions.append("exit_time >= :start_date")
                    params["start_date"] = datetime.combine(start_date, datetime.min.time())
                if end_date:
                    conditions.append("exit_time <= :end_date")
                    params["end_date"] = datetime.combine(end_date, datetime.max.time())

                where_clause = " AND ".join(conditions)

                query = text(f"""
                    SELECT
                        DATE(exit_time AT TIME ZONE 'UTC') as trade_date,
                        COUNT(*) as trades,
                        SUM(realized_pnl - entry_fee - exit_fee) as net_pnl,
                        SUM(SUM(realized_pnl - entry_fee - exit_fee)) OVER (ORDER BY DATE(exit_time AT TIME ZONE 'UTC')) as cumulative_pnl
                    FROM hyperrsi_trades
                    WHERE {where_clause}
                    GROUP BY DATE(exit_time AT TIME ZONE 'UTC')
                    ORDER BY trade_date
                """)

                result = await session.execute(query, params)
                return [
                    {
                        'date': str(row.trade_date),
                        'trades': row.trades,
                        'net_pnl': float(row.net_pnl),
                        'cumulative_pnl': float(row.cumulative_pnl)
                    }
                    for row in result.fetchall()
                ]

        except Exception as e:
            logger.error(f"Failed to get daily PnL series: {e}", exc_info=True)
            return []

    async def get_symbol_breakdown(
        self,
        okx_uid: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> List[Dict[str, Any]]:
        """
        심볼별 통계 조회.

        각 심볼별 수익/손실 현황을 제공합니다.
        """
        try:
            async with get_transactional_session() as session:
                conditions = ["okx_uid = :okx_uid"]
                params: Dict[str, Any] = {"okx_uid": okx_uid}

                if start_date:
                    conditions.append("exit_time >= :start_date")
                    params["start_date"] = datetime.combine(start_date, datetime.min.time())
                if end_date:
                    conditions.append("exit_time <= :end_date")
                    params["end_date"] = datetime.combine(end_date, datetime.max.time())

                where_clause = " AND ".join(conditions)

                query = text(f"""
                    SELECT
                        symbol,
                        COUNT(*) as total_trades,
                        COUNT(*) FILTER (WHERE (realized_pnl - entry_fee - exit_fee) > 0) as winning_trades,
                        ROUND(
                            COALESCE(
                                COUNT(*) FILTER (WHERE (realized_pnl - entry_fee - exit_fee) > 0)::NUMERIC
                                / NULLIF(COUNT(*), 0) * 100,
                                0
                            ), 2
                        ) as win_rate,
                        SUM(realized_pnl - entry_fee - exit_fee) as net_pnl,
                        SUM(entry_value) as total_volume
                    FROM hyperrsi_trades
                    WHERE {where_clause}
                    GROUP BY symbol
                    ORDER BY net_pnl DESC
                """)

                result = await session.execute(query, params)
                return [
                    {
                        'symbol': row.symbol,
                        'total_trades': row.total_trades,
                        'winning_trades': row.winning_trades,
                        'win_rate': float(row.win_rate),
                        'net_pnl': float(row.net_pnl),
                        'total_volume': float(row.total_volume)
                    }
                    for row in result.fetchall()
                ]

        except Exception as e:
            logger.error(f"Failed to get symbol breakdown: {e}", exc_info=True)
            return []


# Singleton instance
_trading_stats_service: Optional[TradingStatsService] = None


def get_trading_stats_service() -> TradingStatsService:
    """Get singleton TradingStatsService instance."""
    global _trading_stats_service
    if _trading_stats_service is None:
        _trading_stats_service = TradingStatsService()
    return _trading_stats_service
