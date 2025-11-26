"""
HYPERRSI Trade Record Model.

거래 기록 모델 - 종료된 모든 거래의 상세 정보를 저장하여 통계 분석에 사용합니다.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Index, String, DateTime, Integer, Boolean, Numeric, CheckConstraint, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from HYPERRSI.src.core.database_dir.base import Base


class CloseType:
    """거래 종료 유형 상수."""
    MANUAL = 'manual'          # 수동 청산
    TP1 = 'tp1'                # Take Profit 1
    TP2 = 'tp2'                # Take Profit 2
    TP3 = 'tp3'                # Take Profit 3
    SL = 'sl'                  # Stop Loss
    BREAK_EVEN = 'break_even'  # 손익분기점 청산
    TRAILING_STOP = 'trailing_stop'  # 트레일링 스탑
    LIQUIDATION = 'liquidation'      # 청산
    HEDGE_TP = 'hedge_tp'      # 헤지 포지션 TP
    HEDGE_SL = 'hedge_sl'      # 헤지 포지션 SL
    SIGNAL = 'signal'          # 시그널 기반 청산
    FORCE_CLOSE = 'force_close'  # 강제 청산


class HyperrsiTrade(Base):
    """
    거래 기록 테이블.

    종료된 모든 거래의 상세 정보를 기록합니다.
    통계 계산 (승률, 수익팩터, MDD, 샤프비율 등)의 기초 데이터로 사용됩니다.

    Attributes:
        id: 자동 증가 Primary Key
        okx_uid: OKX 사용자 UID
        telegram_id: 텔레그램 사용자 ID
        symbol: 거래 심볼 (예: BTC-USDT-SWAP)
        side: 거래 방향 (long, short)
        is_hedge: 헤지 포지션 여부
        entry_time: 진입 시간
        entry_price: 진입 가격
        entry_size: 진입 수량
        entry_value: 진입 가치 (price * size)
        exit_time: 청산 시간
        exit_price: 청산 가격
        exit_size: 청산 수량
        exit_value: 청산 가치
        close_type: 청산 유형
        leverage: 레버리지
        dca_count: DCA 횟수
        avg_entry_price: 평균 진입 가격
        realized_pnl: 실현 손익
        realized_pnl_percent: 실현 손익률
        entry_fee: 진입 수수료
        exit_fee: 청산 수수료
        session_id: 세션 ID (외래키)
        entry_order_id: 진입 주문 ID
        exit_order_id: 청산 주문 ID
        extra_data: 추가 데이터 (JSON)
        created_at: 레코드 생성 시각
    """

    __tablename__ = "hyperrsi_trades"

    __table_args__ = (
        Index('idx_trades_okx_uid', 'okx_uid'),
        Index('idx_trades_okx_uid_symbol', 'okx_uid', 'symbol'),
        Index('idx_trades_okx_uid_exit_time', 'okx_uid', 'exit_time'),
        Index('idx_trades_session', 'session_id'),
        Index('idx_trades_close_type', 'close_type'),
        CheckConstraint("side IN ('long', 'short')", name='chk_trades_side'),
        CheckConstraint(
            "close_type IN ('manual', 'tp1', 'tp2', 'tp3', 'sl', 'break_even', "
            "'trailing_stop', 'liquidation', 'hedge_tp', 'hedge_sl', 'signal', 'force_close')",
            name='chk_trades_close_type'
        ),
    )

    # Primary Key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # User identification
    okx_uid: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="OKX 사용자 UID"
    )

    telegram_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="텔레그램 사용자 ID"
    )

    # Trading target
    symbol: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="거래 심볼 (예: BTC-USDT-SWAP)"
    )

    # Trade direction
    side: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="거래 방향 (long, short)"
    )

    is_hedge: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="헤지 포지션 여부"
    )

    # Entry information
    entry_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="진입 시간 (UTC)"
    )

    entry_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        comment="진입 가격"
    )

    entry_size: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        comment="진입 수량 (계약 수 또는 기준 통화)"
    )

    entry_value: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        comment="진입 가치 (entry_price * entry_size)"
    )

    # Exit information
    exit_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="청산 시간 (UTC)"
    )

    exit_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        comment="청산 가격"
    )

    exit_size: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        comment="청산 수량"
    )

    exit_value: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        comment="청산 가치 (exit_price * exit_size)"
    )

    # Close type
    close_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="청산 유형 (manual, tp1, tp2, tp3, sl, break_even, trailing_stop, etc.)"
    )

    # Position management info
    leverage: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="레버리지"
    )

    dca_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="DCA 횟수"
    )

    avg_entry_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 8),
        nullable=True,
        comment="가중 평균 진입 가격 (DCA 사용 시)"
    )

    # PnL information
    realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        comment="실현 손익 (USDT)"
    )

    realized_pnl_percent: Mapped[Decimal] = mapped_column(
        Numeric(10, 4),
        nullable=False,
        comment="실현 손익률 (%)"
    )

    # Fee information
    entry_fee: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        default=Decimal('0'),
        comment="진입 수수료"
    )

    exit_fee: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        default=Decimal('0'),
        comment="청산 수수료"
    )

    # Session reference
    session_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey('hyperrsi_sessions.id', ondelete='SET NULL'),
        nullable=True,
        comment="세션 ID"
    )

    # Order IDs
    entry_order_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="진입 주문 ID"
    )

    exit_order_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="청산 주문 ID"
    )

    # Additional data
    extra_data: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="추가 메타데이터"
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        comment="레코드 생성 시각"
    )

    def __repr__(self) -> str:
        return (
            f"<HyperrsiTrade("
            f"id={self.id}, "
            f"okx_uid={self.okx_uid}, "
            f"symbol={self.symbol}, "
            f"side={self.side}, "
            f"pnl={self.realized_pnl}"
            f")>"
        )

    @property
    def total_fee(self) -> Decimal:
        """총 수수료."""
        return self.entry_fee + self.exit_fee

    @property
    def net_pnl(self) -> Decimal:
        """순 손익 (수수료 차감 후)."""
        return self.realized_pnl - self.total_fee

    @property
    def holding_seconds(self) -> int:
        """보유 시간 (초)."""
        return int((self.exit_time - self.entry_time).total_seconds())

    @property
    def holding_hours(self) -> float:
        """보유 시간 (시간)."""
        return self.holding_seconds / 3600.0

    @property
    def trade_date(self) -> datetime:
        """거래일 (UTC 기준 청산 날짜)."""
        return self.exit_time.date()

    @property
    def is_winner(self) -> bool:
        """수익 거래 여부."""
        return self.net_pnl > 0

    @property
    def is_loser(self) -> bool:
        """손실 거래 여부."""
        return self.net_pnl < 0

    def to_dict(self) -> dict:
        """Convert model to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "okx_uid": self.okx_uid,
            "telegram_id": self.telegram_id,
            "symbol": self.symbol,
            "side": self.side,
            "is_hedge": self.is_hedge,
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "entry_price": float(self.entry_price),
            "entry_size": float(self.entry_size),
            "entry_value": float(self.entry_value),
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "exit_price": float(self.exit_price),
            "exit_size": float(self.exit_size),
            "exit_value": float(self.exit_value),
            "close_type": self.close_type,
            "leverage": self.leverage,
            "dca_count": self.dca_count,
            "avg_entry_price": float(self.avg_entry_price) if self.avg_entry_price else None,
            "realized_pnl": float(self.realized_pnl),
            "realized_pnl_percent": float(self.realized_pnl_percent),
            "entry_fee": float(self.entry_fee),
            "exit_fee": float(self.exit_fee),
            "total_fee": float(self.total_fee),
            "net_pnl": float(self.net_pnl),
            "holding_seconds": self.holding_seconds,
            "holding_hours": round(self.holding_hours, 2),
            "session_id": self.session_id,
            "entry_order_id": self.entry_order_id,
            "exit_order_id": self.exit_order_id,
            "extra_data": self.extra_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class HyperrsiDailyStats(Base):
    """
    일별 사전 집계 통계 테이블.

    대량 데이터셋의 빠른 쿼리를 위해 일별로 미리 계산된 통계입니다.
    선택적 기능으로, 거래량이 많을 때 성능 최적화에 사용됩니다.

    Attributes:
        id: 자동 증가 Primary Key
        okx_uid: OKX 사용자 UID
        symbol: 거래 심볼 (NULL이면 전체 종목 집계)
        stat_date: 통계 기준일
        total_trades: 총 거래 수
        winning_trades: 수익 거래 수
        losing_trades: 손실 거래 수
        gross_pnl: 총 손익
        total_fees: 총 수수료
        net_pnl: 순 손익
        total_win_amount: 총 수익 금액
        total_loss_amount: 총 손실 금액
        max_win: 최대 수익
        max_loss: 최대 손실
        total_volume: 총 거래량
        avg_holding_time: 평균 보유 시간 (초)
        close_type_counts: 청산 유형별 카운트 (JSON)
        starting_balance: 시작 잔고
        ending_balance: 종료 잔고
        peak_balance: 최대 잔고
        daily_drawdown: 일일 하락폭
        daily_drawdown_percent: 일일 하락률
        created_at: 레코드 생성 시각
        updated_at: 레코드 수정 시각
    """

    __tablename__ = "hyperrsi_daily_stats"

    __table_args__ = (
        Index('idx_daily_stats_okx_uid', 'okx_uid'),
        Index('idx_daily_stats_okx_uid_date', 'okx_uid', 'stat_date'),
        Index('idx_daily_stats_okx_uid_symbol_date', 'okx_uid', 'symbol', 'stat_date'),
    )

    # Primary Key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Dimensions
    okx_uid: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="OKX 사용자 UID"
    )

    symbol: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="거래 심볼 (NULL이면 전체 종목 집계)"
    )

    stat_date: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        comment="통계 기준일"
    )

    # Trade counts
    total_trades: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="총 거래 수"
    )

    winning_trades: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="수익 거래 수"
    )

    losing_trades: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="손실 거래 수"
    )

    # PnL metrics
    gross_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        default=Decimal('0'),
        comment="총 손익"
    )

    total_fees: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        default=Decimal('0'),
        comment="총 수수료"
    )

    net_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        default=Decimal('0'),
        comment="순 손익"
    )

    # Win/Loss breakdowns
    total_win_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        default=Decimal('0'),
        comment="총 수익 금액"
    )

    total_loss_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        default=Decimal('0'),
        comment="총 손실 금액 (절대값)"
    )

    max_win: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        default=Decimal('0'),
        comment="최대 수익"
    )

    max_loss: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        default=Decimal('0'),
        comment="최대 손실"
    )

    # Volume
    total_volume: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        default=Decimal('0'),
        comment="총 거래량 (entry_value 합계)"
    )

    # Holding time
    avg_holding_time: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="평균 보유 시간 (초)"
    )

    min_holding_time: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="최소 보유 시간 (초)"
    )

    max_holding_time: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="최대 보유 시간 (초)"
    )

    # Close type breakdown
    close_type_counts: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="청산 유형별 카운트"
    )

    # Balance tracking
    starting_balance: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 8),
        nullable=True,
        comment="시작 잔고"
    )

    ending_balance: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 8),
        nullable=True,
        comment="종료 잔고"
    )

    peak_balance: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 8),
        nullable=True,
        comment="최대 잔고"
    )

    # Daily drawdown
    daily_drawdown: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        default=Decimal('0'),
        comment="일일 하락폭"
    )

    daily_drawdown_percent: Mapped[Decimal] = mapped_column(
        Numeric(10, 4),
        nullable=False,
        default=Decimal('0'),
        comment="일일 하락률 (%)"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        comment="레코드 생성 시각"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        comment="레코드 수정 시각"
    )

    def __repr__(self) -> str:
        return (
            f"<HyperrsiDailyStats("
            f"okx_uid={self.okx_uid}, "
            f"symbol={self.symbol}, "
            f"date={self.stat_date}, "
            f"trades={self.total_trades}"
            f")>"
        )

    @property
    def win_rate(self) -> float:
        """승률 (%)."""
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100

    @property
    def profit_factor(self) -> Optional[float]:
        """수익팩터."""
        if self.total_loss_amount == 0:
            return None
        return float(self.total_win_amount / self.total_loss_amount)

    def to_dict(self) -> dict:
        """Convert model to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "okx_uid": self.okx_uid,
            "symbol": self.symbol,
            "stat_date": self.stat_date.isoformat() if self.stat_date else None,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": round(self.win_rate, 2),
            "gross_pnl": float(self.gross_pnl),
            "total_fees": float(self.total_fees),
            "net_pnl": float(self.net_pnl),
            "total_win_amount": float(self.total_win_amount),
            "total_loss_amount": float(self.total_loss_amount),
            "max_win": float(self.max_win),
            "max_loss": float(self.max_loss),
            "profit_factor": self.profit_factor,
            "total_volume": float(self.total_volume),
            "avg_holding_time": self.avg_holding_time,
            "close_type_counts": self.close_type_counts,
            "daily_drawdown": float(self.daily_drawdown),
            "daily_drawdown_percent": float(self.daily_drawdown_percent),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
