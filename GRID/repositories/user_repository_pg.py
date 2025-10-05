"""
User Repository for PostgreSQL

Handles all database operations related to GRID users.
"""

import json
from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from GRID.models.user import User, TelegramID
from shared.logging import get_logger

logger = get_logger(__name__)


class UserRepositoryPG:
    """Repository for User model operations"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(
        self, user_id: int, exchange_name: str
    ) -> Optional[User]:
        """
        Get user by ID and exchange name.

        Args:
            user_id: User identifier
            exchange_name: Exchange name (e.g., 'okx', 'binance')

        Returns:
            User object or None if not found
        """
        stmt = select(User).where(
            User.user_id == user_id,
            User.exchange_name == exchange_name
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_by_exchange(self, exchange_name: str) -> List[User]:
        """
        Get all users for a specific exchange.

        Args:
            exchange_name: Exchange name

        Returns:
            List of User objects
        """
        stmt = select(User).where(User.exchange_name == exchange_name)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_running_users(self, exchange_name: str) -> List[User]:
        """
        Get all running users for a specific exchange.

        Args:
            exchange_name: Exchange name

        Returns:
            List of User objects where is_running=True
        """
        stmt = select(User).where(
            User.exchange_name == exchange_name,
            User.is_running == True
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, user_data: Dict[str, Any]) -> User:
        """
        Create a new user.

        Args:
            user_data: Dictionary containing user fields

        Returns:
            Created User object
        """
        user = User(**user_data)
        self.session.add(user)
        await self.session.flush()
        logger.info(f"Created user {user.user_id} for {user.exchange_name}")
        return user

    async def update(
        self, user_id: int, exchange_name: str, updates: Dict[str, Any]
    ) -> Optional[User]:
        """
        Update user fields.

        Args:
            user_id: User identifier
            exchange_name: Exchange name
            updates: Dictionary of fields to update

        Returns:
            Updated User object or None if not found
        """
        # Update timestamp
        updates["updated_at"] = datetime.utcnow()

        stmt = (
            update(User)
            .where(User.user_id == user_id, User.exchange_name == exchange_name)
            .values(**updates)
            .returning(User)
        )
        result = await self.session.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            logger.info(f"Updated user {user_id} for {exchange_name}")

        return user

    async def update_running_status(
        self, user_id: int, exchange_name: str, is_running: bool
    ) -> Optional[User]:
        """
        Update user's running status.

        Args:
            user_id: User identifier
            exchange_name: Exchange name
            is_running: Running status

        Returns:
            Updated User object
        """
        return await self.update(
            user_id, exchange_name, {"is_running": is_running}
        )

    async def add_task(
        self, user_id: int, exchange_name: str, task: str
    ) -> Optional[User]:
        """
        Add a task to user's task list.

        Args:
            user_id: User identifier
            exchange_name: Exchange name
            task: Task to add

        Returns:
            Updated User object
        """
        user = await self.get_by_id(user_id, exchange_name)
        if not user:
            return None

        tasks = json.loads(user.tasks)
        if task not in tasks:
            tasks.append(task)
            return await self.update(
                user_id, exchange_name, {"tasks": json.dumps(tasks)}
            )
        return user

    async def remove_task(
        self, user_id: int, exchange_name: str, task: str
    ) -> Optional[User]:
        """
        Remove a task from user's task list.

        Args:
            user_id: User identifier
            exchange_name: Exchange name
            task: Task to remove

        Returns:
            Updated User object
        """
        user = await self.get_by_id(user_id, exchange_name)
        if not user:
            return None

        tasks = json.loads(user.tasks)
        if task in tasks:
            tasks.remove(task)
            return await self.update(
                user_id, exchange_name, {"tasks": json.dumps(tasks)}
            )
        return user

    async def add_running_symbol(
        self, user_id: int, exchange_name: str, symbols: List[str] | str
    ) -> Optional[User]:
        """
        Add symbol(s) to running symbols list.

        Args:
            user_id: User identifier
            exchange_name: Exchange name
            symbols: Symbol or list of symbols to add

        Returns:
            Updated User object
        """
        user = await self.get_by_id(user_id, exchange_name)
        if not user:
            return None

        running_symbols = set(json.loads(user.running_symbols))

        if isinstance(symbols, list):
            running_symbols.update(symbols)
        else:
            running_symbols.add(symbols)

        return await self.update(
            user_id,
            exchange_name,
            {"running_symbols": json.dumps(list(running_symbols))}
        )

    async def remove_running_symbol(
        self, user_id: int, exchange_name: str, symbol: str
    ) -> Optional[User]:
        """
        Remove symbol from running symbols list.

        Args:
            user_id: User identifier
            exchange_name: Exchange name
            symbol: Symbol to remove

        Returns:
            Updated User object
        """
        user = await self.get_by_id(user_id, exchange_name)
        if not user:
            return None

        running_symbols = set(json.loads(user.running_symbols))
        running_symbols.discard(symbol)

        return await self.update(
            user_id,
            exchange_name,
            {"running_symbols": json.dumps(list(running_symbols))}
        )

    async def reset_user_data(
        self, user_id: int, exchange_name: str
    ) -> Optional[User]:
        """
        Reset user runtime data (tasks, running symbols, status).

        Args:
            user_id: User identifier
            exchange_name: Exchange name

        Returns:
            Updated User object
        """
        return await self.update(
            user_id,
            exchange_name,
            {
                "is_running": False,
                "tasks": "[]",
                "running_symbols": "[]",
            }
        )

    async def delete(self, user_id: int, exchange_name: str) -> bool:
        """
        Delete a user.

        Args:
            user_id: User identifier
            exchange_name: Exchange name

        Returns:
            True if deleted, False if not found
        """
        stmt = delete(User).where(
            User.user_id == user_id,
            User.exchange_name == exchange_name
        )
        result = await self.session.execute(stmt)

        if result.rowcount > 0:
            logger.info(f"Deleted user {user_id} for {exchange_name}")
            return True
        return False

    # Telegram ID operations
    async def get_telegram_id(
        self, user_id: int, exchange_name: str
    ) -> Optional[str]:
        """
        Get user's Telegram ID.

        Args:
            user_id: User identifier
            exchange_name: Exchange name

        Returns:
            Telegram ID string or None
        """
        stmt = select(TelegramID).where(
            TelegramID.user_id == user_id,
            TelegramID.exchange_name == exchange_name
        )
        result = await self.session.execute(stmt)
        telegram = result.scalar_one_or_none()
        return telegram.telegram_id if telegram else None

    async def update_telegram_id(
        self, user_id: int, exchange_name: str, telegram_id: str
    ) -> TelegramID:
        """
        Update or create Telegram ID for user.

        Args:
            user_id: User identifier
            exchange_name: Exchange name
            telegram_id: Telegram ID to set

        Returns:
            TelegramID object
        """
        stmt = select(TelegramID).where(
            TelegramID.user_id == user_id,
            TelegramID.exchange_name == exchange_name
        )
        result = await self.session.execute(stmt)
        telegram = result.scalar_one_or_none()

        if telegram:
            telegram.telegram_id = telegram_id
            telegram.updated_at = datetime.utcnow()
        else:
            telegram = TelegramID(
                user_id=user_id,
                exchange_name=exchange_name,
                telegram_id=telegram_id
            )
            self.session.add(telegram)

        await self.session.flush()
        logger.info(f"Updated Telegram ID for user {user_id}")
        return telegram
