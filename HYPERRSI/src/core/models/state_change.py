"""
HYPERRSI State Change Audit Log Model.

모든 상태 변경을 기록하는 감사 로그 테이블 (월별 파티셔닝, 1년 보존).
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Index, String, DateTime, Integer, Numeric, BigInteger
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from HYPERRSI.src.core.database_dir.base import Base


class HyperrsiStateChange(Base):
    """
    상태 변경 감사 로그 테이블.

    모든 상태 변경을 기록하여 감사 추적을 가능하게 합니다.
    - 월별 파티셔닝으로 1년 보존
    - 비동기 배치 쓰기로 성능 최적화

    Change Types:
        Session related:
            - session_started: 트레이딩 세션 시작
            - session_stopped: 트레이딩 세션 종료
            - session_error: 세션 에러 발생

        Position related:
            - position_opened: 포지션 진입
            - position_closed: 포지션 청산
            - dca_executed: DCA 추가 진입
            - position_partial_close: 부분 청산

        TP/SL related:
            - tp1_hit, tp2_hit, tp3_hit: TP 발동
            - sl_hit: SL 발동
            - break_even_activated: 브레이크이븐 활성화
            - trailing_activated: 트레일링스탑 활성화
            - trailing_updated: 트레일링스탑 가격 업데이트

        Hedge related:
            - hedge_opened: 헷지 포지션 진입
            - hedge_closed: 헷지 포지션 청산
            - hedge_tp_hit: 헷지 TP 발동
            - hedge_sl_hit: 헷지 SL 발동

        Settings related:
            - settings_updated: 일반 설정 변경
            - dual_side_updated: 양방향 설정 변경
            - leverage_changed: 레버리지 변경

        Order related:
            - order_placed: 주문 생성
            - order_filled: 주문 체결
            - order_cancelled: 주문 취소

    Triggered By:
        - user: 사용자 직접 조작 (텔레그램 봇)
        - celery: Celery 태스크
        - websocket: position_monitor WebSocket
        - exchange: 거래소 이벤트
        - system: 내부 시스템

    Attributes:
        id: 자동 증가 Primary Key (BIGSERIAL)
        change_time: 변경 발생 시각 (파티션 키)
        okx_uid: OKX 사용자 UID
        session_id: 세션 ID (nullable)
        symbol: 거래 심볼
        change_type: 변경 유형
        previous_state: 변경 전 상태 (JSON)
        new_state: 변경 후 상태 (JSON)
        price_at_change: 변경 시점 가격
        pnl_at_change: 변경 시점 손익
        pnl_percent: 손익률 (%)
        triggered_by: 트리거 주체
        trigger_source: 트리거 소스 상세
        extra_data: 추가 메타데이터 (JSON)
    """

    __tablename__ = "hyperrsi_state_changes"

    __table_args__ = (
        Index('idx_state_changes_okx_uid_time', 'okx_uid', 'change_time'),
        Index('idx_state_changes_session', 'session_id', 'change_time'),
        Index('idx_state_changes_type', 'change_type', 'change_time'),
        Index('idx_state_changes_symbol', 'symbol', 'change_time'),
        # Composite primary key for partitioning
        {'postgresql_partition_by': 'RANGE (change_time)'}
    )

    # Primary Key (includes partition key)
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True
    )

    change_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        nullable=False,
        default=datetime.utcnow,
        comment="변경 발생 시각 (UTC, 파티션 키)"
    )

    # Context
    okx_uid: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="OKX 사용자 UID"
    )

    session_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="세션 ID"
    )

    symbol: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="거래 심볼"
    )

    # Change type
    change_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="변경 유형"
    )

    # Change content (before/after state)
    previous_state: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="변경 전 상태"
    )

    new_state: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="변경 후 상태"
    )

    # Price/PnL info
    price_at_change: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 8),
        nullable=True,
        comment="변경 시점 가격"
    )

    pnl_at_change: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 8),
        nullable=True,
        comment="변경 시점 손익 (USDT)"
    )

    pnl_percent: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 4),
        nullable=True,
        comment="손익률 (%)"
    )

    # Trigger info
    triggered_by: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default='system',
        comment="트리거 주체 (user, celery, websocket, exchange, system)"
    )

    trigger_source: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="트리거 소스 상세 (예: telegram_bot, trading_tasks.py)"
    )

    # Additional data
    extra_data: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        default=dict,
        comment="추가 메타데이터"
    )

    def __repr__(self) -> str:
        return (
            f"<HyperrsiStateChange("
            f"id={self.id}, "
            f"okx_uid={self.okx_uid}, "
            f"symbol={self.symbol}, "
            f"change_type={self.change_type}, "
            f"change_time={self.change_time}"
            f")>"
        )

    def to_dict(self) -> dict:
        """Convert model to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "change_time": self.change_time.isoformat() if self.change_time else None,
            "okx_uid": self.okx_uid,
            "session_id": self.session_id,
            "symbol": self.symbol,
            "change_type": self.change_type,
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            "price_at_change": float(self.price_at_change) if self.price_at_change else None,
            "pnl_at_change": float(self.pnl_at_change) if self.pnl_at_change else None,
            "pnl_percent": float(self.pnl_percent) if self.pnl_percent else None,
            "triggered_by": self.triggered_by,
            "trigger_source": self.trigger_source,
            "extra_data": self.extra_data,
        }

    @classmethod
    def create_change(
        cls,
        okx_uid: str,
        symbol: str,
        change_type: str,
        session_id: Optional[int] = None,
        previous_state: Optional[dict] = None,
        new_state: Optional[dict] = None,
        price: Optional[float] = None,
        pnl: Optional[float] = None,
        pnl_percent: Optional[float] = None,
        triggered_by: str = 'system',
        trigger_source: Optional[str] = None,
        extra_data: Optional[dict] = None
    ) -> 'HyperrsiStateChange':
        """Factory method to create a state change record."""
        return cls(
            okx_uid=okx_uid,
            symbol=symbol,
            change_type=change_type,
            session_id=session_id,
            previous_state=previous_state,
            new_state=new_state,
            price_at_change=Decimal(str(price)) if price else None,
            pnl_at_change=Decimal(str(pnl)) if pnl else None,
            pnl_percent=Decimal(str(pnl_percent)) if pnl_percent else None,
            triggered_by=triggered_by,
            trigger_source=trigger_source,
            extra_data=extra_data or {}
        )


