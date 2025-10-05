"""
Transaction Management Tests

Tests for shared/database/transactions.py including:
- Transactional context manager
- Deadlock retry logic
- Savepoint support
- Isolation levels
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, Mock, patch
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from shared.database.transactions import transactional, atomic, run_in_transaction
from shared.errors import DatabaseException


@pytest.fixture
def mock_session():
    """Create a mock AsyncSession"""
    session = AsyncMock(spec=AsyncSession)
    session.in_transaction.return_value = False
    session.begin_nested = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


class TestTransactionalContextManager:
    """Test transactional context manager"""

    @pytest.mark.asyncio
    async def test_successful_transaction(self, mock_session):
        """Test successful transaction commits"""
        async with transactional(mock_session) as tx:
            assert tx is mock_session

        mock_session.commit.assert_called_once()
        mock_session.rollback.assert_not_called()

    @pytest.mark.asyncio
    async def test_transaction_rollback_on_error(self, mock_session):
        """Test transaction rolls back on error"""
        with pytest.raises(ValueError):
            async with transactional(mock_session):
                raise ValueError("Test error")

        mock_session.rollback.assert_called_once()
        mock_session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_nested_transaction_with_savepoint(self, mock_session):
        """Test nested transaction uses savepoint"""
        mock_session.in_transaction.return_value = True

        async with transactional(mock_session):
            pass

        mock_session.begin_nested.assert_called_once()

    @pytest.mark.asyncio
    async def test_deadlock_retry_success(self, mock_session):
        """Test deadlock retry logic succeeds on retry"""
        # Simulate deadlock on first attempt, success on second
        call_count = 0

        async def commit_with_deadlock():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First attempt: deadlock
                error = DBAPIError("", "", orig=Mock(pgcode='40P01'))
                raise error
            # Second attempt: success
            return None

        mock_session.commit = commit_with_deadlock

        async with transactional(mock_session, retry_on_deadlock=True):
            pass

        assert call_count == 2  # One failure + one success

    @pytest.mark.asyncio
    async def test_deadlock_retry_max_attempts(self, mock_session):
        """Test deadlock retry fails after max attempts"""
        # Always raise deadlock error
        def commit_with_deadlock():
            error = DBAPIError("", "", orig=Mock(pgcode='40P01'))
            raise error

        mock_session.commit = AsyncMock(side_effect=commit_with_deadlock)

        with pytest.raises(DatabaseException) as exc_info:
            async with transactional(mock_session, retry_on_deadlock=True, max_retries=3):
                pass

        assert "deadlock" in str(exc_info.value).lower()
        # Should have tried 3 times
        assert mock_session.commit.call_count == 3

    @pytest.mark.asyncio
    async def test_non_deadlock_error_no_retry(self, mock_session):
        """Test non-deadlock errors are not retried"""
        mock_session.commit = AsyncMock(
            side_effect=DBAPIError("", "", orig=Mock(pgcode='23505'))  # Unique violation
        )

        with pytest.raises(DatabaseException):
            async with transactional(mock_session, retry_on_deadlock=True):
                pass

        # Should only try once
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_isolation_level_set(self, mock_session):
        """Test isolation level is set correctly"""
        mock_session.execute = AsyncMock()

        async with transactional(mock_session, isolation_level="SERIALIZABLE"):
            pass

        # Should execute SET TRANSACTION ISOLATION LEVEL
        call_args = mock_session.execute.call_args[0][0]
        assert "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE" in str(call_args)

    @pytest.mark.asyncio
    async def test_retry_disabled(self, mock_session):
        """Test retry can be disabled"""
        mock_session.commit = AsyncMock(
            side_effect=DBAPIError("", "", orig=Mock(pgcode='40P01'))
        )

        with pytest.raises(DatabaseException):
            async with transactional(mock_session, retry_on_deadlock=False):
                pass

        # Should only try once
        mock_session.commit.assert_called_once()


class TestAtomicHelper:
    """Test atomic() convenience function"""

    @pytest.mark.asyncio
    async def test_atomic_executes_callback(self, mock_session):
        """Test atomic executes callback and commits"""
        callback_executed = False

        async def callback(tx):
            nonlocal callback_executed
            callback_executed = True
            assert tx is mock_session

        result = await atomic(mock_session, callback)

        assert callback_executed
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_atomic_returns_callback_result(self, mock_session):
        """Test atomic returns callback result"""
        async def callback(tx):
            return "test_result"

        result = await atomic(mock_session, callback)

        assert result == "test_result"

    @pytest.mark.asyncio
    async def test_atomic_rollback_on_error(self, mock_session):
        """Test atomic rolls back on callback error"""
        async def callback(tx):
            raise ValueError("Test error")

        with pytest.raises(ValueError):
            await atomic(mock_session, callback)

        mock_session.rollback.assert_called_once()


class TestRunInTransaction:
    """Test run_in_transaction() wrapper"""

    @pytest.mark.asyncio
    async def test_run_in_transaction_executes(self, mock_session):
        """Test run_in_transaction executes operations"""
        result_list = []

        async def operation1(tx):
            result_list.append(1)

        async def operation2(tx):
            result_list.append(2)

        await run_in_transaction(mock_session, operation1, operation2)

        assert result_list == [1, 2]
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_in_transaction_rollback_on_error(self, mock_session):
        """Test run_in_transaction rolls back on error"""
        async def operation1(tx):
            pass

        async def operation2(tx):
            raise ValueError("Test error")

        with pytest.raises(ValueError):
            await run_in_transaction(mock_session, operation1, operation2)

        mock_session.rollback.assert_called_once()


class TestTransactionIntegration:
    """Integration tests with real session (requires database)"""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_real_transaction_commit(self):
        """Test real transaction with database (integration test)"""
        # This would require actual database connection
        # Marked with @pytest.mark.integration for optional execution
        pytest.skip("Requires database connection")

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_real_deadlock_retry(self):
        """Test deadlock retry with real database"""
        pytest.skip("Requires database connection and concurrent transactions")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
