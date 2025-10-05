from GRID.infra import database
from GRID.database import redis_database
from GRID.services import user_service_pg

# services/db_service.py - Updated to use PostgreSQL
async def init_database(exchange_names):
    for exchange_name in exchange_names:
        try:
            await redis_database.initialize_database(exchange_name)
            await user_service_pg.initialize_database(exchange_name)
        except Exception as e:
            print(f"Error initializing database for {exchange_name}: {e}")
    print('Databases initialized')