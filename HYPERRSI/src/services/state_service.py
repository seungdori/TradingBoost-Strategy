"""
HYPERRSI State Service.

현재 봇 상태 관리 서비스 (PostgreSQL SSOT).
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.session import get_transactional_session
from shared.logging import get_logger

from HYPERRSI.src.core.models.current_state import HyperrsiCurrent
from HYPERRSI.src.core.models.state_change import ChangeType, TriggeredBy

logger = get_logger(__name__)


class StateService:
    """
    현재 봇 상태 관리 서비스.

    PostgreSQL이 SSOT (Source of Truth), Redis는 캐시.
    모든 상태 변경은 DB에 먼저 기록되고, 이후 Redis에 동기화됩니다.
    """

    def __init__(self, state_change_logger=None, cache_sync_service=None):
        """
        Initialize state service.

        Args:
            state_change_logger: StateChangeLogger instance
            cache_sync_service: CacheSyncService instance
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

    async def get_current_state(
        self,
        okx_uid: str,
        symbol: str
    ) -> Optional[HyperrsiCurrent]:
        """
        현재 상태 조회.

        Args:
            okx_uid: OKX 사용자 UID
            symbol: 거래 심볼

        Returns:
            Optional[HyperrsiCurrent]: 현재 상태 (없으면 None)
        """
        try:
            async with get_transactional_session() as session:
                stmt = select(HyperrsiCurrent).where(
                    HyperrsiCurrent.okx_uid == okx_uid,
                    HyperrsiCurrent.symbol == symbol
                )
                result = await session.execute(stmt)
                return result.scalar_one_or_none()

        except Exception as e:
            logger.error(f"Failed to get current state: {e}", exc_info=True)
            return None

    async def update_position(
        self,
        okx_uid: str,
        symbol: str,
        side: str,
        position_data: Dict[str, Any],
        change_type: str,
        session_id: Optional[int] = None,
        price: Optional[float] = None,
        pnl: Optional[float] = None,
        pnl_percent: Optional[float] = None,
        triggered_by: str = TriggeredBy.SYSTEM,
        trigger_source: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[HyperrsiCurrent]:
        """
        포지션 상태 업데이트.

        1. hyperrsi_current 업데이트
        2. hyperrsi_state_changes에 변경 기록
        3. Redis 캐시 동기화

        Args:
            okx_uid: OKX 사용자 UID
            symbol: 거래 심볼
            side: 포지션 방향 ('long', 'short', 'hedge')
            position_data: 포지션 데이터
            change_type: 변경 유형
            session_id: 세션 ID (optional)
            price: 가격
            pnl: 손익
            pnl_percent: 손익률
            triggered_by: 트리거 주체
            trigger_source: 트리거 소스 상세
            metadata: 추가 메타데이터

        Returns:
            Optional[HyperrsiCurrent]: 업데이트된 상태
        """
        previous_state = None
        current_state = None

        try:
            async with get_transactional_session() as session:
                # 1. 현재 상태 조회
                stmt = select(HyperrsiCurrent).where(
                    HyperrsiCurrent.okx_uid == okx_uid,
                    HyperrsiCurrent.symbol == symbol
                )
                result = await session.execute(stmt)
                current_state = result.scalar_one_or_none()

                if not current_state:
                    logger.warning(
                        f"No current state found for okx_uid={okx_uid}, symbol={symbol}"
                    )
                    return None

                # 2. 이전 상태 저장
                if side == 'long':
                    previous_state = current_state.position_long
                elif side == 'short':
                    previous_state = current_state.position_short
                elif side == 'hedge':
                    previous_state = current_state.hedge_position
                else:
                    logger.warning(f"Invalid position side: {side}")
                    return None

                # 3. 포지션 업데이트
                position_data['last_update'] = datetime.utcnow().isoformat()

                if side == 'long':
                    current_state.position_long = position_data
                elif side == 'short':
                    current_state.position_short = position_data
                elif side == 'hedge':
                    current_state.hedge_position = position_data

                current_state.last_execution_at = datetime.utcnow()

                # 세션 ID 업데이트 (제공된 경우)
                if session_id:
                    current_state.session_id = session_id

            # 4. Redis 캐시 동기화 (트랜잭션 외부)
            try:
                await self.cache_sync_service.sync_position(
                    okx_uid=okx_uid,
                    symbol=symbol,
                    side=side,
                    position_data=position_data
                )
            except Exception as e:
                logger.warning(f"Failed to sync position to Redis: {e}")

            # 5. 이벤트 기록 (비동기, non-blocking)
            try:
                await self.state_change_logger.log_change(
                    okx_uid=okx_uid,
                    symbol=symbol,
                    change_type=change_type,
                    session_id=session_id or (current_state.session_id if current_state else None),
                    previous_state=previous_state,
                    new_state=position_data,
                    price=price,
                    pnl=pnl,
                    pnl_percent=pnl_percent,
                    triggered_by=triggered_by,
                    trigger_source=trigger_source or 'state_service.update_position',
                    metadata=metadata
                )
            except Exception as e:
                logger.warning(f"Failed to log position change: {e}")

            logger.debug(
                f"Position updated: okx_uid={okx_uid}, symbol={symbol}, "
                f"side={side}, change_type={change_type}"
            )

            return current_state

        except Exception as e:
            logger.error(f"Failed to update position: {e}", exc_info=True)
            return None

    async def clear_position(
        self,
        okx_uid: str,
        symbol: str,
        side: str,
        change_type: str = ChangeType.POSITION_CLOSED,
        price: Optional[float] = None,
        pnl: Optional[float] = None,
        pnl_percent: Optional[float] = None,
        triggered_by: str = TriggeredBy.SYSTEM,
        trigger_source: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[HyperrsiCurrent]:
        """
        포지션 청산 (상태 클리어).

        Args:
            okx_uid: OKX 사용자 UID
            symbol: 거래 심볼
            side: 포지션 방향 ('long', 'short', 'hedge')
            change_type: 변경 유형
            price: 청산 가격
            pnl: 실현 손익
            pnl_percent: 손익률
            triggered_by: 트리거 주체
            trigger_source: 트리거 소스 상세
            metadata: 추가 메타데이터

        Returns:
            Optional[HyperrsiCurrent]: 업데이트된 상태
        """
        previous_state = None
        current_state = None

        try:
            async with get_transactional_session() as session:
                # 1. 현재 상태 조회
                stmt = select(HyperrsiCurrent).where(
                    HyperrsiCurrent.okx_uid == okx_uid,
                    HyperrsiCurrent.symbol == symbol
                )
                result = await session.execute(stmt)
                current_state = result.scalar_one_or_none()

                if not current_state:
                    return None

                # 2. 이전 상태 저장
                if side == 'long':
                    previous_state = current_state.position_long
                    current_state.position_long = None
                elif side == 'short':
                    previous_state = current_state.position_short
                    current_state.position_short = None
                elif side == 'hedge':
                    previous_state = current_state.hedge_position
                    current_state.hedge_position = None

                current_state.last_execution_at = datetime.utcnow()

                # 3. 통계 업데이트
                if pnl:
                    current_state.trades_today = (current_state.trades_today or 0) + 1
                    current_state.pnl_today = Decimal(str(
                        float(current_state.pnl_today or 0) + pnl
                    ))

            # 4. Redis 캐시 동기화
            try:
                await self.cache_sync_service.clear_position(
                    okx_uid=okx_uid,
                    symbol=symbol,
                    side=side
                )
            except Exception as e:
                logger.warning(f"Failed to clear position from Redis: {e}")

            # 5. 이벤트 기록
            try:
                await self.state_change_logger.log_change(
                    okx_uid=okx_uid,
                    symbol=symbol,
                    change_type=change_type,
                    session_id=current_state.session_id if current_state else None,
                    previous_state=previous_state,
                    new_state=None,
                    price=price,
                    pnl=pnl,
                    pnl_percent=pnl_percent,
                    triggered_by=triggered_by,
                    trigger_source=trigger_source or 'state_service.clear_position',
                    metadata=metadata
                )
            except Exception as e:
                logger.warning(f"Failed to log position clear: {e}")

            logger.info(
                f"Position cleared: okx_uid={okx_uid}, symbol={symbol}, "
                f"side={side}, pnl={pnl}"
            )

            return current_state

        except Exception as e:
            logger.error(f"Failed to clear position: {e}", exc_info=True)
            return None

    async def update_settings(
        self,
        okx_uid: str,
        symbol: str,
        params_settings: Optional[Dict[str, Any]] = None,
        dual_side_settings: Optional[Dict[str, Any]] = None,
        triggered_by: str = TriggeredBy.USER,
        trigger_source: Optional[str] = None
    ) -> Optional[HyperrsiCurrent]:
        """
        설정 업데이트.

        1. hyperrsi_current 업데이트
        2. 'settings_updated' 또는 'dual_side_updated' 이벤트 기록
        3. Redis 캐시 동기화

        Args:
            okx_uid: OKX 사용자 UID
            symbol: 거래 심볼
            params_settings: 트레이딩 파라미터 (optional)
            dual_side_settings: 양방향 설정 (optional)
            triggered_by: 트리거 주체
            trigger_source: 트리거 소스 상세

        Returns:
            Optional[HyperrsiCurrent]: 업데이트된 상태
        """
        previous_params = None
        previous_dual_side = None
        current_state = None

        try:
            async with get_transactional_session() as session:
                # 1. 현재 상태 조회
                stmt = select(HyperrsiCurrent).where(
                    HyperrsiCurrent.okx_uid == okx_uid,
                    HyperrsiCurrent.symbol == symbol
                )
                result = await session.execute(stmt)
                current_state = result.scalar_one_or_none()

                if not current_state:
                    logger.warning(
                        f"No current state found for okx_uid={okx_uid}, symbol={symbol}"
                    )
                    return None

                # 2. 이전 상태 저장 및 업데이트
                if params_settings is not None:
                    previous_params = current_state.params_settings
                    current_state.params_settings = params_settings

                if dual_side_settings is not None:
                    previous_dual_side = current_state.dual_side_settings
                    current_state.dual_side_settings = dual_side_settings

            # 3. Redis 캐시 동기화
            try:
                await self.cache_sync_service.sync_settings(
                    okx_uid=okx_uid,
                    symbol=symbol,
                    params_settings=params_settings,
                    dual_side_settings=dual_side_settings
                )
            except Exception as e:
                logger.warning(f"Failed to sync settings to Redis: {e}")

            # 4. 이벤트 기록
            if params_settings is not None:
                try:
                    await self.state_change_logger.log_change(
                        okx_uid=okx_uid,
                        symbol=symbol,
                        change_type=ChangeType.SETTINGS_UPDATED,
                        session_id=current_state.session_id if current_state else None,
                        previous_state=previous_params,
                        new_state=params_settings,
                        triggered_by=triggered_by,
                        trigger_source=trigger_source or 'state_service.update_settings'
                    )
                except Exception as e:
                    logger.warning(f"Failed to log settings update: {e}")

            if dual_side_settings is not None:
                try:
                    await self.state_change_logger.log_change(
                        okx_uid=okx_uid,
                        symbol=symbol,
                        change_type=ChangeType.DUAL_SIDE_UPDATED,
                        session_id=current_state.session_id if current_state else None,
                        previous_state=previous_dual_side,
                        new_state=dual_side_settings,
                        triggered_by=triggered_by,
                        trigger_source=trigger_source or 'state_service.update_settings'
                    )
                except Exception as e:
                    logger.warning(f"Failed to log dual_side update: {e}")

            logger.debug(
                f"Settings updated: okx_uid={okx_uid}, symbol={symbol}"
            )

            return current_state

        except Exception as e:
            logger.error(f"Failed to update settings: {e}", exc_info=True)
            return None

    async def update_last_signal(
        self,
        okx_uid: str,
        symbol: str,
        signal: str
    ) -> None:
        """
        마지막 시그널 업데이트 (간단한 업데이트, 이벤트 기록 없음).

        Args:
            okx_uid: OKX 사용자 UID
            symbol: 거래 심볼
            signal: 시그널
        """
        try:
            async with get_transactional_session() as session:
                stmt = update(HyperrsiCurrent).where(
                    HyperrsiCurrent.okx_uid == okx_uid,
                    HyperrsiCurrent.symbol == symbol
                ).values(
                    last_signal=signal,
                    last_execution_at=datetime.utcnow()
                )
                await session.execute(stmt)

        except Exception as e:
            logger.error(f"Failed to update last signal: {e}", exc_info=True)

    async def reset_daily_stats(self, okx_uid: str, symbol: str) -> None:
        """
        일일 통계 리셋.

        Args:
            okx_uid: OKX 사용자 UID
            symbol: 거래 심볼
        """
        try:
            async with get_transactional_session() as session:
                stmt = update(HyperrsiCurrent).where(
                    HyperrsiCurrent.okx_uid == okx_uid,
                    HyperrsiCurrent.symbol == symbol
                ).values(
                    trades_today=0,
                    pnl_today=Decimal('0')
                )
                await session.execute(stmt)

        except Exception as e:
            logger.error(f"Failed to reset daily stats: {e}", exc_info=True)


# Singleton instance
_state_service: Optional[StateService] = None


def get_state_service() -> StateService:
    """Get singleton StateService instance."""
    global _state_service
    if _state_service is None:
        _state_service = StateService()
    return _state_service
