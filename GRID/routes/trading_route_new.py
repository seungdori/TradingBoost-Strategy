"""
Trading Routes - Migrated to New Infrastructure

Demonstrates:
- Input validation with Pydantic
- Dependency injection
- Structured exception handling
- Structured logging
"""

from typing import List

from fastapi import APIRouter, Body, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from GRID.dtos.symbol import AccessListDto
from GRID.services.trading_service_new import TradingAccessService
from shared.database.session import get_db
from shared.dtos.response import ResponseDto
from shared.errors import DatabaseException, ValidationException
from shared.logging import get_logger
from shared.validation import sanitize_symbol

logger = get_logger(__name__)
router = APIRouter(prefix="/trading", tags=["trading"])


# ============================================================================
# Dependency Injection
# ============================================================================


async def get_trading_access_service(
    db: AsyncSession = Depends(get_db)
) -> TradingAccessService:
    """
    Create trading access service instance.

    This is a factory dependency that provides service with database session.
    """
    return TradingAccessService(db)


# ============================================================================
# Access List Routes (Migrated)
# ============================================================================


@router.get(
    "/blacklist/{exchange_name}/{user_id}",
    response_model=ResponseDto[List[str]]
)
async def get_blacklist(
    exchange_name: str = Path(..., description="Exchange name (okx, binance, etc.)"),
    user_id: int = Path(..., gt=0, description="User ID"),
    service: TradingAccessService = Depends(get_trading_access_service)
) -> ResponseDto[List[str]]:
    """
    Get user's blacklisted symbols.

    Migrated from direct database access to service layer.

    Args:
        exchange_name: Exchange identifier
        user_id: User ID
        service: Trading access service (injected)

    Returns:
        ResponseDto with list of blacklisted symbols

    Example:
        ```bash
        curl "http://localhost:8012/trading/blacklist/okx/123"
        ```
    """
    logger.info(
        "Getting blacklist",
        extra={"exchange": exchange_name, "user_id": user_id}
    )

    try:
        symbols = await service.get_blacklist(exchange_name, user_id)

        logger.info(
            "Blacklist retrieved",
            extra={
                "exchange": exchange_name,
                "user_id": user_id,
                "count": len(symbols)
            }
        )

        return ResponseDto[List[str]](
            success=True,
            message="Successfully retrieved blacklist",
            data=symbols
        )

    except Exception as e:
        logger.error(
            "Failed to get blacklist",
            exc_info=True,
            extra={"exchange": exchange_name, "user_id": user_id}
        )
        # Exception is automatically handled by exception handlers
        raise


@router.get(
    "/whitelist/{exchange_name}/{user_id}",
    response_model=ResponseDto[List[str]]
)
async def get_whitelist(
    exchange_name: str = Path(...),
    user_id: int = Path(..., gt=0),
    service: TradingAccessService = Depends(get_trading_access_service)
) -> ResponseDto[List[str]]:
    """
    Get user's whitelisted symbols.

    Args:
        exchange_name: Exchange identifier
        user_id: User ID
        service: Trading access service (injected)

    Returns:
        ResponseDto with list of whitelisted symbols
    """
    logger.info(
        "Getting whitelist",
        extra={"exchange": exchange_name, "user_id": user_id}
    )

    symbols = await service.get_whitelist(exchange_name, user_id)

    return ResponseDto[List[str]](
        success=True,
        message="Successfully retrieved whitelist",
        data=symbols
    )


@router.post(
    "/blacklist/{exchange_name}/{user_id}/add",
    response_model=ResponseDto[int]
)
async def add_to_blacklist(
    exchange_name: str = Path(...),
    user_id: int = Path(..., gt=0),
    dto: AccessListDto = Body(...),
    service: TradingAccessService = Depends(get_trading_access_service)
) -> ResponseDto[int]:
    """
    Add symbols to blacklist.

    Args:
        exchange_name: Exchange identifier
        user_id: User ID
        dto: Access list DTO with symbols to add
        service: Trading access service (injected)

    Returns:
        ResponseDto with count of symbols added

    Raises:
        ValidationException: Invalid symbols or empty list
        DatabaseException: Database operation failed

    Example:
        ```bash
        curl -X POST "http://localhost:8012/trading/blacklist/okx/123/add" \\
             -H "Content-Type: application/json" \\
             -d '{
                   "type": "blacklist",
                   "symbols": ["BTC/USDT", "ETH/USDT"]
                 }'
        ```
    """
    logger.info(
        "Adding symbols to blacklist",
        extra={
            "exchange": exchange_name,
            "user_id": user_id,
            "symbols": dto.symbols
        }
    )

    # Validate DTO type matches endpoint
    if dto.type != "blacklist":
        raise ValidationException(
            f"Invalid access list type for blacklist endpoint: {dto.type}",
            details={"expected": "blacklist", "received": dto.type}
        )

    count = await service.add_to_access_list(exchange_name, user_id, dto)

    return ResponseDto[int](
        success=True,
        message=f"Successfully added {count} symbols to blacklist",
        data=count
    )


