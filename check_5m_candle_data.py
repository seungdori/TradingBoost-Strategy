"""
5분봉 캔들 데이터 확인
"""

import asyncio
from datetime import datetime, timezone
from sqlalchemy import text
from shared.database.session import create_async_engine
from BACKTEST.config import get_shared_settings


async def check_5m_data():
    """5분봉 데이터 확인"""

    print("=" * 100)
    print("5분봉 캔들 데이터 확인")
    print("=" * 100)

    settings = get_shared_settings()
    db_url = f"postgresql+asyncpg://{settings.TIMESCALE_USER}:{settings.TIMESCALE_PASSWORD}@{settings.TIMESCALE_HOST}:{settings.TIMESCALE_PORT}/{settings.TIMESCALE_DATABASE}"
    engine = create_async_engine(db_url)

    # 20:40~21:00 구간 조회
    start_time = datetime(2025, 11, 16, 20, 40, 0, tzinfo=timezone.utc)
    end_time = datetime(2025, 11, 16, 21, 0, 0, tzinfo=timezone.utc)

    async with engine.begin() as conn:
        result = await conn.execute(
            text("""
                SELECT time, open, high, low, close, volume, bb_state
                FROM okx_candles_5m
                WHERE symbol = 'BTCUSDT'
                  AND time >= :start_time
                  AND time <= :end_time
                ORDER BY time ASC
            """),
            {'start_time': start_time, 'end_time': end_time}
        )

        rows = result.fetchall()

    print(f"\n📊 조회된 5분봉: {len(rows)}개")
    print(f"\n{'Time':<20} {'Open':>10} {'High':>10} {'Low':>10} {'Close':>10} {'Volume':>12} {'BB_State':>10}")
    print("-" * 100)

    for row in rows:
        time = str(row[0])[:19]
        open_price = float(row[1])
        high = float(row[2])
        low = float(row[3])
        close = float(row[4])
        volume = float(row[5])
        bb_state = row[6]

        print(f"{time:<20} {open_price:>10.2f} {high:>10.2f} {low:>10.2f} {close:>10.2f} {volume:>12.2f} {bb_state:>10}")


if __name__ == "__main__":
    asyncio.run(check_5m_data())
