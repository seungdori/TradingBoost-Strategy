"""
GRID Trading Data Operations - PostgreSQL Version

All functions are re-exported from trading_data_service_pg for backward compatibility.
"""

import time

from GRID.services import trading_data_service_pg

# =============================================================================
# PostgreSQL Re-exports for Backward Compatibility
# =============================================================================

# Re-export all functions from PostgreSQL service
ensure_database_exists = trading_data_service_pg.ensure_database_exists
create_database = trading_data_service_pg.create_database
update_entry_data = trading_data_service_pg.update_entry_data
update_tp_data = trading_data_service_pg.update_tp_data
update_sl_data = trading_data_service_pg.update_sl_data
save_win_rates_to_db = trading_data_service_pg.save_win_rates_to_db


# Legacy function (deprecated - user authentication moved to PostgreSQL)
async def create_user_table_if_not_exists():
    """Deprecated - User authentication is now handled by PostgreSQL"""
    pass