@router.post(
    "/blacklist/{exchange_name}/{user_id}/remove",
    response_model=ResponseDto[int]
)
async def remove_from_blacklist(
    exchange_name: str = Path(...),
    user_id: int = Path(..., gt=0),
    dto: AccessListDto = Body(...),
    service: TradingAccessService = Depends(get_trading_access_service)
) -> ResponseDto[int]:
    """
    Remove symbols from blacklist.

    Args:
        exchange_name: Exchange identifier
        user_id: User ID
        dto: Access list DTO with symbols to remove
        service: Trading access service (injected)

    Returns:
        ResponseDto with count of symbols removed

    Example:
        ```bash
        curl -X POST "http://localhost:8012/trading/blacklist/okx/123/remove" \\
             -H "Content-Type: application/json" \\
             -d '{
                   "type": "blacklist",
                   "symbols": ["BTC/USDT"]
                 }'
        ```
    """
    logger.info(
        "Removing symbols from blacklist",
        extra={
            "exchange": exchange_name,
            "user_id": user_id,
            "symbols": dto.symbols
        }
    )

    if dto.type != "blacklist":
        raise ValidationException(
            f"Invalid access list type for blacklist endpoint: {dto.type}"
        )

    count = await service.remove_from_access_list(exchange_name, user_id, dto)

    return ResponseDto[int](
        success=True,
        message=f"Successfully removed {count} symbols from blacklist",
        data=count
    )


@router.post(
    "/blacklist/{exchange_name}/{user_id}/update",
    response_model=ResponseDto[int]
)
async def update_blacklist(
    exchange_name: str = Path(...),
    user_id: int = Path(..., gt=0),
    dto: AccessListDto = Body(...),
    append: bool = Query(False, description="Append to existing list (default: replace)"),
    service: TradingAccessService = Depends(get_trading_access_service)
) -> ResponseDto[int]:
    """
    Update blacklist (replace or append).

    Args:
        exchange_name: Exchange identifier
        user_id: User ID
        dto: Access list DTO with symbols
        append: If True, append to existing list. If False, replace.
        service: Trading access service (injected)

    Returns:
        ResponseDto with count of symbols in final list

    Example (replace):
        ```bash
        curl -X POST "http://localhost:8012/trading/blacklist/okx/123/update?append=false" \\
             -H "Content-Type: application/json" \\
             -d '{
                   "type": "blacklist",
                   "symbols": ["BTC/USDT", "ETH/USDT"]
                 }'
        ```

    Example (append):
        ```bash
        curl -X POST "http://localhost:8012/trading/blacklist/okx/123/update?append=true" \\
             -H "Content-Type: application/json" \\
             -d '{
                   "type": "blacklist",
                   "symbols": ["SOL/USDT"]
                 }'
        ```
    """
    logger.info(
        "Updating blacklist",
        extra={
            "exchange": exchange_name,
            "user_id": user_id,
            "symbols": dto.symbols,
            "append": append
        }
    )

    if dto.type != "blacklist":
        raise ValidationException(
            f"Invalid access list type for blacklist endpoint: {dto.type}"
        )

    count = await service.update_access_list(exchange_name, user_id, dto, append=append)

    action = "appended to" if append else "replaced"
    return ResponseDto[int](
        success=True,
        message=f"Successfully {action} blacklist with {len(dto.symbols)} symbols",
        data=count
    )


# ============================================================================
# Migration Notes
# ============================================================================

"""
Migration Checklist:

2. ✅ Use dependency injection for database session
3. ✅ Add input validation (Pydantic + sanitizers)
4. ✅ Implement structured exception handling
5. ✅ Add structured logging with context
6. ✅ Use service layer for business logic
7. ✅ Return ResponseDto for consistent API responses
8. [ ] Add database models for Blacklist/Whitelist tables
9. [ ] Implement actual SQLAlchemy queries in repository
10. [ ] Add unit tests with mocked dependencies

Next steps:
- Create SQLAlchemy models for blacklist/whitelist
- Migrate remaining trading routes
- Add integration tests
- Update frontend to handle new response format
"""
