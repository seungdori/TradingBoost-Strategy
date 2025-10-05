"""Configuration module"""
from shared.config.logging import (
    setup_logger, get_logger, setup_json_logger, should_log, JSONFormatter
)
from shared.config.constants import (
    SUPPORTED_SYMBOLS,
    MESSAGE_QUEUE_KEY, MESSAGE_PROCESSING_FLAG,
    USER_SETTINGS_KEY, USER_RECENT_SYMBOLS_KEY,
    USER_POSITION_KEY, USER_ORDER_KEY,
    POSITION_KEY, ORDER_KEY,
    MONITOR_INTERVAL, ORDER_CHECK_INTERVAL,
    MAX_RESTART_ATTEMPTS, MAX_MEMORY_MB,
    MEMORY_CLEANUP_INTERVAL, CONNECTION_TIMEOUT, API_RATE_LIMIT,
    ORDER_STATUS_CACHE_TTL, DEFAULT_CACHE_TTL, USER_SETTINGS_TTL,
    LOG_INTERVAL_SECONDS, LOG_MAX_BYTES, LOG_BACKUP_COUNT,
    DEFAULT_USER_SETTINGS,
    ORDER_TYPES, VALID_ORDER_NAMES,
    POSITION_SIDES,
    REDIS_DB_DEFAULT, REDIS_DB_BROKER, REDIS_DB_BACKEND,
    MAX_RECENT_SYMBOLS
)

# Import unified settings from settings.py
from shared.config.settings import settings, get_settings, Settings

# Backward compatibility: Export individual config values
OKX_API_KEY = settings.OKX_API_KEY
OKX_SECRET_KEY = settings.OKX_SECRET_KEY
OKX_PASSPHRASE = settings.OKX_PASSPHRASE
TELEGRAM_BOT_TOKEN = settings.TELEGRAM_BOT_TOKEN
OWNER_ID = settings.OWNER_ID
DATABASE_URL = settings.DATABASE_URL
REDIS_URL = settings.REDIS_URL
REDIS_HOST = settings.REDIS_HOST
REDIS_PORT = settings.REDIS_PORT
REDIS_PASSWORD = settings.REDIS_PASSWORD

__all__ = [
    # Logging
    'setup_logger', 'get_logger', 'setup_json_logger', 'should_log', 'JSONFormatter',
    # Settings
    'settings', 'Settings', 'get_settings',
    # API Keys
    'OKX_API_KEY', 'OKX_SECRET_KEY', 'OKX_PASSPHRASE',
    'TELEGRAM_BOT_TOKEN', 'OWNER_ID',
    # Database
    'DATABASE_URL', 'REDIS_URL', 'REDIS_HOST', 'REDIS_PORT', 'REDIS_PASSWORD',
    # Constants - Symbols
    'SUPPORTED_SYMBOLS',
    # Constants - Redis Keys
    'MESSAGE_QUEUE_KEY', 'MESSAGE_PROCESSING_FLAG',
    'USER_SETTINGS_KEY', 'USER_RECENT_SYMBOLS_KEY',
    'USER_POSITION_KEY', 'USER_ORDER_KEY',
    'POSITION_KEY', 'ORDER_KEY',
    # Constants - Monitoring
    'MONITOR_INTERVAL', 'ORDER_CHECK_INTERVAL',
    'MAX_RESTART_ATTEMPTS', 'MAX_MEMORY_MB',
    'MEMORY_CLEANUP_INTERVAL', 'CONNECTION_TIMEOUT', 'API_RATE_LIMIT',
    # Constants - Cache
    'ORDER_STATUS_CACHE_TTL', 'DEFAULT_CACHE_TTL', 'USER_SETTINGS_TTL',
    # Constants - Logging
    'LOG_INTERVAL_SECONDS', 'LOG_MAX_BYTES', 'LOG_BACKUP_COUNT',
    # Constants - Defaults
    'DEFAULT_USER_SETTINGS',
    # Constants - Order Types
    'ORDER_TYPES', 'VALID_ORDER_NAMES',
    # Constants - Position
    'POSITION_SIDES',
    # Constants - Redis DB
    'REDIS_DB_DEFAULT', 'REDIS_DB_BROKER', 'REDIS_DB_BACKEND',
    # Constants - Symbols
    'MAX_RECENT_SYMBOLS'
]
