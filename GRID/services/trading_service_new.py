"""
Trading Service - Migrated to New Infrastructure

Demonstrates:
- New exception handling
- Input validation
- Transaction management
- Structured logging
"""

import json
from pathlib import Path
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from GRID.dtos.symbol import AccessListDto
from GRID.repositories.symbol_repository_new import SymbolRepository
from shared.database.session import transactional_session
from shared.errors import (
    ConfigurationException,
    DatabaseException,
    ValidationException,
)
from shared.logging import get_logger
from shared.validation import sanitize_symbol

logger = get_logger(__name__)


class TradingAccessService:
    """
    Service for managing trading access lists (blacklist/whitelist).

    Migrated from file-based storage to database with new infrastructure.
    """

    def __init__(self, session: AsyncSession):
        """
        Initialize service with database session.

        Args:
            session: SQLAlchemy async session
        """
        self.session = session
        self.symbol_repo = SymbolRepository(session)

    async def get_blacklist(self, exchange_name: str, user_id: int) -> List[str]:
        """
        Get user's blacklisted symbols.

        Args:
            exchange_name: Exchange identifier
            user_id: User ID

        Returns:
            List of blacklisted symbols

        Example:
            >>> service = TradingAccessService(session)
            >>> blacklist = await service.get_blacklist("okx", 123)
        """
        logger.info(
            "Getting blacklist",
            extra={"exchange": exchange_name, "user_id": user_id}
        )

        return await self.symbol_repo.get_blacklist(exchange_name, user_id)

    async def get_whitelist(self, exchange_name: str, user_id: int) -> List[str]:
        """
        Get user's whitelisted symbols.

        Args:
            exchange_name: Exchange identifier
            user_id: User ID

        Returns:
            List of whitelisted symbols
        """
        logger.info(
            "Getting whitelist",
            extra={"exchange": exchange_name, "user_id": user_id}
        )
        return await self.symbol_repo.get_whitelist(exchange_name, user_id)

    async def get_access_list(
        self,
        exchange_name: str,
        user_id: int,
        list_type: str
    ) -> AccessListDto:
        """
        Get access list (blacklist or whitelist).

        Args:
            exchange_name: Exchange identifier
            user_id: User ID
            list_type: "blacklist" or "whitelist"

        Returns:
            AccessListDto with symbols

        Raises:
            ValidationException: Invalid list_type

        Example:
            >>> dto = await service.get_access_list("okx", 123, "blacklist")
            >>> print(dto.symbols)  # ['BTC/USDT', 'ETH/USDT']
        """
        if list_type not in ["blacklist", "whitelist"]:
            raise ValidationException(
                f"Invalid access list type: {list_type}",
                details={"valid_types": ["blacklist", "whitelist"]}
            )

        logger.info(
            "Getting access list",
            extra={
                "exchange": exchange_name,
                "user_id": user_id,
                "type": list_type
            }
        )

        if list_type == "blacklist":
            symbols = await self.get_blacklist(exchange_name, user_id)
        else:
            symbols = await self.get_whitelist(exchange_name, user_id)

        return AccessListDto(type=list_type, symbols=symbols, exchange_name=exchange_name, user_id=user_id)

    async def add_to_access_list(
        self,
        exchange_name: str,
        user_id: int,
        dto: AccessListDto
    ) -> int:
        """
        Add symbols to access list.

        Args:
            exchange_name: Exchange identifier
            user_id: User ID
            dto: Access list data with symbols to add

        Returns:
            Number of symbols added

        Raises:
            ValidationException: Invalid symbols or list type

        Example:
            >>> dto = AccessListDto(type="blacklist", symbols=["BTC/USDT"])
            >>> count = await service.add_to_access_list("okx", 123, dto)
        """
        if not dto.symbols:
            raise ValidationException(
                "No symbols provided to add",
                details={"dto": dto.dict()}
            )

        logger.info(
            "Adding symbols to access list",
            extra={
                "exchange": exchange_name,
                "user_id": user_id,
                "type": dto.type,
                "symbols": dto.symbols
            }
        )

        async with transactional_session(self.session) as tx_session:
            tx_repo = SymbolRepository(tx_session)

            if dto.type == "blacklist":
                count = await tx_repo.add_to_blacklist(
                    exchange_name, user_id, dto.symbols
                )
            elif dto.type == "whitelist":
                count = await tx_repo.add_to_whitelist(
                    exchange_name, user_id, dto.symbols
                )
            else:
                raise ValidationException(
                    f"Invalid access list type: {dto.type}",
                    details={"valid_types": ["blacklist", "whitelist"]}
                )

        logger.info(
            "Symbols added to access list",
            extra={
                "exchange": exchange_name,
                "user_id": user_id,
                "type": dto.type,
                "count": count
            }
        )

        return count

    async def remove_from_access_list(
        self,
        exchange_name: str,
        user_id: int,
        dto: AccessListDto
    ) -> int:
        """
        Remove symbols from access list.

        Args:
            exchange_name: Exchange identifier
            user_id: User ID
            dto: Access list data with symbols to remove

        Returns:
            Number of symbols removed

        Example:
            >>> dto = AccessListDto(type="blacklist", symbols=["BTC/USDT"])
            >>> count = await service.remove_from_access_list("okx", 123, dto)
        """
        if not dto.symbols:
            raise ValidationException(
                "No symbols provided to remove",
                details={"dto": dto.dict()}
            )

        logger.info(
            "Removing symbols from access list",
            extra={
                "exchange": exchange_name,
                "user_id": user_id,
                "type": dto.type,
                "symbols": dto.symbols
            }
        )

        count: int
        async with transactional_session(self.session) as tx_session:
            tx_repo = SymbolRepository(tx_session)

            if dto.type == "blacklist":
                # TODO: Implement remove_from_blacklist in SymbolRepository
                count = 0  # Placeholder until method is implemented
                # count = await tx_repo.remove_from_blacklist(
                #     exchange_name, user_id, dto.symbols
                # )
            elif dto.type == "whitelist":
                # TODO: Implement whitelist methods in repository
                # count = await tx_repo.remove_from_whitelist(
                #     exchange_name, user_id, dto.symbols
                # )
                count = 0
            else:
                raise ValidationException(
                    f"Invalid access list type: {dto.type}",
                    details={"valid_types": ["blacklist", "whitelist"]}
                )

        logger.info(
            "Symbols removed from access list",
            extra={
                "exchange": exchange_name,
                "user_id": user_id,
                "type": dto.type,
                "count": count
            }
        )

        return count

    async def update_access_list(
        self,
        exchange_name: str,
        user_id: int,
        dto: AccessListDto,
        append: bool = False
    ) -> int:
        """
        Update access list (replace or append).

        Args:
            exchange_name: Exchange identifier
            user_id: User ID
            dto: Access list data
            append: If True, append to existing list. If False, replace.

        Returns:
            Number of symbols in final list

        Example:
            >>> dto = AccessListDto(type="blacklist", symbols=["BTC/USDT", "ETH/USDT"])
            >>> count = await service.update_access_list("okx", 123, dto, append=False)
        """
        if append:
            return await self.add_to_access_list(exchange_name, user_id, dto)
        else:
            # Replace: remove all, then add new
            async with transactional_session(self.session) as tx_session:
                tx_repo = SymbolRepository(tx_session)

                # Get current list
                if dto.type == "blacklist":
                    current = await tx_repo.get_blacklist(exchange_name, user_id)
                else:
                    current = await tx_repo.get_whitelist(exchange_name, user_id)

                # Remove all current symbols
                if current:
                    remove_dto = AccessListDto(type=dto.type, symbols=current, exchange_name=exchange_name, user_id=user_id)
                    await self.remove_from_access_list(exchange_name, user_id, remove_dto)

                # Add new symbols
                return await self.add_to_access_list(exchange_name, user_id, dto)


