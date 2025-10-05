"""
Trading Log Repository - Migrated to New Infrastructure

Manages trading message queue operations with structured logging.
"""

from typing import List

from shared.logging import get_logger

from GRID.strategies import strategy

logger = get_logger(__name__)


def get_trading_messages(exchange_name: str) -> List[str]:
    """
    Pop all messages from trading message queue.

    Args:
        exchange_name: Exchange identifier (used for future exchange-specific logs)

    Returns:
        List of trading messages (queue will be empty after this call)

    Example:
        >>> messages = get_trading_messages("okx")
        >>> print(messages)  # ['Order placed', 'Position closed']
    """
    logger.info(
        "Fetching trading messages",
        extra={"exchange": exchange_name}
    )

    message_queue = strategy.get_trading_message_queue()
    messages: List[str] = []

    # TODO: Implement exchange-specific logs
    # Future: Store messages in database for persistence

    while not message_queue.empty():
        messages.append(message_queue.get())

    logger.info(
        "Trading messages retrieved",
        extra={
            "exchange": exchange_name,
            "message_count": len(messages)
        }
    )

    return messages


def put_trading_message(message: str) -> None:
    """
    Add a message to trading message queue.

    Args:
        message: Trading message to add to queue

    Example:
        >>> put_trading_message("Long position opened at 50000")
    """
    logger.debug(
        "Adding trading message",
        extra={"message": message}
    )

    message_queue = strategy.get_trading_message_queue()
    message_queue.put(message)

    logger.debug("Trading message added to queue")
