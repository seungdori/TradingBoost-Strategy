"""
HYPERRSI State Change Logger.

비동기 상태 변경 로깅 서비스 - 배치 쓰기로 성능 최적화.
"""

import asyncio
import json
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any, List

from shared.database.session import get_transactional_session
from shared.logging import get_logger

from HYPERRSI.src.core.models.state_change import HyperrsiStateChange

logger = get_logger(__name__)


class StateChangeLogger:
    """
    비동기 상태 변경 로깅 서비스.

    특징:
    - 배치 쓰기로 성능 최적화 (5초 간격)
    - 큐 기반 비블로킹 처리
    - 실패 시 자동 재시도

    Usage:
        logger = StateChangeLogger()
        await logger.start()

        # 상태 변경 기록 (non-blocking)
        await logger.log_change(
            okx_uid='12345',
            symbol='BTC-USDT-SWAP',
            change_type='position_opened',
            new_state={'entry_price': 45000.0}
        )

        # 종료 시
        await logger.stop()
    """

    BATCH_SIZE = 100
    FLUSH_INTERVAL = 5  # seconds
    MAX_QUEUE_SIZE = 1000
    MAX_RETRIES = 3

    def __init__(self):
        """Initialize state change logger."""
        self._change_queue: asyncio.Queue = asyncio.Queue(maxsize=self.MAX_QUEUE_SIZE)
        self._running = False
        self._flush_task: Optional[asyncio.Task] = None
        self._retry_queue: List[Dict[str, Any]] = []

    async def start(self) -> None:
        """Start the background flush task."""
        if self._running:
            logger.warning("StateChangeLogger already running")
            return

        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info("StateChangeLogger started")

    async def stop(self) -> None:
        """Stop the background flush task and flush remaining items."""
        if not self._running:
            return

        self._running = False

        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Final flush
        await self._flush_to_db()
        logger.info("StateChangeLogger stopped")

    async def log_change(
        self,
        okx_uid: str,
        symbol: str,
        change_type: str,
        session_id: Optional[int] = None,
        previous_state: Optional[Dict[str, Any]] = None,
        new_state: Optional[Dict[str, Any]] = None,
        price: Optional[float] = None,
        pnl: Optional[float] = None,
        pnl_percent: Optional[float] = None,
        triggered_by: str = 'system',
        trigger_source: Optional[str] = None,
        extra_data: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        상태 변경 기록 (non-blocking).

        큐에 변경 기록을 추가하고 즉시 반환합니다.
        실제 DB 쓰기는 백그라운드에서 배치로 처리됩니다.

        Args:
            okx_uid: OKX 사용자 UID
            symbol: 거래 심볼
            change_type: 변경 유형
            session_id: 세션 ID (optional)
            previous_state: 변경 전 상태 (optional)
            new_state: 변경 후 상태 (optional)
            price: 가격 (optional)
            pnl: 손익 (optional)
            pnl_percent: 손익률 (optional)
            triggered_by: 트리거 주체
            trigger_source: 트리거 소스 상세
            extra_data: 추가 메타데이터 (optional)
        """
        try:
            change_record = {
                'change_time': datetime.utcnow(),
                'okx_uid': okx_uid,
                'session_id': session_id,
                'symbol': symbol,
                'change_type': change_type,
                'previous_state': previous_state,
                'new_state': new_state,
                'price_at_change': Decimal(str(price)) if price else None,
                'pnl_at_change': Decimal(str(pnl)) if pnl else None,
                'pnl_percent': Decimal(str(pnl_percent)) if pnl_percent else None,
                'triggered_by': triggered_by,
                'trigger_source': trigger_source,
                'extra_data': extra_data or {}
            }

            # Non-blocking put
            try:
                self._change_queue.put_nowait(change_record)
            except asyncio.QueueFull:
                logger.warning(
                    f"State change queue full, dropping oldest entry. "
                    f"Queue size: {self._change_queue.qsize()}"
                )
                # Remove oldest and add new
                try:
                    self._change_queue.get_nowait()
                    self._change_queue.put_nowait(change_record)
                except asyncio.QueueEmpty:
                    pass

        except Exception as e:
            logger.error(f"Failed to queue state change: {e}", exc_info=True)

    async def _flush_loop(self) -> None:
        """Background loop that flushes queue to database."""
        while self._running:
            try:
                await asyncio.sleep(self.FLUSH_INTERVAL)
                await self._flush_to_db()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Flush loop error: {e}", exc_info=True)

    async def _flush_to_db(self) -> None:
        """Batch write queued changes to PostgreSQL."""
        if self._change_queue.empty() and not self._retry_queue:
            return

        # Collect items from queue
        batch = []

        # First, add retry items
        if self._retry_queue:
            batch.extend(self._retry_queue[:self.BATCH_SIZE])
            self._retry_queue = self._retry_queue[self.BATCH_SIZE:]

        # Then add new items from queue
        remaining_capacity = self.BATCH_SIZE - len(batch)
        while not self._change_queue.empty() and len(batch) < self.BATCH_SIZE:
            try:
                batch.append(self._change_queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        if not batch:
            return

        try:
            async with get_transactional_session() as session:
                # Create model instances and add to session
                for record in batch:
                    state_change = HyperrsiStateChange(
                        change_time=record['change_time'],
                        okx_uid=record['okx_uid'],
                        session_id=record['session_id'],
                        symbol=record['symbol'],
                        change_type=record['change_type'],
                        previous_state=record['previous_state'],
                        new_state=record['new_state'],
                        price_at_change=record['price_at_change'],
                        pnl_at_change=record['pnl_at_change'],
                        pnl_percent=record['pnl_percent'],
                        triggered_by=record['triggered_by'],
                        trigger_source=record['trigger_source'],
                        extra_data=record['extra_data']
                    )
                    session.add(state_change)

            logger.debug(f"Flushed {len(batch)} state changes to PostgreSQL")

        except Exception as e:
            logger.error(f"Failed to flush state changes: {e}", exc_info=True)

            # Add failed items to retry queue
            for record in batch:
                record['_retry_count'] = record.get('_retry_count', 0) + 1
                if record['_retry_count'] <= self.MAX_RETRIES:
                    self._retry_queue.append(record)
                else:
                    logger.warning(
                        f"Dropping state change after {self.MAX_RETRIES} retries: "
                        f"okx_uid={record['okx_uid']}, type={record['change_type']}"
                    )

    def get_queue_size(self) -> int:
        """Get current queue size."""
        return self._change_queue.qsize()

    def get_retry_queue_size(self) -> int:
        """Get current retry queue size."""
        return len(self._retry_queue)

    @property
    def is_running(self) -> bool:
        """Check if logger is running."""
        return self._running


# Global singleton instance
_state_change_logger: Optional[StateChangeLogger] = None


def get_state_change_logger() -> StateChangeLogger:
    """Get singleton StateChangeLogger instance."""
    global _state_change_logger
    if _state_change_logger is None:
        _state_change_logger = StateChangeLogger()
    return _state_change_logger


async def start_state_change_logger() -> StateChangeLogger:
    """Start and return the state change logger."""
    logger_instance = get_state_change_logger()
    if not logger_instance.is_running:
        await logger_instance.start()
    return logger_instance


async def stop_state_change_logger() -> None:
    """Stop the state change logger."""
    global _state_change_logger
    if _state_change_logger is not None and _state_change_logger.is_running:
        await _state_change_logger.stop()
