"""
HYPERRSI Trading Session Model.

트레이딩 세션 라이프사이클 관리 - 봇 시작/종료 단위로 세션을 기록합니다.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Index, String, DateTime, Integer, Text, Numeric, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from HYPERRSI.src.core.database_dir.base import Base


class HyperrsiSession(Base):
    """
    트레이딩 세션 테이블.

    봇 시작/종료 단위로 세션을 관리합니다.
    - 봇이 시작될 때 레코드 생성 (status='running')
    - 봇이 종료될 때 ended_at, final_settings, 통계 업데이트 (status='stopped')

    Attributes:
        id: 자동 증가 Primary Key
        okx_uid: OKX 사용자 UID
        telegram_id: 텔레그램 사용자 ID
        symbol: 거래 심볼 (예: BTC-USDT-SWAP)
        timeframe: 타임프레임 (예: 1m, 5m, 15m)
        status: 세션 상태 (running, stopped, error)
        started_at: 세션 시작 시각 (UTC)
        ended_at: 세션 종료 시각 (UTC)
        params_settings: 트레이딩 파라미터 설정 (시작 시점 스냅샷)
        dual_side_settings: 양방향 매매 설정 (시작 시점 스냅샷)
        final_settings: 세션 종료 시 최종 설정값
        end_reason: 종료 사유 (manual, error, system)
        error_message: 에러 메시지 (에러 종료 시)
        total_trades: 총 거래 수
        winning_trades: 수익 거래 수
        total_pnl: 총 손익 (USDT)
        created_at: 레코드 생성 시각
        updated_at: 레코드 수정 시각
    """

    __tablename__ = "hyperrsi_sessions"

    __table_args__ = (
        Index('idx_sessions_okx_uid', 'okx_uid'),
        Index('idx_sessions_status', 'status', postgresql_where="status = 'running'"),
        Index('idx_sessions_started_at', 'started_at'),
        Index('idx_sessions_okx_uid_symbol', 'okx_uid', 'symbol'),
        Index('idx_sessions_okx_uid_status', 'okx_uid', 'status'),
        CheckConstraint("status IN ('running', 'stopped', 'error')", name='chk_sessions_status'),
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

    timeframe: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="타임프레임 (예: 1m, 5m, 15m)"
    )

    # Session state
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default='running',
        comment="세션 상태 (running, stopped, error)"
    )

    # Time information (UTC)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        comment="세션 시작 시각 (UTC)"
    )

    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="세션 종료 시각 (UTC)"
    )

    # Settings snapshot at session start
    params_settings: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="트레이딩 파라미터 설정 (시작 시점 스냅샷)"
    )

    dual_side_settings: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="양방향 매매 설정 (시작 시점 스냅샷)"
    )

    # Final settings at session end
    final_settings: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="세션 종료 시 최종 설정값"
    )

    # End reason
    end_reason: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="종료 사유 (manual, error, system)"
    )

    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="에러 메시지 (에러 종료 시)"
    )

    # Session statistics
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

    total_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        default=Decimal('0'),
        comment="총 손익 (USDT)"
    )

    # Metadata
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
            f"<HyperrsiSession("
            f"id={self.id}, "
            f"okx_uid={self.okx_uid}, "
            f"symbol={self.symbol}, "
            f"status={self.status}, "
            f"started_at={self.started_at}"
            f")>"
        )

    def to_dict(self) -> dict:
        """Convert model to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "okx_uid": self.okx_uid,
            "telegram_id": self.telegram_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "params_settings": self.params_settings,
            "dual_side_settings": self.dual_side_settings,
            "final_settings": self.final_settings,
            "end_reason": self.end_reason,
            "error_message": self.error_message,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "total_pnl": float(self.total_pnl) if self.total_pnl else 0.0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @property
    def is_running(self) -> bool:
        """Check if session is currently running."""
        return self.status == 'running'

    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate session duration in seconds."""
        if not self.started_at:
            return None
        end_time = self.ended_at or datetime.utcnow()
        return (end_time - self.started_at).total_seconds()

    @property
    def win_rate(self) -> Optional[float]:
        """Calculate win rate percentage."""
        if self.total_trades == 0:
            return None
        return (self.winning_trades / self.total_trades) * 100
