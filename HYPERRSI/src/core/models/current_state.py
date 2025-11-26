"""
HYPERRSI Current Bot State Model.

현재 활성 봇 상태 관리 - PostgreSQL이 SSOT (Source of Truth), Redis는 캐시.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Index, String, DateTime, Integer, Boolean, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from HYPERRSI.src.core.database_dir.base import Base


class HyperrsiCurrent(Base):
    """
    현재 활성 봇 상태 테이블.

    PostgreSQL이 SSOT (Source of Truth), Redis는 성능을 위한 캐시로 사용합니다.
    - 사용자+심볼당 최대 1개 레코드 (UNIQUE)
    - 봇 시작 시 INSERT OR UPDATE
    - 봇 종료 시 is_running=False로 업데이트

    Attributes:
        id: 자동 증가 Primary Key
        okx_uid: OKX 사용자 UID
        telegram_id: 텔레그램 사용자 ID
        symbol: 거래 심볼
        timeframe: 타임프레임
        is_running: 봇 실행 중 여부
        session_id: 현재 세션 ID (FK to hyperrsi_sessions)
        params_settings: 현재 트레이딩 파라미터
        dual_side_settings: 현재 양방향 매매 설정
        position_long: 롱 포지션 상태 (JSON)
        position_short: 숏 포지션 상태 (JSON)
        hedge_position: 헷지 포지션 상태 (양방향 매매)
        last_execution_at: 마지막 실행 시각
        last_signal: 마지막 시그널
        trades_today: 오늘 거래 수
        pnl_today: 오늘 손익
        created_at: 레코드 생성 시각
        updated_at: 레코드 수정 시각
    """

    __tablename__ = "hyperrsi_current"

    __table_args__ = (
        UniqueConstraint('okx_uid', 'symbol', name='uq_current_okx_uid_symbol'),
        Index('idx_current_okx_uid', 'okx_uid'),
        Index('idx_current_is_running', 'is_running', postgresql_where="is_running = TRUE"),
        Index('idx_current_session_id', 'session_id'),
    )

    # Primary Key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # User identification
    okx_uid: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
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

    # Bot state
    is_running: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="봇 실행 중 여부"
    )

    session_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("hyperrsi_sessions.id", ondelete="SET NULL"),
        nullable=True,
        comment="현재 세션 ID"
    )

    # Current settings
    params_settings: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="현재 트레이딩 파라미터"
    )

    dual_side_settings: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="현재 양방향 매매 설정"
    )

    # Position state (flexible JSON structure)
    position_long: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="""롱 포지션 상태
        {
            "entry_price": 45000.00,
            "avg_price": 44800.00,
            "size": 0.1,
            "contracts": 1,
            "leverage": 10,
            "dca_count": 2,
            "tp_state": 0,
            "tp_prices": [45500, 46000, 47000],
            "sl_price": 43000,
            "break_even_active": false,
            "trailing_active": false,
            "trailing_stop_price": null,
            "unrealized_pnl": 50.25,
            "last_update": "2025-11-26T10:00:00Z"
        }
        """
    )

    position_short: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="숏 포지션 상태 (position_long과 동일 구조)"
    )

    # Hedge position (dual-side trading)
    hedge_position: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="""헷지 포지션 상태 (양방향 매매)
        {
            "side": "short",
            "entry_price": 45100.00,
            "size": 0.05,
            "dca_index": 3,
            "dual_side_count": 1,
            "tp_price": 44500,
            "sl_price": 45500
        }
        """
    )

    # Last execution info
    last_execution_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="마지막 실행 시각"
    )

    last_signal: Mapped[Optional[str]] = mapped_column(
        String(30),
        nullable=True,
        comment="마지막 시그널 (long_entry, short_exit, dca_long 등)"
    )

    # Daily statistics
    trades_today: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="오늘 거래 수"
    )

    pnl_today: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        default=Decimal('0'),
        comment="오늘 손익 (USDT)"
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
            f"<HyperrsiCurrent("
            f"id={self.id}, "
            f"okx_uid={self.okx_uid}, "
            f"symbol={self.symbol}, "
            f"is_running={self.is_running}"
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
            "is_running": self.is_running,
            "session_id": self.session_id,
            "params_settings": self.params_settings,
            "dual_side_settings": self.dual_side_settings,
            "position_long": self.position_long,
            "position_short": self.position_short,
            "hedge_position": self.hedge_position,
            "last_execution_at": self.last_execution_at.isoformat() if self.last_execution_at else None,
            "last_signal": self.last_signal,
            "trades_today": self.trades_today,
            "pnl_today": float(self.pnl_today) if self.pnl_today else 0.0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def to_redis_cache(self) -> dict:
        """
        Convert to Redis cache format.
        Maintains backward compatibility with existing Redis key patterns.
        """
        return {
            "is_running": "1" if self.is_running else "0",
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "session_id": str(self.session_id) if self.session_id else "",
            "last_signal": self.last_signal or "",
            "last_execution_at": self.last_execution_at.isoformat() if self.last_execution_at else "",
        }

    @property
    def has_long_position(self) -> bool:
        """Check if there's an active long position."""
        if not self.position_long:
            return False
        return float(self.position_long.get('size', 0)) > 0

    @property
    def has_short_position(self) -> bool:
        """Check if there's an active short position."""
        if not self.position_short:
            return False
        return float(self.position_short.get('size', 0)) > 0

    @property
    def has_hedge_position(self) -> bool:
        """Check if there's an active hedge position."""
        if not self.hedge_position:
            return False
        return float(self.hedge_position.get('size', 0)) > 0

    @property
    def active_side(self) -> Optional[str]:
        """Get the active position side (long/short/both/none)."""
        has_long = self.has_long_position
        has_short = self.has_short_position

        if has_long and has_short:
            return 'both'
        elif has_long:
            return 'long'
        elif has_short:
            return 'short'
        return None

    def get_position(self, side: str) -> Optional[dict]:
        """Get position data by side."""
        if side == 'long':
            return self.position_long
        elif side == 'short':
            return self.position_short
        elif side == 'hedge':
            return self.hedge_position
        return None

    def get_tp_state(self, side: str) -> int:
        """Get TP state for a position side (0=not triggered, 1=TP1, 2=TP2, 3=TP3)."""
        position = self.get_position(side)
        if not position:
            return 0
        return position.get('tp_state', 0)

    def get_dca_count(self, side: str) -> int:
        """Get DCA count for a position side."""
        position = self.get_position(side)
        if not position:
            return 0
        return position.get('dca_count', 0)