# Legacy file-based functions (deprecated - for backward compatibility only)

def get_list_from_file(file_name: str) -> List[str]:
    """
    DEPRECATED: Use TradingAccessService instead.

    Get list from JSON file.
    """
    logger.warning(
        "Using deprecated file-based access list",
        extra={"file_name": file_name}
    )

    try:
        file_path = Path(file_name)
        if not file_path.exists():
            return []

        with open(file_path, 'r') as file:
            result: List[str] = json.load(file)
            return result

    except FileNotFoundError:
        logger.warning(f"File not found: {file_name}")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in file {file_name}: {e}")
        raise ConfigurationException(f"Invalid JSON file: {file_name}")
    except Exception as e:
        logger.error(f"Error reading file {file_name}: {e}")
        raise ConfigurationException(f"Failed to read file: {file_name}")


def update_file(file_name: str, new_items: List[str], append: bool = False) -> None:
    """
    DEPRECATED: Use TradingAccessService instead.

    Update list in JSON file.
    """
    logger.warning(
        "Using deprecated file-based access list update",
        extra={"file_name": file_name, "append": append}
    )

    items = get_list_from_file(file_name) if append else []
    updated_items = list(set(items + new_items))

    try:
        file_path = Path(file_name)
        with open(file_path, 'w') as file:
            json.dump(updated_items, file, indent=2)
    except Exception as e:
        logger.error(f"Error writing file {file_name}: {e}")
        raise ConfigurationException(f"Failed to write file: {file_name}")


def remove_items_from_file(file_name: str, items_to_remove: List[str]) -> None:
    """
    DEPRECATED: Use TradingAccessService instead.

    Remove items from JSON file.
    """
    logger.warning(
        "Using deprecated file-based access list removal",
        extra={"file_name": file_name}
    )

    items = get_list_from_file(file_name)
    updated_items = [item for item in items if item not in items_to_remove]
    update_file(file_name, updated_items, append=False)
