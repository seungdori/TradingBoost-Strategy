"""
GRID Trading Data Operations - PostgreSQL Version

All functions are re-exported from trading_data_service_pg for backward compatibility.
"""

import time

from GRID.services.trading_data_service_pg import (
    ensure_database_exists,
    create_database,
    update_entry_data,
    update_tp_data,
    update_sl_data,
    save_win_rates_to_db,
)

# =============================================================================
# PostgreSQL Re-exports for Backward Compatibility
# =============================================================================

# Functions are imported directly above


# Legacy function (deprecated - user authentication moved to PostgreSQL)
async def create_user_table_if_not_exists():
    """Deprecated - User authentication is now handled by PostgreSQL"""
    pass