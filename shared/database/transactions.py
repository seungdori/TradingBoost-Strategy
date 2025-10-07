"""
Transaction Management for TradingBoost-Strategy

Provides explicit transaction boundaries with:
- Automatic commit/rollback
- Deadlock retry with exponential backoff
- Savepoint support for nested transactions
- Isolation level control
- Structured logging
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator, TypeVar, Callable, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import DBAPIError
from sqlalchemy import text
from shared.logging import get_logger
from shared.errors.exceptions import DatabaseException
import asyncio

logger = get_logger(__name__)

T = TypeVar('T')


@asynccontextmanager
async def transactional(
    session: AsyncSession,
    *,
    retry_on_deadlock: bool = True,
    max_retries: int = 3,
    isolation_level: str | None = None
) -> AsyncGenerator[AsyncSession, None]:
    """
    Explicit transaction context manager with retry logic.

    Features:
    - Auto-commit on success, rollback on error
    - Deadlock retry with exponential backoff
    - Optional isolation level control
    - Structured logging with attempt tracking
    - Savepoint support for nested transactions

    Usage:
        async with transactional(session) as tx:
            order = await create_order(tx, data)
            await update_balance(tx, user_id, -order.amount)
            # Commits automatically on success

    Args:
        session: SQLAlchemy async session
        retry_on_deadlock: Retry on deadlock errors (40P01)
        max_retries: Maximum retry attempts (default: 3)
        isolation_level: Transaction isolation level (READ COMMITTED, REPEATABLE READ, SERIALIZABLE)

    Yields:
        AsyncSession: The session to use for database operations

    Raises:
        DatabaseException: On transaction failure after retries
    """
    attempt = 0
    last_error = None

    while attempt < max_retries:
        try:
            # Set isolation level if specified
            if isolation_level:
                await session.execute(text(f"SET TRANSACTION ISOLATION LEVEL {isolation_level}"))

            # Begin nested transaction if already in transaction (SAVEPOINT)
            if session.in_transaction():
                async with session.begin_nested():
                    yield session
            else:
                yield session

            # Commit transaction
            await session.commit()

            # Log retry success if this wasn't the first attempt
            if attempt > 0:
                logger.info(
                    "Transaction succeeded after retry",
                    extra={
                        "attempt": attempt + 1,
                        "max_retries": max_retries
                    }
                )

            return  # Success - exit function

        except DBAPIError as e:
            last_error = e
            await session.rollback()

            # Check if this is a deadlock error
            # PostgreSQL: 40P01 (deadlock_detected)
            is_deadlock = (
                e.orig is not None and
                hasattr(e.orig, 'pgcode') and
                e.orig.pgcode == '40P01'
            )

            # Determine if we should retry
            should_retry = (
                is_deadlock and
                retry_on_deadlock and
                attempt < max_retries - 1
            )

            if should_retry:
                attempt += 1
                # Exponential backoff: 0.2s, 0.4s, 0.8s
                backoff = 2 ** attempt * 0.1

                logger.warning(
                    "Deadlock detected, retrying transaction",
                    extra={
                        "attempt": attempt,
                        "max_retries": max_retries,
                        "backoff_seconds": backoff,
                        "error_code": e.orig.pgcode if e.orig is not None and hasattr(e.orig, 'pgcode') else None
                    }
                )

                await asyncio.sleep(backoff)
                continue

            # Not retryable or max retries exceeded
            logger.error(
                "Transaction failed",
                extra={
                    "error": str(e),
                    "is_deadlock": is_deadlock,
                    "attempt": attempt + 1,
                    "max_retries": max_retries
                },
                exc_info=True
            )

            raise DatabaseException(
                message="Transaction failed",
                details={
                    "error": str(e),
                    "attempts": attempt + 1,
                    "is_deadlock": is_deadlock,
                    "retryable": is_deadlock
                }
            )

        except Exception as e:
            await session.rollback()
            logger.error(
                "Unexpected error in transaction",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "attempt": attempt + 1
                },
                exc_info=True
            )

            raise DatabaseException(
                message="Transaction failed with unexpected error",
                details={
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            )


@asynccontextmanager
async def atomic(
    session: AsyncSession
) -> AsyncGenerator[AsyncSession, None]:
    """
    Simpler atomic transaction without retry logic.

    For simple operations that don't need deadlock retry.
    Use transactional() for complex multi-step operations.

    Usage:
        async with atomic(session) as tx:
            await repository.create(tx, data)

    Args:
        session: SQLAlchemy async session

    Yields:
        AsyncSession: The session to use for database operations

    Raises:
        Exception: Any exception from the transaction
    """
    try:
        if session.in_transaction():
            async with session.begin_nested():
                yield session
        else:
            yield session
            await session.commit()
    except Exception:
        await session.rollback()
        raise


async def run_in_transaction(
    session: AsyncSession,
    func: Callable[[AsyncSession], Any],
    *,
    retry_on_deadlock: bool = True,
    max_retries: int = 3
) -> Any:
    """
    Execute a function within a transaction.

    Convenience wrapper for transactional context manager.

    Usage:
        result = await run_in_transaction(
            session,
            lambda tx: create_order(tx, order_data),
            retry_on_deadlock=True
        )

    Args:
        session: SQLAlchemy async session
        func: Async function to execute (receives session as argument)
        retry_on_deadlock: Enable deadlock retry
        max_retries: Maximum retry attempts

    Returns:
        Result of the function execution

    Raises:
        DatabaseException: On transaction failure
    """
    async with transactional(
        session,
        retry_on_deadlock=retry_on_deadlock,
        max_retries=max_retries
    ) as tx:
        if asyncio.iscoroutinefunction(func):
            return await func(tx)
        else:
            return func(tx)


# Transaction isolation levels
class IsolationLevel:
    """Standard SQL transaction isolation levels"""
    READ_UNCOMMITTED = "READ UNCOMMITTED"
    READ_COMMITTED = "READ COMMITTED"  # PostgreSQL default
    REPEATABLE_READ = "REPEATABLE READ"
    SERIALIZABLE = "SERIALIZABLE"
