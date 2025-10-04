import os

import aiosqlite

from shared.dtos.trading import TradingDataDto
from shared.utils import path_helper


async def fetch_db_prices(exchange_name: str, symbol: str) -> TradingDataDto | None:
    db_path = str(path_helper.logs_dir / 'trading_data' / f'{exchange_name}_entry_data.db')
    # db_path = f"logs/trading_data/{exchange_name}_entry_data.db" // Todo: remove
    if not os.path.exists(db_path):
        return None
    async with aiosqlite.connect(db_path) as conn:  # 비동기적으로 DB 연결 관리
        async with conn.cursor() as cursor:  # 비동기적으로 커서 관리
            await cursor.execute("SELECT tp1_price, tp2_price, tp3_price, sl_price FROM entry WHERE symbol = ?",
                                 (symbol,))
            row = await cursor.fetchone()  # 결과를 비동기적으로 가져옴

    if row:
        trading_data: TradingDataDto = TradingDataDto(
            symbol=symbol,
            long_tp1_price=row[0],
            long_tp2_price=row[1],
            long_tp3_price=row[2],
            long_sl_price=row[3]
        )
        return trading_data

    else:
        return None
