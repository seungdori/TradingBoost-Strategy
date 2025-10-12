"""Notification module"""
from shared.notifications.telegram import (
    MESSAGE_PROCESSING_FLAG,
    MESSAGE_QUEUE_KEY,
    MessageType,
    TelegramNotifier,
    enqueue_telegram_message,
    get_telegram_id,
    process_telegram_messages,
    send_telegram_message,
)

__all__ = [
    'TelegramNotifier',
    'MessageType',
    'get_telegram_id',
    'enqueue_telegram_message',
    'process_telegram_messages',
    'send_telegram_message',
    'MESSAGE_QUEUE_KEY',
    'MESSAGE_PROCESSING_FLAG',
]