# Change type constants for type safety
class ChangeType:
    """Constants for change types."""

    # Session related
    SESSION_STARTED = 'session_started'
    SESSION_STOPPED = 'session_stopped'
    SESSION_ERROR = 'session_error'

    # Position related
    POSITION_OPENED = 'position_opened'
    POSITION_CLOSED = 'position_closed'
    DCA_EXECUTED = 'dca_executed'
    POSITION_PARTIAL_CLOSE = 'position_partial_close'

    # TP/SL related
    TP1_HIT = 'tp1_hit'
    TP2_HIT = 'tp2_hit'
    TP3_HIT = 'tp3_hit'
    SL_HIT = 'sl_hit'
    BREAK_EVEN_ACTIVATED = 'break_even_activated'
    TRAILING_ACTIVATED = 'trailing_activated'
    TRAILING_UPDATED = 'trailing_updated'

    # Hedge related
    HEDGE_OPENED = 'hedge_opened'
    HEDGE_CLOSED = 'hedge_closed'
    HEDGE_TP_HIT = 'hedge_tp_hit'
    HEDGE_SL_HIT = 'hedge_sl_hit'

    # Settings related
    SETTINGS_UPDATED = 'settings_updated'
    DUAL_SIDE_UPDATED = 'dual_side_updated'
    LEVERAGE_CHANGED = 'leverage_changed'

    # Order related
    ORDER_PLACED = 'order_placed'
    ORDER_FILLED = 'order_filled'
    ORDER_CANCELLED = 'order_cancelled'

    # Additional position events
    TP_HIT = 'tp_hit'                     # Take profit hit (generic)
    BREAK_EVEN_HIT = 'break_even_hit'     # Break even stop triggered
    MANUAL_CLOSE = 'manual_close'         # Position manually closed


class TriggeredBy:
    """Constants for triggered_by values."""

    USER = 'user'           # Direct user action (telegram bot)
    CELERY = 'celery'       # Celery task
    WEBSOCKET = 'websocket' # position_monitor WebSocket
    EXCHANGE = 'exchange'   # Exchange event
    SYSTEM = 'system'       # Internal system
    SIGNAL = 'signal'       # Trading signal triggered
    TP_SL = 'tp_sl'         # TP/SL order triggered
