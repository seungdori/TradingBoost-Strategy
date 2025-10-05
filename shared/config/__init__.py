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

# Import settings from parent config.py file
import sys
import os
parent_dir = os.path.dirname(os.path.dirname(__file__))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Import from shared.config module (the .py file)
import importlib.util
config_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.py')
spec = importlib.util.spec_from_file_location("_config", config_file)
_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_config)

settings = _config.settings
Settings = _config.Settings
get_settings = _config.get_settings

# Export all variables from config.py
OKX_API_KEY = _config.OKX_API_KEY
OKX_SECRET_KEY = _config.OKX_SECRET_KEY
OKX_PASSPHRASE = _config.OKX_PASSPHRASE
TELEGRAM_BOT_TOKEN = _config.TELEGRAM_BOT_TOKEN
OWNER_ID = _config.OWNER_ID
DATABASE_URL = _config.DATABASE_URL
REDIS_URL = _config.REDIS_URL
REDIS_HOST = _config.REDIS_HOST
REDIS_PORT = _config.REDIS_PORT
REDIS_PASSWORD = _config.REDIS_PASSWORD

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
