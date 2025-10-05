from GRID.infra import database
from GRID.database import redis_database
from GRID.database import user_database

# services/db_service.py 수정
async def init_database(exchange_names):
    for exchange_name in exchange_names:
        try:
            await redis_database.initialize_database(exchange_name)
            await user_database.initialize_database(exchange_name)
        except Exception as e:
            print(f"Error initializing database for {exchange_name}: {e}")
    print('Databases initialized')