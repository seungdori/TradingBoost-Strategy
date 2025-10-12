"""
AI Search Repository - Migrated to New Infrastructure

Manages AI search progress tracking with structured logging.
"""

from GRID.dtos.ai_search import AiSearchProgress
from GRID.infra.ai_search_progress import ai_search_progress_store
from shared.errors import DatabaseException, ValidationException
from shared.logging import get_logger

logger = get_logger(__name__)


def get_progress(exchange_name: str, enter_strategy: str) -> AiSearchProgress:
    """
    Get AI search progress for exchange and strategy.

    Args:
        exchange_name: Exchange identifier
        enter_strategy: Entry strategy name

    Returns:
        AiSearchProgress DTO with current progress

    Raises:
        ValidationException: Invalid parameters
        DatabaseException: Storage operation failed

    Example:
        >>> progress = get_progress("okx", "RSI_DIVERGENCE")
        >>> print(progress.completed_symbol_count)  # 45
    """
    if not exchange_name or not isinstance(exchange_name, str):
        raise ValidationException(
            "Exchange name cannot be empty",
            details={"exchange_name": exchange_name}
        )

    if not enter_strategy or not isinstance(enter_strategy, str):
        raise ValidationException(
            "Enter strategy cannot be empty",
            details={"enter_strategy": enter_strategy}
        )

    try:
        logger.info(
            "Getting AI search progress",
            extra={
                "exchange": exchange_name,
                "enter_strategy": enter_strategy
            }
        )

        progress = ai_search_progress_store.get_progress(
            exchange_name=exchange_name,
            enter_strategy=enter_strategy
        )

        logger.info(
            "AI search progress retrieved",
            extra={
                "exchange": exchange_name,
                "enter_strategy": enter_strategy,
                "completed": progress.completed_symbol_count,
                "total": progress.total_symbol_count,
                "status": progress.status
            }
        )

        return progress

    except Exception as e:
        logger.error(
            "Failed to get AI search progress",
            exc_info=True,
            extra={
                "exchange": exchange_name,
                "enter_strategy": enter_strategy
            }
        )
        raise DatabaseException(
            f"Failed to get AI search progress",
            details={
                "exchange": exchange_name,
                "enter_strategy": enter_strategy,
                "error": str(e)
            }
        )


def update_progress(dto: AiSearchProgress) -> None:
    """
    Update AI search progress.

    Args:
        dto: AiSearchProgress DTO with updated data

    Raises:
        ValidationException: Invalid DTO data
        DatabaseException: Storage operation failed

    Example:
        >>> progress = AiSearchProgress(
        ...     exchange_name="okx",
        ...     enter_strategy="RSI_DIVERGENCE",
        ...     current_progress_symbol="BTC/USDT",
        ...     completed_symbol_count=46,
        ...     total_symbol_count=100,
        ...     status="running"
        ... )
        >>> update_progress(progress)
    """
    if not dto or not isinstance(dto, AiSearchProgress):
        raise ValidationException(
            "Invalid AI search progress DTO",
            details={"dto": dto}
        )

    try:
        logger.info(
            "Updating AI search progress",
            extra={
                "exchange": dto.exchange_name,
                "enter_strategy": dto.enter_strategy,
                "current_symbol": dto.current_progress_symbol,
                "completed": dto.completed_symbol_count,
                "total": dto.total_symbol_count,
                "status": dto.status
            }
        )

        ai_search_progress_store.update(
            exchange_name=dto.exchange_name,
            enter_strategy=dto.enter_strategy,
            current_progress_symbol=dto.current_progress_symbol,
            current_completed_symbol_count=dto.completed_symbol_count,
            current_total_symbol_count=dto.total_symbol_count,
            status=dto.status
        )

        logger.info(
            "AI search progress updated",
            extra={
                "exchange": dto.exchange_name,
                "enter_strategy": dto.enter_strategy,
                "completed": dto.completed_symbol_count,
                "total": dto.total_symbol_count
            }
        )

    except Exception as e:
        logger.error(
            "Failed to update AI search progress",
            exc_info=True,
            extra={
                "exchange": dto.exchange_name,
                "enter_strategy": dto.enter_strategy
            }
        )
        raise DatabaseException(
            f"Failed to update AI search progress",
            details={
                "exchange": dto.exchange_name,
                "enter_strategy": dto.enter_strategy,
                "error": str(e)
            }
        )
