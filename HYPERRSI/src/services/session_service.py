"""
HYPERRSI Session Service.

트레이딩 세션 라이프사이클 관리 서비스.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.session import get_transactional_session
from shared.logging import get_logger

from HYPERRSI.src.core.models.session import HyperrsiSession
from HYPERRSI.src.core.models.current_state import HyperrsiCurrent
from HYPERRSI.src.core.models.state_change import ChangeType, TriggeredBy

logger = get_logger(__name__)


class SessionService:
    """
    트레이딩 세션 관리 서비스.

    봇 시작/종료 단위로 세션을 관리하고,
    현재 상태(hyperrsi_current)와 동기화합니다.
    """

    def __init__(self, state_change_logger=None, cache_sync_service=None):
        """
        Initialize session service.

        Args:
            state_change_logger: StateChangeLogger instance (optional, will be imported if None)
            cache_sync_service: CacheSyncService instance (optional, will be imported if None)
        """
        self._state_change_logger = state_change_logger
        self._cache_sync_service = cache_sync_service

    @property
    def state_change_logger(self):
        """Lazy load state change logger."""
        if self._state_change_logger is None:
            from HYPERRSI.src.services.state_change_logger import get_state_change_logger
            self._state_change_logger = get_state_change_logger()
        return self._state_change_logger

    @property
    def cache_sync_service(self):
        """Lazy load cache sync service."""
        if self._cache_sync_service is None:
            from HYPERRSI.src.services.cache_sync_service import get_cache_sync_service
            self._cache_sync_service = get_cache_sync_service()
        return self._cache_sync_service

    async def start_session(
        self,
        okx_uid: str,
        symbol: str,
        timeframe: str,
        params_settings: dict,
        dual_side_settings: dict,
        telegram_id: Optional[int] = None,
        triggered_by: str = TriggeredBy.SYSTEM,
        trigger_source: Optional[str] = None
    ) -> int:
        """
        트레이딩 세션 시작.

        1. hyperrsi_sessions에 새 레코드 생성
        2. hyperrsi_current UPSERT (INSERT OR UPDATE)
        3. Redis 캐시 동기화
        4. 'session_started' 이벤트 기록

        Args:
            okx_uid: OKX 사용자 UID
            symbol: 거래 심볼
            timeframe: 타임프레임
            params_settings: 트레이딩 파라미터
            dual_side_settings: 양방향 매매 설정
            telegram_id: 텔레그램 ID (optional)
            triggered_by: 트리거 주체
            trigger_source: 트리거 소스 상세

        Returns:
            int: 생성된 세션 ID
        """
        try:
            async with get_transactional_session() as session:
                # 1. 기존 실행 중인 세션이 있으면 종료
                await self._close_existing_session(
                    session, okx_uid, symbol, 'system_restart'
                )

                # 2. 새 세션 생성
                new_session = HyperrsiSession(
                    okx_uid=okx_uid,
                    telegram_id=telegram_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    status='running',
                    params_settings=params_settings,
                    dual_side_settings=dual_side_settings,
                )
                session.add(new_session)
                await session.flush()  # ID 확보

                session_id = new_session.id
                logger.info(
                    f"Session created: session_id={session_id}, "
                    f"okx_uid={okx_uid}, symbol={symbol}"
                )

                # 3. hyperrsi_current UPSERT
                await self._upsert_current_state(
                    session=session,
                    okx_uid=okx_uid,
                    telegram_id=telegram_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    session_id=session_id,
                    params_settings=params_settings,
                    dual_side_settings=dual_side_settings,
                    is_running=True
                )

            # 4. Redis 캐시 동기화 (트랜잭션 외부)
            try:
                await self.cache_sync_service.sync_session_start(
                    okx_uid=okx_uid,
                    symbol=symbol,
                    timeframe=timeframe,
                    session_id=session_id,
                    params_settings=params_settings,
                    dual_side_settings=dual_side_settings
                )
            except Exception as e:
                logger.warning(f"Failed to sync session start to Redis: {e}")

            # 5. 이벤트 기록 (비동기, non-blocking)
            try:
                await self.state_change_logger.log_change(
                    okx_uid=okx_uid,
                    symbol=symbol,
                    change_type=ChangeType.SESSION_STARTED,
                    session_id=session_id,
                    new_state={
                        'timeframe': timeframe,
                        'params_settings': params_settings,
                        'dual_side_settings': dual_side_settings,
                    },
                    triggered_by=triggered_by,
                    trigger_source=trigger_source or 'session_service.start_session'
                )
            except Exception as e:
                logger.warning(f"Failed to log session_started event: {e}")

            return session_id

        except Exception as e:
            logger.error(f"Failed to start session: {e}", exc_info=True)
            raise

    async def stop_session(
        self,
        okx_uid: str,
        symbol: str,
        end_reason: str = 'manual',
        error_message: Optional[str] = None,
        final_settings: Optional[dict] = None,
        triggered_by: str = TriggeredBy.USER,
        trigger_source: Optional[str] = None
    ) -> Optional[int]:
        """
        트레이딩 세션 종료.

        1. hyperrsi_sessions 업데이트 (ended_at, final_settings, 통계)
        2. hyperrsi_current 업데이트 (is_running=False)
        3. Redis 캐시 정리
        4. 'session_stopped' 이벤트 기록

        Args:
            okx_uid: OKX 사용자 UID
            symbol: 거래 심볼
            end_reason: 종료 사유 ('manual', 'error', 'system')
            error_message: 에러 메시지 (에러 종료 시)
            final_settings: 최종 설정값
            triggered_by: 트리거 주체
            trigger_source: 트리거 소스 상세

        Returns:
            Optional[int]: 종료된 세션 ID (없으면 None)
        """
        session_id = None

        try:
            async with get_transactional_session() as db_session:
                # 1. 현재 실행 중인 세션 조회
                stmt = select(HyperrsiSession).where(
                    HyperrsiSession.okx_uid == okx_uid,
                    HyperrsiSession.symbol == symbol,
                    HyperrsiSession.status == 'running'
                ).order_by(HyperrsiSession.started_at.desc()).limit(1)

                result = await db_session.execute(stmt)
                running_session = result.scalar_one_or_none()

                if running_session:
                    session_id = running_session.id

                    # 세션 통계 조회 (from hyperrsi_current)
                    current_state = await self._get_current_state(
                        db_session, okx_uid, symbol
                    )

                    # 2. 세션 업데이트
                    update_data = {
                        'status': 'error' if end_reason == 'error' else 'stopped',
                        'ended_at': datetime.utcnow(),
                        'end_reason': end_reason,
                        'error_message': error_message,
                        'final_settings': final_settings or {
                            'params_settings': current_state.params_settings if current_state else {},
                            'dual_side_settings': current_state.dual_side_settings if current_state else {},
                        },
                    }

                    if current_state:
                        update_data['total_trades'] = current_state.trades_today
                        update_data['total_pnl'] = current_state.pnl_today

                    stmt = update(HyperrsiSession).where(
                        HyperrsiSession.id == session_id
                    ).values(**update_data)
                    await db_session.execute(stmt)

                    logger.info(
                        f"Session stopped: session_id={session_id}, "
                        f"end_reason={end_reason}"
                    )

                # 3. hyperrsi_current 업데이트
                if current_state:
                    stmt = update(HyperrsiCurrent).where(
                        HyperrsiCurrent.okx_uid == okx_uid,
                        HyperrsiCurrent.symbol == symbol
                    ).values(
                        is_running=False,
                        session_id=None
                    )
                    await db_session.execute(stmt)

            # 4. Redis 캐시 정리 (트랜잭션 외부)
            try:
                await self.cache_sync_service.sync_session_stop(
                    okx_uid=okx_uid,
                    symbol=symbol
                )
            except Exception as e:
                logger.warning(f"Failed to sync session stop to Redis: {e}")

            # 5. 이벤트 기록
            if session_id:
                try:
                    await self.state_change_logger.log_change(
                        okx_uid=okx_uid,
                        symbol=symbol,
                        change_type=ChangeType.SESSION_STOPPED if end_reason != 'error' else ChangeType.SESSION_ERROR,
                        session_id=session_id,
                        new_state={
                            'end_reason': end_reason,
                            'error_message': error_message,
                        },
                        triggered_by=triggered_by,
                        trigger_source=trigger_source or 'session_service.stop_session'
                    )
                except Exception as e:
                    logger.warning(f"Failed to log session_stopped event: {e}")

            return session_id

        except Exception as e:
            logger.error(f"Failed to stop session: {e}", exc_info=True)
            raise

    async def get_running_session(
        self,
        okx_uid: str,
        symbol: str
    ) -> Optional[HyperrsiSession]:
        """
        현재 실행 중인 세션 조회.

        Args:
            okx_uid: OKX 사용자 UID
            symbol: 거래 심볼

        Returns:
            Optional[HyperrsiSession]: 실행 중인 세션 (없으면 None)
        """
        try:
            async with get_transactional_session() as session:
                stmt = select(HyperrsiSession).where(
                    HyperrsiSession.okx_uid == okx_uid,
                    HyperrsiSession.symbol == symbol,
                    HyperrsiSession.status == 'running'
                ).order_by(HyperrsiSession.started_at.desc()).limit(1)

                result = await session.execute(stmt)
                return result.scalar_one_or_none()

        except Exception as e:
            logger.error(f"Failed to get running session: {e}", exc_info=True)
            return None

    async def get_session_history(
        self,
        okx_uid: str,
        symbol: Optional[str] = None,
        limit: int = 50
    ) -> List[HyperrsiSession]:
        """
        세션 이력 조회.

        Args:
            okx_uid: OKX 사용자 UID
            symbol: 거래 심볼 (optional, 전체 심볼 조회 시 None)
            limit: 최대 조회 수

        Returns:
            List[HyperrsiSession]: 세션 이력 목록
        """
        try:
            async with get_transactional_session() as session:
                stmt = select(HyperrsiSession).where(
                    HyperrsiSession.okx_uid == okx_uid
                )

                if symbol:
                    stmt = stmt.where(HyperrsiSession.symbol == symbol)

                stmt = stmt.order_by(HyperrsiSession.started_at.desc()).limit(limit)

                result = await session.execute(stmt)
                return list(result.scalars().all())

        except Exception as e:
            logger.error(f"Failed to get session history: {e}", exc_info=True)
            return []

    async def update_session_stats(
        self,
        session_id: int,
        total_trades: int,
        winning_trades: int,
        total_pnl: Decimal
    ) -> None:
        """
        세션 통계 업데이트.

        Args:
            session_id: 세션 ID
            total_trades: 총 거래 수
            winning_trades: 수익 거래 수
            total_pnl: 총 손익
        """
        try:
            async with get_transactional_session() as session:
                stmt = update(HyperrsiSession).where(
                    HyperrsiSession.id == session_id
                ).values(
                    total_trades=total_trades,
                    winning_trades=winning_trades,
                    total_pnl=total_pnl
                )
                await session.execute(stmt)

        except Exception as e:
            logger.error(f"Failed to update session stats: {e}", exc_info=True)

    async def _close_existing_session(
        self,
        db_session: AsyncSession,
        okx_uid: str,
        symbol: str,
        end_reason: str
    ) -> None:
        """기존 실행 중인 세션 종료 (내부 메서드)."""
        stmt = update(HyperrsiSession).where(
            HyperrsiSession.okx_uid == okx_uid,
            HyperrsiSession.symbol == symbol,
            HyperrsiSession.status == 'running'
        ).values(
            status='stopped',
            ended_at=datetime.utcnow(),
            end_reason=end_reason
        )
        await db_session.execute(stmt)

    async def _upsert_current_state(
        self,
        session: AsyncSession,
        okx_uid: str,
        telegram_id: Optional[int],
        symbol: str,
        timeframe: str,
        session_id: int,
        params_settings: dict,
        dual_side_settings: dict,
        is_running: bool
    ) -> HyperrsiCurrent:
        """hyperrsi_current UPSERT (내부 메서드)."""
        # 기존 레코드 조회
        stmt = select(HyperrsiCurrent).where(
            HyperrsiCurrent.okx_uid == okx_uid,
            HyperrsiCurrent.symbol == symbol
        )
        result = await session.execute(stmt)
        current = result.scalar_one_or_none()

        if current:
            # UPDATE
            current.telegram_id = telegram_id
            current.timeframe = timeframe
            current.session_id = session_id
            current.params_settings = params_settings
            current.dual_side_settings = dual_side_settings
            current.is_running = is_running
            current.last_execution_at = datetime.utcnow()
        else:
            # INSERT
            current = HyperrsiCurrent(
                okx_uid=okx_uid,
                telegram_id=telegram_id,
                symbol=symbol,
                timeframe=timeframe,
                session_id=session_id,
                params_settings=params_settings,
                dual_side_settings=dual_side_settings,
                is_running=is_running,
            )
            session.add(current)

        return current

    async def _get_current_state(
        self,
        session: AsyncSession,
        okx_uid: str,
        symbol: str
    ) -> Optional[HyperrsiCurrent]:
        """현재 상태 조회 (내부 메서드)."""
        stmt = select(HyperrsiCurrent).where(
            HyperrsiCurrent.okx_uid == okx_uid,
            HyperrsiCurrent.symbol == symbol
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


# Singleton instance
_session_service: Optional[SessionService] = None


def get_session_service() -> SessionService:
    """Get singleton SessionService instance."""
    global _session_service
    if _session_service is None:
        _session_service = SessionService()
    return _session_service
