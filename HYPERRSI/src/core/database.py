"""
Database compatibility module for HYPERRSI.

This module re-exports database functions from the shared infrastructure
to maintain backward compatibility with existing imports.

Usage:
    from HYPERRSI.src.core.database import init_db, get_redis_client, engine
"""

# Re-export database session functions from shared
from shared.database.session import (
    init_db,
    get_db,
    DatabaseConfig
)

# Re-export Redis functions from shared
from shared.database.redis import (
    get_redis,
    get_redis_binary,
    get_redis_connection,
    init_redis,
    close_redis
)

# Re-export Redis helper functions
from shared.database.redis_helper import (
    get_redis_client
)

# Re-export Base from local database_dir
from HYPERRSI.src.core.database_dir.base import Base

# Export engine as a callable that returns the engine
def get_engine():
    """Get database engine"""
    return DatabaseConfig.get_engine()

# For direct access pattern: from HYPERRSI.src.core.database import engine
# Note: This creates the engine at import time, which is the expected behavior
# for backward compatibility with synchronous import patterns
engine = DatabaseConfig.get_engine()

__all__ = [
    # Session/Database
    'init_db',
    'get_db',
    'engine',
    'get_engine',
    'Base',
    'DatabaseConfig',

    # Redis async
    'get_redis',
    'get_redis_binary',
    'get_redis_connection',
    'init_redis',
    'close_redis',

    # Redis sync
    'get_redis_client',
]
