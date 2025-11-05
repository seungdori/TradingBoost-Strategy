"""
Shared database models for user identifier mapping and error logging.

This module provides SQLAlchemy models for:
- User identifier mapping (user_id, telegram_id, okx_uid)
- Error logging (centralized error storage)
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Index, Integer, String, Text, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for shared database models."""
    pass


class UserIdentifierMapping(Base):
    """
    사용자 식별자 매핑 테이블.

    다양한 사용자 식별자(user_id, telegram_id, okx_uid)간의 매핑 관계를 관리합니다.
    Redis 캐싱과 함께 사용하여 빠른 조회를 지원합니다.

    Attributes:
        id: 자동 증가 Primary Key
        user_id: 사용자 고유 식별자 (UUID 또는 정수 문자열)
        telegram_id: 텔레그램 사용자 ID (정수, Telegram API용)
        okx_uid: OKX 거래소 UID (문자열, nullable)
        created_at: 레코드 생성 시각
        updated_at: 레코드 최종 수정 시각
        is_active: 활성 상태 (기본: True)
    """

    __tablename__ = "user_identifier_mappings"

    # 복합 인덱스: 각 식별자로 빠른 조회 가능
    __table_args__ = (
        Index('idx_user_id', 'user_id'),
        Index('idx_telegram_id', 'telegram_id'),
        Index('idx_okx_uid', 'okx_uid'),
        Index('idx_active_users', 'is_active', 'telegram_id'),
        Index('idx_execution_mode', 'execution_mode'),
    )

    # Primary Key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # User Identifiers
    user_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="사용자 고유 식별자 (UUID 또는 정수 문자열)"
    )

    telegram_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
        comment="텔레그램 사용자 ID (정수)"
    )

    okx_uid: Mapped[Optional[str]] = mapped_column(
        String(255),
        unique=True,
        nullable=True,
        index=True,
        comment="OKX 거래소 UID (선택적)"
    )

    # Execution Mode Settings
    execution_mode: Mapped[str] = mapped_column(
        String(20),
        default="api_direct",
        nullable=False,
        index=True,
        comment="주문 실행 방식 (api_direct | signal_bot)"
    )

    signal_bot_token: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="OKX Signal Bot Token (보안 주의: 암호화 저장 권장)"
    )

    signal_bot_webhook_url: Mapped[Optional[str]] = mapped_column(
        String(512),
        nullable=True,
        comment="OKX Signal Bot Webhook URL"
    )

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        nullable=False,
        comment="레코드 생성 시각"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
        nullable=False,
        comment="레코드 최종 수정 시각"
    )

    is_active: Mapped[bool] = mapped_column(
        Integer,  # SQLite compatibility: use 0/1 for boolean
        default=1,
        nullable=False,
        comment="활성 상태 (1=활성, 0=비활성)"
    )

    def __repr__(self) -> str:
        return (
            f"<UserIdentifierMapping("
            f"id={self.id}, "
            f"user_id={self.user_id}, "
            f"telegram_id={self.telegram_id}, "
            f"okx_uid={self.okx_uid}, "
            f"is_active={self.is_active}"
            f")>"
        )

    def to_dict(self) -> dict:
        """Convert model to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "telegram_id": self.telegram_id,
            "okx_uid": self.okx_uid,
            "execution_mode": self.execution_mode,
            "signal_bot_webhook_url": self.signal_bot_webhook_url,
            # 보안: signal_bot_token은 반환하지 않음
            "has_signal_bot_token": bool(self.signal_bot_token),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_active": bool(self.is_active)
        }


class ErrorLog(Base):
    """
    에러 로그 테이블.

    모든 시스템 에러를 중앙 집중식으로 저장하여 분석과 모니터링을 지원합니다.
    파일 기반 로깅과 병행하여 DB 쿼리를 통한 에러 분석이 가능합니다.

    Attributes:
        id: 자동 증가 Primary Key
        timestamp: 에러 발생 시각 (인덱스)
        user_id: 사용자 ID (okx_uid 또는 user_id, nullable)
        telegram_id: 텔레그램 ID (nullable)
        error_type: 에러 타입/카테고리 (예: ValidationError, APIError, DatabaseError)
        error_message: 에러 메시지
        error_details: 에러 상세 정보 (JSON)
        strategy_type: 전략 타입 (HYPERRSI, GRID 등)
        module: 에러 발생 모듈
        function: 에러 발생 함수
        traceback: 스택 트레이스 (전체 텍스트)
        extra_metadata: 추가 메타데이터 (JSON)
        severity: 심각도 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        resolved: 해결 여부
        resolved_at: 해결 시각
    """

    __tablename__ = "error_logs"

    # 복합 인덱스: 시간별, 사용자별, 타입별 쿼리 최적화
    __table_args__ = (
        Index('idx_timestamp', 'timestamp'),
        Index('idx_user_id', 'user_id'),
        Index('idx_telegram_id', 'telegram_id'),
        Index('idx_error_type', 'error_type'),
        Index('idx_strategy_type', 'strategy_type'),
        Index('idx_severity', 'severity'),
        Index('idx_resolved', 'resolved'),
        Index('idx_timestamp_user', 'timestamp', 'user_id'),
        Index('idx_timestamp_strategy', 'timestamp', 'strategy_type'),
    )

    # Primary Key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Timestamp (중요: 시계열 데이터)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        index=True,
        default=datetime.utcnow,
        comment="에러 발생 시각 (UTC)"
    )

    # User Information
    user_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="사용자 ID (okx_uid 또는 user_id)"
    )

    telegram_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        index=True,
        comment="텔레그램 사용자 ID"
    )

    # Error Classification
    error_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="에러 타입/카테고리"
    )

    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        default="ERROR",
        comment="심각도 (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )

    strategy_type: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        index=True,
        comment="전략 타입 (HYPERRSI, GRID)"
    )

    # Error Content
    error_message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="에러 메시지"
    )

    error_details: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="에러 상세 정보 (JSON)"
    )

    # Code Location
    module: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="에러 발생 모듈"
    )

    function: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="에러 발생 함수"
    )

    traceback: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="스택 트레이스"
    )

    # Additional Metadata
    extra_metadata: Mapped[Optional[dict]] = mapped_column(
        "metadata",  # DB 컬럼명은 그대로 유지
        JSON,
        nullable=True,
        comment="추가 메타데이터 (JSON)"
    )

    # Resolution Status
    resolved: Mapped[bool] = mapped_column(
        Integer,  # SQLite compatibility: 0/1 for boolean
        default=0,
        nullable=False,
        index=True,
        comment="해결 여부 (0=미해결, 1=해결)"
    )

    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="해결 시각"
    )

    def __repr__(self) -> str:
        return (
            f"<ErrorLog("
            f"id={self.id}, "
            f"timestamp={self.timestamp}, "
            f"error_type={self.error_type}, "
            f"severity={self.severity}, "
            f"user_id={self.user_id}, "
            f"resolved={self.resolved}"
            f")>"
        )

    def to_dict(self) -> dict:
        """Convert model to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "user_id": self.user_id,
            "telegram_id": self.telegram_id,
            "error_type": self.error_type,
            "severity": self.severity,
            "strategy_type": self.strategy_type,
            "error_message": self.error_message,
            "error_details": self.error_details,
            "module": self.module,
            "function": self.function,
            "traceback": self.traceback,
            "metadata": self.metadata,
            "resolved": bool(self.resolved),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None
        }
