"""
HYPERRSI Trade Record Service.

거래 기록 관리 서비스 - 포지션 종료 시 거래 기록을 저장합니다.
"""

from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List, Dict, Any

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.session import get_transactional_session
from shared.logging import get_logger

from HYPERRSI.src.core.models.trade import HyperrsiTrade, HyperrsiDailyStats, CloseType
from HYPERRSI.src.core.models.state_change import ChangeType, TriggeredBy

logger = get_logger(__name__)


class TradeRecordService:
    """
    거래 기록 관리 서비스.

    포지션 종료 시 거래 정보를 hyperrsi_trades 테이블에 저장하고,
    통계 조회 기능을 제공합니다.
    """

    def __init__(self, state_change_logger=None):
        """
        Initialize trade record service.

        Args:
            state_change_logger: StateChangeLogger instance (optional)
        """
        self._state_change_logger = state_change_logger

    @property
    def state_change_logger(self):
        """Lazy load state change logger."""
        if self._state_change_logger is None:
            from HYPERRSI.src.services.state_change_logger import get_state_change_logger
            self._state_change_logger = get_state_change_logger()
        return self._state_change_logger

    async def record_trade(
        self,
        okx_uid: str,
        symbol: str,
        side: str,
        entry_time: datetime,
        entry_price: float,
        entry_size: float,
        exit_time: datetime,
        exit_price: float,
        exit_size: float,
        close_type: str,
        realized_pnl: float,
        realized_pnl_percent: float,
        leverage: int = 1,
        dca_count: int = 0,
        avg_entry_price: Optional[float] = None,
        entry_fee: float = 0.0,
        exit_fee: float = 0.0,
        is_hedge: bool = False,
        session_id: Optional[int] = None,
        telegram_id: Optional[int] = None,
        entry_order_id: Optional[str] = None,
        exit_order_id: Optional[str] = None,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[int]:
        """
        거래 기록 저장.

        포지션이 종료될 때 호출하여 거래 정보를 기록합니다.

        Args:
            okx_uid: OKX 사용자 UID
            symbol: 거래 심볼
            side: 거래 방향 ('long', 'short')
            entry_time: 진입 시간
            entry_price: 진입 가격
            entry_size: 진입 수량
            exit_time: 청산 시간
            exit_price: 청산 가격
            exit_size: 청산 수량
            close_type: 청산 유형 (CloseType 상수 참조)
            realized_pnl: 실현 손익 (USDT)
            realized_pnl_percent: 실현 손익률 (%)
            leverage: 레버리지
            dca_count: DCA 횟수
            avg_entry_price: 평균 진입 가격 (DCA 사용 시)
            entry_fee: 진입 수수료
            exit_fee: 청산 수수료
            is_hedge: 헤지 포지션 여부
            session_id: 세션 ID
            telegram_id: 텔레그램 ID
            entry_order_id: 진입 주문 ID
            exit_order_id: 청산 주문 ID
            extra_data: 추가 메타데이터

        Returns:
            Optional[int]: 생성된 거래 기록 ID (실패 시 None)
        """
        try:
            # 계산 필드
            entry_value = entry_price * entry_size
            exit_value = exit_price * exit_size

            async with get_transactional_session() as session:
                trade = HyperrsiTrade(
                    okx_uid=okx_uid,
                    telegram_id=telegram_id,
                    symbol=symbol,
                    side=side,
                    is_hedge=is_hedge,
                    entry_time=entry_time,
                    entry_price=Decimal(str(entry_price)),
                    entry_size=Decimal(str(entry_size)),
                    entry_value=Decimal(str(entry_value)),
                    exit_time=exit_time,
                    exit_price=Decimal(str(exit_price)),
                    exit_size=Decimal(str(exit_size)),
                    exit_value=Decimal(str(exit_value)),
                    close_type=close_type,
                    leverage=leverage,
                    dca_count=dca_count,
                    avg_entry_price=Decimal(str(avg_entry_price)) if avg_entry_price else None,
                    realized_pnl=Decimal(str(realized_pnl)),
                    realized_pnl_percent=Decimal(str(realized_pnl_percent)),
                    entry_fee=Decimal(str(entry_fee)),
                    exit_fee=Decimal(str(exit_fee)),
                    session_id=session_id,
                    entry_order_id=entry_order_id,
                    exit_order_id=exit_order_id,
                    extra_data=extra_data or {},
                )
                session.add(trade)
                await session.flush()

                trade_id = trade.id
                logger.info(
                    f"Trade recorded: id={trade_id}, "
                    f"okx_uid={okx_uid}, symbol={symbol}, "
                    f"side={side}, pnl={realized_pnl:.4f}"
                )

            # 상태 변경 이벤트 기록
            try:
                await self.state_change_logger.log_change(
                    okx_uid=okx_uid,
                    symbol=symbol,
                    change_type=ChangeType.POSITION_CLOSED,
                    session_id=session_id,
                    new_state={
                        'trade_id': trade_id,
                        'side': side,
                        'close_type': close_type,
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'size': exit_size,
                        'realized_pnl': realized_pnl,
                        'is_hedge': is_hedge,
                    },
                    price=exit_price,
                    pnl=realized_pnl,
                    pnl_percent=realized_pnl_percent,
                    triggered_by=TriggeredBy.SYSTEM,
                    trigger_source='trade_record_service.record_trade',
                    extra_data=extra_data
                )
            except Exception as e:
                logger.warning(f"Failed to log position_closed event: {e}")

            return trade_id

        except Exception as e:
            logger.error(f"Failed to record trade: {e}", exc_info=True)
            return None

    async def get_trades(
        self,
        okx_uid: str,
        symbol: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        side: Optional[str] = None,
        close_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[HyperrsiTrade]:
        """
        거래 기록 조회.

        Args:
            okx_uid: OKX 사용자 UID
            symbol: 거래 심볼 (optional)
            start_date: 시작 날짜 (optional)
            end_date: 종료 날짜 (optional)
            side: 거래 방향 (optional)
            close_type: 청산 유형 (optional)
            limit: 최대 조회 수
            offset: 오프셋

        Returns:
            List[HyperrsiTrade]: 거래 기록 목록
        """
        try:
            async with get_transactional_session() as session:
                stmt = select(HyperrsiTrade).where(
                    HyperrsiTrade.okx_uid == okx_uid
                )

                if symbol:
                    stmt = stmt.where(HyperrsiTrade.symbol == symbol)
                if start_date:
                    stmt = stmt.where(HyperrsiTrade.exit_time >= datetime.combine(start_date, datetime.min.time()))
                if end_date:
                    stmt = stmt.where(HyperrsiTrade.exit_time <= datetime.combine(end_date, datetime.max.time()))
                if side:
                    stmt = stmt.where(HyperrsiTrade.side == side)
                if close_type:
                    stmt = stmt.where(HyperrsiTrade.close_type == close_type)

                stmt = stmt.order_by(HyperrsiTrade.exit_time.desc()).limit(limit).offset(offset)

                result = await session.execute(stmt)
                return list(result.scalars().all())

        except Exception as e:
            logger.error(f"Failed to get trades: {e}", exc_info=True)
            return []

    async def get_trade_count(
        self,
        okx_uid: str,
        symbol: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> int:
        """거래 수 조회."""
        try:
            async with get_transactional_session() as session:
                stmt = select(func.count(HyperrsiTrade.id)).where(
                    HyperrsiTrade.okx_uid == okx_uid
                )

                if symbol:
                    stmt = stmt.where(HyperrsiTrade.symbol == symbol)
                if start_date:
                    stmt = stmt.where(HyperrsiTrade.exit_time >= datetime.combine(start_date, datetime.min.time()))
                if end_date:
                    stmt = stmt.where(HyperrsiTrade.exit_time <= datetime.combine(end_date, datetime.max.time()))

                result = await session.execute(stmt)
                return result.scalar() or 0

        except Exception as e:
            logger.error(f"Failed to get trade count: {e}", exc_info=True)
            return 0

    async def get_recent_trades(
        self,
        okx_uid: str,
        symbol: Optional[str] = None,
        limit: int = 10
    ) -> List[HyperrsiTrade]:
        """최근 거래 기록 조회."""
        return await self.get_trades(
            okx_uid=okx_uid,
            symbol=symbol,
            limit=limit
        )

    async def get_trades_by_session(
        self,
        session_id: int,
        limit: int = 100
    ) -> List[HyperrsiTrade]:
        """세션별 거래 기록 조회."""
        try:
            async with get_transactional_session() as session:
                stmt = select(HyperrsiTrade).where(
                    HyperrsiTrade.session_id == session_id
                ).order_by(HyperrsiTrade.exit_time.desc()).limit(limit)

                result = await session.execute(stmt)
                return list(result.scalars().all())

        except Exception as e:
            logger.error(f"Failed to get trades by session: {e}", exc_info=True)
            return []

    async def get_symbols_traded(
        self,
        okx_uid: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> List[str]:
        """거래된 심볼 목록 조회."""
        try:
            async with get_transactional_session() as session:
                stmt = select(HyperrsiTrade.symbol.distinct()).where(
                    HyperrsiTrade.okx_uid == okx_uid
                )

                if start_date:
                    stmt = stmt.where(HyperrsiTrade.exit_time >= datetime.combine(start_date, datetime.min.time()))
                if end_date:
                    stmt = stmt.where(HyperrsiTrade.exit_time <= datetime.combine(end_date, datetime.max.time()))

                result = await session.execute(stmt)
                return [row[0] for row in result.all()]

        except Exception as e:
            logger.error(f"Failed to get symbols traded: {e}", exc_info=True)
            return []


# Singleton instance
_trade_record_service: Optional[TradeRecordService] = None


def get_trade_record_service() -> TradeRecordService:
    """Get singleton TradeRecordService instance."""
    global _trade_record_service
    if _trade_record_service is None:
        _trade_record_service = TradeRecordService()
    return _trade_record_service
