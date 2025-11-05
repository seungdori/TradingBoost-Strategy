"""
Error Log Service

Centralized service for storing and retrieving error logs from database.
Works in parallel with file-based logging for comprehensive error tracking.
"""

import traceback as tb
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models import ErrorLog
from shared.logging import get_logger

logger = get_logger(__name__)


class ErrorLogService:
    """
    에러 로그 저장 및 조회 서비스.

    Features:
    - DB에 에러 로그 저장
    - 다양한 조건으로 에러 조회
    - 에러 통계 집계
    - 에러 해결 상태 관리
    """

    @staticmethod
    async def create_error_log(
        db: AsyncSession,
        error_type: str,
        error_message: str,
        severity: str = "ERROR",
        user_id: Optional[str] = None,
        telegram_id: Optional[int] = None,
        strategy_type: Optional[str] = None,
        module: Optional[str] = None,
        function: Optional[str] = None,
        traceback: Optional[str] = None,
        error_details: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ErrorLog:
        """
        Create a new error log entry in database.

        Args:
            db: Database session
            error_type: Error type/category (e.g., "APIError", "ValidationError")
            error_message: Error message
            severity: Severity level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            user_id: User ID (okx_uid or user_id)
            telegram_id: Telegram user ID
            strategy_type: Strategy type (HYPERRSI, GRID)
            module: Module where error occurred
            function: Function where error occurred
            traceback: Stack trace
            error_details: Additional error details (JSON)
            metadata: Additional metadata (JSON)

        Returns:
            ErrorLog: Created error log entry
        """
        try:
            error_log = ErrorLog(
                timestamp=datetime.utcnow(),
                user_id=user_id,
                telegram_id=telegram_id,
                error_type=error_type,
                severity=severity,
                strategy_type=strategy_type,
                error_message=error_message,
                error_details=error_details,
                module=module,
                function=function,
                traceback=traceback,
                metadata=metadata,
                resolved=False
            )

            db.add(error_log)
            await db.commit()
            await db.refresh(error_log)

            logger.debug(f"Error log created: ID={error_log.id}, type={error_type}")
            return error_log

        except Exception as e:
            logger.error(f"Failed to create error log: {e}", exc_info=True)
            await db.rollback()
            raise

    @staticmethod
    async def log_exception(
        db: AsyncSession,
        exception: Exception,
        error_type: Optional[str] = None,
        user_id: Optional[str] = None,
        telegram_id: Optional[int] = None,
        strategy_type: Optional[str] = None,
        module: Optional[str] = None,
        function: Optional[str] = None,
        additional_details: Optional[Dict[str, Any]] = None,
    ) -> ErrorLog:
        """
        Log an exception to database.

        Convenience method that extracts information from exception object.

        Args:
            db: Database session
            exception: Exception object
            error_type: Error type (if None, uses exception class name)
            user_id: User ID
            telegram_id: Telegram user ID
            strategy_type: Strategy type
            module: Module name
            function: Function name
            additional_details: Additional error details

        Returns:
            ErrorLog: Created error log entry
        """
        if error_type is None:
            error_type = exception.__class__.__name__

        error_message = str(exception)
        traceback_str = ''.join(tb.format_exception(type(exception), exception, exception.__traceback__))

        return await ErrorLogService.create_error_log(
            db=db,
            error_type=error_type,
            error_message=error_message,
            severity="ERROR",
            user_id=user_id,
            telegram_id=telegram_id,
            strategy_type=strategy_type,
            module=module,
            function=function,
            traceback=traceback_str,
            error_details=additional_details
        )

    @staticmethod
    async def get_error_logs(
        db: AsyncSession,
        user_id: Optional[str] = None,
        telegram_id: Optional[int] = None,
        error_type: Optional[str] = None,
        severity: Optional[str] = None,
        strategy_type: Optional[str] = None,
        resolved: Optional[bool] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ErrorLog]:
        """
        Query error logs with filters.

        Args:
            db: Database session
            user_id: Filter by user ID
            telegram_id: Filter by telegram ID
            error_type: Filter by error type
            severity: Filter by severity
            strategy_type: Filter by strategy type
            resolved: Filter by resolution status
            start_time: Filter by start time
            end_time: Filter by end time
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of ErrorLog objects
        """
        try:
            query = select(ErrorLog)

            # Apply filters
            if user_id:
                query = query.where(ErrorLog.user_id == user_id)
            if telegram_id:
                query = query.where(ErrorLog.telegram_id == telegram_id)
            if error_type:
                query = query.where(ErrorLog.error_type == error_type)
            if severity:
                query = query.where(ErrorLog.severity == severity)
            if strategy_type:
                query = query.where(ErrorLog.strategy_type == strategy_type)
            if resolved is not None:
                query = query.where(ErrorLog.resolved == (1 if resolved else 0))
            if start_time:
                query = query.where(ErrorLog.timestamp >= start_time)
            if end_time:
                query = query.where(ErrorLog.timestamp <= end_time)

            # Order by timestamp descending (newest first)
            query = query.order_by(ErrorLog.timestamp.desc())

            # Apply pagination
            query = query.limit(limit).offset(offset)

            result = await db.execute(query)
            return list(result.scalars().all())

        except Exception as e:
            logger.error(f"Failed to query error logs: {e}", exc_info=True)
            raise

    @staticmethod
    async def get_error_statistics(
        db: AsyncSession,
        user_id: Optional[str] = None,
        strategy_type: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Get error statistics.

        Args:
            db: Database session
            user_id: Filter by user ID
            strategy_type: Filter by strategy type
            start_time: Start time for statistics
            end_time: End time for statistics

        Returns:
            Dictionary with error statistics
        """
        try:
            query = select(ErrorLog)

            # Apply filters
            if user_id:
                query = query.where(ErrorLog.user_id == user_id)
            if strategy_type:
                query = query.where(ErrorLog.strategy_type == strategy_type)
            if start_time:
                query = query.where(ErrorLog.timestamp >= start_time)
            if end_time:
                query = query.where(ErrorLog.timestamp <= end_time)

            # Total count
            total_query = select(func.count()).select_from(query.subquery())
            total_result = await db.execute(total_query)
            total_count = total_result.scalar()

            # Count by severity
            severity_query = (
                select(ErrorLog.severity, func.count(ErrorLog.id))
                .select_from(query.subquery())
                .group_by(ErrorLog.severity)
            )
            severity_result = await db.execute(severity_query)
            severity_counts = {row[0]: row[1] for row in severity_result.all()}

            # Count by error type
            type_query = (
                select(ErrorLog.error_type, func.count(ErrorLog.id))
                .select_from(query.subquery())
                .group_by(ErrorLog.error_type)
                .order_by(func.count(ErrorLog.id).desc())
                .limit(10)
            )
            type_result = await db.execute(type_query)
            type_counts = {row[0]: row[1] for row in type_result.all()}

            # Resolved vs unresolved
            resolved_query = (
                select(ErrorLog.resolved, func.count(ErrorLog.id))
                .select_from(query.subquery())
                .group_by(ErrorLog.resolved)
            )
            resolved_result = await db.execute(resolved_query)
            resolved_counts = {bool(row[0]): row[1] for row in resolved_result.all()}

            return {
                "total_errors": total_count,
                "by_severity": severity_counts,
                "by_type": type_counts,
                "resolved": resolved_counts.get(True, 0),
                "unresolved": resolved_counts.get(False, 0),
            }

        except Exception as e:
            logger.error(f"Failed to get error statistics: {e}", exc_info=True)
            raise

    @staticmethod
    async def mark_as_resolved(
        db: AsyncSession,
        error_log_id: int
    ) -> Optional[ErrorLog]:
        """
        Mark an error as resolved.

        Args:
            db: Database session
            error_log_id: Error log ID

        Returns:
            Updated ErrorLog or None if not found
        """
        try:
            query = select(ErrorLog).where(ErrorLog.id == error_log_id)
            result = await db.execute(query)
            error_log = result.scalar_one_or_none()

            if error_log:
                error_log.resolved = True
                error_log.resolved_at = datetime.utcnow()
                await db.commit()
                await db.refresh(error_log)
                logger.info(f"Error log {error_log_id} marked as resolved")

            return error_log

        except Exception as e:
            logger.error(f"Failed to mark error as resolved: {e}", exc_info=True)
            await db.rollback()
            raise

    @staticmethod
    async def delete_old_errors(
        db: AsyncSession,
        days: int = 90,
        strategy_type: Optional[str] = None
    ) -> int:
        """
        Delete error logs older than specified days.

        Args:
            db: Database session
            days: Number of days to keep (default: 90)
            strategy_type: Optional strategy type filter

        Returns:
            Number of deleted records
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)

            query = select(ErrorLog).where(ErrorLog.timestamp < cutoff_date)

            if strategy_type:
                query = query.where(ErrorLog.strategy_type == strategy_type)

            result = await db.execute(query)
            errors_to_delete = result.scalars().all()

            count = len(errors_to_delete)

            for error in errors_to_delete:
                await db.delete(error)

            await db.commit()

            logger.info(f"Deleted {count} error logs older than {days} days")
            return count

        except Exception as e:
            logger.error(f"Failed to delete old errors: {e}", exc_info=True)
            await db.rollback()
            raise
